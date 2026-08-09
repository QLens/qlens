"""The ``qlens`` command line.

    qlens view data/traces/traces.jsonl
    qlens view data/traces.db --state-dir data/qstates --port 9000
    qlens view --demo
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import webbrowser
from pathlib import Path

import qlens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qlens", description=__doc__)
    parser.add_argument("--version", action="version", version=f"qlens {qlens.__version__}")
    sub = parser.add_subparsers(dest="command")

    view = sub.add_parser("view", help="open the circuit viewer on a trace source")
    view.add_argument(
        "source",
        nargs="?",
        help="a TraceAct .jsonl file, folder, or SqliteSink .db",
    )
    view.add_argument(
        "--demo",
        action="store_true",
        help="generate sample runs and open on those instead of a source",
    )
    view.add_argument(
        "--state-dir",
        default="data/qstates",
        help="directory holding statevector sidecar files (default: data/qstates)",
    )
    view.add_argument("--host", default="127.0.0.1")
    view.add_argument("--port", type=int, default=8766)
    view.add_argument("--no-browser", action="store_true")

    args = parser.parse_args(argv)
    if args.command != "view":
        parser.print_help()
        return 2

    source, state_dir = args.source, args.state_dir
    if args.demo:
        from qlens.viewer._demo import generate

        # A fresh directory per launch, so the demo never accumulates
        # runs across sessions or collides with a real trace file.
        demo_dir = Path(tempfile.mkdtemp(prefix="qlens-demo-"))
        source, state_dir = generate(demo_dir)
        print(f"qlens: generated sample runs in {demo_dir}")
    elif not source:
        print(
            "qlens: view needs a trace source, or --demo for sample runs",
            file=sys.stderr,
        )
        return 2
    elif not Path(source).exists():
        print(f"qlens: source {source!r} does not exist", file=sys.stderr)
        return 1

    from qlens.viewer.server import serve

    server = serve(source, state_dir=state_dir, host=args.host, port=args.port)
    host_part, port_part = server.server_address[0], server.server_address[1]
    if isinstance(host_part, bytes):
        host_part = host_part.decode()
    url = f"http://{host_part}:{port_part}/"
    print(f"qlens viewer on {url} (source: {source})")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nqlens viewer stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
