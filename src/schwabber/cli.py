import argparse
import asyncio
import os
import stat

from schwabber.config import ConfigurationError, Settings
from schwabber.providers.schwab import create_schwab_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="schwabber")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    auth = commands.add_parser("auth").add_subparsers(
        dest="auth_command", required=True
    )
    auth.add_parser("login")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("symbol")
    return parser


def auth_login(settings: Settings) -> None:
    if not settings.schwab_configured:
        raise ConfigurationError(
            "SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET are required"
        )
    assert settings.schwab_client_id is not None
    assert settings.schwab_client_secret is not None
    from schwab.auth import client_from_manual_flow  # type: ignore[import-untyped]

    settings.token_path.parent.mkdir(parents=True, exist_ok=True)
    client_from_manual_flow(
        settings.schwab_client_id,
        settings.schwab_client_secret,
        settings.callback_url,
        str(settings.token_path),
        enforce_enums=False,
    )
    os.chmod(settings.token_path, stat.S_IRUSR | stat.S_IWUSR)


def smoke(settings: Settings, symbol: str) -> None:
    async def run() -> None:
        provider = await create_schwab_provider(settings)
        quotes = await provider.quotes((symbol.strip().upper(),))
        print(quotes[0].model_dump_json(exclude_none=True))

    asyncio.run(run())


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    if args.command == "auth":
        auth_login(settings)
        return
    if args.command == "serve":
        import uvicorn

        uvicorn.run("schwabber.app:create_app", factory=True, host="0.0.0.0", port=8000)
        return
    if args.command == "smoke":
        smoke(settings, args.symbol)
        return
