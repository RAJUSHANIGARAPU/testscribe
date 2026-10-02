# TestScribe

TestScribe is a FastAPI service that turns user stories, requirements text and OpenAPI specs into draft test cases. It sends the input to the Anthropic Messages API with a QA-oriented prompt and returns the result as Gherkin `.feature` scenarios, a Markdown test table, or pytest stubs.

## Status

- **Self-hosted only.** There is no hosted version running: no public domain is live and no Fly.io app is deployed. Run it locally or on your own infrastructure.
- **The JSON API works.** The test suite passes and the server starts from `.env.example`; `/health`, registration, login and the generation endpoints respond.
- **Long inputs are processed in the background.** Inputs of 3,000 characters or more return `202 Accepted` with a `pending` generation; a worker started with the app processes it, so poll `GET /generations/{id}` until it is `completed` or `failed`. A failed attempt is retried up to three times with backoff before the generation is marked `failed`.
- **The HTML pages are static shells.** `/`, `/demo`, `/dashboard`, `/pricing` and `/docs-page` render, but there is no HTML login: `/demo` and `/dashboard` call the JSON API with an access token stored as `ts_access_token` in the browser's localStorage. Links to checkout and login point at JSON endpoints.
- **Billing code is present but not in use.** The code has Stripe checkout, webhooks and per-plan monthly limits (the `free` plan allows 25 generations a month). The Stripe settings are required for the app to start, but placeholder values are enough as long as you don't call the billing endpoints.

## What it does

- Accepts five input types: `user_story`, `requirement`, `openapi`, `jira_text`, `raw`
- Produces three output formats: `gherkin`, `tabular`, `pytest`
- Prompts the model to cover happy paths, boundary values, negative cases and common security cases
- Processes inputs under 3,000 characters within the request; longer inputs go to a background queue
- Stores generation history with status, latency and token counts
- Authenticates with JWT access/refresh tokens or long-lived API keys (bcrypt-hashed, `tsc_` prefix)
- Retries model calls and wraps them in a circuit breaker; applies per-IP and per-user rate limits

## Run locally

Requires Python 3.12 (the version CI uses) and an Anthropic API key to actually generate anything.

```bash
git clone https://github.com/RAJUSHANIGARAPU/testscribe.git
cd testscribe
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Set JWT_SECRET_KEY to a random string of 32+ characters:
#   python -c "import secrets; print(secrets.token_hex(32))"
# Set ANTHROPIC_API_KEY to a real key if you want generations to succeed.
# The Stripe placeholders can stay as they are.

make dev          # uvicorn with reload on http://localhost:8000
curl http://localhost:8000/health
```

Database tables are created automatically on startup (SQLite file `./testscribe.db` by default). Set `DEBUG=true` in `.env` to enable the interactive API docs at `http://localhost:8000/api/docs`.

### Tests

```bash
make test         # or just: pytest
```

The tests use in-memory SQLite and mock the Anthropic and Stripe clients, so they need no network access or keys. `pytest.ini` enforces at least 80% coverage. `make lint` runs ruff; CI fails on any finding.

### Docker

```bash
cp .env.example .env    # fill in as above
# Put the database on the mounted volume so it survives restarts:
#   DATABASE_URL=sqlite:////data/testscribe.db
make build              # docker build -t testscribe .
make run                # docker-compose up -d
curl http://localhost:8080/health
```

## Example

```bash
# Register (returns an access token and a refresh token)
curl -s -X POST localhost:8000/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"me@example.com","password":"Str0ngPass!word1"}'

# Submit a generation (inputs under 3,000 characters return the result directly)
curl -s -X POST localhost:8000/generations \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"input_type":"user_story","output_format":"gherkin",
       "input_text":"As a user I want to reset my password via an emailed link that expires in 30 minutes."}'

# Fetch a stored generation by ID
curl -s localhost:8000/generations/$GENERATION_ID -H "Authorization: Bearer $ACCESS_TOKEN"
```

## API reference

Authenticated endpoints accept either `Authorization: Bearer <jwt>` or `X-API-Key: tsc_<key>`. Paths are relative to the server root; there is no version prefix.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check, including a database ping |
| `GET` | `/health/ready` | Readiness check |
| `POST` | `/auth/register` | Create an account; returns a token pair |
| `POST` | `/auth/login` | Exchange email and password for a token pair |
| `POST` | `/auth/refresh` | Exchange a refresh token for a new access token |
| `POST` | `/auth/logout` | Revoke the current refresh token |
| `GET` | `/auth/me` | Current user |
| `GET` / `POST` | `/api-keys` | List or create API keys |
| `DELETE` | `/api-keys/{key_id}` | Revoke an API key |
| `POST` | `/generations` | Submit input for test case generation |
| `GET` | `/generations` | List your generations (paginated) |
| `GET` / `DELETE` | `/generations/{gen_id}` | Fetch or delete a generation |
| `GET` | `/usage` | Usage for the current month against the plan limit |
| `POST` | `/billing/checkout` | Create a Stripe Checkout session (needs real Stripe keys) |
| `GET` | `/billing/portal` | Redirect to the Stripe Customer Portal (needs real Stripe keys) |
| `GET` | `/billing/subscription` | Current subscription |
| `POST` | `/billing/webhook` | Stripe webhook receiver |
| `GET` | `/admin/stats` | Aggregate stats (admin role only) |

## Configuration

All settings are read from environment variables or `.env`. See `.env.example` for a complete template.

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_NAME` | No | `TestScribe` | Application display name |
| `APP_ENV` | No | `development` | `development`, `staging` or `production` |
| `APP_URL` | No | `http://localhost:8000` | Public base URL, used for Stripe redirect URLs |
| `DEBUG` | No | `false` | Verbose errors and the `/api/docs` page |
| `LOG_LEVEL` | No | `INFO` | `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `DATABASE_URL` | No | `sqlite:///./testscribe.db` | SQLAlchemy URL; use `postgresql+asyncpg://...` for PostgreSQL |
| `JWT_SECRET_KEY` | **Yes** | — | JWT signing secret, at least 32 characters |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `30` | Refresh token lifetime |
| `ANTHROPIC_API_KEY` | **Yes** | — | Anthropic API key; a placeholder lets the app start, but generations fail |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-20250514` | Model ID used for generation |
| `ANTHROPIC_MAX_TOKENS` | No | `2000` | Maximum tokens in the model response |
| `ANTHROPIC_TIMEOUT` | No | `60.0` | Timeout in seconds for model API calls |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | No | `5` | Consecutive failures before the circuit breaker opens |
| `CIRCUIT_BREAKER_RECOVERY_SECONDS` | No | `60.0` | Seconds before the circuit breaker tries again |
| `STRIPE_SECRET_KEY` | **Yes** | — | Stripe secret key (placeholder is fine if billing is unused) |
| `STRIPE_PUBLISHABLE_KEY` | **Yes** | — | Stripe publishable key |
| `STRIPE_WEBHOOK_SECRET` | **Yes** | — | Stripe webhook signing secret |
| `STRIPE_PRICE_SOLO` | **Yes** | — | Stripe Price ID for the `solo` plan |
| `STRIPE_PRICE_PRO` | **Yes** | — | Stripe Price ID for the `pro` plan |
| `STRIPE_PRICE_TEAM` | **Yes** | — | Stripe Price ID for the `team` plan |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:8000` | Comma-separated allowed CORS origins |
| `RATE_LIMIT_IP` | No | `60/minute` | Global per-IP rate limit |
| `RATE_LIMIT_GENERATE` | No | `20/minute` | Per-user rate limit on generation |
| `TASK_POLL_INTERVAL` | No | `2.0` | Seconds between background worker polls |
| `TASK_REAPER_INTERVAL` | No | `300.0` | Seconds between stale-task cleanup runs |
| `PORT` | No | `8080` | Listening port inside the Docker image |

## Architecture

A FastAPI application on SQLAlchemy. `POST /generations` validates the request, checks the user's monthly limit and stores a `pending` record. For inputs under 3,000 characters it then calls the Anthropic API in the same request (with `tenacity` retries and a circuit breaker) and stores the output, token counts and latency. Longer inputs are written to a `TaskQueue` table. The app lifespan starts a worker from `app/tasks.py` that claims queued tasks (a conditional update, so the two uvicorn processes in the Docker image never run the same task) and a reaper that fails or re-queues tasks stuck in `running`. Data lives in one SQLite file by default; the schema also works on PostgreSQL by changing `DATABASE_URL`.

## Repository layout

| Path | Contents |
|---|---|
| `app/` | Application code: `main.py` (routes), `ai.py` (prompting and model client), `tasks.py` (background worker), `limits.py` (plan limits), `billing.py` (Stripe) |
| `app/templates/` | HTML pages (Jinja), see Status |
| `tests/` | pytest suite |
| `fly.toml` | Fly.io config; no Fly app is deployed from it and CI does not deploy |
| `COPY.md`, `SEO.md`, `ONBOARDING.md` | Marketing and email drafts for a hosted version that was never launched; the URLs and prices in them are not live |

## License

MIT, see [LICENSE](LICENSE).
