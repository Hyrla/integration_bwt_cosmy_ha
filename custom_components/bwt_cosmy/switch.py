from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.switch import SwitchEntity
from homeassistant.components import bluetooth
from homeassistant.helpers import device_registry as dr

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from .const import (
    DOMAIN,
    SERVICE_UUID, CHAR_WRITE, CHAR_NOTIFY,
    CMD_ON, CMD_OFF, CMD_STAT,
    CONF_ADDRESS, CONF_NAME,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    address = (entry.unique_id or entry.data.get(CONF_ADDRESS) or "").strip()
    name = entry.data.get(CONF_NAME) or "BWT Cosmy"

    if not address:
        _LOGGER.error("[%s] Pas d'adresse BLE dans l'entrée; aucune entité créée", DOMAIN)
        return

    ent = BwtCosmySwitch(hass, entry, address, name)
    async_add_entities([ent], update_before_add=False)
    _LOGGER.debug("[%s] Entité switch ajoutée pour %s (%s)", DOMAIN, name, address)


class BwtCosmySwitch(SwitchEntity):
    """Cosmy Power switch (ON/OFF) + minutes restantes en attribut."""

    _attr_icon = "mdi:robot-vacuum"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str, name: str) -> None:
        self.hass = hass
        self.entry = entry
        self._address = address.upper()
        self._client: Optional[BleakClientWithServiceCache] = None
        self._is_on: Optional[bool] = None
        self._minutes: int = 0

        self._attr_name = f"{name} Power"
        self._attr_unique_id = f"{DOMAIN}_{self._address.replace(':','').lower()}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            connections={(dr.CONNECTION_BLUETOOTH, self._address)},
            name=name,
            manufacturer="BWT",
            model="Cosmy",
        )
        self._attr_available = False

    # ---------- Initialisation : faire un vrai refresh synchrone ----------
    async def async_added_to_hass(self) -> None:
        await self._initial_refresh()

    async def _initial_refresh(self) -> None:
        _LOGGER.debug("[%s] Initial refresh pour %s", DOMAIN, self._address)
        client = await self._ensure_client()
        if not client:
            self._attr_available = False
            self.async_write_ha_state()
            _LOGGER.debug("[%s] Initial refresh: device hors de portée", DOMAIN)
            return
        try:
            await client.start_notify(CHAR_NOTIFY, self._on_notify)
            await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
            await asyncio.sleep(1.0)
            await client.stop_notify(CHAR_NOTIFY)
            self._attr_available = True
            _LOGGER.debug("[%s] Initial refresh OK (connecté)", DOMAIN)
        except Exception as e:
            self._attr_available = False
            _LOGGER.debug("[%s] Initial refresh KO: %s", DOMAIN, e)
        finally:
            self.async_write_ha_state()

    # ---------- Connexion BLE ----------
    async def _ensure_client(self) -> Optional[BleakClientWithServiceCache]:
        if self._client and self._client.is_connected:
            return self._client

        # 1) Essai en connectable=True
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            _LOGGER.debug("[%s] Pas de BLEDevice connectable pour %s; 2e essai connectable=False",
                          DOMAIN, self._address)
            # 2) Certains proxys remontent l'annonce non-connectable
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=False
            )

        if ble_device is None:
            self._attr_available = False
            _LOGGER.debug("[%s] BLEDevice %s introuvable (même non-connectable)", DOMAIN, self._address)
            return None

        _LOGGER.debug("[%s] BLEDevice résolu: %s (connectable=%s)",
                      DOMAIN, ble_device, getattr(ble_device, "details", None))

        try:
            self._client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=ble_device,
                name=self._address,
            )
            self._attr_available = True
            _LOGGER.debug("[%s] Connexion GATT OK -> %s", DOMAIN, self._address)
            return self._client
        except Exception as e:
            self._attr_available = False
            _LOGGER.debug("[%s] Connexion GATT KO -> %s (%s)", DOMAIN, self._address, e)
            return None

    # ---------- Parsing statut ----------
    def _parse_status(self, data: bytes) -> bool | None:
        # 20 octets, header ffa53a1384 ; bit 7 de data[5] = ON
        if len(data) == 20 and data[:5] == bytes.fromhex("ffa53a1384"):
            is_on = bool(data[5] & 0x80)
            self._is_on = is_on
            self._minutes = int.from_bytes(data[6:8], "little") if is_on else 0
            _LOGGER.debug("[%s] Status: %s, minutes=%d", DOMAIN, "ON" if is_on else "OFF", self._minutes)
            return is_on
        _LOGGER.debug("[%s] Frame inattendue: %s", DOMAIN, data.hex())
        return None

    def _on_notify(self, _handle: int, payload: bytearray) -> None:
        self._parse_status(bytes(payload))
        self._attr_available = True

    # ---------- API Switch ----------
    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"minutes_remaining": self._minutes}

    async def async_turn_on(self, **kwargs: Any) -> None:
        client = await self._ensure_client()
        if not client:
            self._attr_available = False
            self.async_write_ha_state()
            return
        await client.write_gatt_char(CHAR_WRITE, CMD_ON, response=True)
        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
        await asyncio.sleep(1.0)
        await client.stop_notify(CHAR_NOTIFY)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        client = await self._ensure_client()
        if not client:
            self._attr_available = False
            self.async_write_ha_state()
            return
        await client.write_gatt_char(CHAR_WRITE, CMD_OFF, response=True)
        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
        await asyncio.sleep(1.0)
        await client.stop_notify(CHAR_NOTIFY)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        client = await self._ensure_client()
        if not client:
            self._attr_available = False
            return
        try:
            await client.start_notify(CHAR_NOTIFY, self._on_notify)
            await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
            await asyncio.sleep(1.0)
            await client.stop_notify(CHAR_NOTIFY)
            self._attr_available = True
        except Exception as e:
            self._attr_available = False
            _LOGGER.debug("[%s] Update BLE KO: %s", DOMAIN, e)
            try:
                if self._client and self._client.is_connected:
                    await self._client.disconnect()
            except Exception:
                pass

    async def async_will_remove_from_hass(self) -> None:
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
