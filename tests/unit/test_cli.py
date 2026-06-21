"""Unit tests for the ``intraday`` CLI entry point."""

from __future__ import annotations

import pytest

from intraday_trader_air.cli import CommandNotFoundError, _resolve_command, main


def test_resolve_backtest_run():
    target, args = _resolve_command(["backtest", "run", "--strategy", "ema"])
    assert "run_backtests:run_command" in target
    assert args == ["--strategy", "ema"]


def test_resolve_backtest_optimise():
    target, args = _resolve_command(["backtest", "optimise", "--strategy", "mr"])
    assert "run_backtests:optimise_command" in target
    assert args == ["--strategy", "mr"]


def test_resolve_backtest_optimize_alias():
    target, args = _resolve_command(["backtest", "optimize"])
    assert "run_backtests:optimise_command" in target
    assert args == []


def test_resolve_backtest_benchmark():
    target, args = _resolve_command(["backtest", "benchmark"])
    assert "run_backtests:benchmark_command" in target
    assert args == []


def test_resolve_data_backfill():
    target, args = _resolve_command(["data", "backfill", "--fields", "vwap"])
    assert "run_backfill_data:main" in target
    assert args == ["--fields", "vwap"]


def test_resolve_update_data():
    target, args = _resolve_command(["update-data"])
    assert "run_update_data:main" in target
    assert args == []


def test_resolve_live():
    target, args = _resolve_command(["live", "--config", "config.yml"])
    assert "run_live_trading:main" in target
    assert args == ["--config", "config.yml"]


def test_resolve_dashboard():
    target, args = _resolve_command(["dashboard"])
    assert "run_dashboard:main" in target
    assert args == []


def test_resolve_generate_report():
    target, args = _resolve_command(["generate-report"])
    assert "run_generate_report:main" in target
    assert args == []


def test_missing_command_raises():
    with pytest.raises(CommandNotFoundError, match="missing command"):
        _resolve_command([])


def test_unknown_top_level_command_raises():
    with pytest.raises(CommandNotFoundError, match="unknown command 'nope'"):
        _resolve_command(["nope"])


def test_missing_backtest_subcommand_raises():
    with pytest.raises(CommandNotFoundError, match="missing backtest command"):
        _resolve_command(["backtest"])


def test_unknown_backtest_subcommand_raises():
    with pytest.raises(
        CommandNotFoundError, match="unknown backtest command 'flibble'"
    ):
        _resolve_command(["backtest", "flibble"])


def test_missing_data_subcommand_raises():
    with pytest.raises(CommandNotFoundError, match="missing data command"):
        _resolve_command(["data"])


def test_unknown_data_subcommand_raises():
    with pytest.raises(CommandNotFoundError, match="unknown data command 'florp'"):
        _resolve_command(["data", "florp"])


def test_main_help_flag_returns_zero():
    assert main(["--help"]) == 0


def test_main_no_args_returns_zero():
    assert main([]) == 0


def test_main_short_help_flag_returns_zero():
    assert main(["-h"]) == 0
