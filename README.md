# POBridge Backend

POBridge is an AI-powered purchase order processing and ERP automation application. This backend provides the API foundation for document ingestion, data extraction, and future ERP export workflows.

## Technology stack

- Python 3.12.11
- FastAPI and Uvicorn
- Pydantic v2 and pydantic-settings
- pytest and HTTPX

## Structure

```text
app/
├── api/v1/       # Versioned API routes
├── core/         # Central configuration
├── schemas/      # Pydantic request and response models
├── modules/      # Ingestion, extraction, and export feature modules
└── main.py       # FastAPI entry point
tests/            # Automated API tests
```

The feature modules are intentionally empty placeholders for later development phases.

## Local setup

Install Python 3.12.11 with pyenv if it is not already available. The checked-in `.python-version` makes pyenv select it automatically inside `pobridge_backend/`.

From `pobridge_backend/`, confirm the selected version, then create and activate a virtual environment:

```bash
python --version  # Python 3.12.11
python -m venv .venv
source .venv/bin/activate
```

Install the application and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Create the local environment file from the safe example:

```bash
cp .env.example .env
```

The default configuration works for local development. `OPENAI_API_KEY` and `OPENAI_MODEL` may remain empty because AI integration is not enabled yet. Never commit credentials or the `.env` file.

## Run the API

```bash
uvicorn app.main:app --reload
```

The API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs), and the health endpoint is available at [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health).

## Run tests

```bash
pytest
```

Tests run locally without databases, external services, or API credentials.
