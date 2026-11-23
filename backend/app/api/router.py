from fastapi import APIRouter

from app.api.admin.routes import router as admin_router
from app.api.auth.routes import router as auth_router
from app.api.backups.routes import router as backups_router
from app.api.canteens.routes import router as canteens_router
from app.api.carts.routes import router as carts_router
from app.api.customers.routes import router as customers_router
from app.api.events.routes import router as events_router
from app.api.inventory.routes import router as inventory_router
from app.api.invoices.routes import router as invoices_router
from app.api.kiosk.routes import router as kiosk_router
from app.api.kitchen.routes import router as kitchen_router
from app.api.meal_plans.routes import router as meal_plans_router
from app.api.menus.routes import router as menus_router
from app.api.notifications.routes import router as notifications_router
from app.api.orders.routes import router as orders_router
from app.api.payments.routes import router as payments_router
from app.api.pickup.routes import router as pickup_router
from app.api.pos.routes import router as pos_router
from app.api.printing.routes import router as printing_router
from app.api.promotions.routes import router as promotions_router
from app.api.qr.routes import router as qr_router
from app.api.queue.routes import router as queue_router
from app.api.realtime.routes import router as realtime_router
from app.api.reports.routes import router as reports_router
from app.api.security.routes import router as security_router
from app.api.staff.routes import router as staff_router
from app.api.support.routes import router as support_router
from app.api.tokens.routes import router as tokens_router
from app.api.ws.routes import router as ws_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(canteens_router)
api_router.include_router(admin_router)
api_router.include_router(menus_router)
api_router.include_router(customers_router)
api_router.include_router(qr_router)
api_router.include_router(carts_router)
api_router.include_router(orders_router)
api_router.include_router(payments_router)
api_router.include_router(tokens_router)
api_router.include_router(printing_router)
api_router.include_router(kitchen_router)
api_router.include_router(pickup_router)
api_router.include_router(pos_router)
api_router.include_router(queue_router)
api_router.include_router(inventory_router)
api_router.include_router(staff_router)
api_router.include_router(promotions_router)
api_router.include_router(notifications_router)
api_router.include_router(support_router)
api_router.include_router(reports_router)
api_router.include_router(security_router)
api_router.include_router(backups_router)
api_router.include_router(kiosk_router)
api_router.include_router(meal_plans_router)
api_router.include_router(events_router)
api_router.include_router(invoices_router)
api_router.include_router(realtime_router)
api_router.include_router(ws_router)
