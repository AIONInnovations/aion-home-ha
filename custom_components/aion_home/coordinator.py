"""Coordinator used to fetch and mutate the gateway bootstrap snapshot."""

from __future__ import annotations

from typing import Any
import asyncio
import copy
import logging
import random
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from .api import AionGatewayApi, AionGatewayAuthError, AionGatewayError
from .const import (
    AION_GATEWAY_API_KEY,
    AION_GATEWAY_URL,
    COORDINATOR_INTERVAL,
    CONF_HA_ACCESS_TOKEN,
    DOMAIN,
    LOCAL_POLL_INTERVAL,
)
from .local_api import AionLocalClient, AionLocalError

LOGGER = logging.getLogger(__name__)

# Exponential backoff constants for transient gateway failures.
# Backoff formula: min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * 2^(n-1)) + jitter
BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 60


def _summarize_entities(entities: list[dict[str, Any]]) -> dict[str, int]:
    """Count normalized entities by platform for concise setup diagnostics."""
    platform_counts: dict[str, int] = {}
    for entity in entities:
        platform_name = entity.get("platform") or "unknown"
        platform_counts[platform_name] = platform_counts.get(platform_name, 0) + 1
    return platform_counts


class AionHomeDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keep a cached copy of the gateway bootstrap and expose indexed lookups."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        local_client: AionLocalClient,
    ) -> None:
        """Store the API clients used during periodic refresh and local writes."""
        super().__init__(
            hass,
            logger=LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=COORDINATOR_INTERVAL,
        )
        self.config_entry = entry
        self.api = AionGatewayApi(
            session=async_get_clientsession(hass),
            gateway_url=AION_GATEWAY_URL,
            gateway_api_key=AION_GATEWAY_API_KEY,
            ha_access_token=entry.data.get(CONF_HA_ACCESS_TOKEN),
        )
        self.local_client = local_client
        self._local_poll_task = None
        self._local_poll_unsub = None
        # Tracks consecutive cloud bootstrap failures for exponential backoff.
        self._failure_count = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest bootstrap document and index it for entity lookups."""
        # LOGGER.info(
        #     "Requesting AION gateway bootstrap for entry_id=%s",
        #     self.config_entry.entry_id,
        # )
        try:
            bootstrap = await self.api.async_fetch_bootstrap()
        except AionGatewayAuthError as error:
            # Auth failures are permanent — let HA surface a reauth prompt.
            # Do not apply backoff; the coordinator will stop polling on its own.
            LOGGER.error(
                "AION gateway bootstrap auth failed for entry_id=%s error=%s",
                self.config_entry.entry_id,
                error,
            )
            raise ConfigEntryAuthFailed(str(error)) from error
        except AionGatewayError as error:
            # Transient failure — apply exponential backoff to respect the 20 RPM limit.
            self._failure_count += 1
            exponential_wait = min(
                MAX_BACKOFF_SECONDS,
                BASE_BACKOFF_SECONDS * (2 ** (self._failure_count - 1)),
            )
            jitter = random.uniform(0, 1)
            total_wait = exponential_wait + jitter
            self.update_interval = timedelta(seconds=total_wait)
            raise UpdateFailed(str(error)) from error

        # Successful fetch — restore normal 24-hour interval if we were in backoff.
        if self._failure_count > 0:
            self._failure_count = 0
            self.update_interval = COORDINATOR_INTERVAL

        devices = bootstrap.get("devices", [])
        entities = bootstrap.get("entities", [])
        if not isinstance(devices, list) or not isinstance(entities, list):
            LOGGER.error(
                "AION gateway bootstrap shape is invalid for entry_id=%s devices_type=%s entities_type=%s keys=%s",
                self.config_entry.entry_id,
                type(devices).__name__,
                type(entities).__name__,
                list(bootstrap.keys()),
            )
            raise UpdateFailed("invalid_bootstrap_shape")

        # for _dev in devices:
        #     LOGGER.debug(
        #         "[AION][alias] device received: uid=%s name=%s room_name=%s room_key=%s",
        #         _dev.get("device_uid"),
        #         _dev.get("name"),
        #         _dev.get("room_name"),
        #         _dev.get("room_key"),
        #     )
        # LOGGER.info(
        #     "AION gateway bootstrap received for entry_id=%s devices=%s entities=%s platform_counts=%s",
        #     self.config_entry.entry_id,
        #     len(devices),
        #     len(entities),
        #     _summarize_entities(entities),
        # )

        try:
            indexed = self._index_bootstrap(bootstrap)
        except Exception:
            LOGGER.exception(
                "AION gateway bootstrap indexing failed for entry_id=%s devices=%s entities=%s",
                self.config_entry.entry_id,
                len(devices),
                len(entities),
            )
            raise

        # Area sync is intentionally NOT called here.
        # Calling async_update_device in a tight loop before entity platform setup
        # completes causes HA's entity_registry to process area-change callbacks for
        # every entity in the registry, generating a burst of 200+ log messages and
        # triggering the util.logging rate-limit warning.
        # Area sync is called from async_setup_entry AFTER async_forward_entry_setups,
        # when all entities/devices are registered and the registry is stable.
        return indexed

    def _async_sync_device_areas(self, devices: list[dict]) -> None:
        """
        Update each device's area in HA's device registry to match the room alias.
        Creates the area if it doesn't exist yet. Skips devices with no room name.
        """
        area_reg = ar.async_get(self.hass)
        device_reg = dr.async_get(self.hass)
        for dev in devices:
            room_name: str = dev.get("room_name") or ""
            device_uid: str = dev.get("device_uid") or ""
            if not room_name or not device_uid:
                # LOGGER.info(
                #     "[AION][alias] skipping area sync: uid=%s room_name=%r",
                #     device_uid,
                #     room_name,
                # )
                continue
            # Find or create the area by human-readable name.
            area_entry = area_reg.async_get_area_by_name(room_name)
            if area_entry is None:
                area_entry = area_reg.async_create(room_name)
                # LOGGER.info("[AION][alias] created area: %s", room_name)
            # Locate the device in the registry by its AION identifier.
            device_entry = device_reg.async_get_device(identifiers={(DOMAIN, device_uid)})
            if device_entry is None:
                # LOGGER.info(
                #     "[AION][alias] device not yet in registry, area will be set via suggested_area: uid=%s room=%s",
                #     device_uid,
                #     room_name,
                # )
                continue
            if device_entry.area_id != area_entry.id:
                device_reg.async_update_device(device_entry.id, area_id=area_entry.id)
                # LOGGER.info(
                #     "[AION][alias] assigned device=%s to area=%s (id=%s)",
                #     device_uid,
                #     room_name,
                #     area_entry.id,
                # )
            else:
                pass  # LOGGER.debug("[AION][alias] device=%s already in area=%s, no change", device_uid, room_name)

    def async_start_local_polling(self) -> None:
        """Start the local poll scheduler used for eligible stateful AION devices."""
        if self._local_poll_unsub is not None:
            return

        self._local_poll_unsub = async_track_time_interval(
            self.hass,
            self._async_schedule_local_poll,
            LOCAL_POLL_INTERVAL,
        )

    def async_stop_local_polling(self) -> None:
        """Stop the local poll scheduler and cancel any running poll task."""
        if self._local_poll_unsub is not None:
            self._local_poll_unsub()
            self._local_poll_unsub = None

        if self._local_poll_task is not None and not self._local_poll_task.done():
            self._local_poll_task.cancel()
            self._local_poll_task = None

    @callback
    def _async_schedule_local_poll(self, now: datetime) -> None:
        """Schedule a local poll task while avoiding overlapping polls."""
        if self._local_poll_task is not None and not self._local_poll_task.done():
            return

        self._local_poll_task = self.hass.async_create_task(self._async_update_local_state())

    async def async_refresh_local_state(self) -> None:
        """Fetch current local state once and apply it to the cached descriptor map."""
        await self._async_update_local_state()

    async def _async_update_local_state(self) -> None:
        """Fetch and apply local state for all eligible stateful entities.

        Collects one representative descriptor per physical device, polls them
        concurrently, then applies ALL results in a single async_set_updated_data
        call to avoid flooding the entity_registry log.
        """
        if not self.data:
            return

        entities = self.data.get("entities", [])
        device_roots: dict[str, dict[str, Any]] = {}

        # Pass 1: primary stateful entities (switch/light/cover/lock).
        # These are the preferred polling representative because they also carry
        # state data that can be patched back into the coordinator cache.
        for entity in entities:
            if entity.get("platform") not in {"switch", "light", "cover", "lock"}:
                continue
            if entity.get("control", {}).get("family") != "primary":
                continue
            local = entity.get("local", {})
            if not (
                local.get("device_ip")
                and local.get("device_ssid")
                and local.get("main_key")
            ):
                continue
            device_uid = entity.get("device", {}).get("device_uid")
            if not device_uid:
                continue
            device_roots.setdefault(device_uid, entity)

        # Pass 2: IR-only devices that have no primary switch/light/cover/lock entity.
        # Their local connection info is still present on every IR sub-remote entity,
        # so we can poll the hub via any one of them.
        for entity in entities:
            if entity.get("control", {}).get("family") != "ir":
                continue
            local = entity.get("local", {})
            if not (
                local.get("device_ip")
                and local.get("device_ssid")
                and local.get("main_key")
            ):
                continue
            device_uid = entity.get("device", {}).get("device_uid")
            if not device_uid:
                continue
            # setdefault: won't override a primary-family entry already present.
            device_roots.setdefault(device_uid, entity)

        if not device_roots:
            return

        semaphore = asyncio.Semaphore(3)
        tasks = [
            self._async_poll_device(root_descriptor, semaphore)
            for root_descriptor in device_roots.values()
        ]
        # Each task returns (device_uid, local_state | None); None means poll failed.
        poll_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Apply every device's result in ONE deep-copy + one async_set_updated_data
        # call so the entity_registry is not flooded with per-device notifications.
        updated_data = copy.deepcopy(self.data)
        data_changed = False

        for result in poll_results:
            if isinstance(result, Exception):
                continue
            if result is None:
                continue
            device_uid, local_state = result
            if local_state is None:
                # Device did not respond — mark all its entities unavailable.
                if self._patch_device_availability(updated_data, device_uid, available=False):
                    data_changed = True
            else:
                # Device responded — mark available and apply state patches.
                if self._patch_local_state_snapshot(updated_data, device_uid, local_state):
                    data_changed = True

        if data_changed:
            self.async_set_updated_data(updated_data)

    async def _async_poll_device(
        self,
        descriptor: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> tuple[str, Any] | None:
        """Fetch one device's local state snapshot.

        Returns (device_uid, local_state) on success or (device_uid, None) when
        the device is unreachable.  Returns None only when device_uid is empty.
        """
        device_uid = descriptor.get("device", {}).get("device_uid") or ""
        if not device_uid:
            return None

        async with semaphore:
            try:
                local_state = await self.local_client.async_fetch_local_state(descriptor)
            except AionLocalError:
                return (device_uid, None)

        return (device_uid, local_state)

    def _patch_local_state_snapshot(
        self,
        updated_data: dict[str, Any],
        device_uid: str,
        local_state: Any,
    ) -> bool:
        """Apply a local state snapshot into updated_data for all entities of a device.

        Marks every entity of the device as locally available and applies state
        patches for primary-family entities.  Returns True when any value changed.
        """
        entity_index = updated_data.get("entity_index", {})
        device_category = ""
        changed = False

        # Resolve device category from the first matching entity.
        for entity in updated_data.get("entities", []):
            if entity.get("device", {}).get("device_uid") == device_uid:
                device_category = entity.get("device", {}).get("category", "")
                break

        for entity in updated_data.get("entities", []):
            if entity.get("device", {}).get("device_uid") != device_uid:
                continue

            entity_uid = entity.get("entity_uid")
            if not entity_uid:
                continue

            target_entity = entity_index.get(entity_uid)
            if not target_entity:
                continue

            # Successful poll → device is reachable.
            if not target_entity.get("local_available", True):
                target_entity["local_available"] = True
                changed = True

            # State patches apply only to primary-family entities.
            if entity.get("control", {}).get("family") != "primary":
                continue

            patch = self._build_local_state_patch(entity, local_state, device_category)
            if not patch:
                continue

            target_state = target_entity.setdefault("state", {})
            if any(target_state.get(k) != v for k, v in patch.items()):
                target_state.update(patch)
                changed = True

        return changed

    def _patch_device_availability(
        self,
        updated_data: dict[str, Any],
        device_uid: str,
        available: bool,
    ) -> bool:
        """Set local_available on every entity belonging to a physical device.

        Modifies updated_data in-place.  Returns True when any value changed.
        """
        entity_index = updated_data.get("entity_index", {})
        changed = False

        for entity in updated_data.get("entities", []):
            if entity.get("device", {}).get("device_uid") != device_uid:
                continue
            entity_uid = entity.get("entity_uid")
            if not entity_uid:
                continue
            target_entity = entity_index.get(entity_uid)
            if target_entity is None:
                continue
            if target_entity.get("local_available") == available:
                continue
            target_entity["local_available"] = available
            changed = True

        return changed

    def _build_local_state_patch(
        self,
        entity: dict[str, Any],
        local_state: Any,
        device_category: str,
    ) -> dict[str, Any] | None:
        """Convert the raw local state snapshot into a Home Assistant state patch."""
        platform = entity.get("platform")
        control = entity.get("control", {})
        current_state = entity.get("state", {})

        if device_category == "Multi-Gang" and isinstance(local_state, dict):
            gang_id = control.get("gang_id")
            if gang_id in local_state:
                value = self._normalize_local_numeric_state(local_state[gang_id])
                if value is None:
                    return None
                return {"is_on": value > 0}
            return None

        if platform == "switch":
            value = self._normalize_local_numeric_state(local_state)
            if value is None:
                return None
            return {"is_on": value > 0}

        if platform == "light":
            value = self._normalize_local_numeric_state(local_state)
            if value is None:
                return None
            patch = {"is_on": value > 0}
            if "brightness_percent" in current_state:
                patch["brightness_percent"] = max(0, min(100, value))
            return patch

        if platform == "cover":
            value = self._normalize_local_numeric_state(local_state)
            if value is None:
                return None
            position = max(0, min(100, value))
            return {"position": position, "is_closed": position == 0}

        if platform == "lock":
            value = self._normalize_local_numeric_state(local_state)
            if value is None:
                return None
            return {"is_locked": value == 0}

        return None

    def _normalize_local_numeric_state(self, value: Any) -> int | None:
        """Interpret device-local state values as an integer if possible."""
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if isinstance(value, str):
            try:
                return int(float(value.strip()))
            except (TypeError, ValueError):
                return None
        return None

    def get_entity(self, entity_uid: str) -> dict[str, Any] | None:
        """Return the indexed descriptor for a single normalized entity uid."""
        if not self.data:
            return None
        return self.data.get("entity_index", {}).get(entity_uid)

    def get_entities_for_platform(self, platform_name: str) -> list[dict[str, Any]]:
        """Return only the normalized entities that belong to the requested platform."""
        if not self.data:
            return []
        return [
            entity
            for entity in self.data.get("entities", [])
            if entity.get("platform") == platform_name
        ]

    async def async_apply_entity_patch(
        self,
        entity_uid: str,
        state_patch: dict[str, Any] | None,
    ) -> None:
        """Update a single entity descriptor optimistically after a local write succeeds."""
        if not state_patch or not self.data:
            return

        updated_data = copy.deepcopy(self.data)
        entity_index = updated_data.get("entity_index", {})
        target_entity = entity_index.get(entity_uid)
        if not target_entity:
            return

        target_state = target_entity.setdefault("state", {})
        target_state.update(state_patch)
        self.async_set_updated_data(updated_data)

    def _index_bootstrap(self, bootstrap: dict[str, Any]) -> dict[str, Any]:
        """Create an entity index map so platform setup and services can resolve descriptors fast."""
        indexed_bootstrap = copy.deepcopy(bootstrap)
        entity_index: dict[str, dict[str, Any]] = {}
        for entity in indexed_bootstrap.get("entities", []):
            entity_uid = entity.get("entity_uid")
            if not entity_uid:
                continue
            # Warn on duplicate entity_uid — this would cause HA entity_registry
            # collisions and is the most common source of the 200-message flood.
            if entity_uid in entity_index:
                LOGGER.warning(
                    "[AION] Duplicate entity_uid detected: %s — second descriptor discarded. "
                    "Check backend normalization for platform=%s name=%s",
                    entity_uid,
                    entity.get("platform"),
                    entity.get("name"),
                )
                continue
            entity_index[entity_uid] = entity
        indexed_bootstrap["entity_index"] = entity_index
        return indexed_bootstrap