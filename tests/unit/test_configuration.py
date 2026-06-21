1|from pathlib import Path
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|
3|import pytest
4|
5|pytest.importorskip("yaml")
6|
7|from intraday_trader_air.configuration import ConfigurationError, load_app_config
8|
9|
10|def test_load_app_config(tmp_path: Path):
11|    config_path = tmp_path / "config.yml"
12|    config_path.write_text(
13|        """
14|        data:
15|          ticker: "SPY"
16|          timeframe_value: 15
17|          timeframe_unit: "Minute"
18|          start_date: "2024-01-01"
19|          end_date: "2024-01-31"
20|          adjustment: "split"
21|        paths:
22|          output_dir: "output"
23|          log_dir: "output/logs"
24|          chart_dir: "output/charts"
25|          cache_dir: "output/cache"
26|        benchmark:
27|          enabled: true
28|          total_return: true
29|        backtest:
30|          initial_cash: 100000
31|          commission: 0.001
32|          max_cpus: "auto"
33|        strategies:
34|          dummy:
35|            class_name: "MeanReversionZScoreStrategy"
36|        logging:
37|          level: "INFO"
38|          format: "%(message)s"
39|          datefmt: "%Y"
40|        """,
41|        encoding="utf-8",
42|    )
43|
44|    config = load_app_config(config_path)
45|    assert config.data.resample_frequency == "15min"
46|    assert config.backtest.max_cpus >= 1
47|    assert config.benchmark.total_return is True
48|    assert config.strategies[0].key == "dummy"
49|
50|
51|def test_invalid_timeframe_raises(tmp_path: Path):
52|    config_path = tmp_path / "config.yml"
53|    config_path.write_text(
54|        """
55|        data:
56|          ticker: "SPY"
57|          timeframe_value: 15
58|          timeframe_unit: "Invalid"
59|          start_date: "2024-01-01"
60|          end_date: "2024-01-31"
61|        paths:
62|          output_dir: "output"
63|          log_dir: "output/logs"
64|          chart_dir: "output/charts"
65|          cache_dir: "output/cache"
66|        benchmark:
67|          enabled: false
68|        backtest:
69|          initial_cash: 100000
70|          commission: 0.001
71|          max_cpus: 1
72|        strategies: {}
73|        logging:
74|          level: "INFO"
75|          format: "%(message)s"
76|          datefmt: "%Y"
77|        """,
78|        encoding="utf-8",
79|    )
80|
81|    with pytest.raises(ConfigurationError):
82|        load_app_config(config_path)
83|
