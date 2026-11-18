from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, store_categories, store_customers, store_inventory_adjustments, store_memberships, store_orders, store_products, store_storefront_content, store_workspace, stores

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(stores.router)
api_router.include_router(store_memberships.router)
api_router.include_router(store_workspace.router)
api_router.include_router(store_categories.router)
api_router.include_router(store_products.router)
api_router.include_router(store_inventory_adjustments.router)
api_router.include_router(store_orders.router)
api_router.include_router(store_customers.router)
api_router.include_router(store_storefront_content.router)
