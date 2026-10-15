import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_ocr import score  # noqa: E402
from receipt_ai.ocr import Box, group_lines  # noqa: E402


def test_group_lines_joins_boxes_on_same_row_left_to_right():
    boxes = [
        Box("31.000", x=300, y=101, h=20),
        Box("TOTAL", x=20, y=100, h=20),
        Box("CASH", x=20, y=130, h=20),
    ]
    assert group_lines(boxes) == ["TOTAL 31.000", "CASH"]


def test_group_lines_separates_rows_closer_than_one_line_apart():
    # 12px apart with 20px tall boxes: more than half a line height -> different rows
    boxes = [Box("A", 0, 100, 20), Box("B", 0, 112, 20)]
    assert group_lines(boxes) == ["A", "B"]


def test_group_lines_empty():
    assert group_lines([]) == []


def test_score_counts_duplicate_words_only_as_often_as_ocr_saw_them():
    label = {"words": ["31.000", "31.000"], "lines": ["TOTAL 31.000"], "fields": {"total_price": "31.000"}}
    result = score(["TOTAL 31.000"], label)
    assert result["word_recall"] == 0.5
    assert result["total_found"] is True


def test_score_total_matches_ignoring_separators():
    label = {"words": [], "lines": [], "fields": {"total_price": "31.000"}}
    assert score(["TOTAL 31,000"], label)["total_found"] is True
    assert score(["TOTAL 31.500"], label)["total_found"] is False


def test_score_total_none_when_receipt_has_no_label():
    label = {"words": ["x"], "lines": ["x"], "fields": {"total_price": None}}
    assert score(["x"], label)["total_found"] is None
