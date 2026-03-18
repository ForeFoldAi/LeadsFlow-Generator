# 🚀 Multi-Source Lead Engine

Scrapes leads from **5 sources simultaneously**, deduplicates them,
and ranks every lead with an **AI scoring model** (0–100 score).

---

## ⚡ Quick Start

```bash
pip install -r requirements.txt
playwright install chromium

python main.py -k "plumbers" -l "Austin, TX"
```

---

## 📊 The Ranking Model

Every lead gets a **0–100 composite score** across 6 dimensions:

| Dimension           | Max  | What it measures                                  |
|---------------------|------|---------------------------------------------------|
| ⭐ Rating Quality   | 25   | Star rating with steep penalty below 3.5          |
| 📣 Review Authority | 20   | Log-scaled volume (10 reviews ≠ 100 reviews)      |
| 📞 Contact Richness | 20   | Phone (8) + Website (7) + Address (3) + Email (2) |
| 🔗 Source Credibility| 15  | Trust weight per source + multi-source bonus      |
| 🔥 Engagement       | 10   | Rating × √reviews — popularity signal             |
| 📋 Profile Complete | 10   | Name, category, city, hours, zip filled           |

### Tiers
| Score    | Tier          | Action                              |
|----------|---------------|-------------------------------------|
| 85–100   | 🏆 Hot Lead   | Call today                          |
| 70–84    | 🔥 Strong     | High priority outreach              |
| 55–69    | ✅ Good        | Queue for follow-up                 |
| 40–54    | 👀 Moderate   | Nurture / lower priority            |
| 0–39     | ❄️ Weak       | Skip or research more               |

### Source Trust Weights (used in scoring)
| Source       | Trust |
|--------------|-------|
| Google Maps  | 1.00  |
| BBB          | 0.95  |
| LinkedIn     | 0.80  |
| Yelp         | 0.85  |
| Yellow Pages | 0.75  |

---

## 🗂️ Sources

| Key           | Site                  | Best for                     |
|---------------|-----------------------|------------------------------|
| `google`      | Google Maps           | All local businesses         |
| `yelp`        | Yelp                  | Restaurants, home services   |
| `yellowpages` | YellowPages.com       | Trades, services             |
| `bbb`         | BBB.org               | Verified/accredited only     |
| `linkedin`    | LinkedIn              | B2B, companies (needs login) |

---

## 🖥️ CLI Reference

```bash
python main.py [options]

Required:
  -k, --keyword     Search term          "plumbers"
  -l, --location    Location             "Austin, TX"

Optional:
  --sources         Sources to use       google yelp bbb   (or: all)
  --max             Max per source       25
  --min-score       Filter by score      55
  --format          Export format        excel | csv | json | all
  --output          File base name       leads
  --top             Rows in terminal     20
  --scorecards      Show top 3 breakdown
  --visible         Show browser
  --delay           Seconds between reqs 1.5
```

---

## 💡 Usage Examples

```bash
# Home services — all 4 main sources, export Excel
python main.py -k "HVAC contractors" -l "Houston, TX" --sources google yelp yellowpages bbb

# Only High-quality leads (score ≥ 70)
python main.py -k "dentists" -l "Chicago" --min-score 70 --format excel

# B2B — include LinkedIn (will prompt for credentials)
python main.py -k "marketing agencies" -l "New York" --sources all

# Full scorecards for top picks
python main.py -k "roofers" -l "Phoenix, AZ" --scorecards --top 5

# All formats at once
python main.py -k "restaurants" -l "Miami, FL" --format all
```

---

## 📁 File Structure

```
lead_engine/
├── main.py               # CLI entry point
├── orchestrator.py       # Runs scrapers, deduplicates, exports
├── lead_scorer.py        # Scoring & ranking model
├── lead.py               # Lead dataclass
├── scraper_google.py     # Google Maps scraper
├── scraper_yelp.py       # Yelp scraper
├── scraper_yellowpages.py# Yellow Pages scraper
├── scraper_bbb.py        # BBB scraper
├── scraper_linkedin.py   # LinkedIn scraper (needs login)
├── requirements.txt
└── README.md
```

---

## 🔐 LinkedIn Setup

LinkedIn requires login. Set environment variables before running:

```bash
# Windows
set LINKEDIN_EMAIL=you@email.com
set LINKEDIN_PASSWORD=yourpassword

# Mac/Linux
export LINKEDIN_EMAIL=you@email.com
export LINKEDIN_PASSWORD=yourpassword
```

Or the tool will prompt you interactively.

---

## 📤 Output (Excel)

The Excel export is color-coded by tier:
- 🟡 Gold rows = Hot Leads
- 🟠 Orange rows = Strong Leads
- 🟢 Green rows = Good Leads
- 🔵 Blue rows = Moderate Leads
- ⚫ Grey rows = Weak Leads

Columns include all 6 sub-scores so you can sort/filter by any dimension.

---

## ⚠️ Disclaimer

For educational and legitimate business research purposes only.
Respect each platform's Terms of Service and rate limits.
