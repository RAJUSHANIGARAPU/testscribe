# TestScribe

TestScribe is an AI-powered test case generation service that converts user stories, requirements documents, and OpenAPI specifications into comprehensive test cases in seconds. Built on top of Claude (Anthropic), it understands QA best practices and automatically covers happy paths, boundary conditions, security scenarios, and edge cases — producing output in Gherkin BDD, tabular, or pytest formats that you can paste directly into your tools.

The service is a FastAPI application backed by SQLAlchemy (SQLite for local use, PostgreSQL for production), with JWT + API key authentication, Stripe billing, and an async generation pipeline. It ships as a single Docker image and deploys to Fly.io with one command. Free users get 25 generations per month with no credit card required; paid plans unlock higher limits, all output formats, OpenAPI input, and programmatic API access.

## Features

- Generate Gherkin BDD `.feature` files, Markdown test tables, and pytest stubs from a user story in under 10 seconds
- Supports five input types: user story, requirements document, OpenAPI spec, Jira text, raw text
- Automatic coverage of happy path, boundary values, negative cases, and security scenarios (injection, auth bypass, rate limiting)
- Three subscription tiers: Free (25/mo), Solo ($19/mo, 200/mo), Pro ($49/mo, 600/mo)
- REST API with API key authentication for CI/CD integration (Pro plan)
- Generation history with replay, status tracking, and token usage reporting
- Stripe-powered billing with webhook-driven subscription management
- SQLite for local development; PostgreSQL-ready for production
- Docker + Fly.io deployment with persistent volume for the database

## Quick Start

```bash
# 1. Clone and install
git clone git@github.com:RAJUSHANIGARAPU/testscribe.git
cd testscribe
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in: JWT_SECRET_KEY, ANTHROPIC_API_KEY, and Stripe keys

# 3. Start the server (creates DB tables automatically on first run)
make dev
# → http://localhost:8000
```

To run with Docker:

```bash
make build
make run          # docker-compose up -d
open http://localhost:8080
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_NAME` | No | `TestScribe` | Application display name |
| `APP_ENV` | No | `development` | Environment: `development`, `staging`, `production` |
| `APP_URL` | No | `http://localhost:8000` | Public base URL (used in email links and Stripe redirect URLs) |
| `DEBUG` | No | `false` | Enable debug mode and verbose error responses |
| `LOG_LEVEL` | No | `INFO` | Log level: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `DATABASE_URL` | No | `sqlite:///./testscribe.db` | SQLAlchemy database URL. Use `postgresql+asyncpg://...` for production |
| `JWT_SECRET_KEY` | **Yes** | — | JWT signing secret, minimum 32 characters |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `15` | Access token TTL in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `30` | Refresh token TTL in days |
| `ANTHROPIC_API_KEY` | **Yes** | — | Anthropic API key for Claude access |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-20250514` | Claude model ID to use for generation |
| `ANTHROPIC_MAX_TOKENS` | No | `2000` | Maximum tokens in the AI response |
| `ANTHROPIC_TIMEOUT` | No | `60.0` | Timeout in seconds for Anthropic API calls |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | No | `5` | Consecutive failures before opening the circuit breaker |
| `CIRCUIT_BREAKER_RECOVERY_SECONDS` | No | `60.0` | Seconds before attempting to close the circuit breaker |
| `STRIPE_SECRET_KEY` | **Yes** | — | Stripe secret key (`sk_live_...` or `sk_test_...`) |
| `STRIPE_PUBLISHABLE_KEY` | **Yes** | — | Stripe publishable key (`pk_live_...` or `pk_test_...`) |
| `STRIPE_WEBHOOK_SECRET` | **Yes** | — | Stripe webhook signing secret (`whsec_...`) |
| `STRIPE_PRICE_SOLO` | **Yes** | — | Stripe Price ID for the Solo plan |
| `STRIPE_PRICE_PRO` | **Yes** | — | Stripe Price ID for the Pro plan |
| `STRIPE_PRICE_TEAM` | **Yes** | — | Stripe Price ID for the Team plan (future) |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:8000` | Comma-separated list of allowed CORS origins |
| `RATE_LIMIT_IP` | No | `60/minute` | Global per-IP rate limit |
| `RATE_LIMIT_GENERATE` | No | `20/minute` | Per-user rate limit on the generation endpoint |
| `TASK_POLL_INTERVAL` | No | `2.0` | Seconds between generation status polls (async worker) |
| `TASK_REAPER_INTERVAL` | No | `300.0` | Seconds between stale task cleanup runs |
| `PORT` | No | `8080` | Listening port (used by Docker / Fly.io) |

## API Quick Reference

All requests require `X-API-Key: tsc_<your_key>` or `Authorization: Bearer <jwt>`.

Base URL: `https://testscribe.ai/api/v1`

| Method | Path | Description |
|---|---|---|
| `POST` | `/generations` | Submit a user story or spec for test case generation |
| `GET` | `/generations/{id}` | Get a single generation by ID (use for polling) |
| `GET` | `/generations` | List your recent generations (paginated) |
| `GET` | `/usage` | Check current month usage and plan limits |
| `POST` | `/auth/register` | Register a new user account |
| `POST` | `/auth/login` | Obtain a JWT access/refresh token pair |
| `POST` | `/auth/refresh` | Exchange a refresh token for a new access token |
| `POST` | `/billing/checkout` | Create a Stripe Checkout session |
| `POST` | `/billing/portal` | Open Stripe Customer Portal for self-service billing |
| `POST` | `/billing/webhook` | Stripe webhook receiver (Stripe calls this directly) |

## Deployment

### Fly.io (recommended)

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Authenticate
fly auth login

# Create the app (first time only)
fly launch --no-deploy

# Create the persistent volume (first time only)
fly volumes create testscribe_data --region ams --size 3

# Set all required secrets
fly secrets set \
  JWT_SECRET_KEY="$(openssl rand -hex 32)" \
  ANTHROPIC_API_KEY="sk-ant-..." \
  STRIPE_SECRET_KEY="sk_live_..." \
  STRIPE_PUBLISHABLE_KEY="pk_live_..." \
  STRIPE_WEBHOOK_SECRET="whsec_..." \
  STRIPE_PRICE_SOLO="price_..." \
  STRIPE_PRICE_PRO="price_..." \
  STRIPE_PRICE_TEAM="price_..." \
  DATABASE_URL="sqlite:////data/testscribe.db" \
  APP_ENV="production" \
  APP_URL="https://testscribe.fly.dev"

# Deploy
fly deploy

# Initialise the database on first deploy
fly ssh console -C "python -c \"from app.database import init_db; init_db(); print('Done')\""

# View logs
fly logs

# List secrets (names only, values hidden)
make secrets
```

### Docker (self-hosted)

```bash
# Build
docker build -t testscribe .

# Run with docker-compose
cp .env.example .env   # fill in your secrets
docker-compose up -d

# Check health
curl http://localhost:8080/health
```

## Architecture

TestScribe is a single-process FastAPI application using SQLAlchemy with an async engine. Incoming generation requests are validated, written to the database with `status=pending`, and handed to an in-process background worker that calls the Anthropic API, then updates the record with the result. A circuit breaker (via `tenacity`) wraps all Anthropic calls to handle transient failures gracefully. Authentication supports both short-lived JWT access tokens (refreshed via a 30-day refresh token) and long-lived API keys stored as bcrypt-hashed prefixed tokens. Billing is handled entirely by Stripe Checkout and the Customer Portal; plan changes are applied synchronously via webhook. The application stores all data in a single SQLite file in `/data` for simplicity — the schema is portable to PostgreSQL by changing `DATABASE_URL` to an `asyncpg` connection string.

## License

MIT — see [LICENSE](LICENSE).
