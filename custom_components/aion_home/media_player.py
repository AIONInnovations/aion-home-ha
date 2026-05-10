"""Media player platform for AION IR remotes (TV, STB, Projector, Speaker)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AionHomeDataUpdateCoordinator

# Map from ha_service_map key → the HA feature flag it enables.
# This drives dynamic supported_features: only flags for services that exist
# in the live ha_service_map are advertised to HA, keeping the UI clean.
_SERVICE_FEATURE_MAP: dict[str, MediaPlayerEntityFeature] = {
    "turn_on":              MediaPlayerEntityFeature.TURN_ON,
    "turn_off":             MediaPlayerEntityFeature.TURN_OFF,
    "volume_up":            MediaPlayerEntityFeature.VOLUME_STEP,
    "volume_down":          MediaPlayerEntityFeature.VOLUME_STEP,
    "mute_volume":          MediaPlayerEntityFeature.VOLUME_MUTE,
    "media_next_track":     MediaPlayerEntityFeature.NEXT_TRACK,
    "media_previous_track": MediaPlayerEntityFeature.PREVIOUS_TRACK,
    "media_play":           MediaPlayerEntityFeature.PLAY,
    "media_pause":          MediaPlayerEntityFeature.PAUSE,
    "media_stop":           MediaPlayerEntityFeature.STOP,
}

# Base features always present regardless of ha_service_map content.
_BASE_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a media_player entity for each IR sub-remote of type TV/STB/Projector/Speaker."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities = [
        AionIRMediaPlayer(coordinator, descriptor)
        for descriptor in coordinator.get_entities_for_platform("media_player")
        if descriptor.get("control", {}).get("family") == "ir"
    ]
    # LOGGER.info("[AION][media_player] setup_entry: registering %d entities", len(entities))
    async_add_entities(entities)


class AionIRMediaPlayer(
    CoordinatorEntity[AionHomeDataUpdateCoordinator], MediaPlayerEntity
):
    """
    Represent an IR-controlled media device (TV, STB, Projector, Speaker).

    All state is fully optimistic — IR provides no feedback.
    The entity always reports ON to keep it usable in the dashboard.
    """

    _attr_has_entity_name = True
    # Always report ON — IR has no power state feedback.
    _attr_state = MediaPlayerState.ON
    # is_volume_muted is always None — IR has no mute state feedback.
    _attr_is_volume_muted: bool | None = None

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
        self._remote_type: str = control.get("remote_type") or "IR Remote"
        self._remote_brand: str = control.get("brand") or "AION"
        # Virtual device uid — same pattern used by button.py and remote.py.
        self._virtual_device_uid: str = (
            f"{self._device_uid}::ir_{self._remote_id}"
            if self._remote_id
            else self._device_uid
        )

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """
        Compute feature flags dynamically from the live ha_service_map.

        Only advertises features that have an actual IR command mapped to them,
        so the HA media card doesn't show buttons that would silently no-op.
        If shortcut_commands is non-empty, SELECT_SOURCE is added so the
        streaming apps appear in the source dropdown.
        """
        control = self._descriptor.get("control", {})
        service_map: dict = control.get("ha_service_map", {})
        features = _BASE_FEATURES
        for service, feature in _SERVICE_FEATURE_MAP.items():
            if service in service_map:
                features |= feature
        # Add source selector when streaming shortcut buttons exist.
        if control.get("shortcut_commands"):
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        return features

    @property
    def source_list(self) -> list[str] | None:
        """
        Return streaming app shortcut labels as selectable sources.

        These are the same labels emitted as button entities (Netflix, Shahid,
        Prime Video) but also exposed here so the media card source dropdown works.
        """
        control = self._descriptor.get("control", {})
        shortcuts: dict = control.get("shortcut_commands", {})
        return list(shortcuts.keys()) if shortcuts else None

    @property
    def source(self) -> str | None:
        """Always unknown — IR provides no input-source feedback."""
        return None

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

    def _get_service_command(self, service: str) -> str | None:
        """
        Look up the IR command label for a given HA service name.

        ha_service_map stores {service_name: label_string}.
        Returns None if the service is not mapped for this remote type.
        """
        control = self._descriptor.get("control", {})
        return control.get("ha_service_map", {}).get(service)

    async def _fire(self, service: str) -> None:
        """Fire the IR command mapped to this HA service name, if one exists."""
        command_label = self._get_service_command(service)
        if not command_label:
            return
        await self.coordinator.local_client.async_execute_service_command(
            descriptor=self._descriptor,
            command_type="ir",
            command_payload=command_label,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send Power IR command."""
        await self._fire("turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send Power IR command."""
        await self._fire("turn_off")

    async def async_volume_up(self) -> None:
        """Send Volume Up IR command."""
        await self._fire("volume_up")

    async def async_volume_down(self) -> None:
        """Send Volume Down IR command."""
        await self._fire("volume_down")

    async def async_mute_volume(self, mute: bool) -> None:
        """Send Mute IR command (IR cannot distinguish mute/unmute)."""
        await self._fire("mute_volume")

    async def async_media_next_track(self) -> None:
        """Send Channel Up / Next IR command."""
        await self._fire("media_next_track")

    async def async_media_previous_track(self) -> None:
        """Send Channel Down / Previous IR command."""
        await self._fire("media_previous_track")

    async def async_media_play(self) -> None:
        """Send Play IR command."""
        await self._fire("media_play")

    async def async_media_pause(self) -> None:
        """Send Pause IR command."""
        await self._fire("media_pause")

    async def async_media_stop(self) -> None:
        """Send Stop IR command."""
        await self._fire("media_stop")

    async def async_select_source(self, source: str) -> None:
        """
        Fire the IR command whose label matches the chosen streaming source.

        The source name is identical to the IR command label (e.g. 'Netflix'),
        so it is fired directly without a ha_service_map lookup.
        """
        await self.coordinator.local_client.async_execute_service_command(
            descriptor=self._descriptor,
            command_type="ir",
            command_payload=source,
        )
