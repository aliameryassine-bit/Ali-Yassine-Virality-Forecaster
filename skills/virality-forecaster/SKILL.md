---
name: virality-forecaster
description: Forecast how a short-form video (TikTok, Reels, Shorts, Spotlight, or a social video ad) will perform, as calibrated odds and view ranges measured against the creator's own track record, then update the forecast from early stats and score it against what really happened. Use this whenever someone asks "will this go viral", wants a virality, hook or retention score, asks which cut, hook or caption to post, wants a video or script critiqued for reach, shares early numbers and asks whether a post is taking off, pastes analytics and asks what to expect, or wants a prediction tool such as Higgsfield's Virality Predictor checked or beaten. Use it even for a quick opinion on a video's chances, because an unstructured guess is exactly what this replaces.
license: MIT
---

# Ali Yassine Virality Forecaster

## What this does and why it is built this way

How a video performs comes from three things: how good it is for its audience, who the account already reaches, and what happens after posting (who sees it first, what else is in the feed that day). Studies on real platforms find the third part is large, so nobody can say for sure that a video will go viral. See `references/evidence.md`.

A tool that looks at a clip and prints one "virality score" sees only the first of the three, gives no odds, and cannot be checked. This skill does five things instead:

1. **Looks at the video properly**: the first three seconds frame by frame, pacing, audio, spoken words.
2. **Judges it on a fixed rubric**: six sub-scores, each with written evidence.
3. **Turns the judgment into odds against this account's own history**, pulled toward the account's base rates by how reliable the judging has proven to be.
4. **Updates the forecast from the first hours of real numbers**, which carry more information than any pre-post judgment.
5. **Logs every forecast and scores it later**, so reliability is measured instead of assumed and the odds sharpen with use.

The division of labour is strict: **you judge, the script does the arithmetic.**

## Ground rules

Each of these protects accuracy. Keep them even when the user wants a quick answer.

- **Never state a probability, a view range or a 0-100 score from your own head.** Language models give overconfident numbers. Write sub-scores, run `vforecast.py`, report what it prints.
- **Forecast against the account's own baseline.** Raw view counts mostly reflect account size. "2x your usual" is the question that content can answer.
- **Judge before you know the outcome.** In a backtest, do not open `history.csv`, `key.json` or anything else with results until every judgment is written.
- **Say what you could not perceive.** You cannot hear audio. If there is no transcript, you do not know what is said. List it under `blind_spots` instead of guessing.
- **Log, resolve, show the scoreboard.** A forecast that is never scored teaches nothing.
- **Match words to numbers**, and always give the base rate next to the forecast:

| Probability | Say |
|---|---|
| 85% or more | very likely |
| 65 to 85% | likely |
| 35 to 65% | about even |
| 15 to 35% | unlikely |
| under 15% | very unlikely |

Never say a video "will go viral". Define the word instead: by default a **breakout** is 3x the account's baseline and **viral** is 10x. Use the user's own threshold if they have one (`--multiples 2,5,20`).

## Setup

The scripts sit next to this file. Below, `VF` means `python3 <this skill's folder>/scripts/vforecast.py` and `AV` means `python3 <this skill's folder>/scripts/analyze_video.py`.

1. Run `AV --check` once per session. ffmpeg, numpy and Pillow are required; install what is missing. For the spoken words, install a speech-to-text engine: `pip install sherpa-onnx` works in sandboxes that only reach package registries and GitHub (it fetches a Whisper model from GitHub on first use, which takes about a minute), and `pip install faster-whisper` gives exact word timings where Hugging Face is reachable. The script tries whatever is installed. For speech that is not English, pass `--language` (for example `ar` or `ro`) and `--whisper-model small`. If no engine can run, read burned-in captions off the frames and ask the user for the script or the first spoken line.
2. Pick the data folder and pass it as `--data` to every command. Use one folder per account and platform, because baselines differ between platforms.
   - A working directory that persists (a project folder, Claude Code): use `./virality-data/<account>-<platform>`.
   - A sandbox that is wiped after the chat: ask whether they have a `virality-data.zip` from last time and restore it with `VF import --data D --zip virality-data.zip`. Before you finish, run `VF export --data D --out virality-data.zip`, send them the file and ask them to bring it back next time. Without this the track record is lost.
3. `VF status --data D` shows what the folder already holds.

## Which mode

| The user... | Mode |
|---|---|
| has a finished video that is not posted yet | A. Pre-post forecast |
| has two or more versions of a video, hook or caption | B. Pick a variant |
| has only a script or an idea | C. Script check |
| has posted and has early numbers | D. Nowcast |
| reports the final numbers of a forecast video | E. Resolve and scoreboard |
| wants proof, a comparison with another tool, or can share past videos with their results | F. Backtest |

If they can share past videos with results, suggest F early. It is the single biggest accuracy upgrade, because it replaces assumed reliability with measured reliability and gives you anchors.

## A. Pre-post forecast

**A1. Intake.** Ask in one message, and only for what is missing:
- the video file (a link is not enough; you need the file to look at it)
- platform, and one line on who the audience is
- recent results: the last 10 to 30 view counts, newest first, or an analytics export (CSV). Only posts old enough for their numbers to have settled, about a week.
- caption and sound, if decided
- the horizon they care about (default: views after 7 days). Use the same horizon for history, forecast and final numbers.

Without history you can still forecast, but only as "where this would land among the account's posts", with no view numbers. Say so.

For paid ads, reach is bought, so views are not the question. Use rate targets instead: `hook_rate`, `completion_rate`, `share_rate`.

**A2. Baseline.**

```
VF profile --data D --platform tiktok --views "5300, 4100, 12000, 3900, ..."     # newest first
VF profile --data D --platform tiktok --history export.csv                        # columns are detected
```

If a column is not recognised, map it: `--map views="Video views"`. Check the printed date range and ordering, then tell the user their baseline and base rates in one line ("your typical post gets about 7,200 views; about 15% of your posts reach double that").

**A3. Look at the video.**

```
AV video.mp4 --out D/analysis/<video-id>
```

Then actually open `hook_sheet.jpg` and `timeline_sheet.jpg` and read `analysis.json` (transcript, pacing, motion, audio, flags). Open single frames from `frames/` when on-screen text is too small on the sheet. Every flag is a checkable fact that deserves a look; what it means for this video is your call. Do not judge from the file name or from the user's description of the video.

**A4. Check the context**, if you can search the web. Two to four searches for this platform and this month: is attention to the topic rising or fading, how are comparable recent videos doing, is this angle fresh or the tenth copy. Score each from -2 to +2 as the rubric describes, keep 0 when you found nothing either way, and put what you found in `context.sources`. With no search tool, set `"checked": false`. The user saying "this is trending" is a lead to check, not evidence.

**A5. Anchors**, when the library has them:

```
VF anchors --data D --target views
```

This prints past videos of this account with known results, weakest to strongest. Decide where the new video belongs among them and record that as `anchor_percentile`. Comparing against known cases is more reliable than rating in a vacuum. Leave it `null` when the command says there are not enough.

**A6. Judge.** Read `references/rubric.md` the first time in a session. Write the judgment to `D/judgments/<video-id>.json` in the format given in `references/data-formats.md`. Evidence first, number second, one dimension at a time.

If subagents with a fresh context are available and the user is fine with the extra time, have two of them judge independently, giving each only the analysis folder, the audience line and the rubric, and pass all judge files to `--judge`. Averaging independent judgments removes part of the noise. Re-scoring it yourself with your first scores in view does not, so skip this when subagents are not available.

**A7. Forecast.**

```
VF forecast --data D --judge D/judgments/<video-id>.json --target views --video-id <video-id>
```

Add more targets when the history has them: `--target views,share_rate,completion_rate`. Report in the format below.

**A8. Fixes.** Pick the one to three weakest sub-scores that an edit could realistically move. For each, name the edit and your honest estimate of the new sub-score, then let the script price it:

```
VF forecast --data D --judge D/judgments/<video-id>.json --set stop_power=5.5 --set hold=5
```

Present the change in odds as your estimate of the edit, not a measured effect. Most edits move the odds by a few points. Say that plainly; do not sell an edit as the difference between a flop and a hit.

**A9. Close the loop.** Tell the user what to send after posting: views at 1 hour, 3 hours and 24 hours (mode D), and the final count at the horizon (mode E).

## B. Pick a variant

1. Analyze each version (A3) and judge each separately (A6).
2. Compare them pairwise. For each pair, put the two hook sheets side by side and decide which one a cold viewer in the target audience is more likely to stop for and finish. Record the winner and a margin: 1 slight, 2 clear, 3 decisive. Do every pair twice with the order swapped and judge it fresh the second time. If your pick flips, record the flip; the script treats it as uncertainty.
3. `VF rank --data D --pairs pairs.json`
4. Report the order and the calibrated chance that the top pick really outperforms the runner-up. When the script says "toss-up" or "lean", say exactly that and recommend testing both with real viewers (as ad variants or as spaced posts). A coin flip described as a verdict is worse than no answer.

## C. Script check

Judge the script with the same rubric and set `"input": "script"` in the judge file, which makes the script discount the judgment. Score what a script cannot show (delivery, visuals, pacing) at 4 and list it under `blind_spots`. Give the forecast plus the specific lines to change, and run mode A when the video exists.

## D. Nowcast

```
VF snapshot --data D --video-id <video-id> --age-min 60 --views 1400 --shares 22 --likes 130
VF nowcast --data D --video-id <video-id>
```

Early velocity is the strongest predictor there is, so encourage users to send these numbers. The final-count estimate needs at least five past videos of this account that have both a snapshot at a similar age and a final count. Until then the command reports pace against the account's usual and how the rates compare. Ask for snapshots at 60, 180 and 1440 minutes on every post so this unlocks quickly.

## E. Resolve and scoreboard

```
VF resolve --data D --video-id <video-id> --views 18400 --shares 310 --completion-rate 0.31
VF scoreboard --data D
```

Tell the user how the post did against the forecast (inside the range or not, which of the odds events happened), then the running scoreboard: rank correlation with its interval, Brier score against the base rate, how often the 80% ranges held. Be plain about misses. One miss says little either way; the scoreboard is the evidence.

## F. Backtest and head-to-head

This measures how well the judging works on this account, and whether it beats another predictor on the same videos.

It needs past videos as files, their final numbers in the history CSV, and a `video_path` column pointing at each file. To compare with another tool, add its score for each video as a column, for example `higgsfield_score`.

```
VF profile --data D --history export_with_paths.csv
VF backtest-prepare --data D --max 30
```

Judge every item in `D/blind/queue.json` blind: you get the video, the platform and the caption, and nothing else. Write one judge file per item to `D/blind/judgments/<anon_id>.json`, with no context scores and no anchors. If subagents are available, one fresh subagent per video is the cleanest way; otherwise judge each video from its own analysis folder, without going back to earlier judgments. If you have already seen this account's numbers per video in this conversation, say that the backtest would be contaminated and run it in a fresh session.

```
VF backtest-score --data D --compare higgsfield_score --apply
```

Report this skill's rank correlation with its interval, the other tool's, the difference on the same videos with its interval, and the sample size. Under 30 videos, call it a first read. Do not claim a win that the interval does not support, in either direction.

`--apply` stores the measured reliability and turns the judged videos into the account's library, which unlocks anchors (A5) and scoring on the account's own scale. With 30 or more videos, `--stack higgsfield_score` fits a blend of both signals; later forecasts then take `--external higgsfield_score=62`. If the other tool adds signal, use it. The goal is the most accurate forecast, not loyalty to one method.

Other tools' scores come from the user. If such a tool is connected in this session, ask before running it, because it may spend their credits.

**Quick anchors without a full backtest.** If the user gives three to six past videos with their view counts, judge each and add it:

```
VF library-add --data D --judge j.json --video-id <name> --views 41000
```

These serve as anchors only. Their results were known when you judged them, so they do not count toward measured reliability.

## Report format

Keep it short and scannable. Numbers come from the script output, unchanged.

```
**Forecast: <video> on <platform>, views after 7 days**

| | This video | Your usual |
|---|---|---|
| Beats your baseline (7,190) | 63% | 55% |
| 2x or more | 19% | 15% |
| 3x or more (breakout) | 9% | 7% |
| 10x or more (viral) | 1% | 0.5% |

Likely range: 3,300 to 17,000 views (median 8,600).
Confidence: low. <The main reason, in plain words.>

**Why:** one line per sub-score with the evidence and timestamps.
**Change first:** one to three edits with the what-if odds.
**Could not check:** the blind spots.
**Next:** post, send views at 1h / 3h / 24h, then the final count on day 7.
```

When confidence is low, lead with the comparison to the usual odds ("slightly better than your typical post") instead of the percentages alone, and say what would raise confidence (a backtest, more resolved forecasts).

## When the user asks how accurate this is

Answer from `VF scoreboard` or the last backtest if they exist: the rank correlation with its interval and the sample size. If nothing is scored yet, say that reliability is an assumed starting value, explain the ceiling using `references/evidence.md`, and offer mode F. Do not claim this beats any named tool unless a head-to-head on this account's videos showed it.

## Files

- `scripts/analyze_video.py`: frames, pacing, audio and transcript from a video file.
- `scripts/vforecast.py`: baselines, forecasts, ranking, nowcasts, scoring, backtests. `-h` on any subcommand lists its options; `selftest` checks the statistics on simulated accounts.
- `references/rubric.md`: how to judge. Read before the first judgment of a session.
- `references/data-formats.md`: the judge file, the pairs file, history columns, the data folder.
- `references/methodology.md`: the statistics and their assumptions. Read when the user asks how the numbers are made.
- `references/evidence.md`: what research says is and is not predictable. Read when the user asks about accuracy or limits.
