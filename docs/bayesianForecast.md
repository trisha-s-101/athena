# Experiment: a Bayesian demand forecaster

**Status:** merged into `main` with Neil's approval ([PR #17](https://github.com/trisha-s-101/athena/pull/17), from branch `experiment/bayesianForecast`). The instance runs it after the next INSTANCE_SETUP Part 8C deploy.

**In one line:** replacing the per-pair weekday average with a partially pooled Bayesian model cuts forecast error by 6.5–8.2% (12% in the first four weeks). In the simulator, the exchange gets the same waste and shortages with about 14% fewer courier transfers. Nothing outside `engine/forecast.py` has to change.

## What changed

| File | Change |
|---|---|
| `engine/forecast.py` | `forecastDemand` is now a partially pooled Poisson–Gamma model with recency weighting. Same signature and behavior rules as contract §6: same validation, missing days count as zero, duplicates sum, only observed pairs appear, inputs aren't modified. |
| `engine/weekdayForecast.py` | The previous forecaster, kept only for comparison. Not exported from `engine/__init__.py`. |
| `engine/tests/test_bayesian_forecast.py` | 9 new tests: sparse data, real differences not pooled away, all-zero history, recency, determinism and input order, unchanged inputs, output shape, and the baseline module. |
| `bench/forecastBacktest.py` and its tests | The backtest below. |
| `engine/README.md` | The forecasting section and pitch paragraph. |

The API, database, simulator, dashboard and contract are unchanged.

## How the model works

Each hospital/blood-group pair's daily demand is treated as Poisson, with a Gamma prior on its rate (the conjugate Poisson–Gamma model). The rate is estimated in two pooled steps (empirical Bayes):

1. **Pair rate.** The prior mean is the hospital's total daily demand split by the region's blood-group mix, over the groups seen at that hospital, so a hospital's priors add up to its total. The posterior is `own + (prior − own) × κ₁ / (κ₁ + n)`, where `n` is the number of (weighted) days of data.
2. **Weekday rate.** The prior mean is that pair rate times the region's weekday profile (quieter weekends, for example). The posterior is `ownWeekday + (prior − ownWeekday) × κ₂ / (κ₂ + nWeekday)`.

**Pooling strength is learned, not set by hand.** The method of moments compares how far pairs' own averages sit from the pooled pattern with how far Poisson noise alone would put them. Excess spread means hospitals genuinely differ, so the prior is weakened. No excess means the pattern explains them, so the prior is strengthened. `κ` is clamped to 0.5–1,000 days. On a scenario's history the learned values adapt to how much data there is:

| History | Learned prior strength (pair level / weekday level) |
|---|---|
| 14 days (sim) | 1,000 / 1,000 days: too little data to trust each pair's own, so it pools almost fully |
| 28 days (as the API calls it) | 62 / 372 days |
| 89 days (as the sim calls it) | 286 / 125 days |

**Recency:** the last 28 days count fully, and older days lose half their weight every 8 weeks.

**Speed:** 1.7 ms per call on 89 days of history, against 1.0 ms for the weekday average.

**Why the existing engine tests still pass unchanged.** Pooling only changes a forecast when the pooled pattern differs from the pair's own history. In the existing fixtures each hospital has a single blood group, and all pairs share the same weekly shape, so the pooled prior equals each pair's own estimate. Their windows are under 28 days, so recency weighting doesn't apply either. That's a property of the model, not a special case. For the same reason, recency weighting never affects the API, which passes exactly 28 days. It only affects the simulator, which passes the whole run.

## Tuning (seeds 101–105, separate from the reported seeds)

The grid covered 3 full-weight windows (7, 14, 28 days), 5 half-lives (7, 14, 28 and 56 days, or no fading) and 2 prior caps (100, 1,000), each tested across both history settings and both scenarios.

- Every configuration scored between 0.5457 and 0.5491 mean MAE, against **0.5880** for the weekday average. **The gain comes from pooling. Recency weighting adds nothing measurable on this data**: the synthetic demand doesn't drift, and the 7-day surge is too short for fading old history to help.
- The chosen setting (28 days full weight, 8-week half-life, cap 1,000) is the gentlest one tied for best. It's kept as a safeguard for real data, which does drift.

## Backtest (held-out seeds 1–10, 90 days, 3-day horizon)

`python -m bench.forecastBacktest` rolls a forecast origin through each scenario from day 7. At each origin, both forecasters see only earlier demand and are scored on the next 3 days. MAE is in units per hospital/group/day, and lower is better.

| Setting / scenario | Weekday average | Bayesian | Change | First 4 weeks | Later | Rare groups | RMSE |
|---|---|---|---|---|---|---|---|
| API (28 days) / stationary | 0.5868 | 0.5387 | **−8.2%** | −12.2% | −6.7% | −5.9% | 0.991 → 0.871 |
| Sim (full history) / stationary | 0.5495 | 0.5137 | **−6.5%** | −12.2% | −4.3% | −3.2% | 0.939 → 0.847 |
| API / demand surge | 0.6094 | 0.5596 | **−8.2%** | −12.2% | −6.7% | −5.5% | 1.066 → 0.945 |
| Sim / demand surge | 0.5687 | 0.5319 | **−6.5%** | −12.2% | −4.3% | −2.9% | 1.007 → 0.916 |

The Bayesian forecaster is better in every setting, scenario and segment. The largest gains come early, when history is thinnest.

## Simulator comparison (`python -m sim.run`, the same code on `main` and on this branch)

| Exchange policy | `main` (weekday average) | Bayesian |
|---|---|---|
| Waste, 10 seeds (mean ± SD) | 14.45% ± 1.04 | 14.40% ± 1.05 |
| Shortages, 10 seeds | 40.6 ± 8.9 | 38.6 ± 8.7 |
| **Transfers, 10 seeds** | **472 ± 38** | **405 ± 35 (−14%)** |
| Canonical seed 42 (waste / shortages / transfers) | 15.95% / 49 / 461 | 15.95% / 50 / 402 |
| Demand surge | 14.68% / 91 / 608 | 14.64% / 90 / 542 |
| Supply dip | 15.29% / 160 / 488 | 15.26% / 160 / 433 |

No sharing is identical on both, as it should be, because that policy never calls the forecaster.

**Reading it:** waste and shortages stay the same within noise, while **courier transfers drop 11–14%** in every run. The likely reason, which I haven't measured directly: the weekday average's noisy per-pair estimates create phantom shortfalls that the engine fills with transfers, and the pooled forecast removes most of them. So in this simulator, the payoff is efficiency (fewer trips for the same outcome) rather than less waste.

## Tests

On the branch's code commit, every suite passes:

| Suite | Tests |
|---|---|
| API | 20 |
| Database | 13 |
| Bench (including 3 new backtest tests) | 7 |
| Engine (32 existing, unmodified, plus 9 new) | 41 |
| Dashboard | 7 |
| Sim | 42 |

## Trade-offs and risks

- **The synthetic data suits this model.** The simulator generates demand as hospital size × blood-group mix × weekday factor, which is exactly the structure the prior pools toward. Real hospitals will differ more. The learned pooling strength weakens automatically when they do (see the "real differences aren't pooled away" test), but the size of the gain on real data is unproven.
- **Harder to explain** than "a weekday average", though the one-line version is easy: it learns each hospital's demand and borrows strength from similar hospitals where data is thin.
- **Uncertainty isn't used yet.** The model has a full predictive distribution, but `recommendTransfers` still only receives expected values, as the contract requires. Using uncertainty in transfer decisions would be a separate, larger change.
- **Conflicts.** Someone else is changing engine logic. If they edit `engine/forecast.py`, whichever change merges second will conflict.

## Recommendation and how to undo it

It's worth merging if there's time before the feature freeze and the engine owner agrees:
- better forecasts, measured on held-out seeds
- fewer transfers for the same outcomes
- no interface changes and a negligible speed cost

**To undo:** the change is one merge commit. Reverting it and redeploying with INSTANCE_SETUP Part 8C restores the weekday average exactly.

**Pitch line:** "Our exchange forecasts demand with a Bayesian model that learns each hospital's pattern and borrows strength from similar hospitals where data is thin. In simulation it cut forecast error by about 7%, and 12% in the first month, and achieved the same waste and shortages with 14% fewer courier trips."

## Reproduce

```bash
python -m bench.forecastBacktest                 # held-out seeds 1–10
python -m bench.forecastBacktest --seeds 101,102,103,104,105   # the tuning seeds
python -m sim.run                                # writes results/comparison.json; compare with main's
python -m unittest discover -s engine/tests
```
