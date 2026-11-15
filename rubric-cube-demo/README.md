# Cube race

Jev and CLM play the same scrambled Rubik's cube, one move at a time. A perfect solver referees every move, and two baselines (a random mover and the perfect solver itself) show the floor and the ceiling.

![Cube race: Jev, CLM-8B and the perfect solver after replaying the same recorded cube](docs/race.png)

<sub>Screenshot from a rehearsal with the mock server (model names `mock-jev` / `mock-clm`), so the numbers are not real results.</sub>


> Why the models struggle here, with the measurement behind it: [docs/README.md, section 8](../docs/README.md#8-where-it-breaks-the-guard-and-the-cube). Every move is also listed in the page's **decision log** (player, move, probability, top alternatives, the solver's verdict, time), downloadable as CSV.

## What the audience sees

* **One lane per player**, always in the same colour: Jev indigo, CLM teal, BHT Medium (optional chat LLM) pink, random grey, perfect solver gold.
* **The cube in 3D** (drag to rotate, all lanes turn together) or **unfolded in 2D**, after every move, with the face that was just turned outlined.
* **A stopwatch** counting while the model "thinks", then freezing on the measured time.
* **Every move graded** by the referee: <code>optimal</code> (one step closer, the best possible), <code>neutral</code> (no progress), <code>worse</code> (further away).
* **The top 3 choices** with probabilities, so you can see how sure the model was.
* **A chart of "moves left to solve"** per player, plus a summary over *every* recorded cube.

![Summary over all recorded cubes, and the distance-to-solved chart](docs/summary-and-chart.png)

## What happens under the hood

**What the models read.** Kept short on purpose (`agents/players.py`). Both models get the same cube text:

* **Six 3x3 grids of colour names**, each with one phrase that fixes how it is drawn ("Front face (green centre), seen from the front, top edge at the top"), plus the previous move.

On top of that:

* **Gemma (BHT Medium)** also gets one line per allowed move with where its stickers go, read off the engine, for example "R: turn the right face (red centre) clockwise as seen from the right: front face's right column → top face's right column; top face's right column → back face's left column (flipped); …". It may think it through and ends with "Final move: X".
* **CLM** gets the moves as short, distinct answers ("R: turn the right face (red centre) clockwise"). It compares the cube text with each answer text, so long, near-identical answers made it pick the same favourite every turn (e.g. F2 over and over). `python tools/tune_cube.py` compares three ways of asking CLM on 21 cubes and also counts how many different moves it picks, so a stuck model shows up as a number. Switch with `CUBE_CLM_DESIGN` in `.env`.
* **A test proves the move lines are enough:** applying every move using only its text reproduces the engine exactly on random cubes.
* **The history colours** (green optimal, amber neutral, red worse) are the referee's grades for the audience. The models never see them; that would give the answer away.

**The engine is checked against an independent solver.** For every one of the 18 moves, Kociemba's two-phase solver returns exactly the inverse move, and its solutions solve our scrambles (`tests/test_cube.py`, runs when `pip install kociemba` is available). So when a model struggles, the cube is not the problem.

**The LLM player** (BHT Medium) may think out loud, then ends with "Final move: X". The app takes that final move, not the first move it mentions.


```mermaid
flowchart LR
    S[Cube state<br/>54 stickers] --> T[Describe it in text<br/>6 faces as 3x3 colour grids]
    T --> Q["Typed question<br/>choice: which move?<br/>15–18 options"]
    Q --> J[Jev]
    Q --> C[CLM-8B]
    J --> M[Chosen move +<br/>probabilities]
    C --> M
    M --> A[Code applies the move]
    A --> R[Referee: exact solver<br/>distance before / after]
    R --> S
```

Each turn is one **System One decision**: unstructured state in, one typed choice out. The surrounding code does only two things, the "smart if-statement" pattern:

1. **It limits the options.** With the default rule, a model may not turn the same face twice in a row (that is always wasteful), so it chooses from 15 moves instead of 18.
2. **It applies the chosen move.** The model never edits the cube itself.

### The exact request both models get

Both models receive byte-for-byte the same request (`agents/players.py`):

```text
state:
  A Rubik's cube. Each face is a 3x3 grid of sticker colours, as seen when looking straight at that face.
  Top face (white centre):
    white white green
    ...
  Stickers already matching their face's centre: 38 of 54.
  Previous move: R.
  Goal: solve the cube so every face shows a single colour.

question (choice): Which single move brings this Rubik's cube closest to being solved?
  U  : "U: turn the top face (white centre) a quarter turn clockwise"
  U' : "U': turn the top face (white centre) a quarter turn counter-clockwise"
  U2 : "U2: turn the top face (white centre) a half turn (180°)"
  ... (15 or 18 options)
```

The **Raw log** link under each lane shows the full request and response for every move.

### The referee

`cube/oracle.py` knows the exact number of moves left for any cube up to 7 moves from solved:

* At start-up it searches outward from the solved cube and stores every state within 4 moves (46,741 states, under a second).
* To measure a cube, it searches up to 3 moves forward from it and looks the results up in that table.
* 4 + 3 means the answer is exact up to 7 moves. Beyond that the page shows "7+".

That's why the difficulty levels are 1–7: level 3 means "exactly 3 perfect moves solve it", checked by the referee, not just 3 random turns.

### The cube engine

`cube/cube_state.py` derives every move from 3D geometry: each sticker has a position and a direction, the layer is rotated 90°, and the code reads off where each sticker landed. The first version used hand-typed move tables, and three of six moves were wrong (U and D turned backwards, and B produced unsolvable cubes). The tests now check every move against standard reference strings and known facts, e.g. (R U) repeated 105 times returns to solved.

## How to run it

**In the web app** (from the repository root): `uvicorn webapp.app:app --port 8000`, then open http://localhost:8000/cube.

**Recorded (default).** Each player is recorded on its own, one move at a time, and the page replays the moves at their real speed. Record before the lecture, from this folder:

```bash
python -m runner.record --players clm random oracle --levels 2 3 4 --cubes 10 --where "GPU box, BHT"
python -m runner.record --players jev --levels 2 3 4 --cubes 10 --where "Laptop, Berlin"
```

Cube *k* at level *L* always has the same scramble, so recordings from different machines and days line up cube by cube. "New cube" on the page picks a recorded cube at random, and the summary table always covers all of them.

**Live.** Switch the page to Live: every move asks the models right now.

**In the terminal:**

```bash
python -m runner.race --level 3 --players jev clm random oracle
python -m pytest tests            # engine, solver and scrambler tests
```

## Files

| File | What it does |
| :--- | :--- |
| `cube/cube_state.py` | Sticker layout, the 18 moves (derived from 3D geometry), helpers |
| `cube/oracle.py` | Exact "moves left to solve" referee (up to 7 moves) |
| `cube/scrambler.py` | Seeded scrambles; `scramble_exact()` gives a cube exactly N moves from solved |
| `agents/players.py` | The players (Jev, CLM, BHT Medium, random, perfect solver), the shared request, the `play()` game loop and the `judge()` referee call |
| `agents/recorded.py` | Loads recordings for replay and builds the summary |
| `runner/record.py` | Records games, one player at a time |
| `runner/race.py` | Live race in the terminal |
| `tests/test_cube.py` | Engine and solver tests |

The web page itself is in `../webapp/static/cube.html` and `cube.js`.

## Talking points

* **Speed adds up.** A model that needs 400 ms per move needs 4 s for 10 moves. This is why System One latency matters for agents that take many steps.
* **The honest limit.** Solving a cube means planning several moves ahead; a one-shot decision model only sees the next move. Expect Jev and CLM to be much closer to the random mover than to the perfect solver. That's the System 1 vs System 2 point of the talk: use the fast model for the decision at hand, and planning or search (or a System 2 model) for the long game.
* **System 1 vs System 2, live.** Tick *BHT Medium (LLM)* to add a chat model (`bht/medium` on BHT's LUMIS; needs `BHT_LLM_INF_API_KEY` in your environment). It gets the same cube description and move list, writes its answer as text, and the app parses a move out of it. Compare seconds per move and the optimal-move rate: writing more is not the same as planning ahead. It also gives no probabilities, only text. Record it like the others: `python -m runner.record --players llm --levels 2 3 4 --cubes 10`.
* **What to compare.** The optimal-move rate against the random mover's shows whether a model has *any* sense of the cube. Usually only one or two of the 15–18 moves are optimal, so random play scores about 7%. Time per move shows the cost.
