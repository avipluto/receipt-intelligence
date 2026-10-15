"""OCR lines -> LLM -> RawReceipt -> validated Receipt.

The LLM's only job is reading: find the merchant, date, items and amounts in noisy
OCR text and copy them out. Ollama's structured outputs (format=<JSON schema>)
constrain decoding to that schema, so the reply is always valid JSON of the
right shape. Converting text to numbers and checking the maths happen in
schema.py, in ordinary Python.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests
from pydantic import ValidationError

from .schema import RawReceipt, Receipt

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:3b"
NUM_CTX = 4096  # measured: ~2.3 GB VRAM on the RTX 2050, see docs/00-model-selection.md

SYSTEM_PROMPT = """You extract data from OCR text of shop receipts.
The OCR text may contain spelling errors, merged words and lines out of order.

Rules:
- Copy every amount EXACTLY as printed (keep "60.000", "1,250.00", "Rp" etc.). Do not convert or calculate.
- items: only purchased products/services. Not subtotal, tax, discount, payment or change lines.
- total: the final amount paid (often labelled TOTAL, GRAND TOTAL, NET, AMOUNT DUE).
- tax: the tax amount; if several tax lines, copy the one total tax line, or the single tax line.
- Use null for anything not present. Never invent values."""


@dataclass
class Extraction:
    receipt: Receipt | None
    raw_json: str
    seconds: float
    error: str | None = None


def llm_schema() -> dict:
    """RawReceipt's JSON schema with every key required (values may still be null).

    Pydantic marks fields with defaults as optional, and constrained decoding lets
    the model skip optional keys entirely. A 3B model takes that shortcut and
    silently drops subtotal/tax/date. Requiring every key forces an explicit
    value-or-null decision for each field.
    """
    schema = RawReceipt.model_json_schema()
    for obj in [schema, *schema.get("$defs", {}).values()]:
        if "properties" in obj:
            obj["required"] = list(obj["properties"])
    return schema


def build_messages(ocr_lines: list[str]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "OCR TEXT:\n" + "\n".join(ocr_lines)},
    ]


def extract(ocr_lines: list[str], model: str = MODEL, timeout: int = 120) -> Extraction:
    body = {
        "model": model,
        "messages": build_messages(ocr_lines),
        "format": llm_schema(),
        "stream": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
        "keep_alive": "10m",
    }
    start = time.perf_counter()
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        return Extraction(None, "", time.perf_counter() - start, f"ollama request failed: {e}")

    seconds = time.perf_counter() - start
    try:
        # One bad reply must not kill a batch: treat a garbled body like any other failure.
        data = resp.json()
        raw_json = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as e:  # JSONDecodeError is a ValueError
        return Extraction(None, resp.text[:500], seconds, f"ollama reply was not usable JSON: {e!r}")

    if data.get("prompt_eval_count", 0) >= NUM_CTX:
        # Ollama silently drops the start of the prompt when it overflows the context.
        return Extraction(None, raw_json, seconds, f"prompt ({data['prompt_eval_count']} tokens) filled the context window")

    try:
        raw = RawReceipt.model_validate_json(raw_json)
    except ValidationError as e:
        return Extraction(None, raw_json, seconds, f"schema validation failed: {e.error_count()} errors")
    return Extraction(Receipt.from_raw(raw), raw_json, seconds)


if __name__ == "__main__":
    import sys

    lines = [ln.rstrip("\n") for ln in open(sys.argv[1], encoding="utf-8")] if len(sys.argv) > 1 else sys.stdin.read().splitlines()
    result = extract(lines)
    print(json.dumps(json.loads(result.raw_json or "{}"), indent=1, ensure_ascii=False))
    if result.receipt:
        print(result.receipt.model_dump_json(indent=1))
    print(f"{result.seconds:.1f}s  error={result.error}")
