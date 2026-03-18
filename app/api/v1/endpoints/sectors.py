"""
Sectors endpoint — returns the list of supported business sectors.
"""
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.orchestrator import SECTOR_HINTS

router = APIRouter()


class SectorsResponse(BaseModel):
    sectors: List[str]


@router.get(
    "",
    response_model=SectorsResponse,
    summary="Get available business sectors",
    description="Returns the list of predefined business sectors supported by the lead generation engine.",
)
async def get_sectors() -> SectorsResponse:
    sectors = [sector for _, sector in SECTOR_HINTS]
    return SectorsResponse(sectors=sectors)
