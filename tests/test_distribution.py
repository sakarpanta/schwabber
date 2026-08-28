from pathlib import Path


def test_distribution_files_have_safe_defaults() -> None:
    assert "SCHWABBER_API_KEY=" in Path(".env.example").read_text()
    assert "token.json" in Path(".gitignore").read_text()
    assert "/data" in Path("compose.yaml").read_text()
