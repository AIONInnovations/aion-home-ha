"""Config flow for AION Home QR-based pairing through the gateway."""

from __future__ import annotations

from typing import Any
import secrets

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers import instance_id as ha_instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.system_info import async_get_system_info

from .api import AionGatewayApi, AionGatewayAuthError, AionGatewayError, AionGatewayPairingError
from .const import (
    AION_GATEWAY_API_KEY,
    AION_GATEWAY_URL,
    CONF_HA_ACCESS_TOKEN,
    CONF_HA_ID,
    CONF_INSTANCE_NAME,
    CONF_PAIRING_TOKEN,
    DOMAIN,
)
from .qr import build_pairing_payload, render_pairing_qr_markdown


class AionHomeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Guide the user through gateway setup and QR-based mobile pairing."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the temporary pairing state used across the two config steps."""
        self._pairing_token = ""
        self._ha_id = ""
        self._instance_name = ""
        self._machine_type = ""
        self._qr_payload = ""
        self._aion_reauth_entry_id: str | None = None

    async def _async_ensure_pairing_context(self) -> None:
        """Create the pairing payload once so the first HA step can show the QR immediately."""
        if self._pairing_token:
            return

        self._instance_name = self.hass.config.location_name or "Home Assistant"
        self._pairing_token = secrets.token_hex(16)
        # Use the persistent HA instance UUID so ha_id survives reboots and NIC changes.
        self._ha_id = await ha_instance_id.async_get(self.hass)
        try:
            sys_info = await async_get_system_info(self.hass)

            # Attempt 1: Try to get the exact hardware board (HAOS / Supervised)
            machine = sys_info.get("machine")

            if machine:
                self._machine_type = machine
            else:
                # Attempt 2: Fallback for Docker / Core users
                install_type = sys_info.get("installation_type", "Unknown Install")
                arch = sys_info.get("arch", "unknown_arch")

                # Creates a string like: "Home Assistant Container (aarch64)"
                self._machine_type = f"{install_type} ({arch})"
        except Exception:  # noqa: BLE001
            self._machine_type = "unknown_ha_device"
        self._qr_payload = build_pairing_payload(
            gateway_url=AION_GATEWAY_URL,
            pairing_token=self._pairing_token,
            ha_id=self._ha_id,
            instance_name=self._instance_name,
        )

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Skip manual gateway input and immediately show the generated pairing QR."""
        await self._async_ensure_pairing_context()
        return await self.async_step_pair()

    async def async_step_reauth(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Reuse the same QR flow when Home Assistant asks to reauthenticate."""
        self._aion_reauth_entry_id = self.context.get("entry_id")
        self._pairing_token = ""
        self._ha_id = ""
        self._machine_type = ""
        self._qr_payload = ""
        await self._async_ensure_pairing_context()
        return await self.async_step_pair()

    async def async_step_pair(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Render the pairing QR and exchange it for a gateway access token when submitted."""
        await self._async_ensure_pairing_context()
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = AionGatewayApi(
                session=session,
                gateway_url=AION_GATEWAY_URL,
                gateway_api_key=AION_GATEWAY_API_KEY,
            )

            try:
                exchange_payload = await api.async_exchange_pairing(
                    pairing_token=self._pairing_token,
                    ha_id=self._ha_id,
                    instance_name=self._instance_name,
                    machine_type=self._machine_type,
                )
            except AionGatewayPairingError as err:
                if err.code == AionGatewayPairingError.CONSUMED_CODE:
                    # Token was already consumed — force a completely fresh QR.
                    self._pairing_token = ""
                    self._ensure_pairing_context()
                    errors["base"] = "pairing_consumed"
                else:
                    # Token not yet written by the app — let the user retry same QR.
                    errors["base"] = "pairing_not_found"
            except AionGatewayAuthError:
                errors["base"] = "invalid_auth"
            except AionGatewayError:
                errors["base"] = "cannot_connect"
            else:
                # Only extract the access token and connection params — the
                # bootstrap payload is intentionally discarded here. The
                # coordinator will fetch fresh state from /sync on first refresh.
                ha_access_token = exchange_payload[CONF_HA_ACCESS_TOKEN]
                link = exchange_payload.get("link", {})
                user = exchange_payload.get("user", {})
                title = (
                    link.get("label")
                    or self._instance_name
                    or "AION Home"
                )
                await self.async_set_unique_id(
                    f"{user.get('usid', 'unknown')}::{self._ha_id}"
                )
                entry_data = {
                    CONF_INSTANCE_NAME: self._instance_name,
                    CONF_PAIRING_TOKEN: self._pairing_token,
                    CONF_HA_ID: self._ha_id,
                    CONF_HA_ACCESS_TOKEN: ha_access_token,
                }

                if self._aion_reauth_entry_id:
                    entry = self.hass.config_entries.async_get_entry(
                        self._aion_reauth_entry_id
                    )
                    if entry is None:
                        errors["base"] = "cannot_connect"
                    else:
                        self.hass.config_entries.async_update_entry(
                            entry,
                            data=entry_data,
                        )
                        await self.hass.config_entries.async_reload(entry.entry_id)
                        return self.async_abort(reason="reauth_successful")
                else:
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=title,
                        data=entry_data,
                    )

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "qr_markdown": render_pairing_qr_markdown(self._qr_payload),
            },
        )