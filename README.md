# POBridge Backend

POBridge is an AI-powered purchase order processing and ERP automation application. This backend provides the API foundation for document ingestion, data extraction, and future ERP export workflows.

## Technology stack

- Python 3.12.11
- FastAPI and Uvicorn
- Pydantic v2 and pydantic-settings
- OpenAI Python SDK using the Responses API
- PyMuPDF for defensive PDF inspection
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

The extraction module accepts one validated PDF, calls a replaceable AI provider once,
and returns typed purchase-order data with deterministic and model-reported warnings.

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

Set these extraction values in `.env`:

```env
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-6-luna
MAX_UPLOAD_SIZE_MB=10
MAX_PDF_PAGES=25
OPENAI_TIMEOUT_SECONDS=90
```

`gpt-6-luna` is the documented default because this is a focused, cost-sensitive
extraction workload. The model remains configurable so accuracy and cost can be
benchmarked without code changes. A missing API key does not affect application startup
or health checks; only the extraction endpoint returns a configuration error. Never
commit credentials or the `.env` file.

## Run the API

```bash
uvicorn app.main:app --reload
```

The API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs), and the health endpoint is available at [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health).

## Extract a purchase order

The endpoint accepts one PDF of at most 10 MB and 25 pages by default. It validates the
extension, MIME type, PDF signature, parseability, encryption state, and page count
before calling OpenAI. Decimal quantities and money values are returned as JSON strings.

```bash
curl --fail-with-body \
  -X POST http://localhost:8000/api/v1/purchase-orders/extract \
  -H 'Accept: application/json' \
  -F 'file=@/absolute/path/to/sample-po.pdf;type=application/pdf'
```

For an optional manual integration test, add a real `OPENAI_API_KEY` to `.env`, start
Uvicorn, and run the command above with a non-sensitive sample PO. This is the only test
that incurs API usage; the automated suite injects fake providers and makes no paid calls.

## Run tests

```bash
pytest
```

Tests run locally without databases, external services, or API credentials.

## MVP limitations

Extraction is synchronous and uses the source PDF as provided. There is no OCR
preprocessing, rotation correction, persistence, retry queue, ERP matching, pricing
validation, or automatic total calculation. Scanned or visually difficult documents may
therefore extract less accurately and should be evaluated with representative samples.
