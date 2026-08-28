import json
import logging

from schwabber.logging import JsonFormatter, redact


def test_redact_removes_nested_credentials() -> None:
    assert redact({"Authorization": "secret", "nested": {"token": "x"}}) == {
        "Authorization": "[REDACTED]",
        "nested": {"token": "[REDACTED]"},
    }


def test_json_formatter_is_structured() -> None:
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    assert json.loads(JsonFormatter().format(record))["message"] == "hello"
