# India Market Master

Milestone M0 is a local settings and safety shell. It loads configuration, records audit events, and refuses live orders. It does not forecast, value options, or place broker orders.

## What you need

- Docker, for Postgres, the API, and the settings page
- No Groww account or token

## Start

```bash
cp .env.example .env
# Set OPERATOR_PASSWORD and SESSION_SECRET in .env.
# Leave LIVE_ORDER_SERVER_FLAG=false.
docker compose up --build
```

- API health: http://localhost:8000/health
- Settings: http://localhost:3000

Sign in with `OPERATOR_PASSWORD`. The default operating mode is `PAPER`. The live-order server flag stays off, so the settings page cannot place an order.

## Run the backend and the frontend

Local development runs three processes: Postgres, the API, and the Next.js desk. Start them in that order. The API reads `DATABASE_URL`, `SESSION_SECRET`, and `OPERATOR_PASSWORD` from the repository `.env`.

Sign-in writes a session row, so it fails while Postgres is stopped. `GET /health` still answers; read `"database": true` in that body before signing in. `"database": false` means the API is up and the database is not.

### Each time you start

1. Postgres on port 5432:

```bash
docker compose up -d postgres
```

If the container already exists and is stopped, `docker start stock_market_analysis-postgres-1` does the same thing. Wait until it accepts connections:

```bash
docker exec stock_market_analysis-postgres-1 pg_isready -U imm -d imm
```

2. API, from the repository root, with the virtualenv active:

```bash
. .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8014
```

Leave that terminal running. Health: http://127.0.0.1:8014/health

3. Desk, in a second terminal:

```bash
cd apps/web
API_URL=http://127.0.0.1:8014 npm run dev -- --hostname 127.0.0.1 --port 3000
```

Desk: http://127.0.0.1:3000

Sign in with the `OPERATOR_PASSWORD` value from `.env`. There is no username field until an operator account is stored. After the migration below, http://127.0.0.1:3000/signup creates that account once. Later sign-ins use the stored username and password.

### First time on this machine

```bash
cp .env.example .env
# Set OPERATOR_PASSWORD and SESSION_SECRET in .env.
# Leave LIVE_ORDER_SERVER_FLAG=false.
python3 -m venv .venv
. .venv/bin/activate
pip install -e "apps/api[dev]"
docker compose up -d postgres
cd apps/api
alembic upgrade head
cd ../web
npm install
```

`alembic upgrade head` creates the tables, including `operator_accounts`. Postgres from `.env.example` is `localhost:5432`. Then use the three start steps above. The API command stays at the repository root after `alembic`; the migration command stays in `apps/api`, where `alembic.ini` lives.

## API integrations

Settings → API integrations is `http://localhost:3000/settings/integrations`. It stores Groww and OpenAI credentials in Postgres as Fernet ciphertext. The encryption key is `INTEGRATIONS_SECRET_KEY` in `.env`. The application does not generate or commit that key. Read endpoints return configured/not-configured and the last connection-test result. They do not return secret values.

Saving credentials does not test them. Use the test buttons. Groww's test is `GET /v1/margins/detail/user`. OpenAI's test is `GET /v1/models/{model}`. Neither test places an order or requests a forecast. Live trading stays disabled.

## Run the API tests

The tests use Postgres on port 54329 and do not call Groww.

```bash
docker run -d --name imm-m0-test-pg \
  -e POSTGRES_USER=imm -e POSTGRES_PASSWORD=imm -e POSTGRES_DB=imm \
  -p 54329:5432 postgres:16.6
python3 -m venv .venv
. .venv/bin/activate
pip install -e "apps/api[dev]"
cd apps/api
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  DATABASE_URL=postgresql+psycopg://imm:imm@localhost:54329/imm \
  pytest
```

The design for the model registry, Forecast Model Studio, and LangGraph evidence workflow is in `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md` and `docs/LANGGRAPH_ORCHESTRATION_SPEC.md`. Those parts are not built in M0.

## Research desk

The web app also serves local research pages: Dashboard, Data, Analysis, Forecasts, Walk-forward, Options, Risk, Paper, Registry, and Health. They read the local API. They do not place orders. Paper trading stays disabled. Verified live prices are not shown.

`GET /api/research/status` requires a signed-in session. It reports the kill switch only when the row was read. A missing switch is not reported as off. Risk capital stays null until an operator sets it.

## UI & Trading Desk Walkthrough

A comprehensive, canonical walkthrough of every page, view mode, button, toggle, dropdown, metric card, and status indicator is maintained at:
- **[`docs/UI_WALKTHROUGH.md`](docs/UI_WALKTHROUGH.md)**

Whenever UI components in `apps/web` are updated, this document must be updated concurrently (enforced by `.agents/rules/ui-documentation.md` and `AGENTS.md`).

Start the API and the desk with the commands in **Run the backend and the frontend**. `LIVE_ORDER_SERVER_FLAG` stays false. Do not set `PAPER_TRADING_ACTIVE`.

```bash
cd apps/web
node --test app/research/status.test.mjs app/settings/integrations/labels.test.mjs
npm run build
```

## Not finished

M10 paper fills are not persisted. M11 and later milestones are not started. Quarantined Groww candles are not trusted market data. The timestamp contract is not verified.

`cursor-sdk` is not required to run the desk.
