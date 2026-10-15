"""Run OCR once over a folder of images and save the lines to disk.

OCR is the slowest stage (~7 s/receipt on CPU). Caching it lets us iterate on the
LLM extraction step many times without paying that cost again.

  python scripts/cache_ocr.py --data data/cord/test
  -> data/cord/test/ocr/<id>.json   ({"engine": ..., "lines": [...]})
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai.ocr import DEFAULT_ENGINE, load_engine  # noqa: E402


def is_valid(path: Path) -> bool:
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8"))["lines"], list)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def write_atomic(path: Path, text: str) -> None:
    """Write to a temp file, then rename. A crash mid-write leaves the old file (or
    none), never a half-written one: two cache files were once found full of NUL bytes."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cord/test")
    ap.add_argument("--engine", default=DEFAULT_ENGINE)
    args = ap.parse_args()

    out = Path(args.data, "ocr")
    out.mkdir(exist_ok=True)
    todo = [p for p in sorted(Path(args.data, "images").glob("*.png")) if not is_valid(out / f"{p.stem}.json")]
    if not todo:
        print("All images already cached.")
        return

    engine = load_engine(args.engine)
    for i, img in enumerate(todo, 1):
        lines = engine(str(img))
        write_atomic(out / f"{img.stem}.json", json.dumps({"engine": args.engine, "lines": lines}, ensure_ascii=False, indent=1))
        print(f"[{i}/{len(todo)}] {img.stem}: {len(lines)} lines", flush=True)


if __name__ == "__main__":
    main()
