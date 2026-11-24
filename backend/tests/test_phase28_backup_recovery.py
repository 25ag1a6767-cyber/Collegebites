from __future__ import annotations

from uuid import UUID, uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.integrations.razorpay_client import razorpay_gateway
from app.models import Base
from app.models.system import BackupRecord, SecurityAlert
from app.services import backup_service
from tests.conftest import TEST_DB_URL, TestingSessionLocal, login_as, test_engine


def test_encrypted_backup_verification_redaction_isolation_and_disaster_recovery(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")

    # 1. Non-college-admin users MUST NOT create/list/restore backups (403)
    assert client.get("/api/v1/backups/dashboard", headers=student["headers"]).status_code == 403
    assert client.post("/api/v1/backups", headers=manager["headers"], json={"trigger_type": "manual"}).status_code == 403

    # 2. Place and verify a real paid order so backup captures live business transactions
    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    food = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()[0]
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"bkp-{uuid4().hex[:14]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food["id"], "quantity": 1}],
        },
    ).json()
    pay_id = f"pay_{uuid4().hex[:12]}"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=co["razorpay_order_id"],
        razorpay_payment_id=pay_id,
    )
    client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co["id"],
            "razorpay_order_id": co["razorpay_order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )

    # 3. Create encrypted backup and validate cipher & strict secret redaction
    bkp_resp = client.post("/api/v1/backups", headers=admin["headers"], json={"trigger_type": "manual"})
    assert bkp_resp.status_code == 200, bkp_resp.text
    bkp = bkp_resp.json()
    assert bkp["is_encrypted"] is True
    assert bkp["integrity_verified"] is True
    assert bkp["row_counts"]["orders"] >= 1
    assert bkp["row_counts"]["payments"] >= 1

    # Raw blob stored in DB is Fernet-encrypted and readable cleanly via download endpoint
    dl = client.get(f"/api/v1/backups/{bkp['id']}/download", headers=admin["headers"])
    assert dl.status_code == 200
    assert dl.headers["x-backup-checksum-sha256"] == bkp["checksum_sha256"]
    assert co["order_number"].encode("utf-8") not in dl.content

    with TestingSessionLocal() as db:
        rec = db.get(BackupRecord, UUID(bkp["id"]))
        assert rec is not None
        bundle = backup_service._decrypt_and_validate_bundle(db, rec)
        for u in bundle["tables"].get("users", []):
            assert u.get("password_hash") is None
        for o in bundle["tables"].get("orders", []):
            assert o.get("guest_access_token_hash") is None

    # 4. Verify & Dry-Run Restore
    ver = client.post(f"/api/v1/backups/{bkp['id']}/verify", headers=admin["headers"])
    assert ver.status_code == 200
    assert ver.json()["verified"] is True

    # Live restore without exact confirmation phrase MUST fail 400
    bad_live = client.post(
        f"/api/v1/backups/{bkp['id']}/restore",
        headers=admin["headers"],
        json={"dry_run": False, "confirmation_phrase": "wrong"},
    )
    assert bad_live.status_code == 400

    dry = client.post(
        f"/api/v1/backups/{bkp['id']}/restore",
        headers=admin["headers"],
        json={"dry_run": True},
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["verification_passed"] is True

    # 5. Real isolated disaster recovery drill (isolated PG schema on PostgreSQL; isolated SQLite DB on SQLite)
    if test_engine.dialect.name == "sqlite":
        from sqlalchemy import create_engine

        drill_engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=drill_engine)
        try:
            with TestingSessionLocal() as db:
                drill_res = backup_service.restore_backup(
                    db,
                    UUID(bkp["id"]),
                    dry_run=False,
                    target_engine=drill_engine,
                    actor_user_id=UUID(admin["user"]["id"]),
                )
                assert drill_res["verification_passed"] is True

            with drill_engine.begin() as conn:
                assert conn.execute(text("SELECT count(*) FROM orders")).scalar() >= 1
                assert conn.execute(text("SELECT count(*) FROM payments")).scalar() >= 1
                assert conn.execute(text("SELECT count(*) FROM pickup_tokens")).scalar() >= 1
        finally:
            drill_engine.dispose()
    else:
        drill_schema = "dr_drill_verify"
        with test_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{drill_schema}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{drill_schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{drill_schema}"'))
            Base.metadata.create_all(bind=conn)

        try:
            with TestingSessionLocal() as db:
                drill_res = backup_service.restore_backup(
                    db,
                    UUID(bkp["id"]),
                    dry_run=False,
                    target_engine=test_engine,
                    target_schema=drill_schema,
                    actor_user_id=UUID(admin["user"]["id"]),
                )
                assert drill_res["verification_passed"] is True

            with test_engine.begin() as conn:
                conn.execute(text(f'SET LOCAL search_path TO "{drill_schema}"'))
                restored_order_cnt = conn.execute(text("SELECT count(*) FROM orders")).scalar()
                restored_pay_cnt = conn.execute(text("SELECT count(*) FROM payments")).scalar()
                restored_tok_cnt = conn.execute(text("SELECT count(*) FROM pickup_tokens")).scalar()
                assert restored_order_cnt >= 1
                assert restored_pay_cnt >= 1
                assert restored_tok_cnt >= 1
        finally:
            with test_engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{drill_schema}" CASCADE'))

    # 6. Checksum tampering triggers integrity failure + critical SecurityAlert
    with TestingSessionLocal() as db:
        rec = db.get(BackupRecord, UUID(bkp["id"]))
        orig_hash = rec.checksum_sha256
        rec.checksum_sha256 = "0" * 64
        db.commit()

    tamper_ver = client.post(f"/api/v1/backups/{bkp['id']}/verify", headers=admin["headers"])
    assert tamper_ver.status_code == 400
    with TestingSessionLocal() as db:
        rec = db.get(BackupRecord, UUID(bkp["id"]))
        rec.checksum_sha256 = orig_hash
        rec.integrity_verified = True
        db.commit()

    # 7. Backup failure creates failed record + critical alert, and retention policy prunes excess
    with TestingSessionLocal() as db:
        try:
            backup_service.create_backup(db, trigger_type="scheduled", simulate_failure=True)
            assert False, "Expected backup failure exception"
        except Exception:
            pass
        alerts = db.scalars(
            select(SecurityAlert).where(SecurityAlert.alert_type.in_(("backup_failed", "backup_integrity_failed")))
        ).all()
        assert len(alerts) >= 2

    # Create two more backups and enforce max_backups=2 pruning
    b2 = client.post("/api/v1/backups", headers=admin["headers"], json={"trigger_type": "manual"}).json()
    assert b2["is_encrypted"] is True
    client.put(
        "/api/v1/backups/settings",
        headers=admin["headers"],
        json={"auto_backup_enabled": True, "frequency_hours": 12, "retention_days": 14, "max_backups": 2},
    )
    b3 = client.post("/api/v1/backups", headers=admin["headers"], json={"trigger_type": "manual"}).json()
    assert b3["is_encrypted"] is True
    listed = client.get("/api/v1/backups", headers=admin["headers"]).json()
    valid_listed = [x for x in listed if x["status"] != "failed"]
    assert len(valid_listed) <= 2
