"""Constants for the AION Home integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "aion_home"

CONF_GATEWAY_URL = "gateway_url"
CONF_GATEWAY_TOKEN = "gateway_token"
CONF_HA_ACCESS_TOKEN = "ha_access_token"
CONF_HA_ID = "ha_id"
CONF_PAIRING_TOKEN = "pairing_token"
CONF_INSTANCE_NAME = "instance_name"
CONF_QR_PAYLOAD = "qr_payload"

AION_GATEWAY_URL = "https://aion-ha-gateway-4ozwcqqm.ew.gateway.dev"
AION_GATEWAY_API_KEY = "AIzaSyAZlVofbQBZd3IfrOMFZF4UPuT6V0sJRTE"

HEADER_GATEWAY_API_KEY = "x-api-key"

DATA_API = "api"
DATA_COORDINATOR = "coordinator"
DATA_LOCAL_CLIENT = "local_client"

LOCAL_COMMAND = "9854FA69739A7"
LOCAL_STATE = "FD77E3EB765FF"
LOCAL_INIT = "ZRX7NPIKU60NZ"
LOCAL_IR_ACTION = "BPH4NSEYPTLZT"
LOCAL_AC_ACTION = "OHG3TLNG1OHG3"
LOCAL_AUX_COMMANDS = "8DD6DA24A3D24"
LOCAL_RESTART_COMMAND = "F8B76985D5FAC"

PAIR_EXCHANGE_PATH = "/v1/ha/exchange"
SYNC_BOOTSTRAP_PATH = "/v1/ha/sync"

PLATFORMS = (
    "switch",
    "light",
    "cover",
    "lock",
    "remote",
    "climate",
    "button",
    "number",
    "select",
    "sensor",
    "media_player",
    "fan",
    "water_heater",
)

COORDINATOR_INTERVAL = timedelta(hours=24)
LOCAL_POLL_INTERVAL = timedelta(seconds=30)
SESSION_TTL_MS = 60 * 60 * 1000

QR_PAYLOAD_VERSION = 1
QR_PROVIDER = "aion_home"

SERVICE_SEND_AUX_COMMAND = "send_aux_command"
SERVICE_RESYNC_GATEWAY = "resync_gateway"

ATTR_ENTITY_UID = "entity_uid"
ATTR_DEVICE_UID = "device_uid"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_COMMAND_TYPE = "command_type"
ATTR_COMMAND_PAYLOAD = "command_payload"

ENTITY_CATEGORY_PRIMARY = "primary"
ENTITY_CATEGORY_AUXILIARY = "auxiliary"

DEFAULT_SCAN_LANGUAGE = "en"
DEFAULT_SCAN_ROOM_ALIAS = "home"

# AC mode codes as stored in device.AC[id].m — power off is controlled by p=0, not m.
HVAC_MODE_MAP = {
    "0": "auto",
    "1": "cool",
    "2": "heat",
    "3": "dry",
    "4": "fan_only",
}

# AC fan speed codes as stored in device.AC[id].f
FAN_MODE_MAP = {
    "0": "auto",
    "1": "min",
    "2": "low",
    "3": "medium",
    "4": "high",
    "5": "max",
}

SWITCH_CATEGORIES = {
    "Normal Light",
    "Electric Device",
    "Multi-Gang",
}

BRIGHTNESS_CATEGORIES = {
    "Dimmable Light",
}

COVER_CATEGORIES = {
    "Shutters",
}

LOCK_CATEGORIES = {
    "Door Lock",
}

IR_REMOTE_CATEGORY = "IR Remote"