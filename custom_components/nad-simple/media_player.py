"""Support for interfacing with NAD receivers."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NADReceiverCoordinator
from .const import (
    CONF_DEFAULT_MAX_VOLUME,
    CONF_DEFAULT_MIN_VOLUME,
    CONF_MAX_VOLUME,
    CONF_MIN_VOLUME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the NAD Receiver media player."""
    coordinator: NADReceiverCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([NADMain(coordinator)])


class NAD(MediaPlayerEntity):
    """Representation of a NAD Receiver."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    zone = "Main"

    def __init__(self, coordinator: NADReceiverCoordinator):
        """Initialize the NAD Receiver device."""
        self.coordinator = coordinator

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"{coordinator.unique_id}-mediaplayer-{self.zone.lower()}"
        )

        self._min_volume = coordinator.options.get(
            CONF_MIN_VOLUME, CONF_DEFAULT_MIN_VOLUME
        )
        self._max_volume = coordinator.options.get(
            CONF_MAX_VOLUME, CONF_DEFAULT_MAX_VOLUME
        )

        self._source_dict = coordinator.sources
        self._reverse_mapping = {value: key for key, value in self._source_dict.items()}

        # Remove listener callback when entity is removed
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks with coordinator."""
        _LOGGER.debug("async_added_to_hass")

        # Register with coordinator for updates
        self._remove_listener = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )

        # Initial update
        self._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._remove_listener:
            self._remove_listener()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("_handle_coordinator_update")

        # Availability based on connection state, not power state
        self._attr_available = (
            self.coordinator.client is not None
            and self.coordinator.client.connected
        )

        if self._attr_available:
            # Use power_state from coordinator (already mapped to MediaPlayerState)
            # Use OFF as fallback if power state not yet known
            self._attr_state = self.coordinator.power_state or MediaPlayerState.OFF

            if self.coordinator.power_state == MediaPlayerState.ON:
                # Update mute status
                self._attr_is_volume_muted = (
                    self.coordinator.data.get(self.zone + ".Mute", "").lower() == "on"
                )

                # Update volume
                volume = self.coordinator.data.get(self.zone + ".Volume")
                if volume is not None and volume.lstrip("-").isnumeric():
                    volume = float(volume)
                    self._attr_volume_level = self.calc_volume(volume)
                else:
                    # Some receivers cannot report the volume, e.g. C 356BEE,
                    # instead they only support stepping the volume up or down
                    self._attr_volume_level = None

                # Update source
                source = self.coordinator.data.get(self.zone + ".Source")
                if source and source.isnumeric():
                    self._attr_source = self._source_dict.get(int(source))

        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        await self.coordinator.async_send_command(self.zone + ".Power", "=", "Off")

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        await self.coordinator.async_send_command(self.zone + ".Power", "=", "On")

    async def async_volume_up(self) -> None:
        """Volume up the media player."""
        await self.coordinator.async_send_command(self.zone + ".Volume", "+")

    async def async_volume_down(self) -> None:
        """Volume down the media player."""
        await self.coordinator.async_send_command(self.zone + ".Volume", "-")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self.coordinator.async_send_command(
            self.zone + ".Volume", "=", str(int(self.calc_db(volume)))
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute (true) or unmute (false) media player."""
        if mute:
            await self.coordinator.async_send_command(self.zone + ".Mute", "=", "On")
        else:
            await self.coordinator.async_send_command(self.zone + ".Mute", "=", "Off")

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        _LOGGER.debug("async_select_source(%s)", source)

        if source in self._reverse_mapping:
            source_id = self._reverse_mapping[source]
        elif source.isnumeric() and int(source) in self._source_dict:
            source_id = int(source)
        else:
            raise HomeAssistantError(f"Source {source} invalid")

        _LOGGER.debug("Source ID: %s", source_id)

        await self.coordinator.async_send_command(
            self.zone + ".Source", "=", str(source_id)
        )

    @property
    def source_list(self):
        """List of available input sources."""
        return list(self._reverse_mapping)

    def calc_volume(self, decibel):
        """Calculate the volume given the decibel.

        Return the volume (0..1).
        """
        return abs(self._min_volume - decibel) / abs(
            self._min_volume - self._max_volume
        )

    def calc_db(self, volume):
        """Calculate the decibel given the volume.

        Return the dB.
        """
        return self._min_volume + round(
            abs(self._min_volume - self._max_volume) * volume
        )


class NADMain(NAD):
    """Representation of a NAD Receiver - Main Zone."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    zone = "Main"
