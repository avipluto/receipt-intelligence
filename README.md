# Receipt Intelligence

Ask questions about your spending in plain English, answered from photos of your receipts.
It runs **fully locally and for free**: no paid APIs, and nothing leaves your machine.

```
photo / PDF ──► PaddleOCR (CPU) ──► qwen2.5:3b via Ollama (GPU) ──► Python checks ──► SQLite
                                     "read and copy only"            parse, verify, repair
question ──► LLM picks a tested query ──► Python validates it ──► SQL ──► answer + cited receipts
```

## Design principles

1. **The LLM only reads; Python computes.** The model copies amounts *as printed*. Python parses them (`Decimal`, integer cents in the DB), checks the arithmetic (`subtotal + tax + service − discount = total`, `cash − change = total`, items ≈ subtotal), and flags receipts that don't add up.
2. **The LLM never writes SQL.** It picks one of five tested query functions plus a period *label* ("last_month"). Python turns the label into dates and drops any value the question doesn't support.
3. **Every number in an answer is verified.** If the LLM's reply contains a number that isn't in the query result, a plain template answer is used instead. Every answer cites the receipts it came from.
4. **Measured, not guessed.** Each model, OCR engine and prompt change was benchmarked on the 100-receipt CORD v2 test set.

## Results (CORD v2 test, 100 real receipt photos)

| | v2 (start) | v10 (now) |
|---|---|---|
| Total correct | 79.6% | **91.5%** |
| Tax correct | 47.5% | **80.0%** |
| Subtotal correct | 84.1% | **90.6%** |
| Correct totals still flagged for review | 51.4% | **32.6%** |

On perfect (labelled) text the LLM gets 94.7% of totals and 95.1% of tax right. The remaining gap is mostly OCR.
Write-ups: [model choice](docs/00-model-selection.md) · [OCR choice](docs/01-ocr-selection.md) · [extraction iterations and lessons](docs/02-extraction.md)

## Run it

**Prerequisite:** [Ollama](https://ollama.com) running on the host with `ollama pull qwen2.5:3b`.

With Docker:
```bash
docker compose up --build
```
UI at http://localhost:8501, API docs at http://localhost:8765/docs. OCR models download to `./models` on first use.
*(Status: the compose setup is written but its first full build has not completed yet; the Docker engine crashed mid-build on the dev machine. The non-Docker route below is tested.)*

Without Docker (Python 3.11):
```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn receipt_ai.api:app --app-dir src --port 8765
.venv/Scripts/python -m streamlit run src/receipt_ai/ui.py
```

Tests: `python -m pytest -q tests`. Evaluation: `python scripts/eval_extraction.py --source ocr --tag vN` (needs the CORD data, see `scripts/prepare_cord.py`).

## Hardware it was built on

RTX 2050 (4 GB VRAM), 16 GB RAM, Windows 11. The 3B model uses ~2.3 GB VRAM at a 4096-token context. OCR takes ~7–13 s per photo on the CPU, extraction ~8 s on the GPU.

## Layout

| Path | What |
|---|---|
| `src/receipt_ai/ocr.py` | PaddleOCR wrapper, line grouping |
| `src/receipt_ai/extract.py` | prompt + JSON-schema-constrained extraction, retries |
| `src/receipt_ai/schema.py` | amount/date parsing, total repair, consistency checks |
| `src/receipt_ai/db.py`, `queries.py` | SQLite storage and the five tested queries |
| `src/receipt_ai/ask.py` | question → validated route → query → grounded answer |
| `src/receipt_ai/api.py`, `ui.py` | FastAPI backend, Streamlit front end |
| `scripts/` | benchmarks, evaluation (`--rescore` re-tests Python-only changes in seconds), demo |
