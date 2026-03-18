"""
Lead Engine — CLI
=================
12 sources: scrapers + social + APIs → exports to LeadsFlow format.

  No login :  google  yelp  yellowpages  bbb
  Need login: linkedin  facebook  instagram  twitter
  API key  :  apollo  hunter  snov  rocketreach

Best for name + phone + email + company:
  python cli.py -k "schools" -l "Hyderabad" --apis
"""

import asyncio, sys, os
from datetime import datetime
from pathlib import Path

# ── Auto-load .env file on every run ─────────────────────────────────────────
def _load_env():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    loaded = []
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip(); val = val.strip()
            # Skip placeholder values
            if key and val and not val.startswith("paste_") and not val.startswith("your_"):
                os.environ.setdefault(key, val)
                loaded.append(key)
    if loaded:
        print(f"  🔑  Loaded credentials from .env: {', '.join(loaded)}")

_load_env()
# ─────────────────────────────────────────────────────────────────────────────

from app.services.orchestrator import (LeadEngine, ALL_SOURCES,
                                        DEFAULT_SOURCES, SOCIAL_SOURCES, API_SOURCES)

API_ENV_HINTS = {
    "apollo":      ("APOLLO_API_KEY",      "https://app.apollo.io → Settings → API Keys"),
    "hunter":      ("HUNTER_API_KEY",      "https://hunter.io → Dashboard → API  (Gmail OK)"),
    "snov":        ("SNOV_CLIENT_ID",      "https://snov.io → Settings → API  (Gmail OK)"),
    "rocketreach": ("ROCKETREACH_API_KEY", "https://rocketreach.co → Account → API  (Gmail OK)"),
}
SOCIAL_ENV_HINTS = {
    "linkedin":  "LINKEDIN_EMAIL, LINKEDIN_PASSWORD",
    "facebook":  "FACEBOOK_EMAIL, FACEBOOK_PASSWORD",
    "instagram": "INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD",
    "twitter":   "TWITTER_USERNAME, TWITTER_PASSWORD",
}


def parse_args():
    import argparse
    p = argparse.ArgumentParser(
        description="🚀 Lead Engine — 12 sources → LeadsFlow CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
── Source groups ──────────────────────────────────────────
  --sources google yelp yellowpages bbb   (default, no login)
  --social    adds linkedin facebook instagram twitter
  --apis      adds apollo hunter snov rocketreach  ← best for email+phone
  --sources all   all 12 sources

── Quick examples ─────────────────────────────────────────
  python cli.py -k "schools"  -l "Hyderabad" --apis --best 5
  python cli.py -k "plumbers" -l "Hyderabad"
  python cli.py -k "doctors"  -l "Mumbai"    --sources hunter google
  python cli.py -k "lawyers"  -l "Delhi"     --sources apollo google --best 10
        """,
    )
    p.add_argument("-k", "--keyword",    required=True)
    p.add_argument("-l", "--location",   required=True)
    p.add_argument("--sources",  nargs="+", default=None,
                   help='Specific sources. "all" = all 12.')
    p.add_argument("--social",   action="store_true",
                   help="Add social sources (LinkedIn/Facebook/Instagram/Twitter)")
    p.add_argument("--apis",     action="store_true",
                   help="Add API sources (Apollo/Hunter/Snov/RocketReach) — best for email+phone")
    # API keys
    p.add_argument("--apollo-key",      default="", help="Apollo.io API key")
    p.add_argument("--hunter-key",      default="", help="Hunter.io API key")
    p.add_argument("--snov-id",         default="", help="Snov.io Client ID")
    p.add_argument("--snov-secret",     default="", help="Snov.io Client Secret")
    p.add_argument("--rocketreach-key", default="", help="RocketReach API key")
    # Run options
    p.add_argument("--max",       type=int,   default=25)
    p.add_argument("--best",      type=int,   default=0,
                   help="Export only top N leads")
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--country",   default="India")
    p.add_argument("--format",    choices=["csv","excel","both"], default="csv")
    p.add_argument("--output",    default="leadsflow")
    p.add_argument("--top",       type=int,   default=20)
    p.add_argument("--scorecards", action="store_true")
    p.add_argument("--visible",   action="store_true")
    p.add_argument("--delay",     type=float, default=1.5)
    return p.parse_args()


async def main():
    args = parse_args()

    # ── Resolve sources ───────────────────────────────────────────────────────
    if args.sources and "all" in args.sources:
        sources = ALL_SOURCES
    elif args.sources:
        sources = args.sources
    else:
        sources = list(DEFAULT_SOURCES)
        if args.social: sources += SOCIAL_SOURCES
        if args.apis:   sources += API_SOURCES

    invalid = [s for s in sources if s not in ALL_SOURCES]
    if invalid:
        print(f"❌  Unknown sources: {invalid}")
        print(f"   Valid: {ALL_SOURCES}")
        sys.exit(1)

    # ── Inject API keys into env ──────────────────────────────────────────────
    key_map = {
        "APOLLO_API_KEY":      args.apollo_key,
        "HUNTER_API_KEY":      args.hunter_key,
        "SNOV_CLIENT_ID":      args.snov_id,
        "SNOV_CLIENT_SECRET":  args.snov_secret,
        "ROCKETREACH_API_KEY": args.rocketreach_key,
    }
    for env_var, val in key_map.items():
        if val:
            os.environ[env_var] = val

    # ── Print setup reminders ─────────────────────────────────────────────────
    api_needed    = [s for s in sources if s in API_SOURCES]
    social_needed = [s for s in sources if s in SOCIAL_SOURCES]

    if api_needed:
        print("\n  ℹ️   API sources included. Keys needed (all accept Gmail signup):")
        for s in api_needed:
            env_var, url = API_ENV_HINTS[s]
            already_set  = "✅ set" if os.getenv(env_var) else "❌ not set"
            print(f"      {s:<14} {already_set:<10} get key: {url}")
        print()

    if social_needed:
        print("  ℹ️   Social sources included. Login env vars needed:")
        for s in social_needed:
            print(f"      {SOCIAL_ENV_HINTS[s]}")
        print()

    # ── Run ───────────────────────────────────────────────────────────────────
    engine = LeadEngine(
        sources        = sources,
        max_per_source = args.max,
        delay          = args.delay,
        headless       = not args.visible,
        min_score      = args.min_score,
        country        = args.country,
    )

    leads = await engine.run(args.keyword, args.location)
    if not leads:
        print("\n❌  No leads found.")
        sys.exit(1)

    if args.best > 0:
        engine.leads = engine.leads[:args.best]
        print(f"\n  🏆  Keeping top {args.best} leads")

    engine.print_summary(top_n=args.top)
    if args.scorecards:
        engine.print_top_scorecards(n=min(3, len(engine.leads)))

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = args.keyword.replace(" ", "_").lower()
    base = f"{args.output}_{slug}_{ts}"

    if args.format in ("csv",   "both"): engine.to_csv(f"{base}.csv")
    if args.format in ("excel", "both"): engine.to_excel(f"{base}.xlsx")

    n = len(engine.leads)
    print(f"\n✅  {n} lead{'s' if n!=1 else ''} exported → ready for LeadsFlow!\n")


if __name__ == "__main__":
    asyncio.run(main())
