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

# Interval between periodic reconnection attempts and status checks
REFRESH_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    address = (entry.unique_id or entry.data.get(CONF_ADDRESS) or "").strip()
    name = entry.data.get(CONF_NAME) or "BWT Cosmy"

    if not address:
        _LOGGER.error("[%s] No BLE address found in config entry; no entity created", DOMAIN)
        return

    ent = BwtCosmySwitch(hass, entry, address, name)
    async_add_entities([ent], update_before_add=False)
    _LOGGER.debug("[%s] Switch entity added for %s (%s)", DOMAIN, name, address)


class BwtCosmySwitch(SwitchEntity):
    """Cosmy cleaning mode switch (start/stop cleaning) with remaining minutes as attribute, auto-reconnects."""

    _attr_icon = "mdi:robot-vacuum"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str, name: str) -> None:
        self.hass = hass
        self.entry = entry
        self._address = address.upper()
        self._client: Optional[BleakClientWithServiceCache] = None
        self._is_on: Optional[bool] = None  # True = cleaning, False = idle
        self._minutes: int = 0

        self._attr_name = f"{name} Cleaning"
        self._attr_unique_id = f"{DOMAIN}_{self._address.replace(':','').lower()}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            connections={(dr.CONNECTION_BLUETOOTH, self._address)},
            name=name,
            manufacturer="BWT",
            model="Cosmy",
        )
        self._attr_available = False

        # Periodic refresh task and lock to prevent concurrent refreshes
        self._unsub_timer = None
        self._refresh_lock = asyncio.Lock()

    # ---------- Entity lifecycle ----------
    async def async_added_to_hass(self) -> None:
        # Initial refresh
        await self._refresh_status(initial=True)
        # Start periodic refresh/reconnection
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

    # ---------- BLE connection ----------
    async def _ensure_client(self) -> Optional[BleakClientWithServiceCache]:
        if self._client and self._client.is_connected:
            return self._client

        # Try connectable first
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            # Some proxies only report non-connectable advertisements
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=False
            )

        if ble_device is None:
            self._attr_available = False
            _LOGGER.debug("[%s] BLEDevice %s not found (out of range or proxy not advertising)", DOMAIN, self._address)
            return None

        try:
            self._client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=ble_device,
                name=self._address,
            )
            # Set disconnect callback to mark unavailable
            try:
                self._client.set_disconnected_callback(
                    lambda _c: self.hass.loop.call_soon_threadsafe(
                        self._on_ble_disconnected
                    )
                )
            except Exception:
                pass  # Ignore if not supported

            self._attr_available = True
            _LOGGER.debug("[%s] GATT connection established -> %s", DOMAIN, self._address)
            return self._client
        except Exception as e:
            self._attr_available = False
            _LOGGER.debug("[%s] GATT connection failed -> %s (%s)", DOMAIN, self._address, e)
            return None

    def _on_ble_disconnected(self) -> None:
        _LOGGER.debug("[%s] BLE GATT disconnected -> %s", DOMAIN, self._address)
        self._client = None
        self._attr_available = False
        self.async_write_ha_state()

    # ---------- Frame helpers ----------
    def _is_ack_frame(self, data: bytes) -> bool:
        """Filter short ACK frames that are not status frames."""
        if len(data) in (3, 4) and data[:2] == b"\x00\x51":
            return True
        if len(data) <= 12 and (data.endswith(b"\x51\x0c") or data.endswith(b"\x51\x0c\xfd")):
            return True
        return False

    # ---------- Status parsing ----------
    def _parse_status(self, data: bytes) -> bool | None:
        # 20 bytes, header ffa53a1384 ; bit 7 of data[5] = cleaning, minutes LE [6:8]
        if len(data) == 20 and data[:5] == bytes.fromhex("ffa53a1384"):
            cleaning = bool(data[5] & 0x80)
            self._is_on = cleaning
            self._minutes = int.from_bytes(data[6:8], "little") if cleaning else 0
            _LOGGER.debug("[%s] Status: %s, minutes=%d", DOMAIN, "CLEANING" if cleaning else "IDLE", self._minutes)
            return cleaning
        _LOGGER.debug("[%s] Unexpected frame: %s", DOMAIN, data.hex())
        return None

    def _on_notify(self, _handle: int, payload: bytearray) -> None:
        b = bytes(payload)
        if self._is_ack_frame(b):
            _LOGGER.debug("[%s] ACK ignored: %s", DOMAIN, b.hex())
            return
        self._parse_status(b)
        self._attr_available = True

    # ---------- Refresh / Reconnect ----------
    async def _refresh_status(self, *, initial: bool) -> None:
        """Attempt (re)connection and query status."""
        if self._refresh_lock.locked():
            _LOGGER.debug("[%s] Refresh already in progress -> skip", DOMAIN)
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
                _LOGGER.debug("[%s] Refresh failed: %s", DOMAIN, e)
                try:
                    if self._client and self._client.is_connected:
                        await self._client.disconnect()
                except Exception:
                    pass
            finally:
                self.async_write_ha_state()

    # ---------- Switch API ----------
    @property
    def is_on(self) -> bool | None:
        """True = cleaning, False = idle."""
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"minutes_remaining": self._minutes}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start cleaning."""
        client = await self._ensure_client()
        if not client:
            self._attr_available = False
            self.async_write_ha_state()
            return

        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        # Optimistic state change
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
        """Stop cleaning."""
        client = await self._ensure_client()
        if not client:
            self._attr_available = False
            self.async_write_ha_state()
            return

        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        # Optimistic state change
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
        """HA manual update."""
        await self._refresh_status(initial=False)
