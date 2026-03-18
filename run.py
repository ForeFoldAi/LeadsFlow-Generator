"""
Development server launcher.

Usage:
    python run.py                  # localhost:8000, auto-reload on file changes
    python run.py --port 9000      # custom port
    python run.py --no-reload      # disable auto-reload (e.g. for staging)
"""
import argparse
import uvicorn


def parse_args():
    p = argparse.ArgumentParser(description="Start the Lead Generation API server")
    p.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=9000, help="Bind port (default: 8000)")
    p.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
    p.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(f"\n  Lead Generation API")
    print(f"  Swagger UI  → http://localhost:{args.port}/docs")
    print(f"  ReDoc       → http://localhost:{args.port}/redoc\n")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        workers=args.workers if args.no_reload else 1,
        log_level="info",
    )
