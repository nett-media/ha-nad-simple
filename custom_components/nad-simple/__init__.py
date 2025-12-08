"""The NAD Simple integration with async push support."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TYPE,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import DeviceInfo

from .client import NADClient, NADClientError, NADSerialClient, NADTCPClient
from .const import (
    CONF_SERIAL_PORT,
    CONF_TYPE_SERIAL,
    CONF_TYPE_TELNET,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
]


class NADReceiverCoordinator:
    """NAD Receiver Coordinator with push-based updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize NAD Receiver Coordinator."""
        self.hass = hass
        self.config = entry.data
        self.options = entry.options
        self.unique_id = entry.entry_id

        self.client: NADClient | None = None
        self.model: str | None = None
        self.version: str | None = None
        self.device_info: DeviceInfo | None = None
        self.sources: dict[int, str] = {}
        self.data: dict[str, str] = {}
        self.power_state: MediaPlayerState | None = None

        # Entity update callbacks
        self._listeners: list[Callable] = []
        self._update_debounce_task: asyncio.Task | None = None

        # Setup client based on connection type
        config_type = self.config[CONF_TYPE]
        if config_type == CONF_TYPE_SERIAL:
            serial_port = self.config[CONF_SERIAL_PORT]
            self.client = NADSerialClient(serial_port)
        elif config_type == CONF_TYPE_TELNET:
            host = self.config[CONF_HOST]
            port = self.config[CONF_PORT]
            self.client = NADTCPClient(host, port)

    async def connect(self) -> bool:
        """Connect to NAD receiver and fetch initial data."""
        if not self.client:
            _LOGGER.error("No client configured")
            return False

        try:
            # Connect to receiver
            await self.client.connect()

            # Set callback for push messages
            self.client.set_callback(self._handle_message)

            # Set callback for reconnect events
            self.client.set_reconnect_callback(self._handle_reconnect)

            # Query initial data
            await self.client.send_command("Main.Model", "?")
            await asyncio.sleep(0.3)  # Wait for response via callback
            self.model = self.data.get("Main.Model", "Unknown")

            await self.client.send_command("Main.Version", "?")
            await asyncio.sleep(0.3)
            self.version = self.data.get("Main.Version", "Unknown")

            # Setup device info
            identifiers = {(DOMAIN, self.unique_id)}
            if self.config[CONF_TYPE] == CONF_TYPE_SERIAL:
                identifiers.add((DOMAIN, self.config[CONF_SERIAL_PORT]))

            self.device_info = DeviceInfo(
                identifiers=identifiers,
                name=f"NAD {self.model}",
                model=self.model,
                manufacturer="NAD",
                sw_version=self.version,
            )

            # Get available sources
            await self._fetch_sources()

            # Query initial state
            await self.client.send_command("Main.Power", "?")
            await self.client.send_command("Main.Volume", "?")
            await self.client.send_command("Main.Mute", "?")
            await self.client.send_command("Main.Source", "?")
            await asyncio.sleep(0.5)  # Wait for all responses

            _LOGGER.info("Connected to NAD %s", self.model)
            return True

        except NADClientError as err:
            _LOGGER.error("Failed to connect to NAD receiver: %s", err)
            return False

    async def disconnect(self) -> None:
        """Disconnect from NAD receiver."""
        if self.client:
            await self.client.disconnect()

    async def _refresh_state(self) -> None:
        """Refresh current state after reconnect."""
        _LOGGER.debug("Refreshing state after reconnect")
        try:
            # Query current state
            await self.client.send_command("Main.Power", "?")
            await self.client.send_command("Main.Volume", "?")
            await self.client.send_command("Main.Mute", "?")
            await self.client.send_command("Main.Source", "?")
            await asyncio.sleep(0.5)  # Wait for all responses
            _LOGGER.debug("State refreshed successfully")
        except Exception as err:
            _LOGGER.error("Failed to refresh state: %s", err)

    async def _fetch_sources(self) -> None:
        """Fetch available input sources."""
        self.sources = {}

        for i in range(1, 13):
            await self.client.send_command(f"Source{i}.Enabled", "?")
            await asyncio.sleep(0.1)

            enabled = self.data.get(f"Source{i}.Enabled", "").lower()
            if enabled == "yes":
                await self.client.send_command(f"Source{i}.Name", "?")
                await asyncio.sleep(0.1)

                name = self.data.get(f"Source{i}.Name")
                if name:
                    self.sources[i] = name
                    _LOGGER.debug("Found source %d: %s", i, name)

    @callback
    def _handle_message(self, key: str, value: str) -> None:
        """Handle push message from NAD receiver.

        This is called by the client when a message is received.
        Updates internal state and notifies entities.
        """
        _LOGGER.debug("Push update: %s = %s", key, value)

        # Update data cache
        self.data[key] = value

        # Update power state for MediaPlayerState mapping
        if key == "Main.Power":
            if value.lower() == "on":
                self.power_state = MediaPlayerState.ON
            elif value.lower() == "off":
                self.power_state = MediaPlayerState.OFF

        # Debounce entity updates (avoid flooding when volume changes rapidly)
        if self._update_debounce_task and not self._update_debounce_task.done():
            self._update_debounce_task.cancel()

        self._update_debounce_task = self.hass.async_create_task(
            self._debounced_notify()
        )

    async def _debounced_notify(self) -> None:
        """Debounced notification to entities."""
        try:
            # Wait a short time to collect multiple rapid updates
            await asyncio.sleep(0.05)

            # Notify all listening entities (use copy to avoid modification during iteration)
            for update_callback in self._listeners.copy():
                update_callback()
        except asyncio.CancelledError:
            pass

    @callback
    def _handle_reconnect(self) -> None:
        """Handle reconnection event.

        Called when the client successfully reconnects.
        Triggers a state refresh.
        """
        _LOGGER.info("Reconnection successful, refreshing state")
        # Schedule state refresh
        self.hass.async_create_task(self._refresh_state())

    @callback
    def async_add_listener(self, update_callback: Callable) -> Callable:
        """Add a listener for data updates.

        Returns a function to remove the listener.
        """
        self._listeners.append(update_callback)

        def remove_listener() -> None:
            """Remove the listener."""
            self._listeners.remove(update_callback)

        return remove_listener

    async def async_send_command(
        self, command: str, operator: str = "?", value: str = ""
    ) -> str | None:
        """Send command to NAD receiver.

        Args:
            command: Command name (e.g., "Main.Power")
            operator: Operator ("?", "=", "+", "-")
            value: Value for "=" operator

        Returns:
            Current value from data cache (response comes via push)
        """
        if not self.client or not self.client.connected:
            _LOGGER.warning("Not connected to NAD receiver")
            return None

        try:
            await self.client.send_command(command, operator, value)

            # For commands that change state, wait briefly for push update
            if operator in ("=", "+", "-"):
                await asyncio.sleep(0.15)

            # Return current value from cache
            return self.data.get(command)

        except NADClientError as err:
            _LOGGER.error("Failed to send command %s: %s", command, err)
            return None

    def get_sources(self) -> dict[int, str]:
        """Get available sources (for compatibility)."""
        return self.sources


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NAD Receiver from a config entry."""

    @callback
    def _async_migrate_entity_entry(
        registry_entry: entity_registry.RegistryEntry,
    ) -> dict[str, Any] | None:
        """Migrate old unique ID to the new unique ID."""
        if entry.data[CONF_TYPE] == CONF_TYPE_SERIAL:
            if registry_entry.unique_id.startswith(f"{entry.data[CONF_SERIAL_PORT]}-"):
                new_unique_id = registry_entry.unique_id.replace(
                    f"{entry.data[CONF_SERIAL_PORT]}-",
                    f"{registry_entry.config_entry_id}-",
                )
                _LOGGER.debug("Migrating entity unique id to %s", new_unique_id)
                return {"new_unique_id": new_unique_id}

        # No migration needed
        return None

    await entity_registry.async_migrate_entries(
        hass, entry.entry_id, _async_migrate_entity_entry
    )

    try:
        coordinator = NADReceiverCoordinator(hass, entry)

        # Connect to receiver
        if not await coordinator.connect():
            raise ConfigEntryNotReady("Unable to connect to NAD receiver")

        _LOGGER.info("NAD receiver is available")

    except Exception as ex:
        raise ConfigEntryNotReady(f"Unable to connect to NAD receiver: {ex}") from ex

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: NADReceiverCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.disconnect()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Configuration options updated, reloading NAD receiver integration")
    await hass.config_entries.async_reload(entry.entry_id)
