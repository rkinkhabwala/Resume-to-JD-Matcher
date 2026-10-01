# JobFit

JobFit compares a candidate's resume with a job description and returns a match score, confidence, and an evidence-backed explanation.

## Features

- Resume upload for PDF, DOCX, and TXT inputs
- Job fetching via URL or pasted description
- Evidence-backed match scoring with confidence and requirement verdicts
- Async API submission and polling flow
- Streamlit UI for interactive review and JSON report download

## Quick start

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Add your provider credentials and model settings to `.env`.

3. Install dependencies:

   ```bash
   uv sync --all-groups
   ```

4. Start the API:

   ```bash
   uv run uvicorn api.app:app --host 0.0.0.0 --port 8000
   ```

5. Start the UI in a second terminal:

   ```bash
   JOBFIT_API_BASE_URL=http://localhost:8000 uv run streamlit run streamlit_app.py
   ```

## Docker

Build and run the full stack with Docker Compose:

```bash
cp .env.example .env
docker compose up --build
```

This starts:

- API on http://localhost:8000
- UI on http://localhost:8501
- Redis on http://localhost:6379
- Postgres on http://localhost:5432

## Environment variables

The project reads its runtime settings from environment variables. The defaults are documented in `.env.example` and include:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `LLM_MODEL`
- `LOG_LEVEL`
- `JOBFIT_API_KEY` for protected API access
- `JOBFIT_API_USER`
- `JOBFIT_DAILY_BUDGET_USD`

## Deployment notes

This project is designed for a simple container-based deployment model. The included Dockerfile is a multi-stage build with a non-root runtime user, and the Compose file provides the API, UI, Redis, and Postgres services needed for local delivery and preview environments.

For production, add a managed Postgres/Redis service, rotate secrets via your environment manager, and keep the OpenAI credentials out of source control.

## Quality gate

The project uses the following checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy jobfit
uv run pytest
```

The CI workflow also runs coverage, dependency auditing, and a Docker build.
