# RentMeBro

RentMeBro is a light-weight rent + utility billing platform for small and independent landlords and
contractors. Renters pay Landlords directly through Cash App Pay (via Stripe Connect) or on-chain
Bitcoin (p2p). An optional mileage-based gas/utility add-on tracks and bills a renter (passenger)
for days driven to/from a work-site/etc - based on a customizable mileage profile and weekly gas
prices.

[![CI](https://github.com/Celshade/RentMeBro/actions/workflows/ci.yml/badge.svg)](https://github.com/Celshade/RentMeBro/actions/workflows/ci.yml)
![Status](https://img.shields.io/badge/Status-Alpha-orange)
![Version](https://img.shields.io/github/v/tag/Celshade/RentMeBro?label=version)
![License](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-purple)\
![Python](https://img.shields.io/badge/Python-3.12-blue)
![Django](https://img.shields.io/badge/Django-6.0-092E20)
![React](https://img.shields.io/badge/React-19-61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-blue)
![Vite](https://img.shields.io/badge/Vite-8-646CFF)
![Bitcoin](https://img.shields.io/badge/Bitcoin-on--chain-F7931A)
![Stripe](https://img.shields.io/badge/Stripe-Cash%20App%20Pay-635BFF)

## Status

Early-stage and not deployed. This is an entrepreneurial/portfolio project first; use
it at your own risk.

Permitted uses under the [LICENSE](LICENSE):
- ✅ Personal use / self-hosting for noncommercial purposes
- ✅ Education, research, and portfolio use, with no anticipated
  commercial application
- ❌ Any commercial use, including running RentMeBro (or a derivative)
  as a paid or hosted service
- ✅ Contributions back to this repository

## Security

Please don't open a public issue for vulnerabilities — see
[SECURITY.md](SECURITY.md) for private reporting instructions.

## Known limitations / roadmap

- **Scheduled cleanup** — token-pruning management commands exist but
  aren't wired into a scheduler yet, so expired/spent auth records only
  get cleaned up when run by hand. Scheduling is planned before any
  real deployment.
- **Manual review pass** — a style, modularity, and readability review
  of the codebase is planned before any real deployment (tracked in
  [#59](https://github.com/Celshade/RentMeBro/issues/59)).

## Features

**Billing**
- Leases with documents and term
- Rent revisions with effective dates
- Monthly billing periods
- Invoice generation — combined, rent-only, or gas-only
- Line items with recompute

**Gas / mileage add-on (optional)**
- `MileageProfile` — one-way commute miles and MPG
- `GasPriceEntry` — effective-dated weekly gas prices
- `DrivenDayLog` — driven / day-off / other-ride, with half-day fractions
- From-scratch calendar UI (no third-party calendar library)

**Payments**
- Stripe Cash App Pay
- Stripe Connect Standard, per-landlord payouts
- Bitcoin payment via mempool.space address watching
- Multi-round / partial settlements (`InvoiceSettlement`)
- Per-line-item payment locks
- Webhook handling for both platform and Connect events

**Auth**
- Passwordless magic-link login
- Role-scoped accounts (landlord / renter)
- JWT access/refresh tokens
- Throttled magic-link endpoints

## Tech stack

- **Backend**: Python 3.12 + Django 6 + Django REST Framework + drf-spectacular +
  SimpleJWT, Postgres (SQLite for local dev)
  - managed with `uv`
- **Frontend**: React 19 + TypeScript + Vite, `oxlint`,
  `@stripe/react-stripe-js`

## Project structure

```
backend/
  src/
    config/    # Django project settings, URLs
    accounts/  # auth, magic links, roles
    billing/   # leases, rent revisions, invoices, gas/mileage
    payments/  # Stripe Cash App Pay, Connect, BTC watching
frontend/
  src/
    api/         # HTTP client + endpoint wrappers
    auth/        # login/magic-link UI
    landlord/    # landlord dashboard, lease + invoice management
    renter/      # renter dashboard, payment UI
    invoices/    # shared invoice/payment components
    components/  # shared UI components
    theme/       # system/light/dark theme toggle
docker-compose.yml
```

## Getting started

### Local dev (SQLite, no Docker)

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

### Local dev (Docker)

```bash
docker compose up --build
```

This runs Postgres + backend (`:8000`) + frontend (`:5173`) together.
Switching the backend from SQLite to Postgres locally only requires setting
`DATABASE_URL` in `backend/.env` (see `.env.example`) — no code changes
needed, since `DATABASES` already reads it via django-environ.

The compose setup is written but not yet run/verified in this environment
(no Docker available here) — verify with `docker compose up` once Docker is
installed.

## Configuration

Environment variables are documented in `backend/.env.example` and
`frontend/.env.example`. Copy each to `.env` and fill in real values — never
commit `.env` itself in local builds or contribution PRs.

**Backend**

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django cryptographic signing key |
| `DEBUG` | Django debug mode |
| `DJANGO_ALLOWED_HOSTS` | Allowed `Host` header values |
| `CORS_ALLOWED_ORIGINS` | Allowed frontend origins |
| `FRONTEND_URL` | Base URL used in outgoing links (e.g. magic-link emails) |
| `DATABASE_URL` | Postgres connection string (unset = SQLite) |
| `EMAIL_BACKEND` | Django email backend (unset = console backend) |
| `DEFAULT_FROM_EMAIL` | From address for outgoing email |
| `STRIPE_SECRET_KEY` | Stripe secret API key |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable API key |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for the platform webhook endpoint |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Signing secret for the Connect webhook endpoint |
| `MEMPOOL_API_BASE_URL` | Base URL for the mempool.space REST API |

**Frontend**

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Backend API base URL |
| `VITE_STRIPE_PUBLISHABLE_KEY` | Stripe publishable API key |
| `VITE_MEMPOOL_BASE_URL` | mempool.space base URL, used for tx links |

## API docs

Interactive schema at `/api/schema/swagger/` (drf-spectacular). Route groups:

- `/api/auth/` — accounts, magic-link login
- `/api/leases/`, `/api/invoices/`, `/api/driven-days/` — billing
- `/api/payments/...` — Stripe and Bitcoin payment flows

## Testing

```bash
# backend
cd backend
uv run ruff check   # lint (line-length, quotes, annotations)
uv run pytest

# frontend
cd frontend
npm run lint    # oxlint
npm run build   # tsc -b && vite build
```

Backend test suites live under `src/{accounts,billing,payments}/tests/`.

## License

[PolyForm Noncommercial 1.0.0](LICENSE), source-available (not OSI-approved
open source):

- ✅ Study, modify, and contribute
- ✅ Personal use and self-hosting for noncommercial purposes, with no
  anticipated commercial application
- ❌ No commercial use — including selling derivatives or running
  RentMeBro (or a fork) as a paid or hosted service
- ℹ️ The creator and their business retain full commercial rights
- ℹ️ Commercial use requires a separate license from the creator

See [LICENSE](LICENSE) for the full text and the attribution requirements
that apply when redistributing.

Select components with standalone reuse value (currently: the P2P Bitcoin
payment-watching rail) are being considered for release under a separate
FOSS (Free and Open Source Software) license in the future, once they can
be cleanly separated from the rest of the codebase.

## Credits

Developer — Celshade
