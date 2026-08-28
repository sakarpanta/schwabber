from schwabber.rate_limit import TokenBucket


def test_bucket_allows_burst_then_reports_wait() -> None:
    now = [0.0]
    bucket = TokenBucket(rate_per_second=1.0, capacity=2, clock=lambda: now[0])
    assert bucket.consume("key") is None
    assert bucket.consume("key") is None
    assert bucket.consume("key") == 1


def test_bucket_refills_without_exceeding_capacity() -> None:
    now = [0.0]
    bucket = TokenBucket(rate_per_second=1.0, capacity=2, clock=lambda: now[0])
    bucket.consume("key")
    bucket.consume("key")
    now[0] = 5.0
    assert bucket.consume("key") is None
    assert bucket.consume("key") is None
    assert bucket.consume("key") == 1
