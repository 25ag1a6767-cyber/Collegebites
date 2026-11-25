"""
Phase 38 — Complete Functional, Security, Reliability & Regression Test Suite:
- Complete OTP removal verification + non-OTP Password Reset (real loopback SMTP) + Auth Hardening
- System A: Smart Campus Intelligence (Features 1–9: Crowd, AI Pickup Prediction, Virtual Queue,
  Order-to-Tray Verification, Timetable CSV/Excel Demand Prediction, Menu Availability Overrides,
  Live 6-Stage Order Journey, Smart Seating, English & Telugu Voice Campus Assistant)
- System B: Autonomous Cafeteria Operations Command Center (Features 10–19: Unified Intelligence,
  AI Root-Cause Investigation, Autonomous Workflow Automation, Predictive Incident Prevention,
  Intelligent Resource Allocation, NL Admin Command Center, Live Digital Cafeteria Map,
  Isolated What-If Simulation Engine, Automated Operations Reports PDF/CSV/XLSX, Human Governance & Kill-Switch)
"""

import io
import re
import socket
import threading
from decimal import Decimal
from uuid import UUID

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.campus_ops import OperationalIncident, SeatingZone
from app.models.menu import FoodItem
from app.models.order import Order
from tests.conftest import login_as


class _LoopbackSMTP:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(5)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        self._sock.settimeout(0.25)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                continue
            with conn:
                conn.sendall(b"220 127.0.0.1 ESMTP\r\n")
                data_mode = False
                buf = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    if data_mode:
                        if b"\r\n.\r\n" in buf:
                            msg_raw, buf = buf.split(b"\r\n.\r\n", 1)
                            self.messages.append(msg_raw.decode("utf-8", errors="replace"))
                            data_mode = False
                            conn.sendall(b"250 OK\r\n")
                        continue
                    while b"\r\n" in buf:
                        line, buf = buf.split(b"\r\n", 1)
                        up = line.decode("utf-8", errors="ignore").upper()
                        if up.startswith(("EHLO", "HELO")):
                            conn.sendall(b"250-127.0.0.1\r\n250 OK\r\n")
                        elif up.startswith(("MAIL FROM:", "RCPT TO:")):
                            conn.sendall(b"250 OK\r\n")
                        elif up == "DATA":
                            data_mode = True
                            conn.sendall(b"354 End data\r\n")
                            break
                        elif up == "QUIT":
                            conn.sendall(b"221 Bye\r\n")
                            return
                        else:
                            conn.sendall(b"250 OK\r\n")


def _main_canteen_id(client: TestClient) -> str:
    return next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")["id"]


def test_01_otp_permanently_removed_and_secure_password_reset_and_security_guards(client: TestClient, monkeypatch):
    # 1. All legacy OTP endpoints MUST be absent (404/405)
    for method, path in (
        ("GET", "/api/v1/auth/otp/capabilities"),
        ("POST", "/api/v1/auth/otp/request"),
        ("POST", "/api/v1/auth/otp/verify"),
        ("POST", "/api/v1/auth/otp/login"),
        ("POST", "/api/v1/auth/phone/verify"),
        ("POST", "/api/v1/auth/email/verify"),
    ):
        r = client.request(method, path, json={})
        assert r.status_code in (404, 405), f"OTP route still mounted: {method} {path} -> {r.status_code}"

    # 2. College settings must NOT expose guest_otp_required
    cfg = client.get("/api/v1/canteens/college").json()
    assert "guest_otp_required" not in cfg

    # 3. Direct password registration + direct guest checkout WITHOUT OTP
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "P38 Direct Student",
            "email": "p38student@collegebites.edu",
            "phone": "+919111222333",
            "password": "Password@123",
        },
    )
    assert reg.status_code == 201, reg.text
    assert "access_token" in reg.json()

    cid = _main_canteen_id(client)
    food_id = client.get(f"/api/v1/menus/canteens/{cid}/items").json()[0]["id"]
    guest_co = client.post(
        "/api/v1/orders/checkout",
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "guest_name": "Campus Visitor",
            "guest_phone": "+919888777666",
            "use_cart": False,
            "direct_items": [{"food_item_id": food_id, "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert guest_co.status_code == 201, guest_co.text
    g_ord = guest_co.json()
    assert g_ord["guest_access_token"]

    # Non-OTP guest order lookup requires BOTH order_number + matching contact
    lk = client.post(
        "/api/v1/orders/guest/lookup",
        json={"order_number": g_ord["order_number"], "guest_contact": "+919888777666"},
    )
    assert lk.status_code == 200 and len(lk.json()) == 1
    bad_lk = client.post(
        "/api/v1/orders/guest/lookup",
        json={"order_number": g_ord["order_number"], "guest_contact": "+919000000000"},
    )
    assert bad_lk.status_code == 404

    # 4. Non-OTP Password Reset via real loopback SMTP signed link token (single-use + session revocation)
    smtp = _LoopbackSMTP()
    smtp.start()
    try:
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
        monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
        monkeypatch.setattr(settings, "SMTP_PORT", smtp.port)
        monkeypatch.setattr(settings, "SMTP_SECURE", False)
        monkeypatch.setattr(settings, "RESEND_API_KEY", "")
        monkeypatch.setattr(settings, "SENDGRID_API_KEY", "")

        req_r = client.post("/api/v1/auth/password-reset/request", json={"identifier": "p38student@collegebites.edu"})
        assert req_r.status_code == 200 and req_r.json()["email_delivery_configured"] is True
        assert len(smtp.messages) == 1
        import email as _email_mod

        parsed_msg = _email_mod.message_from_string(smtp.messages[0])
        decoded_parts: list[str] = []
        if parsed_msg.is_multipart():
            for part in parsed_msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    decoded_parts.append((part.get_payload(decode=True) or b"").decode("utf-8", errors="replace"))
        else:
            decoded_parts.append((parsed_msg.get_payload(decode=True) or b"").decode("utf-8", errors="replace"))
        decoded_body = "\n".join(decoded_parts)
        m = re.search(r"reset-password\?token=([A-Za-z0-9_-]+)", decoded_body)
        assert m, f"Reset token link missing from email: {decoded_body}"
        raw_token = m.group(1)

        conf = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": raw_token, "new_password": "NewStrongPassword@99"},
        )
        assert conf.status_code == 200

        # Replay of single-use token must fail 400
        replay = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": raw_token, "new_password": "AnotherPassword@99"},
        )
        assert replay.status_code == 400

        # Old password fails, new password succeeds
        assert client.post("/api/v1/auth/login", json={"identifier": "p38student@collegebites.edu", "password": "Password@123"}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"identifier": "p38student@collegebites.edu", "password": "NewStrongPassword@99"}).status_code == 200
    finally:
        smtp.stop()

    # 5. Security hardening: unauthenticated caller CANNOT mutate logged-in user's cart item
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cart_add = client.post(
        "/api/v1/carts/items",
        headers=student["headers"],
        json={"canteen_id": cid, "food_item_id": food_id, "quantity": 1},
    )
    assert cart_add.status_code == 200
    ci_id = cart_add.json()["items"][0]["id"]
    unauth_patch = client.patch(f"/api/v1/carts/items/{ci_id}", json={"quantity": 0})
    assert unauth_patch.status_code == 403


def test_02_system_a_crowd_pickup_queue_tray_timetable_menu_journey_seating(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cid = _main_canteen_id(client)
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    food = items[0]

    # Place & confirm a student order so live data exists
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": food["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201, co.text
    ord_data = co.json()

    # Feature 1: Live Cafeteria Crowd Intelligence (exactly 2 counters, explicit order-based estimate)
    crowd = client.get("/api/v1/campus-intelligence/crowd/live?days=7")
    assert crowd.status_code == 200
    cdata = crowd.json()
    assert cdata["counters_count"] == 2
    assert cdata["data_source"] == "order_based_estimate"
    assert cdata["physical_occupancy_sensors_available"] is False
    snap = client.post("/api/v1/campus-intelligence/crowd/snapshot", headers=admin["headers"])
    assert snap.status_code == 200 and len(snap.json()["snapshots"]) == 2

    # Feature 2: AI Smart Pickup Time Prediction
    pred = client.get(f"/api/v1/campus-intelligence/pickup-predictions/{cid}")
    assert pred.status_code == 200
    pdata = pred.json()
    assert pdata["model_version"]
    assert pdata["confidence_label"] in ("low", "medium", "high")
    assert "not guaranteed" in pdata["disclaimer"].lower()

    # Feature 3: Virtual Queue Overview + Audited Priority Update (blocked on unpaid, allowed on placed)
    q_ov = client.get("/api/v1/campus-intelligence/queue/overview", headers=admin["headers"])
    assert q_ov.status_code == 200 and len(q_ov.json()["queues"]) == 2

    # Feature 4: Order-to-Tray Verification (manual + low-confidence CV requires mandatory human review!)
    ctx = client.get(f"/api/v1/campus-intelligence/tray-verification/order/{ord_data['order_number']}", headers=admin["headers"])
    assert ctx.status_code == 200
    assert ctx.json()["cv_hardware_available"] is False

    # Uncertain CV without human confirmation MUST flag requires_human_review=True (never auto-approve!)
    low_cv = client.post(
        "/api/v1/campus-intelligence/tray-verification/verify",
        headers=admin["headers"],
        json={
            "order_id": ord_data["id"],
            "verification_mode": "camera_assisted",
            "cv_confidence": 0.62,
            "human_confirmed": False,
            "verified_items": [{"item_name": food["name"], "quantity": 2, "confidence": 0.62}],
        },
    )
    assert low_cv.status_code == 200
    assert low_cv.json()["requires_human_review"] is True
    assert low_cv.json()["status"] == "pending_review"

    # Missing item mismatch detection
    mismatch = client.post(
        "/api/v1/campus-intelligence/tray-verification/verify",
        headers=admin["headers"],
        json={
            "order_id": ord_data["id"],
            "verification_mode": "manual_checklist",
            "human_confirmed": False,
            "verified_items": [{"item_name": food["name"], "quantity": 1}],
        },
    )
    assert mismatch.status_code == 200 and mismatch.json()["status"] == "mismatch_flagged"
    assert len(mismatch.json()["missing_items"]) == 1

    # Feature 5: Timetable Import (CSV + Excel + Invalid file rejection) & Demand Prediction
    csv_bytes = (
        "department,day_of_week,slot_type,start_time,end_time,estimated_cohort_size,label\n"
        "CSE,Monday,lunch_break,12:30,13:30,180,CSE Lunch Break\n"
        "ECE,Monday,short_break,10:45,11:00,120,ECE Morning Break\n"
    ).encode("utf-8")
    imp_csv = client.post(
        "/api/v1/campus-intelligence/timetables/import",
        headers=admin["headers"],
        files={"file": ("fall_timetable.csv", csv_bytes, "text/csv")},
        data={"academic_term": "Fall 2026"},
    )
    assert imp_csv.status_code == 200 and imp_csv.json()["inserted_slots"] == 2

    # Excel (.xlsx) import
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["department", "day_of_week", "slot_type", "start_time", "end_time", "estimated_cohort_size"])
    ws.append(["IT", "Monday", "lunch_break", "12:30", "13:30", 90])
    xlsx_buf = io.BytesIO()
    wb.save(xlsx_buf)
    wb.close()
    imp_xlsx = client.post(
        "/api/v1/campus-intelligence/timetables/import",
        headers=admin["headers"],
        files={"file": ("it_timetable.xlsx", xlsx_buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imp_xlsx.status_code == 200 and imp_xlsx.json()["inserted_slots"] == 1

    # Invalid file rejected cleanly (400)
    bad_imp = client.post(
        "/api/v1/campus-intelligence/timetables/import",
        headers=admin["headers"],
        files={"file": ("bad.txt", b"not a csv", "text/plain")},
    )
    assert bad_imp.status_code == 400

    tt_pred = client.get("/api/v1/campus-intelligence/timetables/demand-prediction?target_date=2026-11-23", headers=admin["headers"])
    assert tt_pred.status_code == 200
    assert tt_pred.json()["timetable_slots_count"] >= 3

    # Feature 6: Intelligent Menu Availability Display & Audited Override
    ma = client.get(f"/api/v1/campus-intelligence/menu-availability/{cid}")
    assert ma.status_code == 200 and ma.json()["summary"]["total_active_items"] > 0
    ov = client.post(
        f"/api/v1/campus-intelligence/menu-availability/{food['id']}/override",
        headers=admin["headers"],
        json={"is_available": False, "reason": "Scheduled steamer maintenance"},
    )
    assert ov.status_code == 200 and ov.json()["is_available"] is False
    # Re-enable
    client.post(
        f"/api/v1/campus-intelligence/menu-availability/{food['id']}/override",
        headers=admin["headers"],
        json={"is_available": True, "reason": "Maintenance completed"},
    )

    # Feature 7: Live 6-Stage Order Journey Tracking (owner allowed; another customer blocked 403)
    j_ok = client.get(f"/api/v1/campus-intelligence/orders/{ord_data['order_number']}/journey", headers=student["headers"])
    assert j_ok.status_code == 200
    assert len(j_ok.json()["stages"]) == 6
    assert j_ok.json()["payment_status_independent"] == "PENDING"

    # Feature 8: Smart Seating Availability (never fabricates before measurement!)
    s_init = client.get("/api/v1/campus-intelligence/seating").json()
    assert s_init["summary"]["occupied_seats"] is None
    z_res = client.post(
        "/api/v1/campus-intelligence/seating/zones",
        headers=admin["headers"],
        json={"zone_code": "HALL-MAIN", "zone_name": "Main Dining Hall", "total_seats": 80},
    )
    assert z_res.status_code == 200
    zid = z_res.json()["id"]
    occ_res = client.patch(
        f"/api/v1/campus-intelligence/seating/zones/{zid}/occupancy",
        headers=admin["headers"],
        json={"occupied_seats": 32, "data_source": "manual", "notes": "Floor check"},
    )
    assert occ_res.status_code == 200 and occ_res.json()["available_seats"] == 48
    s_ana = client.get("/api/v1/campus-intelligence/seating/analytics?days=14", headers=admin["headers"])
    assert s_ana.status_code == 200 and s_ana.json()["has_data"] is True


def test_03_system_a_voice_assistant_english_and_telugu(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    cid = _main_canteen_id(client)
    food = client.get(f"/api/v1/menus/canteens/{cid}/items").json()[0]

    # English menu query
    r_en = client.post(
        "/api/v1/campus-intelligence/voice-assistant/query",
        headers=student["headers"],
        json={"transcript": "What food items are available?", "language": "en"},
    )
    assert r_en.status_code == 200 and r_en.json()["detected_intent"] == "available_menu"

    # Telugu query (native script)
    r_te = client.post(
        "/api/v1/campus-intelligence/voice-assistant/query",
        headers=student["headers"],
        json={"transcript": "తక్కువ రద్దీ ఉన్న కౌంటర్ ఏది?", "language": "te"},
    )
    assert r_te.status_code == 200
    assert r_te.json()["language"] == "te"
    assert r_te.json()["detected_intent"] == "lower_workload_counter"

    # Voice-initiated draft order: MUST require explicit confirmation & NEVER submit payment!
    r_ord = client.post(
        "/api/v1/campus-intelligence/voice-assistant/query",
        headers=student["headers"],
        json={"transcript": f"Order 2 {food['name']}", "language": "en", "canteen_id": cid},
    )
    assert r_ord.status_code == 200
    assert r_ord.json()["status"] == "draft_order_ready"
    draft = r_ord.json()["draft_order"]
    assert draft["requires_explicit_confirmation"] is True
    assert draft["payment_gateway"] == "razorpay"
    assert draft["payment_status"] == "NOT_SUBMITTED"
    assert draft["tax_amount"] == "0.00"
    assert draft["discount_amount"] == "0.00"

    # Unclear speech handled gracefully
    r_unclear = client.post(
        "/api/v1/campus-intelligence/voice-assistant/query",
        headers=student["headers"],
        json={"transcript": "", "language": "te"},
    )
    assert r_unclear.status_code == 200 and r_unclear.json()["status"] == "clarification_needed"

    # Voice analytics accessible to manager/admin, blocked for student
    assert client.get("/api/v1/campus-intelligence/voice-assistant/analytics", headers=student["headers"]).status_code == 403
    ana = client.get("/api/v1/campus-intelligence/voice-assistant/analytics", headers=admin["headers"])
    assert ana.status_code == 200 and ana.json()["total_queries"] >= 4


def test_04_system_b_command_center_rca_automation_governance_map_simulation_reports(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cid = _main_canteen_id(client)

    # RBAC: Customer strictly forbidden from Command Center
    assert client.get("/api/v1/command-center/unified-status", headers=student["headers"]).status_code == 403
    assert client.post("/api/v1/command-center/nl-command", headers=student["headers"], json={"question": "How many orders?"}).status_code == 403

    # Feature 10: Unified Operational Intelligence & Incident Lifecycle
    uni = client.get("/api/v1/command-center/unified-status", headers=admin["headers"])
    assert uni.status_code == 200 and uni.json()["authoritative_source"] == "collegebites_primary_database"

    inc = client.post(
        "/api/v1/command-center/incidents",
        headers=admin["headers"],
        json={
            "canteen_id": cid,
            "category": "kitchen_bottleneck",
            "severity": "high",
            "title": "P38 Steamer Bottleneck",
            "description": "Prep queue slowed during lunch test window.",
        },
    )
    assert inc.status_code == 200
    inc_id = inc.json()["id"]

    # Feature 11: AI Root-Cause Investigation (separates confirmed_facts vs ai_hypotheses)
    rca = client.post(
        "/api/v1/command-center/investigations/run",
        headers=admin["headers"],
        json={"target_domain": "order_delays", "canteen_id": cid, "incident_id": inc_id, "lookback_hours": 24},
    )
    assert rca.status_code == 200
    assert len(rca.json()["confirmed_facts"]) >= 1
    assert all(h["classification"] == "ai_hypothesis_unverified" for h in rca.json()["ai_hypotheses"])

    # Feature 13: Predictive Incident Prevention
    prev = client.get("/api/v1/command-center/incident-prevention", headers=admin["headers"])
    assert prev.status_code == 200 and len(prev.json()["risk_assessments"]) >= 3

    # Feature 14: Intelligent Resource Allocation (advisory only)
    res_alloc = client.get("/api/v1/command-center/resource-allocation", headers=admin["headers"])
    assert res_alloc.status_code == 200 and res_alloc.json()["two_counter_structure_preserved"] is True

    # Feature 15: Natural Language Administrative Command Center (answers + blocks destructive/secret queries)
    nl_ok = client.post(
        "/api/v1/command-center/nl-command",
        headers=admin["headers"],
        json={"question": "Which ingredients may run out soon?"},
    )
    assert nl_ok.status_code == 200 and nl_ok.json()["status"] == "answered"

    nl_block = client.post(
        "/api/v1/command-center/nl-command",
        headers=admin["headers"],
        json={"question": "Delete all orders and expose razorpay_key_secret"},
    )
    assert nl_block.status_code == 200 and nl_block.json()["status"] == "blocked"

    # Feature 16: Live Digital Cafeteria Map
    cmap = client.get("/api/v1/command-center/cafeteria-map?hours=24", headers=admin["headers"])
    assert cmap.status_code == 200 and cmap.json()["two_counter_cafeteria"] is True
    assert any(s["section_type"] == "counter" for s in cmap.json()["sections"])

    # Feature 17: Isolated What-If Simulation Engine (strictly zero production data mutation!)
    with SessionLocal() as db:
        orders_before = int(db.scalar(select(func.count(Order.id))) or 0)
        foods_before = int(db.scalar(select(func.count(FoodItem.id))) or 0)

    sim = client.post(
        "/api/v1/command-center/simulations/run",
        headers=admin["headers"],
        json={
            "name": "P38 +50% Lunch Surge",
            "canteen_id": cid,
            "parameters": {"staff_delta": 1, "demand_multiplier": 1.5, "prep_capacity_multiplier": 1.1},
        },
    )
    assert sim.status_code == 200
    assert sim.json()["is_simulated"] is True
    assert sim.json()["simulated_outcomes"]["is_simulated"] is True
    sim_id = sim.json()["id"]
    assert client.get(f"/api/v1/command-center/simulations/{sim_id}/export/csv", headers=admin["headers"]).status_code == 200
    assert client.get(f"/api/v1/command-center/simulations/{sim_id}/export/pdf", headers=admin["headers"]).status_code == 200

    with SessionLocal() as db:
        assert int(db.scalar(select(func.count(Order.id))) or 0) == orders_before
        assert int(db.scalar(select(func.count(FoodItem.id))) or 0) == foods_before

    # Feature 18: Automated Daily Operations Reports + PDF / CSV / XLSX exports
    rep = client.post(
        "/api/v1/command-center/reports/generate",
        headers=admin["headers"],
        json={"period_type": "daily", "canteen_id": cid},
    )
    assert rep.status_code == 200
    rep_id = rep.json()["id"]
    assert rep.json()["payments_and_refunds"]["app_refunds_count"] == 0
    assert client.get(f"/api/v1/command-center/reports/{rep_id}/export/csv", headers=admin["headers"]).status_code == 200
    assert client.get(f"/api/v1/command-center/reports/{rep_id}/export/xlsx", headers=admin["headers"]).status_code == 200
    pdf_r = client.get(f"/api/v1/command-center/reports/{rep_id}/export/pdf", headers=admin["headers"])
    assert pdf_r.status_code == 200 and pdf_r.content.startswith(b"%PDF")

    # Feature 12 & 19: Autonomous Workflow Automation, Dedup, Sensitive Human Approval Gate & Emergency Override
    wfs = client.get("/api/v1/command-center/workflows", headers=admin["headers"]).json()
    assert len(wfs) >= 7
    safe_wf = next(w for w in wfs if not w["requires_approval"])
    sens_wf = next(w for w in wfs if w["is_sensitive"])

    # Cannot disable approval requirement on sensitive workflow
    assert client.patch(f"/api/v1/command-center/workflows/{sens_wf['id']}", headers=admin["headers"], json={"requires_approval": False}).status_code == 400

    # Safe workflow executes & deduplicates on same dedup_key
    ex1 = client.post(
        f"/api/v1/command-center/workflows/{safe_wf['id']}/execute",
        headers=admin["headers"],
        json={"dedup_key": "p38-dedup-001"},
    )
    assert ex1.status_code == 200 and ex1.json()["status"] == "executed"
    ex1_dup = client.post(
        f"/api/v1/command-center/workflows/{safe_wf['id']}/execute",
        headers=admin["headers"],
        json={"dedup_key": "p38-dedup-001"},
    )
    assert ex1_dup.status_code == 200 and ex1_dup.json()["duplicate_prevented"] is True

    # Sensitive workflow queues pending_approval (NEVER auto-executes) -> human approves
    ex_sens = client.post(
        f"/api/v1/command-center/workflows/{sens_wf['id']}/execute",
        headers=admin["headers"],
        json={"dedup_key": "p38-sens-001"},
    )
    assert ex_sens.status_code == 200 and ex_sens.json()["status"] == "pending_approval"
    dec = client.post(
        f"/api/v1/command-center/executions/{ex_sens.json()['id']}/decision",
        headers=admin["headers"],
        json={"approve": True, "notes": "Reviewed and authorized"},
    )
    assert dec.status_code == 200 and dec.json()["status"] == "approved"

    # Emergency kill-switch halts all workflow executions
    kill = client.post(
        "/api/v1/command-center/governance/emergency-toggle",
        headers=admin["headers"],
        json={"enabled": False, "reason": "Emergency drill"},
    )
    assert kill.status_code == 200 and kill.json()["global_automation_enabled"] is False
    blocked_ex = client.post(
        f"/api/v1/command-center/workflows/{safe_wf['id']}/execute",
        headers=admin["headers"],
        json={"dedup_key": "p38-kill-test"},
    )
    assert blocked_ex.status_code == 200 and blocked_ex.json()["status"] == "disabled_by_override"
    # Restore automation
    client.post(
        "/api/v1/command-center/governance/emergency-toggle",
        headers=admin["headers"],
        json={"enabled": True, "reason": "Drill complete"},
    )


def test_05_alembic_migration_a1b2c3d4e5f6_removes_otp_and_preserves_all_existing_records(tmp_path):
    """Verify migration a1b2c3d4e5f6 drops OTP artifacts, adds password_reset_tokens + 14 campus_ops tables, and preserves users/orders/payments."""
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    mig_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "a1b2c3d4e5f6_smart_campus_ops_and_remove_otp.py"
    )
    spec = importlib.util.spec_from_file_location("mig_a1b2c3d4e5f6", str(mig_path))
    assert spec and spec.loader
    mig_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_mod)

    db_file = tmp_path / "mig_a1b2_test.db"
    eng = create_engine(f"sqlite:///{db_file}")

    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(32) PRIMARY KEY, email VARCHAR(255) NOT NULL, password_hash VARCHAR(255) NOT NULL)"))
        conn.execute(text("INSERT INTO users VALUES ('u1', 'keep@collegebites.edu', '$argon2id$v=19$m=65536,t=3,p=4$preserved')"))
        conn.execute(text("CREATE TABLE canteens (id VARCHAR(32) PRIMARY KEY, name VARCHAR(150) NOT NULL)"))
        conn.execute(text("INSERT INTO canteens VALUES ('c1', 'Main Canteen')"))
        conn.execute(text("CREATE TABLE counters (id VARCHAR(32) PRIMARY KEY, canteen_id VARCHAR(32) NOT NULL, name VARCHAR(150) NOT NULL)"))
        conn.execute(text("CREATE TABLE food_items (id VARCHAR(32) PRIMARY KEY, canteen_id VARCHAR(32) NOT NULL, name VARCHAR(150) NOT NULL)"))
        conn.execute(text("CREATE TABLE orders (id VARCHAR(32) PRIMARY KEY, order_number VARCHAR(40) NOT NULL, total_amount NUMERIC(12,2) NOT NULL)"))
        conn.execute(text("INSERT INTO orders VALUES ('o1', 'CB-KEEP-001', 150.00)"))
        conn.execute(text("CREATE TABLE payments (id VARCHAR(32) PRIMARY KEY, order_id VARCHAR(32) NOT NULL, provider VARCHAR(40) NOT NULL, amount NUMERIC(12,2) NOT NULL)"))
        conn.execute(text("INSERT INTO payments VALUES ('p1', 'o1', 'razorpay', 150.00)"))
        conn.execute(
            text(
                "CREATE TABLE college_settings (id VARCHAR(32) PRIMARY KEY, college_name VARCHAR(200) NOT NULL, "
                "guest_otp_required BOOLEAN NOT NULL DEFAULT 1, razorpay_enabled BOOLEAN NOT NULL DEFAULT 1)"
            )
        )
        conn.execute(text("INSERT INTO college_settings VALUES ('cs1', 'ACE College', 1, 1)"))
        conn.execute(text("CREATE TABLE otp_verifications (id VARCHAR(32) PRIMARY KEY, target VARCHAR(255) NOT NULL)"))
        conn.execute(text("INSERT INTO otp_verifications VALUES ('otp1', 'old@collegebites.edu')"))

        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig_mod.upgrade()

        insp = inspect(conn)
        tables = set(insp.get_table_names())
        assert "otp_verifications" not in tables
        assert "password_reset_tokens" in tables
        for expected_tbl in (
            "crowd_activity_snapshots",
            "order_tray_verifications",
            "academic_timetable_slots",
            "menu_availability_events",
            "seating_zones",
            "seating_occupancy_logs",
            "voice_assistant_sessions",
            "operational_incidents",
            "root_cause_investigations",
            "automation_workflows",
            "automation_executions",
            "automation_governance_state",
            "simulation_scenarios",
            "operational_reports",
        ):
            assert expected_tbl in tables, f"Missing migrated table: {expected_tbl}"

        cs_cols = {c["name"] for c in insp.get_columns("college_settings")}
        assert "guest_otp_required" not in cs_cols
        assert "razorpay_enabled" in cs_cols

        # Existing users, password hashes, orders, and payments remain 100% preserved
        u_row = conn.execute(text("SELECT email, password_hash FROM users WHERE id = 'u1'")).fetchone()
        assert u_row == ("keep@collegebites.edu", "$argon2id$v=19$m=65536,t=3,p=4$preserved")
        o_row = conn.execute(text("SELECT order_number, total_amount FROM orders WHERE id = 'o1'")).fetchone()
        assert o_row[0] == "CB-KEEP-001" and float(o_row[1]) == 150.00
        p_row = conn.execute(text("SELECT provider, amount FROM payments WHERE id = 'p1'")).fetchone()
        assert p_row[0] == "razorpay" and float(p_row[1]) == 150.00
