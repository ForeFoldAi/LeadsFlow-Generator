"""
Export endpoints — download leads as CSV or Excel (LeadsFlow format).
"""
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.job import ScrapeJob
from app.models.lead import Lead as LeadModel
from app.services.lead_engine import build_excel_bytes, leads_to_leadsflow_rows

router = APIRouter()


async def _fetch_leads(db: AsyncSession, job_id: Optional[str], min_score: float):
    q = select(LeadModel).order_by(LeadModel.lead_score.desc())
    if job_id:
        q = q.where(LeadModel.job_id == job_id)
    if min_score > 0:
        q = q.where(LeadModel.lead_score >= min_score)
    result = await db.execute(q)
    return result.scalars().all()


async def _get_keyword(db: AsyncSession, job_id: Optional[str]) -> str:
    if not job_id:
        return ""
    result = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
    job = result.scalar_one_or_none()
    return job.keyword if job else ""


@router.get(
    "/csv",
    summary="Export leads as CSV (LeadsFlow format)",
    description=(
        "Downloads leads as a CSV file ready for import into LeadsFlow CRM. "
        "Optionally filter by job_id or minimum score."
    ),
    response_class=StreamingResponse,
)
async def export_csv(
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    import csv
    from datetime import datetime

    leads = await _fetch_leads(db, job_id, min_score)
    if not leads:
        raise HTTPException(status_code=404, detail="No leads match the given filters")

    keyword = await _get_keyword(db, job_id)
    rows = leads_to_leadsflow_rows(leads, keyword=keyword)

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    buf.seek(0)

    filename = f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/excel",
    summary="Export leads as Excel (color-coded by tier)",
    description=(
        "Downloads leads as an Excel .xlsx file with color-coded rows "
        "(gold=Hot, orange=Strong, green=Good, blue=Moderate, grey=Weak)."
    ),
    response_class=StreamingResponse,
)
async def export_excel(
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    from datetime import datetime

    leads = await _fetch_leads(db, job_id, min_score)
    if not leads:
        raise HTTPException(status_code=404, detail="No leads match the given filters")

    keyword = await _get_keyword(db, job_id)
    rows = leads_to_leadsflow_rows(leads, keyword=keyword)
    excel_bytes = build_excel_bytes(rows)

    filename = f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
