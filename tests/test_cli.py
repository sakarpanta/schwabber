import pytest

from schwabber.cli import build_parser, smoke
from schwabber.config import Settings


def test_cli_parses_auth_login() -> None:
    args = build_parser().parse_args(["auth", "login"])
    assert args.command == "auth"
    assert args.auth_command == "login"


def test_smoke_requires_authorized_token(tmp_path) -> None:
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SCHWAB_CLIENT_ID": "id",
            "SCHWAB_CLIENT_SECRET": "secret",
            "SCHWAB_TOKEN_PATH": str(tmp_path / "missing.json"),
        }
    )
    with pytest.raises(Exception, match="auth login"):
        smoke(settings, "AAPL")
