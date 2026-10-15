"""OCR lines -> LLM -> RawReceipt -> validated Receipt.

The LLM's only job is reading: find the merchant, date, items and amounts in noisy
OCR text and copy them out. Ollama's structured outputs (format=<JSON schema>)
constrain decoding to that schema, so the reply is always valid JSON of the
right shape. Converting text to numbers and checking the maths happen in
schema.py, in ordinary Python.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests
from pydantic import ValidationError

from .schema import RawReceipt, Receipt

# In Docker, set OLLAMA_URL=http://host.docker.internal:11434 to reach Ollama on the host.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = "qwen2.5:3b"
MAX_OUTPUT_TOKENS = 1500  # the longest correct CORD extraction is far below this
NUM_CTX = 4096  # measured: ~2.3 GB VRAM on the RTX 2050, see docs/00-model-selection.md

SYSTEM_PROMPT = """You extract data from OCR text of shop receipts.
The OCR text may contain spelling errors, merged words and lines out of order.

Rules:
- Copy every amount EXACTLY as printed (keep "60.000", "1,250.00", "Rp" etc.). Do not convert or calculate.
- items: only purchased products/services. Not subtotal, tax, discount, payment or change lines.
- line_total: the amount printed on the item's line. It already includes the quantity: for "2 COFFEE 24,000" line_total is "24,000", NOT 48,000.
  unit_price: only if a separate per-unit price is printed, else null.
- total: the final amount of the bill (labelled TOTAL, GRAND TOTAL, NET, AMOUNT DUE).
  NOT the cash handed over (CASH, TUNAI, PAID) and NOT the CHANGE / KEMBALI given back.
- tax: the tax amount. Tax lines are labelled TAX, PB1, PB 1, PPN, VAT, GST, CGST/SGST, often with a percent like "10%".
  If several tax lines, copy the one total tax line. Service charge (SERVICE, SVC CHG) is NOT tax.
- service_charge: the service charge amount (SERVICE, SVC CHG, SC), or null.
- discount: a discount applied to the whole bill (DISCOUNT, DISC, VOUCHER), or null. Not item-level discounts.
- cash_paid: the amount the customer handed over (CASH, TUNAI, PAID, CARD), or null. change: CHANGE / KEMBALI, or null.
- Use null for anything not present. Never invent values."""


@dataclass
class Extraction:
    receipt: Receipt | None
    raw_json: str
    seconds: float
    error: str | None = None
    retryable: bool = False


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


def extract(ocr_lines: list[str], model: str = MODEL, timeout: int = 120, attempts: int = 2) -> Extraction:
    """Extract one receipt, retrying once on a transient failure.

    Measured on the eval runs: ~2-4% of calls fail intermittently (Ollama 500s, or the
    model looping until it hits the cap), and the same receipt succeeds on a re-run.
    Ollama reuses its prompt cache across requests (likely making GPU arithmetic depend on the previous one), so even
    temperature 0 isn't perfectly repeatable. A single retry recovers these cheaply.
    """
    result = _extract_once(ocr_lines, model, timeout)
    for _ in range(attempts - 1):
        if not result.retryable:
            break
        retry = _extract_once(ocr_lines, model, timeout)
        retry.seconds += result.seconds
        result = retry
    return result


def _extract_once(ocr_lines: list[str], model: str, timeout: int) -> Extraction:
    body = {
        "model": model,
        "messages": build_messages(ocr_lines),
        "format": llm_schema(),
        "stream": False,
        # num_predict caps a runaway generation (the model looping on items) so it fails
        # in well under a minute as invalid JSON instead of hitting the request timeout.
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": MAX_OUTPUT_TOKENS},
        "keep_alive": "10m",
    }
    start = time.perf_counter()
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        status = e.response.status_code if e.response is not None else None
        body_text = e.response.text[:200] if e.response is not None else ""
        # 4xx means our request is wrong and will be wrong again; anything else may pass next time.
        return Extraction(None, "", time.perf_counter() - start, f"ollama request failed: {e} {body_text}".strip(),
                          retryable=status is None or status >= 500)

    seconds = time.perf_counter() - start
    try:
        # One bad reply must not kill a batch: treat a garbled body like any other failure.
        data = resp.json()
        raw_json = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as e:  # JSONDecodeError is a ValueError
        return Extraction(None, resp.text[:500], seconds, f"ollama reply was not usable JSON: {e!r}", retryable=True)

    if data.get("prompt_eval_count", 0) >= NUM_CTX:
        # Ollama silently drops the start of the prompt when it overflows the context.
        return Extraction(None, raw_json, seconds, f"prompt ({data['prompt_eval_count']} tokens) filled the context window")

    try:
        raw = RawReceipt.model_validate_json(raw_json)
    except ValidationError as e:
        # Usually output cut off at num_predict by a looping model.
        return Extraction(None, raw_json, seconds, f"schema validation failed: {e.error_count()} errors", retryable=True)
    return Extraction(Receipt.from_raw(raw), raw_json, seconds)


if __name__ == "__main__":
    import sys

    lines = [ln.rstrip("\n") for ln in open(sys.argv[1], encoding="utf-8")] if len(sys.argv) > 1 else sys.stdin.read().splitlines()
    result = extract(lines)
    print(json.dumps(json.loads(result.raw_json or "{}"), indent=1, ensure_ascii=False))
    if result.receipt:
        print(result.receipt.model_dump_json(indent=1))
    print(f"{result.seconds:.1f}s  error={result.error}")
