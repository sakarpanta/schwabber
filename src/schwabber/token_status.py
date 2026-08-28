import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast


@dataclass(frozen=True)
class TokenStatus:
    state: Literal["OK", "URGENT", "EXPIRED", "MISSING", "UNAVAILABLE"]
    days_left: int | None
    expires_at: datetime | None


def classify_token(
    *, now: datetime, creation_timestamp: int | None, warn_days: int, max_days: int
) -> TokenStatus:
    if creation_timestamp is None:
        return TokenStatus("MISSING", None, None)
    created = min(datetime.fromtimestamp(creation_timestamp, tz=UTC), now)
    expires_at = created + timedelta(days=max_days)
    age = now - created
    days_left = max((expires_at - now).days, 0)
    state = (
        "EXPIRED"
        if age >= timedelta(days=max_days)
        else "URGENT"
        if age >= timedelta(days=warn_days)
        else "OK"
    )
    return TokenStatus(
        cast(Literal["OK", "URGENT", "EXPIRED"], state), days_left, expires_at
    )


def classify_token_file(
    *, path: Path, now: datetime, warn_days: int, max_days: int
) -> TokenStatus:
    if not path.exists():
        return TokenStatus("MISSING", None, None)
    try:
        payload = json.loads(path.read_text())
        timestamp = payload["creation_timestamp"]
        if not isinstance(timestamp, int):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError):
        return TokenStatus("UNAVAILABLE", None, None)
    return classify_token(
        now=now, creation_timestamp=timestamp, warn_days=warn_days, max_days=max_days
    )
