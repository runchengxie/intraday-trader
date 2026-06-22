"""Multi-broker adapter layer (Phase 1).

Exports:
    - ``protocols``: standard data models and the BrokerAdapter protocol.
    - ``factory.create_broker``: instantiate the configured broker adapter.
    - ``AlpacaBrokerAdapter``, ``FutuBrokerAdapter``: concrete adapters.
"""

from .alpaca import AlpacaBrokerAdapter
from .factory import create_broker
from .futu import FutuBrokerAdapter

__all__ = [
    "AlpacaBrokerAdapter",
    "FutuBrokerAdapter",
    "create_broker",
]
