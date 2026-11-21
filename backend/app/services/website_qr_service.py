import base64
import io
import os
from typing import Optional
from urllib.parse import quote, urlparse
from uuid import UUID

import qrcode
import qrcode.image.svg
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.college import Canteen, CollegeSettings
from app.models.menu import FoodCategory
from app.services.audit_service import record_audit_log
from app.services.college_service import get_or_create_college_settings


def _is_localhost_or_loopback(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return True
    host = (parsed.hostname or "").lower()
    if not host:
        return True
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.endswith(".local"):
        return True
    return parsed.scheme not in ("http", "https")


def resolve_public_frontend_url() -> tuple[str, bool, bool]:
    """Return (configured_url, is_production, is_valid_public_url) from environment configuration."""
    base_url = settings.public_frontend_url.rstrip("/")
    is_prod = bool(
        settings.is_production
        or os.environ.get("VERCEL") == "1"
        or os.environ.get("VERCEL_ENV") == "production"
    )
    is_local = _is_localhost_or_loopback(base_url)
    valid = bool(base_url.startswith("https://") and not is_local) if is_prod else (base_url.startswith(("http://", "https://")) and bool(urlparse(base_url).hostname))
    return base_url, is_prod, valid


def build_website_qr_target(
    db: Session,
    *,
    target_type: str,
    canteen_id: Optional[UUID] = None,
    category_id: Optional[UUID] = None,
) -> dict:
    """Resolve verified real public website URL and branding metadata without fake URLs or prod localhost."""
    base_url, is_prod, valid = resolve_public_frontend_url()
    if is_prod and (_is_localhost_or_loopback(base_url) or not base_url.startswith("https://")):
        raise HTTPException(
            status_code=503,
            detail="Production public frontend URL must be a valid HTTPS domain (localhost URLs are blocked in production). Configure PUBLIC_FRONTEND_URL or PUBLIC_BASE_URL.",
        )
    if not valid:
        raise HTTPException(status_code=400, detail="Configured public frontend URL is invalid")

    college: CollegeSettings = get_or_create_college_settings(db)
    ttype = (target_type or "website").strip().lower()
    if ttype not in ("website", "canteen", "menu"):
        raise HTTPException(status_code=400, detail="target_type must be website, canteen, or menu")

    canteen_name: Optional[str] = None
    category_name: Optional[str] = None

    if ttype == "website":
        target_url = f"{base_url}/"
        title = college.college_name
        subtitle = "All Campus Canteens"
        slug_part = "website"
    else:
        if not canteen_id:
            raise HTTPException(status_code=400, detail="canteen_id is required for canteen or menu website QR")
        canteen = db.get(Canteen, canteen_id)
        if not canteen or not canteen.is_active:
            raise HTTPException(status_code=404, detail="Active canteen not found")
        canteen_name = canteen.name
        title = canteen.name
        if ttype == "canteen":
            target_url = f"{base_url}/?canteen={quote(canteen.slug)}"
            subtitle = canteen.location or "Canteen Digital Ordering"
            slug_part = f"canteen-{canteen.slug}"
        else:
            if category_id:
                cat = db.get(FoodCategory, category_id)
                if not cat or cat.canteen_id != canteen.id or not cat.is_active:
                    raise HTTPException(status_code=404, detail="Active category not found for selected canteen")
                category_name = cat.name
                target_url = f"{base_url}/?canteen={quote(canteen.slug)}&category={cat.id}#menu"
                subtitle = f"{canteen.name} • {cat.name}"
                slug_part = f"menu-{canteen.slug}-{cat.slug}"
            else:
                target_url = f"{base_url}/?canteen={quote(canteen.slug)}#menu"
                subtitle = f"{canteen.name} • Live Menu"
                slug_part = f"menu-{canteen.slug}"

    return {
        "target_type": ttype,
        "target_url": target_url,
        "title": title,
        "subtitle": subtitle,
        "college_name": college.college_name,
        "college_logo_url": college.logo_url,
        "canteen_name": canteen_name,
        "category_name": category_name,
        "poster_headline": "Scan to Order Food",
        "filename_base": f"collegebites-{slug_part}-qr",
    }


def render_website_qr_png(url: str, *, box_size: int = 12) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=max(6, min(box_size, 24)),
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_website_qr_svg(url: str, *, box_size: int = 12) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=max(6, min(box_size, 24)),
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    factory = qrcode.image.svg.SvgPathImage
    img = qr.make_image(image_factory=factory)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def get_website_qr_config(db: Session) -> dict:
    base_url, is_prod, valid = resolve_public_frontend_url()
    college = get_or_create_college_settings(db)
    canteens = db.scalars(select(Canteen).where(Canteen.is_active.is_(True)).order_by(Canteen.name)).all()
    return {
        "public_frontend_url": base_url,
        "is_production": is_prod,
        "is_valid_public_url": valid,
        "college_name": college.college_name,
        "college_logo_url": college.logo_url,
        "poster_headline": "Scan to Order Food",
        "canteens": [
            {
                "id": str(c.id),
                "name": c.name,
                "slug": c.slug,
                "location": c.location,
            }
            for c in canteens
        ],
    }


def generate_website_qr_payload(
    db: Session,
    *,
    target_type: str,
    canteen_id: Optional[UUID],
    category_id: Optional[UUID],
    box_size: int,
    actor_user_id: UUID,
) -> dict:
    meta = build_website_qr_target(db, target_type=target_type, canteen_id=canteen_id, category_id=category_id)
    png_bytes = render_website_qr_png(meta["target_url"], box_size=box_size)
    svg_markup = render_website_qr_svg(meta["target_url"], box_size=box_size)
    record_audit_log(
        db,
        action="website_qr.generated",
        entity_type="website_qr",
        entity_id=meta["filename_base"],
        actor_user_id=actor_user_id,
        details={"target_type": meta["target_type"], "target_url": meta["target_url"]},
    )
    db.commit()
    return {
        **meta,
        "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "svg_markup": svg_markup,
    }
