# Assumptions

What is synthetic in this prototype, and what each number rests on. This is the source for the pitch's assumptions slide (contract §12, item 6).

**Status:** every value in `shared/*.json` is a placeholder (contract §4). Neil committed them so the app could run. None has been signed off against a published source yet. Each row says what checking it would take.

## Real

| What | Detail |
|---|---|
| Hospitals | 10 real Greater Manchester hospitals (`shared/hospitals.json`): Manchester Royal Infirmary, Salford Royal, Wythenshawe, Royal Bolton, Royal Oldham, Fairfield General, Stepping Hill, Tameside General, Royal Albert Edward Infirmary (Wigan) and Rochdale Infirmary. Names and approximate coordinates are real. |
| Reservation correctness | Measured, not assumed. 1,000 simultaneous reservations for one unit give exactly one success (`bench/reserveRace.py`; numbers in `results/benchmark.json` from the LinuxONE instance). |
| Speed | Measured on the instance by `bench/latency.py`. |

## Synthetic or estimated

| What | Value | Basis | To make it defensible |
|---|---|---|---|
| Hospital size and haematology flag | 4 large with haematology, 5 medium, 1 small | Team estimate from each hospital's general role | Check against each trust's published services. The Christie (a specialist cancer centre and heavy platelet user) is a candidate 11th hospital. |
| Travel times | 21–69 minutes, all 90 ordered pairs | **Estimated**: straight-line distance × 1.3 road factor at 50 km/h average, plus 10 minutes for handling | Replace with real driving times (for example Google Maps at a stated time of day). |
| Compatibility penalties | 0 for ABO-identical, 2 for non-identical where the donor plasma is compatible, 3 where it isn't; +1 for an RhD-negative unit going to an RhD-positive recipient; RhD-positive units never go to RhD-negative recipients | Simplified rule based on ABO-identical-first practice. A planning preference, not clinical guidance | Check against current UK platelet transfusion guidance (JPAC / BSH). |
| Shelf life | 7 days from collection | Contract convention | Confirm with a source. |
| Shelf life left on arrival | 1–4 days | Contract placeholder | Needs a source on the age of platelets when delivered to hospitals. |
| Daily demand per hospital | small 1, medium 3, large 8 units a day; weekends × 0.6 | Contract placeholder | Needs hospital-level usage data or a published estimate. |
| Blood group mix | O+ 35%, A+ 30%, O− 13%, A− 8%, B+ 8%, B− 2%, AB+ 2%, AB− 1% | Contract placeholder, close to commonly quoted UK donor proportions | Cite the source used. |
| Baseline waste rate | 4.8% | Contract placeholder for the national figure | Cite the published national platelet wastage figure. |
| Transfer limits | Trips of at most 240 minutes; units need at least 12 hours left to be moved | Team planning choice | State as a design choice. |
| All stock, deliveries and demand | Generated per seed by `sim/generate.py` | Synthetic scenario from the values above | n/a: say clearly that it's a simulation. |

## Current simulation results and their limits

From `results/comparison.json` (90 days, seeds 1–10, generated with the placeholders above):

| Policy | Waste rate (mean ± 1 SD) | Shortage events (mean) | Transfers (mean) |
|---|---|---|---|
| No sharing | 32.1% ± 0.9% | 1,262 | 0 |
| Exchange | 30.6% ± 1.0% | 1,205 | 253 |

The exchange lowers both waste and shortages on average across the 10 seeds, in the canonical seed-42 run, and in both stress scenarios (a 3× demand surge at Manchester Royal Infirmary, and a 3-day supply gap). The waste difference (1.5 points) is about 1.5 standard deviations, so it shows a consistent direction rather than a large effect. **But the absolute numbers aren't realistic yet.** No-sharing waste is about 32%, against the 4.8% baseline the scenario is meant to reproduce, and shortages are far too frequent. The supply and demand placeholders aren't calibrated against each other. Until they are:

- present the **direction** of the effect (less waste and fewer shortages with sharing, averaged over 10 seeds), not the absolute percentages
- say plainly that the scenario is synthetic and not yet calibrated

Calibrating the sim is Person 2's next step (brief: the no-sharing waste rate should land near the baseline).

## Suggested slide wording

> **What's real:** 10 Greater Manchester hospitals; the reservation logic and its benchmark, run on IBM LinuxONE.
> **What's simulated:** stock, deliveries and demand, generated from stated placeholder assumptions; travel times estimated from distance; a simplified compatibility rule.
> **Not yet validated:** demand and supply levels, so we report the direction of the effect, averaged over 10 seeds, rather than absolute waste rates.
