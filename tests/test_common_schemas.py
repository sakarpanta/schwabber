from datetime import UTC, datetime

from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope


def test_success_envelope_serializes_metadata() -> None:
    body = SuccessEnvelope(
        data={"count": 1},
        meta=ResponseMeta(
            source="schwab",
            retrieved_at=datetime(2026, 8, 28, tzinfo=UTC),
            request_id="req-1",
            cache=CacheMeta(hit=False, age_seconds=0),
            result_count=1,
        ),
    ).model_dump(mode="json")
    assert body["meta"]["cache"] == {"hit": False, "age_seconds": 0}
