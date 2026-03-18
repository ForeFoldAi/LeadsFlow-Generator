"""
In-memory session store — holds scraping results keyed by session_id.
No database required; results live for the lifetime of the process.
"""
from datetime import datetime
from typing import Dict, List, Optional

from app.models.lead_dataclass import Lead


class SessionData:
    def __init__(self, sector: str, city: str, country: str):
        self.sector = sector
        self.city = city
        self.country = country
        self.status: str = "pending"   # pending | running | completed | failed
        self.leads: List[Lead] = []
        self.total: int = 0
        self.error: Optional[str] = None
        self.created_at: datetime = datetime.utcnow()
        self.completed_at: Optional[datetime] = None


_store: Dict[str, SessionData] = {}


def create(session_id: str, sector: str, city: str, country: str) -> SessionData:
    data = SessionData(sector=sector, city=city, country=country)
    _store[session_id] = data
    return data


def get(session_id: str) -> Optional[SessionData]:
    return _store.get(session_id)


def delete(session_id: str) -> None:
    _store.pop(session_id, None)


def all_sessions() -> Dict[str, SessionData]:
    return dict(_store)
