"""
Demo web app: Jev vs CLM, side by side.

    pip install -r requirements.txt
    uvicorn webapp.app:app --port 8000        (run from the repository root)
    open http://localhost:8000

Pages
  /        overview + model status
  /cube    Rubik's Cube race (one decision per move, judged by an exact solver)
  /scam    Berlin rental-scam detector (red-flag checklist)
  /guard   Beat the Guard (prompt-injection game)

Every page sends the identical request to both models at the same time and
shows answer, confidence and measured latency next to each other.
"""

from __future__ import annotations

import random
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "rubric-cube-demo", "scam-detector-demo", "beat-the-guard-demo"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from agents import recorded as cube_rec  # noqa: E402
from agents.players import PLAYERS, decide, judge, state_key  # noqa: E402
from cube.cube_state import ALL_MOVES, apply_move, is_solved, stickers_in_place  # noqa: E402
from cube.oracle import MAX_EXACT, distance, warm_up  # noqa: E402
from cube.scrambler import scramble_exact  # noqa: E402
from guard import recorded as guard_rec  # noqa: E402
from guard.game import DEFAULT_DEFENDER, GuardGame  # noqa: E402
from scam import recorded as scam_rec  # noqa: E402
from scam.detector import MODELS as SCAM_MODELS, RED_FLAGS, analyze_listing, load_examples  # noqa: E402
from system_one import SystemOneClient  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
state: dict = {}


@asynccontextmanager
async def lifespan(_app):
    warm_up()
    state["client"] = SystemOneClient()
    state["guard"] = GuardGame(state["client"])
    yield
    await state["guard"].aclose()
    await state["client"].aclose()


app = FastAPI(title="System One demos", lifespan=lifespan)


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """Pages and scripts change together: make the browser re-check them on every load,
    so an updated page never runs against an old cached common.js (which breaks it)."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _page(name: str):
    return FileResponse(STATIC / f"{name}.html")


@app.get("/", include_in_schema=False)
def index():
    return _page("index")


@app.get("/cube", include_in_schema=False)
def cube_page():
    return _page("cube")


@app.get("/scam", include_in_schema=False)
def scam_page():
    return _page("scam")


@app.get("/guard", include_in_schema=False)
def guard_page():
    return _page("guard")


@app.get("/api/health")
async def health():
    return await state["client"].health()


# ── Rubik's Cube race ─────────────────────────────────────────────────────────

class StepIn(BaseModel):
    player: str
    state: list[int] = Field(min_length=54, max_length=54)
    last_move: str | None = None
    constrain: bool = True
    # for the "never return to an earlier position" rule: where this player started and its moves so far
    start_state: list[int] | None = None
    history: list[str] = Field(default_factory=list, max_length=2000)
    no_repeat: bool = True


@app.get("/api/cube/new")
def cube_new(level: int = 3, seed: int | None = None):
    if not 1 <= level <= MAX_EXACT:
        raise HTTPException(400, f"level must be 1-{MAX_EXACT}")
    seed = seed if seed is not None else random.randint(1, 99999)
    s, moves = scramble_exact(level, seed=seed)
    return {"state": s, "scramble": moves, "distance": level, "seed": seed,
            "players": PLAYERS, "in_place": stickers_in_place(s)}


@app.post("/api/cube/step")
async def cube_step(body: StepIn):
    if body.player not in PLAYERS:
        raise HTTPException(400, "unknown player")
    if sorted(body.state) != sorted([c for c in range(6) for _ in range(9)]):
        raise HTTPException(400, "not a valid sticker set")
    visited = None
    if body.no_repeat and body.start_state:
        s = list(body.start_state)
        visited = {state_key(s)}
        for m in body.history:
            if m not in ALL_MOVES:
                raise HTTPException(400, f"unknown move {m!r}")
            s = apply_move(s, m)
            visited.add(state_key(s))
    res = await decide(body.player, body.state, body.last_move, state["client"], body.constrain,
                       visited=visited)
    res.pop("request", None)   # the full prompt is logged by record.py; the browser doesn't need it
    res.pop("answers", None)
    out = {**res, "distance_before": distance(body.state), "optimal_moves": [],
           "distance_after": None, "state_after": None, "solved": False, "verdict": None}
    if res["ok"]:
        nxt = apply_move(body.state, res["move"])
        out.update(state_after=nxt, solved=is_solved(nxt), in_place=stickers_in_place(nxt),
                   **judge(body.state, res["move"], body.last_move, body.constrain, visited))
    return out


# ── Scam detector ─────────────────────────────────────────────────────────────

class ListingIn(BaseModel):
    text: str = Field(min_length=10, max_length=6000)
    title: str | None = None
    rent_eur: float | None = None
    size_m2: float | None = None
    district: str | None = None


@app.get("/api/scam/examples")
def scam_examples():
    return {"examples": load_examples(), "flags": RED_FLAGS, "models": SCAM_MODELS}


@app.post("/api/scam/analyze")
async def scam_analyze(body: ListingIn):
    return await analyze_listing(state["client"], body.model_dump())


# ── Beat the Guard ────────────────────────────────────────────────────────────

class GuardIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    player: str = Field(default="anonymous", max_length=40)
    defender: str = DEFAULT_DEFENDER
    threshold: float = Field(default=0.5, ge=0.05, le=0.95)


@app.post("/api/guard/message")
async def guard_message(body: GuardIn):
    return await state["guard"].play(body.text, body.player, body.defender, body.threshold)


class GuessIn(BaseModel):
    guess: str = Field(min_length=1, max_length=100)
    player: str = Field(default="anonymous", max_length=40)


@app.post("/api/guard/guess")
def guard_guess(body: GuessIn):
    """Check a guessed password: proves a leak (even by hint or translation) really worked."""
    return state["guard"].guess(body.guess, body.player)


@app.get("/api/guard/leaderboard")
def guard_leaderboard():
    return state["guard"].leaderboard()


@app.get("/api/guard/info")
def guard_info():
    return state["guard"].info()


@app.post("/api/guard/reset")
def guard_reset():
    state["guard"].reset()
    return {"ok": True}


# ── Recorded runs (replay) ────────────────────────────────────────────────────
# Written by the record.py scripts. Each model was recorded on its own, one call
# at a time; the browser replays the calls at their recorded speed.

def _found(x):
    if x is None:
        raise HTTPException(404, "not recorded")
    return x


@app.get("/api/replay/cube/catalog")
def replay_cube_catalog():
    return cube_rec.catalog()


@app.get("/api/replay/cube/game")
def replay_cube_game(level: int, seed: int):
    return _found(cube_rec.replay_game(level, seed))


@app.get("/api/replay/cube/raw")
def replay_cube_raw(level: int, seed: int, player: str):
    return _found(cube_rec.raw_game(level, seed, player))


@app.get("/api/replay/scam/catalog")
def replay_scam_catalog():
    return scam_rec.catalog()


@app.get("/api/replay/scam/listing")
def replay_scam_listing(id: str):
    return _found(scam_rec.replay_listing(id))


@app.get("/api/replay/scam/raw")
def replay_scam_raw(id: str, provider: str):
    return _found(scam_rec.raw_calls(id, provider))


@app.get("/api/replay/guard/catalog")
def replay_guard_catalog():
    return guard_rec.catalog()


@app.get("/api/replay/guard/attack")
def replay_guard_attack(id: str, defender: str = DEFAULT_DEFENDER, threshold: float = 0.5):
    return _found(guard_rec.replay_attack(id, defender, min(max(threshold, 0.05), 0.95)))


@app.get("/api/replay/guard/raw")
def replay_guard_raw(id: str, provider: str):
    return _found(guard_rec.raw_calls(id, provider))
