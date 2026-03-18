# Lead Generation API

Multi-source B2B/B2C lead generation engine — now with a full **FastAPI REST API**, **Swagger UI**, **SQLite/PostgreSQL persistence**, and **Alembic migrations**.

---

## Project Structure

```
Lead Generation New/
├── app/                          # FastAPI application package
│   ├── main.py                   # App factory, lifespan, Swagger config
│   ├── core/
│   │   ├── config.py             # Pydantic settings (reads .env)
│   │   └── database.py           # Async SQLAlchemy engine + session
│   ├── models/
│   │   ├── job.py                # ScrapeJob SQLAlchemy model
│   │   └── lead.py               # Lead SQLAlchemy model
│   ├── schemas/
│   │   ├── job.py                # Pydantic request/response schemas for jobs
│   │   └── lead.py               # Pydantic response schemas for leads
│   ├── api/v1/
│   │   ├── router.py             # Aggregates all endpoint routers
│   │   └── endpoints/
│   │       ├── scrape.py         # POST /scrape, GET /scrape/jobs/{id}
│   │       ├── leads.py          # GET/DELETE /leads, GET /leads/{id}
│   │       └── export.py         # GET /export/csv, GET /export/excel
│   └── services/
│       └── lead_engine.py        # Background job runner + export helpers
│
├── alembic/                      # Database migrations
│   ├── env.py                    # Async-compatible Alembic env
│   ├── script.py.mako            # Revision file template
│   └── versions/
│       └── 001_initial_schema.py # Initial tables + indexes
│
├── orchestrator.py               # Existing scraping engine (unchanged)
├── lead.py                       # Lead dataclass (unchanged)
├── lead_scorer.py                # Scoring algorithm (unchanged)
├── scraper_*.py                  # Individual scrapers (unchanged)
│
├── alembic.ini                   # Alembic configuration
├── requirements.txt              # Python dependencies
├── run.py                        # Dev server launcher
├── Dockerfile                    # Production container
├── docker-compose.yml            # API + PostgreSQL stack
├── .env                          # Your credentials (never commit)
└── .env.example                  # Template — copy to .env
```

---

## Quick Start (Local Development)

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in APOLLO_API_KEY and any social credentials
```

### 3. Apply database migrations

```bash
alembic upgrade head
```

This creates `leads.db` (SQLite) with the `scrape_jobs` and `leads` tables.

### 4. Start the API server

```bash
python run.py
```

- **Swagger UI** → http://localhost:8000/docs
- **ReDoc** → http://localhost:8000/redoc
- **OpenAPI JSON** → http://localhost:8000/openapi.json

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/scrape` | Start a background scraping job |
| `GET` | `/api/v1/scrape/jobs` | List all jobs |
| `GET` | `/api/v1/scrape/jobs/{job_id}` | Get job status |
| `DELETE` | `/api/v1/scrape/jobs/{job_id}` | Delete job + its leads |
| `GET` | `/api/v1/leads` | List leads (filterable) |
| `GET` | `/api/v1/leads/{lead_id}` | Get a single lead |
| `DELETE` | `/api/v1/leads/{lead_id}` | Delete a single lead |
| `DELETE` | `/api/v1/leads` | Bulk delete leads |
| `GET` | `/api/v1/export/csv` | Download CSV (LeadsFlow format) |
| `GET` | `/api/v1/export/excel` | Download color-coded Excel |
| `GET` | `/health` | Health check |

### Example: Start a scraping job

```bash
curl -X POST http://localhost:8000/api/v1/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "keyword": "plumbers",
    "location": "Austin, TX",
    "max_per_source": 25,
    "include_apis": true
  }'
```

Response (202 Accepted):
```json
{
  "id": "abc123...",
  "keyword": "plumbers",
  "location": "Austin, TX",
  "status": "pending",
  "sources": ["google","yelp","yellowpages","bbb","apollo"]
}
```

Poll for status:
```bash
curl http://localhost:8000/api/v1/scrape/jobs/abc123...
```

Get results:
```bash
curl "http://localhost:8000/api/v1/leads?job_id=abc123...&min_score=55"
```

Export:
```bash
curl "http://localhost:8000/api/v1/export/csv?job_id=abc123..." -o leads.csv
curl "http://localhost:8000/api/v1/export/excel?job_id=abc123..." -o leads.xlsx
```

---

## Available Sources

| Key | Name | Requires |
|-----|------|----------|
| `google` | Google Maps | Nothing |
| `yelp` | Yelp | Nothing |
| `yellowpages` | Yellow Pages | Nothing |
| `bbb` | Better Business Bureau | Nothing |
| `linkedin` | LinkedIn | `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` |
| `facebook` | Facebook | `FACEBOOK_EMAIL` + `FACEBOOK_PASSWORD` |
| `instagram` | Instagram | `INSTAGRAM_USERNAME` + `INSTAGRAM_PASSWORD` |
| `twitter` | Twitter/X | `TWITTER_USERNAME` + `TWITTER_PASSWORD` |
| `apollo` | Apollo.io | `APOLLO_API_KEY` |

Default sources (no login needed): `google`, `yelp`, `yellowpages`, `bbb`

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Generate a new migration after changing models
alembic revision --autogenerate -m "add column X to leads"

# View migration history
alembic history --verbose
```

---

## Production Deployment

### Docker Compose (API + PostgreSQL)

```bash
# 1. Build and start
docker-compose up --build -d

# 2. Check logs
docker-compose logs -f api

# 3. Stop
docker-compose down
```

The compose stack:
- `api` — FastAPI on port 8000, runs `alembic upgrade head` on startup
- `db` — PostgreSQL 15, data persisted in `postgres_data` volume

### Standalone Docker

```bash
docker build -t lead-gen-api .
docker run -p 8000:8000 \
  -e DATABASE_URL=sqlite+aiosqlite:///./leads.db \
  -e APOLLO_API_KEY=your_key \
  lead-gen-api
```

### Cloud Deployment (Railway / Render / Fly.io)

1. Set `DATABASE_URL` to your managed PostgreSQL connection string
2. Set all required environment variables in the platform dashboard
3. Push — the `CMD` in `Dockerfile` runs `alembic upgrade head` then starts uvicorn

---

## Lead Scoring (0–100)

| Dimension | Max | What it measures |
|-----------|-----|-----------------|
| Rating Quality | 25 | Star rating quality |
| Review Authority | 20 | Log-scaled review volume |
| Contact Richness | 20 | Phone + website + email completeness |
| Source Credibility | 15 | Trust weight of sources found in |
| Engagement | 10 | Rating x sqrt(reviews) popularity signal |
| Profile Completeness | 10 | Name, category, city, hours, zip |

**Tiers:** Hot (85+) / Strong (70+) / Good (55+) / Moderate (40+) / Weak (<40)

---

## CLI (Original Interface — Still Works)

```bash
python main.py -k "plumbers" -l "Austin, TX" --apis --best 20
```
