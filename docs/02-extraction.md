# 02 — LLM extraction: prompt and check iterations (measured 2026-10-15)

Model: qwen2.5:3b (Q4_K_M) through Ollama, temperature 0, num_ctx 4096, structured outputs (JSON schema).
Data: CORD v2 test split, 100 receipts. Script: `scripts/eval_extraction.py`; per-receipt rows are in `extraction_results/`.

Every version is run on two inputs:
- **gt**: the labelled ("perfect") text. Errors here are the LLM's fault.
- **ocr**: PaddleOCR's real output. The gap between gt and ocr is the OCR's fault.

`scripts/compare_runs.py gt.json ocr.json` splits each field's errors into those two buckets.

## Results on perfect text (gt)

| Version | Change | Total | Subtotal | Tax | Item recall | Catch rate ↑ | False alarms ↓ | Failed calls |
|---|---|---|---|---|---|---|---|---|
| v1 | baseline prompt | 92.6 | 0.0 | 2.4 | 82.6 | 42.9 | 32.2 | 1 |
| v2 | every schema key **required** | 94.7 | 93.8 | 53.7 | 80.0 | 40.0 | 44.4 | 1 |
| v3 | tax labels (PB1, PPN, VAT, GST); `"null"` string → None | 93.5 | 98.4 | 82.9 | 79.3 | 50.0 | 37.2 | 4 |
| v4 | `service_charge` + `discount` fields in the total check; output cap; 1 retry | 86.2 | 95.3 | 92.5 | 79.1 | 76.9 | 28.4 | 1 |
| v5 | "line_total already includes quantity"; "total is not CASH" | 88.2 | 98.5 | 95.1 | 83.1 | 72.7 | 29.3 | 2 |
| v6 | `cash_paid` + `change` fields, `cash − change = total` check | 87.4 | 96.9 | 95.1 | 84.9 | **100** | 30.1 | 0 |
| v7 | Python repairs the total from cash − change | **94.7** | 96.9 | **95.1** | **84.9** | 80.0 | 30.0 | **0** |
| v8 | check accepts discount inside the subtotal, and split payments (Python only, via `--rescore`) | 94.7 | 96.9 | 95.1 | 84.9 | 80.0 | **27.8** | 0 |

Catch rate: of receipts with a wrong total, the share flagged "needs review". False alarms: of receipts with a correct total, the share flagged anyway.

## OCR vs LLM: where do the errors come from? (v2)

| Field | Labelled | Right on both | OCR-caused | LLM-caused |
|---|---|---|---|---|
| total | 93 | 74 | **14** | 5 |
| subtotal | 62 | 53 | 5 | 4 |
| tax | 40 | 19 | 3 | **18** |

Item recall: 80.0% on perfect text, 73.0% on OCR.

- **Total errors are mostly OCR.** There are three kinds: the label and amount land on different lines (`TOTAL` on one line, the number on another); digits are misread (`5,000` for 54,000, `48:888`); or the number is read correctly but the noisier text leads the LLM to pick the CASH amount. A prompt can't fix misread digits, which is why the arithmetic check exists: it flagged 10 of the 14.
- **Tax errors are mostly the LLM.** CORD is Indonesian, where restaurant tax is printed as **PB1**. A 3B model doesn't know that PB1 means tax. Naming it in the prompt (v3) took tax from 53.7% to 82.9%.

## The real pipeline (OCR input): v2 → v10

| Version | Change | Total | Subtotal | Tax | Item recall | Catch rate ↑ | False alarms ↓ | Failed calls |
|---|---|---|---|---|---|---|---|---|
| v2 | | 79.6 | 84.1 | 47.5 | 73.0 | 68.4 | 51.4 | 2 |
| v8 | prompt + checks (above) | 87.4 | 87.7 | 73.2 | 74.9 | 91.7 | 34.9 | 0 |
| v9 | tilt-aware OCR line grouping (see below) | 90.4 | 90.6 | 80.0 | 75.4 | 77.8 | 32.9 | 2 |
| v10 | cash − change repair only when positive (Python only, `--rescore`) | **91.5** | **90.6** | **80.0** | **75.4** | 75.0 | **32.6** | 2 |

Where the remaining v8 errors come from:

| Field | Labelled | Right on both | OCR-caused | LLM-caused |
|---|---|---|---|---|
| total | 95 | 81 | **9** | 3 |
| subtotal | 65 | 55 | **8** | 0 |
| tax | 41 | 30 | **9** | 2 |

**After v8 the bottleneck is the OCR, not the LLM.** More prompt work has little left to gain. The next accuracy gains come from OCR line grouping (keeping a label and its amount together) and from the review flag, which already catches 92% of wrong totals.

### v9: OCR line grouping on tilted photos

PaddleOCR returns text *segments*; `ocr.group_lines` joins segments whose vertical centres are within half a line height. On a tilted photo that fails. On CORD 095 (rotated ~2.7°), each amount sits 550 px to the right of its label and 27 px higher, so `TOTAL` and `56,181` ended up on different lines.

Fix: estimate the page's tilt from the boxes themselves (width-weighted median slope of their top and bottom edges; short boxes don't vote, and the median ignores junk), then group on `y − tilt × x`, i.e. as if the photo were straight. Text height is now measured along the box edges; the old vertical extent was inflated by the tilt.

Measured *before* running the LLM, on the same detector boxes (`scripts/score_ocr_cache.py`):

| | old grouping | new grouping |
|---|---|---|
| Total on the same line as a TOTAL label | 78.9% | **83.2%** |
| Line similarity to labels | 93.2 | **94.3** |
| Word recall (grouping can't change it) | 83.5 | 83.5 |

4 receipts were fixed, none broken. The old rule applied to the new boxes reproduces the old cache 100/100, so OCR itself was unchanged and the gain is entirely from grouping. The cache now stores the raw boxes; `cache_ocr.py --regroup` re-tests a grouping change in seconds.

With the LLM (v9): total 87.4 → 90.4, tax 73.2 → 80.0. Not every change is due to grouping: 035 and 064 improved and 005 got worse with **identical** OCR lines, which is the LLM's run-to-run noise (about ±1–2 receipts). v9 also exposed a bug in the v7 repair. On 080, grouping fixed the line and the LLM read the total right, but it also copied the cash amount into `change`, and "total = cash − change" turned that into a total of 0. v10 only repairs to a positive amount.

**Two receipts are beyond grouping:** on 013 the detector never found the amounts, and on 020 it read them as junk (`00`, `0--0n`). That needs a better detector or image preprocessing.

**Catch rate fell (92% → 75%) for a good reason:** grouping fixed the wrong totals that were easy to catch. 8 wrong totals remain and 6 are flagged; the 2 unflagged ones are 020 (no amounts readable) and 067 (`9.500,00` copied as `9,500,00`, consistent with itself everywhere).

The 2 failed calls are back-to-back Ollama timeouts (057, 058: 4 minutes each with the retry). The server stalled; both receipts succeeded in every earlier run.

### Rejected: accepting "tax-inclusive" totals
Letting `total == subtotal` pass when a tax line is printed would cut false alarms by 1–2 receipts, with no catch-rate loss *on this set*. It was rejected anyway. There are only 12 wrong totals in the set, so "no measured harm" proves little, and the change would hide a classic misread (copying the subtotal as the total). A test now pins that case.

## Lessons

1. **Measure each change on its own, on a fixed set.** v4 improved tax and flags but cut total accuracy by 7 points. We only saw it because every version runs on the same 100 receipts and the per-receipt rows can be diffed.
2. **More fields can distract a small model.** After v4 added two fields between `tax` and `total`, the model started copying `CASH 70.000` as the total. JSON keys are generated in schema order, so what sits just before `total` matters.
3. **Give the distractor its own slot, then let Python do the maths.** v6 added `cash_paid` and `change` fields. The model still made mistakes (now it often left total null), but the new `cash − change` check caught **every** wrong total (catch rate 100%). In v7, Python derives the total from those two numbers. The LLM only reads; Python computes, and the subtotal/items checks still verify the result.
4. **Fix data problems in code, not with more prompting.** The model writes `"null"`, `"Not specified"` and so on instead of JSON null. That's a Python cleanup (`clean_text`), and a "date" with no digits counts as missing.
5. **The first diagnosis was wrong.** The crash blamed on "a non-JSON Ollama reply" actually came from two cached OCR files full of NUL bytes, left by a write that was interrupted. Fixes: atomic writes (temp file + `os.replace`), and an eval that records a bad file as an error row instead of dying. Read the traceback's *file and line* before you believe a story about it.
6. **Local LLM servers fail intermittently.** About 2–4% of calls failed (HTTP 500 or runaway generation) and then succeeded when re-run, even at temperature 0. (Likely cause, not proven: Ollama reuses its prompt cache across requests, so GPU arithmetic can depend on the previous request.) One retry plus `num_predict=1500` (so a looping model stops in seconds rather than hitting the 2-minute timeout) brought failed calls to 0–1 per 100.
7. **Keep the expensive step separate from the cheap one.** From v7 on, eval rows save the raw LLM JSON, so `--rescore` re-tests Python-only changes (parsing, repairs, checks) in seconds instead of a 13-minute LLM run.
8. **Small samples can't prove a change safe.** See "Rejected" above: when the downside is a known failure mode, keep the strict rule even if your eval set can't show the harm.
9. **Separate the variable you changed from the noise.** Per-receipt diffs plus "were the OCR lines identical?" told grouping gains apart from LLM run-to-run noise, and found a bug in an older rule that the new input exposed.

## Remaining weaknesses

- About 28% (gt) / 35% (ocr) of receipts with a correct total are still flagged. Most come from the items-sum check, and most of those are *real* item errors: the model multiplies quantity × price despite the prompt, duplicates lines, or fills quantity with junk like `"bytes"`. The total is right but item-level answers would be wrong, so the flag is earned. "False alarm on correct totals" overstates the problem; a better metric would score flags per field.
- Garbled amounts like `9.500,00` copied as `950000`. A plausibility check (total vs items) flags these but can't fix them.
- OCR that misses amounts entirely (CORD 013, 020): needs a stronger detector or preprocessing, not grouping.
- Curved or crumpled receipts: the tilt fix assumes one straight tilt per photo.

