from fastapi import APIRouter, Depends

from app.api.deps import require_internal_token
from app.api.v1 import health

api_router = APIRouter(dependencies=[Depends(require_internal_token)])
api_router.include_router(health.router)
