# CollegeBites — Backup & Disaster Recovery Plan

## 1. Recovery Objectives
- **Target RPO (Recovery Point Objective):** ≤ 1 hour via Neon PostgreSQL continuous WAL / Point-in-Time Restore (PITR) + scheduled JSON/SQL verified snapshots (`POST /api/v1/backups`).
- **Target RTO (Recovery Time Objective):** ≤ 30 minutes for database branch restore + Vercel deployment promotion/rollback.

## 2. Backup Capabilities & Integrity Verification
- **Application-Managed Verified Snapshots (`/api/v1/backups`):**
  - `POST /api/v1/backups` creates an encrypted/checksummed snapshot with SHA-256 manifest, row-count ledger across operational tables, and immutable audit entry.
  - `POST /api/v1/backups/{backup_id}/verify` validates archive integrity and SHA-256 checksums before trusting any backup for recovery.
  - `POST /api/v1/backups/{backup_id}/restore` supports `dry_run: true` validation prior to executing any live restore (which additionally requires explicit confirmation phrase and `super_admin`/`college_admin` role).
- **Database-Native Backups (PostgreSQL / Neon):**
  ```bash
  pg_dump --format=custom --no-owner --no-privileges "$DATABASE_URL_UNPOOLED" -f "collegebites_$(date +%Y%m%d_%H%M%S).dump"
  sha256sum collegebites_*.dump > checksums.sha256
  ```

## 3. Isolated Restore Drill Procedure (Never Run Destructively on Production!)
1. Provision an isolated staging database or Neon branch (`staging_restore_drill`).
2. Restore the dump:
   ```bash
   pg_restore --clean --if-exists --no-owner --dbname="$STAGING_DB_URL" collegebites_YYYYMMDD_HHMMSS.dump
   ```
3. Run `alembic current` and verify schema head matches `e5f6a7b8c9d0`.
4. Verify critical row counts (`orders`, `payments`, `stock_batches`, `food_safety_inspections`, `production_batches`, `audit_logs`) and run read-only smoke queries against `/health/ready`, `/api/v1/canteens`, and `/api/v1/reports/dashboard`.
5. Destroy the temporary staging restore database once verified.

## 4. Verification Status in This Upgrade
- Isolated backup creation (`POST /api/v1/backups`), SHA-256 integrity verification (`POST /api/v1/backups/{id}/verify`), and non-destructive `dry_run: true` restore simulation (`POST /api/v1/backups/{id}/restore`) were executed and verified in `test_phase35_enterprise_master_platform.py`.
- Full PostgreSQL `pg_dump`/`pg_restore` against production Neon Postgres was **not executed** on live production in accordance with strict non-destructive safety rules.
