"""Benchmark candidate stylist models on the real recommendation task.

Scores each model the way the app actually uses it: build the genuine
stylist prompt from a wardrobe, ask for an outfit, then grade the reply —

- valid:   returned parseable JSON passing full stylist validation
           (real IDs from the candidate slots, all required slots filled)
- latency: seconds to a validated answer (first call includes model load)
- rationale length: sanity signal that it explained itself

Usage:
    python scripts/bench_models.py [--url http://localhost:11434]
                                   [--models m1 m2 ...] [--runs 3]
                                   [--wardrobe seed|full]

Without --models, every model listed on the server is benchmarked.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR.parent / "backend"))

import httpx  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.llm.provider import OllamaProvider  # noqa: E402
from app.services import stylist  # noqa: E402
from app.services.candidates import select  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "seed_wardrobe", SCRIPTS_DIR / "seed_wardrobe.py"
)
_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_seed)
SEED_ITEMS = [
    {
        "id": i + 1,
        "name": n, "type": t, "category": cat, "color": c,
        "warmth": w, "formality": f,
        "style_tags": tags, "notes": None, "times_worn": 0,
        "persona_id": persona,
    }
    for i, (n, t, cat, c, w, f, tags, persona) in enumerate(_seed.SAMPLE_WARDROBE)
]


def bench_one(provider: OllamaProvider, model: str, candidates, runs: int) -> dict:
    """Run the stylist task `runs` times; return score summary."""
    results = {"model": model, "ok": 0, "fail": 0, "latencies": [], "rationale_words": []}

    # Vary the mood per run: a stylist that only handles one mood is useless.
    moods = [
        ("feeling cosy and relaxed, want soft unstructured comfort", "casual"),
        ("confident and sharp, want to make an impression", "work"),
        ("playful and energetic, bright colors welcome", "casual"),
    ]

    for i in range(runs):
        mood, occasion = moods[i % len(moods)]
        # Fresh candidate set per occasion/temperature for a realistic mix.
        cs = select(
            SEED_ITEMS,
            temp_c=[18.0, 8.0, 26.0][i % 3],
            occasion=occasion,
            rng_seed=20260903,
        )
        t0 = time.time()
        try:
            choice = stylist.choose(provider, model, cs, mood, occasion)
        except stylist.StylistError as exc:
            results["fail"] += 1
            results.setdefault("errors", []).append(str(exc)[:80])
            continue
        elapsed = time.time() - t0
        results["ok"] += 1
        results["latencies"].append(elapsed)
        results["rationale_words"].append(len(choice.rationale.split()))

    lat = results["latencies"]
    results["latency_avg"] = sum(lat) / len(lat) if lat else None
    results["latency_max"] = max(lat) if lat else None
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:11434")
    parser.add_argument("--models", nargs="*", default=None,
                        help="models to benchmark (default: all on the server)")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    resp = httpx.get(f"{args.url}/api/tags", timeout=10)
    resp.raise_for_status()
    available = [m["name"] for m in resp.json().get("models", [])]
    if not available:
        sys.exit(f"No models listed on {args.url}")

    models = args.models or available
    for m in models:
        if m not in available:
            sys.exit(f"Model {m!r} not found on {args.url}. Available: {available}")

    # Warm the DB path (not used for storage here, just keeps imports honest).
    cfg = AppConfig(db_path=Path("/dev/null"))

    provider = OllamaProvider(args.url, timeout=300.0)
    print(f"Benchmarking {len(models)} model(s) on {args.url}, {args.runs} run(s) each\n")
    print(f"{'model':28} {'ok':>4} {'fail':>5} {'avg_s':>7} {'max_s':>7} {'rationale':>10}")
    print("-" * 68)

    all_results = []
    for model in models:
        # Deterministic candidate sets identical across models for fairness.
        r = bench_one(provider, model, None, args.runs)
        all_results.append(r)
        avg = f"{r['latency_avg']:.1f}" if r["latency_avg"] else "—"
        mx = f"{r['latency_max']:.1f}" if r["latency_max"] else "—"
        words = (
            f"{sum(r['rationale_words']) / len(r['rationale_words']):.0f}"
            if r["rationale_words"] else "—"
        )
        print(f"{model:28} {r['ok']:>4} {r['fail']:>5} {avg:>7} {mx:>7} {words:>10}")

    # Verdict: models with all runs valid, ranked by average latency.
    valid = [r for r in all_results if r["fail"] == 0 and r["ok"] == args.runs]
    print()
    if valid:
        best = min(valid, key=lambda r: r["latency_avg"])
        print(f"Best stylist model: {best['model']} "
              f"(all runs valid, avg {best['latency_avg']:.1f}s)")
    else:
        print("No model passed every run — check output above before choosing.")


if __name__ == "__main__":
    main()
