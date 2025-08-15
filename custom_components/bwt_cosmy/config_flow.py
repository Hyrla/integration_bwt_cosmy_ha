from __future__ import annotations

from typing import Any, Optional
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_address_present,
)
from homeassistant.components import bluetooth  # pour la vérif facultative en user-step

from .const import DOMAIN, CONF_ADDRESS as C_ADDR, CONF_NAME as C_NAME  # garde compat local si tu utilises const.py


def _normalize_addr(addr: str) -> str:
    return (addr or "").strip().upper()


async def _already_configured(hass: HomeAssistant, address: str) -> bool:
    """Vérifie si l'adresse BLE est déjà utilisée par une entrée existante."""
    norm = _normalize_addr(address)
    for entry in hass.config_entries.async_entries(DOMAIN):
        uid = (entry.unique_id or entry.data.get(CONF_ADDRESS) or "").upper()
        if uid == norm:
            return True
    return False


class BwtCosmyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._disc_addr: Optional[str] = None
        self._disc_name: Optional[str] = None

    # ---------- Ajout manuel (ton code conservé) ----------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            address = _normalize_addr(user_input.get(CONF_ADDRESS, ""))
            name = (user_input.get(CONF_NAME) or "BWT Cosmy").strip() or "BWT Cosmy"

            if not address or len(address) < 11:
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                # Déduplication
                if await _already_configured(self.hass, address):
                    return self.async_abort(reason="already_configured")

                # Vérif facultative : device vu par la stack BT (non bloquant)
                _ = bluetooth.async_ble_device_from_address(self.hass, address, connectable=True)

                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data={CONF_ADDRESS: address, CONF_NAME: name})

        # Préremplir si on vient d'une découverte
        defaults = {}
        if self._disc_addr:
            defaults[CONF_ADDRESS] = self._disc_addr
            defaults[CONF_NAME] = (self._disc_name or "BWT Cosmy")

        schema = vol.Schema({
            vol.Required(CONF_ADDRESS, default=defaults.get(CONF_ADDRESS, "")): str,
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, "BWT Cosmy")): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # ---------- Découverte Bluetooth (auto-suggest) ----------
    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        """
        Appelé automatiquement quand un advert BLE matche les 'bluetooth' matchers de manifest.json :
          - local_name: "RoboCleaner*"
          - service_uuid: "0000fff0-0000-1000-8000-00805f9b34fb"
        """
        address = _normalize_addr(discovery_info.address)
        name = (discovery_info.name or "BWT Cosmy").strip() or "BWT Cosmy"

        # Déduplication : si déjà configuré, on ignore
        if await _already_configured(self.hass, address):
            return self.async_abort(reason="already_configured")

        # Si pour une raison X l'adresse n'est pas vue par HA, on ignore
        if not async_address_present(self.hass, address):
            return self.async_abort(reason="not_supported")

        # On fixe unique_id = adresse BLE pour cette entrée
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        # On stocke pour préremplir, puis on demande confirmation
        self._disc_addr = address
        self._disc_name = name
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Étape de confirmation affichée après une découverte."""
        if user_input is not None:
            # Crée l'entrée avec l'adresse/nom découverts
            address = _normalize_addr(self._disc_addr or "")
            name = (self._disc_name or "BWT Cosmy").strip() or "BWT Cosmy"

            # Re-check déduplication juste avant création
            if await _already_configured(self.hass, address):
                return self.async_abort(reason="already_configured")

            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=name, data={CONF_ADDRESS: address, CONF_NAME: name})

        # Affiche une petite confirmation (textes dans strings.json/translations)
        return self.async_show_form(step_id="confirm")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Options flow (placeholder)."""
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        # Pas d’options pour l’instant
        return self.async_create_entry(title="", data=self.entry.options or {})
