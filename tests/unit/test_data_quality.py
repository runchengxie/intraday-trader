1|import json
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|from datetime import datetime
3|
4|import pandas as pd
5|
6|from intraday_trader_air.data_quality import (
7|    build_expected_frequency,
8|    run_quality_checks,
9|    write_quality_report,
10|)
11|
12|
13|def _build_sample_frame():
14|    index = pd.date_range("2024-01-02 09:30", periods=5, freq="1min", tz="UTC")
15|    data = {
16|        "open": [100, 101, 102, 103, 104],
17|        "high": [101, 102, 103, 104, 105],
18|        "low": [99, 100, 101, 102, 103],
19|        "close": [100, 101, 102, 103, 104],
20|        "volume": [1000, 1100, 1200, 1300, 1400],
21|    }
22|    return pd.DataFrame(data, index=index)
23|
24|
25|def test_run_quality_checks_passes_on_clean_data():
26|    df = _build_sample_frame()
27|    report = run_quality_checks(df, "1min", "TEST")
28|
29|    assert report["overall_passed"] is True
30|    assert not report["warnings"]
31|    assert {check["name"] for check in report["checks"]} == {
32|        "timestamp_monotonicity",
33|        "missing_bars",
34|        "null_values",
35|        "price_jumps",
36|    }
37|
38|
39|def test_run_quality_checks_flags_missing_bar():
40|    frame = _build_sample_frame()
41|    df = frame.drop(frame.index[2])
42|    report = run_quality_checks(df, "1min", "TEST")
43|
44|    missing_bar_check = next(
45|        check for check in report["checks"] if check["name"] == "missing_bars"
46|    )
47|
48|    assert report["overall_passed"] is False
49|    assert missing_bar_check["passed"] is False
50|    assert missing_bar_check["details"]["missing_count"] == 1
51|
52|
53|def test_write_quality_report(tmp_path):
54|    df = _build_sample_frame()
55|    report = run_quality_checks(df, "1min", "TEST")
56|    report["timestamp"] = datetime(2024, 1, 2, 12, 0, 0).isoformat()
57|
58|    path = write_quality_report(report, tmp_path)
59|
60|    assert path.exists()
61|    payload = json.loads(path.read_text(encoding="utf-8"))
62|    assert payload["symbol"] == "TEST"
63|
64|
65|def test_build_expected_frequency_handles_units():
66|    assert build_expected_frequency(5, "Minute") == "5min"
67|    assert build_expected_frequency(2, "hour") == "2H"
68|    assert build_expected_frequency(1, "DAY") == "1D"
69|    assert build_expected_frequency(1, "weird") is None
70|

