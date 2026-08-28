# Schwabber self-hosted research gateway design

Date: 2026-08-28
Status: approved

## 1. Purpose

Schwabber is an open-source, self-hosted research gateway for a private Custom
GPT. Each operator runs an independent instance using their own Schwab
developer application and credentials. The service gives the GPT compact,
structured market data from Schwab and authoritative company financial data
from SEC EDGAR.

The service does not call an OpenAI model, make investment recommendations, or
place trades. It supplies evidence; the operator's private GPT performs the
analysis.

The first release is intentionally single-user and read-only. The public
repository contains application code and synthetic test fixtures, never
credentials, tokens, cached market data, or licensed Schwab responses.

## 2. Goals

- Provide a stable, GPT-oriented REST API over selected Schwab market-data
  operations.
- Provide normalized annual and quarterly company facts plus recent filing
  metadata from SEC EDGAR.
- Keep every request read-only and every response within GPT Action limits.
- Support local Docker plus ngrok and VPS Docker Compose plus Caddy.
- Keep Schwab OAuth credentials and tokens inside the operator's deployment.
- Publish an OpenAPI schema suitable for import into a private Custom GPT.
- Make freshness, source, truncation, and derivation explicit in responses.

## 3. Non-goals

- Account balances, positions, transaction history, or order history.
- Order preview, placement, replacement, or cancellation.
- Portfolio management, signal generation, or investment advice.
- A hosted multi-tenant Schwabber service.
- Scraping thinkorswim or calling undocumented Schwab endpoints.
- A v1 server-side news feed. The GPT uses web search for current news.
- Full filing-body parsing, earnings transcripts, analyst estimates, ratings,
  or consensus forecasts.
- Redis, a database, or multiple API workers.

## 4. Architecture

```text
Private Custom GPT
        |
        | HTTPS + bearer API key
        v
    Caddy or ngrok
        |
        v
FastAPI application (one worker)
        |-- request authentication and validation
        |-- response models, bounds, and metadata
        |-- in-memory cache and rate limiting
        |-- Schwab adapter and token store
        `-- SEC adapter and financial-fact normalizer
                 |                    |
                 v                    v
        Schwab Trader API       SEC data APIs
```

The middleware is a standalone Python 3.12+ FastAPI application. It uses
`schwab-py` behind an internal adapter so the public API is not coupled to
Schwab's raw response shapes. It uses an HTTP client behind a separate SEC
adapter. Domain services consume adapter interfaces rather than HTTP response
objects, which keeps normalization and route behavior independently testable.

Only one application worker runs. `schwab-py` updates its token file during
access-token refresh; multiple workers could hold different in-memory token
states and overwrite one another's updates.

## 5. Configuration and secrets

The supported environment variables are:

| Variable | Required | Purpose |
|---|---:|---|
| `SCHWABBER_API_KEY` | yes | Bearer secret used by the GPT Action; minimum 32 characters. |
| `SCHWAB_CLIENT_ID` | yes for Schwab | Operator's Schwab app client ID. |
| `SCHWAB_CLIENT_SECRET` | yes for Schwab | Operator's Schwab app secret. |
| `SCHWAB_CALLBACK_URL` | no | Defaults to `https://127.0.0.1:8182`; must exactly match the Schwab app. |
| `SCHWAB_TOKEN_PATH` | no | Defaults to `/data/token.json` in Docker. |
| `SCHWAB_REFRESH_TOKEN_MAX_AGE_DAYS` | no | Documented Schwab-oriented default of 7; configurable if policy changes. |
| `SCHWAB_REFRESH_TOKEN_WARN_AGE_DAYS` | no | Defaults to 6. |
| `SEC_USER_AGENT` | yes for SEC | Descriptive application/contact identity required for SEC access. |
| `SCHWABBER_REQUESTS_PER_MINUTE` | no | Inbound bearer-key limit; defaults to 60. |
| `SCHWABBER_LOG_LEVEL` | no | Defaults to `INFO`. |

Startup validates configuration without printing secret values. The API may
start in a degraded state when a provider is unconfigured or unauthorized so
health and status remain available and the other provider can continue to
serve requests.

`.env`, token files, Docker data, caches, and logs are ignored by Git.

## 6. Authentication and public routes

The GPT Action uses API-key authentication in bearer form:

```http
Authorization: Bearer <SCHWABBER_API_KEY>
```

Bearer values are compared in constant time. Missing or invalid credentials
return a compact `401` response. Authorization headers, environment values,
OAuth payloads, and tokens are never logged.

Public routes are limited to:

- `GET /healthz`: process liveness only; it reveals no provider or brokerage
  state.
- `GET /openapi.json`: the schema imported into the GPT editor.

All `/v1` routes, including provider readiness details, require the bearer
key. CORS is disabled because the API is server-to-server.

## 7. Schwab authorization lifecycle

Authorization uses `schwab-py`'s manual login flow through the container:

```bash
docker compose run --rm schwabber auth login
```

The command prints the Schwab authorization URL. The operator opens it in any
browser, authorizes the app, then pastes the entire redirected URL back into
the CLI. This works locally and through an SSH session without publishing an
OAuth callback route or requiring a browser inside the container. The command
writes `/data/token.json` with mode `0600` in the persistent
volume. The operator then restarts the API container so its single client
loads the newly minted refresh token.

Normal access-token refresh is automatic and persists updates to the same
file. Refresh-token age uses `schwab-py`'s immutable `creation_timestamp`, not
file modification time. `GET /v1/status` reports `OK`, `URGENT`, `EXPIRED`,
`MISSING`, or `UNAVAILABLE`, the calculated expiry time, and days remaining,
but no token contents.

## 8. Public API

All research operations use `GET`, have stable `operationId` values, and are
non-consequential. There is no generic upstream-proxy route.

### 8.1 Service status

`GET /v1/status`

Returns application version, readiness by provider, cache availability, and
the classified Schwab token age. An optional lightweight upstream check must
be explicitly requested so routine status calls do not consume provider
quota.

### 8.2 Quotes

`GET /v1/quotes?symbols=AAPL,MSFT`

- Accepts 1 to 25 normalized symbols.
- Returns quote, reference, and session fields useful for research, including
  source timestamps and Schwab's real-time/delayed indicator when supplied.
- Missing upstream fields remain `null`; the service does not estimate them.

### 8.3 Price history

`GET /v1/history/{symbol}`

- Supports bounded 1-, 5-, 15-, and 30-minute, daily, and weekly intervals.
- Defaults to one year of daily data. The maximum requested windows are 10
  calendar days for 1-minute data, 60 calendar days for 5-, 15-, and 30-minute
  data, 5 years for daily data, and 20 years for weekly data.
- Returns at most 500 OHLCV candles and explicitly reports truncation. The
  lower cap keeps the normalized JSON response below the 90,000-character
  Action budget even when timestamps and numeric values use their widest
  expected representations.
- Extended-hours inclusion is an explicit parameter where Schwab supports it.

### 8.4 Instruments and quote-level fundamentals

`GET /v1/instruments/{symbol}`

Returns instrument identity plus the standard Schwab fundamental fields that
are present, such as market capitalization, earnings multiples, EPS, dividend
data, beta, shares outstanding, and 52-week range. These fields are useful
market metrics, not a replacement for reported financial statements.

### 8.5 Option chains

`GET /v1/options/{symbol}`

- Filters by expiration range, put/call side, strike count, and optional
  minimum open interest.
- Defaults to calls and puts expiring within 45 calendar days, 10 strikes
  centered on the underlying price, and no minimum open-interest filter.
- Returns no more than 200 contracts and reports truncation plus the filters
  used.
- Returns contract identity, expiration, strike, bid, ask, last, mark, volume,
  open interest, implied volatility, and Greeks when Schwab supplies them.
- Preserves quote timestamps and any real-time/delayed markers supplied by
  Schwab.

### 8.6 Movers

`GET /v1/movers/{index}`

Accepts only documented index, direction, and frequency enums. It returns a
normalized list with a default of 10 and a maximum of 50 movers, and never
forwards an arbitrary upstream path or enum.

### 8.7 Market hours

`GET /v1/market-hours`

Returns equity and option sessions for one requested date, including regular
and extended-hours intervals when supplied by Schwab.

### 8.8 Financial statements

`GET /v1/financials/{symbol}`

Parameters select `annual` or `quarterly` periods. The default result count is
5 annual or 8 quarterly periods, with a maximum of 20.
The response includes canonical metrics when unambiguous:

- Revenue, net income, and diluted EPS.
- Assets, liabilities, stockholders' equity, and cash.
- Short- and long-term debt when reported in compatible concepts.
- Operating cash flow and capital expenditure.
- Free cash flow only when operating cash flow and capital expenditure share
  compatible units, dates, duration, and filing context.

Every value includes taxonomy, concept, unit, start/end dates when applicable,
fiscal year and period, form, filing date, accession number, and whether it is
reported or derived. The normalizer uses explicit, ordered concept aliases for
standard US-GAAP and IFRS taxonomies. It does not guess from labels or combine
custom concepts with superficially similar names.

Selection rules are deterministic:

1. Reject facts with incompatible units or unsupported forms.
2. Keep only facts matching the requested annual or directly reported
   quarterly duration. V1 does not derive a fourth quarter by subtracting
   nine-month values from an annual value.
3. Deduplicate identical accession/context facts.
4. For a repeated reporting context, prefer the latest filed fact and retain
   its amended/form provenance.
5. Return `null` when aliases conflict or a value cannot be selected safely.

### 8.9 Recent filings

`GET /v1/filings/{symbol}`

Returns a bounded, filterable list of filing metadata, defaulting to recent
10-K, 10-Q, and 8-K filings. The default result count is 20 and the maximum is
100. Each entry includes form, filing and report dates, accession number,
description, primary document, and an official SEC URL. V1 does not download,
parse, summarize, or republish the filing body.

## 9. Response contract and size limits

Successful responses use a common envelope:

```json
{
  "data": {},
  "meta": {
    "source": "schwab",
    "retrieved_at": "2026-08-28T14:30:00Z",
    "request_id": "...",
    "cache": {"hit": false, "age_seconds": 0},
    "result_count": 1,
    "truncated": false
  }
}
```

Models use snake_case, JSON numbers for numeric values, ISO 8601 timestamps,
and `null` for unavailable fields. Raw provider bodies are not exposed.

Endpoint-specific collection limits keep maximum valid responses below 90,000
characters, leaving headroom beneath the GPT Action 100,000-character limit.
Maximum-shape contract tests enforce that budget. Requests that cannot fit
within documented bounds receive `422` with guidance for narrowing them.

## 10. Caching and rate limits

The single-process application uses an in-memory TTL cache capped at 1,024
entries with least-recently-used eviction. Cache keys include every parameter
that affects a response. V1 defaults are:

| Data | TTL |
|---|---:|
| Quotes | 5 seconds |
| Intraday history | 15 seconds |
| Options | 15 seconds |
| Movers | 30 seconds |
| Market hours | 60 seconds |
| Daily/weekly history | 5 minutes |
| Schwab instrument fundamentals | 5 minutes |
| SEC filing list | 5 minutes |
| SEC company facts/normalized financials | 60 minutes |
| SEC ticker-to-CIK mapping | 24 hours |

Every response reports cache hit and age. Caches never survive a restart and
are not a source of record.

Authenticated requests use a configurable token bucket keyed by the sole
bearer credential, defaulting to 60 requests per minute with a burst of 10.
Invalid-authentication attempts have a separate client-IP limit. Forwarded
client addresses are trusted only from the loopback reverse proxy. SEC calls
use a separate limit of 5 requests per second with a burst of 5, below the
SEC's published fair-access ceiling, and always send `SEC_USER_AGENT`.

## 11. Timeouts, retries, and errors

The application enforces a 25-second total provider-operation deadline beneath
the GPT Action 45-second round-trip timeout. Individual calls use a 3-second
connect timeout and a 10-second read timeout.

Schwab `429` and transient `5xx` responses receive at most two retries after
the initial attempt, with exponential backoff and jitter while the operation
remains inside its deadline. SEC retries follow the same rule. Non-retryable
`4xx` responses are not retried.

Errors use one compact envelope:

```json
{
  "error": {
    "code": "SCHWAB_REAUTH_REQUIRED",
    "message": "Schwab authorization must be renewed.",
    "retryable": false,
    "retry_after_seconds": null,
    "request_id": "..."
  }
}
```

Status mappings are:

| Status | Meaning |
|---:|---|
| `401` | Missing or invalid middleware bearer key. |
| `404` | Unknown symbol or unavailable requested resource. |
| `422` | Invalid parameters or request exceeds documented bounds. |
| `429` | Middleware or upstream rate limit; include `Retry-After` when known. |
| `502` | Upstream failure or an upstream response that cannot be validated. |
| `503` | Provider unconfigured, unavailable, or Schwab reauthorization required. |

One provider's outage does not disable the other provider's routes.

## 12. Logging and security

Structured logs include request ID, operation ID, provider, status, duration,
retry count, result count, and cache state. They exclude authorization
headers, query-string secrets, environment values, token payloads, and raw
upstream bodies. Known token fields are registered for redaction before any
provider client logs can be emitted.

The Docker image runs as a non-root user. The token volume is writable only by
that user. On a VPS, the API port binds to `127.0.0.1`; only Caddy exposes port
443. Caddy supplies a valid public certificate. Local ngrok use points at the
same loopback API port.

The project ships a security policy describing credential handling and a
private vulnerability-reporting path. It includes financial-data and
no-investment-advice disclaimers plus explicit Schwab, SEC, and OpenAI
non-affiliation language.

## 13. News boundary

Schwab's thinkorswim applications provide news, but no supported news operation
is present in the Trader API surface used by this design. Schwabber does not
scrape thinkorswim, reuse browser sessions, or call undocumented endpoints.

The GPT should enable web search for headlines, current reporting, earnings
coverage, transcripts, estimates, and qualitative context. SEC filing routes
cover official disclosures such as 8-Ks.

V1 documents a future licensed news-provider extension but implements no
`/news` route or unused provider abstraction. A later release may add a
normalized headline route after choosing a provider whose terms permit this
single-user server use. It must return metadata and links, not republish full
copyrighted articles.

## 14. Deployment and operator workflow

### Local

1. Copy `.env.example` to `.env` and fill in operator-owned credentials.
2. Run the containerized manual Schwab login.
3. Start Docker Compose.
4. Start ngrok against the loopback API port.
5. Import the public `openapi.json` URL into the private GPT and configure its
   bearer API key.

### VPS

1. Clone the repository and configure `.env` on the VPS.
2. Run the manual login through an SSH terminal, opening the printed URL in a
   workstation browser and pasting the redirected URL back into the terminal.
3. Start the API and Caddy Compose services.
4. Allow inbound SSH and HTTPS only; do not expose the FastAPI port.
5. Import the HTTPS OpenAPI URL into the private GPT.

Reauthorization repeats the manual CLI flow and restarts the API container.
The README explains the token status endpoint and renewal workflow.

## 15. Repository contents

The initial public repository includes:

- FastAPI application and CLI package.
- Dockerfile and Docker Compose definitions for local and Caddy-backed use.
- Caddy configuration template.
- `.env.example` with placeholders only.
- GPT Action setup instructions and the generated OpenAPI schema route.
- Local/ngrok and VPS deployment guides.
- Schwab app, callback, login, and reauthorization instructions.
- SEC identification and fair-access instructions.
- MIT license, security policy, contributing guide, and disclaimers.
- Synthetic provider fixtures and automated tests.

## 16. Testing

Unit tests cover:

- Bearer authentication and constant-time validation behavior.
- Configuration validation without secret disclosure.
- Schwab response normalization for every supported endpoint.
- SEC CIK lookup, concept aliases, unit and duration checks, duplicates,
  amendments, missing concepts, and reported-versus-derived facts.
- Cache keys, TTLs, hit metadata, and bounded eviction.
- Rate limiting, provider timeouts, retries, and error mappings.
- Token age classification based on `creation_timestamp`.

Contract and integration tests cover:

- Every success and error response model.
- Maximum response shapes below 90,000 characters.
- OpenAPI validity, stable operation IDs, authentication declarations, and GPT
  Action description-length limits.
- Provider independence during partial outages.
- Log capture proving secrets and tokens are absent.
- Docker image construction, non-root execution, health, and degraded startup.

Tests use synthetic Schwab and SEC-shaped fixtures. Ordinary CI requires no
network and no credentials. GitHub Actions runs formatting, linting, type
checks, tests, and Docker construction.

An optional `schwabber smoke AAPL` command performs read-only live checks
against configured providers. It is never run in CI and prints no credentials
or raw tokens.

## 17. Acceptance criteria

V1 is complete when a new operator can follow the public documentation to:

1. Configure their own Schwab developer credentials and SEC identity.
2. Mint and persist a Schwab token using the containerized CLI.
3. Launch the service locally through ngrok or on a VPS through Caddy.
4. Import the schema into a private Custom GPT and configure bearer auth.
5. Retrieve a quote, bounded price history, filtered option chain, instrument
   fundamentals, movers, and market hours from Schwab.
6. Retrieve normalized, provenance-rich financial series and recent filing
   links from SEC EDGAR.
7. Observe source, freshness, cache, and truncation metadata on every response.
8. Receive compact, stable errors when a provider is unavailable or Schwab
   authorization must be renewed.

## 18. References

- OpenAI GPT Actions overview:
  https://developers.openai.com/api/docs/actions/introduction
- OpenAI GPT Action authentication:
  https://developers.openai.com/api/docs/actions/authentication
- OpenAI GPT Action production limits:
  https://developers.openai.com/api/docs/actions/production
- SEC EDGAR data APIs:
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC developer resources and fair access:
  https://www.sec.gov/about/developer-resources
- Schwab developer portal:
  https://developer.schwab.com/
