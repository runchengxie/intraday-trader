import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# --- Path Setup ---
# Ensures that other project modules can be found by Streamlit
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from intraday_trader_air.configuration import load_app_config
from intraday_trader_air.db_handler import DBHandler
from intraday_trader_air.performance_analyzer import PerformanceAnalyzer
from intraday_trader_air.risk_manager import RiskManager

# --- Main Application Logic ---
st.set_page_config(layout="wide", page_title="Trading Performance Dashboard")

st.title("Algorithmic Trading Performance Dashboard")

# Load environment variables from .env before loading config
load_dotenv()

# --- Load config and initialize ---
try:
    config = load_app_config(Path("config.yml"))
    db_handler = DBHandler(asdict(config.database) if config.database else {})
    db_handler.initialize_db()
except Exception as e:
    st.error(f"Failed to initialize application: {e}")
    # Stop execution if config fails
    st.stop()

# --- Sidebar for controls ---
st.sidebar.header("Dashboard Controls")
days_to_load = st.sidebar.slider("Days of data to load", 1, 90, 7)

end_date = datetime.now()
start_date = end_date - timedelta(days=days_to_load)


# --- Load data ---
@st.cache_data(ttl=600)  # Cache for 10 minutes
def load_data(start, end):
    trade_logs_df = db_handler.get_trade_logs_as_df(start, end)
    perf_snapshots_df = db_handler.get_performance_snapshots_as_df(start, end)
    return trade_logs_df, perf_snapshots_df


trade_logs, perf_snapshots = load_data(start_date, end_date)

if perf_snapshots.empty:
    st.warning("No performance snapshots found for the selected period.")
else:
    # --- Calculate metrics using PerformanceAnalyzer ---
    initial_capital = config.backtest.initial_cash
    analyzer = PerformanceAnalyzer(initial_capital)
    risk_manager = RiskManager()

    # Populate analyzer with snapshot data
    analyzer.portfolio_values = list(
        zip(perf_snapshots["timestamp"], perf_snapshots["portfolio_value"])
    )
    returns = analyzer.calculate_returns()
    if not returns.empty:
        for r in returns:
            risk_manager.returns_history.append(r)

    # --- Display Key Performance Indicators (KPIs) ---
    st.header("Key Performance Indicators (KPIs)")

    latest_value = perf_snapshots["portfolio_value"].iloc[-1]
    total_return_pct = (latest_value / initial_capital - 1) * 100

    risk_metrics = analyzer.calculate_risk_metrics()
    var_result = risk_manager.calculate_var(latest_value)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Return", f"{total_return_pct:.2f}%")
    col2.metric("Sharpe Ratio", f"{risk_metrics.get('sharpe_ratio', 0):.2f}")
    col3.metric("Max Drawdown", f"{risk_metrics.get('max_drawdown', 0)*100:.2f}%")
    col4.metric("Daily VaR (95%)", f"${var_result.get('var', 0):,.2f}")

    # --- Display charts ---
    st.header("Performance Charts")
    st.subheader("Portfolio Value Over Time")
    st.line_chart(perf_snapshots.set_index("timestamp")["portfolio_value"])

    st.subheader("Recent Trades")
    st.dataframe(trade_logs.sort_values(by="timestamp", ascending=False))
