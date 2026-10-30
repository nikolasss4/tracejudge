from typer.testing import CliRunner

from tracejudge import __version__
from tracejudge.cli import app


def test_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
