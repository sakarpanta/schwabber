import tomllib
from pathlib import Path

import schwabber


def test_project_version_matches_package() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert project["version"] == schwabber.__version__
