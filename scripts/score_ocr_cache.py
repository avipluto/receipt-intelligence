"""Score cached OCR lines against CORD labels, without running OCR or the LLM.

  python scripts/score_ocr_cache.py data/cord/test/ocr_v8 data/cord/test/ocr

Metrics:
  word_recall       share of labelled words OCR produced (grouping can't change this)
  line_similarity   how well each labelled line matches its best OCR line (0-100):
                    the metric that grouping actually moves
  total_found       the total's digits appear anywhere in the OCR text
  total_on_line     one OCR line holds both a TOTAL label and the right amount,
                    the pairing the LLM needs
"""

import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from benchmark_ocr import digits, score  # noqa: E402


def total_on_line(lines: list[str], total: str | None) -> bool | None:
    if not total:
        return None
    want = digits(total)
    return any(re.search(r"total", ln, re.I) and want in {digits(t) for t in ln.split()} for ln in lines)


def score_folder(folder: Path, labels: Path) -> dict:
    rows = []
    for f in sorted(folder.glob("*.json")):
        lines = json.loads(f.read_text(encoding="utf-8"))["lines"]
        label = json.loads((labels / f.name).read_text(encoding="utf-8"))
        r = score(lines, label)
        r["total_on_line"] = total_on_line(lines, label["fields"].get("total_price"))
        rows.append(r)

    def mean(key, pct=True):
        xs = [r[key] for r in rows if r[key] is not None]
        return round((100 if pct else 1) * statistics.mean(xs), 1)

    return {"files": len(rows), "word_recall": mean("word_recall"), "line_similarity": mean("line_similarity", pct=False),
            "total_found": mean("total_found"), "total_on_line": mean("total_on_line")}


if __name__ == "__main__":
    labels = Path("data/cord/test/labels")
    for folder in sys.argv[1:]:
        print(folder, json.dumps(score_folder(Path(folder), labels)))
