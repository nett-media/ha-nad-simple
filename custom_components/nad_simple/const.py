"""Constants for the NAD Simple integration."""

from typing import Final

DOMAIN: Final = "nad_simple"

CONF_TYPE_SERIAL: Final = "RS232"
CONF_TYPE_TELNET: Final = "Telnet"

CONF_SERIAL_PORT: Final = "serial_port"
CONF_DEFAULT_PORT: Final = 23

CONF_MIN_VOLUME: Final = "min_volume"
CONF_MAX_VOLUME: Final = "max_volume"

CONF_DEFAULT_MIN_VOLUME: Final = -92
CONF_DEFAULT_MAX_VOLUME: Final = -20
