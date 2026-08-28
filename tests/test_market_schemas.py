from schwabber.schemas.market import Quote


def test_quote_keeps_unknown_fields_nullable() -> None:
    quote = Quote(symbol="AMD", last_price=172.34)
    assert quote.bid_price is None
    assert quote.is_realtime is None
