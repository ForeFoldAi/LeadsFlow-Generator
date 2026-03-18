"""
Lead engine service — background scraping + DB persistence + export helpers.

This module bridges the existing root-level orchestrator (unchanged) with
the new FastAPI / SQLAlchemy persistence layer.
"""
import io
import uuid
from datetime import datetime
from typing import List, Optional


# ── Background job ────────────────────────────────────────────────────────────

async def run_scrape_job(
    job_id: str,
    keyword: str,
    location: str,
    sources: List[str],
    max_per_source: int = 25,
    min_score: float = 0.0,
    country: str = "India",
    headless: bool = True,
    delay: float = 1.5,
) -> None:
    """
    Background coroutine: run all scrapers, score leads, persist to DB.
    Called by FastAPI BackgroundTasks — runs after the HTTP response is sent.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import ScrapeJob
    from app.models.lead import Lead as LeadModel
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        # ── Mark job as running ───────────────────────────────────────────────
        res = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        job = res.scalar_one_or_none()
        if not job:
            return

        job.status = "running"
        job.updated_at = datetime.utcnow()
        await db.commit()

        try:
            from app.services.orchestrator import LeadEngine

            engine = LeadEngine(
                sources=sources,
                max_per_source=max_per_source,
                delay=delay,
                headless=headless,
                min_score=min_score,
                country=country,
            )
            leads = await engine.run(keyword, location)

            # ── Persist scored leads ──────────────────────────────────────────
            for lead in leads:
                db_lead = LeadModel(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    name=lead.name,
                    category=lead.category,
                    phone=lead.phone,
                    website=lead.website,
                    email=lead.email,
                    address=lead.address,
                    city=lead.city,
                    state=lead.state,
                    zip_code=lead.zip_code,
                    rating=lead.rating,
                    reviews=lead.reviews,
                    hours=lead.hours,
                    sources=lead.sources,
                    source_urls=lead.source_urls,
                    lead_score=lead.lead_score,
                    tier=lead.tier,
                    score_rating=lead.score_rating,
                    score_reviews=lead.score_reviews,
                    score_contact=lead.score_contact,
                    score_sources=lead.score_sources,
                    score_engagement=lead.score_engagement,
                    score_profile=lead.score_profile,
                    scraped_at=lead.scraped_at,
                    created_at=datetime.utcnow(),
                )
                db.add(db_lead)

            job.status = "completed"
            job.total_found = len(leads)
            job.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            await db.commit()

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.updated_at = datetime.utcnow()
            await db.commit()
            raise


# ── Export helpers ────────────────────────────────────────────────────────────

def leads_to_leadsflow_rows(
    db_leads,
    keyword: str = "",
    country: str = "India",
) -> List[dict]:
    """
    Convert a list of SQLAlchemy Lead models to LeadsFlow-format row dicts.
    Uses the existing orchestrator conversion logic verbatim.
    """
    from app.models.lead_dataclass import Lead as LeadDataclass
    from app.services.orchestrator import lead_to_leadsflow

    rows = []
    for dl in db_leads:
        dataclass_lead = LeadDataclass(
            name=dl.name or "",
            category=dl.category or "",
            phone=dl.phone or "",
            website=dl.website or "",
            email=dl.email or "",
            address=dl.address or "",
            city=dl.city or "",
            state=dl.state or "",
            zip_code=dl.zip_code or "",
            rating=dl.rating or 0.0,
            reviews=dl.reviews or 0,
            hours=dl.hours or "",
            sources=dl.sources or "",
            source_urls=dl.source_urls or "",
            lead_score=dl.lead_score or 0.0,
            tier=dl.tier or "",
            score_rating=dl.score_rating or 0.0,
            score_reviews=dl.score_reviews or 0.0,
            score_contact=dl.score_contact or 0.0,
            score_sources=dl.score_sources or 0.0,
            score_engagement=dl.score_engagement or 0.0,
            score_profile=dl.score_profile or 0.0,
            scraped_at=dl.scraped_at or "",
        )
        row = lead_to_leadsflow(dataclass_lead, keyword=keyword, country=country)
        if row:
            rows.append(row)
    return rows


def build_excel_bytes(rows: List[dict]) -> bytes:
    """
    Build a color-coded Excel workbook from LeadsFlow rows and return raw bytes.
    """
    if not rows:
        return b""

    import pandas as pd
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from app.services.orchestrator import LEADSFLOW_COLUMNS

    df = pd.DataFrame(rows, columns=LEADSFLOW_COLUMNS)
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="LeadsFlow Import")
        ws = writer.sheets["LeadsFlow Import"]

        # Header styling
        hfill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        hfont = Font(bold=True, color="FFFFFF", name="Arial", size=9)
        for cell in ws[1]:
            cell.fill = hfill
            cell.font = hfont
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 42

        tier_fills = {
            "Hot":      PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
            "Strong":   PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"),
            "Good":     PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"),
            "Moderate": PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid"),
            "Weak":     PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid"),
        }
        alt = [
            PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid"),
            PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid"),
        ]
        bfont = Font(name="Arial", size=9)
        border = Border(bottom=Side(style="thin", color="DDDDDD"))
        notes_idx = LEADSFLOW_COLUMNS.index("Additional Notes")

        for i, row in enumerate(ws.iter_rows(min_row=2, max_row=ws.max_row), 1):
            notes_val = str(row[notes_idx].value or "")
            fill = alt[i % 2]
            for lbl, tfill in tier_fills.items():
                if f"Tier {lbl}" in notes_val:
                    fill = tfill
                    break
            for cell in row:
                cell.fill = fill
                cell.font = bfont
                cell.border = border
                cell.alignment = Alignment(vertical="top")

        for col in ws.columns:
            w = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(w + 3, 40)
        ws.freeze_panes = "A2"

    output.seek(0)
    return output.read()
