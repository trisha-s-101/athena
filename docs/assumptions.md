# Assumptions

What is synthetic in this prototype, and what each number rests on. This is the source for the pitch's assumptions slide (contract §12, item 6).

**Status:** every value in `shared/*.json` is a placeholder (contract §4). Neil committed them so the app could run. None has been signed off against a published source yet. Each row says what checking it would take.

## Real

| What | Detail |
|---|---|
| Hospitals | 10 real Greater Manchester hospitals (`shared/hospitals.json`): Manchester Royal Infirmary, Salford Royal, Wythenshawe, Royal Bolton, Royal Oldham, Fairfield General, Stepping Hill, Tameside General, Royal Albert Edward Infirmary (Wigan) and Rochdale Infirmary. Names and approximate coordinates are real. |
| Reservation correctness | Measured on IBM LinuxONE (s390x), 17 Oct 2026: 1,000 simultaneous reservations for one unit gave exactly 1 success and 999 safe rejections, with 0 errors (`bench/reserveRace.py`, `results/benchmark.json`). The race took 6.5 s because all 1,000 requests queue for one app process at the same instant. It shows correctness under contention, not speed. |
| Speed | Measured on the instance by `bench/latency.py`, 20 requests in flight: about 100–120 requests/s per endpoint with 0 errors in 4,000 requests. Emergency sourcing p50 180 ms, p99 316 ms, well under the 1-second target. This measures the prototype (one Python process on a small instance), not IBM Z's capacity. |

## Synthetic or estimated

| What | Value | Basis | To make it defensible |
|---|---|---|---|
| Hospital size and haematology flag | 4 large with haematology, 5 medium, 1 small | Team estimate from each hospital's general role | Check against each trust's published services. The Christie (a specialist cancer centre and heavy platelet user) is a candidate 11th hospital. |
| Travel times | 21–69 minutes, all 90 ordered pairs | **Estimated**: straight-line distance × 1.3 road factor at 50 km/h average, plus 10 minutes for handling | Replace with real driving times (for example Google Maps at a stated time of day). |
| Compatibility penalties | 0 for ABO-identical, 2 for non-identical where the donor plasma is compatible, 3 where it isn't; +1 for an RhD-negative unit going to an RhD-positive recipient; RhD-positive units never go to RhD-negative recipients | Simplified rule based on ABO-identical-first practice. A planning preference, not clinical guidance | Check against current UK platelet transfusion guidance (JPAC / BSH). |
| Shelf life | 5 days from collection (contract §3) | [Leeds Teaching Hospitals NHS Trust](https://www.leedsth.nhs.uk/services/pathology/blood-transfusion-services/blood-products/), which states a 5-day shelf life for platelets | Settled. Seven days applies only where platelets are bacterially screened, so 5 is the conservative figure. Note it does not change the results either way: expiry is driven by shelf life left on arrival, not the nominal figure. |
| Shelf life left on arrival | 1–4 days | Contract placeholder | Needs a source on the age of platelets when delivered to hospitals. |
| Daily demand per hospital | small 1, medium 3, large 8 units a day; weekends × 0.6; plus occasional emergency admissions needing several units of one group | Contract placeholder | Needs hospital-level usage data or a published estimate. |
| Ordering | Each hospital orders enough to keep `targetStockDays` of expected use (small and medium 2 days, large 1.5) | Contract placeholder | Needs a source on typical hospital platelet stock levels. |
| Blood group mix | O+ 35%, A+ 30%, O− 13%, A− 8%, B+ 8%, B− 2%, AB+ 2%, AB− 1% | Contract placeholder, close to commonly quoted UK donor proportions | Cite the source used. |
| Baseline waste rate | 4.8% | Contract placeholder for the national figure | Cite the published national platelet wastage figure. |
| Transfer limits | Trips of at most 240 minutes; units need at least 12 hours left to be moved | Team planning choice | State as a design choice. |
| All stock, deliveries and demand | Generated per seed by `sim/generate.py` | Synthetic scenario from the values above | n/a: say clearly that it's a simulation. |

## Current simulation results and their limits

From `results/comparison.json` (90 days, seeds 1–10, generated with the placeholders above):

| Policy | Waste rate (mean ± 1 SD) | Shortage events (mean ± 1 SD) | Transfers (mean) |
|---|---|---|---|
| No sharing | 19.0% ± 0.9% | 263 ± 23 | 0 |
| Exchange | 14.4% ± 1.0% | 41 ± 9 | 472 |

The exchange cuts shortages by about 85% and waste by about 4.6 percentage points (nearly five standard deviations) on average across the 10 seeds. It also beats no sharing in the canonical seed-42 run and in both stress scenarios:

| Stress scenario | No sharing (waste, shortages) | Exchange (waste, shortages) |
|---|---|---|
| Demand at Manchester Royal Infirmary × 3 for 7 days | 20.1%, 356 | 14.7%, 91 |
| No deliveries for 3 days | 19.8%, 374 | 15.3%, 160 |

**Limits to state honestly:**
- No-sharing waste of about 19% is still well above the 4.8% national baseline the scenario should reproduce. The most likely driver is the placeholder of 1–4 days of shelf life left on arrival. So present the **relative** effect (fewer shortages, less waste) rather than the absolute percentages.
- When a hospital runs out, the exchange sources a unit from another hospital and counts it as arriving within the same 6-hour sim step. Courier time isn't charged for these urgent transfers (routine transfers do wait for travel time), so the shortage reduction is somewhat optimistic.
- Everything rests on the placeholder values above.

## Suggested slide wording

> **What's real:** 10 Greater Manchester hospitals; the reservation logic and its benchmark, run on IBM LinuxONE.
> **What's simulated:** stock, deliveries and demand, generated from stated placeholder assumptions; travel times estimated from distance; a simplified compatibility rule.
> **Result:** across 10 simulated seeds, sharing cut shortages by about 85% and waste by about 4.6 percentage points, and held up under a demand surge and a supply gap.
> **Not yet validated:** absolute supply and demand levels (the simulated baseline waste is higher than the national figure), so we quote relative improvements, not absolute waste rates.
