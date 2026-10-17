# Platelet Exchange dashboard

Person 4 implementation of contract v1.1, sections 5 and 8. Copy this entire `web/` folder into the team repository. No build step or Python dependencies are required.

## Preview

From the repository root:

```sh
python -m http.server 8080 --directory web
```

Open http://localhost:8080. Mock mode is enabled by default. Select a hospital, reserve a recommended unit, complete its handoff, and submit an emergency request. Mock changes live in memory and reset on reload or mode switch. The mock simulation clock is fixed; polling does not advance it.

## Connect to the API

Have Neil serve `web/` at `/` through FastAPI on port 8000, as specified in the contract. Open that origin and turn off **Use mock data**. Requests use same-origin `/api/...` paths; no invented endpoints or CORS setup are needed. API connection errors are displayed and retried every five seconds. Mock mode is never selected automatically after an API failure.

Reservations are created with `POST /api/reservations`. Complete buttons call `POST /api/reservations/{reservationId}/complete`. A 409 refreshes stock and explains the conflict. Reservation cards are held only for the current page session: the contract provides no list-reservations endpoint. Keep the page open until handoffs finish. An interrupted write may have reached the API; verify its outcome before retrying. Database concurrency correctness belongs to the API; the in-memory mock is only a UI demonstration.

The emergency form uses `POST /api/emergency` and displays the engine's ranking without reranking or implying that search reserves stock. The mock supports exact blood group matches only, uses synthetic journey times, and does not claim clinical compatibility beyond those fixtures. No clinical compatibility algorithm runs in the real dashboard.

## Data and display

- Hospital data, geography, journeys, stock, recommendations, events, metrics, and simulation results in `mock/` are synthetic illustrations, not researched or validated operational data.
- The map uses Leaflet 1.9.4 from a CDN and OpenStreetMap tiles. If Leaflet cannot load, hospital buttons still provide stock access. Internet access is needed for the map; the rest of mock mode runs locally.
- Map color shows the earliest expiry among available units. Gray means no available stock. The legend uses red under 24h, amber 24–72h, green 72h or more. The brief leaves 48–72h unspecified; amber conservatively fills that display gap. Times use the API simulation clock, never the workstation clock.
- Stock includes all nonterminal statuses supplied by `/api/stock`; the detail table shows status explicitly.
- Daily waste and shortage charts compare the supplied single seed. Missing days break chart lines. Example fixture totals match their daily data; they are not measured outcomes.
- Events are displayed in the newest-first order supplied by the API. The dashboard polls hospitals, stock, recommendations, metrics, and events every five seconds. Simulation results refresh separately.

## Contract gaps for Neil

1. The brief requests a benchmark panel from `results/benchmark.json`, but section 8 specifies neither an HTTP endpoint nor a schema for that file. The panel explains this dependency. No direct filesystem access or endpoint is assumed.
2. The definition of done requires error bars across seeds; `/simulation/results` returns a single `seed` with two `SimResult` objects. A versioned multi-seed contract is needed before error bars can be implemented.
3. Cross-reload reservation recovery requires a list-reservations interface if needed for the demo.

## Tests

Node is optional and only needed for development tests, not LinuxONE deployment:

```sh
node --test web/tests/*.test.js
```

Tests cover mock reservation conflict and handoff, emergency filtering, API error propagation, UTC expiry colors, escaped text, shelf life, and simulation totals. They do not substitute for Neil's database reservation benchmark.

Suggested PR summary: `Implement Person 4 dashboard with mock/live HTTP workflows matching contract v1.1 sections 5 and 8.`
