"""Score one OCR engine on the CORD test split.

Run once per engine so each gets a fresh process (fair memory numbers):
  python scripts/benchmark_ocr.py --engine tesseract
  python scripts/benchmark_ocr.py --engine tesseract --preprocess

Metrics (CORD labels cover only the item/total region, so we measure recall, not precision):
  word_recall    : % of labelled words that appear exactly in the OCR output
  line_similarity: for each labelled line, best fuzzy match (0-100) against any OCR line, averaged
  total_found    : % of receipts whose TOTAL amount appears in the OCR output
                   -> the single number the spending assistant can least afford to get wrong
"""

import argparse
import json
import re
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import psutil
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai.ocr import load_engine  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class PeakRSS:
    """Samples this process's resident memory in a background thread."""

    def __init__(self) -> None:
        self.proc, self.peak, self._stop = psutil.Process(), 0, False
        self._t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop:
            self.peak = max(self.peak, self.proc.memory_info().rss)
            time.sleep(0.05)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop = True
        self._t.join()


def score(ocr_lines: list[str], label: dict) -> dict:
    ocr_tokens = Counter(norm(t) for line in ocr_lines for t in line.split())
    hits = 0
    for w in label["words"]:
        if ocr_tokens[norm(w)] > 0:
            ocr_tokens[norm(w)] -= 1
            hits += 1
    word_recall = hits / max(len(label["words"]), 1)

    sims = [max((fuzz.ratio(norm(g), norm(o)) for o in ocr_lines), default=0) for g in label["lines"]]

    total = label["fields"]["total_price"]
    ocr_numbers = {digits(t) for line in ocr_lines for t in line.split()} - {""}
    total_found = None if not total else digits(total) in ocr_numbers

    return {"word_recall": word_recall, "line_similarity": statistics.mean(sims) if sims else 0, "total_found": total_found}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["tesseract", "rapidocr", "paddleocr", "paddleocr-medium"])
    ap.add_argument("--preprocess", action="store_true")
    ap.add_argument("--data", default="data/cord/test")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default="docs/ocr_results")
    args = ap.parse_args()

    images = sorted(Path(args.data, "images").glob("*.png"))[: args.limit]
    tag = f"{args.engine}{'+pre' if args.preprocess else ''}"

    with PeakRSS() as mem:
        t0 = time.perf_counter()
        engine = load_engine(args.engine, args.preprocess)
        engine(str(images[0]))  # warm-up: first call often compiles/initialises
        load_s = time.perf_counter() - t0

        per_image, times, samples = [], [], {}
        for img in images:
            label = json.loads(Path(args.data, "labels", img.stem + ".json").read_text(encoding="utf-8"))
            t = time.perf_counter()
            lines = engine(str(img))
            times.append(time.perf_counter() - t)
            per_image.append({"id": img.stem, **score(lines, label)})
            if len(samples) < 3:
                samples[img.stem] = lines

    totals = [r["total_found"] for r in per_image if r["total_found"] is not None]
    summary = {
        "engine": tag,
        "images": len(per_image),
        "word_recall_pct": round(100 * statistics.mean(r["word_recall"] for r in per_image), 1),
        "line_similarity": round(statistics.mean(r["line_similarity"] for r in per_image), 1),
        "total_found_pct": round(100 * sum(totals) / len(totals), 1),
        "sec_per_image_median": round(statistics.median(times), 2),
        "load_s": round(load_s, 1),
        "peak_ram_mb": round(mem.peak / 2**20),
    }
    print(json.dumps(summary))

    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(args.out, f"{tag}.json").write_text(
        json.dumps({"summary": summary, "per_image": per_image, "samples": samples}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
