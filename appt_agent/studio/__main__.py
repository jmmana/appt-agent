"""python -m appt_agent.studio"""
from __future__ import annotations
import os
import argparse
from appt_agent.studio.app import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="appt-agent-studio")
    parser.add_argument("--host",     default="0.0.0.0")
    parser.add_argument("--port",     type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--data-dir", default=os.environ.get("APPT_DATA_DIR", "/data"))
    parser.add_argument("--reload",   action="store_true")
    args = parser.parse_args()

    print(f"🗓️  appt-agent studio")
    print(f"   http://{args.host}:{args.port}")
    print(f"   Data dir: {args.data_dir}")
    serve(data_dir=args.data_dir, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
