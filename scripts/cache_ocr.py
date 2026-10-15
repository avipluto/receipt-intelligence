"""Run OCR once over a folder of images and save the lines to disk.

OCR is the slowest stage (~7 s/receipt on CPU). Caching it lets us iterate on the
LLM extraction step many times without paying that cost again.

  python scripts/cache_ocr.py --data data/cord/test
  -> data/cord/test/ocr/<id>.json   ({"engine": ..., "lines": [...]})
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai.ocr import DEFAULT_ENGINE, load_engine  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cord/test")
    ap.add_argument("--engine", default=DEFAULT_ENGINE)
    args = ap.parse_args()

    out = Path(args.data, "ocr")
    out.mkdir(exist_ok=True)
    todo = [p for p in sorted(Path(args.data, "images").glob("*.png")) if not (out / f"{p.stem}.json").exists()]
    if not todo:
        print("All images already cached.")
        return

    engine = load_engine(args.engine)
    for i, img in enumerate(todo, 1):
        lines = engine(str(img))
        (out / f"{img.stem}.json").write_text(
            json.dumps({"engine": args.engine, "lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"[{i}/{len(todo)}] {img.stem}: {len(lines)} lines", flush=True)


if __name__ == "__main__":
    main()
