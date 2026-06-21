1|"""Unit tests for the ``intraday`` CLI entry point."""
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|
3|from __future__ import annotations
4|
5|import pytest
6|
7|from intraday_trader_air.cli import CommandNotFoundError, _resolve_command, main
8|
9|
10|def test_resolve_backtest_run():
11|    target, args = _resolve_command(["backtest", "run", "--strategy", "ema"])
12|    assert "run_backtests:run_command" in target
13|    assert args == ["--strategy", "ema"]
14|
15|
16|def test_resolve_backtest_optimise():
17|    target, args = _resolve_command(["backtest", "optimise", "--strategy", "mr"])
18|    assert "run_backtests:optimise_command" in target
19|    assert args == ["--strategy", "mr"]
20|
21|
22|def test_resolve_backtest_optimize_alias():
23|    target, args = _resolve_command(["backtest", "optimize"])
24|    assert "run_backtests:optimise_command" in target
25|    assert args == []
26|
27|
28|def test_resolve_backtest_benchmark():
29|    target, args = _resolve_command(["backtest", "benchmark"])
30|    assert "run_backtests:benchmark_command" in target
31|    assert args == []
32|
33|
34|def test_resolve_data_backfill():
35|    target, args = _resolve_command(["data", "backfill", "--fields", "vwap"])
36|    assert "run_backfill_data:main" in target
37|    assert args == ["--fields", "vwap"]
38|
39|
40|def test_resolve_update_data():
41|    target, args = _resolve_command(["update-data"])
42|    assert "run_update_data:main" in target
43|    assert args == []
44|
45|
46|def test_resolve_live():
47|    target, args = _resolve_command(["live", "--config", "config.yml"])
48|    assert "run_live_trading:main" in target
49|    assert args == ["--config", "config.yml"]
50|
51|
52|def test_resolve_dashboard():
53|    target, args = _resolve_command(["dashboard"])
54|    assert "run_dashboard:main" in target
55|    assert args == []
56|
57|
58|def test_resolve_generate_report():
59|    target, args = _resolve_command(["generate-report"])
60|    assert "run_generate_report:main" in target
61|    assert args == []
62|
63|
64|def test_missing_command_raises():
65|    with pytest.raises(CommandNotFoundError, match="missing command"):
66|        _resolve_command([])
67|
68|
69|def test_unknown_top_level_command_raises():
70|    with pytest.raises(CommandNotFoundError, match="unknown command 'nope'"):
71|        _resolve_command(["nope"])
72|
73|
74|def test_missing_backtest_subcommand_raises():
75|    with pytest.raises(CommandNotFoundError, match="missing backtest command"):
76|        _resolve_command(["backtest"])
77|
78|
79|def test_unknown_backtest_subcommand_raises():
80|    with pytest.raises(
81|        CommandNotFoundError, match="unknown backtest command 'flibble'"
82|    ):
83|        _resolve_command(["backtest", "flibble"])
84|
85|
86|def test_missing_data_subcommand_raises():
87|    with pytest.raises(CommandNotFoundError, match="missing data command"):
88|        _resolve_command(["data"])
89|
90|
91|def test_unknown_data_subcommand_raises():
92|    with pytest.raises(CommandNotFoundError, match="unknown data command 'florp'"):
93|        _resolve_command(["data", "florp"])
94|
95|
96|def test_main_help_flag_returns_zero():
97|    assert main(["--help"]) == 0
98|
99|
100|def test_main_no_args_returns_zero():
101|    assert main([]) == 0
102|
103|
104|def test_main_short_help_flag_returns_zero():
105|    assert main(["-h"]) == 0
106|

