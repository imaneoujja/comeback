"""Run the COMEBACK demo server: ``python -m comeback`` then open http://localhost:8000."""

import argparse
import logging

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="COMEBACK demo server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(f"\n  COMEBACK is running → http://localhost:{args.port}\n")
    uvicorn.run("comeback.api.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
