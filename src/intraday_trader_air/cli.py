"""Command-line entry point for the Intraday Trader Air framework."""

from __future__ import annotations

import argparse
import importlib
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

    for name, target in _BACKTEST_COMMANDS.items():
        sub = backtest_subparsers.add_parser(name, add_help=False)
        sub.add_argument("args", nargs=argparse.REMAINDER)
        sub.set_defaults(target=target)

    for name, target in _SIMPLE_COMMANDS.items():
        simple = subparsers.add_parser(name, add_help=False)
        simple.add_argument("args", nargs=argparse.REMAINDER)
        simple.set_defaults(target=target)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    parsed = parser.parse_args(argv)

    target_path = getattr(parsed, "target", None)
    if target_path is None:
        parser.print_help()
        return 0

    target = _load_callable(target_path)
    args = getattr(parsed, "args", [])
    result = target(args)
    return 0 if result is None else int(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
