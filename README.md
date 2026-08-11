# RentMeBro

Rent + utility billing for small and independent landlords. Renters pay by
Cash App Pay (via Stripe) or on-chain Bitcoin; landlords are paid out through
Stripe Connect Standard. An optional mileage-based gas/utility add-on bills a
renter for driving days at a per-week gas price.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Django](https://img.shields.io/badge/Django-6.0-092E20)
![React](https://img.shields.io/badge/React-19-61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-blue)
![Vite](https://img.shields.io/badge/Vite-8-646CFF)
![Stripe](https://img.shields.io/badge/Stripe-Cash%20App%20Pay-635BFF)
![Bitcoin](https://img.shields.io/badge/Bitcoin-on--chain-F7931A)
![Status](https://img.shields.io/badge/Status-Alpha-orange)
![License](https://img.shields.io/badge/License-GPL--3.0%20%2B%20Commons%20Clause-purple)

## Status

Early-stage and not deployed. This is a portfolio/learning project first; use
it at your own risk.

Permitted uses under the [LICENSE](LICENSE):
- ✅ Personal use / self-hosting for your own rentals
- ✅ Education and portfolio use
- ✅ Contributions back to this repository
- ❌ Commercial use or selling derivatives

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
commit `.env` itself.

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
uv run pytest

# frontend
cd frontend
npm run lint    # oxlint
npm run build   # tsc -b && vite build
```

Backend test suites live under `src/{accounts,billing,payments}/tests/`.

## License

GPL-3.0 with a [Commons Clause](LICENSE):

- ✅ Study, modify, and contribute
- ✅ Personal use and self-hosting for your own rentals
- ❌ No commercial use or resale of derivatives
- ℹ️ The creator and their business retain full commercial rights

See [LICENSE](LICENSE) for the full text.

## Credits

Developer — Celshade
