"""
Scraping endpoints — submit jobs, poll status.
"""
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.job import ScrapeJob
from app.schemas.job import JobRead, ScrapeRequest
from app.services.lead_engine import run_scrape_job

router = APIRouter()


# ── Valid sources (mirrors orchestrator.SOURCES) ──────────────────────────────
ALL_SOURCES = ["google", "yelp", "yellowpages", "bbb",
               "linkedin", "facebook", "instagram", "twitter", "apollo"]
DEFAULT_SOURCES = ["google", "yelp", "yellowpages", "bbb"]
SOCIAL_SOURCES = ["linkedin", "facebook", "instagram", "twitter"]
API_SOURCES = ["apollo"]


@router.post(
    "",
    response_model=JobRead,
    status_code=202,
    summary="Start a lead scraping job",
    description=(
        "Submits a background scraping job across up to 9 sources. "
        "Returns immediately with a `job_id` — poll `/api/v1/scrape/jobs/{job_id}` "
        "for status, or `GET /api/v1/leads?job_id=...` for results."
    ),
)
async def start_scrape(
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    # ── Resolve source list ───────────────────────────────────────────────────
    if request.sources:
        sources: List[str] = list(request.sources)
    else:
        sources = list(DEFAULT_SOURCES)
        if request.include_social:
            sources += SOCIAL_SOURCES
        if request.include_apis:
            sources += API_SOURCES

    invalid = [s for s in sources if s not in ALL_SOURCES]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sources: {invalid}. Valid options: {ALL_SOURCES}",
        )

    # ── Persist job record ────────────────────────────────────────────────────
    job = ScrapeJob(
        id=str(uuid.uuid4()),
        keyword=request.keyword,
        location=request.location,
        sources=sources,
        status="pending",
        max_per_source=request.max_per_source,
        min_score=request.min_score,
        country=request.country,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # ── Queue background task ─────────────────────────────────────────────────
    background_tasks.add_task(
        run_scrape_job,
        job_id=job.id,
        keyword=request.keyword,
        location=request.location,
        sources=sources,
        max_per_source=request.max_per_source,
        min_score=request.min_score,
        country=request.country,
        headless=request.headless,
        delay=request.delay,
    )

    return job  # type: ignore[return-value]


@router.get(
    "/jobs",
    response_model=List[JobRead],
    summary="List all scraping jobs",
)
async def list_jobs(
    status: str = Query(None, description="Filter by status: pending|running|completed|failed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> List[JobRead]:
    q = select(ScrapeJob).order_by(ScrapeJob.created_at.desc())
    if status:
        q = q.where(ScrapeJob.status == status)
    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()  # type: ignore[return-value]


@router.get(
    "/jobs/{job_id}",
    response_model=JobRead,
    summary="Get status of a specific scraping job",
)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)) -> JobRead:
    result = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job  # type: ignore[return-value]


@router.delete(
    "/jobs/{job_id}",
    status_code=204,
    summary="Delete a job and all its leads",
)
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    await db.delete(job)
    await db.commit()
