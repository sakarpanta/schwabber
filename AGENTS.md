# Schwabber Agent Guide

## Project Scope

Schwabber is a self-hosted, read-only research gateway for Custom GPT Actions.
It provides normalized Schwab market data and SEC EDGAR research. It must not
place trades or expose brokerage account credentials, balances, positions, or
account numbers.

Read [`docs/architecture.md`](docs/architecture.md) and the design record before
changing provider boundaries or API contracts.

## Development

Use Python 3.12 or newer. Install development dependencies with:

```bash
pip install -e '.[dev]'
```

Before submitting changes, run:

```bash
pytest -q
ruff check src tests
mypy src
```

Add or update tests with behavior changes. Provider tests must use mocks or
synthetic fixtures; never use live brokerage or SEC credentials in tests.

## Security

- Keep `.env`, token files, and API keys out of git.
- Schwab OAuth tokens stay server-side; do not add endpoints that return them.
- Preserve bearer authentication, bounded responses, caching, rate limits, and
  provider-specific error handling.
- Treat news integrations as licensed-provider work. Do not scrape or
  redistribute content by default.

## Changes

- Prefer small, focused feature branches and descriptive commits.
- Do not rewrite shared branch history.
- Work directly in the checkout; do not create git worktrees.
- Keep the OpenAPI operation IDs and response envelopes stable unless the
  change includes an explicit compatibility plan.
- Use ASCII by default and avoid unrelated refactors.
