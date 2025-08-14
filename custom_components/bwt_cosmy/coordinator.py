from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.components import bluetooth
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.dispatcher import (
    async_dispatcher_send,
    async_dispatcher_connect,
)

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from .const import (
    SERVICE_UUID,  # kept for reference
    CHAR_WRITE,
    CHAR_NOTIFY,
    CMD_ON,
    CMD_OFF,
    CMD_STAT,
    SIGNAL_STATE_FMT,
    SIGNAL_MINUTES_FMT,
    SIGNAL_REFRESH_FMT,
)

_LOGGER = logging.getLogger(__name__)

# Periodic reconnect + status
REFRESH_INTERVAL = timedelta(seconds=45)

# Hard timeouts (seconds)
CONNECT_TIMEOUT = 6.0
REFRESH_TIMEOUT = 5.0
NOTIFY_WAIT = 1.0

# Backoff after a failed refresh/connect (seconds)
BACKOFF_START = 10
BACKOFF_MAX = 120


class CosmyCoordinator:
    """Centralizes BLE (re)connection and status parsing for the Cosmy robot.

    Thread-safety: all dispatcher sends happen from HA's event loop.
    Bleak callbacks bounce into the HA loop via call_soon_threadsafe.
    """

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        self.hass = hass
        self.address = address.upper()
        self.name = name

        self._client: Optional[BleakClientWithServiceCache] = None
        self.cleaning: Optional[bool] = None  # True/False/None(unknown)
        self.minutes: int = 0
        self.available: bool = False

        self._lock = asyncio.Lock()
        self._unsub_timer = None

        # Queue a single trailing refresh if requests come while running
        self._refresh_queued = False

        # Backoff between retries after failures
        self._backoff = BACKOFF_START
        self._backoff_handle: Optional[asyncio.TimerHandle] = None

        # Per-device dispatcher signals
        key = self.address.replace(":", "").lower()
        self.sig_state = SIGNAL_STATE_FMT.format(addr=key)
        self.sig_minutes = SIGNAL_MINUTES_FMT.format(addr=key)
        self.sig_refresh = SIGNAL_REFRESH_FMT.format(addr=key)
        self._unsub_refresh = None

    # ---------------- Lifecycle ----------------
    async def async_start(self) -> None:
        """Register listeners and schedule the first refresh (non-blocking)."""
        self._unsub_refresh = async_dispatcher_connect(
            self.hass, self.sig_refresh, self._on_refresh_request
        )
        self._unsub_timer = async_track_time_interval(
            self.hass, self._scheduled_refresh, REFRESH_INTERVAL
        )
        # Do not block HA startup: schedule the first refresh
        self.hass.async_create_task(self.async_refresh())

    async def async_stop(self) -> None:
        """Stop timers and close BLE connection."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None
        if self._backoff_handle:
            self._backoff_handle.cancel()
            self._backoff_handle = None
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self.available = False
        self.minutes = 0
        self._push_update()

    async def _scheduled_refresh(self, _now) -> None:
        await self.async_refresh()

    def _on_refresh_request(self) -> None:
        """Dispatcher callback (may be off-loop) -> schedule safely on HA loop."""
        self.hass.loop.call_soon_threadsafe(self._queue_or_run_refresh)

    def _queue_or_run_refresh(self) -> None:
        """If a refresh is running, queue one trailing run; else start now."""
        if self._lock.locked():
            self._refresh_queued = True
            _LOGGER.debug("[bwt_cosmy] refresh in progress -> queue trailing refresh")
            return
        self.hass.async_create_task(self.async_refresh())

    # ---------------- BLE helpers ----------------
    async def _ensure_client(self) -> Optional[BleakClientWithServiceCache]:
        """Ensure a connected Bleak client (via HA Bluetooth proxy)."""
        if self._client and self._client.is_connected:
            return self._client

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=False
            )

        if ble_device is None:
            self.available = False
            self.minutes = 0
            _LOGGER.debug("[bwt_cosmy] BLEDevice %s not found (out of range/proxy)", self.address)
            return None

        try:
            # Guard against long internal retries with an overall timeout
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._client = await establish_connection(
                    client_class=BleakClientWithServiceCache,
                    device=ble_device,
                    name=self.address,
                )
            try:
                # Bounce disconnect into HA loop
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
            self.minutes = 0
            _LOGGER.debug("[bwt_cosmy] GATT connect failed -> %s (%s)", self.address, e)
            return None

    def _on_disconnect(self) -> None:
        """Runs in HA event loop (scheduled via call_soon_threadsafe)."""
        _LOGGER.debug("[bwt_cosmy] GATT disconnected -> %s", self.address)
        self._client = None
        self.available = False
        self.minutes = 0
        self._push_update()

    # ---------------- Notify handling (thread-safe) ----------------
    def _on_notify(self, _handle: int, payload: bytearray) -> None:
        """Bleak thread callback -> bounce into HA loop safely."""
        data = bytes(payload)
        self.hass.loop.call_soon_threadsafe(self._handle_notify, data)

    @staticmethod
    def _is_ack_frame(data: bytes) -> bool:
        """Filter short ACK frames that are not status frames."""
        if len(data) in (3, 4) and data[:2] == b"\x00\x51":
            return True
        if len(data) <= 12 and (data.endswith(b"\x51\x0c") or data.endswith(b"\x51\x0c\xfd")):
            return True
        return False

    def _handle_notify(self, data: bytes) -> None:
        """Runs in HA event loop; parse and publish status."""
        if self._is_ack_frame(data):
            _LOGGER.debug("[bwt_cosmy] ACK ignored: %s", data.hex())
            return
        self._parse_status(data)
        self.available = True
        self._push_update()

    def _parse_status(self, data: bytes) -> Optional[bool]:
        """Parse 20-byte status frame: header ffa53a1384, bit7 at [5] is cleaning, minutes LE [6:8]."""
        if len(data) == 20 and data[:5] == bytes.fromhex("ffa53a1384"):
            cleaning = bool(data[5] & 0x80)
            self.cleaning = cleaning
            self.minutes = int.from_bytes(data[6:8], "little") if cleaning else 0
            _LOGGER.debug(
                "[bwt_cosmy] Status: %s, minutes=%d",
                "CLEANING" if cleaning else "IDLE",
                self.minutes,
            )
            return cleaning
        _LOGGER.debug("[bwt_cosmy] Unexpected frame: %s", data.hex())
        return None

    def _push_update(self) -> None:
        """Emit dispatcher signals (runs in HA loop)."""
        async_dispatcher_send(
            self.hass,
            self.sig_minutes,
            self.minutes if self.available else None,
        )
        async_dispatcher_send(
            self.hass,
            self.sig_state,
            self.cleaning if self.available else None,
            self.minutes,
        )

    # ---------------- Public operations ----------------
    async def async_refresh(self) -> None:
        """Attempt (re)connection and query status; deduplicated and timed out."""
        if self._lock.locked():
            _LOGGER.debug("[bwt_cosmy] refresh already in progress -> skip")
            return
        async with self._lock:
            # Cancel any scheduled backoff when actively refreshing
            if self._backoff_handle:
                self._backoff_handle.cancel()
                self._backoff_handle = None

            client = await self._ensure_client()
            if not client:
                self.available = False
                self.minutes = 0
                self._push_update()
                # schedule next try with backoff
                self._schedule_backoff()
                return

            try:
                async with asyncio.timeout(REFRESH_TIMEOUT):
                    await client.start_notify(CHAR_NOTIFY, self._on_notify)
                    await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
                    await asyncio.sleep(NOTIFY_WAIT)
                    await client.stop_notify(CHAR_NOTIFY)
                self.available = True
                self._push_update()
                # reset backoff after success
                self._backoff = BACKOFF_START
            except (asyncio.TimeoutError, Exception) as e:
                self.available = False
                self.minutes = 0
                _LOGGER.debug("[bwt_cosmy] refresh failed/timeout: %s", e)
                try:
                    if self._client and self._client.is_connected:
                        await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
                self._push_update()
                self._schedule_backoff()
            finally:
                # Run a queued trailing refresh exactly once
                if self._refresh_queued:
                    self._refresh_queued = False
                    self.hass.async_create_task(self.async_refresh())

    def _schedule_backoff(self) -> None:
        """Schedule a retry with exponential backoff (non-blocking)."""
        delay = min(self._backoff, BACKOFF_MAX)
        _LOGGER.debug("[bwt_cosmy] scheduling retry in %ss", delay)
        self._backoff = min(self._backoff * 2, BACKOFF_MAX)
        if self._backoff_handle:
            self._backoff_handle.cancel()
        self._backoff_handle = self.hass.loop.call_later(
            delay, lambda: self.hass.async_create_task(self.async_refresh())
        )

    async def async_start_cleaning(self) -> None:
        client = await self._ensure_client()
        if not client:
            self.available = False
            self.minutes = 0
            self._push_update()
            self._schedule_backoff()
            return
        try:
            async with asyncio.timeout(REFRESH_TIMEOUT):
                await client.start_notify(CHAR_NOTIFY, self._on_notify)
                # Optimistic UI
                self.cleaning = True
                self._push_update()
                await client.write_gatt_char(CHAR_WRITE, CMD_ON, response=True)
                await asyncio.sleep(1.5)
                await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
                await asyncio.sleep(2.0)
        except (asyncio.TimeoutError, Exception) as e:
            _LOGGER.debug("[bwt_cosmy] start_cleaning failed/timeout: %s", e)
            self._schedule_backoff()
        finally:
            try:
                await client.stop_notify(CHAR_NOTIFY)
            except Exception:
                pass

    async def async_stop_cleaning(self) -> None:
        client = await self._ensure_client()
        if not client:
            self.available = False
            self.minutes = 0
            self._push_update()
            self._schedule_backoff()
            return
        try:
            async with asyncio.timeout(REFRESH_TIMEOUT):
                await client.start_notify(CHAR_NOTIFY, self._on_notify)
                # Optimistic UI
                self.cleaning = False
                self.minutes = 0
                self._push_update()
                await client.write_gatt_char(CHAR_WRITE, CMD_OFF, response=True)
                await asyncio.sleep(0.8)
                await client.write_gatt_char(CHAR_WRITE, CMD_STAT, response=True)
                await asyncio.sleep(1.5)
        except (asyncio.TimeoutError, Exception) as e:
            _LOGGER.debug("[bwt_cosmy] stop_cleaning failed/timeout: %s", e)
            self._schedule_backoff()
        finally:
            try:
                await client.stop_notify(CHAR_NOTIFY)
            except Exception:
                pass
