"""Fan platform for AION IR remotes (Fan, Air Purifier)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AionHomeDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a fan entity for each IR sub-remote of type Fan or Air Purifier."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities = [
        AionIRFan(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("fan")
        if descriptor.get("control", {}).get("family") == "ir"
    ]
    # LOGGER.info("[AION][fan] setup_entry: registering %d entities", len(entities))
    async_add_entities(entities)


class AionIRFan(CoordinatorEntity[AionHomeDataUpdateCoordinator], FanEntity):
    """
    Represent an IR-controlled fan or air purifier.

    Power maps to HA turn_on/turn_off.
    All other non-shortcut commands become preset_modes so users can pick speeds
    and oscillation modes from the fan card's preset selector.
    State is fully optimistic — IR provides no feedback.
    """

    _attr_has_entity_name = True
    # Unknown state — IR has no feedback.
    _attr_is_on: bool | None = None

    def __init__(
        self,
        coordinator: AionHomeDataUpdateCoordinator,
        descriptor: dict[str, Any],
    ) -> None:
        """Store entity uid and cache stable device/remote metadata."""
        super().__init__(coordinator)
        self._entity_uid: str = descriptor["entity_uid"]
        self._attr_unique_id = self._entity_uid
        self._attr_name: str = descriptor.get("name", "")

        device = descriptor.get("device", {})
        control = descriptor.get("control", {})
        self._device_uid: str = device.get("device_uid", "")
        self._device_room: str = device.get("room_name", "")
        self._remote_id: str = control.get("remote_id", "")
        self._remote_type: str = control.get("remote_type") or "IR Fan"
        self._remote_brand: str = control.get("brand") or "AION"
        self._virtual_device_uid: str = (
            f"{self._device_uid}::ir_{self._remote_id}"
            if self._remote_id
            else self._device_uid
        )
        # Build preset list from ha_extra_commands (all non-power commands).
        self._preset_list: list[str] = list(
            control.get("ha_extra_commands", {}).keys()
        )

    @property
    def _descriptor(self) -> dict[str, Any]:
        """Return the live descriptor from the coordinator cache."""
        return self.coordinator.get_entity(self._entity_uid) or {}

    @property
    def available(self) -> bool:
        """Available when the parent device has a reachable local connection."""
        desc = self._descriptor
        local = desc.get("local", {})
        if not (
            bool(local.get("device_ip"))
            and bool(local.get("device_ssid"))
            and bool(local.get("main_key"))
        ):
            return False
        return desc.get("local_available", True)

    @property
    def device_info(self) -> DeviceInfo:
        """Attach this entity to its sub-remote's virtual device card."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._virtual_device_uid)},
            name=self._attr_name,
            model=self._remote_type,
            manufacturer=self._remote_brand,
            suggested_area=self._device_room,
            via_device=(DOMAIN, self._device_uid) if self._remote_id else None,
        )

    @property
    def supported_features(self) -> FanEntityFeature:
        """
        Advertise power buttons always, and preset modes only when available.

        HA will only surface turn_on/turn_off actions when the entity reports
        the corresponding feature flags.
        """
        features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        if self.preset_modes:
            features |= FanEntityFeature.PRESET_MODE
        return features

    @property
    def preset_modes(self) -> list[str] | None:
        """Expose all non-power IR commands as preset modes."""
        return self._preset_list or None

    @property
    def preset_mode(self) -> str | None:
        """Always unknown — IR provides no state feedback."""
        return None

    def _get_service_command(self, service: str) -> str | None:
        """
        Look up the IR command label mapped to a given HA service name.

        Returns None if no mapping exists for this service on this remote type.
        """
        control = self._descriptor.get("control", {})
        return control.get("ha_service_map", {}).get(service)

    async def _fire(self, service: str) -> None:
        """Fire the IR command associated with a given HA service name."""
        command_label = self._get_service_command(service)
        if not command_label:
            return
        await self.coordinator.local_client.async_execute_service_command(
            descriptor=self._descriptor,
            command_type="ir",
            command_payload=command_label,
        )

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Send Power IR command to turn the fan on."""
        await self._fire("turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send Power IR command to turn the fan off."""
        await self._fire("turn_off")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """
        Fire the IR command whose label matches the requested preset name.

        The preset label is used directly as the command_payload so the local client
        can look it up in the commands dict and send the correct IR code.
        """
        await self.coordinator.local_client.async_execute_service_command(
            descriptor=self._descriptor,
            command_type="ir",
            command_payload=preset_mode,
        )
