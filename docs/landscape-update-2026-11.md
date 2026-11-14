# Decision-Model Landscape Update (as of 14 Nov 2026)

> When we started, the field had two models (Jev and CLM-8B). Within two months it has grown into a whole category of "System 1" decision models.
> Most figures below are **vendor-reported** (marked ⚠️), not independent benchmarks. Please cite the source if you use a number on a slide.

---

## 1. Models and tools at a glance

| Name | Who | Released | Open weights? | What's notable | Source |
|---|---|---|---|---|---|
| **Jev** | TypeSafe AI | 15 Sep 2026 | No (API, e.g. OpenRouter, Vercel AI Gateway) | Started the category; question types Choice / Score / Noul | [InfoQ](https://infoq.com/news/2026/10/typesafe-ai-jev-released), [Kanerika](https://kanerika.com/blogs/jev-vs-llm/) |
| **CLM-8B** | Stanford + NVIDIA | Late Sep 2026 | Yes, Apache 2.0 | Contrastive model with action caching; ⚠️ "up to 9× faster than Jev" in internal tests | [Overview article](https://pasqualepillitteri.it/en/news/20652/ai-decision-models-run-locally) |
| **OpenAI Decisions API** | OpenAI | 29 Sep 2026 | No (limited preview) | ⚠️ ~150 ms response time reported | [Overview article](https://pasqualepillitteri.it/en/news/20652/ai-decision-models-run-locally) |
| **Strands Decider** (2B / Gemma-4 E4B build) | AWS Strands Agents | Oct 2026 | Yes, Apache 2.0 | Used in production at Amazon (see §3) | [Strands blog](https://strandsagents.com/blog/amazon-saves-millions-replacing-sonnet-with-strands-decider/) |
| **Perplexity Decider v1.3 / Flash v1.3** | Perplexity | 12 Nov 2026 | Yes, Apache 2.0 (Hugging Face); also on OpenRouter and the Perplexity Decisions API | Adds **locate** (extract text spans); ⚠️ claims to beat Jev 1.14 on most benchmark groups | [Perplexity blog](https://www.perplexity.ai/hub/blog/perplexity-decider) |
| **Gemini Decision 1** | Google | Nov 2026 | No (Decisions API) | **Multimodal** (text, image, video, audio, PDF); up to 1,000 questions per request over ~262k tokens of shared input | [Google AI Studio docs](https://aistudio.google.com/docs/models/gemini-decision-1) |
| **vLLM Semantic Router (vLLM-SR)** | vLLM project (open source) | ongoing | Yes | Not a model but a **routing layer** in front of models; its "System One" engine API (`/v1/systemone`) serves decision models | [vllm-sr.ai](https://vllm-sr.ai/) |

Also: Thoughtworks added "decision models" to its Technology Radar (Nov 2026, ring "Assess"). The use cases they list are judging (an alternative to LLM-as-a-judge), model/tool routing, policy gates and bulk labelling. [Link](https://www.thoughtworks.com/es-cl/radar/platforms/decision-models)

---

## 2. Details on the new entries

### Google: Gemini Decision 1
- Model ID `gemini-decision-1`, available through the Decisions API: `client.decisions.create` in the Python and JS SDKs, or REST at `/v1beta/decisions`.
- Works on text, images, video, audio and PDFs in a single prefill pass, with **zero output tokens**.
- Question types:
  - **Yes/no:** probability from 0.01 to 0.99, plus a confidence score
  - **Single-select:** 2–255 options
  - **Rubric rating:** 2–255 ordered levels; returns an expected score
- Use cases Google lists: request routing, checking many policy rules at once, scoring candidates against a rubric, tool selection, live-media classification.
- No latency or pricing numbers are published on the docs page yet.

### Perplexity: Decider v1.3 and Decider Flash v1.3 (12 Nov 2026)
- Perplexity says the design is inspired by Jev. It is built on generative LLM backbones: Qwen3.8-27B for the large model, and Flash is distilled into Qwen3.5-4B.
- Question types: yes/no, multiple choice, ordered score. **Locate** is new and extracts matching text spans, e.g. for NER, PII or extractive QA.
- ⚠️ Selected benchmarks reported by Perplexity:
  - Query classification: 91.6% mean accuracy over 63 tasks
  - Agreement with frontier LLM judges on real requests: ~94%
  - Decider v1.3 beats Jev 1.14 on classification, domain tasks (up to +12.9 pts in finance), retrieval, multilingual and image tasks
  - Flash trails Jev in finance, programming and law
- ⚠️ Cost per 1M production requests on their workload:

  | Model | Cost per 1M requests |
  |---|---|
  | Decider v1.3 | ~$26 |
  | Decider Flash v1.3 | ~$13 |
  | Jev 1.14 | ~$68 |

  These Decider numbers exclude local hardware cost.
- ⚠️ Robustness (share of answers that changed when labels were reworded):

  | Model | Answers changed |
  |---|---|
  | Decider v1.3 | 0.27% |
  | Jev 1.14 | 2.7–4.8% |

- No latency figures are given.

### vLLM Semantic Router (vLLM-SR)
- An open-source "decision layer" in front of your model pool. It works with vLLM, SGLang or any OpenAI-compatible API, in the cloud, on-prem or at the edge.
- It has two modes:
  - **Router mode:** apps call a normal OpenAI- or Anthropic-compatible endpoint. The router reads signals (domain, complexity, jailbreak risk, PII, language) and sends each request to one model according to a policy.
  - **Engine mode** (`/v1/systemone`): calls a decision model directly and gets calibrated probabilities per option.
- Partners include AMD, Hugging Face, Microsoft, NVIDIA and Red Hat.
- ⚠️ Research claims: ~98× lower routing latency without a dedicated GPU, and up to 96% lower inference cost when pairing an 8B model with memory-augmented routing.

---

## 3. Case study: Amazon replaced Claude Sonnet with Strands Decider (9 Nov 2026)

This case is also about **ticket labelling**, the same task our project uses.

- **Task:** label internal tickets across 20 categories. This was previously done with Claude Sonnet 4.6.
- **Cost:** about $0.0222 → $0.0005 per ticket (~98% lower). Per 1M tickets that is about $22,200 → $500.
- **Latency:** about 4.2 s → 0.9 s average per call. Tokens per ticket fell by ~70%.
- **Architecture:** SQS → Lambda → SageMaker endpoint (single-GPU instances, no outbound network access). A config switch has three modes:
  - `BEDROCK`: the LLM only
  - `DUAL`: both models in parallel, for comparison
  - `DECIDER`: the decision model only
- **Rollback:** switching back to the LLM was a 45-second config change.
- **Lessons they report:**
  - The approach fits closed label sets, high volume and latency-sensitive work.
  - It fits less well when labels need explanation text, the catalogue changes often, or the needed context doesn't fit in a few thousand tokens.
  - ⚠️ **The JSON key order changed probabilities by up to 0.19.** They now sort keys before sending.
- No exact accuracy numbers are published. The post says the decider matched or beat the LLM after the confidence threshold was tuned.

Source: [Strands blog](https://strandsagents.com/blog/amazon-saves-millions-replacing-sonnet-with-strands-decider/)

---

*Compiled 14 Nov 2026. Verify numbers against the linked sources before using them.*
