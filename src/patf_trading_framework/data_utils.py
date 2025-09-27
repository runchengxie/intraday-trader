import logging
import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .db_handler import DBHandler


# --- Logging Setup ---
logger = logging.getLogger(__name__)

# Cache directory will be provided as a parameter to functions that need it


# --- Helper Function to find the nearest previous trading day ---
def get_last_trading_day(api_instance, target_date_str):
    """
    Finds the trading day on or immediately preceding the target date.

    Args:
        api_instance (REST): Initialized Alpaca API client.
        target_date_str (str): The target date in 'YYYY-MM-DD' format.

    Returns:
        str: The date string of the actual trading day in 'YYYY-MM-DD' format, or None if an error occurs.
    """
    target_dt = date.fromisoformat(target_date_str)
    # Check a window around the target date for the calendar
    calendar_start = (target_dt - timedelta(days=10)).strftime("%Y-%m-%d")
    calendar_end = target_dt.strftime("%Y-%m-%d")

    try:
        calendar = api_instance.get_calendar(start=calendar_start, end=calendar_end)
        trading_days = {
            cal.date.date() for cal in calendar
        }  # Use .date() to get date object

        current_dt = target_dt
        while current_dt >= date.fromisoformat(calendar_start):
            if current_dt in trading_days:
                logger.info(
                    f"Trading day for target date {target_date_str} determined as: {current_dt.strftime('%Y-%m-%d')}"
                )  # Use logger
                return current_dt.strftime("%Y-%m-%d")
            current_dt -= timedelta(days=1)

        logger.error(
            f"Error: No trading day found between {calendar_start} and {target_date_str}."
        )  # Use logger
        return None
    except Exception as e:
        logger.error(f"Error retrieving trading calendar: {e}")  # Use logger
        return None


def fetch_historical_data(
    api,
    symbol,
    timeframe,
    start_date,
    end_date,
    cache_dir: str,
    db_handler: DBHandler = None,
):
    """
    Fetches historical bar data, using the database as the primary cache.
    Falls back to the Alpaca API if data is not in the database.
    """
    # --- 1. Try fetching from Database ---
    if db_handler:
        # End date for query needs to be exclusive
        end_date_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
        end_date_query = end_date_dt.strftime("%Y-%m-%d")

        db_data = db_handler.get_market_data(symbol, start_date, end_date_query)
        if not db_data.empty:
            logger.info(f"Successfully loaded data for {symbol} from the database.")
            # Filter again to ensure strict date range
            db_data = db_data[start_date:end_date]
            return db_data

    # --- 2. Fallback to API Fetch (original logic) ---
    logger.info(f"Data for {symbol} not found in DB, fetching from API...")
    # --- Cache Handling ---
    # Ensure cache directory exists
    os.makedirs(cache_dir, exist_ok=True)

    # Create a unique filename for the cache
    timeframe_str = str(timeframe).replace(
        "TimeFrame.", ""
    )  # Get a string representation like 'Minute'
    cache_filename = f"{symbol}_{timeframe_str}_{start_date}_{end_date}.parquet"
    cache_filepath = os.path.join(cache_dir, cache_filename)

    # Check if cached file exists
    if os.path.exists(cache_filepath):
        try:
            logger.info(f"Loading data from cache: {cache_filepath}")  # Use logger
            bars = pd.read_parquet(cache_filepath)
            # Parquet usually handles timezone better, but double-check
            if not isinstance(bars.index, pd.DatetimeIndex):
                bars.index = pd.to_datetime(bars.index)  # Ensure index is datetime
            if bars.index.tz is None:
                bars.index = bars.index.tz_localize("UTC")  # Assume UTC if no timezone
            bars.index = bars.index.tz_convert(
                "America/New_York"
            )  # Convert to desired timezone
            # Filter again to ensure strict date range after loading from cache
            bars = bars[
                (bars.index >= pd.Timestamp(start_date, tz="America/New_York"))
                & (
                    bars.index
                    <= pd.Timestamp(end_date, tz="America/New_York") + timedelta(days=1)
                )
            ]
            logger.info(
                f"Successfully loaded {len(bars)} data points from cache."
            )  # Use logger
            return bars
        except Exception as e:
            logger.warning(
                f"Error loading data from cache: {e}. Will attempt to fetch from API."
            )  # Use logger
            # If loading fails, proceed to fetch from API

    # --- Fetch from API (if not cached or cache load failed) ---
    try:
        logger.info(
            f"Fetching {symbol} {timeframe} data from {start_date} to {end_date} via API..."
        )  # Use logger
        # Note: Alpaca's get_bars returns data in UTC.
        start_dt_iso = (
            pd.Timestamp(start_date, tz="America/New_York")
            .tz_convert("UTC")
            .isoformat()
        )
        end_dt_iso = (
            (
                pd.Timestamp(end_date, tz="America/New_York")
                + timedelta(days=1)
                - timedelta(seconds=1)
            )
            .tz_convert("UTC")
            .isoformat()
        )

        api_bars = api.get_bars(
            symbol, timeframe, start=start_dt_iso, end=end_dt_iso, adjustment="raw"
        ).df

        if not api_bars.empty:
            # Convert index to America/New_York timezone for consistency
            api_bars.index = api_bars.index.tz_convert("America/New_York")
            # Filter data strictly within the requested start/end dates in NY time
            api_bars = api_bars[
                (api_bars.index >= pd.Timestamp(start_date, tz="America/New_York"))
                & (
                    api_bars.index
                    <= pd.Timestamp(end_date, tz="America/New_York") + timedelta(days=1)
                )
            ]

            logger.info(
                f"Successfully fetched {len(api_bars)} data points from API."
            )  # Use logger

            # --- 3. Save newly fetched data to Database and Cache ---
            if not api_bars.empty:
                # Save to DB
                if db_handler:
                    db_handler.save_market_data(api_bars.copy(), symbol)

                # Save to file cache (can be kept as a backup)
                try:
                    # Use df.to_parquet. No need to reset index usually.
                    # Specify the engine and potentially compression
                    api_bars.to_parquet(
                        cache_filepath, engine="pyarrow", compression="snappy"
                    )  # 'snappy' is a common choice
                    logger.info(f"Data cached to: {cache_filepath}")  # Use logger
                except Exception as e:
                    logger.warning(
                        f"Error caching data: {e}"
                    )  # Use logger - Log caching error but continue

            return api_bars
        else:
            logger.warning(f"No data retrieved for {symbol} from any source.")
            return None  # Return None if no data fetched

    except Exception as e:
        logger.error(f"Error fetching {symbol} data: {e}")  # Use logger
        return None


# --- Price smoothing helper (formerly Kalman filter) ---
def apply_kalman_filter(prices: pd.Series, span: int = 10) -> pd.Series:
    """Lightweight price smoother used in place of the previous Kalman filter.

    The original implementation relied on the ``pykalman`` dependency, which we
    dropped to simplify the prototype stack.  For an initial MVP a low-latency
    exponential moving average provides comparable noise reduction while keeping
    the dependency footprint minimal.  The function signature remains the same so
    callers do not need to change.
    """

    if prices is None or prices.empty:
        return prices

    smoothed = prices.ewm(span=span, adjust=False).mean()
    smoothed.name = getattr(prices, "name", "smoothed")
    return smoothed


def _compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Compute ADX and directional indicators without external libraries."""

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    up_move = high.diff()
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_components = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    )
    true_range = tr_components.max(axis=1)

    atr = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = (
        pd.Series(plus_dm, index=df.index)
        .ewm(alpha=1 / period, min_periods=period, adjust=False)
        .mean()
        / atr
    ) * 100
    minus_di = (
        pd.Series(minus_dm, index=df.index)
        .ewm(alpha=1 / period, min_periods=period, adjust=False)
        .mean()
        / atr
    ) * 100

    directional_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = (plus_di - minus_di).abs() / directional_sum * 100
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    return pd.DataFrame(
        {
            f"adx_{period}": adx,
            f"dmp_{period}": plus_di,
            f"dmn_{period}": minus_di,
        }
    )


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a minimal set of technical indicators using pandas-native
    calculations so we can avoid heavy third-party dependencies during
    prototyping.  The function keeps the previous column names to remain
    compatible with existing strategy code.

    Args:
        df (pd.DataFrame): DataFrame with 'open', 'high', 'low', 'close' columns.

    Returns:
        pd.DataFrame: The DataFrame with added indicator columns.
    """
    if not all(col in df.columns for col in ["high", "low", "close"]):
        logger.error("DataFrame is missing required columns ('high','low','close') for TA.")
        return df

    logger.info("Adding technical indicators (SMA, EMA, ADX) using pandas only...")
    df["sma_20"] = df["close"].rolling(window=20, min_periods=20).mean()
    df["sma_50"] = df["close"].rolling(window=50, min_periods=50).mean()
    df["ema_12"] = df["close"].ewm(span=12, adjust=False).mean()

    adx_df = _compute_adx(df, period=14)
    df = df.join(adx_df)

    required = ["ema_12", "adx_14"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"Technical indicators missing after TA step: {missing}")

    return df
