#!/usr/bin/env python3
"""
vforecast.py - calibrated forecasting toolkit for short-form video performance.

The judge (a person or a language model following references/rubric.md) produces
structured sub-scores. This script does everything that should NOT be left to
judgment: baselines, regression to the mean, probabilities, ranges, logging,
scoring and recalibration.

Subcommands
  profile            build the account baseline from a history CSV or a list of view counts
  status             show what the data folder contains and how calibrated it is
  forecast           judge file(s) + baseline + calibration -> probabilities and ranges
  library-add        add a published video with a known result, to serve as an anchor
  anchors            print past videos with known outcomes to place a new video against
  rank               rank variants from pairwise judgments (Bradley-Terry, then calibrated)
  snapshot           log early post-publish metrics
  nowcast            update the forecast from early metrics
  resolve            record a final outcome
  scoreboard         score past forecasts against outcomes and recalibrate
  backtest-prepare   build a blind queue from history videos
  backtest-score     score blind judgments against real outcomes (+ head-to-head, stacking)
  export / import    move the data folder between sessions
  selftest           synthetic simulation that checks the statistics behave as claimed

Run any subcommand with -h for its options. Method notes: references/methodology.md
"""
import argparse
import builtins
import csv
import datetime as dt
import json
import math
import os
import random
import re
import statistics
import sys
import zipfile
from pathlib import Path

try:
    import numpy as np
except ImportError:                                    # pragma: no cover
    sys.exit("vforecast needs numpy:  pip install numpy")

VERSION = "0.1.0"
ND = statistics.NormalDist()

# ----------------------------------------------------------------------------- configuration
SUBSCORES = ["stop_power", "hold", "share_save", "comment_trigger", "rewatch_loop", "audience_fit"]
CONTEXT_KEYS = ["topic_momentum", "related_activity", "freshness"]
SCRIPT_ONLY_FACTOR = 0.6        # reliability multiplier when the judge saw a script or storyboard, not the video
# The 1-7 judging scale is defined in percentile terms (see references/rubric.md):
# 1 = bottom 2%, 2 = bottom 10%, 3 = 30th pct, 4 = median, 5 = 70th, 6 = top 10%, 7 = top 2%.
SCALE_Z = {1: -2.05, 2: -1.28, 3: -0.52, 4: 0.0, 5: 0.52, 6: 1.28, 7: 2.05}
ITEM_CORRELATION = 0.5          # assumed average correlation between sub-scores (for the composite's spread)
CONTEXT_UNIT = 1.28 / 6.0       # three context dimensions at +2 each == a top-10% tailwind
PRIOR_N = 20                    # the reliability prior counts like this many resolved forecasts
MIN_LIBRARY = 12                # judged videos needed before the composite is standardised empirically
GENERAL_SCALE = "the general scale"
REACH = {"stop_power": .25, "hold": .25, "share_save": .20, "rewatch_loop": .10,
         "comment_trigger": .10, "audience_fit": .10}
# kind: count -> log10(v+1); ratio -> log10(v); rate01 -> logit(v).  r0 = prior reliability of the judge.
TARGETS = {
    "views":           dict(kind="count", weights=REACH, context_gain=0.5, r0=0.25, unit="views"),
    "likes":           dict(kind="count", weights=REACH, context_gain=0.5, r0=0.25, unit="likes"),
    "shares":          dict(kind="count", context_gain=0.5, r0=0.25, unit="shares",
                            weights={"share_save": .5, "hold": .15, "stop_power": .15, "audience_fit": .1, "rewatch_loop": .1}),
    "comments":        dict(kind="count", context_gain=0.5, r0=0.25, unit="comments",
                            weights={"comment_trigger": .5, "hold": .15, "stop_power": .15, "audience_fit": .2}),
    "saves":           dict(kind="count", context_gain=0.25, r0=0.25, unit="saves",
                            weights={"share_save": .6, "hold": .2, "audience_fit": .2}),
    "share_rate":      dict(kind="ratio", context_gain=0.25, r0=0.25, unit="shares per view",
                            weights={"share_save": .7, "audience_fit": .15, "hold": .15}),
    "engagement_rate": dict(kind="ratio", context_gain=0.25, r0=0.25, unit="engagements per view",
                            weights={"share_save": .3, "comment_trigger": .3, "hold": .2, "audience_fit": .2}),
    "hook_rate":       dict(kind="rate01", context_gain=0.0, r0=0.35, unit="share of viewers who stay past the hook",
                            weights={"stop_power": .75, "audience_fit": .25}),
    "completion_rate": dict(kind="rate01", context_gain=0.0, r0=0.35, unit="completion rate",
                            weights={"hold": .6, "rewatch_loop": .15, "stop_power": .1, "audience_fit": .15}),
    "avg_watch_pct":   dict(kind="ratio", context_gain=0.0, r0=0.35, unit="average watch time / duration",
                            weights={"hold": .6, "rewatch_loop": .2, "stop_power": .1, "audience_fit": .1}),
}
SIGMA_FLOOR = {"count": (0.15, 0.25), "ratio": (0.15, 0.25), "rate01": (0.25, 0.40)}   # (n>=15, thinner history)
CANON = ["video_id", "posted_at", "platform", "duration_s", "views", "likes", "comments", "shares", "saves",
         "avg_watch_s", "completion_rate", "hook_rate", "caption", "video_path", "source"]
ALIASES = {
    "video_id": ["video_id", "id", "video id", "post id", "post_id"],
    "posted_at": ["posted_at", "date", "posted", "post time", "publish time", "published", "created",
                  "create time", "time", "post date", "publish date", "date posted"],
    "platform": ["platform"],
    "duration_s": ["duration_s", "duration", "video duration", "length", "duration (s)", "video length"],
    "views": ["views", "video views", "plays", "play count", "view count", "video plays"],
    "likes": ["likes", "like count", "hearts"],
    "comments": ["comments", "comment count"],
    "shares": ["shares", "share count", "sends"],
    "saves": ["saves", "bookmarks", "favorites", "favourites", "save count"],
    "avg_watch_s": ["avg_watch_s", "average watch time", "avg watch time", "average view duration"],
    "completion_rate": ["completion_rate", "completion rate", "watched full video", "watched full video (%)",
                        "full video watched", "full watch rate"],
    "hook_rate": ["hook_rate", "hook rate", "3s view rate", "3-second view rate", "stayed to watch",
                  "viewed vs swiped away", "thumbstop rate", "thumb-stop rate"],
    "caption": ["caption", "title", "description", "video title", "post caption"],
    "video_path": ["video_path", "file", "path", "video file", "filename"],
}
DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y", "%B %d, %Y"]
MARGIN_SHARE = {0: 0.5, 1: 0.62, 2: 0.75, 3: 0.88}     # how decisively a pairwise comparison was won


def print(*args, **kwargs):                              # noqa: A001
    """print that survives a closed pipe (output sent to `head`), so a command still finishes its file writes."""
    try:
        builtins.print(*args, **kwargs)
    except BrokenPipeError:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass


# ----------------------------------------------------------------------------- small maths
def phi(z):
    return ND.cdf(z)


def phinv(p):
    return ND.inv_cdf(min(max(p, 1e-6), 1 - 1e-6))


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def logit(p):
    p = clip(p, 1e-4, 1 - 1e-4)
    return math.log(p / (1 - p))


def expit(x):
    return 1.0 / (1.0 + math.exp(-x))


def to_latent(v, kind):
    """Scale on which 'relative to baseline' is an additive difference."""
    if kind == "count":
        return math.log10(max(v, 0.0) + 1.0)
    if kind == "ratio":
        return math.log10(max(v, 1e-9))
    return logit(v)


def from_latent(x, kind):
    if kind == "count":
        return max(10 ** x - 1.0, 0.0)
    if kind == "ratio":
        return 10 ** x
    return expit(x)


def rankdata(a):
    a = np.asarray(a, float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), float)
    ranks[order] = np.arange(1, len(a) + 1)
    sa = a[order]
    i = 0
    while i < len(sa):
        j = i
        while j + 1 < len(sa) and sa[j + 1] == sa[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(((x - x.mean()) * (y - y.mean())).mean() / (x.std() * y.std()))


def spearman(x, y):
    return pearson(rankdata(x), rankdata(y))


def bootstrap_ci(x, y, stat=spearman, b=2000, seed=12345):
    x, y = np.asarray(x, float), np.asarray(y, float)
    rng = np.random.default_rng(seed)
    n, vals = len(x), []
    for _ in range(b):
        idx = rng.integers(0, n, n)
        v = stat(x[idx], y[idx])
        if not math.isnan(v):
            vals.append(v)
    if len(vals) < b * 0.5:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def pairwise_accuracy(signal, outcome):
    good = total = 0
    n = len(signal)
    for i in range(n):
        for j in range(i + 1, n):
            ds, do = signal[i] - signal[j], outcome[i] - outcome[j]
            if ds == 0 or do == 0:
                continue
            total += 1
            good += (ds > 0) == (do > 0)
    return good / total if total else float("nan")


def normal_scores(values):
    r = rankdata(values)
    return np.array([phinv((ri - 0.5) / len(r)) for ri in r])


def t_ppf(p, df):
    """Student-t quantile (Cornish-Fisher expansion; accurate to ~1% for df >= 4)."""
    z = phinv(p)
    if df > 200:
        return z
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    g4 = (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / 92160
    return z + g1 / df + g2 / df ** 2 + g3 / df ** 3 + g4 / df ** 4


def t_cdf(x, df):
    lo, hi = 1e-6, 1 - 1e-6
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if t_ppf(mid, df) < x:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def score_to_z(score):
    s = clip(float(score), 1.0, 7.0)
    lo = int(math.floor(s))
    hi = min(lo + 1, 7)
    return SCALE_Z[lo] + (SCALE_Z[hi] - SCALE_Z[lo]) * (s - lo)


def fmt_num(v, kind="count"):
    if v is None:
        return "n/a"
    if kind in ("rate01", "ratio"):
        return f"{100 * v:.2f}%" if v < 0.1 else f"{100 * v:.1f}%"
    if v >= 1e6:
        return f"{v / 1e6:.2f}M"
    if v >= 1e4:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.0f}"


def fmt_est(v, kind="count"):
    """Forecast quantities are estimates: two significant figures are all they can carry."""
    if v is None or kind != "count":
        return fmt_num(v, kind)
    if v < 100:
        return f"{v:.0f}"
    r = round(v, 1 - int(math.floor(math.log10(v))))
    return f"{r / 1e6:.1f}M" if r >= 1e6 else f"{r:,.0f}"


def ordinal(p):
    n = int(round(100 * p))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def pct(p):
    return f"{100 * p:.0f}%" if 0.005 <= p <= 0.995 else (f"{100 * p:.1f}%")


# ----------------------------------------------------------------------------- io helpers
def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def data_dir(args, create=True):
    d = Path(getattr(args, "data", None) or "virality-data").expanduser()
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, entries):
    Path(path).write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")


def read_csv(path):
    text = Path(path).expanduser().read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    rows = [dict(r) for r in reader]
    return rows, list(reader.fieldnames or [])


def save_history(path, rows):
    extras = []
    for r in rows:
        for k in r:
            if k not in CANON and k not in extras and k is not None:
                extras.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CANON + extras, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CANON + extras})


def parse_num(s, rate=False):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        v = float(s)
    else:
        t = str(s).strip().replace(",", "").replace(" ", "")
        if t.lower() in ("", "-", "nan", "none", "null", "n/a", "na"):
            return None
        is_pct = t.endswith("%")
        if is_pct:
            t = t[:-1]
        mult = 1.0
        if t and t[-1].lower() in "kmb":
            mult = {"k": 1e3, "m": 1e6, "b": 1e9}[t[-1].lower()]
            t = t[:-1]
        try:
            v = float(t) * mult
        except ValueError:
            return None
        if is_pct:
            v /= 100.0
    if math.isnan(v):
        return None
    if rate and v > 1.0:            # "45" meaning 45%
        v /= 100.0
    return v


def parse_duration(s):
    if s is None:
        return None
    t = str(s).strip().lower()
    if ":" in t:
        try:
            parts = [float(p) for p in t.split(":")]
        except ValueError:
            return None
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
    return parse_num(t.rstrip("s"))


def detect_date_parser(values, fmt=None):
    """Return (parser, warning). Tries ISO first, then common spreadsheet formats."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return None, None
    if fmt:
        return (lambda v: dt.datetime.strptime(v.strip(), fmt)), None

    def iso(v):
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)

    passing = []
    for name, parser in [("ISO", iso)] + [(f, (lambda v, f=f: dt.datetime.strptime(v, f))) for f in DATE_FORMATS]:
        ok = 0
        for v in vals:
            try:
                parser(v)
                ok += 1
            except (ValueError, TypeError):
                pass
        if ok >= 0.95 * len(vals):
            passing.append((name, parser))
    if not passing:
        return None, None
    warning = None
    for name, parser in passing[1:]:
        differs = False
        for v in vals[:200]:
            try:
                if parser(v) != passing[0][1](v):
                    differs = True
                    break
            except (ValueError, TypeError):
                continue
        if differs:
            warning = (f"dates fit more than one format ({passing[0][0]} and {name}); read as {passing[0][0]}. "
                       "If that is wrong, pass --date-format.")
            break
    return passing[0][1], warning


def normalize_history(raw_rows, headers, overrides, order, date_format=None):
    lower = {h.strip().lower(): h for h in headers if h}
    mapping = {}
    for canon, names in ALIASES.items():
        if canon in overrides:
            if overrides[canon] not in headers:
                sys.exit(f"--map {canon}={overrides[canon]}: no such column. Columns: {headers}")
            mapping[canon] = overrides[canon]
            continue
        for name in names:
            if name in lower:
                mapping[canon] = lower[name]
                break
    used = set(mapping.values())
    rows = []
    for raw in raw_rows:
        row = {canon: (raw.get(src) or "").strip() for canon, src in mapping.items()}
        for h in headers:
            if h and h not in used and h not in CANON:
                row[h] = raw.get(h, "")
        rows.append(row)
    info = {"mapped": mapping, "ordering": None, "warning": None}
    parser = None
    if "posted_at" in mapping:
        parser, info["warning"] = detect_date_parser([r.get("posted_at", "") for r in rows], date_format)
    if parser:
        dated, undated = [], []
        for r in rows:
            try:
                d = parser(r["posted_at"].strip())
                r["posted_at"] = d.isoformat(sep=" ")
                dated.append((d, r))
            except (ValueError, TypeError, AttributeError):
                undated.append(r)
        dated.sort(key=lambda x: x[0])
        rows = undated + [r for _, r in dated]
        info["ordering"] = "by posted_at"
        if dated:
            info["ordering"] += f", {dated[0][0]:%Y-%m-%d} to {dated[-1][0]:%Y-%m-%d}"
        if undated:
            info["ordering"] += f" ({len(undated)} undated rows placed first)"
    else:
        if order != "oldest-first":
            rows.reverse()
        info["ordering"] = f"file order assumed {order or 'newest-first'} (no usable date column)"
    for i, r in enumerate(rows):
        if not r.get("video_id"):
            r["video_id"] = f"h{i + 1:04d}"
        r.setdefault("source", "import")
    return rows, info


def parse_posted(text):
    try:
        return dt.datetime.fromisoformat(str(text).strip()).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def mature_rows(rows, min_age_days=7.0):
    """Posts still collecting views would drag the baseline down, so they wait outside the profile."""
    if not min_age_days:
        return list(rows)
    now, out = dt.datetime.now(), []
    for r in rows:
        d = parse_posted(r.get("posted_at")) if r.get("posted_at") else None
        if r.get("source") != "resolve" and d is not None and (now - d).total_seconds() < min_age_days * 86400:
            continue
        out.append(r)
    return out


def merge_resolved(hist_path, rows):
    """Keep outcomes recorded with `resolve` when the history is re-imported."""
    if not Path(hist_path).exists():
        return rows, 0
    ids = {r["video_id"] for r in rows}
    old, _ = read_csv(hist_path)
    keep = [r for r in old if r.get("source") == "resolve" and r.get("video_id") not in ids]
    return rows + keep, len(keep)


def get_target(row, target):
    kind = TARGETS[target]["kind"]

    def g(key, rate=False):
        return parse_num(row.get(key), rate)

    if target == "share_rate":
        s, v = g("shares"), g("views")
        return s / v if (s is not None and v) else None
    if target == "engagement_rate":
        v = g("views")
        parts = [g(k) for k in ("likes", "comments", "shares", "saves")]
        if not v or all(p is None for p in parts):
            return None
        return sum(p or 0 for p in parts) / v
    if target == "avg_watch_pct":
        a, d = parse_duration(row.get("avg_watch_s")), parse_duration(row.get("duration_s"))
        return a / d if (a is not None and d) else None
    return g(target, rate=(kind == "rate01"))


def rolling_rp(latents, window=10):
    """Relative performance of each post vs the median of the `window` posts before it.

    Early posts do not have a full window behind them, so they borrow the posts right after
    them to fill it. Every baseline then rests on the same number of posts, which keeps the
    spread of early posts comparable with the spread a new post will be measured against.
    """
    n = len(latents)
    base, rp = [None] * n, [None] * n
    valid = [i for i, x in enumerate(latents) if x is not None]
    for pos, i in enumerate(valid):
        prev = valid[max(0, pos - window):pos]
        pool = prev + valid[pos + 1:pos + 1 + window - len(prev)]
        if len(pool) < 2:
            continue
        b = statistics.median([latents[j] for j in pool])
        base[i], rp[i] = b, latents[i] - b
    return base, rp


def history_rp(rows, target, window):
    kind = TARGETS[target]["kind"]
    vals = [get_target(r, target) for r in rows]
    lat = [None if v is None or (kind != "count" and v <= 0) else to_latent(v, kind) for v in vals]
    base, rp = rolling_rp(lat, window)
    return vals, lat, base, rp


def build_profile(rows, window=10, platform=None, min_age_days=7.0):
    use = mature_rows(rows, min_age_days)
    prof = {"version": VERSION, "created_at": now_iso(), "n_posts": len(use), "n_waiting": len(rows) - len(use),
            "window": window, "min_age_days": min_age_days, "platform": platform, "targets": {}}
    for target, cfg in TARGETS.items():
        vals, lat, _, rp = history_rp(use, target, window)
        good = [x for x in lat if x is not None]
        rps = sorted(x for x in rp if x is not None)
        if len(good) < 3 or len(rps) < 3:
            continue
        base_now = statistics.median(good[-window:])
        prof["targets"][target] = {
            "kind": cfg["kind"], "n": len(good), "baseline_latent": base_now,
            "baseline": from_latent(base_now, cfg["kind"]), "rp_sorted": [round(x, 5) for x in rps],
            "median_latent_all": statistics.median(good),
        }
    return prof


def card_outcomes(rows, video_id, window):
    """Known results of one history video, as relative performance per target."""
    idx = next((i for i, r in enumerate(rows) if r.get("video_id") == video_id), None)
    out = {}
    if idx is None:
        return out
    for target in TARGETS:
        vals, _, _, rp = history_rp(rows, target, window)
        if rp[idx] is not None:
            out[target] = {"value": vals[idx], "rp": rp[idx]}
    return out


def write_card(data, video_id, judge, subscores, blind=None, outcome=None):
    """One judged video in the account's library: what was seen, how it scored, how it did."""
    path = Path(data) / "library" / video_id / "card.json"
    old = read_json(path, {}) or {}
    card = {"video_id": video_id, "created_at": now_iso(), "platform": judge.get("platform"),
            "audience": judge.get("audience"), "description": judge.get("description"),
            "hook_summary": judge.get("hook_summary"), "subscores": subscores,
            "flags": judge.get("flags") or [], "context": judge.get("context"),
            "blind": old.get("blind") if blind is None else blind,
            "outcome": outcome if outcome is not None else old.get("outcome", {})}
    write_json(path, card)
    return path


class Marginal:
    """The account's own distribution of relative performance, as a quantile function on a z scale.

    Empirical in the middle, using plotting positions i/(n+1) so that the chance a new post lands
    below the i-th smallest past post is exactly i/(n+1). Blended toward a two-piece normal when
    history is thin, and extended beyond the best and worst posts ever observed with separate
    slopes for the upper and lower tail, because view counts are skewed.
    """

    BLEND = 8.0                                     # thin histories lean on a two-piece normal

    def __init__(self, rp_sorted, kind):
        xs = sorted(float(x) for x in rp_sorted)
        self.n = n = len(xs)
        floor = SIGMA_FLOOR[kind][0 if n >= 15 else 1]
        med = statistics.median(xs) if xs else 0.0
        sigma = floor
        if n >= 2:
            sigma = max(1.4826 * statistics.median([abs(x - med) for x in xs]), floor)
        self.median, self.sigma = med, sigma
        self.sigma_hi = self._side([x - med for x in xs if x > med], sigma, floor)
        self.sigma_lo = self._side([med - x for x in xs if x < med], sigma, floor)
        self.zs = [phinv((i + 1.0) / (n + 1.0)) for i in range(n)]
        w = n / (n + self.BLEND)
        self.xs = [w * x + (1 - w) * (med + (self.sigma_hi if z > 0 else self.sigma_lo) * z) + 1e-9 * i
                   for i, (x, z) in enumerate(zip(xs, self.zs))]

    @staticmethod
    def _side(devs, sigma, floor):
        """Spread of one half of the distribution, shrunk toward the overall spread when that half is thin."""
        if not devs:
            return sigma
        devs = sorted(devs)
        k = len(devs)
        s = 1.4826 * statistics.median(devs)
        if k >= 5:                                  # the 80th percentile of one half is the 90th overall
            s = 0.5 * (s + devs[min(k - 1, int(round(0.8 * (k + 1))) - 1)] / 1.2816)
        return max((k * s + 4.0 * sigma) / (k + 4.0), floor)

    def q(self, z):
        if self.n == 0:
            return z * self.sigma
        if z <= self.zs[0]:
            return self.xs[0] + (z - self.zs[0]) * self.sigma_lo
        if z >= self.zs[-1]:
            return self.xs[-1] + (z - self.zs[-1]) * self.sigma_hi
        return float(np.interp(z, self.zs, self.xs))

    def z(self, x):
        if self.n == 0:
            return x / self.sigma
        if x <= self.xs[0]:
            return self.zs[0] + (x - self.xs[0]) / self.sigma_lo
        if x >= self.xs[-1]:
            return self.zs[-1] + (x - self.xs[-1]) / self.sigma_hi
        return float(np.interp(x, self.xs, self.zs))


# ----------------------------------------------------------------------------- the judge signal
def composite_raw(subscores, weights):
    """Weighted mean of sub-score z values, plus the factor that rescales it to unit spread."""
    present = {k: w for k, w in weights.items() if subscores.get(k) is not None}
    if not present:
        raise ValueError(f"judge file has none of the sub-scores this target needs: {list(weights)}")
    total = sum(present.values())
    raw = sum(w * score_to_z(subscores[k]) for k, w in present.items()) / total
    k_eff = 1.0 / sum((w / total) ** 2 for w in present.values())
    factor = math.sqrt((1 + (k_eff - 1) * ITEM_CORRELATION) / k_eff)
    return raw, factor


def library_composites(data, target, exclude=None):
    out = []
    lib = Path(data) / "library"
    if not lib.exists():
        return out
    for card_path in lib.glob("*/card.json"):
        card = read_json(card_path, {})
        if card.get("video_id") == exclude or not card.get("subscores"):
            continue
        try:
            out.append(composite_raw(card["subscores"], TARGETS[target]["weights"])[0])
        except ValueError:
            continue
    return out


def judge_signal(judges, target, data=None, use_context=True, use_anchor=True, video_id=None):
    """Mechanical combination of one or more judge files into a single z signal."""
    cfg = TARGETS[target]
    sub = {}
    for k in SUBSCORES:
        vals = [float(j["subscores"][k]) for j in judges if j.get("subscores", {}).get(k) is not None]
        if vals:
            sub[k] = sum(vals) / len(vals)
    spreads = []
    if len(judges) > 1:
        for k in SUBSCORES:
            vals = [float(j["subscores"][k]) for j in judges if j.get("subscores", {}).get(k) is not None]
            if len(vals) > 1:
                spreads.append(statistics.pstdev(vals))
    raw, factor = composite_raw(sub, cfg["weights"])
    standardization = GENERAL_SCALE
    content_z = raw / factor
    if data is not None:
        lib = library_composites(data, target, exclude=video_id)
        if len(lib) >= MIN_LIBRARY:
            below = sum(1 for x in lib if x < raw)
            ties = sum(1 for x in lib if x == raw)
            content_z = phinv((below + 0.5 * ties + 0.5) / (len(lib) + 1))
            standardization = f"this account's library of {len(lib)} judged videos"
    anchor_z = None
    if use_anchor:
        ps = [float(j["anchor_percentile"]) for j in judges if j.get("anchor_percentile") is not None]
        if ps:
            p = sum(ps) / len(ps)
            p = p / 100.0 if p > 1 else p
            anchor_z = phinv(clip(p, 0.02, 0.98))
            content_z = 0.5 * content_z + 0.5 * anchor_z
    context_z, context_checked = 0.0, False
    if use_context and cfg["context_gain"] > 0:
        sums = []
        for j in judges:
            c = j.get("context") or {}
            if c.get("checked") is False:
                continue
            if any(c.get(k) is not None for k in CONTEXT_KEYS):
                sums.append(sum(clip(float(c.get(k) or 0), -2, 2) for k in CONTEXT_KEYS))
        if sums:
            context_checked = True
            context_z = CONTEXT_UNIT * sum(sums) / len(sums)
    z = clip(content_z + cfg["context_gain"] * context_z, -2.5, 2.5)
    return {
        "z": round(z, 4), "content_z": round(content_z, 4), "composite_raw": round(raw, 4),
        "raw_z": round(clip(raw / factor, -2.5, 2.5), 4),
        "context_z": round(context_z, 4), "context_checked": context_checked,
        "anchor_z": None if anchor_z is None else round(anchor_z, 4),
        "judges": len(judges), "judge_spread": round(sum(spreads) / len(spreads), 3) if spreads else None,
        "standardization": standardization, "subscores": {k: round(v, 2) for k, v in sub.items()},
    }


# ----------------------------------------------------------------------------- calibration
def load_calibration(data):
    return read_json(Path(data) / "calibration.json", {"version": VERSION, "targets": {}}) if data else {"targets": {}}


def reliability(cal, target):
    """Prior reliability shrunk toward what backtests and resolved forecasts have shown (Fisher z)."""
    r0 = TARGETS[target]["r0"]
    num, den, parts, n_obs = PRIOR_N * math.atanh(r0), PRIOR_N, ["prior"], 0
    t = cal.get("targets", {}).get(target, {})
    for source in ("backtest", "live"):
        s = t.get(source)
        if s and s.get("n", 0) >= 5 and s.get("r") is not None and not math.isnan(s["r"]):
            num += s["n"] * math.atanh(clip(s["r"], -0.9, 0.9))
            den += s["n"]
            n_obs += s["n"]
            parts.append(f"{source} n={s['n']} (r={s['r']:.2f})")
    return clip(math.tanh(num / den), 0.0, 0.9), " + ".join(parts), n_obs


def make_forecast(z, r, marg, base_latent, kind, multiples=(2, 3, 10)):
    """Gaussian-copula forecast: the signal moves the outcome only as far as its reliability allows."""
    r = clip(r, 0.0, 0.95)
    mu, sd = r * z, math.sqrt(1 - r * r)

    def exceed(z_threshold):
        return 1 - phi((z_threshold - mu) / sd), 1 - phi(z_threshold)

    out = {"p": {}, "base": {}}
    out["p"]["above_baseline"], out["base"]["above_baseline"] = exceed(marg.z(0.0))
    out["p"]["top_quartile"], out["base"]["top_quartile"] = exceed(phinv(0.75))
    out["thresholds"] = {"top_quartile_rp": marg.q(phinv(0.75))}
    if kind != "rate01":
        for k in multiples:
            out["p"][f"x{k:g}"], out["base"][f"x{k:g}"] = exceed(marg.z(math.log10(k)))
    out["quantiles"] = {}
    for name, q in (("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90)):
        rp = marg.q(mu + sd * phinv(q))
        out["quantiles"][name] = from_latent(base_latent + rp, kind) if base_latent is not None else None
        out.setdefault("rp_quantiles", {})[name] = rp
    out["expected_percentile"] = phi(mu)
    return out


def confidence_label(n_hist, n_obs, r, signal, blind_spots):
    reasons, level = [], "medium"
    if n_obs < 15:
        level = "low"
        reasons.append(f"reliability is mostly a prior ({n_obs} scored forecasts on this account; 15+ needed)")
    if n_hist < 10:
        level = "low"
        reasons.append(f"thin history ({n_hist} posts); the baseline and ranges are rough")
    if signal.get("judge_spread") and signal["judge_spread"] > 0.8:
        level = "low"
        reasons.append("independent judges disagreed noticeably")
    if signal.get("standardization") == GENERAL_SCALE:
        reasons.append("no judged library yet: sub-scores are read against videos of this kind in general, "
                       "not against this account's usual output")
    if blind_spots:
        reasons.append("blind spots: " + "; ".join(blind_spots[:3]))
    if level == "medium" and n_obs >= 40 and r >= 0.4 and n_hist >= 30 and not blind_spots:
        level = "high"
        reasons.append(f"measured reliability r={r:.2f} on {n_obs} scored forecasts")
    return level, reasons


# ----------------------------------------------------------------------------- commands
def cmd_profile(args):
    data = data_dir(args)
    hist_path = data / "history.csv"
    old = read_json(data / "profile.json", {}) or {}
    window = args.window or old.get("window", 10)
    min_age = old.get("min_age_days", 7.0) if args.min_age_days is None else args.min_age_days
    platform = args.platform or old.get("platform")
    overrides = {}
    for item in args.map or []:
        if "=" not in item:
            sys.exit('--map expects canonical=Column Header, e.g. --map views="Video views"')
        k, v = item.split("=", 1)
        overrides[k.strip()] = v.strip()
    info, carried = None, 0
    if args.history:
        raw, headers = read_csv(args.history)
        if not raw:
            sys.exit(f"{args.history} has no data rows.")
        rows, info = normalize_history(raw, headers, overrides, args.order, args.date_format)
        if not args.drop_resolved:
            rows, carried = merge_resolved(hist_path, rows)
        save_history(hist_path, rows)
    elif args.views:
        vals = [parse_num(x) for x in re.split(r"[,\s;]+", args.views.strip()) if x]
        vals = [v for v in vals if v is not None]
        if len(vals) < 3:
            sys.exit("Give at least 3 view counts (10-30 is better), without thousands separators: 1200, 950, 15000")
        if args.order != "oldest-first":
            vals.reverse()
        rows = [{"video_id": f"v{i + 1:03d}", "views": f"{v:.0f}", "source": "list"} for i, v in enumerate(vals)]
        if not args.drop_resolved:
            rows, carried = merge_resolved(hist_path, rows)
        save_history(hist_path, rows)
        info = {"ordering": f"list assumed {args.order}", "mapped": {"views": "(list)"}, "warning": None}
    elif hist_path.exists():
        rows, _ = read_csv(hist_path)
    else:
        sys.exit('Give --history file.csv or --views "1200, 900, ..." (most recent first unless --order oldest-first).')
    prof = build_profile(rows, window, platform, min_age)
    write_json(data / "profile.json", prof)
    print(f"PROFILE  {prof['n_posts']} posts -> {data / 'profile.json'}")
    if info:
        print(f"  ordering: {info['ordering']}")
        if info.get("mapped"):
            print("  columns:  " + ", ".join(f"{k}<-{v}" for k, v in info["mapped"].items()))
        if info.get("warning"):
            print(f"  WARNING {info['warning']}")
        if "views" not in info.get("mapped", {}):
            print('  WARNING no views column was recognised; map it with --map views="<column header>"')
    if carried:
        print(f"  kept {carried} post(s) recorded earlier with `resolve` that this file does not contain by id "
              "(if it does contain them under other ids, re-run with --drop-resolved)")
    if prof["n_waiting"]:
        print(f"  {prof['n_waiting']} post(s) younger than {min_age:g} days are left out until their numbers settle")
    if not prof["targets"]:
        print("  No usable target yet: at least 3 posts with a numeric metric are needed.")
    for target, t in prof["targets"].items():
        m = Marginal(t["rp_sorted"], t["kind"])
        line = f"  {target:16s} n={t['n']:<4d} baseline now {fmt_num(t['baseline'], t['kind'])}"
        if t["kind"] != "rate01":
            line += f"  typical spread x/÷{10 ** m.sigma:.1f}"
        if t["kind"] == "count":
            line += "  base rates: " + ", ".join(f">={k}x {pct(1 - phi(m.z(math.log10(k))))}" for k in (2, 3, 10))
        print(line)
    if prof["n_posts"] < 10:
        print("  NOTE fewer than 10 posts: ranges will be wide and labelled low-confidence.")


def cmd_status(args):
    data = data_dir(args, create=False)
    if not data.exists():
        print(f"No data folder at {data}. Start with: vforecast.py profile --data {data} --views \"...\"")
        return
    prof = read_json(data / "profile.json")
    cal = load_calibration(data)
    preds = read_jsonl(data / "predictions.jsonl")
    print(f"STATUS  {data}")
    if prof:
        wait = f" (+{prof['n_waiting']} too recent to count)" if prof.get("n_waiting") else ""
        print(f"  history: {prof['n_posts']} posts{wait}; platform: {prof.get('platform') or 'not set'}; "
              f"baselines for: {', '.join(prof['targets']) or 'none'}")
    else:
        print("  history: none yet (run `profile`)")
    pre = [p for p in preds if p.get("kind_of_forecast") == "prepost"]
    open_ids = sorted({p["video_id"] for p in pre if not p.get("resolved")})
    done_ids = {p["video_id"] for p in pre if p.get("resolved")}
    print(f"  forecasts: {len(done_ids)} video(s) resolved, {len(open_ids)} open")
    if open_ids:
        print("  open: " + ", ".join(open_ids[:12]) + (" ..." if len(open_ids) > 12 else ""))
    lib = data / "library"
    cards = [read_json(c, {}) for c in lib.glob("*/card.json")] if lib.exists() else []
    known = sum(1 for c in cards if c.get("outcome"))
    print(f"  library: {len(cards)} judged video(s), {known} with a known outcome "
          f"(anchors need 4+, scoring on this account's own scale needs {MIN_LIBRARY}+)")
    snaps = read_csv(data / "snapshots.csv")[0] if (data / "snapshots.csv").exists() else []
    print(f"  early-metric snapshots: {len(snaps)}")
    groups = {}
    for target in (prof["targets"] if prof and prof["targets"] else ["views"]):
        r, src, _ = reliability(cal, target)
        groups.setdefault((f"{r:.2f}", src), []).append(target)
    for (r, src), names in groups.items():
        print(f"  reliability r={r} ({src}): {', '.join(names)}")
    if cal.get("stack"):
        st = cal["stack"]
        print(f"  stacked signal: {st['signals']} (leave-one-out r={st['r_loo']:.2f}, n={st['n']})")


def load_judges(paths):
    judges = []
    for p in paths:
        j = read_json(p)
        if j is None:
            sys.exit(f"Judge file not found: {p}")
        if "subscores" not in j:
            sys.exit(f"{p}: missing 'subscores' (see references/data-formats.md)")
        judges.append(j)
    return judges


def parse_sets(items):
    out = {}
    for item in items or []:
        k, _, v = item.partition("=")
        k = k.strip()
        if k not in SUBSCORES + CONTEXT_KEYS:
            sys.exit(f"--set {k}: unknown key. Use one of {SUBSCORES + CONTEXT_KEYS}")
        val = parse_num(v)
        if val is None:
            sys.exit(f"--set {item}: the value must be a number")
        out[k] = val
    return out


def apply_sets(judges, sets):
    """What-if: the same judgment with some scores overridden."""
    alt = json.loads(json.dumps(judges))
    for j in alt:
        for k, v in sets.items():
            if k in SUBSCORES:
                j.setdefault("subscores", {})[k] = v
            else:
                ctx = j.get("context") or {}
                ctx[k] = v
                ctx["checked"] = True
                j["context"] = ctx
    return alt


def stacked_signal(stack, raw_z, externals):
    """Blend the judge with other predictors using the weights fitted by backtest-score --stack."""
    if not all(name == "judge" or externals.get(name) is not None for name in stack["signals"]):
        return None
    comps = []
    for name in stack["signals"]:
        dist = stack["dists"][name]
        v = raw_z if name == "judge" else externals[name]
        below = sum(1 for x in dist if x < v) + 0.5 * sum(1 for x in dist if x == v)
        comps.append(phinv((below + 0.5) / (len(dist) + 1)))
    return float(np.dot(stack["coef"], comps))


def forecast_one(data, target, judges, alt_judges, video_id, prof, cal, externals, multiples, sets,
                 prev_reasons=None):
    cfg = TARGETS[target]
    kind = cfg["kind"]
    try:
        signal = judge_signal(judges, target, data=data, video_id=video_id)
        alt = judge_signal(alt_judges, target, data=data, video_id=video_id) if alt_judges else None
    except ValueError as exc:
        print(f"FORECAST  {target}: skipped ({exc})")
        return None
    r, r_source, n_obs = reliability(cal, target)
    stack = cal.get("stack") if (cal.get("stack") or {}).get("target") == target else None

    def final_z(sig):
        if stack:
            st = stacked_signal(stack, sig["raw_z"], externals)
            if st is not None:
                return clip(st + cfg["context_gain"] * sig["context_z"], -2.5, 2.5), True
        return sig["z"], False

    z_used, used_stack = final_z(signal)
    notes = []
    if used_stack:
        num = PRIOR_N * math.atanh(cfg["r0"]) + stack["n"] * math.atanh(clip(stack["r_loo"], -0.9, 0.9))
        r = clip(math.tanh(num / (PRIOR_N + stack["n"])), 0.0, 0.9)
        r_source = f"prior + stacked {stack['signals']} (leave-one-out r={stack['r_loo']:.2f}, n={stack['n']})"
        n_obs = max(n_obs, stack["n"])
        notes.append(f"stacked signal from {stack['signals']}: z={z_used:+.2f}")
    elif externals:
        notes.append("an external score was given but no stack is fitted for this target, so it was not used "
                     "(fit one with backtest-score --stack)")
    input_kind = str(judges[0].get("input") or "video").lower()
    if input_kind != "video":
        r *= SCRIPT_ONLY_FACTOR
        r_source += f"; x{SCRIPT_ONLY_FACTOR:g} because the judge saw a {input_kind}, not the finished video"
    tprof = (prof or {}).get("targets", {}).get(target)
    blind = []
    for j in judges:
        blind += [b for b in (j.get("blind_spots") or []) if b not in blind]
    if cfg["context_gain"] > 0 and not signal["context_checked"]:
        blind.append("no trend check (context treated as neutral)")
    if tprof:
        marg, base_lat, n_hist = Marginal(tprof["rp_sorted"], kind), tprof["baseline_latent"], tprof["n"]
        mults = multiples if kind == "count" else []
    else:
        marg, base_lat, n_hist, mults = Marginal([], kind), None, 0, []
    fc = make_forecast(z_used, r, marg, base_lat, kind, mults)
    fc_alt = make_forecast(final_z(alt)[0], r, marg, base_lat, kind, mults) if alt else None
    level, reasons = confidence_label(n_hist, n_obs, r, signal, blind)
    entry = {
        "id": f"{video_id}:{target}:{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}",
        "kind_of_forecast": "prepost", "video_id": video_id, "target": target, "kind": kind,
        "created_at": now_iso(), "signal": signal, "z_used": round(z_used, 4), "r_used": round(r, 4),
        "r_source": r_source, "p": {k: round(v, 4) for k, v in fc["p"].items()},
        "base": {k: round(v, 4) for k, v in fc["base"].items()},
        "quantiles": fc["quantiles"], "thresholds": fc["thresholds"],
        "expected_percentile": round(fc["expected_percentile"], 4),
        "latent_baseline": base_lat, "baseline": tprof["baseline"] if tprof else None, "n_history": n_hist,
        "confidence": level, "confidence_reasons": reasons, "resolved": False,
    }
    if sets:
        entry["what_if"] = {"changes": sets, "p": {k: round(v, 4) for k, v in fc_alt["p"].items()},
                            "quantiles": fc_alt["quantiles"]}

    print(f"{'WHAT-IF ' if sets else 'FORECAST'}  {target}  video: {video_id}" + (f"  changes: {sets}" if sets else ""))
    ctx = f", context {signal['context_z']:+.2f}" if signal["context_checked"] else ", context not checked"
    anc = f", anchors {signal['anchor_z']:+.2f}" if signal["anchor_z"] is not None else ""
    print(f"  signal: content z={signal['content_z']:+.2f}{ctx}{anc} -> z={signal['z']:+.2f}  "
          f"(scored against {signal['standardization']}; {signal['judges']} judge{'s' if signal['judges'] > 1 else ''})")
    for note in notes:
        print(f"  {note}")
    print(f"  reliability used: r={r:.2f}  [{r_source}]")
    print(f"  after regression to the mean: expected near the {ordinal(fc['expected_percentile'])} percentile "
          "of this account's posts")
    print()
    labels = [("beats the current baseline", "above_baseline"), ("lands in this account's top quarter", "top_quartile")]
    labels += [(f"reaches {k:g}x the baseline or more", f"x{k:g}") for k in mults if f"x{k:g}" in fc["p"]]
    for label, key in labels:
        if sets:
            print(f"  P({label}) = {pct(fc['p'][key])} -> {pct(fc_alt['p'][key])} with the change"
                  f"   (base rate {pct(fc['base'][key])})")
        else:
            print(f"  P({label}) = {pct(fc['p'][key]):>5}   (base rate {pct(fc['base'][key])})")
    if tprof and sets:
        print(f"  likely median: {fmt_est(fc['quantiles']['p50'], kind)} -> {fmt_est(fc_alt['quantiles']['p50'], kind)} "
              f"{cfg['unit']} with the change  (baseline {fmt_num(tprof['baseline'], kind)})")
    elif tprof:
        q = fc["quantiles"]
        print(f"  likely range (80%): {fmt_est(q['p10'], kind)} to {fmt_est(q['p90'], kind)} {cfg['unit']}, "
              f"median {fmt_est(q['p50'], kind)}  (baseline {fmt_num(tprof['baseline'], kind)})")
    else:
        print(f"  no baseline for {target} yet, so no numbers or ranges: give the last 10-30 results with `profile`")
    if reasons == prev_reasons:
        print(f"\n  confidence: {level.upper()} (same reasons as above)")
    else:
        print(f"\n  confidence: {level.upper()}" + "".join(f"\n    - {x}" for x in reasons))
    return entry


def cmd_forecast(args):
    data = data_dir(args)
    judges = load_judges(args.judge)
    targets = [t.strip() for t in args.target.split(",") if t.strip()]
    for t in targets:
        if t not in TARGETS:
            sys.exit(f"Unknown target '{t}'. Choose from: {', '.join(TARGETS)}")
    sets = parse_sets(args.set)
    alt = apply_sets(judges, sets) if sets else None
    video_id = args.video_id or judges[0].get("video_id") or f"video-{dt.datetime.now():%Y%m%d-%H%M%S}"
    prof = read_json(data / "profile.json") or {}
    cal = load_calibration(data)
    externals = {}
    for item in args.external or []:
        name, _, val = item.partition("=")
        externals[name.strip()] = parse_num(val)
    multiples = [float(x) for x in str(args.multiples).split(",") if x.strip()]
    entries = []
    for i, target in enumerate(targets):
        if i:
            print()
        entry = forecast_one(data, target, judges, alt, video_id, prof, cal, externals, multiples, sets,
                             entries[-1]["confidence_reasons"] if entries else None)
        if entry:
            entries.append(entry)
    if not entries:
        sys.exit(1)
    if sets:
        print("\n  what-if only, nothing logged. The change in odds is the judge's estimate of the edit, "
              "not a measured effect.")
    elif not args.no_log:
        with open(data / "predictions.jsonl", "a", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        write_card(data, video_id, judges[0], entries[0]["signal"]["subscores"])
        print(f"\n  logged {len(entries)} forecast(s) -> {data / 'predictions.jsonl'}")
        print(f"  when the post has run its course: vforecast.py resolve --data {data} --video-id {video_id} --views N")
    if args.out:
        write_json(args.out, entries if len(entries) > 1 else entries[0])


def cmd_library_add(args):
    """Add an already-published video (judged now, result known) to the library, to serve as an anchor."""
    data = data_dir(args)
    judge = load_judges([args.judge])[0]
    video_id = args.video_id or judge.get("video_id")
    if not video_id:
        sys.exit("Give --video-id (or put video_id in the judge file).")
    prof = read_json(data / "profile.json", {}) or {}
    rows = read_csv(data / "history.csv")[0] if (data / "history.csv").exists() else []
    outcome = card_outcomes(mature_rows(rows, prof.get("min_age_days", 7.0)), video_id, prof.get("window", 10))
    if args.views is not None:
        tprof = prof.get("targets", {}).get("views")
        v = parse_num(args.views)
        if not tprof or v is None:
            sys.exit("--views needs a number and a views baseline (run `profile` first).")
        outcome["views"] = {"value": v, "rp": to_latent(v, "count") - tprof["median_latent_all"]}
    if not outcome:
        sys.exit(f"No known result for {video_id}: pass --views N, or use the video_id of a row in history.csv.")
    sub = {k: float(judge["subscores"][k]) for k in SUBSCORES if judge["subscores"].get(k) is not None}
    path = write_card(data, video_id, judge, sub, blind=False, outcome=outcome)
    shown = ", ".join(f"{t} {10 ** o['rp']:.2f}x" if TARGETS[t]["kind"] != "rate01" else f"{t} {o['value']:.3g}"
                      for t, o in outcome.items())
    print(f"LIBRARY  added {video_id} ({shown} vs baseline) -> {path}")
    print("  It can now serve as an anchor. Because its result was known when it was judged, it does not count "
          "toward measured reliability; only blind backtests and live forecasts do.")


def cmd_anchors(args):
    data = data_dir(args)
    target = args.target
    prof = read_json(data / "profile.json")
    tprof = (prof or {}).get("targets", {}).get(target)
    cards = []
    lib = data / "library"
    for card_path in (lib.glob("*/card.json") if lib.exists() else []):
        c = read_json(card_path, {})
        o = (c.get("outcome") or {}).get(target)
        if o and o.get("rp") is not None:
            cards.append((o["rp"], c, o))
    if len(cards) < 4 or not tprof:
        print(f"ANCHORS  not enough resolved library cards for {target} yet ({len(cards)}; need 4+). "
              "Skip anchors and leave anchor_percentile null.")
        return
    cards.sort(key=lambda x: x[0])
    k = min(args.k, len(cards))
    picks = [cards[round(i * (len(cards) - 1) / (k - 1))] for i in range(k)] if k > 1 else [cards[len(cards) // 2]]
    marg = Marginal(tprof["rp_sorted"], tprof["kind"])
    print(f"ANCHORS  {k} past videos with known {target}, weakest to strongest. Place the new video among them,")
    print("  then set anchor_percentile to the account percentile you would expect it to land at.\n")
    for i, (rp, c, o) in enumerate(picks, 1):
        mult = f"{10 ** rp:.2f}x baseline" if tprof["kind"] != "rate01" else fmt_num(o.get("value"), "rate01")
        print(f"  A{i}  {mult}  (about the {ordinal(phi(marg.z(rp)))} percentile of this account)   id: {c.get('video_id')}")
        if c.get("hook_summary"):
            print(f"      hook: {c['hook_summary']}")
        if c.get("description"):
            print(f"      {str(c['description'])[:320]}")
        print(f"      sub-scores: {c.get('subscores')}\n")


def bradley_terry(items, comparisons, iters=500):
    idx = {name: i for i, name in enumerate(items)}
    n = len(items)
    wins = np.full(n, 0.5)                      # one drawn game against a phantom average item (strength 1)
    games = np.zeros((n, n))
    for c in comparisons:
        a, b = idx[c["a"]], idx[c["b"]]
        margin = int(c.get("margin", 2))
        if c.get("winner") in (None, "tie", ""):
            sa = 0.5
        else:
            share = MARGIN_SHARE.get(clip(margin, 1, 3), 0.75)
            sa = share if c["winner"] == c["a"] else 1 - share
        wins[a] += sa
        wins[b] += 1 - sa
        games[a, b] += 1
        games[b, a] += 1
    p = np.ones(n)
    for _ in range(iters):
        new = np.empty(n)
        for i in range(n):
            denom = 1.0 / (p[i] + 1.0)          # phantom opponent of strength 1
            for j in range(n):
                if games[i, j]:
                    denom += games[i, j] / (p[i] + p[j])
            new[i] = wins[i] / denom
        if np.max(np.abs(new - p)) < 1e-10:
            p = new
            break
        p = new
    return p


def cmd_rank(args):
    spec = read_json(args.pairs)
    if not spec:
        sys.exit(f"Pairs file not found: {args.pairs}")
    items, comps = spec["items"], spec["comparisons"]
    for c in comps:
        if c["a"] not in items or c["b"] not in items:
            sys.exit(f"comparison refers to an unknown item: {c}")
    p = bradley_terry(items, comps)
    order = sorted(range(len(items)), key=lambda i: -p[i])
    cal = load_calibration(data_dir(args, create=False)) if args.data else {"targets": {}}
    r, r_source, _ = reliability(cal, args.target)
    seen, inconsistent = {}, 0
    for c in comps:
        key = tuple(sorted((c["a"], c["b"])))
        w = c.get("winner")
        if key in seen and w and seen[key] and seen[key] != w:
            inconsistent += 1
        seen.setdefault(key, w)

    def p_true(i, j):                           # judge preference -> probability the outcome agrees
        pj = clip(p[i] / (p[i] + p[j]), 0.02, 0.98)
        return phi(r * phinv(pj) / math.sqrt(1 - r * r))

    print(f"RANKING  ({len(comps)} comparisons, reliability r={r:.2f} [{r_source}])")
    for rank, i in enumerate(order, 1):
        print(f"  {rank}. {items[i]:24s} judge strength {p[i]:.2f}")
    if len(order) > 1:
        top, second = order[0], order[1]
        pj = p[top] / (p[top] + p[second])
        pt = p_true(top, second)
        shown = round(100 * pt)                  # the verdict follows the rounded figure that is printed
        verdict = "clear pick" if shown >= 65 else ("lean" if shown >= 55 else "toss-up")
        print(f"\n  {items[top]} over {items[second]}: judge preference {pct(pj)}, "
              f"calibrated chance it actually outperforms {shown}% -> {verdict}")
        if verdict == "lean":
            print("  Treat this as a lean, not a result. If both can be tested with real viewers, test both.")
        elif verdict == "toss-up":
            print("  Too close to call from judgment alone. If both can be tested with real viewers, test both.")
    if inconsistent:
        print(f"  NOTE {inconsistent} pair(s) flipped winner when the order was swapped: the judge is unsure there.")
    result = {"ranking": [items[i] for i in order], "strength": {items[i]: float(p[i]) for i in order},
              "r_used": r, "inconsistent_pairs": inconsistent}
    if len(order) > 1:
        result["p_top_beats_second"] = float(p_true(order[0], order[1]))
        result["verdict"] = verdict
    if args.out:
        write_json(args.out, result)


SNAP_FIELDS = ["video_id", "recorded_at", "age_min", "views", "likes", "comments", "shares", "saves",
               "completion_rate", "avg_watch_s"]


def cmd_snapshot(args):
    data = data_dir(args)
    path = data / "snapshots.csv"
    rows = read_csv(path)[0] if path.exists() else []
    rows.append({"video_id": args.video_id, "recorded_at": now_iso(), "age_min": args.age_min,
                 "views": args.views, "likes": args.likes, "comments": args.comments, "shares": args.shares,
                 "saves": args.saves, "completion_rate": args.completion_rate, "avg_watch_s": args.avg_watch_s})
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SNAP_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in SNAP_FIELDS})
    print(f"SNAPSHOT  {args.video_id} at {args.age_min:g} min: {args.views:g} views -> {path}")
    print("  Standard checkpoints make later nowcasts possible: 60, 180 and 1440 minutes, then the 7-day final.")


def fit_loglog(x, y):
    """log10(final) ~ a + b*log10(early). Slope fixed at 1 on thin data, shrunk toward 1 otherwise."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    sxx = float(((x - x.mean()) ** 2).sum())
    if n >= 10 and sxx > 1e-9:
        b = float(((x - x.mean()) * (y - y.mean())).sum() / sxx)
        w = n / (n + 6.0)
        b = w * b + (1 - w) * 1.0
        df = n - 2
    else:
        b, df = 1.0, n - 1
    a = float(y.mean() - b * x.mean())
    resid = y - (a + b * x)
    s = math.sqrt(float((resid ** 2).sum()) / max(df, 1))
    return {"a": a, "b": b, "s": max(s, 0.03), "df": max(df, 1), "n": n, "xbar": float(x.mean()), "sxx": sxx}


def loglog_predict(fit, x0):
    lever = (x0 - fit["xbar"]) ** 2 / fit["sxx"] if (fit["n"] >= 10 and fit["sxx"] > 1e-9) else 0.0
    return fit["a"] + fit["b"] * x0, fit["s"] * math.sqrt(1 + 1 / fit["n"] + lever)


def cmd_nowcast(args):
    data = data_dir(args)
    target = "views"
    snaps = read_csv(data / "snapshots.csv")[0] if (data / "snapshots.csv").exists() else []
    mine = [x for x in snaps if x["video_id"] == args.video_id and parse_num(x.get("views")) is not None]
    if not mine:
        sys.exit(f"No snapshot for {args.video_id}. Log one first: "
                 "vforecast.py snapshot --video-id ... --age-min ... --views ...")
    cur = max(mine, key=lambda x: parse_num(x["age_min"]) or 0)
    age, v = parse_num(cur["age_min"]), parse_num(cur["views"])
    prof = read_json(data / "profile.json") or {}
    rows = read_csv(data / "history.csv")[0] if (data / "history.csv").exists() else []
    done = [r for r in mature_rows(rows, prof.get("min_age_days", 7.0)) if r.get("video_id") != args.video_id]
    finals = {r["video_id"]: parse_num(r.get("views")) for r in done}
    comps = []
    for vid in {x["video_id"] for x in snaps} - {args.video_id}:
        final = finals.get(vid)
        if final is None:
            continue
        cands = [x for x in snaps if x["video_id"] == vid and parse_num(x.get("views")) is not None
                 and parse_num(x.get("age_min"))]
        cands = [x for x in cands if age / 1.6 <= parse_num(x["age_min"]) <= age * 1.6]
        if not cands:
            continue
        best = min(cands, key=lambda x: abs(math.log(parse_num(x["age_min"]) / age)))
        early = parse_num(best["views"])
        if final >= early:
            comps.append((early, final))
    tprof = prof.get("targets", {}).get(target)
    print(f"NOWCAST  {args.video_id}: {fmt_num(v)} views at {age:g} min")
    known = sorted(f for f in finals.values() if f is not None)
    ahead = sum(1 for f in known if f < v) / len(known) if len(known) >= 5 else 0
    if ahead > 0:
        print(f"  already above the final count of {pct(ahead)} of this account's finished posts")
    if tprof and v >= tprof["baseline"]:
        print(f"  it has passed the baseline ({fmt_num(tprof['baseline'])}): 'beats the baseline' is settled")
    if len(comps) >= 3:
        pace = v / statistics.median([c[0] for c in comps])
        print(f"  pace: {pace:.2f}x this account's usual views at this age (from {len(comps)} past videos)")
    if len(comps) < 5:
        print(f"  Not enough history to turn early views into a final number yet: {len(comps)} past video(s) have "
              f"both a snapshot near {age:g} min and a final count (5+ needed).")
        print("  Keep logging snapshots at 60 / 180 / 1440 min and resolving finals; this unlocks after 5 videos.")
        rate_readout(cur, done)
        return
    fit = fit_loglog([math.log10(c[0] + 1) for c in comps], [math.log10(c[1] + 1) for c in comps])
    m1, s1 = loglog_predict(fit, math.log10(v + 1))
    df = fit["df"]
    note = f"early-signal model: n={fit['n']}, slope {fit['b']:.2f}, typical miss x/÷{10 ** fit['s']:.2f}"
    m, sd = m1, s1
    preds = [p for p in read_jsonl(data / "predictions.jsonl")
             if p.get("video_id") == args.video_id and p.get("target") == target
             and p.get("kind_of_forecast") == "prepost" and (p.get("quantiles") or {}).get("p50")]
    if preds:
        q = preds[-1]["quantiles"]
        m0 = math.log10(q["p50"] + 1)
        s0 = max((math.log10(q["p90"] + 1) - math.log10(q["p10"] + 1)) / 2.563, 0.05)
        w0, w1 = 1 / s0 ** 2, 1 / s1 ** 2
        m, sd = (w0 * m0 + w1 * m1) / (w0 + w1), math.sqrt(1 / (w0 + w1))
        note += f"; blended with the pre-post forecast ({w0 / (w0 + w1):.0%} pre-post, {w1 / (w0 + w1):.0%} early signal)"
    quant = {name: max(10 ** (m + t_ppf(prob, df) * sd) - 1, v) for name, prob in (("p10", .1), ("p50", .5), ("p90", .9))}
    print(f"  final {target} (80% range): {fmt_est(quant['p10'])} to {fmt_est(quant['p90'])}, "
          f"median {fmt_est(quant['p50'])}")
    print(f"  [{note}]")
    entry = {"id": f"{args.video_id}:nowcast:{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}",
             "kind_of_forecast": "nowcast", "video_id": args.video_id, "target": target, "kind": "count",
             "created_at": now_iso(), "age_min": age, "views_at_age": v, "quantiles": quant, "resolved": False,
             "latent_baseline": tprof["baseline_latent"] if tprof else None, "n_comparables": len(comps)}
    if tprof:
        base = tprof["baseline"]
        entry["p"] = {}
        for k in [float(x) for x in str(args.multiples).split(",") if x.strip()]:
            pk = 1.0 if v >= k * base else 1 - t_cdf((math.log10(k * base + 1) - m) / sd, df)
            entry["p"][f"x{k:g}"] = pk
            print(f"  P(finishes at {k:g}x baseline or more, i.e. >= {fmt_num(k * base)}) = {pct(pk)}")
    with open(data / "predictions.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    rate_readout(cur, done)


def rate_readout(snapshot, rows):
    """Rates travel better across time than counts: compare them with the account's finished posts."""
    v = parse_num(snapshot.get("views"))
    checks = []
    comp = parse_num(snapshot.get("completion_rate"), rate=True)
    if comp is not None:
        checks.append(("completion rate", comp, [get_target(r, "completion_rate") for r in rows]))
    sh = parse_num(snapshot.get("shares"))
    if sh is not None and v:
        checks.append(("shares per view", sh / v, [get_target(r, "share_rate") for r in rows]))
    for name, value, hist in checks:
        hist = [h for h in hist if h is not None]
        if len(hist) >= 5:
            below = sum(1 for h in hist if h < value)
            print(f"  {name}: {value:.3g} -> higher than {pct(below / len(hist))} of this account's finished posts")
        else:
            print(f"  {name}: {value:.3g} (no history of this metric to compare with yet)")


def cmd_resolve(args):
    data = data_dir(args)
    hist_path = data / "history.csv"
    rows = read_csv(hist_path)[0] if hist_path.exists() else []
    row = next((r for r in rows if r.get("video_id") == args.video_id), None)
    if row is None:
        row = {"video_id": args.video_id}
        rows.append(row)
    for key in ("views", "likes", "comments", "shares", "saves", "avg_watch_s", "completion_rate", "hook_rate",
                "duration_s", "platform", "posted_at"):
        val = getattr(args, key)
        if val is not None:
            row[key] = val
    if all(get_target(row, t) is None for t in TARGETS):
        sys.exit("Give at least one final number, e.g. --views 12000")
    row["source"] = "resolve"                   # a resolved post is final, whatever its age
    save_history(hist_path, rows)
    old = read_json(data / "profile.json", {}) or {}
    window, min_age = old.get("window", 10), old.get("min_age_days", 7.0)
    write_json(data / "profile.json", build_profile(rows, window, old.get("platform"), min_age))
    preds = read_jsonl(data / "predictions.jsonl")
    scored = []
    for p in preds:
        if p.get("video_id") != args.video_id:
            continue
        val = get_target(row, p["target"])
        if val is None:
            continue
        actual = {"value": val, "resolved_at": now_iso()}
        q = p.get("quantiles") or {}
        if q.get("p10") is not None:
            actual["inside_80"] = bool(q["p10"] <= val <= q["p90"])
        if p.get("latent_baseline") is not None:
            rp = to_latent(val, p["kind"]) - p["latent_baseline"]
            actual["rp"] = rp
            actual["hits"] = {"above_baseline": rp > 0}
            if p.get("thresholds"):
                actual["hits"]["top_quartile"] = rp >= p["thresholds"]["top_quartile_rp"]
            for key in (p.get("p") or {}):
                if key.startswith("x"):
                    actual["hits"][key] = rp >= math.log10(float(key[1:]))
        p["actual"], p["resolved"] = actual, True
        scored.append(p)
    write_jsonl(data / "predictions.jsonl", preds)
    card_path = data / "library" / args.video_id / "card.json"
    card = read_json(card_path)
    if card is not None:
        card["outcome"] = card_outcomes(mature_rows(rows, min_age), args.video_id, window) or card.get("outcome", {})
        write_json(card_path, card)
    print(f"RESOLVED  {args.video_id}: recorded in history; {len(scored)} forecast(s) scored.")
    for p in scored:
        a = p["actual"]
        inside = {True: "inside", False: "outside", None: "n/a"}[a.get("inside_80")]
        line = f"  {p['kind_of_forecast']:8s} {p['target']}: actual {fmt_num(a['value'], p['kind'])}"
        if "rp" in a and p["kind"] != "rate01":
            line += f" = {10 ** a['rp']:.2f}x the baseline at forecast time"
        print(line + f"; the 80% range was {inside}")
    print(f"  Run `vforecast.py scoreboard --data {data}` to update accuracy and reliability.")


def score_block(z, rp, label):
    rho = spearman(z, rp)
    lo, hi = bootstrap_ci(z, rp)
    acc = pairwise_accuracy(z, rp)
    print(f"  {label}: rank correlation {rho:+.2f}  (95% CI {lo:+.2f} to {hi:+.2f}), "
          f"pairwise accuracy {pct(acc) if not math.isnan(acc) else 'n/a'}, n={len(z)}")
    return rho


def cmd_scoreboard(args):
    data = data_dir(args)
    preds = read_jsonl(data / "predictions.jsonl")
    cal = load_calibration(data)
    any_target = False
    for target in TARGETS:
        latest = {}
        for p in preds:
            if (p.get("kind_of_forecast") == "prepost" and p.get("target") == target and p.get("resolved")
                    and "rp" in p.get("actual", {})):
                latest[p["video_id"]] = p
        entries = list(latest.values())
        if not entries:
            continue
        any_target = True
        print(f"SCOREBOARD  {target}: {len(entries)} resolved pre-post forecasts")
        if len(entries) < 5:
            print("  Fewer than 5: too few to score. Keep resolving.")
            continue
        z = [p["z_used"] for p in entries]
        rp = [p["actual"]["rp"] for p in entries]
        rho = score_block(z, rp, "ranking skill")
        keys = {k for p in entries for k in p.get("p", {})}
        ordered = [k for k in ("above_baseline", "top_quartile") if k in keys]
        ordered += sorted((k for k in keys if k.startswith("x")), key=lambda k: float(k[1:]))
        names = {"above_baseline": "beats baseline", "top_quartile": "top quarter"}
        for key in ordered:
            pairs = [(p["p"][key], p["actual"]["hits"].get(key), p["base"][key]) for p in entries
                     if key in p.get("p", {}) and p["actual"].get("hits", {}).get(key) is not None]
            if len(pairs) < 5:
                continue
            happened = sum(float(b) for _, b, _ in pairs)
            line = (f"  P({names.get(key, '>=' + key[1:] + 'x')}): forecast avg "
                    f"{pct(sum(a for a, _, _ in pairs) / len(pairs))}, happened {pct(happened / len(pairs))}")
            if 0 < happened < len(pairs):
                brier = sum((a - float(b)) ** 2 for a, b, _ in pairs) / len(pairs)
                ref = sum((c - float(b)) ** 2 for _, b, c in pairs) / len(pairs)
                line += (f"; Brier {brier:.3f} vs {ref:.3f} for the base rate "
                         f"(skill {1 - brier / ref:+.2f}, above 0 beats quoting the base rate)")
            else:
                line += "; it never happened yet, so it cannot be scored" if happened == 0 else "; it always happened"
            print(line)
        cov = [p["actual"]["inside_80"] for p in entries if p["actual"].get("inside_80") is not None]
        if cov:
            print(f"  80% ranges contained the outcome {pct(sum(cov) / len(cov))} of the time (target 80%)")
        order = sorted(range(len(z)), key=lambda i: -z[i])
        third = max(1, len(z) // 3)
        top = statistics.median([rp[i] for i in order[:third]])
        rest = statistics.median([rp[i] for i in order[third:]]) if len(z) > third else float("nan")
        if entries[0]["kind"] != "rate01":
            print(f"  top third by forecast finished at a median {10 ** top:.2f}x baseline vs {10 ** rest:.2f}x for the rest")
        if not math.isnan(rho):
            cal.setdefault("targets", {}).setdefault(target, {})["live"] = {"r": round(rho, 4), "n": len(entries),
                                                                            "updated_at": now_iso()}
        r, src, _ = reliability(cal, target)
        print(f"  reliability now in use: r={r:.2f}  [{src}]")
        if len(entries) < 15:
            print(f"  NOTE n={len(entries)}: a first read only. The interval above is the honest summary.")
    now = [p for p in preds if p.get("kind_of_forecast") == "nowcast" and p.get("resolved")]
    if now:
        any_target = True
        cov = [p["actual"]["inside_80"] for p in now if p["actual"].get("inside_80") is not None]
        err = [abs(math.log10((p["actual"]["value"] + 1) / (p["quantiles"]["p50"] + 1))) for p in now]
        print(f"NOWCASTS  {len(now)} resolved: 80% ranges held {pct(sum(cov) / len(cov)) if cov else 'n/a'}; "
              f"typical miss x/÷{10 ** statistics.median(err):.2f}")
    if not any_target:
        print("SCOREBOARD  nothing resolved yet. Forecast, post, then `resolve` with the final numbers.")
    write_json(data / "calibration.json", cal)


def cmd_backtest_prepare(args):
    data = data_dir(args)
    prof = read_json(data / "profile.json", {}) or {}
    rows = read_csv(data / "history.csv")[0] if (data / "history.csv").exists() else []
    rows = mature_rows(rows, prof.get("min_age_days", 7.0))
    _, _, _, rp = history_rp(rows, args.target, prof.get("window", 10))
    pool = [r for r, x in zip(rows, rp) if x is not None and r.get("video_path")
            and Path(r["video_path"]).expanduser().exists()]
    if len(pool) < 5:
        sys.exit(f"Backtest needs past videos on disk: {len(pool)} history rows have an existing video_path and a "
                 f"known {args.target} (5+ needed, 30+ for a meaningful result).")
    rng = random.Random(args.seed)
    rng.shuffle(pool)
    pool = pool[:args.max]
    queue, key = [], {}
    for i, r in enumerate(pool, 1):
        anon = f"b{i:03d}"
        key[anon] = r["video_id"]
        queue.append({"anon_id": anon, "video_path": r["video_path"], "platform": r.get("platform") or prof.get("platform"),
                      "caption": r.get("caption", ""), "duration_s": r.get("duration_s", "")})
    blind = data / "blind"
    (blind / "judgments").mkdir(parents=True, exist_ok=True)
    write_json(blind / "queue.json", queue)
    write_json(blind / "key.json", {"WARNING": "outcome key - the judge must not read this file", "key": key,
                                    "target": args.target})
    print(f"BACKTEST  {len(queue)} videos queued -> {blind / 'queue.json'}")
    print("  Judge each one blind (no metrics, no dates, no key.json, no history.csv), one judge file per video:")
    print(f"    {blind / 'judgments'}/<anon_id>.json   (same format as a normal judge file, no context, no anchors)")
    print(f"  Then: vforecast.py backtest-score --data {data} --apply")
    if len(queue) < 30:
        print(f"  NOTE with {len(queue)} videos the confidence interval will be wide; treat the result as a first read.")


def fit_stack(x, y, lam=5.0):
    n, k = x.shape

    def solve(xm, ym):
        return np.linalg.solve(xm.T @ xm + lam * np.eye(k), xm.T @ ym)

    coef = solve(x, y)
    loo = np.empty(n)
    for i in range(n):
        mask = np.ones(n, bool)
        mask[i] = False
        loo[i] = x[i] @ solve(x[mask], y[mask])
    corr = np.corrcoef(x, rowvar=False) if k > 1 else np.ones((1, 1))
    scale = math.sqrt(float(coef @ corr @ coef))
    return (coef / scale if scale > 0 else coef), spearman(loo, y)


def cmd_backtest_score(args):
    data = data_dir(args)
    blind = data / "blind"
    keyfile = read_json(blind / "key.json")
    if not keyfile:
        sys.exit("No blind queue found. Run backtest-prepare first.")
    key, target = keyfile["key"], args.target or keyfile.get("target", "views")
    prof = read_json(data / "profile.json", {}) or {}
    rows = mature_rows(read_csv(data / "history.csv")[0], prof.get("min_age_days", 7.0))
    _, _, _, rp = history_rp(rows, target, prof.get("window", 10))
    rp_by_id = {r["video_id"]: x for r, x in zip(rows, rp)}
    row_by_id = {r["video_id"]: r for r in rows}
    recs = []
    for jpath in sorted((blind / "judgments").glob("*.json")):
        j = read_json(jpath)
        anon = j.get("anon_id") or jpath.stem
        vid = key.get(anon)
        if vid is None or rp_by_id.get(vid) is None or "subscores" not in j:
            continue
        sig = judge_signal([j], target, data=None, use_context=False, use_anchor=False)
        recs.append({"anon_id": anon, "video_id": vid, "z": sig["z"], "rp": rp_by_id[vid],
                     "subscores": sig["subscores"], "judge": j})
    if len(recs) < 5:
        sys.exit(f"Only {len(recs)} usable blind judgments (5+ needed). Judge more videos from blind/queue.json.")
    z = [r["z"] for r in recs]
    y = [r["rp"] for r in recs]
    print(f"BACKTEST  {target}: {len(recs)} blind judgments vs real outcomes")
    rho = score_block(z, y, "this skill (content judgment only)")
    for k in SUBSCORES:
        pairs = [(r["subscores"][k], r["rp"]) for r in recs if k in r["subscores"]]
        if len(pairs) >= 8:
            print(f"    sub-score {k:16s} rank correlation {spearman([a for a, _ in pairs], [b for _, b in pairs]):+.2f}")
    compare = [c.strip() for c in (args.compare or "").split(",") if c.strip()]
    ext = {}
    for col in compare:
        vals = [parse_num(row_by_id[r["video_id"]].get(col)) for r in recs]
        have = [(v, r) for v, r in zip(vals, recs) if v is not None]
        if len(have) < 5:
            print(f"  {col}: only {len(have)} rows have a value; skipped")
            continue
        cz, cy, mz = [v for v, _ in have], [r["rp"] for _, r in have], [r["z"] for _, r in have]
        score_block(cz, cy, f"{col}")
        rng = np.random.default_rng(777)
        a, b, c = np.array(mz), np.array(cz), np.array(cy)
        diffs = []
        for _ in range(2000):
            idx = rng.integers(0, len(a), len(a))
            d = spearman(a[idx], c[idx]) - spearman(b[idx], c[idx])
            if not math.isnan(d):
                diffs.append(d)
        if diffs:
            print(f"    on the same {len(have)} videos: this skill minus {col} = {np.mean(diffs):+.2f} "
                  f"(95% CI {np.percentile(diffs, 2.5):+.2f} to {np.percentile(diffs, 97.5):+.2f}); "
                  f"this skill ranks better in {pct(float(np.mean(np.array(diffs) > 0)))} of resamples")
        ext[col] = vals
    if len(recs) < 30:
        print(f"  NOTE n={len(recs)}: differences smaller than the confidence intervals above are noise.")
    with open(blind / "results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["anon_id", "video_id", "judge_z", "relative_performance"] + list(ext))
        for i, r in enumerate(recs):
            w.writerow([r["anon_id"], r["video_id"], r["z"], round(r["rp"], 4)] + [ext[c][i] for c in ext])
    if args.apply:
        cal = load_calibration(data)
        if not math.isnan(rho):
            cal.setdefault("targets", {}).setdefault(target, {})["backtest"] = {"r": round(rho, 4), "n": len(recs),
                                                                                "updated_at": now_iso()}
        stack_cols = [c for c in (args.stack or "").split(",") if c.strip() and c.strip() in ext]
        if stack_cols:
            keep = [i for i in range(len(recs)) if all(ext[c][i] is not None for c in stack_cols)]
            if len(keep) >= 30:
                cols = [[z[i] for i in keep]] + [[ext[c][i] for i in keep] for c in stack_cols]
                x = np.column_stack([normal_scores(c) for c in cols])
                coef, r_loo = fit_stack(x, normal_scores([y[i] for i in keep]))
                cal["stack"] = {"target": target, "signals": ["judge"] + stack_cols, "coef": [float(c) for c in coef],
                                "r_loo": float(r_loo), "n": len(keep),
                                "dists": {name: sorted(float(v) for v in col) for name, col in
                                          zip(["judge"] + stack_cols, cols)}}
                print(f"  stacked signal fitted on {len(keep)} videos: weights "
                      + ", ".join(f"{n}={c:+.2f}" for n, c in zip(["judge"] + stack_cols, coef))
                      + f"; leave-one-out rank correlation {r_loo:+.2f}")
            else:
                print(f"  stacking needs 30+ videos with every signal; have {len(keep)}. Not fitted.")
        write_json(data / "calibration.json", cal)
        for rec in recs:                        # blind judgments with known results become the account's library
            write_card(data, rec["video_id"], rec["judge"], rec["subscores"], blind=True,
                       outcome=card_outcomes(rows, rec["video_id"], prof.get("window", 10)))
        r, src, _ = reliability(cal, target)
        print(f"  calibration updated: reliability now r={r:.2f}  [{src}]")
        print(f"  {len(recs)} judged videos added to the library (anchors and own-scale scoring)")
    else:
        print("  (dry run: add --apply to store this as the account's measured reliability)")


def cmd_export(args):
    data = data_dir(args, create=False)
    if not data.exists():
        sys.exit(f"No data folder at {data}")
    out = Path(args.out).expanduser()
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(data.rglob("*")):
            if not path.is_file():
                continue
            if not args.with_images and path.suffix.lower() in (".jpg", ".jpeg", ".png", ".mp4", ".mov", ".wav"):
                continue
            zf.write(path, Path(data.name) / path.relative_to(data))
            n += 1
    print(f"EXPORT  {n} files -> {out}  (keep this file; `import` it at the start of the next session)")


def cmd_import(args):
    data = data_dir(args)
    with zipfile.ZipFile(Path(args.zip).expanduser()) as zf:
        for member in zf.namelist():
            parts = Path(member).parts
            if member.endswith("/") or ".." in parts or len(parts) < 2:
                continue
            dest = data.joinpath(*parts[1:])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
    print(f"IMPORT  restored into {data}")
    cmd_status(args)


def cmd_selftest(args):
    """Simulate accounts where the truth is known and check that the statistics do what they claim."""
    rng = np.random.default_rng(42)
    failures = []

    def check(name, ok, detail):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failures.append(name)

    def simulate(n_hist, r_signal, r_used=None, accounts=150, tests=10):
        """Accounts that drift in size and have skewed results, judged by a signal of known quality."""
        series, pool_s, pool_rp = [], [], []
        for _ in range(accounts):
            n = n_hist + tests
            u = rng.standard_normal(n)
            lat = 3.5 + np.cumsum(rng.normal(0, 0.03, n)) + 0.35 * u + 0.06 * (u ** 2 - 1)
            sig = r_signal * u + math.sqrt(1 - r_signal ** 2) * rng.standard_normal(n)
            series.append((lat, sig))
            _, rp = rolling_rp(list(lat[:n_hist]), 10)
            for a, b in zip(sig[:n_hist], rp):
                if b is not None:
                    pool_s.append(a)
                    pool_rp.append(b)
        measured = spearman(pool_s, pool_rp)                    # what a blind backtest would report
        r = measured if r_used is None else r_used
        cover, hits = [], {2: [], 3: []}
        for lat, sig in series:
            for t in range(n_hist, n_hist + tests):
                _, rp = rolling_rp(list(lat[:t]), 10)
                marg = Marginal(sorted(x for x in rp if x is not None), "count")
                base = float(np.median(lat[max(0, t - 10):t]))
                fc = make_forecast(float(sig[t]), r, marg, base, "count", (2, 3))
                cover.append(fc["quantiles"]["p10"] <= from_latent(lat[t], "count") <= fc["quantiles"]["p90"])
                for k in (2, 3):
                    hits[k].append((fc["p"][f"x{k}"], float(lat[t] - base >= math.log10(k)), fc["base"][f"x{k}"]))
        out = {"measured": measured, "cover": float(np.mean(cover))}
        for k in (2, 3):
            a = np.array(hits[k])
            out[f"x{k}"] = (float(a[:, 0].mean()), float(a[:, 1].mean()))
            out[f"skill{k}"] = 1 - float(((a[:, 0] - a[:, 1]) ** 2).mean() / ((a[:, 2] - a[:, 1]) ** 2).mean())
        return out

    print("SELFTEST  150 simulated accounts per case, known ground truth")
    for n_hist in (8, 30):
        sim = simulate(n_hist, 0.5)
        tag = f"{n_hist} posts of history"
        check(f"80% ranges hold, {tag}", 0.76 <= sim["cover"] <= 0.86, f"{sim['cover']:.3f}")
        check(f"P(>=2x) matches frequency, {tag}", abs(sim["x2"][0] - sim["x2"][1]) < 0.03,
              f"forecast {sim['x2'][0]:.3f} vs observed {sim['x2'][1]:.3f}")
        check(f"P(>=3x) matches frequency, {tag}", abs(sim["x3"][0] - sim["x3"][1]) < 0.035,
              f"forecast {sim['x3'][0]:.3f} vs observed {sim['x3'][1]:.3f}")
        check(f"forecast beats the base rate, {tag}", sim["skill2"] > 0.03,
              f"Brier skill {sim['skill2']:+.3f} (judge reliability measured at r={sim['measured']:.2f})")
    sim = simulate(30, 0.0)
    check("a judge with no signal just returns the base rate", abs(sim["skill2"]) < 0.01 and 0.76 <= sim["cover"] <= 0.86,
          f"Brier skill {sim['skill2']:+.3f}, coverage {sim['cover']:.3f}")
    sim = simulate(30, 0.5, r_used=0.9)
    check("an overconfident judge is exposed", sim["cover"] < 0.65 and sim["skill2"] < 0,
          f"claimed 80% ranges held {sim['cover']:.2f}; Brier skill {sim['skill2']:+.2f}")
    r_true = 0.5
    sig = rng.standard_normal(200)
    out = r_true * sig + math.sqrt(1 - r_true ** 2) * rng.standard_normal(200)
    live = spearman(sig, out)
    r_est, _, _ = reliability({"targets": {"views": {"live": {"r": live, "n": 200}}}}, "views")
    check("recalibration moves from the prior to the evidence", abs(r_est - live) < 0.06 and r_est > TARGETS["views"]["r0"],
          f"prior {TARGETS['views']['r0']}, measured {live:.2f} on 200 forecasts -> uses {r_est:.2f}")
    for n_fit in (6, 25):                                       # few past videos with snapshots, then more
        inside = total = 0
        for _ in range(60):
            early = 10 ** rng.normal(3.0, 0.4, n_fit + 10)
            final = early * 10 ** rng.normal(0.9, 0.15, n_fit + 10)
            fit = fit_loglog(np.log10(early[:n_fit] + 1), np.log10(final[:n_fit] + 1))
            for e, f in zip(early[n_fit:], final[n_fit:]):
                m, sd = loglog_predict(fit, math.log10(e + 1))
                inside += 10 ** (m + t_ppf(.1, fit["df"]) * sd) <= f + 1 <= 10 ** (m + t_ppf(.9, fit["df"]) * sd)
                total += 1
        check(f"nowcast 80% ranges hold, fitted on {n_fit} past videos", 0.76 <= inside / total <= 0.86,
              f"{inside / total:.3f} on {total} held-out videos")
    check("student-t quantile and cdf", abs(t_ppf(0.9, 4) - 1.533) < 0.01 and abs(t_cdf(1.533, 4) - 0.9) < 0.005,
          f"t(0.9, 4)={t_ppf(0.9, 4):.4f} (exact 1.5332), cdf back to {t_cdf(1.533, 4):.4f}")
    p = bradley_terry(["A", "B", "C"], [{"a": "A", "b": "B", "winner": "A", "margin": 3},
                                        {"a": "B", "b": "C", "winner": "B", "margin": 2},
                                        {"a": "C", "b": "A", "winner": "A", "margin": 2}])
    check("pairwise ranking recovers the order", p[0] > p[1] > p[2], f"strengths {np.round(p, 2).tolist()}")
    u = rng.standard_normal(300)
    marg = Marginal(sorted((0.35 * u + 0.06 * (u ** 2 - 1)).tolist()), "count")
    worst = max(abs(marg.z(marg.q(zz)) - zz) for zz in np.linspace(-3, 3, 61))
    check("quantile function inverts cleanly", worst < 1e-3, f"max round-trip error {worst:.2e}")
    print("SELFTEST " + ("passed" if not failures else f"FAILED: {failures}"))
    sys.exit(1 if failures else 0)


# ----------------------------------------------------------------------------- cli
def build_parser():
    ap = argparse.ArgumentParser(description="Calibrated forecasting toolkit for short-form video performance.")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, func, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--data", default="virality-data", help="account data folder (default: ./virality-data)")
        sp.set_defaults(func=func)
        return sp

    sp = add("profile", cmd_profile, "build the account baseline")
    sp.add_argument("--history", help="CSV export of past posts (one row per post)")
    sp.add_argument("--views", help="quick start: recent view counts, e.g. \"1200, 900, 15000\"")
    sp.add_argument("--order", choices=["newest-first", "oldest-first"], default="newest-first",
                    help="row order when there is no date column (default: newest-first)")
    sp.add_argument("--map", action="append", help="map a column: canonical=Column Header (repeatable)")
    sp.add_argument("--platform", help="tiktok, reels, shorts, ads, ...")
    sp.add_argument("--window", type=int, help="posts in the rolling baseline (default 10)")
    sp.add_argument("--date-format", help="strptime format of the date column, e.g. %%m/%%d/%%Y, if detection is wrong")
    sp.add_argument("--min-age-days", type=float,
                    help="leave out posts younger than this, their numbers are still growing (default 7; 0 = keep all)")
    sp.add_argument("--drop-resolved", action="store_true",
                    help="do not carry over posts recorded with `resolve` when re-importing")

    add("status", cmd_status, "show what the data folder contains")

    sp = add("forecast", cmd_forecast, "probabilities and ranges from judge file(s)")
    sp.add_argument("--judge", nargs="+", required=True, help="one or more judge JSON files (independent judges are averaged)")
    sp.add_argument("--target", default="views", help=f"one or more, comma-separated, of: {', '.join(TARGETS)}")
    sp.add_argument("--video-id", help="identifier used to log and later resolve this forecast")
    sp.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="what-if: override a sub-score or context score, e.g. --set stop_power=5.5 (not logged)")
    sp.add_argument("--multiples", default="2,3,10", help="breakout thresholds as multiples of baseline")
    sp.add_argument("--external", action="append", help="external signal name=value (used only with a fitted stack)")
    sp.add_argument("--no-log", action="store_true", help="do not write to predictions.jsonl / library")
    sp.add_argument("--out", help="also write the forecast JSON here")

    sp = add("library-add", cmd_library_add, "add a published video with a known result as an anchor")
    sp.add_argument("--judge", required=True)
    sp.add_argument("--video-id", help="id of the row in history.csv (or any id when --views is given)")
    sp.add_argument("--views", help="its final view count, if it is not a row in history.csv")

    sp = add("anchors", cmd_anchors, "past videos with known outcomes, for anchored placement")
    sp.add_argument("--target", default="views")
    sp.add_argument("--k", type=int, default=6)

    sp = add("rank", cmd_rank, "rank variants from pairwise judgments")
    sp.add_argument("--pairs", required=True, help="JSON: {items: [...], comparisons: [{a, b, winner, margin}]}")
    sp.add_argument("--target", default="views")
    sp.add_argument("--out")

    sp = add("snapshot", cmd_snapshot, "log early metrics")
    sp.add_argument("--video-id", required=True)
    sp.add_argument("--age-min", type=float, required=True, help="minutes since posting")
    sp.add_argument("--views", type=float, required=True)
    for name in ("likes", "comments", "shares", "saves", "completion-rate", "avg-watch-s"):
        sp.add_argument(f"--{name}", type=float)

    sp = add("nowcast", cmd_nowcast, "update the forecast from early metrics")
    sp.add_argument("--video-id", required=True)
    sp.add_argument("--multiples", default="2,3,10")

    sp = add("resolve", cmd_resolve, "record a final outcome")
    sp.add_argument("--video-id", required=True)
    sp.add_argument("--views")
    for name in ("likes", "comments", "shares", "saves", "avg-watch-s", "completion-rate", "hook-rate",
                 "duration-s", "platform", "posted-at"):
        sp.add_argument(f"--{name}")

    sp = add("scoreboard", cmd_scoreboard, "score resolved forecasts and recalibrate")

    sp = add("backtest-prepare", cmd_backtest_prepare, "build a blind queue from history videos")
    sp.add_argument("--target", default="views")
    sp.add_argument("--max", type=int, default=30)
    sp.add_argument("--seed", type=int, default=7)

    sp = add("backtest-score", cmd_backtest_score, "score blind judgments against outcomes")
    sp.add_argument("--target")
    sp.add_argument("--compare", help="history columns holding other predictors' scores, comma-separated")
    sp.add_argument("--stack", help="columns from --compare to blend with the judge (needs 30+ videos)")
    sp.add_argument("--apply", action="store_true", help="store the measured reliability in calibration.json")

    sp = add("export", cmd_export, "zip the data folder")
    sp.add_argument("--out", required=True)
    sp.add_argument("--with-images", action="store_true")

    sp = add("import", cmd_import, "restore a zipped data folder")
    sp.add_argument("--zip", required=True)

    add("selftest", cmd_selftest, "check the statistics on synthetic data")
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)
    try:
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


if __name__ == "__main__":
    main()
