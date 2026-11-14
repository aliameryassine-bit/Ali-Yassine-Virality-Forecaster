# What the evidence says

Use this when a user asks how accurate a prediction can be, why the forecast is so cautious, or how this compares with a tool that prints a virality score. Numbers below are from the cited papers; check the source before quoting them further.

## Contents

1. Short version
2. A large part of the outcome is not in the content
3. What can be predicted before posting
4. What early numbers add
5. What makes people share
6. Predicted brain response as a virality signal
7. Forecasting practice
8. How each finding shaped this skill
9. References

## 1. Short version

- The same content can do very differently on different days. Quality sets the odds; it does not decide the result.
- The best published pre-post models, trained on tens of thousands of labelled videos or more, reach rank correlations of roughly 0.6 to 0.7 with real outcomes. That is useful and far from certainty.
- A few early data points after posting carry more information than the content does.
- No published study shows that a predicted-brain-response score tracks views, likes or rewatching. The one independent test found here saw no relation.
- So the honest product is odds against an account's own base rate, updated after posting and scored afterwards.

## 2. A large part of the outcome is not in the content

**Identical songs, different worlds.** Salganik, Dodds and Watts (2006) ran an online music market with 14,341 participants split into parallel "worlds". When people could see what others had downloaded, success became both more unequal and less predictable. Quality mattered only partly: the best songs seldom did poorly and the worst seldom did well, but anything else was possible.

**Identical photos, different cascades.** Cheng and colleagues (2014) studied Facebook photo reshares and found 983 groups of identical photos uploaded many times. The uploads of one photo reached very different sizes, and which upload became the largest was better predicted by how fast it spread early than by anything else.

**A ceiling even with rich data.** Martin and colleagues (2016) predicted cascade sizes on Twitter using extensive data on users, content and past performance. Their best models explained under half of the variance, and they argue that performance would stay bounded well below certainty even with unlimited data.

## 3. What can be predicted before posting

**Retention, from the video itself.** On SnapUGC (about 120,000 Snapchat Spotlight videos, of which 106,192 for training), the target is the share of viewers who keep watching past five seconds. Sun and colleagues (2025) fine-tuned large multimodal models on it. A model given frames, text and the audio track reached a rank correlation of 0.691 on the test set, one given frames and text reached 0.665, and their ensemble won the VQualA 2025 challenge with a rank correlation of 0.707. The authors credit audio for the gap, though they did not isolate it with an ablation.

**Popular or not.** Kayal and colleagues (2025) had a language model judge videos from text descriptions of their frames plus titles and captions, without fine-tuning. On 13,639 popular videos it reached 82% accuracy, against 80% for a supervised network on content embeddings, and 85.5% when the two were combined. All the videos were already popular, so this is an easier setting than a random draft.

**Views after a week, with web context.** Heo and Lee (2026) built WebShorts, 14,000 YouTube Shorts tracked for seven days, each with a card of open-web context (the topic and entities, public discourse, activity around related content). Their best offline model reached a rank correlation of 0.612 with day-7 views, and 0.677 when it kept adapting online as the results of earlier videos came in. In a like-for-like comparison, adding the web-context card to a content-only model raised the rank correlation from 0.448 to 0.518. The scope is English-language YouTube Shorts.

Three things to keep in mind when reading these numbers. They come from models trained on platform-scale labelled data, which an individual creator does not have. They predict across creators, where some of the signal is who the creator is; predicting how one creator's video deviates from that creator's norm is harder. And a rank correlation of 0.7 means picking the better of two videos about three times in four.

## 4. What early numbers add

Szabo and Huberman (2010) showed that on Digg, access counts from the first two hours forecast popularity thirty days later, and that on YouTube ten days of data gave the same performance, because early and later popularity are strongly correlated after a log transformation.

Cheng and colleagues (2014) predicted whether a cascade would double in size. After only the first five reshares, accuracy was 0.795 against a 0.5 chance level, and it rose as more reshares were observed. Timing features alone came within 0.025 of the full model, content features were weak predictors, and the sentiment of the caption text performed at chance.

This is why the nowcast, not the pre-post forecast, is where most of the attainable accuracy is.

## 5. What makes people share

Berger and Milkman (2012) analysed three months of New York Times articles. Positive content was shared more than negative, and beyond valence, content evoking high-arousal emotions (awe, anger, anxiety) was shared more while low-arousal sadness was shared less. The effects held after controlling for how surprising, interesting or useful the content was, and experiments supported a causal reading.

Tellis and colleagues (2019) studied sharing of YouTube video ads across two field studies with 11 emotion measures and over 60 ad characteristics. Information-focused content reduced sharing except for risky purchases such as new or expensive products. Amusement, excitement, inspiration and warmth increased it. Drama, plot, surprise and characters helped by evoking those emotions. Prominent brand placement, especially early or lengthy, reduced sharing.

These findings inform the `share_save` dimension. They describe averages over many items and say little about any single video.

## 6. Predicted brain response as a virality signal

Some tools describe their score as the response of a modelled audience's brain. Higgsfield's Virality Predictor page (read on 14 November 2026) says it takes a clip of up to 15 seconds and returns a virality score, a peak hook timestamp, a hold rate, an engagement score and a heatmap of activated brain regions. The page gives no accuracy figures, benchmarks or validation studies, and does not describe the model or its training data.

The closest public evidence concerns a different, openly released model. Sahu and Pandey (2026) took TRIBE, the winning brain-encoding model of the 2025 Algonauts challenge, and tested whether its predicted global brain signal tracks behaviour on 48 YouTube videos. Within videos, the signal did not predict the "most replayed" heatmap (position-controlled partial correlation +0.058, 95% interval -0.04 to 0.15, not significant, with a Bayes factor of 3.2 in favour of no effect). Across videos, its rank correlation with views was -0.09 and with likes -0.14, neither significant. The authors list the limits: a modest sample of 48 videos that were all already popular, a biased behavioural target, a 60-second analysis window, and a cortical model that leaves out subcortical reward regions.

What can fairly be said: this is one small study of one open model, not a test of any commercial product, and absence of evidence in 48 videos is not proof of absence. But there is currently no public evidence that such a score predicts performance. The way to settle it for a given account is a head-to-head backtest, which `vforecast.py backtest-score --compare` runs.

## 7. Forecasting practice

Three ideas from the forecasting literature are built in:

- **Start from the base rate.** Judging a case on its own features and ignoring how often such cases succeed is a known source of overconfidence. The account's own history is the reference class here.
- **Average independent judgments.** Schoenegger and colleagues (2024) found that the aggregated forecasts of 12 language models on 31 binary questions were statistically indistinguishable from a crowd of 925 human forecasters. Hence the option of several independent judges.
- **Score with proper scoring rules.** The Brier score rewards honest probabilities and penalises confident misses, which is why the scoreboard uses it and compares it with the base rate.

## 8. How each finding shaped this skill

| Finding | Design decision |
|---|---|
| Outcomes are partly luck, even for identical content | Output is odds and a range, never a verdict; forecasts regress to the base rate |
| Creator history carries much of the predictable signal | Everything is measured against the account's own rolling baseline |
| Trained multimodal models reach about 0.6 to 0.7; an untrained judge is unproven | Reliability starts low (0.25 to 0.35) and is replaced by measurement |
| Audio and text matter alongside frames | The analysis extracts a transcript and audio statistics, and what could not be heard is declared a blind spot |
| Open-web context adds signal for view counts beyond the content itself | An explicit, evidence-backed context check with three scores |
| Early spread predicts final size far better than content | Snapshot and nowcast, with the pre-post forecast as a prior |
| Emotion and usefulness drive sharing; early branding hurts it | The `share_save` dimension of the rubric |
| Brain-response scores are unvalidated in public | A built-in head-to-head test, and stacking if the other score proves useful |
| Aggregated model forecasts can match a human crowd | Optional independent judges, averaged |

## 9. References

- Berger, J., & Milkman, K. L. (2012). What makes online content viral? *Journal of Marketing Research*, 49(2), 192-205. https://doi.org/10.1509/jmr.10.0353
- Cheng, J., Adamic, L. A., Dow, P. A., Kleinberg, J., & Leskovec, J. (2014). Can cascades be predicted? *WWW 2014*. https://arxiv.org/abs/1403.4608
- Heo, R., & Lee, D. (2026). Will it go viral? Grounding micro-video popularity prediction on the open web. https://arxiv.org/abs/2605.18653
- Higgsfield. Virality Predictor product page. https://higgsfield.ai/apps/virality-predictor (read 14 November 2026)
- Kayal, P., Mettes, P., Dehmamy, N., & Park, M. (2025). Large language models are natural video popularity predictors. *Findings of ACL 2025*, 11432-11464. https://aclanthology.org/2025.findings-acl.597
- Martin, T., Hofman, J. M., Sharma, A., Anderson, A., & Watts, D. J. (2016). Exploring limits to prediction in complex social systems. *WWW 2016*. https://arxiv.org/abs/1602.01013
- Sahu, B., & Pandey, S. (2026). A global predicted-fMRI drive signal from TRIBE does not predict YouTube replay heatmaps. https://arxiv.org/abs/2607.01400
- Salganik, M. J., Dodds, P. S., & Watts, D. J. (2006). Experimental study of inequality and unpredictability in an artificial cultural market. *Science*, 311(5762), 854-856. https://doi.org/10.1126/science.1121066
- Schoenegger, P., Tuminauskaite, I., Park, P. S., & Tetlock, P. E. (2024). Wisdom of the silicon crowd: LLM ensemble prediction capabilities rival human crowd accuracy. https://arxiv.org/abs/2402.19379
- Sun, W., Cao, L., Cao, Y., Zhang, W., Wen, W., Zhang, K., Chen, Z., Lu, F., Min, X., & Zhai, G. (2025). Engagement prediction of short videos with large multimodal models. https://arxiv.org/abs/2508.02516
- Szabo, G., & Huberman, B. A. (2010). Predicting the popularity of online content. *Communications of the ACM*, 53(8), 80-88. https://arxiv.org/abs/0811.0405
- Tellis, G. J., MacInnis, D. J., Tirunillai, S., & Zhang, Y. (2019). What drives virality (sharing) of online digital content? The critical role of information, emotion, and brand prominence. *Journal of Marketing*, 83(4), 1-20. https://doi.org/10.1177/0022242919841034
