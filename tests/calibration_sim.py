#!/usr/bin/env python3
"""Calibration check across many simulated accounts.

    python tests/calibration_sim.py

Each account has a slowly drifting size and results with a known tail shape. A judge signal of
known quality is attached to every post, its reliability is measured the way a blind backtest
would measure it, and the forecasts for the next posts are compared with what happens.

This reproduces the table in references/methodology.md. It tests the arithmetic under the model's
own assumptions. It says nothing about how well anyone reads a video.
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "virality-forecaster" / "scripts"))
import vforecast as vf  # noqa: E402

SHAPES = {
    "normal": lambda u: 0.35 * u,
    "skewed": lambda u: 0.35 * u + 0.06 * (u ** 2 - 1),
    "occasional breakouts": lambda u: 0.28 * u + 0.9 * np.maximum(u - 1.3, 0) ** 1.4,
}


def run(shape, n_hist, r_signal, accounts=400, tests=10, seed=1):
    rng = np.random.default_rng(seed)
    series, pool_s, pool_rp = [], [], []
    for _ in range(accounts):
        n = n_hist + tests
        u = rng.standard_normal(n)
        lat = 3.5 + np.cumsum(rng.normal(0, 0.03, n)) + SHAPES[shape](u)
        sig = r_signal * u + math.sqrt(1 - r_signal ** 2) * rng.standard_normal(n)
        series.append((lat, sig))
        _, rp = vf.rolling_rp(list(lat), 10)
        for i in range(n_hist):
            if rp[i] is not None:
                pool_s.append(sig[i])
                pool_rp.append(rp[i])
    measured = vf.spearman(pool_s, pool_rp)
    cover, hits = [], {2: [], 3: [], 10: []}
    for lat, sig in series:
        for t in range(n_hist, n_hist + tests):
            hist = list(lat[:t])
            _, rp = vf.rolling_rp(hist, 10)
            marg = vf.Marginal(sorted(x for x in rp if x is not None), "count")
            base = float(np.median(hist[-10:]))
            fc = vf.make_forecast(float(sig[t]), measured, marg, base, "count", (2, 3, 10))
            cover.append(fc["quantiles"]["p10"] <= vf.from_latent(lat[t], "count") <= fc["quantiles"]["p90"])
            for k in hits:
                hits[k].append((fc["p"][f"x{k}"], float(lat[t] - base >= math.log10(k)), fc["base"][f"x{k}"]))
    row = {"shape": shape, "n_hist": n_hist, "r": measured, "cover": float(np.mean(cover))}
    for k, values in hits.items():
        a = np.array(values)
        row[f"f{k}"], row[f"o{k}"] = float(a[:, 0].mean()), float(a[:, 1].mean())
        ref = float(((a[:, 2] - a[:, 1]) ** 2).mean())
        row[f"skill{k}"] = 1 - float(((a[:, 0] - a[:, 1]) ** 2).mean()) / ref if ref > 0 else float("nan")
    return row


def main():
    print("| Tail shape | Posts of history | 80% range held | P(2x): forecast / observed | "
          "P(3x): forecast / observed | P(10x): forecast / observed | Brier skill, 2x |")
    print("|---|---|---|---|---|---|---|")
    for shape in SHAPES:
        for n_hist in (8, 30, 80):
            r = run(shape, n_hist, 0.5)
            print(f"| {shape} | {n_hist} | {100 * r['cover']:.1f}% | {100 * r['f2']:.1f}% / {100 * r['o2']:.1f}% | "
                  f"{100 * r['f3']:.1f}% / {100 * r['o3']:.1f}% | {100 * r['f10']:.1f}% / {100 * r['o10']:.1f}% | "
                  f"{r['skill2']:+.2f} |")
    r = run("skewed", 30, 0.0)
    print(f"\nA judge with no signal (skewed, 30 posts): 80% range held {100 * r['cover']:.1f}%, "
          f"P(2x) {100 * r['f2']:.1f}% forecast vs {100 * r['o2']:.1f}% observed, Brier skill {r['skill2']:+.3f}")


if __name__ == "__main__":
    main()
