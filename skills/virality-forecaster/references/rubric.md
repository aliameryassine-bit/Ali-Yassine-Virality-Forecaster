# Judging rubric

Read this before the first judgment in a session. Your sub-scores are the only input the forecast gets from the video itself, so the forecast is exactly as good as the care taken here.

## Contents

1. The scale
2. Procedure
3. The six dimensions
4. Context scores
5. Anchored placement
6. Pairwise comparison of variants
7. Biases to guard against

## 1. The scale

Every dimension is scored from 1 to 7 (half points allowed), against **typical videos of this kind on this platform**: same niche, same format, same length class.

| Score | Meaning |
|---|---|
| 1 | bottom 2% |
| 2 | bottom 10% |
| 3 | below typical (around the 30th percentile) |
| 4 | typical |
| 5 | above typical (around the 70th percentile) |
| 6 | top 10% |
| 7 | top 2% |

Most scores should be 3, 4 or 5. A 6 needs a specific feature you can name that nine in ten comparable videos lack. A 7 is a video you would use as a teaching example. By definition half of all videos are below typical on any dimension; if you rarely score below 4, you are grading on effort, not on rank.

Why percentiles: the script converts each score to a position on a bell curve, weights the dimensions for the target, and then pulls the result toward the account's base rate by the judge's measured reliability. That only works if a 6 means "top 10%" every time.

## 2. Procedure

For each dimension, in this order:

1. Write the evidence: what you see or read, with timestamps. Facts only.
2. Write what a typical video of this kind does on this dimension.
3. Score the gap between the two.

Finish all six evidence notes before you score any dimension, and do not move one score because of another. If you cannot perceive what a dimension depends on (no audio, no transcript, script only), score that part 4 and add a line to `blind_spots`. A guess written as a score is the fastest way to make the forecast worse.

## 3. The six dimensions

### stop_power (first two seconds)

Question: in a feed, with no context and the thumb already moving, does this stop the scroll?

Look at: the hook sheet from 0.00s to 2.00s, the first spoken words (`transcript.words_first_3s`; word times are approximate when `transcript.timing` says segment-level), when sound starts, motion in the first second, the flags `black_start`, `static_start`, `dead_air_start`, `late_first_word`.

Raises it:
- something is already happening in frame one: motion, a face mid-expression, an object in a state that needs explaining
- on-screen text that can be read in under a second and opens a question
- first words that state a claim, a stake or address the viewer directly
- sound from the first frame
- a subject that reads clearly at phone size

Lowers it:
- a black or fade-in start, a logo, a title card
- a greeting or throat-clearing before the point
- a slow establishing shot
- text that is too small or too long to read in a second
- silence, or the subject only becoming clear after two seconds

Reference points: 2 = a static title card in silence. 4 = a clear subject and speech within a second, nothing surprising. 6 = frame one is already the most interesting moment, and the words or text open a loop.

### hold (three seconds to the end)

Question: once stopped, do they stay to the end?

Look at: the timeline sheet, how often the picture changes (`pacing.changes_per_10s`), the longest stretch without a change (`pacing.longest_segment_s`), `frozen_segments`, `silent_gaps`, the structure of the transcript, the duration.

Raises it:
- a promised payoff that is held back until late, with visible progress toward it
- new information or a visual change every few seconds
- a structure that escalates
- a tight edit with no repeated points
- length that matches the content
- captions that keep sound-off viewers

Lowers it:
- the payoff is given away early and nothing new follows
- long static or silent stretches
- recap, filler, a middle that sags
- an outro or call to action that drags after the payoff
- running long relative to what it delivers

Reference points: 2 = the point is made in five seconds and the video runs for forty. 4 = keeps moving, with one slow stretch. 6 = every few seconds earns the next few, and the best moment is last.

### share_save

Question: would a viewer send this to a specific person, or save it?

Raises it:
- it is usable: steps, a list, a reference worth keeping
- it is aimed at someone you can name ("send this to the friend who...")
- it produces an activated feeling: amusement, awe, surprise, warmth, indignation
- it makes the sender look informed or funny
- it shows something new

Lowers it:
- informational with no feeling and nothing to keep
- early or heavy branding, a sales pitch
- references only the creator understands
- pleasant but flat

Research backing for this dimension is in `evidence.md`: content that evokes high-arousal emotions is shared more, and for video ads, emotional content is shared more than informational content while early brand prominence reduces sharing.

Reference points: 2 = an announcement. 4 = mildly useful or mildly funny. 6 = you can name who would receive it and what the message would say.

### comment_trigger

Question: does a viewer have something to say?

Raises it: a claim people will dispute or correct, a question or a choice, a confession people recognise, an unresolved detail people will point at, an invitation to share their own case.

Lowers it: complete and uncontroversial, nothing to add.

Bait that works by annoying people can lift comments and hurt the account. Score what you see, and flag the risk in your notes instead of recommending it.

Reference points: 2 = nothing to add. 4 = a few people will share their own version. 6 = the video takes a side people care about, or leaves a gap they will rush to fill.

### rewatch_loop

Question: will people watch it more than once?

Look at: the last-frame-versus-first-frame similarity in `analysis.json`, duration, density.

Raises it: the end flows into the start, a reveal so quick it is worth a second look, detail that passes faster than it can be read once, a short runtime with the payoff at the very end.

Lowers it: a long linear explanation, a hard ending (outro, logo), nothing new on a second viewing.

Reference points: 2 = a 50-second explainer with an outro. 4 = short, but once is enough. 6 = a seamless loop or a reveal people will replay.

### audience_fit

Question: is this what this account's audience, and this platform's viewers in this niche, come for?

Look at: the stated audience, captions of past posts if the history has them, platform norms (vertical framing, native look, length, language, captions).

Raises it: squarely in the account's established topic and tone, the audience's own vocabulary, native format.

Lowers it: an off-niche topic, a horizontal video with bars, a language or cultural mismatch, ad-like polish where the niche expects raw footage.

Something new for the account can go either way. Score the fit as it is and mention the upside in your notes.

Reference points: 2 = a different topic in a different format. 4 = on topic, unremarkable. 6 = exactly what this audience follows the account for, in the form they expect.

## 4. Context scores

Three scores from -2 to +2. They describe the moment, not the video. **The default is 0.** Move a score only when you can point to something you found, and list it in `context.sources`.

| Key | +2 | 0 | -2 |
|---|---|---|---|
| `topic_momentum` | attention to the topic, person, product or event is clearly rising or peaking this week | steady, or no evidence | clearly fading or already over |
| `related_activity` | several comparable recent videos (same format, sound or angle) clearly beat their creators' norm | unknown or mixed | comparable recent videos are underperforming |
| `freshness` | a new angle with little direct competition | ordinary | a late copy in a saturated wave |

Context only moves count targets (views, likes, shares, comments, saves), and only by half as much as the content does. Rates such as completion are judged on content alone.

## 5. Anchored placement

When `vforecast.py anchors` prints past videos of this account with their real results, compare the new video with each of them: would it stop more people than A3, hold them better than A4? Then set `anchor_percentile` to the percentile of the account you would expect it to reach, using the percentiles printed next to the anchors. This is a single holistic call and it is averaged with the rubric composite. Keep it independent: decide it from the comparison, not by converting your sub-scores.

## 6. Pairwise comparison of variants

For each pair, with both hook sheets open:

1. Which one would a cold viewer in the target audience be more likely to stop for and finish?
2. How clear is it: 1 slight, 2 clear, 3 decisive? Use 3 rarely.
3. Compare again with the order swapped, as if for the first time. If you flip, record what you decided the second time. The script counts a flip as uncertainty, which is correct.

Variants usually differ in one thing. Judge that one thing in context (does the new hook still set up the same payoff?) and do not reward a variant for being the one presented first or described more enthusiastically.

## 7. Biases to guard against

- **Polish is not a dimension.** Production value is not scored. In many niches rough, native-looking footage does better.
- **Your taste is not the audience's.** Judge for the stated audience.
- **Halo.** A strong hook makes everything after it look better. That is why evidence for all six comes before any score.
- **The user's hopes.** Their investment in the video is not evidence. Neither is yours in being encouraging.
- **Unknown is 4, plus a blind spot.** Never fill a gap with a plausible guess.
- **Length.** Do not penalise length. Penalise length beyond the payoff.
- **AI-generated footage.** Judge it as the audience will see it. Note visible artifacts under `stop_power` or `hold` if they would distract; do not score the method.
- **Outcome knowledge.** If you know how a video did, your scores will drift toward it. That is why backtests are blind and why library videos added with known results do not count toward reliability.
