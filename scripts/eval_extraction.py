"""Score LLM extraction against CORD labels.

  python scripts/eval_extraction.py --source ocr --tag v1   # real pipeline: PaddleOCR lines -> LLM
  python scripts/eval_extraction.py --source gt  --tag v1   # oracle: perfect OCR text -> LLM

Running both separates the two error sources: if accuracy is high on gt but low on
ocr, the OCR is the bottleneck; if both are low, the prompt/model is.

Metrics (each on the receipts where that field is labelled):
  total_acc / subtotal_acc / tax_acc : parsed value equals the parsed label exactly
  item_recall / item_precision       : fuzzy (>=85) one-to-one match of item names
  flag_catch_rate  : of receipts with a WRONG total, % flagged needs_review  (want high)
  flag_false_alarm : of receipts with a CORRECT total, % flagged anyway      (want low)
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai.extract import extract  # noqa: E402
from receipt_ai.schema import parse_amount  # noqa: E402


def match_items(pred: list[str], gold: list[str], threshold: int = 85) -> int:
    remaining = list(gold)
    hits = 0
    for p in pred:
        best = max(remaining, key=lambda g: fuzz.ratio(p.lower(), g.lower()), default=None)
        if best is not None and fuzz.ratio(p.lower(), best.lower()) >= threshold:
            remaining.remove(best)
            hits += 1
    return hits


def gold_amount(value):
    """A few CORD labels list a field twice, e.g. tax_price ['6,818', '0']: take the first non-zero."""
    values = value if isinstance(value, list) else [value]
    parsed = [parse_amount(v) for v in values]
    return next((p for p in parsed if p), parsed[0] if parsed else None)


def pct(xs: list[bool]) -> float | None:
    return round(100 * sum(xs) / len(xs), 1) if xs else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["ocr", "gt"], default="ocr")
    ap.add_argument("--data", default="data/cord/test")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--out", default="docs/extraction_results")
    args = ap.parse_args()

    label_files = sorted(Path(args.data, "labels").glob("*.json"))[: args.limit]
    rows = []
    for i, lf in enumerate(label_files, 1):
        label = json.loads(lf.read_text(encoding="utf-8"))
        if args.source == "gt":
            lines = label["lines"]
        else:
            ocr_file = Path(args.data, "ocr", lf.name)
            if not ocr_file.exists():
                continue
            lines = json.loads(ocr_file.read_text(encoding="utf-8"))["lines"]

        result = extract(lines)
        f, r = label["fields"], result.receipt
        row = {"id": lf.stem, "seconds": round(result.seconds, 2), "error": result.error}
        if r:
            for key, attr in [("total", "total"), ("subtotal", "subtotal"), ("tax", "tax")]:
                gold = gold_amount(f.get(f"{key}_price"))
                row[f"{key}_ok"] = None if gold is None else r.__getattribute__(attr) == gold
            pred_names = [it.name for it in r.items]
            hits = match_items(pred_names, f["item_names"])
            row.update(
                item_hits=hits, item_pred=len(pred_names), item_gold=len(f["item_names"]),
                flagged=r.needs_review, issues=r.issues,
                pred_total=str(r.total), gold_total=f.get("total_price"),
            )
        rows.append(row)
        print(f"[{i}/{len(label_files)}] {lf.stem} total_ok={row.get('total_ok')} {row['seconds']}s {row['error'] or ''}", flush=True)

    ok = [r for r in rows if not r["error"]]

    def field(name):
        return [r[name] for r in ok if r.get(name) is not None]

    wrong_total = [r for r in ok if r.get("total_ok") is False]
    right_total = [r for r in ok if r.get("total_ok") is True]
    summary = {
        "tag": args.tag,
        "source": args.source,
        "receipts": len(rows),
        "valid_pct": pct([not r["error"] for r in rows]),
        "total_acc": pct(field("total_ok")),
        "subtotal_acc": pct(field("subtotal_ok")),
        "tax_acc": pct(field("tax_ok")),
        "item_recall": pct([True] * sum(r["item_hits"] for r in ok) + [False] * (sum(r["item_gold"] for r in ok) - sum(r["item_hits"] for r in ok))),
        "item_precision": pct([True] * sum(r["item_hits"] for r in ok) + [False] * (sum(r["item_pred"] for r in ok) - sum(r["item_hits"] for r in ok))),
        "flag_catch_rate": pct([r["flagged"] for r in wrong_total]),
        "flag_false_alarm": pct([r["flagged"] for r in right_total]),
        "sec_median": round(statistics.median(r["seconds"] for r in rows), 1),
    }
    print(json.dumps(summary))
    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(args.out, f"{args.tag}-{args.source}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
