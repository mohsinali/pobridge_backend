"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.outlook import router as outlook_router
from app.api.v1.purchase_orders import router as purchase_orders_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(purchase_orders_router)
api_router.include_router(outlook_router)
