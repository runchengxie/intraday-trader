import logging
import os
from datetime import date, datetime, timedelta

import pandas as pd

NY_TIMEZONE = "America/New_York"
from .db_handler import DBHandler

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# Cache directory will be provided as a parameter to functions that need it


# --- Helper Function to find the nearest previous trading day ---
def get_last_trading_day(api_instance, target_date_str):
    """Deprecated: use Alpaca calendar API directly via the broker handler."""
    logger.warning(
        "get_last_trading_day is deprecated and will be removed in a future version."
    )
    from datetime import timedelta

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


def _build_cache_path(
    cache_dir: str,
    symbol: str,
    timeframe,
    start_date: str,
    end_date: str,
    adjustment: str,
) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    timeframe_str = str(timeframe).replace("TimeFrame.", "")
    cache_filename = (
        f"{symbol}_{timeframe_str}_{adjustment}_{start_date}_{end_date}.parquet"
    )
    return os.path.join(cache_dir, cache_filename)


def _normalize_index_and_clip(
    df: pd.DataFrame, start_date: str, end_date: str
) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    normalized = df.copy()
    index = normalized.index
    if not isinstance(index, pd.DatetimeIndex):
        index = pd.to_datetime(index, utc=True)
    if index.tz is None:
        index = index.tz_localize("UTC")
    normalized.index = index.tz_convert(NY_TIMEZONE)

    start_ts = pd.Timestamp(start_date, tz=NY_TIMEZONE)
    end_ts = pd.Timestamp(end_date, tz=NY_TIMEZONE) + timedelta(days=1)
    mask = (normalized.index >= start_ts) & (normalized.index < end_ts)
    return normalized.loc[mask]


def _load_from_db(
    db_handler: DBHandler | None, symbol: str, start_date: str, end_date: str
) -> pd.DataFrame | None:
    if not db_handler:
        return None

    end_date_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
    end_date_query = end_date_dt.strftime("%Y-%m-%d")
    db_data = db_handler.get_market_data(symbol, start_date, end_date_query)

    if db_data is None or db_data.empty:
        logger.info(
            "No database records found for %s between %s and %s.",
            symbol,
            start_date,
            end_date,
        )
        return None

    logger.info("Successfully loaded data for %s from the database.", symbol)
    return db_data


def _load_from_cache(cache_filepath: str) -> pd.DataFrame | None:
    if not os.path.exists(cache_filepath):
        return None

    try:
        logger.info("Loading data from cache: %s", cache_filepath)
        return pd.read_parquet(cache_filepath)
    except Exception as exc:  # pragma: no cover - log path for debugging only
        logger.warning(
            "Error loading data from cache %s: %s. Will attempt to fetch from API.",
            cache_filepath,
            exc,
        )
        return None


def _fetch_from_api(
    api,
    symbol: str,
    timeframe,
    start_date: str,
    end_date: str,
    adjustment: str,
) -> pd.DataFrame | None:
    try:
        logger.info(
            "Fetching %s %s data from %s to %s via API...",
            symbol,
            timeframe,
            start_date,
            end_date,
        )
        start_dt_iso = (
            pd.Timestamp(start_date, tz=NY_TIMEZONE).tz_convert("UTC").isoformat()
        )
        end_dt_iso = (
            (
                pd.Timestamp(end_date, tz=NY_TIMEZONE)
                + timedelta(days=1)
                - timedelta(seconds=1)
            )
            .tz_convert("UTC")
            .isoformat()
        )

        bars = api.get_bars(
            symbol,
            timeframe,
            start=start_dt_iso,
            end=end_dt_iso,
            adjustment=adjustment,
        ).df
        return bars if bars is not None else None
    except Exception as exc:
        logger.error("Error fetching %s data: %s", symbol, exc)
        return None


def _cache_data(df: pd.DataFrame, cache_filepath: str) -> None:
    try:
        df.to_parquet(cache_filepath, engine="pyarrow", compression="snappy")
        logger.info("Data cached to: %s", cache_filepath)
    except Exception as exc:  # pragma: no cover - caching failures are non-fatal
        logger.warning("Error caching data: %s", exc)


def ensure_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure optional quote fields exist before persistence or analysis."""

    if df is None or df.empty:
        return df

    ensured = df.copy()
    if "trade_count" not in ensured.columns:
        ensured["trade_count"] = 0
    if "vwap" not in ensured.columns:
        ensured["vwap"] = (
            ensured["high"].astype(float)
            + ensured["low"].astype(float)
            + ensured["close"].astype(float)
        ) / 3.0
    return ensured


def fetch_api_bars(
    api,
    symbol: str,
    timeframe,
    start_date: str,
    end_date: str,
    adjustment: str = "raw",
) -> pd.DataFrame | None:
    """Fetch historical bars straight from the API with normalization."""

    bars = _fetch_from_api(
        api,
        symbol,
        timeframe,
        start_date,
        end_date,
        adjustment=adjustment,
    )
    if bars is None or getattr(bars, "empty", False):
        return None

    normalised = _normalize_index_and_clip(bars, start_date, end_date)
    return ensure_price_columns(normalised)


def fetch_historical_data(
    api,
    symbol,
    timeframe,
    start_date,
    end_date,
    cache_dir: str,
    db_handler: DBHandler = None,
    adjustment: str = "raw",
):
    """
    Fetches historical bar data, using the database as the primary cache.
    Falls back to the Alpaca API if data is not in the database.
    """

    cache_filepath = _build_cache_path(
        cache_dir, symbol, timeframe, start_date, end_date, adjustment
    )

    data_source = "database"
    bars = _load_from_db(db_handler, symbol, start_date, end_date)

    if bars is None:
        data_source = "cache"
        bars = _load_from_cache(cache_filepath)

    if bars is None:
        data_source = "api"
        bars = _fetch_from_api(
            api, symbol, timeframe, start_date, end_date, adjustment=adjustment
        )

    if bars is None or getattr(bars, "empty", False):
        logger.warning("No data retrieved for %s from any source.", symbol)
        return None

    bars = _normalize_index_and_clip(bars, start_date, end_date)

    if bars is None or bars.empty:
        logger.warning("No data retrieved for %s after applying filters.", symbol)
        return None

    bars = ensure_price_columns(bars)

    if data_source == "api":
        if db_handler:
            db_handler.save_market_data(bars.copy(), symbol)
        _cache_data(bars, cache_filepath)

    logger.info(
        "Successfully loaded %d data points for %s via %s.",
        len(bars),
        symbol,
        data_source,
    )
    return bars


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
    return pd.Series(smoothed)
