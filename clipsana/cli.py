"""Příkazová řádka Clipsana. Příkazy přibývají s milníky (doctor v M0, scan/plan/apply v M1)."""
import typer

app = typer.Typer(help="Clipsana – kontrola a oprava videí před střihem.", no_args_is_help=True)


@app.command()
def version() -> None:
    """Vypíše verzi aplikace."""
    from clipsana import __version__
    typer.echo(f"Clipsana {__version__}")


if __name__ == "__main__":
    app()
