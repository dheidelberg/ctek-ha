"""Constants for the CTEK cloud API."""

BASE_URL = "https://iot.ctek.com"
WS_URL = "wss://iot.ctek.com/api/v1/socket/devices/transaction/{device_id}"

# Credentials of the official Android app (se.ctek.ctekapp). The backend only
# accepts the password grant with these; there is no public client.
CLIENT_ID = "android_nS865khcg3ZWiBWF"
CLIENT_SECRET = "secret_@PhIL@gBdV<tpqBW7^2tQR8Yrq8;mvm_"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en",
    "User-Agent": "okhttp/4.12.0",
}

# Refresh this many seconds before the access token actually expires.
TOKEN_REFRESH_MARGIN = 300

# Device types as reported by /api/v3/device/list.
DEVICE_TYPE_CS_ONE_GEN_1 = "CS_ONE_GEN_1"
DEVICE_TYPE_CS_ONE_GEN_2 = "CS_ONE_GEN_2"

# Only devices with a cloud connection deliver live data. Gen 1 is BLE-only.
CLOUD_DEVICE_TYPES = {DEVICE_TYPE_CS_ONE_GEN_2}

CHARGE_PROGRAMS = ("APTO", "RECOND", "SUPPLY", "WAKE UP")
