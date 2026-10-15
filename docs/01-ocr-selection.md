# 01 — OCR selection (measured 2026-10-14)

Dataset: CORD v2 test split, 100 receipt photos (CC-BY-4.0, Park et al. 2019). All engines run on the CPU; the GPU is reserved for the LLM.
Script: `scripts/benchmark_ocr.py`. Per-image results are in `ocr_results/`.
CORD labels only cover the item and total region, so we report recall, not precision.

| Engine | Word recall | Line similarity | TOTAL found | s / receipt | Peak RAM |
|---|---|---|---|---|---|
| Tesseract 5.4 | 35.8% | 54.9 | 31.6% | 0.8 | 174 MB |
| Tesseract + preprocess | 45.1% | 67.7 | 38.9% | 0.7 | 160 MB |
| RapidOCR 1.4 (ONNX) | 69.8% | 92.4 | 93.7% | 2.2 | 656 MB |
| RapidOCR + preprocess | 73.5% | 92.2 | 92.6% | 3.0 | 664 MB |
| **PaddleOCR 3.7, PP-OCRv6 small** | **83.5%** | **93.2** | **94.7%** | 7.2 | 872 MB |
| PaddleOCR small + preprocess | 81.5% | 92.5 | 92.6% | 9.5 | 890 MB |
| PaddleOCR medium (3-image smoke test only) | 74.3% | 96.1 | 100% | 30.3 | 555 MB |

## Decision
**PaddleOCR with PP-OCRv6 small models, no preprocessing.** It is the most accurate. Each receipt is read once at upload, so ~7 s is acceptable.
Fallback if speed matters: RapidOCR (3× faster, ~14 points lower word recall, and it sometimes merges tokens such as `Qty2.0060.000`).

## Lessons
- Tesseract's rule-based layout analysis assumes flat, evenly lit scans and breaks on photos. Deep-learning detectors such as DBNet don't have that problem.
- Preprocessing helped Tesseract (+9 pts) but hurt the neural engines. They were trained on raw photos, so "cleaning" moves the input away from their training distribution.
- A bigger model was not better: medium was 5× slower and no more accurate on our smoke test. The full medium run was stopped after 23 min.

## Gotchas fixed
- PaddlePaddle 3.3 crashes on Windows CPU with oneDNN enabled. Fix: `enable_mkldnn=False`.
- The PaddleX model cache defaults to `C:\Users\<me>\.paddlex`. Redirected to `models/paddlex` via `PADDLE_PDX_CACHE_HOME`.
- Three OpenCV wheels are installed (`opencv-python`, `-headless` and `-contrib`, pulled in by different packages) and they share the `cv2` namespace. They work for now, but this is a dependency risk to pin down in `requirements.txt`.
