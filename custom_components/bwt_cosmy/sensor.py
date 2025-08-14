from __future__ import annotations

import logging
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_NAME,
    DATA_COORDINATOR,
    SIGNAL_MINUTES_FMT,
    SIGNAL_REFRESH_FMT,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coord = data[DATA_COORDINATOR]
    name = entry.data.get(CONF_NAME) or "BWT Cosmy"
    address = (entry.unique_id or entry.data.get(CONF_ADDRESS) or "").strip().upper()

    ent = CosmyMinutesSensor(coord, address, name)
    async_add_entities([ent])


class CosmyMinutesSensor(SensorEntity):
    """Remaining cleaning minutes read via the shared BLE coordinator.

    This sensor is always available; when the robot is idle or unreachable,
    it exposes 0 minutes instead of becoming unavailable.
    """

    _attr_icon = "mdi:clock-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_should_poll = False

    def __init__(self, coord, address: str, name: str) -> None:
        self.coordinator = coord
        self.address = address
        # Default to 0 at startup
        self._minutes: int = int(coord.minutes) if coord.minutes else 0

        # Let HA compose "<device name>: <translated entity name>"
        self._attr_has_entity_name = True
        self._attr_translation_key = "cleaning_minutes"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{DOMAIN}_{address.replace(':','').lower()}")},
            connections={(dr.CONNECTION_BLUETOOTH, address)},
            name=name,
            manufacturer="BWT",
            model="Cosmy",
        )

        # We keep this sensor available regardless of BLE connectivity
        self._attr_available = True

        key = self.address.replace(":", "").lower()
        self._signal_minutes = SIGNAL_MINUTES_FMT.format(addr=key)
        self._signal_refresh = SIGNAL_REFRESH_FMT.format(addr=key)
        self._unsub_minutes = None

    # Always show as available
    @property
    def available(self) -> bool:  # type: ignore[override]
        return True

    async def async_added_to_hass(self) -> None:
        # Subscribe to minutes updates (coordinator dispatches from HA loop)
        self._unsub_minutes = async_dispatcher_connect(
            self.hass, self._signal_minutes, self._on_minutes
        )
        # Publish initial 0 (or cached value) immediately so UI doesn't show unavailable
        self.async_write_ha_state()
        # Ask an immediate refresh for a fresh reading
        async_dispatcher_send(self.hass, self._signal_refresh)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_minutes:
            self._unsub_minutes()
            self._unsub_minutes = None

    def _on_minutes(self, minutes: Optional[int]) -> None:
        """Dispatcher callback — ensure state write happens on HA loop."""
        self._minutes = int(minutes) if minutes is not None else 0
        try:
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)
        except Exception:
            self.hass.async_create_task(self.async_update_ha_state())

    @property
    def native_value(self) -> int:
        return self._minutes

    async def async_update(self) -> None:
        # Manual update: ask coordinator to refresh BLE status
        async_dispatcher_send(self.hass, self._signal_refresh)
