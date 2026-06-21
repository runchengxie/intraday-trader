1|"""Common pytest fixtures for Intraday Trader Air."""
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|
3|from __future__ import annotations
4|
5|from collections.abc import Iterator
6|from pathlib import Path
7|from unittest import mock
8|
9|import pytest
10|
11|from intraday_trader_air.configuration import AppConfig, load_app_config
12|
13|
14|@pytest.fixture(scope="session")
15|def project_root() -> Path:
16|    return Path(__file__).resolve().parent.parent
17|
18|
19|@pytest.fixture
20|def tmp_output_dir(tmp_path: Path) -> Path:
21|    output_dir = tmp_path / "output"
22|    output_dir.mkdir()
23|    return output_dir
24|
25|
26|@pytest.fixture
27|def fake_config(project_root: Path, tmp_output_dir: Path) -> AppConfig:
28|    config_path = project_root / "config.yml"
29|    config = load_app_config(config_path)
30|    # Point outputs to the temporary directory to avoid polluting real artefacts
31|    config.paths = type(config.paths)(
32|        output_dir=tmp_output_dir,
33|        log_dir=tmp_output_dir / "logs",
34|        chart_dir=tmp_output_dir / "charts",
35|        cache_dir=tmp_output_dir / "cache",
36|    )
37|    for path in (config.paths.log_dir, config.paths.chart_dir, config.paths.cache_dir):
38|        path.mkdir(parents=True, exist_ok=True)
39|    return config
40|
41|
42|@pytest.fixture
43|def alpaca_stub() -> Iterator[object]:
44|    class _Stub:
45|        def __init__(self) -> None:
46|            self._calls: list[tuple[str, tuple, dict]] = []
47|
48|        def get_bars(self, symbol, timeframe, start, end, adjustment="raw"):
49|            self._calls.append(
50|                (
51|                    "get_bars",
52|                    (symbol, timeframe, start, end),
53|                    {"adjustment": adjustment},
54|                )
55|            )
56|            import pandas as pd
57|
58|            index = pd.date_range(start=start, periods=2, freq="min", tz="UTC")
59|            frame = pd.DataFrame(
60|                {
61|                    "open": [100.0, 101.0],
62|                    "high": [101.0, 102.0],
63|                    "low": [99.0, 100.0],
64|                    "close": [100.5, 101.5],
65|                    "volume": [1000, 1100],
66|                },
67|                index=index,
68|            )
69|            frame.index.name = "timestamp"
70|            return type("Response", (), {"df": frame})
71|
72|        def get_dividends(
73|            self, symbol, start, end
74|        ):  # pragma: no cover - used selectively
75|            self._calls.append(("get_dividends", (symbol, start, end), {}))
76|            return type(
77|                "Dividends",
78|                (),
79|                {
80|                    "df": None,
81|                },
82|            )
83|
84|    yield _Stub()
85|
86|
87|@pytest.fixture
88|def mocker():
89|    """Lightweight substitute for ``pytest-mock``'s fixture."""
90|
91|    active_patchers: list[object] = []
92|
93|    class _PatchProxy:
94|        def __init__(self, outer: _Mocker) -> None:
95|            self._outer = outer
96|
97|        def __call__(self, target, *args, **kwargs):
98|            return self._outer._patch(target, *args, **kwargs)
99|
100|        def object(self, target, attribute, *args, **kwargs):
101|            return self._outer.patch_object(target, attribute, *args, **kwargs)
102|
103|    class _Mocker:
104|        MagicMock = mock.MagicMock
105|
106|        def __init__(self) -> None:
107|            self.patch = _PatchProxy(self)
108|
109|        def _patch(self, target, *args, **kwargs):
110|            patcher = mock.patch(target, *args, **kwargs)
111|            mocked = patcher.start()
112|            active_patchers.append(patcher)
113|            return mocked
114|
115|        def patch_object(self, target, attribute, *args, **kwargs):
116|            patcher = mock.patch.object(target, attribute, *args, **kwargs)
117|            mocked = patcher.start()
118|            active_patchers.append(patcher)
119|            return mocked
120|
121|        def spy(self, obj, attribute):
122|            patcher = mock.patch.object(obj, attribute, wraps=getattr(obj, attribute))
123|            spy_obj = patcher.start()
124|            active_patchers.append(patcher)
125|            return spy_obj
126|
127|    try:
128|        yield _Mocker()
129|    finally:
130|        while active_patchers:
131|            active_patchers.pop().stop()
132|

