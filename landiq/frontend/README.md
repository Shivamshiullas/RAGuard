# LANDIQ frontend

React 19 + TypeScript + Vite + Tailwind CSS v4 + Leaflet + Recharts + lucide-react.

```powershell
npm ci
npm run dev      # http://localhost:5173, proxies /api to the backend on :8000
npm run build    # type-check + production build into dist/
npm run lint     # oxlint
```

All data comes from the LANDIQ backend (`src/api/client.ts`, mapped to view models in `src/api/adapter.ts`). See `../README.md` for setup, architecture and deployment.
