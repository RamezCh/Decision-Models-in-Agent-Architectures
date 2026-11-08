# Beyond Generative LLMs: System 1 Decision Models (Jev & Open-CLM-8B)

This repository contains the presentation plan, slide outline, architecture benchmarks, and a live proof-of-concept demo comparing **Typesafe Jev** and Stanford/NVIDIA's **Open-CLM-8B** against traditional auto-regressive large language models.

---

## 📌 Presentation Overview

* **Format:** 20-minute Presentation + 10-minute Technical Q&A
* **Team Size:** 4 Presenters (~5 minutes per speaker)
* **Core Theme:** Why generating tokens is the wrong computational primitive for agent routing and tool selection, how contrastive and calibrated decision models work under the hood, and how to build production hybrid pipelines.

```text
00:00 - 05:00       05:00 - 10:00       10:00 - 15:00       15:00 - 20:00       20:00 - 30:00
[ Speaker 1 ]  ->   [ Speaker 2 ]  ->   [ Speaker 3 ]  ->   [ Speaker 4 ]  ->   [ All Hands ]
The Paradigm Shift    Jev Mechanics &     Open-CLM-8B &       Hybrid Arch &       Technical Q&A
& The Token Tax       RLCD Calibration    Action Caching      Live Benchmark      Discussion
```

---

## 👥 Speaker Roles & Workload Distribution

| Speaker | Section | Key Topics Covered | Timing |
| :--- | :--- | :--- | :--- |
| **Speaker 1** | The Paradigm Shift & System 1 vs 2 | The "Token Tax", autoregressive overhead, schema syntax errors, System 1 (fast triage) vs. System 2 (reasoning). | 00:00 – 05:00 |
| **Speaker 2** | Typesafe Jev Deep Dive | Parallel evaluation, typed primitives (`Null`, `Choice`, `Score`), RLCD, and Brier score calibration. | 05:00 – 10:00 |
| **Speaker 3** | Open-CLM-8B & Benchmarks | Contrastive decision models, InfoNCE loss, action-embedding caching (up to 9x–13x speedup), trade-off matrix. | 10:00 – 15:00 |
| **Speaker 4** | Production Systems & Demo | Gatekeeper architecture, confidence thresholds, fallback escalation, and live terminal benchmark. | 15:00 – 20:00 |
| **All Hands** | Interactive Technical Q&A | Pre-assigned topic ownership across architecture, calibration, caching, and production deployments. | 20:00 – 30:00 |

---

## 📊 Architectural Comparison

| Dimension | Generative LLMs (e.g., GPT-4o) | Typesafe Jev | Stanford / NVIDIA Open-CLM-8B |
| :--- | :--- | :--- | :--- |
| **Primary Primitive** | Autoregressive token generation | Parallel typed distributions | Contrastive action-state embeddings |
| **Output Type** | Text strings / JSON tokens | Typed values + calibrated probabilities | Metric space similarity / argmax |
| **Schema Guarantees** | Schema masks / Regex post-processing | Structurally guaranteed by construction | Structurally guaranteed to candidate set |
| **Typical Latency** | 800 ms – 3,000 ms | 70 ms – 150 ms | **15 ms – 25 ms** (with action cache) |
| **Model Weights** | Proprietary API | Proprietary API | **Open Weights** (75 MB projection head) |
| **Confidence Metric** | Uncalibrated logits / prompt vibes | Calibrated via RLCD (Brier Score) | Embedding distance / Softmax dot-product |

---

## 🛠️ Hybrid Architecture Blueprint

```text
Incoming Request (Ticket / Agent State)
                  │
                  ▼
   ┌───────────────────────────────┐
   │    System 1 Decision Model    │
   │       (Jev or CLM-8B)         │
   └──────────────┬────────────────┘
                  │
      Confidence Score ≥ Threshold?
                 / \
           YES  /   \  NO
               /     \
              ▼       ▼
    ┌──────────────┐  ┌───────────────────────────────────┐
    │ Instant Fast │  │ Fallback to System 2 LLM          │
    │  Execution   │  │ (Deep reasoning, long generation) │
    │  (~15-80ms)  │  └───────────────────────────────────┘
    └──────────────┘
```

---

## 💻 Demos: recorded or live (real Jev and CLM calls)

Every demo sends the **identical request** to both models and shows the answer, the confidence and the measured latency side by side. Each page has a **Recorded / Live** switch:

* **Recorded** (default for Cube race and Scam check): each model was recorded *on its own*, one call at a time, with the `record.py` scripts. The page replays the log at the recorded speed, so a 240 ms answer still takes 240 ms on screen. No wifi, GPU or API needed in the lecture hall.
* **Live** (default for Beat the guard): calls the models right now. Recorded attacks are the backup if the network fails.

Each demo folder has its own README with screenshots, a diagram of what happens under the hood, the exact questions the models get, and talking points for the lecture.

Nothing is simulated: a recorded answer is exactly what the model returned, and an unreachable model shows its error instead of a made-up answer.

| Demo | What the audience sees | Why it suits System One models |
| :--- | :--- | :--- |
| **[Cube race](rubric-cube-demo/README.md)** (`/cube`) | Jev, CLM, a random mover and a perfect solver play the same scrambled cube. An exact solver marks every move as optimal, neutral or worse. | One structured decision per step, 15–18 options, latency adds up per move. It also shows the limit: multi-step planning is System 2 work. |
| **[Scam check](scam-detector-demo/README.md)** (`/scam`) | A Berlin flat listing is checked against 9 red flags; code combines them into a risk score with reasons. | Decompose into small typed questions, combine in code, route unsure cases to a human. |
| **[Beat the guard](beat-the-guard-demo/README.md)** (`/guard`) | The audience tries to trick a chatbot into leaking a password; a keyword filter, Jev and CLM guard it. Leaderboard included. | A guardrail runs on every message, so it must be fast; fuzzy leaks (hints, translations) defeat plain code. |

### Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # add TYPESAFE_API_KEY, and CLM_BASE_URL if CLM runs elsewhere
```

CLM runs on a GPU machine (it needs Qwen3-8B as encoder):

```bash
pip install contrastive-lm
vllm serve Qwen/Qwen3-8B --served-model-name qwen3-8b --runner pooling --max-model-len 2048 --port 8090 &
clm-serve                     # API on http://localhost:8700
```

Start the demo app from the repository root and open http://localhost:8000:

```bash
uvicorn webapp.app:app --port 8000
```

The dots in the top bar show whether each model is configured and reachable.

### Recording (do this before the lecture)

Record each model separately, ideally where it will really run. Each command writes `recordings/<demo>/<date>-<time>-<model>.jsonl`; commit that folder so the replays travel with the repo.

```bash
# CLM, on the GPU machine
cd rubric-cube-demo && python -m runner.record --players clm random oracle --levels 2 3 4 --cubes 10 --where "GPU box, BHT" && cd ..
python scam-detector-demo/record.py  --providers clm --where "GPU box, BHT"
python beat-the-guard-demo/record.py --providers clm --where "GPU box, BHT"

# Jev, from your laptop
cd rubric-cube-demo && python -m runner.record --players jev --levels 2 3 4 --cubes 10 --where "Laptop, Berlin" && cd ..
python scam-detector-demo/record.py  --providers jev --where "Laptop, Berlin"
python beat-the-guard-demo/record.py --providers jev --where "Laptop, Berlin"
```

What a recording contains, per call: the full request (state and questions), the model's answers with probabilities, the model version it reported, the measured round trip and (for CLM) the server's own time. Each file starts with a session line: date, the `--where` label, and a **network ping** (a request with no model work), so the audience can see how much of Jev's time is the trip to the US. API keys are never written.

How replays stay honest:
* Cube *k* at level *L* always has the same scramble, so models recorded on different days or machines play the same cubes.
* The cube page shows a summary over **every** recorded cube, and "New cube" picks one at random.
* The scam page shows correct decisions over **all** recorded listings. `evaluate.py` reads the same files, so slide numbers and replays match.
* Every replay shows when, where and with which model version it was recorded, plus a **Raw log** link to the exact request and response.
* Re-recording simply adds a newer file; the newest successful recording per model wins. Delete old files to drop them.

### Rehearsing without a GPU or a Jev key

`tools/mock_system_one_server.py` speaks the same API with keyword rules and noise. Its answers are labelled `mock-jev` / `mock-clm` in the UI, so it can't be confused with the real models. **Never present mock numbers as results**, and don't record against the mock into the real `recordings/` folder (set `SYSTEM_ONE_RECORDINGS=/tmp/mock-rec` while rehearsing).

```bash
python tools/mock_system_one_server.py --port 8700 --name clm --latency-ms 40 &
python tools/mock_system_one_server.py --port 8701 --name jev --latency-ms 120 &
# in .env: CLM_BASE_URL=http://127.0.0.1:8700  TYPESAFE_BASE_URL=http://127.0.0.1:8701  TYPESAFE_API_KEY=mock
```

### Command-line tools (for the data science part)

```bash
cd rubric-cube-demo && python -m runner.race --level 3        # live cube race in the terminal
python scam-detector-demo/evaluate.py                           # from the recordings: AUC, Brier score, calibration,
                                                                # latency percentiles, logistic regression (LOO CV)
python -m pytest tests rubric-cube-demo/tests                   # 23 tests, run against the mock server
```

### Repository layout

```text
system_one/            one client for both models (same wire format: POST /v1/systemone) + recorder
recordings/            recorded calls, replayed by the web app (created by the record.py scripts)
rubric-cube-demo/      README + screenshots; cube engine (moves derived from 3D geometry), exact solver, players, CLI race
scam-detector-demo/    README + screenshots; red flags + combining logic, 30 labelled synthetic listings, evaluate.py
beat-the-guard-demo/   README + screenshots; vault bot (scripted, or any OpenAI-compatible LLM), guards, leaderboard
webapp/                the web pages for all three demos: FastAPI app + static pages (no build step, no CDN: works offline in the lecture hall)
tools/                 mock server for rehearsals
```

---

## 🎯 FAQ Strategy & Coverage Matrix

* **Q: Can Jev hallucinate if schemas cannot break?**
  * *Speaker 2:* It cannot break output types or JSON syntax, but classification mistakes can still happen. That is why calibrated probability (RLCD) is necessary to catch uncertain calls.
* **Q: Why not use small fine-tuned BERT/DeBERTa classifiers instead?**
  * *Speaker 3:* Standard classifiers require full fine-tuning for new label spaces. Jev and CLM-8B evaluate ad-hoc queries and dynamic tools zero-shot using LLM-grade foundational representations.
* **Q: How are free-form responses or text extraction handled?**
  * *Speaker 1 / 4:* Decision models do not write prose. In production, they route to deterministic code paths or trigger a System 2 LLM when open-ended text generation is explicitly required.
* **Q: What determines whether to deploy CLM-8B or Jev?**
  * *Speaker 4:* Use **Open-CLM-8B** for self-hosted environments with static tool sets needing sub-20ms inference via action caching. Use **Jev** for a managed SaaS API with built-in ordinal scoring and RLCD calibration out of the box.
