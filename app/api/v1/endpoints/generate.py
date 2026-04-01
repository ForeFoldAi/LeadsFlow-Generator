"""
Generate endpoint — scrape leads on demand, no DB storage.

Flow:
  1. POST /api/v1/generate  → returns session_id immediately (status: pending)
  2. GET  /api/v1/generate/{session_id} → poll until status = completed | failed
  3. GET  /api/v1/download/csv?session_id=...   → download CSV
  4. GET  /api/v1/download/excel?session_id=... → download Excel
"""
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.generate import GenerateRequest, GenerateResponse, LeadSummary
from app.services import session_store

router = APIRouter()

ALL_SOURCES = ["google", "yelp", "yellowpages", "bbb", "sulekha",
               "linkedin", "facebook", "instagram", "twitter", "apollo"]
DEFAULT_SOURCES = ["google", "yelp", "yellowpages", "bbb"]


def _build_response(session_id: str, data: session_store.SessionData) -> GenerateResponse:
    leads_summary: List[LeadSummary] = [
        LeadSummary(
            name=l.name or "",
            phone=l.phone or "",
            email=l.email or "",
            city=l.city or "",
            category=l.category or "",
            lead_score=l.lead_score or 0.0,
            tier=l.tier or "",
            sources=l.sources or "",
            website=l.website or "",
            rating=l.rating or 0.0,
            reviews=l.reviews or 0,
        )
        for l in data.leads
    ]
    return GenerateResponse(
        session_id=session_id,
        status=data.status,
        sector=data.sector,
        city=data.city,
        country=data.country,
        total=data.total,
        leads=leads_summary,
        error=data.error,
        created_at=data.created_at,
        completed_at=data.completed_at,
        download_csv=f"/api/v1/download/csv?session_id={session_id}",
        download_excel=f"/api/v1/download/excel?session_id={session_id}",
    )


async def _run_scraping(
    session_id: str,
    sector: str,
    city: str,
    country: str,
    sources: List[str],
    max_per_source: int,
    delay: float,
    min_score: float,
    headless: bool,
) -> None:
    data = session_store.get(session_id)
    if not data:
        return

    data.status = "running"
    try:
        from app.services.orchestrator import LeadEngine

        location = f"{city}, {country}"
        engine = LeadEngine(
            sources=sources,
            max_per_source=max_per_source,
            delay=delay,
            headless=headless,
            min_score=min_score,
            country=country,
        )
        leads = await engine.run(sector, location)

        data.leads = leads
        data.total = len(leads)
        data.status = "completed"
        data.completed_at = datetime.utcnow()

    except Exception as exc:
        data.status = "failed"
        data.error = str(exc)


@router.post(
    "",
    response_model=GenerateResponse,
    status_code=202,
    summary="Generate leads (no DB)",
    description=(
        "Start a lead generation job. Returns a `session_id` immediately. "
        "Poll `GET /api/v1/generate/{session_id}` until status = `completed`. "
        "Then download results via `/api/v1/download/csv` or `/api/v1/download/excel`."
    ),
)
async def generate_leads(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
) -> GenerateResponse:
    # Validate sources
    sources = list(request.sources) if request.sources else list(DEFAULT_SOURCES)
    invalid = [s for s in sources if s not in ALL_SOURCES]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sources: {invalid}. Valid: {ALL_SOURCES}",
        )

    session_id = str(uuid.uuid4())
    data = session_store.create(
        session_id=session_id,
        sector=request.sector,
        city=request.city,
        country=request.country,
    )

    background_tasks.add_task(
        _run_scraping,
        session_id=session_id,
        sector=request.sector,
        city=request.city,
        country=request.country,
        sources=sources,
        max_per_source=request.max_per_source,
        delay=request.delay,
        min_score=request.min_score,
        headless=request.headless,
    )

    return _build_response(session_id, data)


@router.get(
    "/{session_id}",
    response_model=GenerateResponse,
    summary="Poll generation status",
    description="Returns current status and leads (once completed).",
)
async def get_session(session_id: str) -> GenerateResponse:
    data = session_store.get(session_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return _build_response(session_id, data)


@router.delete(
    "/{session_id}",
    status_code=204,
    summary="Delete a session and its leads from memory",
)
async def delete_session(session_id: str) -> None:
    if not session_store.get(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    session_store.delete(session_id)
