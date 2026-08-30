# Schwab Developer Setup

Each Schwabber operator needs their own Schwab developer application and OAuth
token. Schwabber does not provide shared Schwab credentials or a hosted brokerage
connection.

Schwab controls developer access, application approval, API availability, and
data-use terms. Use the [Schwab Developer Portal](https://developer.schwab.com/)
for current requirements and review the agreements presented there. Portal labels
and approval steps may change; the environment-variable mapping below is the
stable contract with Schwabber.

## Create the application

1. Sign in to the Schwab Developer Portal with an eligible Schwab account.
2. Create an application for the individual Trader API product.
3. Register an OAuth callback URL. Schwabber defaults to
   `https://127.0.0.1:8182`.
4. Wait until Schwab marks the application approved or ready before running the
   OAuth login command.

Map the application values into `.env` as follows:

| Schwab portal value | Schwabber variable | Notes |
| --- | --- | --- |
| App Key | `SCHWAB_CLIENT_ID` | The OAuth client identifier, not a Schwab username |
| Secret | `SCHWAB_CLIENT_SECRET` | Keep server-side and never publish it |
| Callback URL | `SCHWAB_CALLBACK_URL` | Must exactly match the registered value |

Schwabber does not use a variable named `SCHWAB_API_KEY`. The similarly named
`SCHWABBER_API_KEY` is an independent bearer secret protecting your middleware;
generate it yourself with `openssl rand -hex 32`. It does not come from Schwab.

## Configure the callback

The value of `SCHWAB_CALLBACK_URL` must match the portal entry exactly, including
the scheme, host, port, path, and any trailing slash. A mismatch will cause Schwab
to reject the authorization request.

The callback URL serves a different purpose from the public GPT Action URL:

- `SCHWAB_CALLBACK_URL` is used only during Schwab OAuth authorization. The
  default is `https://127.0.0.1:8182`.
- `SCHWABBER_PUBLIC_BASE_URL` is the HTTPS ngrok or VPS origin imported by the
  Custom GPT, such as `https://example.ngrok.app`.

Do not replace the Schwab callback with the ngrok hostname unless that exact URL
has also been registered for the Schwab application and you intentionally manage
the OAuth callback there. Schwabber's login command is designed for a manual
redirect flow and does not require exposing an OAuth callback endpoint.

## Configure the environment

For the default Docker Compose deployment, start from `.env.example` and retain
the container token path:

```dotenv
SCHWAB_CLIENT_ID=your-app-key
SCHWAB_CLIENT_SECRET=your-app-secret
SCHWAB_CALLBACK_URL=https://127.0.0.1:8182
SCHWAB_TOKEN_PATH=/data/token.json
SCHWABBER_API_KEY=your-random-32-character-or-longer-secret
```

Docker stores `/data/token.json` in the `schwabber-data` named volume. When
running Schwabber directly on the host instead of in Docker, use a writable host
path:

```dotenv
SCHWAB_TOKEN_PATH=./data/token.json
```

Using `/data/token.json` during a direct host run can fail with a read-only or
permission error because `/data` is the container path. Quote `.env` values that
contain spaces, including `SEC_USER_AGENT`, before loading the file in a shell.

## Complete OAuth login

With Docker Compose:

```bash
docker compose build
docker compose run --rm schwabber auth login
```

For a direct virtual-environment installation:

```bash
set -a
source .env
set +a
.venv/bin/schwabber auth login
```

The command prints a Schwab authorization URL. Open it in a browser, sign in,
review the requested access, and approve the application. Schwab then redirects
the browser to the registered callback.

The local callback page may show a connection or certificate error. That is
expected with the manual flow. Copy the complete redirected URL from the browser
address bar, including its query parameters, and paste it into the terminal. The
authorization code in that URL is sensitive and short-lived; do not share it.

The command writes the OAuth token to `SCHWAB_TOKEN_PATH` and restricts the file
to the current user. Test the stored authorization before exposing the API:

```bash
docker compose run --rm schwabber smoke AAPL
docker compose up -d
curl http://127.0.0.1:8000/healthz
```

The smoke command should return a normalized quote. The health endpoint confirms
only that the process is alive; authenticated `/v1/status` reports Schwab and SEC
configuration and readiness.

## Reauthorization

Schwab's current token policy may require recurring interactive authorization.
Schwabber tracks token age using `SCHWAB_REFRESH_TOKEN_WARN_AGE_DAYS` and
`SCHWAB_REFRESH_TOKEN_MAX_AGE_DAYS`; the distributed defaults are warning and
safety thresholds, not a guarantee that Schwab will accept a token for that long.

When Schwabber returns `SCHWAB_REAUTH_REQUIRED`, rerun the same `auth login`
command. The refreshed token remains in the Docker volume or configured host
path, so restarting the server does not normally require a new login by itself.

## Troubleshooting

- **Application not ready:** Confirm the application is approved in the Schwab
  Developer Portal before retrying OAuth.
- **Callback rejected:** Compare the portal value and `SCHWAB_CALLBACK_URL`
  character for character.
- **`command not found` while sourcing `.env`:** Quote values containing spaces.
- **Read-only `/data` error:** Use `./data/token.json` for a direct host run, or
  run the login command through Docker Compose.
- **`SCHWAB_REAUTH_REQUIRED`:** Complete interactive login again; repeated market
  data requests cannot renew an expired authorization.

Never commit `.env`, the Schwab Secret, the OAuth token file, authorization URLs,
or copied portal screenshots containing identifiers. Never place these values in
a Custom GPT's instructions or Action schema. Each operator is responsible for
using Schwab data in accordance with the current portal agreements.
