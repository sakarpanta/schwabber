# Schwabber

Schwabber is a self-hosted, read-only market-data Action for a private Custom GPT.
It normalizes selected Schwab Trader API responses and exposes no account, order,
or trading operations.

## Local setup

```bash
cp .env.example .env
openssl rand -hex 32
docker compose build
docker compose run --rm schwabber auth login
docker compose up -d
curl http://127.0.0.1:8000/healthz
```

Put the generated value in `SCHWABBER_API_KEY`, then set your Schwab client ID,
client secret, and exactly registered callback URL in `.env`. The login command
prints a URL; authorize it in a browser and paste the complete redirected URL
back into the terminal.

## Connect a private GPT

```bash
ngrok http 8000
```

In ChatGPT's private GPT editor, open Actions, import
`https://YOUR-NGROK-HOST/openapi.json`, and configure API-key authentication with
Bearer using the same `SCHWABBER_API_KEY`. Keep web search enabled for current
news; this service does not provide or scrape news.

See `docs/gpt-action-setup.md` for the full Action workflow. SEC financials and
filings are planned after the core Schwab routes.

Schwabber is research infrastructure, not investment advice, and is not affiliated
with Charles Schwab & Co., Inc., the U.S. Securities and Exchange Commission, or
OpenAI. It does not execute trades.
