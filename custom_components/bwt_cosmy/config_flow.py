from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.components import bluetooth
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_ADDRESS, CONF_NAME

def _normalize_addr(addr: str) -> str:
    return addr.strip().upper()

class BwtCosmyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            address = _normalize_addr(user_input.get(CONF_ADDRESS, ""))
            name = (user_input.get(CONF_NAME) or "BWT Cosmy").strip() or "BWT Cosmy"

            if not address or len(address) < 11:
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                # Vérif: adresse vue par la stack BT (proxy inclus) — pas bloquant si absente
                ble_dev = bluetooth.async_ble_device_from_address(self.hass, address, connectable=True)
                # On accepte quand même même si pas vu; on unique_id = adresse
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data={CONF_ADDRESS: address, CONF_NAME: name})

        schema = vol.Schema({
            vol.Required(CONF_ADDRESS): str,
            vol.Optional(CONF_NAME, default="BWT Cosmy"): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
