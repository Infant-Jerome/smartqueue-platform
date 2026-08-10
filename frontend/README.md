# SmartQueue Frontend

React 19 single-page application for the SmartQueue barbershop platform.

## Stack

- React 19 + React Router 7
- Vite (dev server with `/api` proxy to `http://localhost:8000`)
- Tailwind CSS 4 (via `@tailwindcss/vite`)
- Axios (JWT injection + 401 redirect)
- Oxlint for linting

## Scripts

```bash
npm install     # install dependencies
npm run dev     # dev server on http://localhost:5173
npm run build   # production build to dist/
npm run preview # preview the production build
npm run lint    # run oxlint
```

## Key files

| File | Purpose |
| --- | --- |
| `src/main.jsx` / `src/App.jsx` | App entry, routing table |
| `src/services/api.js` | Axios instance, auth header + 401 handling |
| `src/context/AuthContext.jsx` | Auth state, login/register/logout |
| `src/components/ProtectedRoute.jsx` | Route guard (auth + role) |
| `src/pages/` | Page components |

## Development

1. Start the backend (see the root README).
2. `npm run dev` — the Vite proxy forwards `/api/*` to `http://localhost:8000`.