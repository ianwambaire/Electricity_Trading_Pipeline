# PowerFlow frontend

React + TypeScript frontend foundation, using Vite, Tailwind CSS v4 through `@tailwindcss/vite`, React Router, and Lucide React. No new dependencies were needed.

## Local development

From the repository root:

```sh
cd frontend
npm ci # only if dependencies are not already installed
npm run dev -- --host 127.0.0.1
```

Open the local URL printed by Vite (normally http://127.0.0.1:5173).

```sh
npm run lint
npm run build
npm run preview -- --host 127.0.0.1
```

Preview serves the build locally, normally on port 4173. No deployment is involved.

## Routes

| URL | Page |
| --- | --- |
| `/` | Market Overview |
| `/forecasting` | Forecast Intelligence |
| `/analytics` | Market Analytics |
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

## Scope

No API requests, authentication, invented market data, forecasts, user identities, or roles. Placeholder navigation is not authorization; no protected backend data is accessed. All pages explicitly identify unavailable integrations. LoadingState and ErrorState are reusable components for later real requests, not simulated service activity. Existing Python, Streamlit, AWS, and authentication settings are untouched.

## Manual inspection

Visit every route and an unknown URL. Test sidebar collapse/expand, active links, browser back/forward, and direct route refresh. At tablet/mobile widths, open navigation, follow a link, press Escape, click the backdrop, and check focus returns to the menu button. Resize an open mobile drawer to desktop. Tab through controls, use Skip to content, and check reduced-motion settings. Inspect widths from 320px through desktop for overflow.
