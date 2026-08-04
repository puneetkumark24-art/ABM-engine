"""Safe DRIP adapter for the standalone signal engine.

This package never imports DRIP outreach/orchestrator/delivery modules.
"""

from .bridge import SignalBridge

__all__ = ["SignalBridge"]
