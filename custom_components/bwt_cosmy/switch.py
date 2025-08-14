from __future__ import annotations

import asyncio
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.switch import SwitchEntity
from homeassistant.components import bluetooth  # HA bluetooth helpers

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

import logging
_LOGGER = logging.getLogger("custom_components.bwt_cosmy")
_LOGGER.info("[bwt_cosmy] Le module switch.py a été importé et chargé.")

DOMAIN = "bwt_cosmy"

# GATT
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_WRITE   = "0000fff3-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY  = "0000fff4-0000-1000-8000-00805f9b34fb"

# Commands (connues et testées)
CMD_ON   = bytes.fromhex("ffa50a020101b2")
CMD_OFF  = bytes.fromhex("ffa50a020100b1")
CMD_STAT = bytes.fromhex("ffa50a020406ba")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Enregistre l’entité de commutateur Cosmy."""
    address = (entry.unique_id or entry.data.get("address") or "").strip()
    if not address:
        _LOGGER.error("Aucune adresse BLE trouvée dans l'entrée de config, entité non créée.")
        return
    _LOGGER.info(f"Ajout de l'entité Cosmy pour l'adresse {address}")
    async_add_entities([BwtCosmySwitch(hass, entry, address)], update_before_add=False)


class BwtCosmySwitch(SwitchEntity):
    """Switch ON/OFF du robot Cosmy + statut via notif."""

    _attr_icon = "mdi:robot-vacuum"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        self.hass = hass
        self.entry = entry
        self._address = address
        self._client: Optional[BleakClientWithServiceCache] = None
        self._is_on: Optional[bool] = None
        self._minutes: int = 0
        self._attr_name = "Cosmy Power"
        self._attr_unique_id = f"{DOMAIN}_{address.replace(':','').lower()}"
        self._attr_available = False

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name="BWT Cosmy",
            manufacturer="BWT",
            model="Cosmy",
        )

    async def _ensure_client(self) -> Optional[BleakClientWithServiceCache]:
        if self._client and self._client.is_connected:
            _LOGGER.info(f"Client BLE déjà connecté pour {self._address}")
            return self._client

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            _LOGGER.info(f"BLEDevice {self._address} introuvable ou hors de portée.")
            self._attr_available = False
            return None

        try:
            _LOGGER.info(f"Tentative de connexion BLE à {self._address}")
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device=ble_device,
                name=self._address,
            )
            self._attr_available = True
            _LOGGER.info(f"Connexion BLE réussie à {self._address}")
            return self._client
        except Exception as e:
            _LOGGER.info(f"Impossible de se connecter à {self._address}: {e}")
            self._attr_available = False
            return None

    def _parse_status(self, data: bytes) -> bool | None:
        if len(data) == 20 and data[:5] == bytes.fromhex("ffa53a1384"):
            is_on = bool(data[5] & 0x80)
            self._is_on = is_on
            self._minutes = int.from_bytes(data[6:8], "little") if is_on else 0
            _LOGGER.info(f"Notif Cosmy: état={'ON' if is_on else 'OFF'}, minutes={self._minutes}")
            return is_on
        _LOGGER.info(f"Trame status inattendue: {data.hex()}")
        return None

    def _on_notify(self, _handle: int, payload: bytearray) -> None:
        self._parse_status(bytes(payload))
        self._attr_available = True
        _LOGGER.info(f"Notification reçue sur {self._address}, appareil marqué disponible.")

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
            _LOGGER.info(f"Impossible d'allumer Cosmy {self._address}: pas de client BLE.")
            self.async_write_ha_state()
            return
        _LOGGER.info(f"Envoi commande ON à Cosmy {self._address}")
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
            _LOGGER.info(f"Impossible d'éteindre Cosmy {self._address}: pas de client BLE.")
            self.async_write_ha_state()
            return
        _LOGGER.info(f"Envoi commande OFF à Cosmy {self._address}")
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
            _LOGGER.info(f"Cosmy {self._address} indisponible pour update.")
            return
        try:
            _LOGGER.info(f"Update: interrogation statut Cosmy {self._address}")
            await client.start_notify(CHAR_NOTIFY, self._on_notify)
            await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
            await asyncio.sleep(1.0)
            await client.stop_notify(CHAR_NOTIFY)
            self._attr_available = True
        except Exception as e:
            self._attr_available = False
            _LOGGER.info(f"Erreur update BLE Cosmy {self._address}: {e}")
            try:
                if self._client and self._client.is_connected:
                    await self._client.disconnect()
            except Exception:
                pass

    async def async_will_remove_from_hass(self) -> None:
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
                _LOGGER.info(f"Déconnexion BLE propre de Cosmy {self._address}")
            except Exception as e:
                _LOGGER.info(f"Erreur lors de la déconnexion BLE Cosmy {self._address}: {e}")
