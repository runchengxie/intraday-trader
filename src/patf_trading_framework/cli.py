"""Command-line entry point for the PATF trading framework."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable

# Mapping from CLI subcommands to the modules that expose a ``main`` function.
_COMMAND_MODULES: dict[str, str] = {
    "run-backtest": "patf_trading_framework.scripts.run_backtests",
    "run-live": "patf_trading_framework.scripts.run_live_trading",
    "run-update-data": "patf_trading_framework.scripts.run_update_data",
    "run-generate-report": "patf_trading_framework.scripts.run_generate_report",
    "run-dashboard": "patf_trading_framework.scripts.run_dashboard",
}


class CommandNotFoundError(RuntimeError):
    """Raised when a user invokes an unknown PATF subcommand."""


def _load_command(command: str) -> Callable[[], int | None]:
    """Return the ``main`` callable for a given subcommand.

    Parameters
    ----------
    command:
        The subcommand requested by the user, e.g. ``"run-backtest"``.

    Returns
    -------
    Callable
        The zero-argument ``main`` function associated with the command.

    Raises
    ------
    CommandNotFoundError
        If there is no module registered for ``command``.
    AttributeError
        If the target module does not expose a ``main`` function.
    """

    module_path = _COMMAND_MODULES.get(command)
    if module_path is None:
        raise CommandNotFoundError(f"Unknown command: {command}")

    module = importlib.import_module(module_path)
    main_callable = getattr(module, "main")
    if not callable(main_callable):
        raise AttributeError(
            f"Module '{module_path}' does not define a callable 'main' function."
        )
    return main_callable


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser for the CLI."""

    parser = argparse.ArgumentParser(
        prog="patf",
        description=(
            "PATF (Python Algorithmic Trading Framework) command-line interface. "
            "Use one of the available subcommands to interact with the framework."
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=sorted(_COMMAND_MODULES),
        help="The PATF subcommand to execute.",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help=(
            "Additional arguments passed through to the selected subcommand. "
            "These mirror the parameters supported by the underlying script."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``patf`` console script."""

    parser = _build_parser()
    parsed = parser.parse_args(argv)

    if parsed.command is None:
        parser.print_help()
        return 0

    try:
        command_main = _load_command(parsed.command)
    except CommandNotFoundError as exc:
        parser.error(str(exc))
    except AttributeError as exc:
        parser.error(str(exc))

    # Preserve the original sys.argv so that subcommands that rely on
    # ``argparse`` or other CLI parsing work exactly as if they were invoked
    # directly. We scope the new argv to the lifecycle of the subcommand.
    original_argv = sys.argv
    sys.argv = [parsed.command, *parsed.args]
    try:
        result = command_main()
    finally:
        sys.argv = original_argv

    # Normalise ``None`` to ``0`` so that console scripts have a deterministic
    # exit status when the subcommand does not explicitly return anything.
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
