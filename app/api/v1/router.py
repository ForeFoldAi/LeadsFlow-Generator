"""
Aggregates all v1 endpoint routers.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import generate, download, sectors, scrape, leads, export

api_router = APIRouter()

api_router.include_router(generate.router, prefix="/generate", tags=["Generate"])
api_router.include_router(download.router, prefix="/download", tags=["Download"])
api_router.include_router(sectors.router, prefix="/sectors", tags=["Sectors"])
api_router.include_router(scrape.router, prefix="/scrape", tags=["Scrape"])
api_router.include_router(leads.router, prefix="/leads", tags=["Leads"])
api_router.include_router(export.router, prefix="/export", tags=["Export"])
