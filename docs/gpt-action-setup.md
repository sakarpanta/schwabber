# Custom GPT Action Setup

1. Start Schwabber locally with Docker Compose and complete `schwabber auth login`.
2. Publish only the HTTP port through a tunnel or reverse proxy. `ngrok http 8000`
   is suitable for local testing; use HTTPS and an access-controlled VPS for a
   persistent deployment.
3. In the private GPT editor, create an Action and import
   `https://YOUR-HOST/openapi.json`.
4. Configure a bearer API key with the exact value of `SCHWABBER_API_KEY`.
5. Keep web search enabled for news. Schwabber supplies structured Schwab quotes,
   history, options, movers, market hours, plus optional SEC data; it does not
   scrape or redistribute news.

Never commit `.env`, `token.json`, or a copied OpenAPI export containing private
hostnames. Rotate the API key if it is exposed. The service is research-only and
does not place trades.
