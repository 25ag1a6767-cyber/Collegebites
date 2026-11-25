import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.campus_ops import VoiceAssistantSession
from app.models.college import Canteen
from app.models.menu import Allergen, FoodItem, FoodItemAllergen, Ingredient, Recipe, RecipeIngredient
from app.models.order import Order
from app.services import campus_intelligence_service
from app.services.menu_service import compute_schedule_availability_map

SUPPORTED_LANGUAGES = {"en": "en-IN", "te": "te-IN"}

# Telugu script + Romanized Telugu + English keyword patterns
_UNAVAILABLE_PATTERNS = (
    "unavailable", "out of stock", "sold out", "not available", "finished",
    "లేవు", "అందుబాటులో లేవు", "అయిపోయాయి", "levu", "lekapothe", "unavailable items",
)
_INGREDIENT_PATTERNS = (
    "ingredient", "allergen", "what is in", "contains", "made of", "calories",
    "పదార్థాలు", "ఏమి ఉంటాయి", "అలెర్జీ", "padarthalu", "emi untayi",
)
_ORDER_STATUS_PATTERNS = (
    "my order", "order status", "where is my order", "track order", "ready", "pickup time",
    "estimated pickup", "where should i collect", "collect my order", "which counter",
    "నా ఆర్డర్", "ఆర్డర్ స్థితి", "ఎక్కడ తీసుకోవాలి", "ఎంత సమయం", "ఎప్పుడు రెడీ",
    "na order", "order ekkada", "entha time", "eppudu ready",
)
_COUNTER_WORKLOAD_PATTERNS = (
    "lower workload", "less crowd", "less busy", "fastest counter", "crowd", "which counter has",
    "తక్కువ రద్దీ", "ఏ కౌంటర్", "రద్దీ", "thakkuva raddi", "ye counter", "counter busy",
)
_INITIATE_ORDER_PATTERNS = (
    "order ", "buy ", "add ", "i want ", "get me ", "give me ", "book ",
    "ఆర్డర్ చేయి", "కావాలి", "ఇవ్వండి", "order chey", "kavali", "ivvandi",
)
_MENU_PATTERNS = (
    "menu", "available", "what food", "today's menu", "todays menu", "what can i eat", "items",
    "మెనూ", "అందుబాటులో", "ఏం ఉన్నాయి", "ఆహారం", "em unnai", "menu enti", "food items",
)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "ఒక": 1, "ఒకటి": 1, "రెండు": 2, "మూడు": 3, "నాలుగు": 4, "ఐదు": 5,
    "oka": 1, "okati": 1, "rendu": 2, "moodu": 3,
}


def _detect_language(transcript: str, requested_language: Optional[str]) -> str:
    if requested_language and requested_language.lower().startswith("te"):
        return "te"
    # Auto-detect Telugu Unicode block (\u0C00-\u0C7F)
    if any("\u0c00" <= ch <= "\u0c7f" for ch in transcript):
        return "te"
    low = transcript.lower()
    if any(k in low for k in ("em unnai", "kavali", "na order", "entha time", "thakkuva raddi", "menu enti", "levu")):
        return "te"
    return "en"


def _extract_quantity(text: str) -> int:
    m = re.search(r"\b([1-9])\b", text)
    if m:
        return int(m.group(1))
    low = text.lower()
    for word, num in _NUMBER_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low) or word in text:
            return num
    return 1


def _find_matching_items(items: list[FoodItem], transcript: str) -> list[FoodItem]:
    low = transcript.lower()
    matched = [it for it in items if it.name.lower() in low]
    if matched:
        return matched
    tokens = {t for t in re.findall(r"[a-zA-Z]{3,}", low)} - {
        "order", "want", "give", "menu", "food", "item", "items", "what", "are", "the", "for",
        "with", "ingredients", "available", "today", "please", "add", "buy", "get", "kavali",
    }
    if not tokens:
        return []
    scored: list[tuple[int, FoodItem]] = []
    for it in items:
        name_tokens = set(re.findall(r"[a-zA-Z]{3,}", it.name.lower()))
        overlap = len(tokens & name_tokens)
        if overlap > 0:
            scored.append((overlap, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:3]]


def process_voice_query(
    db: Session,
    *,
    transcript: str,
    language: Optional[str] = "en",
    canteen_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
) -> dict[str, Any]:
    clean_text = (transcript or "").strip()
    lang = _detect_language(clean_text, language)
    speech_lang = SUPPORTED_LANGUAGES.get(lang, "en-IN")

    if len(clean_text) < 2:
        msg = (
            "మీ మాట స్పష్టంగా వినిపించలేదు. దయచేసి మళ్ళీ చెప్పండి లేదా టెక్స్ట్ ద్వారా అడగండి."
            if lang == "te"
            else "I could not catch that clearly. Please repeat your question or type it in the text box."
        )
        sess = VoiceAssistantSession(
            user_id=user_id,
            guest_session_id=guest_session_id,
            canteen_id=canteen_id,
            language=lang,
            transcript_text=clean_text or "(empty)",
            detected_intent="unclear_input",
            response_text=msg,
            response_language=lang,
            confidence_score=Decimal("0.100"),
            status="clarification_needed",
        )
        db.add(sess)
        db.commit()
        return {
            "session_id": str(sess.id),
            "language": lang,
            "speech_lang": speech_lang,
            "detected_intent": "unclear_input",
            "status": "clarification_needed",
            "response_text": msg,
            "draft_order": None,
            "supporting_data": {},
        }

    low = clean_text.lower()
    active_canteens = list(
        db.scalars(select(Canteen).where(Canteen.is_active.is_(True)).order_by(Canteen.code.asc())).all()
    )
    canteen_map = {c.id: c for c in active_canteens}

    item_stmt = select(FoodItem).where(FoodItem.is_active.is_(True)).order_by(FoodItem.name.asc())
    if canteen_id:
        item_stmt = item_stmt.where(FoodItem.canteen_id == canteen_id)
    all_items = list(db.scalars(item_stmt).all())
    f_map = {it.id: it for it in all_items}
    sched_map = compute_schedule_availability_map(db, list(f_map.keys()), food_items_map=f_map) if f_map else {}

    available_items = [
        it for it in all_items if it.is_available and not it.insufficient_ingredients and sched_map.get(it.id, True)
    ]
    unavailable_items = [it for it in all_items if it not in available_items]

    intent = "unclear_input"
    status_val = "answered"
    confidence = Decimal("0.850")
    draft_order: Optional[dict[str, Any]] = None
    supporting_data: dict[str, Any] = {}
    response_text = ""

    # 1. Counter workload comparison
    if any(p in low or p in clean_text for p in _COUNTER_WORKLOAD_PATTERNS):
        intent = "lower_workload_counter"
        crowd = campus_intelligence_service.get_live_crowd_intelligence(db, days=7)
        best = crowd.get("recommended_lower_workload_counter")
        counters_summary = [
            {
                "counter_slot": c["counter_slot"],
                "canteen_name": c["canteen_name"],
                "active_orders": c["active_orders"],
                "workload_percent": c["workload_percent"],
                "activity_level": c["activity_level"],
                "estimated_wait_minutes": c["estimated_wait_minutes"],
            }
            for c in crowd["counters"]
        ]
        supporting_data = {"counters": counters_summary, "data_source": "order_based_estimate"}
        if best:
            if lang == "te":
                response_text = (
                    f"ప్రస్తుత ఆర్డర్ అంచనా ప్రకారం {best['canteen_name']} ({best['counter_slot']}) లో తక్కువ రద్దీ ఉంది "
                    f"({best['active_orders']} యాక్టివ్ ఆర్డర్లు, {best['workload_percent']}% లోడ్)."
                )
            else:
                response_text = (
                    f"Based on live order activity, {best['canteen_name']} ({best['counter_slot']}) currently has the lower workload "
                    f"with {best['active_orders']} active orders ({best['workload_percent']}% load)."
                )
        else:
            response_text = (
                "ప్రస్తుతం రెండు కౌంటర్లు మూసివేయబడ్డాయి లేదా పాజ్ చేయబడ్డాయి."
                if lang == "te"
                else "Both cafeteria counters are currently closed or paused."
            )

    # 2. Student's own order status / pickup time / pickup counter (STRICTLY scoped to user_id!)
    elif any(p in low or p in clean_text for p in _ORDER_STATUS_PATTERNS):
        intent = "my_order_status"
        if not user_id:
            status_val = "clarification_needed"
            response_text = (
                "మీ ఆర్డర్ స్థితిని చూడటానికి దయచేసి సైన్ ఇన్ చేయండి లేదా 'నా ఆర్డర్లు' పేజీలో మీ ఆర్డర్ నంబర్ ఉపయోగించండి."
                if lang == "te"
                else "Please sign in to check your personal order status, or open the Order Tracking page with your order number."
            )
        else:
            latest_ord = db.scalar(
                select(Order).where(Order.customer_id == user_id).order_by(Order.created_at.desc()).limit(1)
            )
            if not latest_ord:
                response_text = (
                    "మీ ఖాతాలో ప్రస్తుతం యాక్టివ్ ఆర్డర్లు ఏవీ లేవు."
                    if lang == "te"
                    else "You do not have any orders placed on your account yet."
                )
            else:
                c_obj = canteen_map.get(latest_ord.canteen_id) or db.get(Canteen, latest_ord.canteen_id)
                c_name = c_obj.name if c_obj else "Cafeteria Counter"
                pred = campus_intelligence_service.get_smart_pickup_prediction(
                    db, latest_ord.canteen_id, order_id=latest_ord.id
                )
                est_min = pred.get("predicted_wait_minutes")
                supporting_data = {
                    "order_number": latest_ord.order_number,
                    "status": latest_ord.status,
                    "payment_status": latest_ord.payment_status,
                    "canteen_name": c_name,
                    "estimated_wait_minutes": est_min,
                    "estimated_pickup_at": pred.get("predicted_pickup_at"),
                }
                if lang == "te":
                    wait_txt = f" అంచనా సమయం సుమారు {est_min} నిమిషాలు." if est_min and latest_ord.status not in ("READY", "COMPLETED") else ""
                    response_text = (
                        f"మీ ఆర్డర్ {latest_ord.order_number} ప్రస్తుతం '{latest_ord.status}' స్థితిలో ఉంది "
                        f"(పేమెంట్: {latest_ord.payment_status}). కలెక్షన్ కౌంటర్: {c_name}.{wait_txt}"
                    )
                else:
                    wait_txt = f" Estimated pickup wait is around {est_min} minutes (estimate only)." if est_min and latest_ord.status not in ("READY", "COMPLETED") else ""
                    response_text = (
                        f"Your order {latest_ord.order_number} is currently {latest_ord.status} "
                        f"(payment: {latest_ord.payment_status}). Collect it at {c_name}.{wait_txt}"
                    )

    # 3. Item ingredients & allergens
    elif any(p in low or p in clean_text for p in _INGREDIENT_PATTERNS):
        intent = "item_ingredients"
        matched = _find_matching_items(all_items, clean_text)
        if not matched:
            status_val = "clarification_needed"
            response_text = (
                "ఏ ఆహార పదార్థం యొక్క వివరాలను తెలుసుకోవాలనుకుంటున్నారో దాని పేరు చెప్పండి."
                if lang == "te"
                else "Please mention the specific menu item name so I can look up its recorded ingredients and allergens."
            )
        else:
            it = matched[0]
            rec = db.scalar(select(Recipe).where(Recipe.food_item_id == it.id))
            rec_ings: list[str] = []
            if rec:
                rec_ings = list(
                    db.scalars(
                        select(Ingredient.name)
                        .join(RecipeIngredient, RecipeIngredient.ingredient_id == Ingredient.id)
                        .where(RecipeIngredient.recipe_id == rec.id)
                    ).all()
                )
            allergens = list(
                db.scalars(
                    select(Allergen.name)
                    .join(FoodItemAllergen, FoodItemAllergen.allergen_id == Allergen.id)
                    .where(FoodItemAllergen.food_item_id == it.id)
                ).all()
            )
            ing_summary = ", ".join(rec_ings) if rec_ings else (it.ingredients_text or "")
            supporting_data = {
                "item_name": it.name,
                "ingredients": rec_ings,
                "ingredients_text": it.ingredients_text,
                "allergens": allergens,
            }
            if ing_summary:
                alg_txt = f" Allergens: {', '.join(allergens)}." if allergens else ""
                if lang == "te":
                    response_text = f"{it.name} లో నమోదైన పదార్థాలు: {ing_summary}.{alg_txt}"
                else:
                    response_text = f"Recorded ingredients for {it.name}: {ing_summary}.{alg_txt}"
            else:
                response_text = (
                    f"{it.name} కోసం పదార్థాల వివరాలు ప్రస్తుతం నమోదు చేయబడలేదు."
                    if lang == "te"
                    else f"Detailed ingredient records are not currently listed for {it.name}."
                )

    # 4. Unavailable items
    elif any(p in low or p in clean_text for p in _UNAVAILABLE_PATTERNS):
        intent = "unavailable_items"
        names = [it.name for it in unavailable_items[:12]]
        supporting_data = {"unavailable_count": len(unavailable_items), "items": names}
        if not names:
            response_text = (
                "ప్రస్తుతం అన్ని యాక్టివ్ మెనూ ఐటమ్స్ అందుబాటులో ఉన్నాయి."
                if lang == "te"
                else "All active menu items are currently available."
            )
        else:
            joined = ", ".join(names)
            response_text = (
                f"ప్రస్తుతం అందుబాటులో లేని ఐటమ్స్ ({len(unavailable_items)}): {joined}."
                if lang == "te"
                else f"Currently unavailable items ({len(unavailable_items)}): {joined}."
            )

    # 5. Voice-initiated draft order (STRICTLY requires explicit UI confirmation & Razorpay payment!)
    elif any(p in low or p in clean_text for p in _INITIATE_ORDER_PATTERNS) and _find_matching_items(all_items, clean_text):
        intent = "initiate_order"
        matched = _find_matching_items(all_items, clean_text)
        it = matched[0]
        qty = _extract_quantity(clean_text)
        if it not in available_items:
            status_val = "answered"
            response_text = (
                f"క్షమించండి, {it.name} ప్రస్తుతం అందుబాటులో లేదు."
                if lang == "te"
                else f"Sorry, {it.name} is currently unavailable and cannot be ordered."
            )
        else:
            unit_price = Decimal(str(it.base_price))
            exact_total = (unit_price * qty).quantize(Decimal("0.01"))
            c_obj = canteen_map.get(it.canteen_id)
            draft_order = {
                "canteen_id": str(it.canteen_id),
                "canteen_name": c_obj.name if c_obj else "Cafeteria",
                "items": [
                    {
                        "food_item_id": str(it.id),
                        "item_name": it.name,
                        "quantity": qty,
                        "unit_price": str(unit_price),
                        "line_total": str(exact_total),
                    }
                ],
                "exact_total_amount": str(exact_total),
                "currency": "INR",
                "tax_amount": "0.00",
                "discount_amount": "0.00",
                "requires_explicit_confirmation": True,
                "payment_gateway": "razorpay",
                "payment_status": "NOT_SUBMITTED",
            }
            status_val = "draft_order_ready"
            if lang == "te":
                response_text = (
                    f"{qty} x {it.name} (మొత్తం ₹{exact_total}) డ్రాఫ్ట్ ఆర్డర్ సిద్ధంగా ఉంది. "
                    "దయచేసి వివరాలను పరిశీలించి కన్ఫర్మ్ చేసి Razorpay ద్వారా పేమెంట్ పూర్తి చేయండి."
                )
            else:
                response_text = (
                    f"Prepared draft order: {qty} x {it.name} from {draft_order['canteen_name']} for ₹{exact_total} "
                    "(exact listed price, zero extra tax/fees). Please review, explicitly confirm, and complete payment via Razorpay."
                )

    # 6. Available menu / today's menu
    elif any(p in low or p in clean_text for p in _MENU_PATTERNS):
        intent = "available_menu"
        top_avail = [
            {
                "food_item_id": str(it.id),
                "name": it.name,
                "price": str(it.base_price),
                "canteen_name": canteen_map[it.canteen_id].name if it.canteen_id in canteen_map else None,
            }
            for it in available_items[:12]
        ]
        supporting_data = {"available_count": len(available_items), "items": top_avail}
        if not top_avail:
            response_text = (
                "ప్రస్తుతం అందుబాటులో ఉన్న ఆహార పదార్థాలు ఏవీ లేవు."
                if lang == "te"
                else "No menu items are currently available for ordering."
            )
        else:
            preview = ", ".join(f"{x['name']} (₹{x['price']})" for x in top_avail[:6])
            response_text = (
                f"ప్రస్తుతం {len(available_items)} ఐటమ్స్ అందుబాటులో ఉన్నాయి. కొన్ని ముఖ్యమైనవి: {preview}."
                if lang == "te"
                else f"There are {len(available_items)} items currently available, including: {preview}."
            )
    else:
        intent = "unclear_input"
        status_val = "clarification_needed"
        confidence = Decimal("0.350")
        response_text = (
            "నేను మెనూ, అందుబాటులో లేని ఐటమ్స్, పదార్థాలు, కౌంటర్ రద్దీ, మీ ఆర్డర్ స్థితి లేదా కొత్త ఆర్డర్ డ్రాఫ్ట్ గురించి సహాయం చేయగలను. దయచేసి స్పష్టంగా అడగండి."
            if lang == "te"
            else "I can help with today's available menu, unavailable items, ingredients, counter workload, your order status, pickup time, or drafting an order. Please try asking one of those!"
        )

    sess = VoiceAssistantSession(
        user_id=user_id,
        guest_session_id=guest_session_id,
        canteen_id=canteen_id,
        language=lang,
        transcript_text=clean_text[:1000],
        detected_intent=intent,
        response_text=response_text,
        response_language=lang,
        draft_order_json=draft_order,
        confidence_score=confidence,
        status=status_val,
    )
    db.add(sess)
    db.commit()

    return {
        "session_id": str(sess.id),
        "language": lang,
        "speech_lang": speech_lang,
        "detected_intent": intent,
        "status": status_val,
        "confidence_score": float(confidence),
        "response_text": response_text,
        "draft_order": draft_order,
        "supporting_data": supporting_data,
        "privacy_notice": "Responses are strictly scoped to public menu/counter data and your own authenticated orders.",
    }


def get_voice_assistant_analytics(db: Session, *, days: int = 14) -> dict[str, Any]:
    lookback = max(1, min(int(days or 14), 90))
    since = datetime.now(timezone.utc) - timedelta(days=lookback)
    rows = list(
        db.scalars(
            select(VoiceAssistantSession)
            .where(VoiceAssistantSession.created_at >= since)
            .order_by(VoiceAssistantSession.created_at.desc())
            .limit(1000)
        ).all()
    )
    by_lang: dict[str, int] = {}
    by_intent: dict[str, int] = {}
    drafts = 0
    clarifications = 0
    for r in rows:
        by_lang[r.language] = by_lang.get(r.language, 0) + 1
        by_intent[r.detected_intent] = by_intent.get(r.detected_intent, 0) + 1
        if r.status == "draft_order_ready":
            drafts += 1
        if r.status == "clarification_needed":
            clarifications += 1
    total = len(rows)
    return {
        "lookback_days": lookback,
        "total_queries": total,
        "by_language": by_lang,
        "by_intent": sorted([{"intent": k, "count": v} for k, v in by_intent.items()], key=lambda x: x["count"], reverse=True),
        "draft_orders_initiated": drafts,
        "clarification_rate_percent": round((clarifications / total) * 100, 1) if total else 0.0,
        "supported_languages": ["en", "te"],
        "recent_sessions": [
            {
                "id": str(r.id),
                "language": r.language,
                "detected_intent": r.detected_intent,
                "status": r.status,
                "confidence_score": float(r.confidence_score),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows[:20]
        ],
    }

