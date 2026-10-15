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
from receipt_ai.ocr import DEFAULT_ENGINE, lines_from_quads, load_engine  # noqa: E402


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
    ap.add_argument("--out", default="ocr", help="sub-folder of --data to write to")
    ap.add_argument("--regroup", action="store_true",
                    help="rebuild lines from the stored boxes with the current group_lines; no OCR, seconds")
    args = ap.parse_args()

    out = Path(args.data, args.out)
    out.mkdir(exist_ok=True)
    if args.regroup:
        regroup(out)
        return
    todo = [p for p in sorted(Path(args.data, "images").glob("*.png")) if not is_valid(out / f"{p.stem}.json")]
    if not todo:
        print("All images already cached.")
        return

    engine = load_engine(args.engine)
    for i, img in enumerate(todo, 1):
        # Store the raw detector boxes too: line grouping can then be changed and
        # re-tested (--regroup) without paying ~10 s of OCR per image again.
        quads = engine.quads(str(img))
        lines = lines_from_quads(quads)
        payload = {"engine": args.engine, "lines": lines, "quads": quads}
        write_atomic(out / f"{img.stem}.json", json.dumps(payload, ensure_ascii=False))
        print(f"[{i}/{len(todo)}] {img.stem}: {len(lines)} lines", flush=True)


def regroup(folder: Path) -> None:
    changed = 0
    for f in sorted(folder.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if "quads" not in data:
            raise SystemExit(f"{f} has no stored boxes; re-run OCR to create them")
        lines = lines_from_quads(data["quads"])
        changed += lines != data["lines"]
        data["lines"] = lines
        write_atomic(f, json.dumps(data, ensure_ascii=False))
    print(f"Regrouped {folder}: {changed} file(s) changed.")


if __name__ == "__main__":
    main()
