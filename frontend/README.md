# PowerFlow frontend

React + TypeScript frontend with read-only FastAPI integration, using Vite, Tailwind CSS v4 through `@tailwindcss/vite`, React Router, and Lucide React. No new dependencies were needed.

## Local development

Start the existing read-only backend in terminal 1, from the repository root (dependencies must already be installed):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

This API reads existing reports and SQLite using read-only access. It does not run the pipeline or require AWS credentials. If your virtual environment has a different path, use its Python executable. Do not install or change backend dependencies for this phase.

In terminal 2, from the repository root:

```sh
cd frontend
npm ci # only if dependencies are not already installed
npm run dev -- --host 127.0.0.1
```

Open the local URL printed by Vite (normally http://127.0.0.1:5173).

```sh
npm test # Node 22.6+; built-in test runner, no added libraries
npm run lint
npm run build
npm run preview -- --host 127.0.0.1
```

Preview serves the build locally, normally on port 4173; the development API proxy is only configured for `npm run dev`. Use the dev server for connected local inspection. Production is expected to provide `/api` through its existing reverse proxy. No deployment is involved.

## Routes

| URL | Page |
| --- | --- |
| `/` | Executive Overview |
| `/forecasting` | Forecast Intelligence |
| `/analytics` | Market Intelligence |
| `/anomalies` | Anomaly Detection |
| `/pipeline` | Pipeline Operations |
| `/models` | Model Insights |
| `/profile` | My Profile |

Unknown URLs show a recovery page. BrowserRouter supports browser history; a future hosting configuration must serve `index.html` for frontend routes, without intercepting existing backend routes. No hosting configuration is changed here.

## Structure

- `src/config/navigation.ts`: shared navigation metadata.
- `src/components/layout/`: branding, navigation, and application shell.
- `src/components/ui/`: headings/breadcrumbs, panels, integration notice, loading/empty/error states.
- `src/pages/`: overview and initial workspace placeholders.
- `src/index.css`: Tailwind import, theme, shared styles, responsive and reduced-motion rules.

## API integration and safety

- The client uses same-origin `/api`. Vite forwards `/api/*` to `http://127.0.0.1:8000/*`, matching the existing Nginx prefix stripping. No CORS or production configuration changes.
- Market Overview: `/health`, `/pipeline/status`, `/forecast/next24`.
- Forecast Intelligence: `/pipeline/status`, `/forecast/next24`, `/forecast/one-hour`.
- Pipeline Operations: `/health`, `/pipeline/status`, `/monitoring/forecast-vintages`, `/monitoring/exogenous-readiness`.
- Every section loads independently, with runtime contract validation, a 15-second timeout, cancellation, manual retry, and 60-second refresh. Data is cleared during refresh/failure; old results are not silently reused.
- `Last fetched` is the browser receipt time, not report generation or forecast issuance time. All displayed timestamps are UTC. Availability classification updates every 15 seconds.
- The API supplies no production freshness threshold or live availability attestation. A 3-hour **frontend display recency** window distinguishes old reports conservatively; it does not modify backend freshness/withholding rules. Recent future-target reports remain explicitly unverified, never labeled live. Withholding/unavailability from the latest recorded pipeline run overrides any retained report; its source timestamp is shown, since that status may itself be old. The new safe operational summary supplies a categorized reason when recorded; raw operational messages remain restricted.
- All elapsed targets are historical; older issue times with future targets are stale; partly elapsed windows are identified. One-hour reports are labeled historical and do not inherit next24h model identity or metrics.
- Monitoring parsers select known statuses, source identifiers, timestamps and numeric counts only. They discard paths, raw reasons, unknown fields and credentials. Error responses are generic and do not render server bodies. These filters are presentation measures, not authorization.
- Recharts renders only validated returned values; exact values have an accessible table. The one-hour chart shows the latest 500 available rows, not a claim of continuous seven-day coverage.
- Market Analytics now uses `/market/coverage` and `/market/history` with real date-filtered observations and bounded pagination. Model Insights uses `/models/summary` with separate release-specific metrics and provenance. Anomaly Detection uses the active persisted report through `/anomalies/summary` and `/anomalies/events`. Executive Overview uses `/market/summary` and `/market/chart`; Pipeline Operations adds `/operations/summary`. Profile and restricted feature influence remain pending server-side authentication.
- Phase 5 adds read-only Python API modules and tests; models, pipeline, Streamlit, authentication, infrastructure and production configuration remain unchanged. No login or What-if Lab is implemented. No fake responses or fallback data are shipped. Synthetic contract fixtures exist only under `tests/` and are not imported by the application.

## Phase 3 data readiness

See [data-readiness.md](docs/data-readiness.md) for the three 404 root causes, legitimate local report-generation prerequisites, API query contracts, caching/limits, and model evidence. None of the missing reports was fabricated or generated in this phase.

## Code organization

`src/api/` contains contracts, runtime parsing, HTTP errors and forecast classification. `src/hooks/` manages asynchronous state and the display clock. `src/components/data/` provides request panels, source facts, forecast summaries and the lazy-loaded Recharts chart. Connected pages compose these modules; other pages retain explicit placeholders.

## Validation

`npm test` covers forecast contract validation, negative prices, withholding with or without retained data, historical/stale/recent/future classifications, monitoring field filtering, HTTP 404/503, network failures, invalid JSON, and request retry. Fixtures are test-only.

The local repository currently returns real health and September pipeline status plus 14,878 one-hour records. The next24h and both monitoring report files are missing locally (HTTP 404). Their success and withholding paths are covered by isolated contract tests, not claimed as live production evidence.

## Manual inspection

Visit every route and an unknown URL. Test sidebar collapse/expand, active links, browser back/forward, and direct route refresh. At tablet/mobile widths, open navigation, follow a link, press Escape, click the backdrop, and check focus returns to the menu button. Resize an open mobile drawer to desktop. Tab through controls, use Skip to content, and check reduced-motion settings. Inspect widths from 320px through desktop for overflow.

## Phase 5 P0 restoration

See [the implementation report](docs/phase5-restoration.md) for the parity checklist, every changed file, endpoint bounds, validation evidence, remaining authentication dependencies and P1 work. No additional dependencies were installed.
