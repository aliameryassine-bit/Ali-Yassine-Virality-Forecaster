#!/usr/bin/env python3
"""End-to-end checks for the two scripts. No test framework needed:

    python tests/run_tests.py        (add -v to see every command and its output)

Everything runs on a synthetic account in a temporary folder. The "judge" here is simulated
(sub-scores that correlate with a hidden quality variable), which tests the statistics and the
plumbing, not anyone's ability to judge videos.
"""
import csv
import datetime as dt
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "virality-forecaster" / "scripts"
VF = [sys.executable, str(SCRIPTS / "vforecast.py")]
AV = [sys.executable, str(SCRIPTS / "analyze_video.py")]
SUBSCORES = ["stop_power", "hold", "share_save", "comment_trigger", "rewatch_loop", "audience_fit"]
PASSED = []
VERBOSE = "-v" in sys.argv          # print every command and its output


def run(cmd, expect_ok=True):
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    if VERBOSE:
        print("    $ " + " ".join(Path(str(c)).name if str(c).startswith("/") else str(c) for c in cmd))
        print("".join("    | " + line + "\n" for line in out.splitlines()), end="")
    if expect_ok and proc.returncode != 0:
        raise AssertionError(f"command failed ({proc.returncode}): {' '.join(str(c) for c in cmd)}\n{out}")
    if not expect_ok and proc.returncode == 0:
        raise AssertionError(f"command should have failed: {' '.join(str(c) for c in cmd)}\n{out}")
    return out


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    PASSED.append(name)
    print(f"  ok  {name}")


def fake_judge(rng, quality, video_id, noise=0.9, **extra):
    """A simulated judge: every sub-score sees the hidden quality through its own noise."""
    sub = {k: round(min(7, max(1, 4 + 1.1 * quality + rng.gauss(0, noise))), 1) for k in SUBSCORES}
    judge = {"video_id": video_id, "platform": "tiktok", "audience": "test audience",
             "description": f"synthetic video {video_id}", "hook_summary": "synthetic hook",
             "subscores": sub, "context": {"checked": False}, "blind_spots": []}
    judge.update(extra)
    return judge


def views_for(rng, level, quality):
    return int(round(10 ** (level + 0.30 * quality + rng.gauss(0, 0.12))))


def main():
    rng = random.Random(7)
    tmp = Path(tempfile.mkdtemp(prefix="vforecast-test-"))
    data = tmp / "data"
    try:
        print("statistics self-test")
        out = run(VF + ["selftest"])
        check("selftest passes", "SELFTEST passed" in out, out[-400:])

        # ------------------------------------------------------------------ a messy analytics export
        print("profile from a messy export")
        now = dt.datetime.now()
        hidden, rows = {}, []
        for i in range(46):
            age_days = 10 + 3 * (43 - i) if i < 44 else (3 if i == 44 else 1)       # two posts are too fresh
            quality = rng.gauss(0, 1)
            views = views_for(rng, 3.6 + 0.004 * i, quality)
            clip = tmp / "clips" / f"clip_{i:02d}.mp4"
            clip.parent.mkdir(exist_ok=True)
            clip.write_bytes(b"not a real video; backtest-prepare only needs the file to exist")
            title = f"synthetic post {i:02d}"
            hidden[title] = quality
            shown = f"{views / 1000:.1f}K" if i % 5 == 0 else (f"{views:,}" if i % 5 == 1 else str(views))
            rows.append({
                "Video title": title, "Post time": (now - dt.timedelta(days=age_days)).strftime("%d/%m/%Y %H:%M"),
                "Video views": shown, "Likes": int(views * 0.08), "Comments": int(views * 0.006),
                "Shares": int(views * (0.012 + 0.003 * quality)), "Duration": "0:21",
                "Average watch time": round(21 * (0.42 + 0.05 * quality), 1),
                "Watched full video (%)": f"{100 * min(0.6, max(0.05, 0.25 + 0.05 * quality)):.1f}%",
                "higgsfield_score": round(55 + 9 * (0.35 * quality + rng.gauss(0, 1)), 1),
                "video_path": str(clip), "raw_views": views,
            })
        rows.reverse()                                                    # newest first, like most exports
        export = tmp / "export.csv"
        with open(export, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        out = run(VF + ["profile", "--data", data, "--history", export, "--platform", "tiktok"])
        check("counts only settled posts", "PROFILE  44 posts" in out and "2 post(s) younger than 7 days" in out, out)
        prof = json.loads((data / "profile.json").read_text())
        settled = [r["raw_views"] for r in reversed(rows)][:44]
        expected = sorted(settled[-10:])
        expected = (expected[4] + expected[5]) / 2
        got = prof["targets"]["views"]["baseline"]
        check("baseline is the median of the last 10 settled posts", abs(got - expected) / expected < 0.03,
              f"{got} vs {expected}")
        check("derived targets exist", all(t in prof["targets"] for t in
                                           ("views", "share_rate", "completion_rate", "avg_watch_pct")), list(prof["targets"]))
        history = list(csv.DictReader(open(data / "history.csv", encoding="utf-8")))
        ids = {r["caption"]: r["video_id"] for r in history}

        ambiguous = tmp / "ambiguous.csv"
        ambiguous.write_text("date,views\n03/04/2026,1000\n05/06/2026,1500\n07/08/2026,900\n09/10/2026,1200\n")
        out = run(VF + ["profile", "--data", tmp / "amb", "--history", ambiguous])
        check("ambiguous dates are flagged", "WARNING dates fit more than one format" in out, out)
        out = run(VF + ["profile", "--data", tmp / "quick", "--views", "1200, 950, 15K, 700, 1100, 820"])
        check("quick start from a list of view counts", "PROFILE  6 posts" in out and "fewer than 10 posts" in out, out)

        # ------------------------------------------------------------------ forecast
        print("forecast")
        strong, weak = tmp / "strong.json", tmp / "weak.json"
        strong.write_text(json.dumps(fake_judge(rng, 1.6, "strong", noise=0.1)))
        weak.write_text(json.dumps(fake_judge(rng, -1.6, "weak", noise=0.1)))
        out = run(VF + ["forecast", "--data", data, "--judge", strong, "--target", "views,share_rate,completion_rate"])
        check("forecast prints odds and a range", "P(beats the current baseline)" in out and "likely range (80%)" in out, out)
        run(VF + ["forecast", "--data", data, "--judge", weak])
        preds = [json.loads(line) for line in (data / "predictions.jsonl").read_text().splitlines()]
        check("three targets logged for one video, one for the other", len(preds) == 4, len(preds))
        ps, pw = preds[0], preds[3]
        check("probabilities are ordered", ps["p"]["above_baseline"] > ps["p"]["x2"] >= ps["p"]["x3"] >= ps["p"]["x10"] >= 0,
              ps["p"])
        check("a stronger judgment gives higher odds", ps["p"]["x2"] > pw["p"]["x2"] and
              ps["p"]["above_baseline"] > pw["p"]["above_baseline"], (ps["p"], pw["p"]))
        check("an uncalibrated judge cannot make a confident call",
              ps["p"]["above_baseline"] < 0.75 and pw["p"]["above_baseline"] > 0.25, (ps["p"], pw["p"]))
        q = ps["quantiles"]
        check("range is ordered", q["p10"] < q["p25"] < q["p50"] < q["p75"] < q["p90"], q)
        check("rates do not get 2x/3x/10x questions", "x2" not in preds[2]["p"] and "x2" not in preds[1]["p"], preds[2]["p"])

        out = run(VF + ["forecast", "--data", data, "--judge", weak, "--set", "stop_power=6.5", "--set", "hold=6"])
        n_after = len((data / "predictions.jsonl").read_text().splitlines())
        check("what-if shows the change and logs nothing", "WHAT-IF" in out and "with the change" in out and n_after == 4, out)
        script = tmp / "script.json"
        script.write_text(json.dumps(fake_judge(rng, 1.0, "script-only", input="script")))
        out = run(VF + ["forecast", "--data", data, "--judge", script, "--no-log", "--out", tmp / "script_fc.json"])
        fc = json.loads((tmp / "script_fc.json").read_text())
        check("script-only judgments get less weight", abs(fc["r_used"] - 0.6 * 0.25) < 1e-6 and "not the finished video" in out,
              fc["r_used"])
        run(VF + ["forecast", "--data", data, "--judge", strong, "--target", "nonsense"], expect_ok=False)
        PASSED.append("unknown target is rejected")
        print("  ok  unknown target is rejected")

        # ------------------------------------------------------------------ blind backtest + head-to-head + stacking
        print("blind backtest against another predictor")
        out = run(VF + ["backtest-prepare", "--data", data, "--max", "36"])
        queue = json.loads((data / "blind" / "queue.json").read_text())
        check("blind queue holds 36 videos and no outcomes", len(queue) == 36 and
              all(set(item) == {"anon_id", "video_path", "platform", "caption", "duration_s"} for item in queue), queue[0])
        key = json.loads((data / "blind" / "key.json").read_text())["key"]         # test only: a judge never opens this
        by_id = {v: k for k, v in ids.items()}
        for item in queue:
            quality = hidden[by_id[key[item["anon_id"]]]]
            judge = fake_judge(rng, quality, item["anon_id"], anon_id=item["anon_id"])
            (data / "blind" / "judgments" / f"{item['anon_id']}.json").write_text(json.dumps(judge))
        out = run(VF + ["backtest-score", "--data", data, "--compare", "higgsfield_score",
                        "--stack", "higgsfield_score", "--apply"])
        check("backtest reports this skill and the other predictor",
              "this skill (content judgment only)" in out and "higgsfield_score: rank correlation" in out
              and "this skill minus higgsfield_score" in out, out)
        cal = json.loads((data / "calibration.json").read_text())
        check("measured reliability is stored", cal["targets"]["views"]["backtest"]["n"] == 36
              and 0.2 < cal["targets"]["views"]["backtest"]["r"] < 0.95, cal["targets"])
        check("stack is fitted on 36 videos", cal["stack"]["signals"] == ["judge", "higgsfield_score"]
              and cal["stack"]["n"] == 36 and cal["stack"]["coef"][0] > cal["stack"]["coef"][1], cal["stack"]["coef"])
        cards = list((data / "library").glob("*/card.json"))
        known = [c for c in cards if json.loads(c.read_text()).get("outcome", {}).get("views")]
        check("backtested videos join the library with their results", len(known) == 36, len(known))
        out = run(VF + ["anchors", "--data", data, "--k", "5"])
        check("anchors list past videos from weakest to strongest", "A1" in out and "A5" in out and "x baseline" in out, out)
        out = run(VF + ["forecast", "--data", data, "--judge", strong, "--no-log", "--external", "higgsfield_score=71"])
        check("an external score is blended once a stack exists", "stacked signal from ['judge', 'higgsfield_score']" in out, out)
        out = run(VF + ["forecast", "--data", data, "--judge", strong, "--no-log", "--out", tmp / "own.json"])
        own = json.loads((tmp / "own.json").read_text())
        check("scores are read on the account's own scale once a library exists", "this account's library of" in out
              and own["r_used"] > 0.25, out)

        out = run(VF + ["library-add", "--data", data, "--judge", weak, "--video-id", "old-flop", "--views", "900"])
        card = json.loads((data / "library" / "old-flop" / "card.json").read_text())
        check("library-add stores a known result as a non-blind anchor", card["blind"] is False
              and card["outcome"]["views"]["rp"] < 0, card)

        # ------------------------------------------------------------------ live loop: forecast, snapshot, resolve, score
        print("live loop")
        level = 3.6 + 0.004 * 46
        finals = {}
        for i in range(14):
            vid = f"live-{i:02d}"
            quality = rng.gauss(0, 1)
            judge_path = tmp / f"{vid}.json"
            judge_path.write_text(json.dumps(fake_judge(rng, quality, vid)))
            run(VF + ["forecast", "--data", data, "--judge", judge_path])
            finals[vid] = views_for(rng, level, quality)
            early = int(finals[vid] / 8 * 10 ** rng.gauss(0, 0.08))
            run(VF + ["snapshot", "--data", data, "--video-id", vid, "--age-min", "60", "--views", str(early),
                      "--shares", str(int(early * 0.012))])
            if i < 13:
                out = run(VF + ["resolve", "--data", data, "--video-id", vid, "--views", str(finals[vid]),
                                "--shares", str(int(finals[vid] * 0.012))])
        check("resolve scores the open forecast", "1 forecast(s) scored" in out and "the 80% range was" in out, out)
        out = run(VF + ["nowcast", "--data", data, "--video-id", "live-13"])
        check("nowcast turns early views into a final range", "final views (80% range)" in out
              and "pace:" in out and "P(finishes at 2x baseline or more" in out, out)
        now_entry = [json.loads(line) for line in (data / "predictions.jsonl").read_text().splitlines()][-1]
        early_13 = now_entry["views_at_age"]
        check("nowcast never forecasts fewer views than already counted", now_entry["quantiles"]["p10"] >= early_13, now_entry)
        check("nowcast is tighter than the pre-post range",
              now_entry["quantiles"]["p90"] / now_entry["quantiles"]["p10"] < 4, now_entry["quantiles"])
        out = run(VF + ["resolve", "--data", data, "--video-id", "live-13", "--views", str(finals["live-13"])])
        check("resolving scores both the forecast and the nowcast", "2 forecast(s) scored" in out, out)
        out = run(VF + ["scoreboard", "--data", data])
        check("scoreboard reports skill, calibration and coverage", "ranking skill: rank correlation" in out
              and "Brier" in out and "80% ranges contained the outcome" in out and "NOWCASTS  1 resolved" in out, out)
        cal = json.loads((data / "calibration.json").read_text())
        check("live results feed the reliability", cal["targets"]["views"]["live"]["n"] == 14, cal["targets"]["views"])
        out = run(VF + ["status", "--data", data])
        check("status summarises the folder", "14 video(s) resolved" in out and "backtest n=36" in out and "live n=14" in out, out)
        prof2 = json.loads((data / "profile.json").read_text())
        check("resolved posts move the baseline window", prof2["n_posts"] == 44 + 14, prof2["n_posts"])

        # ------------------------------------------------------------------ ranking variants
        print("ranking variants")
        pairs = tmp / "pairs.json"
        pairs.write_text(json.dumps({"items": ["A", "B", "C"], "comparisons": [
            {"a": "A", "b": "B", "winner": "B", "margin": 3}, {"a": "B", "b": "A", "winner": "B", "margin": 3},
            {"a": "A", "b": "C", "winner": "A", "margin": 1}, {"a": "C", "b": "A", "winner": "A", "margin": 2},
            {"a": "B", "b": "C", "winner": "B", "margin": 3}, {"a": "C", "b": "B", "winner": "B", "margin": 2}]}))
        out = run(VF + ["rank", "--data", data, "--pairs", pairs, "--out", tmp / "rank.json"])
        rank = json.loads((tmp / "rank.json").read_text())
        check("ranking orders the variants", rank["ranking"] == ["B", "A", "C"] and 0.5 < rank["p_top_beats_second"] < 0.95, rank)

        # ------------------------------------------------------------------ portability
        print("export and import")
        archive = tmp / "virality-data.zip"
        run(VF + ["export", "--data", data, "--out", archive])
        out = run(VF + ["import", "--data", tmp / "restored", "--zip", archive])
        check("a data folder survives export and import", "14 video(s) resolved" in out and
              (tmp / "restored" / "calibration.json").exists() and (tmp / "restored" / "library").exists(), out)

        # ------------------------------------------------------------------ perception
        print("video analysis")
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            clip = tmp / "clip.mp4"
            run(["ffmpeg", "-v", "error", "-y",
                 "-f", "lavfi", "-t", "1.2", "-i", "color=c=black:s=360x640:r=30",
                 "-f", "lavfi", "-t", "3.3", "-i", "testsrc2=s=360x640:r=30",
                 "-f", "lavfi", "-t", "3.5", "-i", "mandelbrot=s=360x640:r=30",
                 "-f", "lavfi", "-t", "1.2", "-i", "anullsrc=r=44100:cl=mono",
                 "-f", "lavfi", "-t", "6.8", "-i", "sine=frequency=440:sample_rate=44100",
                 "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v];[3:a][4:a]concat=n=2:v=0:a=1[a]",
                 "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip])
            out = run(AV + [clip, "--out", tmp / "analysis", "--transcribe", "off"])
            result = json.loads((tmp / "analysis" / "analysis.json").read_text())
            flags = {f["id"] for f in result["flags"]}
            check("sheets are written", (tmp / "analysis" / "hook_sheet.jpg").stat().st_size > 5000
                  and (tmp / "analysis" / "timeline_sheet.jpg").stat().st_size > 5000)
            check("a slow, silent, black opening is flagged", {"dead_air_start", "black_start", "static_start"} <= flags, flags)
            check("cuts are found near 1.2s and 4.5s", result["pacing"]["n_cuts"] == 2
                  and abs(result["pacing"]["cuts_s"][0] - 1.2) < 0.15 and abs(result["pacing"]["cuts_s"][1] - 4.5) < 0.15,
                  result["pacing"])
            check("sound onset is measured", abs(result["audio"]["sound_starts_s"] - 1.2) < 0.15, result["audio"])
            check("video facts are read", result["video"]["orientation"] == "vertical"
                  and abs(result["video"]["duration_s"] - 8.0) < 0.2, result["video"])
        else:
            print("  skipped (ffmpeg not installed)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nall {len(PASSED)} checks passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"\nFAILED  {exc}")
        sys.exit(1)
