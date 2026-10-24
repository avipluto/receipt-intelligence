# Project progress: Receipt Intelligence

Last updated: 2026-10-24 · branch `master` · 103 tests passing

## Overall: done (100% of the planned scope)

Planned scope: extraction pipeline, evaluation, question answering, API, UI and docs. Docker was dropped on 2026-10-24 (see below).

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
| OCR line grouping fix (tilted photos) | ✅ done, measured (v9/v10 in `docs/02-extraction.md`) | 100% |
| Docker | ⛔ dropped: the app runs natively; a Linux VM on 16 GB RAM pushed the page file onto a nearly full C: | n/a |
| README / docs | ✅ done | 100% |

## Nice to do next

- **Demo with real receipts:** CORD photos have no dates, so date questions ("last month") can't be shown yet. Ingest a few of your own receipts.

## Optional improvements

- Lower false review flags (about 33% on real OCR). Most come from genuine item errors, so a per-field flag would be fairer.
- OCR misses the amounts entirely on some photos (CORD 013, 020). That needs a better detector or image preprocessing, not grouping.
- A test split of your own receipts (Indian formats: GST, ₹), since CORD is Indonesian.

## Key results so far (real OCR pipeline, 100 CORD photos)

| | v2 (start) | v8 | v10 (now) |
|---|---|---|---|
| Total correct | 79.6% | 87.4% | **91.5%** |
| Tax correct | 47.5% | 73.2% | **80.0%** |
| Subtotal correct | 84.1% | 87.7% | **90.6%** |
| Correct totals still flagged | 51.4% | 34.9% | **32.6%** |

Remaining total errors (v10): 6 caused by OCR, 2 by the LLM.

## How to run

```bash
.venv/Scripts/python -m uvicorn receipt_ai.api:app --app-dir src --port 8765
.venv/Scripts/python -m streamlit run src/receipt_ai/ui.py
```
Port 8765, because 8000 is already used by another program on this PC.
