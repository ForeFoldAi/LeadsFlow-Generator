"""
Download endpoints — export session leads as CSV or Excel (LeadsFlow format).
"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services import session_store
from app.services.lead_engine import build_excel_bytes
from app.services.orchestrator import lead_to_leadsflow, LEADSFLOW_COLUMNS

router = APIRouter()


def _get_rows(session_id: str):
    data = session_store.get(session_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if data.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Session status is '{data.status}'. Wait until 'completed' before downloading.",
        )
    if not data.leads:
        raise HTTPException(status_code=404, detail="No leads found for this session")

    rows = []
    for lead in data.leads:
        row = lead_to_leadsflow(lead, keyword=data.sector, country=data.country)
        if row:
            rows.append(row)

    if not rows:
        raise HTTPException(status_code=404, detail="No exportable leads (all missing name/phone)")

    return rows


@router.get(
    "/csv",
    summary="Download leads as CSV (LeadsFlow format)",
    description="Downloads all leads from the session as a CSV file ready for LeadsFlow CRM import.",
    response_class=StreamingResponse,
)
async def download_csv(
    session_id: str = Query(..., description="Session ID from POST /api/v1/generate"),
) -> StreamingResponse:
    rows = _get_rows(session_id)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LEADSFLOW_COLUMNS)
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
    summary="Download leads as Excel (color-coded by tier)",
    description=(
        "Downloads all leads from the session as a color-coded .xlsx file "
        "(gold=Hot, orange=Strong, green=Good, blue=Moderate, grey=Weak)."
    ),
    response_class=StreamingResponse,
)
async def download_excel(
    session_id: str = Query(..., description="Session ID from POST /api/v1/generate"),
) -> StreamingResponse:
    rows = _get_rows(session_id)
    excel_bytes = build_excel_bytes(rows)

    filename = f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
