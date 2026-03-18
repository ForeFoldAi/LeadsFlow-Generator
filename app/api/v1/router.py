"""
Aggregates all v1 endpoint routers (no-DB version).
"""
from fastapi import APIRouter

from app.api.v1.endpoints import generate, download, sectors

api_router = APIRouter()

api_router.include_router(generate.router, prefix="/generate", tags=["Generate"])
api_router.include_router(download.router, prefix="/download", tags=["Download"])
api_router.include_router(sectors.router, prefix="/sectors", tags=["Sectors"])
