from fastapi import APIRouter

from app.api.v1 import (
    analytics_api,
    auth,
    catalog,
    customers,
    inventory,
    models_api,
    predictions,
    products,
    repairs,
    service_requests,
    warranties,
)

api_router = APIRouter(prefix="/api/v1")
for module in (auth, customers, catalog, products, warranties, service_requests, repairs, inventory, predictions,
               models_api, analytics_api):
    api_router.include_router(module.router)
