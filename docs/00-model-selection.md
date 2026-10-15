# 00 — Model selection (measured 2026-10-14)

Hardware: RTX 2050 4 GB (3.2 GB usable), i5-12th gen H, 15.6 GB RAM. Ollama 0.40.4, models in `D:\ollama\models`.
Raw data: `benchmark_results.json` (from `scripts/benchmark_llm.py`, 344-token receipt prompt, ~252 output tokens).

| Device | ctx | VRAM | RAM | Prompt tok/s | Gen tok/s | Time to first token | Valid JSON |
|---|---|---|---|---|---|---|---|
| GPU | 2048 | 2.2 GB | 0.8 GB | 754 | 37.3 | 2.6 s | 3/3 |
| GPU | 4096 | 2.3 GB | 0.8 GB | 902 | 37.1 | 2.5 s | 3/3 |
| CPU | 2048 | — | 2.1 GB | 50 | 11.2 | 9.0 s | 3/3 |
| CPU | 4096 | — | 2.2 GB | 44 | 9.0 | 9.9 s | 3/3 |

## Decision
- **Model:** `qwen2.5:3b` (Q4_K_M), **GPU**, `num_ctx=4096`. ~7 s per full receipt extraction.
- Going from 2K to 4K context cost only ~75 MB of VRAM (predicted ~75 MB from 36 KB/token × 2048). That left ~0.9 GB of VRAM headroom.
- **OCR and embeddings run on the CPU** to keep the GPU free for the LLM.
- Fallback: CPU mode works (3.3× slower generation, 16× slower prompt reading). `qwen2.5:1.5b` was not needed.
- Licence: Qwen2.5-3B uses the Qwen Research License (non-commercial). Before any commercial use, switch to the Apache-2.0 1.5B/7B models.

## Benchmark bugs found and fixed
1. Prompt caching: an identical prompt on every run let Ollama reuse its KV cache, which made CPU prompt reading look faster than the GPU. Fix: a unique first line per run.
2. RAM showed 58 MB because Ollama 0.40 loads models in `llama-server.exe`. Fix: match that process name too.

## Open question
On the GPU, the time to first token (~2.5 s) is much larger than the prompt-reading time (~0.4 s). Suspect: the JSON-format grammar setup. Investigate when we build the extraction step.
