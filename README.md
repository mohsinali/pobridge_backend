# POBridge Backend

POBridge is an AI-powered purchase order processing and ERP automation application. This backend provides the API foundation for document ingestion, data extraction, and future ERP export workflows.

## Technology stack

- Python 3.12.11
- FastAPI and Uvicorn
- Pydantic v2 and pydantic-settings
- OpenAI Python SDK using the Responses API
- PyMuPDF for defensive PDF inspection
- pytest and HTTPX
- SQLite for local integration persistence and Fernet authenticated encryption

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

## Outlook OAuth integration

Register a Microsoft identity platform web application with support for both
organizational and personal Microsoft accounts. Add the exact callback URL as a web
redirect URI, then configure:

```env
MICROSOFT_CLIENT_ID=your-application-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
MICROSOFT_AUTHORITY=https://login.microsoftonline.com/common
MICROSOFT_REDIRECT_URI=http://localhost:8000/api/v1/integrations/outlook/callback
INTEGRATION_ENCRYPTION_KEY=your-fernet-key
INTEGRATION_DATABASE_PATH=data/integrations.db
INTEGRATION_COOKIE_SECURE=false
OAUTH_TRANSACTION_TTL_SECONDS=600
```

Generate a new encryption key once and keep it stable alongside the other local
secrets. Changing it makes existing encrypted credentials unreadable:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The integration requests delegated `openid`, `profile`, `email`, `User.Read`,
`Mail.Read`, and `offline_access` scopes using Authorization Code Flow with PKCE. The
frontend starts the flow at `GET /api/v1/integrations/outlook/connect`; callback,
status, and disconnect are exposed under the same route prefix. Tokens are never
returned by the API and are stored encrypted in the local SQLite database.

This is intentionally a single-user local-development integration, not an
authentication system. The first browser session to connect owns the sole Outlook
record through a high-entropy HttpOnly, SameSite cookie; other sessions cannot inspect,
replace, or disconnect it, and disconnect additionally requires the configured frontend
Origin. Run only on a trusted loopback machine. For plain HTTP localhost,
`INTEGRATION_COOKIE_SECURE=false` is necessary; set it to `true` whenever the backend is
served over HTTPS. A production deployment still requires real user authentication,
per-user ownership, HTTPS, a managed database, and managed secret/key storage.

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
