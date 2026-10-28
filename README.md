# Proximity Search API – Docker

Lab 7 (nearest-location search over a road network) split into two containers:

| Service | Image | What it does |
|---|---|---|
| `api` | `proximity-api:1.0` (python:3.13-slim) | FastAPI search API on port 8000, only reachable inside Docker |
| `web` | `proximity-web:1.0` (nginx:1.27-alpine) | Serves the UI and forwards `/search/` to `api`; published on `WEB_PORT` (8088) |

## Run

```bash
docker compose up -d --build     # build and start everything
open http://localhost:8088       # web UI
docker compose down              # stop and remove
```

Settings are in `.env` (`WEB_PORT`, `API_WORKERS`, `LOG_LEVEL`). Link files placed in `data/`
can be used by name, e.g. `/search/?lat=0.5&long=0.5&cat=bank&rad=0.2&link=sample_link.txt`.
