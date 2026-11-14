# Data formats

## Contents

1. Judge file
2. Pairs file (variant ranking)
3. History CSV
4. Targets
5. The data folder

## 1. Judge file

One JSON file per judged video. Only `subscores` is required; everything else makes the forecast, the library and the report better.

```json
{
  "video_id": "draft-moka-pot-myth",
  "input": "video",
  "platform": "tiktok",
  "audience": "home coffee beginners who own basic gear",
  "description": "22-second talking-head plus b-roll: claims the burnt taste is a heat problem, shows the fix, ends on a taste test.",
  "hook_summary": "0.0s close-up of a sputtering moka pot, text 'You're burning it', first words 'Your moka pot isn't bad, you are'.",
  "subscores": {
    "stop_power": 5.5,
    "hold": 4.5,
    "share_save": 5,
    "comment_trigger": 5,
    "rewatch_loop": 3,
    "audience_fit": 6
  },
  "reasons": {
    "stop_power": "Motion and sound from frame one, readable 3-word text, a direct challenge. First frame is dark.",
    "hold": "Three clear steps, taste test held to the end, but 6 seconds of b-roll with nothing new at 0:09."
  },
  "context": {
    "checked": true,
    "topic_momentum": 0,
    "related_activity": 1,
    "freshness": 0,
    "notes": "Two mid-size creators' moka pot fix videos did well this month; the angle is common.",
    "sources": ["platform search 'moka pot burnt', sorted by recent"]
  },
  "anchor_percentile": null,
  "flags": ["black_start"],
  "blind_spots": ["sound choice unknown: judged on the voice track only"],
  "fixes": [
    {"change": "Cut the b-roll at 0:09 to 2 seconds", "moves": "hold", "from": 4.5, "to": 5.5}
  ]
}
```

| Field | Notes |
|---|---|
| `video_id` | Used to log, resolve and find the video later. Keep it short and stable. |
| `input` | `video` (default), `script` or `storyboard`. Anything but `video` discounts the judgment's reliability. |
| `description`, `hook_summary` | Stored in the library card so the video can serve as an anchor later. Write them so a judge who has not seen the video can picture it. |
| `subscores` | 1 to 7, half points allowed, as defined in `rubric.md`. Missing dimensions are skipped and the weights are renormalised. |
| `reasons` | Evidence per dimension. Not used by the script; used by you in the report. |
| `context` | `checked: false` (or omitted) means context is treated as neutral and listed as a blind spot. Scores are -2 to +2. |
| `anchor_percentile` | 0 to 100, or `null`. Only after comparing with the output of `vforecast.py anchors`. |
| `flags` | Flag ids from `analysis.json` that you confirmed matter. |
| `blind_spots` | What you could not perceive. Shown in the confidence note. |
| `fixes` | Your proposed edits. Not used by the script; price them with `forecast --set`. |

Several judge files passed to `forecast --judge a.json b.json c.json` are averaged per dimension. Use this only for independent judges.

For a blind backtest, add `"anon_id": "b007"` and leave out `context` and `anchor_percentile`.

## 2. Pairs file

```json
{
  "items": ["hook-A", "hook-B", "hook-C"],
  "comparisons": [
    {"a": "hook-A", "b": "hook-B", "winner": "hook-B", "margin": 2},
    {"a": "hook-B", "b": "hook-A", "winner": "hook-B", "margin": 1},
    {"a": "hook-A", "b": "hook-C", "winner": null}
  ]
}
```

`margin` is 1 (slight), 2 (clear) or 3 (decisive). `winner: null` or `"tie"` records a tie. List each pair twice, once in each order.

## 3. History CSV

One row per published post. Any analytics export works; headers are matched case-insensitively against these names:

| Canonical | Recognised headers |
|---|---|
| `video_id` | video_id, id, video id, post id |
| `posted_at` | posted_at, date, posted, post time, publish time, published, created, create time, time, post date, publish date, date posted |
| `platform` | platform |
| `duration_s` | duration_s, duration, video duration, length, video length (seconds or m:ss) |
| `views` | views, video views, plays, play count, view count, video plays |
| `likes` | likes, like count, hearts |
| `comments` | comments, comment count |
| `shares` | shares, share count, sends |
| `saves` | saves, bookmarks, favorites, save count |
| `avg_watch_s` | avg_watch_s, average watch time, avg watch time, average view duration |
| `completion_rate` | completion_rate, completion rate, watched full video, watched full video (%), full watch rate |
| `hook_rate` | hook_rate, hook rate, 3s view rate, 3-second view rate, stayed to watch, viewed vs swiped away, thumbstop rate |
| `caption` | caption, title, description, video title, post caption |
| `video_path` | video_path, file, path, video file, filename |

Anything else is carried through untouched, which is how another predictor's score gets in: add a column such as `higgsfield_score`.

Rules:
- Map an unrecognised header with `--map views="Vues de la vidéo"`.
- Numbers may be written as `12500`, `12,500` or `12.5K`. Rates may be `0.31`, `31` or `31%`.
- With a date column, rows are sorted by date. Dates that fit two formats (03/04/2026) trigger a warning; fix with `--date-format %m/%d/%Y`.
- Without a date column, rows are assumed newest first; pass `--order oldest-first` otherwise.
- Posts younger than 7 days are kept but left out of the baseline, because their numbers are still growing. Change with `--min-age-days`.
- Rows recorded with `resolve` survive a re-import unless the new file has the same `video_id`. If the new export contains those posts under other ids, re-import with `--drop-resolved`.

## 4. Targets

Pass one or several to `forecast --target`, comma-separated. A target needs at least 3 history posts with the columns it uses.

| Target | Meaning | Needs |
|---|---|---|
| `views` | view count at the horizon | views |
| `likes`, `comments`, `shares`, `saves` | counts at the horizon | that column |
| `share_rate` | shares / views | shares, views |
| `engagement_rate` | (likes + comments + shares + saves) / views | views and at least one of the four |
| `hook_rate` | share of viewers who stay past the opening, as the platform reports it | hook_rate |
| `completion_rate` | share of viewers who watch to the end | completion_rate |
| `avg_watch_pct` | average watch time / duration | avg_watch_s, duration_s |

Count targets get the "2x / 3x / 10x the baseline" questions. Rates and ratios get "beats the baseline" and "top quarter" only.

## 5. The data folder

```
virality-data/<account>-<platform>/
  history.csv          normalised history, including posts added by `resolve`
  profile.json         baselines and the spread of past results per target
  predictions.jsonl    every logged forecast and nowcast, with its outcome once resolved
  calibration.json     measured reliability (backtest, live) and the fitted stack, if any
  snapshots.csv        early metrics logged with `snapshot`
  library/<video_id>/card.json   judged videos: description, sub-scores, outcome
  judgments/           your judge files (a convention, not required)
  analysis/<video_id>/ output of analyze_video.py (a convention, not required)
  blind/               backtest queue, key and blind judgments
```

Everything is plain text and stays on the machine where it was created. `export` zips the folder without images and video; `import` restores it.
