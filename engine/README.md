# Forecasting and optimization engine

Person 3's implementation of `shared/CONTRACT.md` section 6. Uses only the
Python standard library and exports these functions:

```python
from engine import forecastDemand, recommendTransfers, rankEmergencySources
```

All three functions take contract-shaped dictionaries and lists, return
JSON-compatible values, and leave their inputs unchanged. They do not read
files, consult the system clock, make HTTP requests, or access a database.
Run commands from the repository root using Python 3.12 or newer.

## Forecasting

`forecastDemand(history, horizonDays=3)` is a partially pooled Bayesian
(Poisson–Gamma) model. Each hospital/blood-group pair's daily demand is treated
as Poisson, and its rate is estimated in two pooled steps, so pairs with thin
history borrow strength from the rest of the region:

1. **Pair rate**, shrunk toward the hospital's total daily demand split by the
   region's blood-group mix (over the groups seen at that hospital).
2. **Weekday rate**, shrunk toward that pair rate times the region's weekday
   profile (for example, quieter weekends).

How strongly each step pulls is learned from the history by the method of
moments: the more pairs differ from the pooled pattern beyond Poisson noise, the
weaker the pull. The last 28 days count fully, and older days fade with an
8-week half-life. Tuning, the backtest against the previous forecaster and the
simulator comparison are in `docs/bayesianForecast.md`. The previous per-pair
weekday average is kept in `engine/weekdayForecast.py` for comparison only.

Weekdays not represented in the history use the pair's overall rate. Duplicate
records for a date sum; missing records between the first and last history dates
count as zero. Results include only hospital/group pairs observed in history and
don't depend on record order. Empty history returns `{}`; a zero horizon returns
empty arrays for observed pairs.

The interface has no clock argument. Consequently, forecast index 0 is the day
after the latest history date. API and simulator callers should supply history
through the previous complete UTC day, including zero-demand records to mark
otherwise empty days. Keep partial current-day records out of this input.
Pass `horizonDays` explicitly when a different forecast horizon is needed.

## Routine transfers

`recommendTransfers(stock, forecast, travelTimes, compatibility, now)` uses a
deterministic, conservative greedy heuristic:

1. Spread each day's expected demand uniformly over that UTC calendar day.
   Index 0 is today; elapsed demand is excluded on calls later in the day.
   Split demand at expiry times and possible courier arrival times.
2. Allocate compatible local stock to that demand in collection-time FIFO
   order. Protect any unit used even fractionally by this projection. This
   leaves surplus units whose projected local use is zero before expiry.
3. Consider surplus units in expiry order. Require at least 12 hours of shelf
   life at departure, a directed route of at most 240 minutes, and arrival
   strictly before expiry. Only donate units expiring within the supplied
   forecast horizon; later local demand is unknown.
4. Match each candidate to compatible unmet demand after arrival and before
   expiry. Prefer lower compatibility penalties, then greater expected use,
   then shorter travel. Immediately consume the matched forecast shortfall,
   preventing other recommendations from filling it again.
5. Return each unit at most once, sorted by descending score. Scores combine
   expected utilization, expiry urgency, compatibility penalty, and travel
   cost. Ties resolve deterministically using expiry, travel, and IDs.

The score is a prioritization value in `[0, 1]`, not a calibrated probability:

```text
expectedUse * min(1, 24 / hoursToExpiry)
----------------------------------------------------------
1 + averageCompatibilityPenalty + travelMinutes / 240
```

The transfer reason explains the unit's expiry, projected local use, matched
destination shortfall, and preference penalty. Expected use is fractional,
but the entire physical unit is protected or transferred. This is a heuristic,
not a globally optimal flow solution or a guarantee against realized shortages.
Missing forecast hospital/group entries count as zero demand within the supplied
horizon; callers must supply forecasts for every hospital they want protected.

The exact contract signature does not accept assumptions. The routine limits
are therefore the contract v1.1 section 4 values in `engine/_common.py`, with no
file reads or mutable configuration. If Person 5 changes those values, coordinate
with Neil to update these constants or revise the contract to pass configuration.

## Emergency ranking

`rankEmergencySources(request, stock, travelTimes, compatibility, now)` filters
out the requesting hospital, unavailable or expired units, future collections,
incompatible donors, and trips that cannot arrive before expiry. It returns all
alternatives, even when there are more than `unitsNeeded`, so the API can retry
if a reservation loses a race. A nonpositive request returns `[]`.

Sources sort by compatibility penalty, travel minutes, then hours to expiry;
hospital and unit IDs break ties. Ranks start at 1. The routine 12-hour and
240-minute limits do not apply to emergencies, whose contract only requires
compatible external sources; arrival before expiry is still mandatory.

Both allocation functions use the supplied compatibility table in its stated
direction: recipient group to allowed donor groups. They do not infer clinical
compatibility or reverse missing travel routes. This is a synthetic planning
prototype using the team's supplied rules.

## Tests and handoff

```bash
python -m unittest discover -s engine/tests -v
```

Hand-made contract fixtures cover forecast weekday averages and sparse history,
source stock protection, destination coverage, compatibility preference, missing
and directed routes, expiry/arrival timing, threshold boundaries, duplicate IDs,
emergency ordering, deterministic results, and input immutability. A seeded
mixed-stock fixture also checks recommendation invariants.

For Person 2: call the functions directly, pass the simulation clock as `now`,
and provide only completed historical days to forecasting. No simulator or
comparison results exist in this checkout yet. Waste and shortage improvements
across simulation seeds remain to be measured jointly; the unit tests do not
establish the team's simulation acceptance criterion.

For Person 6's pitch: "We forecast each hospital's demand with a Bayesian model
that learns from its history and borrows strength from similar hospitals where
data is thin, protect units it is expected to need, and move surplus stock nearing
expiry to compatible hospitals with a predicted shortfall. Courier travel and
shelf life constrain every recommendation, while emergency requests rank all
compatible sources by preference, speed, and expiry."
