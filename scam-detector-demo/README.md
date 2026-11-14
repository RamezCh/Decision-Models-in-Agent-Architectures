# Scam check: is this Berlin flat a scam?

Paste a flat listing, or pick one of 30 examples. Instead of one big "scam or not?" question, CLM-8B answers nine small yes/no questions, the red flags a careful flat-hunter checks. Plain code then combines the answers into a risk score with reasons.

![Scam check: CLM's verdict, its answer per red flag, and the correct answer revealed](docs/scam-check.png)

<sub>Screenshot from a rehearsal with the mock server (model name `mock-clm`), so the numbers are not real results.</sub>

> **Model:** this demo uses **CLM-8B only** (host it with [`../k8s`](../k8s/README.md)). To compare with Jev again, set `SCAM_MODELS=jev,clm` and `TYPESAFE_API_KEY` in `.env`: the page then shows a lane and a column per model, and marks rows where they disagree.

## What the audience sees

* **A verdict**: *Looks OK*, *Check manually* or *Likely scam*, with a calibrated risk percentage and the answers that pointed to scam or to legit.
* **A stopwatch.** In recorded mode the verdict appears after exactly the time CLM needed when recorded.
* **A red-flag table** with CLM's raw yes-score for each question. Under each bar is how much that answer moved the risk ("+1.3 towards scam"). Hover a row for the exact question and the "yes" and "no" descriptions CLM compares against.
* **"One big question" for comparison**: CLM is also asked "is this a scam?" directly. It is one more input to the calibrated risk.
* **"Reveal the correct answer"**: the list is shuffled and the label is hidden, so the audience can guess first.
* **A speed panel** (average, median, 95th percentile, model vs network time) and a **decision log**: every check with risk, decision, top reasons, raw answer, correct label and time, downloadable as CSV.

## What happens under the hood

> The full explanation with diagrams, theory and real measurements is in [docs/README.md](../docs/README.md).

![From a flat listing to "Likely scam"](../docs/img/scam-pipeline.svg)

1. **One request, ten questions.** The listing is the state. The questions are 9 red flags plus "is this a scam?", all yes/no (`noul`). CLM answers them in one pass.
2. **Every question describes its answers.** Each has a `criteria` text for what *yes* looks like and what *no* looks like. CLM picks an answer by comparing the listing with these texts, so without them both answers look almost alike and everything lands near 50/50 ([why](../docs/README.md#5-why-the-wording-of-a-question-matters)).
3. **Calibration (code).** Raw CLM scores rank listings well but are shifted: legit listings also score high. A logistic regression fitted on the 30 labelled listings turns the 10 answers into an honest risk: `risk = σ(b + Σ wₖ·zₖ)`, where `zₖ` is answer k as standardised log-odds. Each `wₖ·zₖ` is the "push" shown in the table. Stored in `data/calibration_clm.json`.
4. **Decision (code).** Risk below 30% is *Looks OK*, 30–60% is *Check manually*, 60% or more is *Likely scam*.

If there is no valid calibration (for example after you edit a question, which changes its fingerprint), the page says "not calibrated" and falls back to a transparent rule: each flag is an independent reason for suspicion, `risk = 1 − Π(1 − strengthₖ·pₖ)`.

### The nine red flags

| Red flag | Fallback strength |
| :--- | ---: |
| Asks for money before a viewing or contract | 0.60 |
| Keys by post / courier, or a "trustee" / payment-protection service | 0.60 |
| Landlord can't show the flat in person (e.g. lives abroad) | 0.50 |
| Moves to WhatsApp, private email, Western Union, crypto, gift cards | 0.35 |
| Rent far below normal for size and location | 0.30 |
| Wants ID, bank details or payslips before any viewing | 0.25 |
| Time pressure | 0.20 |
| Elaborate personal story explaining the odd arrangement | 0.20 |
| Vague about the flat itself | 0.10 |

The question texts and their yes/no descriptions are in `scam/detector.py`.

### What we measured with the real model

Same 30 listings, CLM-8B on the BHT A100:

| | AUC | Brier (lower = better) |
| :--- | ---: | ---: |
| One big question, first version (no descriptions) | 0.42 | – |
| One big question, with descriptions, raw | 0.93 | 0.431 |
| All 10 answers, calibrated (leave-one-out) | **0.97** | **0.070** |

![Raw vs calibrated](../docs/img/raw_vs_calibrated.png)

This is the pattern from the talk: **decompose into small typed questions, combine in code, route uncertainty to a person.** Every decision can be explained question by question.

## The data

`data/listings.jsonl` has **30 synthetic listings** (15 scams, 15 legitimate) written for this demo. Each has a label and a one-line explanation (`why`). Some are deliberately tricky:

* Legit, but with red-flag words: the landlord is abroad but a friend shows the flat; a cooperative share is paid upfront after signing; time pressure from someone who needs a Nachmieter.
* Scams that are more subtle: "the current tenant is very private, so no viewing".

Add real listings (with labels) to make the evaluation more meaningful. 30 synthetic examples are a classroom illustration, not a benchmark.

## How to run it

**In the web app** (from the repository root): `uvicorn webapp.app:app --port 8000`, then open http://localhost:8000/scam.

**Recorded (default).** Record before the lecture, with CLM running and the tunnel open (see [`../k8s`](../k8s/README.md)), from the repository root:

```bash
python scam-detector-demo/record.py --where "BHT cluster (A100)"
python tools/calibrate.py --only scam        # refit the calibration on what you just recorded
```

If a listing's text or a question is edited later, the old recordings are ignored (each recording stores a fingerprint of the text and of the questions).

**Live.** Switch to Live to check your own text. CLM is asked right now.

**Evaluation for the data science part:**

```bash
python scam-detector-demo/evaluate.py
```

It makes no model calls: it reads the same recordings the page replays, so slide numbers and replays always match. It writes `results/report.md` and `results/predictions.csv` with:

| Metric | How to read it |
| :--- | :--- |
| AUC, raw checklist / raw one big question | Chance that a random scam scores higher than a random legit listing (1.0 = perfect ranking, 0.5 = coin flip), before calibration |
| AUC and Brier, calibrated (leave-one-out) | The same after calibration. Each listing is scored by a calibration fitted *without* it, so the numbers are not flattered |
| Reliability tables | When CLM (or the calibration) says 80%, is it a scam about 80% of the time? Raw vs calibrated |
| Accuracy, precision, recall | When "check" or "warn" counts as flagged |
| Calibration weights | How much each question counts |
| Median / 95th-percentile latency | Typical and worst-case waiting time |

## Files

| File | What it does |
| :--- | :--- |
| `scam/detector.py` | Red flags, the questions with yes/no descriptions, `combine()`, decision thresholds |
| `data/calibration_clm.json` | The fitted calibration (made by `../tools/calibrate.py`) |
| `scam/recorded.py` | Loads recordings for replay and evaluation |
| `record.py` | Records one model at a time over all listings |
| `evaluate.py` | Metrics from the recordings |
| `data/listings.jsonl` | 30 labelled synthetic listings |

The web page itself is in `../webapp/static/scam.html` and `scam.js`.

## Talking points

* **How you ask matters as much as the model.** The same CLM went from worse than a coin flip to AUC 0.93 just by describing what yes and no look like.
* **Small questions beat one big one**: each answer is easier for the model, and the decision becomes explainable.
* **Calibration matters for automation.** A threshold only works if "80% sure" really means right about 80% of the time.
* **The cost of a wrong call is asymmetric.** Missing a scam can cost a deposit; flagging a legit flat costs a second look. That's why there's a *Check manually* band instead of a hard yes/no.
