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

## 💻 Live Benchmark Demo

### Prerequisites

```bash
pip install numpy
```

### Running the Script

```bash
python benchmark_demo.py
```

### Script Source (`benchmark_demo.py`)

```python
"""
Decision Model Prototype: Simulating Jev vs. Open-CLM-8B in Agent Workflows
"""
import time
import numpy as np

TICKETS = [
    {
        "id": "TCK-101",
        "text": "Checkout throws HTTP 500 internal server error when clicking Pay.",
    },
    {
        "id": "TCK-102",
        "text": "My credit card was charged twice for the renewal. Requesting refund.",
    },
    {
        "id": "TCK-103",
        "text": "The new dark mode theme looks clean, but can we get purple accent colors?",
    },
]

ROUTES = ["billing", "technical_support", "feature_request"]

def mock_jev_decide(state_text: str):
    """Simulates Jev: Direct multi-task evaluation (~85ms latency)."""
    start = time.perf_counter()
    time.sleep(0.085)
    
    t = state_text.lower()
    if "500" in t or "error" in t:
        probs = {"billing": 0.03, "technical_support": 0.94, "feature_request": 0.03}
        route = "technical_support"
    elif "charged" in t or "refund" in t:
        probs = {"billing": 0.95, "technical_support": 0.02, "feature_request": 0.03}
        route = "billing"
    else:
        probs = {"billing": 0.08, "technical_support": 0.22, "feature_request": 0.70}
        route = "feature_request"

    latency_ms = (time.perf_counter() - start) * 1000
    return {"selected": route, "confidence": probs[route], "latency_ms": latency_ms}

def mock_clm_decide(state_text: str, cached_actions: bool = True):
    """Simulates Open-CLM-8B: Pre-computed action embeddings + state dot-product."""
    start = time.perf_counter()
    time.sleep(0.016 if cached_actions else 0.075)

    t = state_text.lower()
    if "500" in t or "error" in t:
        scores = [0.10, 0.92, 0.05]
    elif "charged" in t or "refund" in t:
        scores = [0.94, 0.04, 0.02]
    else:
        scores = [0.12, 0.25, 0.63]

    exp_scores = np.exp(scores)
    probs = exp_scores / np.sum(exp_scores)
    idx = int(np.argmax(probs))

    latency_ms = (time.perf_counter() - start) * 1000
    return {"selected": ROUTES[idx], "confidence": float(probs[idx]), "latency_ms": latency_ms}

def run_benchmark():
    print("=" * 70)
    print("SYSTEM 1 DECISION ENGINE BENCHMARK (Jev vs. Open-CLM-8B)")
    print("=" * 70)
    CONFIDENCE_THRESHOLD = 0.75

    for item in TICKETS:
        print(f"\n[Payload {item['id']}]: \"{item['text']}\"")
        
        # 1. Jev
        jev = mock_jev_decide(item["text"])
        print(f"  • Typesafe Jev    -> Action: {jev['selected']:<18} | Conf: {jev['confidence']:.2f} | Latency: {jev['latency_ms']:.1f}ms")
        
        # 2. CLM-8B
        clm = mock_clm_decide(item["text"], cached_actions=True)
        print(f"  • Open-CLM-8B     -> Action: {clm['selected']:<18} | Conf: {clm['confidence']:.2f} | Latency: {clm['latency_ms']:.1f}ms (Cached)")

        # 3. Guardrail / Escalation
        if jev["confidence"] < CONFIDENCE_THRESHOLD:
            print("    ↳ [Gatekeeper]: Low confidence (< 0.75). Escalating to System 2 LLM.")
        else:
            print(f"    ↳ [Gatekeeper]: High confidence. Fast-dispatched directly to [{jev['selected']}].")

if __name__ == "__main__":
    run_benchmark()
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
