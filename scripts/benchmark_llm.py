"""Benchmark a local Ollama model on this machine.

Measures, for each (model, num_ctx, device) combination:
  - load time            : how long Ollama took to load weights into memory
  - time to first token  : latency the user feels before anything appears
  - prompt eval speed    : tokens/s while reading the prompt (prefill)
  - generation speed     : tokens/s while writing the answer (decode)
  - VRAM / RAM used      : what the model actually costs, not what the file size suggests
  - JSON validity        : whether the model returned parseable JSON for a receipt task

Usage:
  python scripts/benchmark_llm.py --models qwen2.5:3b --ctx 2048 4096 --devices gpu cpu
"""

import argparse
import json
import statistics
import time

import psutil
import requests

try:
    import pynvml

    pynvml.nvmlInit()
    _GPU = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:  # no NVIDIA driver / NVML available
    _GPU = None

OLLAMA = "http://localhost:11434"

# A realistic task for this project: turn messy OCR text into structured JSON.
RECEIPT_OCR = """\
BIG BAZAAR  #1142
MG ROAD, BENGALURU
GSTIN 29ABCDE1234F1Z5
DATE: 14/09/2026   TIME 18:42
-----------------------------
AMUL BUTTER 500G      1 x 285.00   285.00
TATA SALT 1KG         2 x  28.00    56.00
BRIT BREAD WHT        1 x  45.00    45.00
SURF EXCEL 1KG        1 x 140.00   140.00
-----------------------------
SUBTOTAL                          526.00
CGST 2.5%                          13.15
SGST 2.5%                          13.15
TOTAL                    INR      552.30
PAID: UPI
"""

PROMPT = f"""Extract the receipt below into JSON with exactly these keys:
merchant (string), date (YYYY-MM-DD), currency (string), total (number),
tax (number), payment_method (string),
items (list of {{name, quantity, unit_price, line_total}}).
Return only JSON.

RECEIPT:
{RECEIPT_OCR}"""


def vram_used_mb() -> float | None:
    if _GPU is None:
        return None
    return pynvml.nvmlDeviceGetMemoryInfo(_GPU).used / 2**20


def ollama_ram_mb() -> float:
    """Resident memory of all Ollama processes (the server + model runner)."""
    total = 0
    for p in psutil.process_iter(["name", "memory_info"]):
        name = (p.info["name"] or "").lower()
        if "ollama" in name or "llama-server" in name:  # 0.40+ runs models in llama-server.exe
            total += p.info["memory_info"].rss
    return total / 2**20


def unload(model: str) -> None:
    requests.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)
    time.sleep(2)


def run_once(model: str, num_ctx: int, device: str) -> dict:
    options = {"num_ctx": num_ctx, "temperature": 0}
    if device == "cpu":
        options["num_gpu"] = 0  # offload zero layers to the GPU -> pure CPU inference

    # Unique first line defeats Ollama's prompt-prefix KV cache, so every run
    # pays the real prompt-processing cost instead of a cache hit.
    prompt = f"Request id {time.time_ns()}.\n{PROMPT}"
    body = {"model": model, "prompt": prompt, "stream": True, "format": "json", "options": options}

    start = time.perf_counter()
    first_token_at = None
    text, final = [], {}
    peak_vram = vram_used_mb() or 0
    with requests.post(f"{OLLAMA}/api/generate", json=body, stream=True, timeout=600) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("response") and first_token_at is None:
                first_token_at = time.perf_counter()
            text.append(chunk.get("response", ""))
            peak_vram = max(peak_vram, vram_used_mb() or 0)
            if chunk.get("done"):
                final = chunk

    ps = requests.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])
    loaded = next((m for m in ps if m["name"].startswith(model.split(":")[0])), {})

    try:
        json.loads("".join(text))
        valid_json = True
    except json.JSONDecodeError:
        valid_json = False

    ns = 1e9
    return {
        "load_s": final.get("load_duration", 0) / ns,
        "ttft_s": (first_token_at or time.perf_counter()) - start,
        "prompt_tok_s": final.get("prompt_eval_count", 0) / max(final.get("prompt_eval_duration", 1) / ns, 1e-9),
        "gen_tok_s": final.get("eval_count", 0) / max(final.get("eval_duration", 1) / ns, 1e-9),
        "prompt_tokens": final.get("prompt_eval_count", 0),
        "gen_tokens": final.get("eval_count", 0),
        "model_size_mb": loaded.get("size", 0) / 2**20,
        "model_in_vram_mb": loaded.get("size_vram", 0) / 2**20,
        "peak_gpu_vram_mb": peak_vram,
        "ollama_ram_mb": ollama_ram_mb(),
        "valid_json": valid_json,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen2.5:3b"])
    ap.add_argument("--ctx", nargs="+", type=int, default=[2048, 4096])
    ap.add_argument("--devices", nargs="+", choices=["gpu", "cpu"], default=["gpu", "cpu"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default="docs/benchmark_results.json")
    args = ap.parse_args()

    results = []
    for model in args.models:
        for device in args.devices:
            for num_ctx in args.ctx:
                unload(model)  # cold start each config so load numbers are honest
                runs = [run_once(model, num_ctx, device) for _ in range(args.runs)]
                warm = runs[1:] or runs  # first run includes model load; ignore it for speed
                row = {
                    "model": model,
                    "device": device,
                    "num_ctx": num_ctx,
                    "cold_load_s": round(runs[0]["load_s"], 2),
                    "ttft_s": round(statistics.median(r["ttft_s"] for r in warm), 2),
                    "prompt_tok_s": round(statistics.median(r["prompt_tok_s"] for r in warm), 1),
                    "gen_tok_s": round(statistics.median(r["gen_tok_s"] for r in warm), 1),
                    "prompt_tokens": runs[-1]["prompt_tokens"],
                    "gen_tokens": runs[-1]["gen_tokens"],
                    "model_size_mb": round(runs[-1]["model_size_mb"]),
                    "model_in_vram_mb": round(runs[-1]["model_in_vram_mb"]),
                    "peak_gpu_vram_mb": round(max(r["peak_gpu_vram_mb"] for r in runs)),
                    "ollama_ram_mb": round(max(r["ollama_ram_mb"] for r in runs)),
                    "json_valid": f"{sum(r['valid_json'] for r in runs)}/{len(runs)}",
                }
                results.append(row)
                print(json.dumps(row))

    unload(args.models[-1])
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} rows to {args.out}")


if __name__ == "__main__":
    main()
