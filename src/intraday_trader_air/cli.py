"""Command-line entry point for the Intraday Trader Air framework."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable, Sequence

_BACKTEST_COMMANDS = {
    "run": "intraday_trader_air.scripts.run_backtests:run_command",
    "optimise": "intraday_trader_air.scripts.run_backtests:optimise_command",
    "optimize": "intraday_trader_air.scripts.run_backtests:optimise_command",
    "benchmark": "intraday_trader_air.scripts.run_backtests:benchmark_command",
}

_SIMPLE_COMMANDS = {
    "update-data": "intraday_trader_air.scripts.run_update_data:main",
    "generate-report": "intraday_trader_air.scripts.run_generate_report:main",
    "live": "intraday_trader_air.scripts.run_live_trading:main",
    "dashboard": "intraday_trader_air.scripts.run_dashboard:main",
}

_DATA_COMMANDS = {
    "backfill": "intraday_trader_air.scripts.run_backfill_data:main",
}


_MIN_ARGS = 2


class CommandNotFoundError(RuntimeError):
    """Raised when a user invokes an unknown Intraday Trader Air subcommand."""


def _load_callable(path: str) -> Callable[[Sequence[str] | None], int | None]:
    module_name, func_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    if not callable(func):  # pragma: no cover - defensive path
        raise AttributeError(f"{path} is not callable")
    return func


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intraday",
        description=(
            "Intraday Trader Air command-line interface. "
            "Use one of the available subcommands to interact with the framework."
        ),
    )

    subparsers = parser.add_subparsers(dest="command")

    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Run backtest workflows (run/optimise/benchmark)",
    )
    backtest_subparsers = backtest_parser.add_subparsers(dest="backtest_command")

    for name in _BACKTEST_COMMANDS:
        backtest_subparsers.add_parser(name, add_help=False)

    for name in _SIMPLE_COMMANDS:
        subparsers.add_parser(name, add_help=False)

    data_parser = subparsers.add_parser(
        "data",
        help="Data maintenance utilities (backfill, migrations)",
    )
    data_subparsers = data_parser.add_subparsers(dest="data_command")

    for name in _DATA_COMMANDS:
        data_subparsers.add_parser(name, add_help=False)

    return parser


def _available(mapping: dict[str, str]) -> str:
    return ", ".join(sorted(mapping))


def _resolve_command(argv: Sequence[str]) -> tuple[str, list[str]]:
    """Resolve the top-level command and preserve all child command options."""

    if not argv:
        raise CommandNotFoundError("missing command")

    command = argv[0]

    if command == "backtest":
        if len(argv) < _MIN_ARGS:
            raise CommandNotFoundError(
                f"missing backtest command. "
                f"Available: {_available(_BACKTEST_COMMANDS)}"
            )
        subcommand = argv[1]
        target = _BACKTEST_COMMANDS.get(subcommand)
        if target is None:
            raise CommandNotFoundError(
                f"unknown backtest command '{subcommand}'. "
                f"Available: {_available(_BACKTEST_COMMANDS)}"
            )
        return target, list(argv[2:])

    if command == "data":
        if len(argv) < _MIN_ARGS:
            raise CommandNotFoundError(
                f"missing data command. "
                f"Available: {_available(_DATA_COMMANDS)}"
            )
        subcommand = argv[1]
        target = _DATA_COMMANDS.get(subcommand)
        if target is None:
            raise CommandNotFoundError(
                f"unknown data command '{subcommand}'. "
                f"Available: {_available(_DATA_COMMANDS)}"
            )
        return target, list(argv[2:])

    target = _SIMPLE_COMMANDS.get(command)
    if target is not None:
        return target, list(argv[1:])

    raise CommandNotFoundError(
        f"unknown command '{command}'. Available: "
        f"backtest, data, {_available(_SIMPLE_COMMANDS)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in {"-h", "--help"}:
        parser.print_help()
        return 0

    try:
        target_path, forwarded_args = _resolve_command(args)
    except CommandNotFoundError as exc:
        parser.error(str(exc))

    target = _load_callable(target_path)
    result = target(forwarded_args)
    return 0 if result is None else int(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
