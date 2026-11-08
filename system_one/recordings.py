"""
Record model calls to disk, and load them again for replay.

Why: in a lecture, a live call can fail (hall wifi, GPU box, an API outage).
So each model is recorded on its own, one call at a time, and the web app
replays the log at the recorded speed. A recorded answer is exactly what the
model returned. Nothing is re-generated or edited.

Layout
    recordings/<demo>/<session_id>.jsonl      (one file per model per recording session)

Each file is JSON Lines:
    {"type": "session", ...}     first line: when, where, which model, network ping
    {"type": "call", ...}        one per model call: full request, answers, latency, context
    {"type": "<event>", ...}     demo-specific markers, e.g. "run_start" / "run_end"

API keys are never written. Files are appended line by line, so an interrupted
recording keeps everything up to the last finished call.

Set SYSTEM_ONE_RECORDINGS to use another folder (the tests do this).
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def recordings_dir() -> Path:
    default = Path(__file__).resolve().parent.parent / "recordings"
    return Path(os.getenv("SYSTEM_ONE_RECORDINGS", default))


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Recorder:
    """Writes one session (one demo, one model) to recordings/<demo>/<session_id>.jsonl."""

    def __init__(self, demo: str, provider: str, where: str | None = None, note: str | None = None):
        self.demo, self.provider = demo, provider
        self.session_id = f"{datetime.now():%Y%m%d-%H%M%S}-{provider}"
        self.path = recordings_dir() / demo / f"{self.session_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.where, self.note = where, note
        self.seq = 0

    def _write(self, obj: dict):
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def start(self, provider_info: dict | None = None, ping: dict | None = None, **extra):
        info = dict(provider_info or {})
        info.pop("api_key", None)  # never record secrets
        self._write({
            "type": "session", "schema": SCHEMA_VERSION, "demo": self.demo, "session_id": self.session_id,
            "provider": self.provider, "recorded_at": _now(), "where": self.where, "note": self.note,
            "provider_info": info, "ping": ping,
            "client": {"python": sys.version.split()[0], "platform": platform.platform(terse=True)},
            **extra,
        })

    def call(self, request: dict | None, result=None, context: dict | None = None, **fields):
        """Log one call. `result` is a system_one Result (or None for non-model players)."""
        self.seq += 1
        line: dict[str, Any] = {"type": "call", "session_id": self.session_id, "seq": self.seq,
                                "t": _now(), "provider": self.provider, "request": request,
                                "context": context or {}}
        if result is not None:
            line.update(ok=result.ok, error=result.error, model=result.model,
                        latency_ms=round(result.latency_ms, 2),
                        server_ms=result.server_ms,
                        answers={k: asdict(a) for k, a in result.answers.items()})
        line.update(fields)
        self._write(line)

    def event(self, kind: str, **data):
        self._write({"type": kind, "session_id": self.session_id, "t": _now(), **data})


def load_sessions(demo: str) -> list[dict]:
    """All sessions for a demo, oldest first: {"header", "calls", "events", "file"}."""
    folder = recordings_dir() / demo
    sessions = []
    for path in sorted(folder.glob("*.jsonl")):
        header, calls, events = None, [], []
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue  # a half-written last line from an interrupted run
                kind = obj.get("type")
                if kind == "session":
                    header = obj
                elif kind == "call":
                    calls.append(obj)
                else:
                    events.append(obj)
        if header:
            sessions.append({"header": header, "calls": calls, "events": events, "file": path.name})
    sessions.sort(key=lambda s: s["header"].get("recorded_at", ""))
    return sessions


def session_meta(session: dict) -> dict:
    """What the UI shows about a recording."""
    h = session["header"]
    models = sorted({c.get("model") for c in session["calls"] if c.get("model")})
    return {"session_id": h["session_id"], "provider": h["provider"], "recorded_at": h.get("recorded_at"),
            "where": h.get("where"), "note": h.get("note"), "file": session["file"],
            "ping_ms": (h.get("ping") or {}).get("median_ms"), "models": models,
            "calls": len(session["calls"])}
