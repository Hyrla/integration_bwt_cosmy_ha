from __future__ import annotations

import asyncio
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.switch import SwitchEntity
from homeassistant.components import bluetooth  # HA bluetooth helpers

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

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
        # On ne lève pas ici pour éviter de spammer les logs : l’entité restera indisponible.
        # Home Assistant affichera que la config est incomplète si nécessaire.
        return
    # IMPORTANT: ne pas forcer un update immédiat au boot (évite une erreur si l’appareil est loin)
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
        # Uniq id → basée sur l’adresse
        self._attr_unique_id = f"{DOMAIN}_{address.replace(':','').lower()}"
        # Entité indisponible tant que l’appareil n’est pas accessible
        self._attr_available = False

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name="BWT Cosmy",
            manufacturer="BWT",
            model="Cosmy",
            via_device=None,
        )

    # -------- Connexion BLE robuste --------
    async def _ensure_client(self) -> Optional[BleakClientWithServiceCache]:
        if self._client and self._client.is_connected:
            return self._client

        # 1) Résoudre le BLEDevice via le helper HA (SYNC → pas d'await)
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            # Pas joignable → marquer indisponible, ne pas lever d’exception
            self._attr_available = False
            return None

        # 2) Connexion via bleak-retry-connector (ASYNC)
        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device=ble_device,
                name=self._address,
            )
            self._attr_available = True
            return self._client
        except Exception:
            # Impossible de se connecter maintenant → rester indisponible
            self._attr_available = False
            return None

    # -------- Parsing des notifs status --------
    def _parse_status(self, data: bytes) -> bool | None:
        """
        Notif 20 octets sur 0xFFF4:
        - header: ffa53a1384
        - état:   ON si (data[5] & 0x80) != 0, sinon OFF
        - minutes: uint16 LE data[6:8] si ON; 0 si OFF
        """
        if len(data) == 20 and data[:5] == bytes.fromhex("ffa53a1384"):
            is_on = bool(data[5] & 0x80)
            self._is_on = is_on
            self._minutes = int.from_bytes(data[6:8], "little") if is_on else 0
            return is_on
        return None

    def _on_notify(self, _handle: int, payload: bytearray) -> None:
        self._parse_status(bytes(payload))
        # On a reçu une notif valide → appareil dispo
        self._attr_available = True

    # -------- API Switch --------
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
        # Demander le statut et lire les notifs
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
        """Refresh à la demande de HA — passe en indisponible si hors de portée, sans erreur log."""
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
        except Exception:
            # Perte de connexion pendant l’update
            self._attr_available = False
            try:
                if self._client and self._client.is_connected:
                    await self._client.disconnect()
            except Exception:
                pass

    async def async_will_remove_from_hass(self) -> None:
        """Nettoyage à l’unload."""
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
