"""The Qlens viewer server.

Stdlib-only, same shape as TraceAct's viewer: a ThreadingHTTPServer
serving three static files and a small JSON API over one trace source.
Trace reading goes through traceact.TraceLog (which handles JSONL files,
folders, SQLite sources, and in-flight stub dedup); statevectors resolve
from the spool directory's sidecar files.

API:
    GET /api/health                     {"status","version","source"}
    GET /api/circuits                   circuit runs, newest first
    GET /api/circuit?trace_id=          one run: layers, gates, markers
    GET /api/state?trace_id=&position=  amplitudes at a captured position
    GET /api/stream                     SSE: new/updated runs as they land
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np

import qlens
from qlens._errors import QlensError
from qlens.tracing._spool import spool_path

_STATIC_DIR = Path(__file__).parent / "static"
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}
_STREAM_POLL_SECONDS = 1.0


class ViewerState:
    """Shared source configuration for all request threads."""

    def __init__(self, source: str, state_dir: str) -> None:
        self.source = source
        self.state_dir = state_dir

    def log(self) -> Any:
        from traceact import TraceLog

        return TraceLog(self.source).filter(action="circuit.run")


def _run_summary(record: dict[str, Any]) -> dict[str, Any]:
    events = record.get("events") or []
    assertions = [e for e in events if e.get("kind") == "assertion"]
    meta = record.get("meta") or {}
    return {
        "trace_id": record.get("trace_id"),
        "status": record.get("status"),
        "in_flight": bool(record.get("in_flight")),
        "started_at": record.get("started_at"),
        "duration_ms": record.get("duration_ms"),
        "correlation_id": record.get("correlation_id"),
        "project": record.get("project"),
        "backend": meta.get("backend"),
        "num_qubits": meta.get("num_qubits"),
        "gate_count": meta.get("gate_count"),
        "capture_mode": meta.get("capture_mode"),
        "assertions_total": len(assertions),
        "assertions_failed": sum(1 for a in assertions if a.get("status") == "failed"),
    }


def _circuit_detail(record: dict[str, Any]) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    qstates: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    for event in record.get("events") or []:
        kind = event.get("kind")
        if kind == "gate":
            if event.get("operation") == "apply_layer":
                layers.append(
                    {
                        "index": event.get("position"),
                        "qubits": event.get("qubits", []),
                        "gates": event.get("gates", []),
                    }
                )
            else:
                layers.append(
                    {
                        "index": event.get("position"),
                        "qubits": event.get("qubits", []),
                        "gates": [
                            {
                                "gate": event.get("gate"),
                                "qubits": event.get("qubits", []),
                                "params": event.get("params", {}),
                                "position": event.get("position"),
                            }
                        ],
                    }
                )
        elif kind == "qstate":
            qstates.append(
                {
                    "position": event.get("position"),
                    "statevector_ref": event.get("statevector_ref"),
                    "norm_check": event.get("norm_check"),
                }
            )
        elif kind == "assertion":
            assertions.append(
                {
                    "assertion": event.get("assertion"),
                    "target": event.get("target"),
                    "status": event.get("status"),
                    "error": event.get("error"),
                    "started_at": event.get("started_at"),
                }
            )
    detail = _run_summary(record)
    detail.update({"layers": layers, "qstates": qstates, "assertions": assertions})
    return detail


class _Handler(BaseHTTPRequestHandler):
    state: ViewerState  # assigned by serve()

    # -- plumbing ----------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:
        pass  # request logging off; this is a local dev tool

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int) -> None:
        self._send_json({"error": message}, status)

    # -- routing -----------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        try:
            if route == "/api/health":
                self._send_json(
                    {"status": "ok", "version": qlens.__version__, "source": self.state.source}
                )
            elif route == "/api/circuits":
                self._serve_circuits()
            elif route == "/api/circuit":
                self._serve_circuit(query)
            elif route == "/api/state":
                self._serve_state(query)
            elif route == "/api/stream":
                self._serve_stream()
            elif route == "/":
                self._serve_static("index.html")
            elif route.startswith("/static/"):
                self._serve_static(route[len("/static/") :])
            else:
                self._send_error_json("not found", 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # a broken request must not kill the thread
            self._send_error_json(f"{type(exc).__name__}: {exc}", 500)

    # -- endpoints ---------------------------------------------------------

    def _serve_circuits(self) -> None:
        result = self.state.log().query(n=500)
        runs = [_run_summary(r) for r in result["traces"]]
        self._send_json({"circuits": runs, "scan_capped": result["scan_capped"]})

    def _record_by_id(self, query: dict[str, list[str]]) -> dict[str, Any] | None:
        trace_id = (query.get("trace_id") or [""])[0]
        if not trace_id:
            self._send_error_json("expected ?trace_id=", 400)
            return None
        matches = self.state.log().filter(trace_id=trace_id).all()
        if not matches:
            self._send_error_json(f"unknown trace_id {trace_id}", 404)
            return None
        return dict(matches[-1])

    def _serve_circuit(self, query: dict[str, list[str]]) -> None:
        record = self._record_by_id(query)
        if record is not None:
            self._send_json(_circuit_detail(record))

    def _serve_state(self, query: dict[str, list[str]]) -> None:
        record = self._record_by_id(query)
        if record is None:
            return
        trace_id = str(record.get("trace_id"))
        try:
            position = int((query.get("position") or ["-1"])[0])
        except ValueError:
            self._send_error_json("position must be an integer", 400)
            return

        path = spool_path(self.state.state_dir, trace_id)
        if not path.is_file():
            self._send_error_json(
                f"no statevector sidecar for {trace_id}; check --state-dir", 404
            )
            return
        with np.load(path) as archive:
            positions = sorted(int(k[4:]) for k in archive.files)
            if position == -1:
                position = positions[-1]
            if position not in positions:
                self._send_error_json(
                    f"position {position} not captured (available: "
                    f"{positions[0]}..{positions[-1]})",
                    404,
                )
                return
            state = np.asarray(archive[f"pos_{position}"], dtype=np.complex128)

        num_qubits = int((record.get("meta") or {}).get("num_qubits", 0))
        self._send_json(
            {
                "trace_id": trace_id,
                "position": position,
                "captured_positions": positions,
                "num_qubits": num_qubits,
                "basis_labels_big_endian": True,
                "amplitudes": [[float(a.real), float(a.imag)] for a in state],
            }
        )

    def _serve_stream(self) -> None:
        """SSE: emit each run summary once, then again whenever its
        status or event count changes. Poll-based over TraceLog, which
        re-reads the source on every call."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        seen: dict[str, tuple[Any, int]] = {}
        while True:
            for record in self.state.log().query(n=500)["traces"]:
                trace_id = str(record.get("trace_id"))
                fingerprint = (record.get("status"), len(record.get("events") or []))
                if seen.get(trace_id) != fingerprint:
                    seen[trace_id] = fingerprint
                    payload = json.dumps(_run_summary(record))
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            time.sleep(_STREAM_POLL_SECONDS)

    def _serve_static(self, filename: str) -> None:
        safe_name = Path(filename).name  # basename only: no traversal
        path = _STATIC_DIR / safe_name
        if not path.is_file():
            self._send_error_json("not found", 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", _CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def serve(
    source: str,
    *,
    state_dir: str,
    host: str = "127.0.0.1",
    port: int = 8766,
    max_port_tries: int = 20,
) -> ThreadingHTTPServer:
    """Bind and return the server (caller drives serve_forever). Tries
    up to ``max_port_tries`` consecutive ports from ``port``."""
    handler = type("BoundHandler", (_Handler,), {"state": ViewerState(source, state_dir)})
    last_error: OSError | None = None
    for candidate in range(port, port + max_port_tries):
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            last_error = exc
    raise QlensError(
        f"no free port in {port}..{port + max_port_tries - 1}: {last_error}"
    )
