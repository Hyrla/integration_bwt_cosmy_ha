from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.switch import SwitchEntity
from homeassistant.components import bluetooth
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from .const import (
    DOMAIN,
    SERVICE_UUID, CHAR_WRITE, CHAR_NOTIFY,
    CMD_ON, CMD_OFF, CMD_STAT,
    CONF_ADDRESS, CONF_NAME,
)

_LOGGER = logging.getLogger(__name__)

# Intervalle de tentative/requête statut (reconnexion incluse)
REFRESH_INTERVAL = timedelta(seconds=30)


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
    """Cosmy Power switch (ON/OFF) + minutes restantes en attribut, avec reconnexion auto."""

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

        # Timer & verrou pour éviter les refresh/reco concurrents
        self._unsub_timer = None
        self._refresh_lock = asyncio.Lock()

    # ---------- Cycle de vie ----------
    async def async_added_to_hass(self) -> None:
        # 1) premier refresh synchrone
        await self._refresh_status(initial=True)
        # 2) timer périodique pour (re)connexion et statut
        self._unsub_timer = async_track_time_interval(
            self.hass, self._scheduled_refresh, REFRESH_INTERVAL
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass

    async def _scheduled_refresh(self, _now) -> None:
        await self._refresh_status(initial=False)

    # ---------- Connexion BLE ----------
    async def _ensure_client(self) -> Optional[BleakClientWithServiceCache]:
        if self._client and self._client.is_connected:
            return self._client

        # Résoudre le BLEDevice (via proxy HA)
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            # certains proxys annoncent en non-connectable
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=False
            )

        if ble_device is None:
            self._attr_available = False
            _LOGGER.debug("[%s] BLEDevice %s introuvable (hors de portée/proxy)", DOMAIN, self._address)
            return None

        try:
            # signature avec arguments nommés (ok sur HA récent)
            self._client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=ble_device,
                name=self._address,
            )
            # Callback de déconnexion pour relancer la dispo
            try:
                self._client.set_disconnected_callback(
                    lambda _c: self.hass.loop.call_soon_threadsafe(
                        self._on_ble_disconnected
                    )
                )
            except Exception:
                # pas bloquant si non supporté
                pass

            self._attr_available = True
            _LOGGER.debug("[%s] Connexion GATT OK -> %s", DOMAIN, self._address)
            return self._client
        except Exception as e:
            self._attr_available = False
            _LOGGER.debug("[%s] Connexion GATT KO -> %s (%s)", DOMAIN, self._address, e)
            return None

    def _on_ble_disconnected(self) -> None:
        _LOGGER.debug("[%s] Déconnexion GATT détectée -> %s", DOMAIN, self._address)
        self._client = None
        self._attr_available = False
        self.async_write_ha_state()
        # le timer périodique s'occupe de retenter

    # ---------- Helpers trames ----------
    def _is_ack_frame(self, data: bytes) -> bool:
        """Filtre les petits ACK non-statut vus dans les logs (ex: 00 51 0c xx)."""
        if len(data) in (3, 4) and data[:2] == b"\x00\x51":
            return True
        if len(data) <= 12 and (data.endswith(b"\x51\x0c") or data.endswith(b"\x51\x0c\xfd")):
            return True
        return False

    # ---------- Parsing statut ----------
    def _parse_status(self, data: bytes) -> bool | None:
        # 20 octets, header ffa53a1384 ; bit 7 de data[5] = ON, minutes LE [6:8]
        if len(data) == 20 and data[:5] == bytes.fromhex("ffa53a1384"):
            is_on = bool(data[5] & 0x80)
            self._is_on = is_on
            self._minutes = int.from_bytes(data[6:8], "little") if is_on else 0
            _LOGGER.debug("[%s] Status: %s, minutes=%d", DOMAIN, "ON" if is_on else "OFF", self._minutes)
            return is_on
        _LOGGER.debug("[%s] Frame inattendue: %s", DOMAIN, data.hex())
        return None

    def _on_notify(self, _handle: int, payload: bytearray) -> None:
        b = bytes(payload)
        if self._is_ack_frame(b):
            _LOGGER.debug("[%s] ACK ignoré: %s", DOMAIN, b.hex())
            return
        self._parse_status(b)
        self._attr_available = True

    # ---------- Rafraîchissement / reconnexion ----------
    async def _refresh_status(self, *, initial: bool) -> None:
        """Tente une (re)connexion et lit le statut. Protégé par un verrou."""
        if self._refresh_lock.locked():
            _LOGGER.debug("[%s] Refresh déjà en cours -> skip", DOMAIN)
            return
        async with self._refresh_lock:
            client = await self._ensure_client()
            if not client:
                self._attr_available = False
                if initial:
                    self.async_write_ha_state()
                return
            try:
                await client.start_notify(CHAR_NOTIFY, self._on_notify)
                await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
                await asyncio.sleep(1.0)
                await client.stop_notify(CHAR_NOTIFY)
                self._attr_available = True
            except Exception as e:
                self._attr_available = False
                _LOGGER.debug("[%s] Refresh KO: %s", DOMAIN, e)
                try:
                    if self._client and self._client.is_connected:
                        await self._client.disconnect()
                except Exception:
                    pass
            finally:
                self.async_write_ha_state()

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

        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        # Optimiste immédiat
        self._is_on = True
        self._attr_available = True
        self.async_write_ha_state()

        await client.write_gatt_char(CHAR_WRITE, CMD_ON, response=True)
        await asyncio.sleep(1.5)
        await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
        await asyncio.sleep(2.0)
        try:
            await client.stop_notify(CHAR_NOTIFY)
        except Exception:
            pass

    async def async_turn_off(self, **kwargs: Any) -> None:
        client = await self._ensure_client()
        if not client:
            self._attr_available = False
            self.async_write_ha_state()
            return

        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        # Optimiste immédiat
        self._is_on = False
        self._attr_available = True
        self.async_write_ha_state()

        await client.write_gatt_char(CHAR_WRITE, CMD_OFF, response=True)
        await asyncio.sleep(0.8)
        await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
        await asyncio.sleep(1.5)
        try:
            await client.stop_notify(CHAR_NOTIFY)
        except Exception:
            pass

    async def async_update(self) -> None:
        # appelé par HA à la demande → on réutilise le refresh protégé
        await self._refresh_status(initial=False)
