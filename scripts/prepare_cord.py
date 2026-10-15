"""Unpack the CORD v2 parquet into image files plus simplified ground-truth JSON.

CORD (naver-clova-ix/cord-v2), CC-BY-4.0: Park et al., "CORD: A Consolidated
Receipt Dataset for Post-OCR Parsing", 2019.

Output per receipt:
  data/cord/test/images/<id>.png
  data/cord/test/labels/<id>.json  ->  {"lines": [...], "words": [...], "fields": {...}}

"lines" rebuilds the printed lines (words grouped by row_id, sorted left to right),
which is what we compare OCR output against.
"""

import argparse
import io
import json
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image


def simplify(gt: dict) -> dict:
    rows = defaultdict(list)
    for line in gt["valid_line"]:
        for w in line["words"]:
            q = w["quad"]
            rows[w["row_id"]].append((q["y1"], q["x1"], w["text"]))

    # Order rows top-to-bottom by their mean y, words left-to-right by x.
    ordered = sorted(rows.values(), key=lambda ws: sum(y for y, _, _ in ws) / len(ws))
    lines = [" ".join(t for _, _, t in sorted(ws, key=lambda w: w[1])) for ws in ordered]
    words = [t for ws in ordered for _, _, t in sorted(ws, key=lambda w: w[1])]

    parse = gt["gt_parse"]
    total = parse.get("total", {})
    if isinstance(total, list):  # a few receipts have multiple total blocks
        total = total[0]
    sub = parse.get("sub_total", {})
    if isinstance(sub, list):
        sub = sub[0]
    menu = parse.get("menu", [])
    if isinstance(menu, dict):
        menu = [menu]

    return {
        "lines": lines,
        "words": words,
        "fields": {
            "total_price": total.get("total_price"),
            "subtotal_price": sub.get("subtotal_price"),
            "tax_price": sub.get("tax_price"),
            "item_names": [m.get("nm") for m in menu if m.get("nm")],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/cord/download/test.parquet")
    ap.add_argument("--out", default="data/cord/test")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)

    table = pq.read_table(args.parquet).to_pylist()
    for i, row in enumerate(table):
        img = Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB")
        img.save(out / "images" / f"{i:03d}.png")
        label = simplify(json.loads(row["ground_truth"]))
        (out / "labels" / f"{i:03d}.json").write_text(json.dumps(label, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(table)} receipts to {out}")


if __name__ == "__main__":
    main()
