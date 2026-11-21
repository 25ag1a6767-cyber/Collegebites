# CollegeBites Deployment & Rollback Guide

## 1. Local Development
1. Start PostgreSQL & Redis (via `docker compose up -d postgres redis` or WSL/local services).
2. Backend:
   ```bash
   cd backend
   python -m venv .venv
   # Activate venv, then:
   pip install -r requirements.txt
   cp .env.example .env
   alembic upgrade head
   python -m app.cli.seed_demo
   uvicorn app.main:app --reload --port 8000
   ```
3. Frontend Web:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
4. Mobile (Expo):
   ```bash
   cd mobile
   npm install
   npx expo start
   ```

## 2. Production / Staging Environment Variables
Set strong secrets (never commit `.env`):
- `ENVIRONMENT=production`
- `OTP_TEST_ECHO=false`
- `RAZORPAY_TEST_MODE=false` (once real Razorpay merchant credentials are configured)
- `DATABASE_URL` (PostgreSQL with SSL/pooler, e.g., Neon Postgres via `vercel integration add neon`)
- `REDIS_URL` (Upstash Redis or managed Redis, e.g., `vercel integration add upstash`)
- `SECRET_KEY` (64+ random chars)
- `QR_SIGNING_SECRET` (64+ random chars)
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`
- `PUBLIC_BASE_URL`, `CORS_ORIGINS`

Create the first production Super Administrator safely:
```bash
python -m app.cli.create_admin --email admin@yourcollege.edu --name "College Super Admin"
```

## 3. Vercel Deployment (Frontend + FastAPI Backend via Vercel Services)
`vercel.json` is pre-configured with Vercel Services (`frontend` static Vite SPA + `backend` FastAPI Python runtime):
1. Link & provision Postgres/Redis on Vercel:
   ```bash
   vercel link
   vercel integration add neon
   vercel integration add upstash
   ```
2. Add secrets (`vercel env add SECRET_KEY production`, `QR_SIGNING_SECRET`, `RAZORPAY_*`, `ENVIRONMENT=production`, `OTP_TEST_ECHO=false`).
3. Run Alembic migrations against production `DATABASE_URL` BEFORE promoting traffic:
   ```bash
   alembic upgrade head
   ```
4. Deploy:
   ```bash
   vercel --prod
   ```

## 4. Automated Backups & Rollback Procedure
- **Database Backup**: Schedule daily `pg_dump --format=custom --no-owner "$DATABASE_URL" > collegebites_$(date +%F).dump` before any migration.
- **Code Rollback (Vercel)**: `vercel ls` -> `vercel rollback <previous-deployment-url>`.
- **Migration Rollback (Alembic)**: Always back up first, then `alembic downgrade -1` if schema rollback is required.
