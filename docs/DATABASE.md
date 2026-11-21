# CollegeBites Database Design (Quick Summary)

See [`DATABASE_SCHEMA.md`](./DATABASE_SCHEMA.md) for the complete 88-table column reference.

PostgreSQL relational schema using SQLAlchemy 2 and Alembic migrations (head: `3b2c4d5e7f8a`).
All monetary columns use exact `NUMERIC(12, 2)` / `NUMERIC(10, 2)` (`Money`).
**No refund tables exist in this schema by policy and design; cash/pay-at-pickup are disabled platform-wide; coupon records are purged.**
