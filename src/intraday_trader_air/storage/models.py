"""SQLAlchemy ORM models for the intraday trader storage layer."""

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MarketData(Base):
    """Minute-level market data stored per-symbol, per-timestamp."""

    __tablename__ = "market_data"
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    symbol = Column(String, nullable=False, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    trade_count = Column(Integer)
    vwap = Column(Float)


class TradeLog(Base):
    """Record of each executed trade (filled order)."""

    __tablename__ = "trade_logs"
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    order_id = Column(String, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float)
    pnl = Column(Float)


class PerformanceSnapshot(Base):
    """Periodic portfolio valuation snapshot."""

    __tablename__ = "performance_snapshots"
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    portfolio_value = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)


__all__ = ["Base", "MarketData", "PerformanceSnapshot", "TradeLog"]
