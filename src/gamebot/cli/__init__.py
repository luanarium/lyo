"""Project and deployment CLI, in the shape of OpenWrt's UCI."""

import click

from gamebot import __version__


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="gamebot")
def main() -> None:
    """A game engine for chatbot games."""


if __name__ == "__main__":
    main()
