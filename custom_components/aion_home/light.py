"""Light platform for dimmable AION Home devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import AionHomeBaseEntity
from .helpers import brightness_to_percent, percent_to_brightness


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load light descriptors from the coordinator and create light entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        AionHomeLightEntity(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("light")
    )


class AionHomeLightEntity(AionHomeBaseEntity, LightEntity):
    """Represent an AION light — either dimmable (brightness) or on/off only."""

    @property
    def _is_dimmable(self) -> bool:
        """Return True when the gateway descriptor carries a brightness_percent value."""
        return "brightness_percent" in self.descriptor.get("state", {})

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return BRIGHTNESS for dimmable lights, ONOFF for plain on/off lights."""
        if self._is_dimmable:
            return {ColorMode.BRIGHTNESS}
        return {ColorMode.ONOFF}

    @property
    def color_mode(self) -> ColorMode:
        """Return the active color mode matching the device capability."""
        if self._is_dimmable:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        """Expose the current on/off state from the normalized descriptor."""
        return bool(self.descriptor.get("state", {}).get("is_on", False))

    @property
    def brightness(self) -> int | None:
        """Return the current brightness in HA's 0-255 scale, or None for ONOFF lights."""
        if not self._is_dimmable:
            return None
        return percent_to_brightness(
            self.descriptor.get("state", {}).get("brightness_percent", 0)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light; applies brightness only when the device is dimmable."""
        if self._is_dimmable:
            brightness_percent = brightness_to_percent(kwargs.get("brightness", 255))
            # Firmware only accepts discrete 10-step levels (0, 10, 20, … 100).
            snapped = max(0, min(100, round(brightness_percent / 10) * 10))
            # Use 10 as minimum "on" value so we never send 0 when turning on.
            command_value = snapped if snapped > 0 else 10
        else:
            # Non-dimmable light: firmware uses 100/0 same as switches.
            command_value = 100
        state_patch = await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value=command_value,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light using the primary LAN command path."""
        state_patch = await self.coordinator.local_client.async_execute_primary(
            descriptor=self.descriptor,
            command_value=0,
        )
        await self.coordinator.async_apply_entity_patch(self._entity_uid, state_patch)