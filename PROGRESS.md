# Project progress: Receipt Intelligence

Last updated: 2026-10-15 · branch `master` · 102 tests passing

## Overall: about 90% done, about 10% left

This is an estimate, weighted by effort, for the planned scope: extraction pipeline, evaluation, question answering, API, UI, Docker and docs.

| Area | Status | Done |
|---|---|---|
| OCR (PaddleOCR) + engine choice | ✅ done, benchmarked (`docs/01-ocr-selection.md`) | 100% |
| LLM choice (qwen2.5:3b on 4 GB GPU) | ✅ done (`docs/00-model-selection.md`) | 100% |
| Extraction prompt + Python checks (v1 → v8) | ✅ done, measured (`docs/02-extraction.md`) | 100% |
| Eval tooling (`eval_extraction.py`, `--rescore`, `compare_runs.py`, `score_ocr_cache.py`) | ✅ done | 100% |
| SQLite storage + 5 tested queries | ✅ done | 100% |
| Question answering (`ask.py`) + live test | ✅ done; router output validated in Python | 100% |
| FastAPI backend | ✅ done, tested, run live | 100% |
| Streamlit UI (Plotly charts, citations) | ✅ done, checked in the browser | 100% |
| OCR line grouping fix (tilted photos) | 🟡 code done and committed; LLM eval (v9) running | 80% |
| Docker | 🟡 Dockerfile + compose written; build **not verified** (Docker Desktop crashed mid-build) | 50% |
| README / docs | 🟡 written; needs the v9 section and Docker confirmation | 85% |

## What's left (in order)

1. **Finish the v9 eval** (OCR grouping fix, ~13 min) and add a v9 section to `docs/02-extraction.md`.
   Already measured without the LLM: total on its label's line 78.9% → 83.2%, 4 receipts fixed, 0 broken.
2. **Verify Docker:** restart Docker Desktop, run `docker compose up --build`, open http://localhost:8501, upload one receipt. Then remove the "not verified" note from the README.
3. **Demo with real receipts:** CORD photos have no dates, so date questions ("last month") can't be shown yet. Ingest a few of your own receipts.

## Optional next steps (outside the planned scope)

- Lower false review flags (about 35% on real OCR). Most come from genuine item errors, so a per-field flag would be fairer.
- OCR misses the amounts entirely on some photos (CORD 013, 020). That needs a better detector or image preprocessing, not grouping.
- A test split of your own receipts (Indian formats: GST, ₹), since CORD is Indonesian.

## Key results so far (real OCR pipeline, 100 CORD photos)

| | v2 (start) | v8 (now) |
|---|---|---|
| Total correct | 79.6% | 87.4% |
| Tax correct | 47.5% | 73.2% |
| Wrong totals flagged for review | 68% | 92% |
| Failed LLM calls | 2 | 0 |

## How to run (no Docker)

```bash
.venv/Scripts/python -m uvicorn receipt_ai.api:app --app-dir src --port 8765
.venv/Scripts/python -m streamlit run src/receipt_ai/ui.py
```
Port 8765, because 8000 is already used by another program on this PC.
