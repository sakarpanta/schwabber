from datetime import UTC, datetime

from schwabber.token_status import classify_token


def test_token_status_uses_creation_timestamp() -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    status = classify_token(
        now=now,
        creation_timestamp=int(now.timestamp()) - 6 * 86_400,
        warn_days=6,
        max_days=7,
    )
    assert status.state == "URGENT"
    assert status.days_left == 1
