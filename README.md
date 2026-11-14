# Ali Yassine Virality Forecaster

Created by Ali Yassine.

A Claude skill that forecasts how a short-form video will perform, as honest odds against your own track record, then checks itself against what really happened.

Works for TikTok, Instagram Reels, YouTube Shorts, Snapchat Spotlight and social video ads.

## Why not just a virality score?

A score computed from the clip alone misses most of what decides how a video does:

- **Identical content gets very different results.** In an online music market with 14,341 participants, success was partly luck: the best songs rarely did poorly and the worst rarely did well, but anything else could happen (Salganik et al., 2006). Identical photos reposted on Facebook reached very different sizes (Cheng et al., 2014).
- **Even the best trained models only get part of it.** Models built on datasets of 14,000 to 120,000 labelled videos reach rank correlations of about 0.6 to 0.7 with real outcomes (Sun et al., 2025; Heo & Lee, 2026). On Twitter, the best models explained less than half of the variance in how far posts spread, even with rich data on users and content (Martin et al., 2016).
- **Early numbers beat content.** After seeing only the first five reshares, whether a Facebook cascade would double was predicted correctly 79.5% of the time, against 50% by chance (Cheng et al., 2014).

So instead of one number, this skill gives you:

| Typical predictor | Virality Forecaster |
|---|---|
| One score from the clip | Odds of beating your usual, and of reaching 2x, 3x or 10x it |
| The same answer for every account | Measured against your own history and base rates |
| No way to check it | Logs every forecast and scores it: rank correlation, Brier score, range coverage |
| Stops when you post | Updates from your first-hour numbers |
| A black box | Every number comes from a documented script; the judgment is written down with evidence |

## What a forecast looks like

Real output on the sample account in `examples/` (a fictional coffee creator with 40 past posts):

```
FORECAST  views  video: draft-moka-pot-myth
  signal: content z=+0.68, context +0.21 -> z=+0.78  (scored against the general scale; 1 judge)
  reliability used: r=0.25  [prior]
  after regression to the mean: expected near the 58th percentile of this account's posts

  P(beats the current baseline) =   63%   (base rate 55%)
  P(lands in this account's top quarter) =   31%   (base rate 25%)
  P(reaches 2x the baseline or more) =   19%   (base rate 15%)
  P(reaches 3x the baseline or more) =    9%   (base rate 7%)
  P(reaches 10x the baseline or more) =    1%   (base rate 0.5%)
  likely range (80%): 3,300 to 17,000 views, median 8,600  (baseline 7,190)

  confidence: LOW
    - reliability is mostly a prior (0 scored forecasts on this account; 15+ needed)
```

The odds move only a little away from the base rates because the judging has not been measured on this account yet. That is deliberate: a forecaster that has not proven itself should not sound sure. As forecasts are resolved, or after a backtest, the measured reliability replaces the assumed one.

## Does it beat Higgsfield's Virality Predictor?

That depends on your videos, and the skill can measure it. Give it about 30 of your past videos with their final views and Higgsfield's score for each. Claude judges them blind (without seeing the results) and the script reports both tools' rank correlation with your real results, plus the difference with a confidence interval. If Higgsfield's score turns out to carry information, the skill blends it in, so you keep the best of both.

What is known as of 14 November 2026: Higgsfield's product page publishes no accuracy figures. One independent study of an open brain-response model (TRIBE) on 48 popular YouTube videos found no significant link with replays, views or likes (Sahu & Pandey, 2026); that study did not test Higgsfield's product. Details and sources are in [`evidence.md`](skills/virality-forecaster/references/evidence.md).

This project is not affiliated with Higgsfield.

## Install

**[Download the Claude-ready skill ZIP](downloads/ali-yassine-virality-forecaster-claude-skill.zip?raw=true)**

**Claude Code**

```
/plugin marketplace add aliameryassine-bit/Ali-Yassine-Virality-Forecaster
/plugin install virality-forecaster@virality-forecaster
```

Or copy `skills/virality-forecaster` into `~/.claude/skills/` (all your projects) or `.claude/skills/` (one project).

**Claude apps (web and desktop)**

1. [Download the Claude-ready skill ZIP](downloads/ali-yassine-virality-forecaster-claude-skill.zip?raw=true). Do not use GitHub’s **Code → Download ZIP**, which contains the full repository.
2. In Claude, go to Customize > Skills, click **+**, then **Create skill** > **Upload a skill**, and upload the skill ZIP without extracting it.

Code execution needs to be on (Settings > Capabilities). See Anthropic's guide: [Use skills in Claude](https://support.claude.com/en/articles/12512180-use-skills-in-claude).

**Requirements**

- Python 3.9 or newer, with `numpy` and `Pillow`
- `ffmpeg` and `ffprobe`
- Optional, to read the spoken words: `pip install sherpa-onnx` (downloads a Whisper model from GitHub on first use) or `pip install faster-whisper` (downloads from Hugging Face)

Claude installs missing Python packages itself when it can.

## Use it

Just talk to Claude. For example:

- "Will this go viral? My last 10 TikToks got 5300, 4100, 12000, ... views." (attach the video)
- "Which of these two hooks should I post?" (attach both)
- "Here's my script for tomorrow's Reel. What will hurt it?"
- "Posted an hour ago, 1.4K views and 22 shares. Is it taking off?"
- "It finished the week at 18,400 views." (scores the forecast)
- "Here are my last 30 videos and their views. How accurate are you, compared with Higgsfield?"

The skill keeps a small data folder per account (`virality-data/`). In sandboxes that are wiped after each chat, it exports the folder as a zip; bring it back next time so your track record carries over.

## How it works

1. **Perception.** `analyze_video.py` turns the video into evidence Claude can judge: a sheet of the first three seconds at quarter-second steps, a timeline sheet, cuts and jump cuts, motion, when sound starts, loudness, and a transcript.
2. **Judgment.** Claude scores six dimensions (stop power, hold, share/save, comment trigger, rewatch, audience fit) on a 1 to 7 scale anchored to percentiles, writing the evidence before each score. Optional: a web check of the topic's momentum, comparison against your past videos with known results, and independent judges averaged together.
3. **Calibration.** `vforecast.py` turns the judgment into odds against your own distribution of results relative to your rolling baseline, pulled toward your base rates by how reliable the judging has proven to be.
4. **Nowcast.** After posting, your early views are compared with how your past videos grew, and the forecast is updated.
5. **Scoreboard.** Every forecast is scored against the outcome. The measured reliability feeds back into step 3.

Claude does the judging; the script does all the arithmetic, so no probability comes from the model's intuition. The full method and its assumptions are in [`methodology.md`](skills/virality-forecaster/references/methodology.md).

## How accurate is it?

- **The arithmetic is checked.** On 400 simulated accounts per setting, the 80% ranges contained the outcome 80 to 84% of the time, and the odds of a 2x or 3x breakout were within about a point of what happened once an account had 30 or more posts (two to four points high with only 8). Run `python tests/calibration_sim.py` to reproduce this.
- **The judging is measured, not assumed.** It starts with a deliberately low assumed reliability (a correlation of 0.25), so early forecasts stay close to your base rates and are not confidently wrong. Each backtest and each resolved forecast replaces that assumption with a measurement on your own account.
- **Nobody can promise virality.** The aim is the best-calibrated odds the evidence allows, and an honest record of how good they turned out to be.

## Your data

Everything is stored as plain files in a folder you choose. The scripts make no network calls except to download a speech-to-text model the first time. Claude sees the frames and transcript, as with any file you share with it, and runs a few web searches when it checks whether a topic is trending.

## Development

```
python tests/run_tests.py                                         # 41 end-to-end checks on a synthetic account
python tests/calibration_sim.py                                   # calibration on simulated accounts
python skills/virality-forecaster/scripts/vforecast.py selftest   # quick statistical self-test
```

Skill test cases for `claude plugin eval` are in `skills/virality-forecaster/evals/`.

To publish a release, tag it (`git tag v0.1.0 && git push --tags`). The release workflow runs the tests and attaches `virality-forecaster.zip`.

```
.claude-plugin/          plugin and marketplace manifests (Claude Code)
skills/virality-forecaster/
  SKILL.md               instructions Claude follows
  scripts/               analyze_video.py, vforecast.py
  references/            rubric, data formats, methodology, evidence
  evals/                 test cases
examples/                sample history, judge file and pairs file
tests/                   end-to-end tests and calibration simulation
```

## Contributing

The most useful contribution is a backtest result: rank correlation, number of videos, platform and niche (no personal data needed). It shows where the rubric works and where it does not. Changes to the rubric or the weights should come with backtest evidence.

## References

Full list with links in [`evidence.md`](skills/virality-forecaster/references/evidence.md#9-references).

## License

MIT
