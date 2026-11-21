import base64
import io
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from tests.conftest import login_as


def test_website_qr_permissions_formats_targets_and_prod_localhost_guard(client: TestClient, monkeypatch):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    main = next(c for c in canteens if c["slug"] == "main-canteen")
    cid = main["id"]
    cats = client.get(f"/api/v1/menus/canteens/{cid}/categories").json()
    cat_id = cats[0]["id"]

    # 1. Strictly requires admin permission qr:website_manage (403 for non-college-admin roles, 401 unauth)
    assert client.get("/api/v1/qr/website/config").status_code == 401
    for non_admin in (student, cashier, inv_mgr, mgr):
        assert client.get("/api/v1/qr/website/config", headers=non_admin["headers"]).status_code == 403
        assert (
            client.post(
                "/api/v1/qr/website/generate",
                headers=non_admin["headers"],
                json={"target_type": "website"},
            ).status_code
            == 403
        )
        assert (
            client.get("/api/v1/qr/website/download?format=png&target_type=website", headers=non_admin["headers"]).status_code
            == 403
        )

    # 2. Localhost URLs MUST be blocked when running in production mode
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://localhost:5173")
    monkeypatch.setattr(settings, "PUBLIC_FRONTEND_URL", "")
    monkeypatch.delenv("VERCEL_PROJECT_PRODUCTION_URL", raising=False)
    monkeypatch.delenv("VERCEL_URL", raising=False)

    cfg_bad = client.get("/api/v1/qr/website/config", headers=admin["headers"])
    assert cfg_bad.status_code == 200
    assert cfg_bad.json()["is_production"] is True
    assert cfg_bad.json()["is_valid_public_url"] is False

    gen_blocked = client.post(
        "/api/v1/qr/website/generate",
        headers=admin["headers"],
        json={"target_type": "website"},
    )
    assert gen_blocked.status_code == 503
    assert (
        client.get("/api/v1/qr/website/download?format=svg&target_type=website", headers=admin["headers"]).status_code
        == 503
    )

    # 3. With valid configured public HTTPS domain, generates Website, Canteen, and Menu QRs in PNG & SVG
    monkeypatch.setattr(settings, "PUBLIC_FRONTEND_URL", "https://collegebites-alpha.vercel.app")
    cfg_ok = client.get("/api/v1/qr/website/config", headers=admin["headers"]).json()
    assert cfg_ok["is_valid_public_url"] is True
    assert cfg_ok["public_frontend_url"] == "https://collegebites-alpha.vercel.app"
    assert cfg_ok["poster_headline"] == "Scan to Order Food"

    gen_site = client.post(
        "/api/v1/qr/website/generate",
        headers=admin["headers"],
        json={"target_type": "website"},
    )
    assert gen_site.status_code == 200, gen_site.text
    site_data = gen_site.json()
    assert site_data["target_url"] == "https://collegebites-alpha.vercel.app/"
    assert site_data["poster_headline"] == "Scan to Order Food"
    assert "localhost" not in site_data["target_url"]
    assert "<svg" in site_data["svg_markup"] and "<path" in site_data["svg_markup"]
    raw_png = base64.b64decode(site_data["png_base64"])
    img = Image.open(io.BytesIO(raw_png))
    assert img.format == "PNG" and img.width >= 200

    # Download PNG and SVG endpoints
    dl_png = client.get(
        "/api/v1/qr/website/download?format=png&target_type=canteen&canteen_id=" + cid,
        headers=admin["headers"],
    )
    assert dl_png.status_code == 200
    assert dl_png.headers["content-type"] == "image/png"
    assert dl_png.content.startswith(b"\x89PNG")

    dl_svg = client.get(
        f"/api/v1/qr/website/download?format=svg&target_type=menu&canteen_id={cid}&category_id={cat_id}",
        headers=admin["headers"],
    )
    assert dl_svg.status_code == 200
    assert dl_svg.headers["content-type"] == "image/svg+xml"
    assert b"<svg" in dl_svg.content

    gen_menu = client.post(
        "/api/v1/qr/website/generate",
        headers=admin["headers"],
        json={"target_type": "menu", "canteen_id": cid, "category_id": cat_id},
    ).json()
    parsed = urlparse(gen_menu["target_url"])
    assert parsed.scheme == "https" and parsed.netloc == "collegebites-alpha.vercel.app"
    assert f"canteen={main['slug']}" in parsed.query
    assert f"category={cat_id}" in parsed.query
    assert parsed.fragment == "menu"

    # 4. Nonexistent canteen / fake targets fail cleanly with 404
    bad_canteen = client.post(
        "/api/v1/qr/website/generate",
        headers=admin["headers"],
        json={"target_type": "canteen", "canteen_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert bad_canteen.status_code == 404
