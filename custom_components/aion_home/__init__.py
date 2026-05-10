"""Set up the AION Home custom integration."""

from __future__ import annotations

from typing import Any
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ATTR_COMMAND_PAYLOAD,
    ATTR_COMMAND_TYPE,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ENTITY_UID,
    DATA_API,
    DATA_COORDINATOR,
    DATA_LOCAL_CLIENT,
    DOMAIN,
    PLATFORMS,
    SERVICE_RESYNC_GATEWAY,
    SERVICE_SEND_AUX_COMMAND,
)
from .coordinator import AionHomeDataUpdateCoordinator
from .local_api import AionLocalClient, AionLocalError

LOGGER = logging.getLogger(__name__)


def _summarize_platforms(entities: list[dict[str, Any]]) -> dict[str, int]:
    """Count normalized entities by platform for setup diagnostics."""
    platform_counts: dict[str, int] = {}
    for entity in entities:
        platform_name = entity.get("platform") or "unknown"
        platform_counts[platform_name] = platform_counts.get(platform_name, 0) + 1
    return platform_counts


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Prepare the integration domain so config entries can be loaded later."""
    hass.data.setdefault(DOMAIN, {})
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create the gateway clients, fetch the bootstrap, and forward the platforms."""
    # LOGGER.info("Starting AION Home setup for entry_id=%s", entry.entry_id)
    session = async_get_clientsession(hass)
    local_client = AionLocalClient(session=session)
    coordinator = AionHomeDataUpdateCoordinator(
        hass=hass,
        entry=entry,
        local_client=local_client,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        LOGGER.exception(
            "AION Home first refresh failed for entry_id=%s",
            entry.entry_id,
        )
        raise

    try:
        await coordinator.async_refresh_local_state()
    except Exception:
        pass

    coordinator.async_start_local_polling()

    entities = coordinator.data.get("entities", []) if coordinator.data else []
    devices = coordinator.data.get("devices", []) if coordinator.data else []
    # LOGGER.info(
    #     "AION Home first refresh succeeded for entry_id=%s devices=%s entities=%s platform_counts=%s",
    #     entry.entry_id,
    #     len(devices),
    #     len(entities),
    #     _summarize_platforms(entities),
    # )

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_API: coordinator.api,
        DATA_COORDINATOR: coordinator,
        DATA_LOCAL_CLIENT: local_client,
    }

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        LOGGER.exception(
            "AION Home platform forwarding failed for entry_id=%s platform_counts=%s",
            entry.entry_id,
            _summarize_platforms(entities),
        )
        raise

    # Sync device areas AFTER platform setup so all devices are registered in the
    # device_registry before async_update_device is called.  Running this during
    # _async_update_data (bootstrap) caused HA to process entity_registry
    # area-change callbacks for every entity simultaneously, producing the
    # "entity_registry logging too frequently — 200 messages" warning.
    coordinator._async_sync_device_areas(devices)

    # LOGGER.info("AION Home platform forwarding completed for entry_id=%s", entry.entry_id)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload all forwarded platforms and release the config entry state."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data:
        entry_data[DATA_COORDINATOR].async_stop_local_polling()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration services once for the whole Home Assistant instance."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_AUX_COMMAND):
        return

    send_aux_schema = vol.Schema(
        {
            vol.Required("entity_id"): cv.entity_id,
            vol.Required(ATTR_COMMAND_TYPE): cv.string,
            vol.Optional(ATTR_COMMAND_PAYLOAD): cv.match_all,
        }
    )
    resync_schema = vol.Schema({vol.Optional("entry_id"): cv.string})

    async def async_send_aux_command_service(call: ServiceCall) -> None:
        """Dispatch the raw auxiliary command service to the shared handler."""
        await _async_handle_send_aux_command(hass, call)

    async def async_resync_gateway_service(call: ServiceCall) -> None:
        """Dispatch the gateway refresh service to the shared handler."""
        await _async_handle_resync_gateway(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_AUX_COMMAND,
        async_send_aux_command_service,
        schema=send_aux_schema,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESYNC_GATEWAY,
        async_resync_gateway_service,
        schema=resync_schema,
    )


async def _async_handle_send_aux_command(
    hass: HomeAssistant,
    call: ServiceCall,
) -> None:
    """Resolve the target entity and route a raw auxiliary command to the local client."""
    entity_id = call.data["entity_id"]
    entity_state = hass.states.get(entity_id)
    if entity_state is None:
        raise HomeAssistantError(f"Entity {entity_id} was not found.")

    config_entry_id = entity_state.attributes.get(ATTR_CONFIG_ENTRY_ID)
    entity_uid = entity_state.attributes.get(ATTR_ENTITY_UID)
    if not config_entry_id or not entity_uid:
        raise HomeAssistantError(
            "The selected entity does not expose AION routing metadata."
        )

    entry_data = hass.data.get(DOMAIN, {}).get(config_entry_id)
    if not entry_data:
        raise HomeAssistantError("The selected AION config entry is not loaded.")

    coordinator: AionHomeDataUpdateCoordinator = entry_data[DATA_COORDINATOR]
    descriptor = coordinator.get_entity(entity_uid)
    if not descriptor:
        raise HomeAssistantError(f"AION entity {entity_uid} could not be resolved.")

    try:
        state_patch = await coordinator.local_client.async_execute_service_command(
            descriptor=descriptor,
            command_type=call.data[ATTR_COMMAND_TYPE],
            command_payload=call.data.get(ATTR_COMMAND_PAYLOAD),
        )
    except AionLocalError as error:
        raise HomeAssistantError(str(error)) from error

    await coordinator.async_apply_entity_patch(entity_uid, state_patch)


async def _async_handle_resync_gateway(
    hass: HomeAssistant,
    call: ServiceCall,
) -> None:
    """Force one or all loaded AION entries to fetch a fresh gateway bootstrap."""
    target_entry_id = call.data.get("entry_id")
    entries = hass.data.get(DOMAIN, {})

    if target_entry_id:
        entry_data = entries.get(target_entry_id)
        if not entry_data:
            raise HomeAssistantError(f"Config entry {target_entry_id} is not loaded.")
        await entry_data[DATA_COORDINATOR].async_request_refresh()
        return

    for entry_data in entries.values():
        await entry_data[DATA_COORDINATOR].async_request_refresh()