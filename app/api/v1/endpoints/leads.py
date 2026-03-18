"""
Lead CRUD endpoints.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.lead import Lead as LeadModel
from app.schemas.lead import LeadListResponse, LeadRead

router = APIRouter()


@router.get(
    "",
    response_model=LeadListResponse,
    summary="List leads",
    description="Retrieve leads with optional filters. Results sorted by lead_score descending.",
)
async def list_leads(
    job_id: Optional[str] = Query(None, description="Filter by scraping job ID"),
    city: Optional[str] = Query(None, description="Partial city name match"),
    state: Optional[str] = Query(None, description="Partial state name match"),
    tier: Optional[str] = Query(
        None,
        description="Filter by tier label: Hot | Strong | Good | Moderate | Weak",
    ),
    min_score: float = Query(0.0, ge=0.0, le=100.0, description="Minimum lead score"),
    max_score: float = Query(100.0, ge=0.0, le=100.0, description="Maximum lead score"),
    has_email: Optional[bool] = Query(None, description="Only leads with / without email"),
    has_phone: Optional[bool] = Query(None, description="Only leads with / without phone"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> LeadListResponse:
    base_q = select(LeadModel)

    if job_id:
        base_q = base_q.where(LeadModel.job_id == job_id)
    if city:
        base_q = base_q.where(LeadModel.city.ilike(f"%{city}%"))
    if state:
        base_q = base_q.where(LeadModel.state.ilike(f"%{state}%"))
    if tier:
        base_q = base_q.where(LeadModel.tier.ilike(f"%{tier}%"))
    if min_score > 0:
        base_q = base_q.where(LeadModel.lead_score >= min_score)
    if max_score < 100:
        base_q = base_q.where(LeadModel.lead_score <= max_score)
    if has_email is True:
        base_q = base_q.where(LeadModel.email != "")
    if has_email is False:
        base_q = base_q.where(LeadModel.email == "")
    if has_phone is True:
        base_q = base_q.where(LeadModel.phone != "")
    if has_phone is False:
        base_q = base_q.where(LeadModel.phone == "")

    # Count total matching rows
    count_q = select(func.count()).select_from(base_q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Paginated results
    result = await db.execute(
        base_q.order_by(LeadModel.lead_score.desc()).offset(offset).limit(limit)
    )
    leads = result.scalars().all()

    return LeadListResponse(total=total, leads=leads)  # type: ignore[arg-type]


@router.get(
    "/{lead_id}",
    response_model=LeadRead,
    summary="Get a single lead by ID",
)
async def get_lead(lead_id: str, db: AsyncSession = Depends(get_db)) -> LeadRead:
    result = await db.execute(select(LeadModel).where(LeadModel.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' not found")
    return lead  # type: ignore[return-value]


@router.delete(
    "/{lead_id}",
    status_code=204,
    summary="Delete a single lead",
)
async def delete_lead(lead_id: str, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(LeadModel).where(LeadModel.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' not found")
    await db.delete(lead)
    await db.commit()


@router.delete(
    "",
    status_code=204,
    summary="Bulk delete leads",
    description="Delete all leads, or only those belonging to a specific job.",
)
async def bulk_delete_leads(
    job_id: Optional[str] = Query(None, description="Delete only leads from this job"),
    db: AsyncSession = Depends(get_db),
) -> None:
    q = delete(LeadModel)
    if job_id:
        q = q.where(LeadModel.job_id == job_id)
    await db.execute(q)
    await db.commit()
