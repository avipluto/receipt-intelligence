"""Split extraction errors into "OCR's fault" and "LLM's fault".

  python scripts/compare_runs.py docs/extraction_results/v2-gt.json docs/extraction_results/v2-ocr.json

For each field, a receipt the LLM gets right on perfect text (gt) but wrong on
real OCR text is an OCR-caused error; one it gets wrong even on perfect text is
an LLM-caused error (the OCR can't be blamed when the input was flawless).
"""

import json
import sys


def load(path):
    return {r["id"]: r for r in json.load(open(path, encoding="utf-8"))["rows"]}


def main(gt_path: str, ocr_path: str) -> None:
    gt, ocr = load(gt_path), load(ocr_path)
    ids = sorted(gt.keys() & ocr.keys())
    print(f"{'field':10} {'labelled':>8} {'both ok':>8} {'OCR err':>8} {'LLM err':>8} {'OCR fixed':>9}")
    for field in ["total_ok", "subtotal_ok", "tax_ok"]:
        both = ocr_err = llm_err = lucky = n = 0
        for i in ids:
            g, o = gt[i].get(field), ocr[i].get(field)
            if g is None or o is None:
                continue
            n += 1
            if g and o:
                both += 1
            elif g and not o:
                ocr_err += 1
            elif not g and not o:
                llm_err += 1
            else:
                lucky += 1  # wrong on perfect text, right on OCR: LLM non-determinism
        print(f"{field[:-3]:10} {n:>8} {both:>8} {ocr_err:>8} {llm_err:>8} {lucky:>9}")
    items = lambda rows: (sum(r.get("item_hits", 0) for r in rows), sum(r.get("item_gold", 0) for r in rows))
    for name, rows in [("gt", [gt[i] for i in ids]), ("ocr", [ocr[i] for i in ids])]:
        h, g = items(rows)
        print(f"item recall on {name}: {100 * h / g:.1f}%")


if __name__ == "__main__":
    main(*sys.argv[1:3])
