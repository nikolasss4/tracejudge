"""Command-line interface."""

import typer

from tracejudge import __version__

app = typer.Typer(help="Evals and trace viewer for tool-calling agents.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """tracejudge: run evals, diff runs and browse traces."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)
