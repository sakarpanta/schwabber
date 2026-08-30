# Roadmap

Schwabber v0.1 focuses on a small, read-only research gateway for a private
Custom GPT. Future work will preserve that boundary and remain opt-in.

## Near Term

- Add GitHub Actions CI and coverage reporting.
- Wire structured request logging and correlation IDs into application startup.
- Expand SEC normalization for more concepts, filing text, and aligned cash-flow derivations.
- Validate the Docker and VPS deployment path from a clean host.
- Add OpenAPI contract and response-size regression tests.

## Research Providers

- Add licensed news-provider adapters with source attribution and timestamps.
- Add earnings calendars, corporate actions, insider transactions, and institutional holdings.
- Add SEC filing text and exhibit retrieval where permitted by the source terms.

News is deliberately outside the current Schwabber boundary. The GPT can use
web search for current news today. Any future news adapter must respect source
licensing, rate limits, attribution, and redistribution terms; Schwabber will
not scrape or republish content as a default behavior.

## Platform

- Keep provider adapters pluggable so Schwab and SEC remain independently available.
- Add an optional persistent cache for single-user VPS deployments.
- Add configurable per-provider limits and observability hooks.
- Consider opt-in streaming quotes after the request/response API is stable.

Features that expose account data or place orders are intentionally not part of
this roadmap for the default deployment.
