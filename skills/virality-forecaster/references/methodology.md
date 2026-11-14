# Methodology

How `vforecast.py` turns a judgment into numbers, and what each step assumes. Read this when a user asks where a number comes from.

## Contents

1. Relative performance
2. The account's own distribution
3. From sub-scores to one signal
4. From signal to forecast
5. Reliability
6. Ranking variants
7. Nowcasting
8. Scoring and head-to-head tests
9. What simulation shows
10. Assumptions and limits

## 1. Relative performance

Raw counts mostly measure account size, so every outcome is expressed relative to the account's recent norm.

- Each value is put on a scale where "relative" means a difference: `log10(value + 1)` for counts, `log10(value)` for ratios such as shares per view, and the logit for rates between 0 and 1.
- A post's baseline is the median of the 10 posts before it. Early posts, which do not have 10 posts behind them, borrow the posts right after them to fill the window, so every baseline rests on the same number of posts.
- Relative performance `rp` is the value minus its baseline on that scale. For counts, `rp = 0.30` means twice the baseline and `rp = 1` means ten times.
- The baseline used for a new forecast is the median of the last 10 settled posts. Posts younger than 7 days are left out because their numbers are still growing; posts recorded with `resolve` always count.

## 2. The account's own distribution

The spread of past `rp` values is the reference class: it gives the base rates ("15% of your posts reach 2x") before anything is known about the new video.

- The distribution is kept as an empirical quantile function. The i-th smallest of n past values sits at probability i/(n+1), which makes "a new post lands below the i-th smallest" correct on average for any distribution.
- With few posts the empirical shape is noisy, so it is blended with a two-piece normal curve (separate spread above and below the median, because view counts are skewed). The data gets weight n/(n+8).
- Beyond the best and worst posts ever observed, the curve continues with a normal tail using the upper or lower spread. This is what gives a non-zero chance of 10x to an account that has never had one.

## 3. From sub-scores to one signal

- A sub-score maps to a bell-curve position through its percentile definition: 1, 2, 3, 4, 5, 6, 7 become -2.05, -1.28, -0.52, 0, +0.52, +1.28, +2.05, with straight lines in between.
- The composite for a target is a weighted mean of those positions:

| Target | stop_power | hold | share_save | comment_trigger | rewatch_loop | audience_fit |
|---|---|---|---|---|---|---|
| views, likes | .25 | .25 | .20 | .10 | .10 | .10 |
| shares | .15 | .15 | .50 | | .10 | .10 |
| comments | .15 | .15 | | .50 | | .20 |
| saves | | .20 | .60 | | | .20 |
| share_rate | | .15 | .70 | | | .15 |
| engagement_rate | | .20 | .30 | .30 | | .20 |
| hook_rate | .75 | | | | | .25 |
| completion_rate | .10 | .60 | | | .15 | .15 |
| avg_watch_pct | .10 | .60 | | | .20 | .10 |

  These weights are design choices, not fitted values. A backtest prints the rank correlation of each sub-score with real outcomes, which shows whether they suit a given account.
- A mean of several correlated scores varies less than a single score, so the composite is rescaled to unit spread assuming an average correlation of 0.5 between sub-scores.
- **Own scale.** Once the account's library holds 12 or more judged videos, the composite is instead converted to its percentile among those videos. This removes the judge's general leniency or harshness and compares the video with this account's usual output, which is what the baseline measures.
- **Anchors.** If the judge placed the video among past videos with known results, that percentile is converted to a bell-curve position and averaged with the composite.
- **Context.** The three context scores (each -2 to +2) are summed and scaled so that +2 on all three equals a top-10% tailwind. The result is added with a gain of 0.5 for views, likes, shares and comments, 0.25 for saves and the engagement ratios, and 0 for retention rates.
- **Several judges.** Sub-scores are averaged per dimension before anything else.
- The final signal `z` is limited to the range -2.5 to +2.5.

## 4. From signal to forecast

The signal and the outcome are modelled as jointly normal with correlation `r`, the judge's reliability, after both are put on a bell-curve scale. Given the signal, the outcome's position is then normal with mean `r * z` and variance `1 - r^2`.

- The chance of reaching a threshold is the upper tail of that distribution beyond the threshold's position in the account's distribution.
- The range comes from mapping the 10th, 25th, 50th, 75th and 90th percentiles of that distribution back through the account's quantile function.
- With `r = 0` the forecast equals the account's base rates exactly. With `r = 0.25`, a top-10% signal moves the expected result only from the 50th to about the 63rd percentile. This is regression to the mean, applied on purpose: a judgment gets exactly as much say as it has earned.
- A consequence worth knowing: when reliability is high, a mildly positive signal can lower the chance of an extreme hit below the base rate, because the forecast has become narrower around "somewhat above average".

## 5. Reliability

- Starting values are assumptions: 0.25 for counts and engagement ratios, 0.35 for retention measures (hook rate, completion rate, average watch share). They are deliberately modest. Trained models reach rank correlations around 0.6 to 0.7 on large datasets (see `evidence.md`), but those models learned from over a hundred thousand labelled videos and predict across creators. An untrained judge predicting how one creator's video deviates from that creator's own norm should be assumed much weaker until measured.
- The starting value counts as 20 observations. Measured rank correlations from blind backtests and from resolved live forecasts are averaged with it, weighted by sample size, on the Fisher scale: `r = tanh((20 * atanh(r0) + n_b * atanh(r_b) + n_l * atanh(r_l)) / (20 + n_b + n_l))`. A source needs at least 5 scored videos to count. The result is limited to 0 to 0.9.
- Judgments made from a script or storyboard are multiplied by 0.6, another assumption.
- Underestimating reliability costs sharpness but keeps the odds honest. Overestimating it produces confident forecasts that fail, which is the worse error, so every default leans low.

## 6. Ranking variants

Pairwise judgments are fitted with a Bradley-Terry model (MM algorithm). A margin of 1, 2 or 3 counts as 0.62, 0.75 or 0.88 of a win, a tie as half. Each item also plays one drawn game against a phantom average item, which keeps strengths finite when an item wins everything. The judge's preference `p` for the top item over the runner-up becomes a calibrated chance `Phi(r * Phi^-1(p) / sqrt(1 - r^2))`: with the starting reliability of 0.25, a 68% preference becomes about 55% and even an 88% preference only 62%. The script calls 65% or more a clear pick, 55 to 64% a lean, and anything lower a toss-up. Using the reliability of single-video judgments for comparisons between variants is an assumption; variants of one idea differ less than different videos do, so it is unlikely to be too cautious.

## 7. Nowcasting

Early and final popularity are close to linearly related on a log scale, which is the basis of most post-publish prediction.

- From this account's past videos that have a snapshot at a similar age (within a factor of 1.6) and a final count, the script fits `log10(final + 1) = a + b * log10(early + 1)`.
- With fewer than 10 such videos the slope is fixed at 1 (a constant multiplier); with more it is estimated and shrunk toward 1.
- The range is a Student-t prediction interval, so it is wide when few past videos exist.
- If a pre-post forecast exists for the video, the two estimates are combined by precision on the log scale. The early signal usually gets nearly all the weight.
- The forecast never goes below the views already counted.

## 8. Scoring and head-to-head tests

- **Ranking skill**: Spearman rank correlation between the signal and realised relative performance, with a 95% bootstrap interval (2000 resamples), and pairwise accuracy (how often the higher-rated of two videos did better).
- **Calibration**: Brier score of each probability against what happened, compared with the Brier score of always quoting the base rate. Skill above 0 means the forecast added information.
- **Coverage**: how often the 80% range contained the outcome. Far below 80% means overconfidence.
- **Head-to-head**: for another predictor's scores on the same videos, the difference in rank correlation with a paired bootstrap interval. A difference whose interval includes 0 is not a win.
- **Stacking**: with 30 or more videos, a ridge regression on the normal scores of the judge signal and the external scores predicts the normal score of the outcome. Its leave-one-out rank correlation is reported and used as the reliability of the blend.

## 9. What simulation shows

`vforecast.py selftest` and `tests/calibration_sim.py` in the repository simulate accounts whose true distribution is known, give the forecaster a signal of known quality, and check the output against what happens. Results from `calibration_sim.py` (400 accounts and 4,000 forecasts per row; the signal's true correlation with quality is 0.5, and its reliability is measured the way a backtest would measure it, at about 0.44 to 0.45):

| Tail shape | Posts of history | 80% range held | P(2x): forecast / observed | P(3x): forecast / observed | P(10x): forecast / observed | Brier skill, 2x |
|---|---|---|---|---|---|---|
| normal | 8 | 83.0% | 23.1% / 20.9% | 13.1% / 10.4% | 1.8% / 0.5% | +0.11 |
| normal | 30 | 80.3% | 21.5% / 21.8% | 11.1% / 10.8% | 1.1% / 0.4% | +0.13 |
| normal | 80 | 82.8% | 21.5% / 21.9% | 10.7% / 9.6% | 0.8% / 0.4% | +0.12 |
| skewed | 8 | 83.5% | 24.8% / 22.6% | 15.7% / 13.4% | 3.4% / 2.1% | +0.11 |
| skewed | 30 | 81.2% | 23.4% / 23.8% | 14.0% / 14.0% | 2.8% / 2.0% | +0.13 |
| skewed | 80 | 82.7% | 23.5% / 23.9% | 13.7% / 13.1% | 2.5% / 1.9% | +0.13 |
| occasional breakouts | 8 | 82.2% | 20.0% / 16.2% | 11.5% / 7.9% | 3.5% / 2.9% | +0.10 |
| occasional breakouts | 30 | 80.1% | 17.3% / 17.2% | 9.3% / 8.6% | 3.3% / 3.0% | +0.12 |
| occasional breakouts | 80 | 82.9% | 17.0% / 16.8% | 8.6% / 7.7% | 3.3% / 2.6% | +0.11 |

Reading: the 80% ranges hold 80 to 84% of the time from 8 posts of history upward. With 30 or more posts the odds of 2x and 3x are within about a point of what happens; with only 8 posts they run two to four points high. The odds of 10x run high for accounts whose results have thin tails (about 1% forecast against 0.4% observed), because the method always leaves room beyond the best post seen so far. A judge with no signal reproduces the base rates exactly (Brier skill 0.000).

This validates the arithmetic under the model's own assumptions. It says nothing about how well any judge reads a video; only a backtest on real videos does.

## 10. Assumptions and limits

- **One reliability number per target.** The model assumes the judge is equally good at spotting flops and hits. If it is better at one, the tails will be off even when the overall ranking is good.
- **Weights and starting values are assumptions** until a backtest replaces or checks them.
- **The baseline lags.** A median of the last 10 posts reacts slowly to a step change, for example the follower jump after a breakout.
- **Platforms change.** A history from before a large change in a platform's distribution describes a different world.
- **One horizon.** Late bloomers that take off after the horizon are scored as what they were at the horizon.
- **Small samples.** With 20 scored videos a rank correlation of 0.4 has an interval of roughly 0 to 0.7. Report the interval.
- **Perception.** The judge sees frames, a transcript and audio statistics. It does not hear the sound, see the competing feed, or know the platform's current distribution rules.
- **Backtest contamination.** If the judge has seen a video's results, or the video itself is well known, the backtest overstates reliability. Use the account's own videos and judge them blind.
