"""Constants for the CTEK integration."""

from datetime import timedelta

DOMAIN = "ctek"

CONF_TOKEN = "token"

# REST polling for the device list (online flag, firmware, alias). Live values
# arrive via websocket, so this only needs to be slow.
UPDATE_INTERVAL = timedelta(minutes=5)

PLATFORMS = ["sensor", "binary_sensor", "update"]
