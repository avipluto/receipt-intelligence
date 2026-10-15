"""End-to-end demo: ingest a few receipt images into a fresh DB, then ask questions.

  python scripts/demo_ask.py --n 8 --db data/db/demo.db
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai import db, pipeline  # noqa: E402
from receipt_ai.ask import ask  # noqa: E402

QUESTIONS = [
    "How much did I spend in total?",
    "Which store got the most money from me?",
    "Did I buy any coffee?",
    "Show me my receipts",
    "How much did I spend last month?",
    "What did I pay for chicken?",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="data/cord/test/images")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--db", default="data/db/demo.db")
    args = ap.parse_args()

    conn = db.connect(args.db)
    for img in sorted(Path(args.images).glob("*.png"))[: args.n]:
        t = time.perf_counter()
        r = pipeline.ingest(img, conn)
        rec = r.receipt
        print(f"{img.name}: id={r.receipt_id} src={r.text_source} {time.perf_counter() - t:.1f}s "
              f"merchant={rec.merchant if rec else None!r} total={rec.total if rec else None} "
              f"review={rec.needs_review if rec else None} err={r.error}", flush=True)

    for q in QUESTIONS:
        t = time.perf_counter()
        a = ask(conn, q)
        print(f"\nQ: {q}\n   route={a.route.model_dump(exclude_none=True)}  period={a.period_text!r}")
        print(f"   A ({'llm' if a.used_llm else 'template'}, {time.perf_counter() - t:.1f}s): {a.text}")
        print(f"   cites receipts: {a.result.to_dict().get('receipt_ids')}")


if __name__ == "__main__":
    main()
