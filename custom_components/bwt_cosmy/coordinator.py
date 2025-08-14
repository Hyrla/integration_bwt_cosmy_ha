from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.components import bluetooth
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.dispatcher import async_dispatcher_send, async_dispatcher_connect
from homeassistant.helpers import device_registry as dr  # only for typing hints if needed

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from .const import (
    SERVICE_UUID, CHAR_WRITE, CHAR_NOTIFY,
    CMD_ON, CMD_OFF, CMD_STAT,
    SIGNAL_STATE_FMT, SIGNAL_MINUTES_FMT, SIGNAL_REFRESH_FMT,
)

_LOGGER = logging.getLogger(__name__)

REFRESH_INTERVAL = timedelta(seconds=30)  # periodic (re)connect + status
NOTIFY_WAIT = 1.0

class CosmyCoordinator:
    """Centralizes BLE connection, reconnection and status parsing for Cosmy."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        self.hass = hass
        self.address = address.upper()
        self.name = name

        self._client: Optional[BleakClientWithServiceCache] = None
        self.cleaning: Optional[bool] = None
        self.minutes: int = 0
        self.available: bool = False

        self._lock = asyncio.Lock()
        self._unsub_timer = None

        # signals for this device
        key = self.address.replace(":", "").lower()
        self.sig_state = SIGNAL_STATE_FMT.format(addr=key)
        self.sig_minutes = SIGNAL_MINUTES_FMT.format(addr=key)
        self.sig_refresh = SIGNAL_REFRESH_FMT.format(addr=key)
        self._unsub_refresh = None

    async def async_start(self) -> None:
        """Start periodic refresh and subscribe to on-demand refresh."""
        # on-demand refresh from sensor
        self._unsub_refresh = async_dispatcher_connect(
            self.hass, self.sig_refresh, self._on_refresh_request
        )
        # periodic refresh
        self._unsub_timer = async_track_time_interval(
            self.hass, self._scheduled_refresh, REFRESH_INTERVAL
        )
        # initial refresh now
        await self.async_refresh()

    async def async_stop(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self.available = False

    async def _scheduled_refresh(self, _now) -> None:
        await self.async_refresh()

    def _on_refresh_request(self) -> None:
        # Run from dispatcher (sensor asks for a refresh)
        self.hass.async_create_task(self.async_refresh())

    # ---------- BLE helpers ----------
    async def _ensure_client(self) -> Optional[BleakClientWithServiceCache]:
        if self._client and self._client.is_connected:
            return self._client

        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=False)

        if ble_device is None:
            self.available = False
            _LOGGER.debug("[bwt_cosmy] BLEDevice %s not found (out of range/proxy)", self.address)
            return None

        try:
            self._client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=ble_device,
                name=self.address,
            )
            try:
                self._client.set_disconnected_callback(
                    lambda _c: self.hass.loop.call_soon_threadsafe(self._on_disconnect)
                )
            except Exception:
                pass
            self.available = True
            _LOGGER.debug("[bwt_cosmy] GATT connected -> %s", self.address)
            return self._client
        except Exception as e:
            self.available = False
            _LOGGER.debug("[bwt_cosmy] GATT connect failed -> %s (%s)", self.address, e)
            return None

    def _on_disconnect(self) -> None:
        _LOGGER.debug("[bwt_cosmy] GATT disconnected -> %s", self.address)
        self._client = None
        self.available = False
        self._push_update()

    # ---------- notify parsing ----------
    @staticmethod
    def _is_ack_frame(data: bytes) -> bool:
        if len(data) in (3, 4) and data[:2] == b"\x00\x51":
            return True
        if len(data) <= 12 and (data.endswith(b"\x51\x0c") or data.endswith(b"\x51\x0c\xfd")):
            return True
        return False

    def _parse_status(self, data: bytes) -> bool | None:
        # 20 bytes, header ffa53a1384 ; bit7 of data[5] = cleaning ; minutes LE [6:8]
        if len(data) == 20 and data[:5] == bytes.fromhex("ffa53a1384"):
            cleaning = bool(data[5] & 0x80)
            self.cleaning = cleaning
            self.minutes = int.from_bytes(data[6:8], "little") if cleaning else 0
            _LOGGER.debug("[bwt_cosmy] Status: %s, minutes=%d", "CLEANING" if cleaning else "IDLE", self.minutes)
            return cleaning
        _LOGGER.debug("[bwt_cosmy] Unexpected frame: %s", data.hex())
        return None

    def _on_notify(self, _handle: int, payload: bytearray) -> None:
        b = bytes(payload)
        if self._is_ack_frame(b):
            _LOGGER.debug("[bwt_cosmy] ACK ignored: %s", b.hex())
            return
        self._parse_status(b)
        self.available = True
        self._push_update()

    def _push_update(self) -> None:
        # push minutes and state to entities
        async_dispatcher_send(self.hass, self.sig_minutes, self.minutes)
        async_dispatcher_send(self.hass, self.sig_state, self.cleaning, self.minutes)

    # ---------- public ops ----------
    async def async_refresh(self) -> None:
        """Attempt (re)connection and query status."""
        if self._lock.locked():
            _LOGGER.debug("[bwt_cosmy] refresh already in progress -> skip")
            return
        async with self._lock:
            client = await self._ensure_client()
            if not client:
                self.available = False
                self._push_update()
                return
            try:
                await client.start_notify(CHAR_NOTIFY, self._on_notify)
                await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
                await asyncio.sleep(NOTIFY_WAIT)
                await client.stop_notify(CHAR_NOTIFY)
                self.available = True
                # if no notify came, still push current state
                self._push_update()
            except Exception as e:
                self.available = False
                _LOGGER.debug("[bwt_cosmy] refresh failed: %s", e)
                try:
                    if self._client and self._client.is_connected:
                        await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
                self._push_update()

    async def async_start_cleaning(self) -> None:
        client = await self._ensure_client()
        if not client:
            self.available = False
            self._push_update()
            return
        try:
            await client.start_notify(CHAR_NOTIFY, self._on_notify)
            # optimistic
            self.cleaning = True
            self._push_update()
            await client.write_gatt_char(CHAR_WRITE, CMD_ON, response=True)
            await asyncio.sleep(1.5)
            await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
            await asyncio.sleep(2.0)
        finally:
            try:
                await client.stop_notify(CHAR_NOTIFY)
            except Exception:
                pass

    async def async_stop_cleaning(self) -> None:
        client = await self._ensure_client()
        if not client:
            self.available = False
            self._push_update()
            return
        try:
            await client.start_notify(CHAR_NOTIFY, self._on_notify)
            # optimistic
            self.cleaning = False
            self.minutes = 0
            self._push_update()
            await client.write_gatt_char(CHAR_WRITE, CMD_OFF, response=True)
            await asyncio.sleep(0.8)
            await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
            await asyncio.sleep(1.5)
        finally:
            try:
                await client.stop_notify(CHAR_NOTIFY)
            except Exception:
                pass
