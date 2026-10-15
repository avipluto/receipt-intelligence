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


def test_box_from_quad_measures_tilt_and_true_height():
    from receipt_ai.ocr import Box

    # 200 px wide, 20 px tall, right end 10 px higher (slope -0.05).
    b = Box.from_quad("TOTAL", [[0, 110], [200, 100], [200, 120], [0, 130]])
    assert round(b.slope, 3) == -0.05 and b.h == 20 and b.w == 200


def test_estimate_skew_ignores_short_boxes_and_outliers():
    from receipt_ai.ocr import Box, estimate_skew

    boxes = [Box("wide", 0, 0, 20, 300, -0.04), Box("wide2", 0, 0, 20, 200, -0.05),
             Box("x", 0, 0, 20, 20, 0.9),  # short box: no vote
             Box("junk", 0, 0, 20, 60, 0.3)]  # an outlier the weighted median outvotes
    assert estimate_skew(boxes) == -0.04
    assert estimate_skew([]) == 0.0


def test_tilted_photo_keeps_label_and_amount_together():
    # Synthetic: page tilted with slope -0.05; amount 600 px right of its label sits 30 px higher.
    from receipt_ai.ocr import Box

    def box(text, x, y, w):  # a straight-text box on a tilted page
        return Box(text, x, y, 20, w, -0.05)

    boxes = [box("TOTAL", 100, 200, 100), box("56,181", 700, 170, 100),
             box("TAX", 100, 240, 100), box("5,618", 700, 210, 100)]
    assert group_lines(boxes, deskew=False) != ["TOTAL 56,181", "TAX 5,618"]  # the old bug
    assert group_lines(boxes) == ["TOTAL 56,181", "TAX 5,618"]


def test_real_cord_095_boxes_pair_labels_with_amounts():
    import json

    from receipt_ai.ocr import lines_from_quads

    quads = json.loads((ROOT / "tests" / "data" / "cord_095_quads.json").read_text(encoding="utf-8"))["quads"]
    lines = lines_from_quads(quads)
    for expected in ["TOTAL 56,181", "TAX 10.00 % 5,618", "GRAND TOTAL 61,799", "TUNAI 62,000", "KEMBALI 201"]:
        assert expected in lines, lines
