"""Async client for the (unofficial) CTEK cloud API at iot.ctek.com.

Reverse-engineered from the CTEK Android app and verified against the live
backend on 2026-09-02. Kept as a self-contained subpackage so the Home
Assistant integration ships without an external PyPI dependency; it can be
extracted into its own distribution later.
"""

from .auth import CtekAuth
from .client import CtekClient
from .exceptions import CtekApiError, CtekAuthError, CtekConnectionError, CtekError
from .models import CHARGER_STATE_NAMES, CHARGER_STATES, Device, DeviceState, Token
from .stream import CtekDeviceStream

__all__ = [
    "CHARGER_STATE_NAMES",
    "CHARGER_STATES",
    "CtekApiError",
    "CtekAuth",
    "CtekAuthError",
    "CtekClient",
    "CtekConnectionError",
    "CtekDeviceStream",
    "CtekError",
    "Device",
    "DeviceState",
    "Token",
]
