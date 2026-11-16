# POBridge

AI-assisted purchase-order PDF extraction with a local Microsoft Outlook inbox integration.

> Source audit: 17 November 2026. This README describes the code currently present in `pobridge_backend/` and `pobridge_frontend/`. Planned capabilities are labelled explicitly.

## Table of contents

- [What POBridge does](#what-pobridge-does)
- [Current status](#current-status)
- [Architecture and workflows](#architecture-and-workflows)
- [Technology stack](#technology-stack)
- [Repository layout](#repository-layout)
- [Environment variables](#environment-variables)
- [New-client setup](#new-client-setup)
- [Microsoft Entra ID and Graph](#microsoft-entra-id-and-graph)
- [OpenAI extraction](#openai-extraction)
- [API reference](#api-reference)
- [Security, data, and operations](#security-data-and-operations)
- [Troubleshooting](#troubleshooting)
- [Known limitations and roadmap](#known-limitations-and-roadmap)

## What POBridge does

POBridge accepts one purchase-order PDF, validates it, sends it to an OpenAI structured-output workflow, and presents the extracted data in a Next.js UI. A user can also connect one Microsoft 365, Outlook.com, or Hotmail mailbox, view connection status, and list summaries for the latest 20 inbox messages.

The extraction contract includes:

- PO number, PO date, and requested delivery date
- Customer, bill-to, and ship-to details
- Line number, part number, description, quantity, UOM, unit price, and line total
- Carrier, shipping method, third-party account, and shipping notes
- Subtotal, tax, shipping cost, grand total, and currency
- Deterministic and model-reported warnings plus processing metadata

Missing source values remain `null`. Quantities and money values serialize as decimal strings, preserving decimal precision; identifiers such as part numbers remain strings so leading zeroes can be retained.

POBridge does **not** currently download email attachments, extract POs from email automatically, write to an ERP, authenticate application users, or isolate multiple tenants.

## Current status

| Capability | Status | Implementation boundary |
| --- | --- | --- |
| PDF upload and defensive validation | Implemented | One `.pdf`; MIME/signature, encryption, parseability, size, and page count checked |
| OpenAI structured PO extraction | Implemented | One Responses API call after validation; no paid call occurs for rejected PDFs |
| Results UI and warnings | Implemented | Displays structured fields, warnings, and metadata |
| JSON download | Implemented | Downloads the complete, unmodified backend response in the browser |
| CSV export | Planned | Button is present but disabled |
| Outlook connect, status, and disconnect | Implemented | Delegated OAuth, single connection, browser-session ownership |
| Outlook inbox summaries | Implemented | Latest 20 messages; sender, subject, received time, and attachment flag |
| Access-token refresh | Implemented | Refreshes shortly before expiry or once after a Graph `401` |
| Email body or attachment retrieval | Not implemented | `hasAttachments` is metadata only |
| Automatic mailbox monitoring | Not implemented | No polling worker, scheduled task, or Graph webhook |
| Email-to-extraction workflow | Not implemented | Manual PDF upload is the only extraction entry point |
| Persistent PO history | Not implemented | Extraction responses and uploaded PDFs are not stored by the app |
| ERP validation/export/import | Not implemented | No ERP connector or acknowledgement workflow |
| Application login / multi-tenancy | Not implemented | The Outlook cookie is connection ownership, not user authentication |

## Architecture and workflows

```text
Browser: Next.js 16 / React 19
  |-- Manual PDF upload -------------------------------+
  |                                                    |
  |-- Results rendering + client-side JSON download    v
  |                                             FastAPI 0.115
  |                                                    |
  |                                      PDF validation (PyMuPDF)
  |                                                    |
  |                                      OpenAI Responses API
  |                                      structured Pydantic output
  |
  +-- Email Integrations UI ---------------------------+
                                                       |
                                           Outlook OAuth routes
                                              |               |
                            Microsoft identity platform   SQLite
                                              |        encrypted tokens
                                              v
                                      Microsoft Graph `/me`
                                      and inbox messages
```

### Manual extraction workflow

1. The browser performs lightweight extension/type/10 MB checks and uploads one multipart `file`.
2. The backend reads at most the configured size plus one byte, sanitizes the filename, and checks `.pdf`, exact `application/pdf` MIME type, `%PDF-` signature, encryption, corruption/repair, and page count.
3. A valid PDF is base64-encoded in memory and sent to the configured OpenAI model with `detail: low`, a strict Pydantic response format, and `store=False`.
4. Pydantic validates the structured response. The service adds deterministic missing-field/date warnings to model observations.
5. The API returns a UUID document ID, schema version `1.0`, structured PO, warnings, filename/model/timing/page metadata. The frontend renders it and can download the same response as JSON.

### Outlook workflow

1. `/connect` creates a high-entropy browser session, OAuth state, and PKCE verifier; the hashed state and encrypted verifier are stored in SQLite.
2. The browser is redirected to the Microsoft `/common` authorization endpoint for delegated consent.
3. The callback consumes the one-time state, exchanges the code, calls Graph `/me`, and stores encrypted access/refresh credentials against a hash of the browser session.
4. `/emails` reads the latest 20 inbox summaries. Expired tokens are refreshed and re-encrypted before use.
5. `/disconnect` deletes the local connection and cookie. It does **not** revoke consent or tokens at Microsoft.

## Technology stack

Versions are pinned by the current dependency manifests.

| Area | Current implementation |
| --- | --- |
| Backend runtime | Python `>=3.12.11,<3.13` (`.python-version`: 3.12.11) |
| API | FastAPI 0.115.12, Uvicorn 0.34.2, python-multipart 0.0.20 |
| Schemas/config | Pydantic 2.11.4, pydantic-settings 2.9.1 |
| AI | OpenAI Python SDK 3.49.0, Responses API structured parsing |
| PDF validation | PyMuPDF 1.26.6 |
| Microsoft HTTP | HTTPX 0.28.1, direct OAuth 2.0 and Graph REST calls |
| Secret encryption | cryptography 44.0.3 / Fernet |
| Integration storage | Python SQLite; schema initializes automatically |
| Frontend runtime | Node.js 20.19.6 (`.nvmrc`) |
| Frontend | Next.js 16.4.6 App Router, React 19.3.1, TypeScript 5.9.3 |
| Styling/UI | Tailwind CSS 4.3.5, Radix UI, Lucide React, Sonner |
| Tests | pytest 8.3.5; Vitest 3.2.7 and Testing Library |

## Repository layout

The workspace contains two independent Git repositories:

```text
pobridge/
├── README.md
├── pobridge_backend/
│   ├── app/
│   │   ├── api/v1/                 # Health, extraction, and Outlook routes
│   │   ├── core/config.py          # All backend environment settings
│   │   ├── modules/extraction/     # Prompt, provider, orchestration
│   │   ├── modules/ingestion/      # PDF validation
│   │   ├── modules/integrations/   # Microsoft client, OAuth service, crypto, SQLite
│   │   └── schemas/                # API and provider contracts
│   ├── tests/
│   ├── .env.example
│   └── pyproject.toml
└── pobridge_frontend/
    ├── src/app/                    # Extraction and email-integration pages
    ├── src/components/             # Shared shell and UI components
    ├── src/features/               # PO and Outlook features/services/tests
    ├── .env.example
    ├── package.json
    └── package-lock.json
```

## Environment variables

Do not copy values from a real `.env` into documentation or source control. Backend settings are case-sensitive. Pydantic ignores unknown variables.

### Backend: `pobridge_backend/.env`

| Variable | Required | Code default | Purpose / security notes |
| --- | --- | --- | --- |
| `APP_NAME` | No | `POBridge API` | OpenAPI title and health response application name |
| `APP_ENV` | No | `development` | Environment label; currently not used to switch behavior |
| `DEBUG` | No | `true` | Selects DEBUG vs INFO application logging |
| `API_V1_PREFIX` | No | `/api/v1` | Prefix for every API route and the Outlook cookie path |
| `FRONTEND_URL` | Yes for browser use | `http://localhost:3000` | Sole allowed CORS origin, OAuth result redirect base, and required disconnect `Origin`; no trailing slash needed |
| `OPENAI_API_KEY` | For extraction | unset | Server-only OpenAI credential. Startup and health still work without it; extraction returns `503` |
| `OPENAI_MODEL` | For extraction | `gpt-6-luna` | Model sent verbatim to OpenAI. Confirm the deployment account can use it; availability is not validated at startup |
| `MAX_UPLOAD_SIZE_MB` | No | `10` | Positive integer backend upload limit. The current frontend message/check remains fixed at 10 MB |
| `MAX_PDF_PAGES` | No | `25` | Positive integer page limit |
| `OPENAI_TIMEOUT_SECONDS` | No | `90.0` | Positive provider request timeout in seconds |
| `MICROSOFT_CLIENT_ID` | For Outlook | unset | Entra Application (client) ID |
| `MICROSOFT_CLIENT_SECRET` | For Outlook | unset | Entra client secret **Value**, not secret ID; server-only |
| `MICROSOFT_AUTHORITY` | For Outlook | `https://login.microsoftonline.com/common` | Code rejects any authority not ending in `/common` |
| `MICROSOFT_REDIRECT_URI` | For Outlook | `http://localhost:8000/api/v1/integrations/outlook/callback` | Must exactly match an Entra **Web** redirect URI |
| `INTEGRATION_ENCRYPTION_KEY` | For Outlook | unset | URL-safe Fernet key encrypting PKCE verifiers and OAuth tokens; loss makes stored credentials unreadable |
| `INTEGRATION_DATABASE_PATH` | No | `data/integrations.db` | SQLite path, resolved from the backend process working directory; parent/schema are auto-created |
| `INTEGRATION_COOKIE_SECURE` | No | `true` | `Secure` flag for the Outlook cookie. `.env.example` deliberately sets `false` for local HTTP only |
| `OAUTH_TRANSACTION_TTL_SECONDS` | No | `600` | OAuth state lifetime; integer greater than 0 and at most 1800 seconds |

Copy-ready local configuration:

```dotenv
APP_NAME=POBridge API
APP_ENV=development
DEBUG=true
API_V1_PREFIX=/api/v1
FRONTEND_URL=http://localhost:3000

OPENAI_API_KEY=replace-with-openai-api-key
OPENAI_MODEL=gpt-6-luna
MAX_UPLOAD_SIZE_MB=10
MAX_PDF_PAGES=25
OPENAI_TIMEOUT_SECONDS=90

MICROSOFT_CLIENT_ID=replace-with-application-client-id
MICROSOFT_CLIENT_SECRET=replace-with-client-secret-value
MICROSOFT_AUTHORITY=https://login.microsoftonline.com/common
MICROSOFT_REDIRECT_URI=http://localhost:8000/api/v1/integrations/outlook/callback
INTEGRATION_ENCRYPTION_KEY=replace-with-generated-fernet-key
INTEGRATION_DATABASE_PATH=data/integrations.db
INTEGRATION_COOKIE_SECURE=false
OAUTH_TRANSACTION_TTL_SECONDS=600
```

### Frontend: `pobridge_frontend/.env.local`

| Variable | Required | Default | Purpose / security notes |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | Yes | None | Browser-visible API v1 base URL, for example `http://localhost:8000/api/v1`; the code removes one trailing slash |

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

Never place OpenAI keys, Microsoft secrets, OAuth tokens, or the Fernet key in a `NEXT_PUBLIC_` variable.

## New-client setup

This sequence creates the currently supported **local single-user** deployment. POBridge has no verified production deployment manifests and is not safe to expose as a shared internet service without the hardening described below.

### 1. Confirm prerequisites and ownership

Required:

- Git and a checkout containing both component directories
- Python 3.12.11, Node.js 20.19.6, and npm
- An OpenAI account/project, API key, billing, and access to the configured model
- A client-owned Microsoft Entra app registration and a Microsoft 365/Outlook.com mailbox
- A client/tenant administrator available if app registration or consent is restricted
- Approval to send purchase-order documents to OpenAI and read mailbox metadata through Microsoft Graph

Record the client owner, environment, intended mailbox, Entra tenant/app IDs, callback URL, secret expiry owner, OpenAI project/model, data-handling approval, and backup owner. Never record secret values in the handover document.

### 2. Obtain the source

Use the actual organization URL. If the project is distributed as separate backend/frontend repositories, clone each into the directory names shown below.

```bash
git clone <pobridge-repository-url> pobridge
cd pobridge
```

Confirm both `pobridge_backend/pyproject.toml` and `pobridge_frontend/package-lock.json` exist.

### 3. Configure Python and the backend

```bash
cd pobridge_backend
python --version                         # Must be Python 3.12.x; 3.12.11 is pinned
python -m venv .venv
source .venv/bin/activate                # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

Edit `.env` with the values described above. Do not commit it.

### 4. Configure OpenAI

Set `OPENAI_API_KEY` to a server-side key and `OPENAI_MODEL` to the model this release was tested with. The checked-in default is `gpt-6-luna`; model availability depends on the OpenAI project/account and a missing or unavailable model is reported only when extraction is attempted.

No OpenAI call is needed to verify startup. A real extraction later in this guide consumes API quota and sends the uploaded PDF to OpenAI.

### 5. Create the client's Entra app

The **client/tenant administrator** should own this registration and its credentials.

1. In the [Microsoft Entra admin center](https://entra.microsoft.com), open **Identity → Applications → App registrations → New registration**.
2. Enter a client/environment-specific name.
3. Choose **Accounts in any organizational directory and personal Microsoft accounts**. This matches the code-enforced `/common` authority and supports Microsoft 365 plus personal Outlook accounts. A single-tenant setup requires a code change because the backend rejects a tenant-specific authority.
4. Add a redirect URI with platform **Web** and exact local value `http://localhost:8000/api/v1/integrations/outlook/callback`.
5. Copy the **Application (client) ID** to `MICROSOFT_CLIENT_ID`. Do not confuse it with the Directory (tenant) ID.
6. Under **Certificates & secrets → Client secrets → New client secret**, create a secret, securely capture its **Value** immediately, record its expiry/owner, and set `MICROSOFT_CLIENT_SECRET`. The current code supports a client secret only; certificate/federated credentials would require implementation work.

Microsoft recommends certificates or federated credentials instead of client secrets for production. See [app registration](https://learn.microsoft.com/en-us/graph/auth-register-app-v2) and [credential management](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-credentials).

### 6. Configure Graph delegated permissions and consent

In **API permissions → Add a permission → Microsoft Graph → Delegated permissions**, configure the scopes requested by the code:

| Scope | Why POBridge requests it |
| --- | --- |
| `openid` | OpenID Connect sign-in |
| `profile` | Basic identity claims |
| `email` | Email claim when available |
| `User.Read` | Read `/me` to identify the connected account |
| `Mail.Read` | Read the signed-in user's inbox messages |
| `offline_access` | Obtain a refresh token for continued delegated access |

Do not add application permissions: the implementation uses delegated authorization only. `Mail.Read` delegated reads the signed-in user's mailbox; shared mailbox behavior is not implemented or verified. Tenant policy may require an administrator to grant consent even where the permission does not require admin consent by default. See the [Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference).

### 7. Generate the encryption key and prepare storage

With the backend virtual environment active:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the output in the environment's secret manager and set `INTEGRATION_ENCRYPTION_KEY`. Keep a recoverable backup separate from the database. Never change this key while retaining the existing database unless a token re-encryption migration is implemented.

No migration command is required. When Outlook functionality is first initialized, the backend creates the SQLite parent directory, file, and two tables automatically, then attempts to set the database file mode to `0600`. Start the process from `pobridge_backend/` if using the default relative path.

### 8. Configure and install the frontend

In another terminal:

```bash
cd pobridge_frontend
nvm install 20.19.6                   # First use only
nvm use 20.19.6
node --version                        # v20.19.6
npm ci
cp .env.example .env.local
```

Keep `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1` for local use. Use `localhost` for both frontend and API; mixing it with `127.0.0.1` prevents the browser from sending the Outlook session cookie.

### 9. Start and verify both applications

Backend terminal:

```bash
cd pobridge_backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend terminal:

```bash
cd pobridge_frontend
nvm use 20.19.6
npm run dev
```

Verify:

```bash
curl --fail http://localhost:8000/api/v1/health
```

Expected shape: `{"status":"ok","application":"POBridge API","version":"..."}`. Open `http://localhost:8000/docs` and `http://localhost:3000`.

### 10. Connect and verify the mailbox

1. Open `http://localhost:3000/integrations/email` in the browser that will own the connection.
2. Click **Connect Outlook**, sign in to the intended mailbox, and consent. A tenant administrator must complete any tenant-required approval.
3. Confirm the UI shows **Connected** and the expected address.
4. Confirm **Inbox Emails** shows up to 20 newest messages, in descending received order. Use **Refresh Emails** to repeat the Graph call.
5. Verify attachment icons only indicate Graph's `hasAttachments` value. POBridge cannot open or process those attachments.
6. Refresh the page and confirm status persists in the same browser profile.

The status endpoint requires the HttpOnly connection cookie; a `401` before the first connect is expected. A different browser profile receives `403` while another browser owns the stored connection.

### 11. Test PDF extraction

Use a non-sensitive representative PDF. This is a live, paid OpenAI call.

```bash
curl --fail-with-body -X POST \
  http://localhost:8000/api/v1/purchase-orders/extract \
  -H 'Accept: application/json' \
  -F 'file=@/absolute/path/to/sample-po.pdf;type=application/pdf'
```

Expected: HTTP `200`, `status: "completed"`, `schema_version: "1.0"`, structured `data`, `warnings`, and `metadata`. In the UI, verify the source values, warnings, page count/model, and **Download JSON**. Do not treat AI output as ERP-approved data.

Also verify one safe rejection, such as a password-protected PDF, wrong MIME type, file over 10 MB, or file over 25 pages. Rejected inputs must not reach OpenAI.

### 12. Run targeted quality checks

External services are mocked by the automated suites; they do not make paid OpenAI calls or live Microsoft sign-ins.

```bash
# Backend
cd pobridge_backend
source .venv/bin/activate
pytest

# Frontend
cd ../pobridge_frontend
npm run test
npm run typecheck
npm run lint
```

### 13. Production decision gate and handover

There is no Dockerfile, deployment manifest, production database migration system, background worker, or production user-authentication layer in the audited source. Before any networked/shared deployment:

- Add real login, per-user/per-tenant authorization, and per-connection ownership.
- Terminate HTTPS and set `FRONTEND_URL`, `NEXT_PUBLIC_API_BASE_URL`, and `MICROSOFT_REDIRECT_URI` to their exact public HTTPS values; register the same callback in Entra.
- Set `INTEGRATION_COOKIE_SECURE=true`; review cookie domain/SameSite, proxy behavior, CORS, and CSRF protection.
- Move secrets and the Fernet key out of `.env` into an approved secret manager.
- Replace or operationalize SQLite for concurrency, durable storage, migrations, encrypted backups, and restore testing.
- Add rate limiting, request/body limits at the proxy, audit logging, monitoring, retention controls, and incident procedures.
- Reassess client-secret authentication; the current code cannot use certificate/federated credentials.
- Obtain security/privacy approval for OpenAI document processing and Microsoft mailbox access.

Hand over the release Git SHAs for both repositories, URLs, non-secret configuration names, Entra tenant/app IDs, authorized mailbox, consent record, secret expiry owner, Fernet-key backup owner, database backup/restore procedure, OpenAI model/project, acceptance results, and support contacts.

## Microsoft Entra ID and Graph

### Exact implementation

- OAuth 2.0 authorization-code flow with PKCE (`S256`) and a confidential client secret
- Microsoft v2 endpoints under the code-enforced `/common` authority
- Delegated scopes: `openid profile email User.Read Mail.Read offline_access`
- Account lookup: `GET https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName`
- Inbox lookup: `GET https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages`
- Inbox query: `$top=20`, `$orderby=receivedDateTime desc`, `$select=id,from,subject,receivedDateTime,hasAttachments`
- HTTP timeout: 15 seconds for token and Graph calls (not environment-configurable)
- No pagination, filtering, body read, attachment endpoint, shared-mailbox endpoint, webhook, delta query, or application permission

### Token lifecycle

Tokens and metadata (`token_type`, granted `scope`, `expires_in`, `obtained_at`) are encrypted as one JSON payload. POBridge refreshes 60 seconds before the recorded expiry. If Graph nevertheless returns `401`, it refreshes once and retries once. A rotated refresh token is persisted; if Microsoft omits a new refresh token, the old one is retained.

Token endpoint `400/401` during refresh becomes “authorization expired” and the user must reconnect. Graph/token `429` becomes rate limited, timeout becomes `504`, and other HTTP failures are exposed only as a generic provider error. Disconnect removes the local row but does not call a Microsoft revocation endpoint.

## OpenAI extraction

The provider is behind an `ExtractionProvider` interface, but OpenAI is the only implementation. It uses `AsyncOpenAI.responses.parse`, embeds the PDF as a base64 `input_file`, requests strict `StructuredPurchaseOrderExtraction`, disables OpenAI response storage with `store=False`, sets `max_retries=0`, and logs token counts when available.

### Input restrictions

- Exactly one multipart upload field named `file`
- Filename must end in `.pdf` after basename sanitization
- MIME type must be exactly `application/pdf`
- Non-empty content beginning with `%PDF-`
- Default maximum 10 MB and 25 pages
- At least one readable page
- Password-protected, repaired, malformed, or unreadable PDFs are rejected

There is no separate OCR, deskew, rotation-correction, antivirus, or content-classification stage. Difficult scans may extract poorly even when the PDF passes structural checks.

### Error handling

| Condition | API result |
| --- | --- |
| Missing OpenAI key/model | `503 EXTRACTION_NOT_CONFIGURED` |
| Authentication failure | `503 EXTRACTION_AUTHENTICATION_FAILED` |
| Rate limit, connection, internal provider, or other API status error | `503 EXTRACTION_UNAVAILABLE` |
| Provider timeout | `504 EXTRACTION_TIMEOUT` |
| Incomplete/content-filtered/invalid structured output | `502 INVALID_EXTRACTION_RESPONSE` |

The API deliberately avoids exposing provider response bodies, tokens, or tracebacks. `store=False` controls OpenAI response storage but is not a complete data-retention policy; confirm current OpenAI project and contractual data controls before client use.

## API reference

No route has application-user authentication. Outlook ownership is enforced only by its dedicated cookie. The configured `API_V1_PREFIX` defaults to `/api/v1`; paths below assume that default.

| Method | Route | Purpose | Access / important behavior |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health` | Return status, app name, version | Public; does not verify OpenAI, Microsoft, or database connectivity |
| `POST` | `/api/v1/purchase-orders/extract` | Validate and extract one PO PDF | Public multipart `file`; `200`, `400`, `413`, `422`, `502`, `503`, or `504` |
| `GET` | `/api/v1/integrations/outlook/connect` | Start OAuth and redirect to Microsoft | Existing cookie optional; creates 30-day cookie. `307`; `403` if another browser owns the connection; `503` if unconfigured |
| `GET` | `/api/v1/integrations/outlook/callback` | Consume state, exchange code, identify account, persist tokens | Microsoft callback plus same session cookie; always redirects `303` to frontend Outlook result page on handled success/error |
| `GET` | `/api/v1/integrations/outlook/status` | Return `{connected,email}` | Requires valid Outlook session cookie; `401`, `403`, or `503` otherwise |
| `GET` | `/api/v1/integrations/outlook/emails` | Return normalized latest inbox summaries | Requires owning cookie and connection; `401`, `403`, `409`, `429`, `502`, `503`, or `504` |
| `POST` | `/api/v1/integrations/outlook/disconnect` | Delete local connection and cookie | Requires owning cookie and exact `Origin == FRONTEND_URL`; `401`, `403`, or `503` otherwise |

Interactive schemas are available at `/docs`. The extraction response shape is defined in `app/schemas/purchase_order.py`; inbox results contain `provider: "outlook"` and an `emails` array with `id`, nullable sender/subject, `received_at`, and `has_attachments`.

## Security, data, and operations

### Implemented controls

- PDF validation occurs before the paid provider call; upload reading is bounded.
- OAuth state and browser session values are high entropy; only SHA-256 hashes are persisted.
- OAuth state is single-use and expires after 10 minutes by default.
- PKCE verifiers and token JSON are authenticated-encrypted with Fernet.
- SQLite is initialized with parameterized queries and the file is set to mode `0600` where supported.
- The Outlook cookie is HttpOnly, SameSite=Lax, path-scoped to the Outlook API, and optionally Secure.
- CORS allows credentials only from the single configured `FRONTEND_URL`.
- Disconnect additionally checks the exact browser `Origin`.
- OpenAI requests disable SDK retries and request `store=False`; logs contain metadata/error classes rather than PDF contents.

### Persistence and backup

Uploaded PDFs and extraction responses are held in memory for the request and are not intentionally persisted by application code. The SQLite database persists OAuth transactions and one Outlook connection. It contains account identifiers/email in plaintext and OAuth credentials encrypted with the Fernet key.

Back up the database and Fernet key separately but as one recoverable set. Test restoration. A database without the original key cannot decrypt tokens; a key without the database cannot restore the connection. There is no key rotation/re-encryption command. If the key is lost or changed, stop the app, archive/remove the unusable database according to policy, restore the old key or recreate the database, and reconnect the mailbox.

### Operational cautions

- `DEBUG` controls log level only; FastAPI debug mode is not enabled by it.
- Logs go to standard output using timestamp, level, logger, and message. No file rotation, audit sink, metrics, or health dependency checks exist.
- SQLite initialization happens lazily when the configured Outlook service is first constructed. A bad path/permissions error can therefore appear on an Outlook request while `/health` remains green.
- One `integration_connections` row is allowed for provider `outlook`. A second browser cannot take over until the owner disconnects or an operator removes/reinitializes the database.
- The session cookie lasts 30 days, but there is no user login, server-side browser-session expiry table, or logout beyond Outlook disconnect.
- Local disconnect does not revoke Microsoft grants. Revoke the app/session in Microsoft account/tenant controls when required by incident or offboarding policy.
- The extraction route is unauthenticated and has no rate limiting. Do not expose it publicly as-is.

## Troubleshooting

| Symptom | Cause supported by the implementation | Resolution |
| --- | --- | --- |
| Outlook route returns `503` | Missing client ID, secret, Fernet key; invalid Fernet key; or authority is not `/common` | Check server configuration, restore a valid Fernet key, restart the backend |
| `AADSTS50011` / redirect mismatch | Entra Web redirect and `MICROSOFT_REDIRECT_URI` differ | Match scheme, host, port, prefix, path, and trailing slash exactly; restart |
| `invalid_client` at callback/refresh | Wrong/expired secret, secret ID used, or ID/secret from different registrations | Create/copy the secret **Value** from the same app, update secret store, restart, reconnect |
| Personal account is rejected | App registration does not support personal Microsoft accounts | Select the multi-tenant plus personal account audience required by `/common` |
| Consent/privilege error | `User.Read`/`Mail.Read` missing, tenant consent policy, Conditional Access, or wrong signed-in account | Confirm delegated permissions and granted consent with tenant admin; retry with intended account |
| OAuth returns error after a delay | State expired, was already used, browser lost cookie, or callback opened in another profile | Start a fresh Connect flow in the same browser; do not reuse callback URLs |
| UI says connection belongs to another browser | Single stored connection is owned by another session hash | Use the original profile and disconnect. If inaccessible, an authorized operator must reinitialize/delete the connection row/database and reconnect |
| UI cannot reach backend / cookie unavailable | API stopped, wrong `NEXT_PUBLIC_API_BASE_URL`, CORS mismatch, or mixed `localhost`/`127.0.0.1` | Start backend; align frontend/API URLs and `FRONTEND_URL`; use `localhost` consistently; restart frontend after env changes |
| Status is `401` before first connection | No Outlook session cookie exists yet | This is expected; click Connect Outlook |
| Inbox returns `409` | Session exists but no connection row exists | Connect Outlook again |
| Inbox returns `401` after being connected | Refresh token is absent/rejected or stored credentials cannot decrypt/parse | Restore the original Fernet key if appropriate; otherwise reconnect |
| Inbox returns `429` | Graph or token endpoint throttled | Wait and manually retry; no automatic backoff is implemented |
| Inbox returns `502`/`504` | Graph failure/invalid response or 15-second timeout | Check Microsoft service/network and server logs; retry. Details are intentionally hidden from browser |
| Inbox shows attachment icon but cannot open it | Only `hasAttachments` metadata is implemented | Attachment retrieval/processing requires new code |
| Extraction returns `503` | Key missing/invalid, model unavailable, provider rate limit/network/server error | Validate server-only key, model access, quota/network, and sanitized backend logs |
| Extraction returns `502` | OpenAI output incomplete, filtered, or fails strict schema parsing | Retry with a supported PDF; inspect sanitized error class/validation paths in backend logs |
| PDF returns `400`/`413` | Wrong extension/MIME/signature, empty/encrypted/repaired/malformed PDF, too many pages, or too large | Correct or recreate the PDF; compare backend limits. `413` is size; page limit is `400` |
| Frontend accepts a file the backend rejects | Frontend only checks a fixed subset and fixed 10 MB size | Treat backend validation as authoritative; keep limits at 10 MB unless frontend is updated too |
| Stored tokens fail after key change | Fernet key no longer matches database ciphertext | Restore the backed-up key or reinitialize integration storage and reconnect; no rotation tool exists |

Do not share complete authorization URLs or logs containing `code`, `state`, tokens, client secrets, API keys, or client documents.

## Known limitations and roadmap

### Partially implemented

- Outlook email integration lists only the first 20 newest inbox messages, without pagination, search, filtering, body, attachment content, folders, or shared-mailbox selection.
- OAuth refresh is on-demand only; there is no proactive scheduler, distributed locking, retry/backoff policy, or Microsoft token revocation.
- Extraction identifies missing/ambiguous fields but does not reconcile arithmetic, validate master data, score confidence, or require human approval.
- JSON export is client-side only. CSV is visibly planned but disabled.

### Not implemented / next steps

1. Add real application authentication, authorization, tenant isolation, and per-user mailbox ownership before shared deployment.
2. Add attachment enumeration/download, safe PDF selection, deduplication, and reuse of the existing extraction service.
3. Add polling or Graph change notifications, subscription renewal, retries/backoff, idempotency, and monitoring.
4. Add persistent PO/job history, migrations, review/approval, audit events, and retention controls.
5. Add deterministic totals, item/customer/UOM/address rules and representative-document accuracy evaluation.
6. Define and implement an ERP export/import contract with human authorization and positive acknowledgement.
7. Add production packaging, secret-manager integration, managed storage/backups, observability, proxy limits, and incident runbooks.
8. Add CSV export and only then enable the existing UI button.

Keep this README and both `.env.example` files in the same change as future configuration, route, integration, or status changes.
