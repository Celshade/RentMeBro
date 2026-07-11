# RentMeBro

Rent + utility billing SaaS. Renter pays via Cash App Pay (through
Stripe); landlord receives via Stripe payout to their bank account.

## Layout

- `backend/` — Django + DRF API (SQLite for local dev; Postgres via
  `DATABASE_URL` for docker-compose/production).
- `frontend/` — React + TypeScript (Vite).
- `docker-compose.yml` + `backend/Dockerfile` + `frontend/Dockerfile` —
  Postgres + backend + frontend. Written but **not yet run/verified**
  in this environment (no Docker available); verify with `docker
  compose up` once Docker is installed.

## Local dev (current: SQLite, no Docker)

```bash
# backend
cd backend
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py runserver

# frontend
cd frontend
cp .env.example .env
npm run dev
```

## Local dev (once Docker is available)

```bash
docker compose up --build
```

This runs Postgres + backend (`:8000`) + frontend (`:5173`) together.
Switching the backend from SQLite to Postgres locally only requires
setting `DATABASE_URL` in `backend/.env` (see `.env.example`) — no code
changes needed, since `DATABASES` already reads it via django-environ.
