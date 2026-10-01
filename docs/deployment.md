# Deployment guide

This project is designed to run as a small containerized service with a web UI, an API, Redis, and Postgres.

## Render deployment

1. Create a new Web Service for the API using the repository root.
2. Set the build command to:

   ```bash
   docker build -t jobfit .
   ```

3. Set the start command to:

   ```bash
   uv run uvicorn api.app:app --host 0.0.0.0 --port 10000
   ```

4. Add environment variables from `.env.example`.
5. Provision a managed Postgres instance and a Redis instance.
6. In the UI service, point `JOBFIT_API_BASE_URL` at the public API URL.

## Environment checklist

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `LLM_MODEL`
- `JOBFIT_API_KEY`
- `JOBFIT_API_USER`
- `JOBFIT_DAILY_BUDGET_USD`
- `LOG_LEVEL`

## Production recommendations

- Keep secrets in your deployment platform's secret manager.
- Enable autoscaling only after measuring the queue and LLM latency.
- Add a health check on `/ready`.
- Surface the UI behind a reverse proxy or managed external app gateway.
