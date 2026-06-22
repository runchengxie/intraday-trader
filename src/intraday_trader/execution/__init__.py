"""Safe execution pipeline (Phase 4).

Signal → Target → OrderPlan → BrokerAdapter.

This package converts raw trading signals into auditable order plans
before submitting them through the multi-broker adapter layer.
"""

from .executor import execute_close_via_order, execute_order_plan
from .order_plan import (
    OrderPlanEntry,
    OrderPlanOptions,
    build_close_plan,
    build_order_plan,
)
from .targets import SignalTarget, signal_to_target

__all__ = [
    "OrderPlanEntry",
    "OrderPlanOptions",
    "SignalTarget",
    "build_close_plan",
    "build_order_plan",
    "execute_close_via_order",
    "execute_order_plan",
    "signal_to_target",
]
