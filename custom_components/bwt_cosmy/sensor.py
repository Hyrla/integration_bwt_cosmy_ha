from __future__ import annotations

import logging
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

from .const import (
    DOMAIN, CONF_ADDRESS, CONF_NAME, DATA_COORDINATOR,
    SIGNAL_MINUTES_FMT, SIGNAL_REFRESH_FMT,
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
    """Remaining cleaning minutes read from BLE via the shared coordinator."""

    _attr_icon = "mdi:clock-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_should_poll = False

    def __init__(self, coord, address: str, name: str) -> None:
        self.coordinator = coord
        self.address = address
        self._minutes: Optional[int] = coord.minutes if coord.minutes else 0
        self._attr_name = f"{name} Cleaning Minutes"
        self._attr_unique_id = f"{DOMAIN}_{address.replace(':','').lower()}_minutes"
        self._attr_available = coord.available

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{DOMAIN}_{address.replace(':','').lower()}")},
            connections={(dr.CONNECTION_BLUETOOTH, address)},
            name=name,
            manufacturer="BWT",
            model="Cosmy",
        )

        key = self.address.replace(":", "").lower()
        self._signal_minutes = SIGNAL_MINUTES_FMT.format(addr=key)
        self._signal_refresh = SIGNAL_REFRESH_FMT.format(addr=key)
        self._unsub_minutes = None

    async def async_added_to_hass(self) -> None:
        # Subscribe to minutes updates
        self._unsub_minutes = async_dispatcher_connect(
            self.hass, self._signal_minutes, self._on_minutes
        )
        # Request an immediate refresh to get an up-to-date value at startup
        async_dispatcher_send(self.hass, self._signal_refresh)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_minutes:
            self._unsub_minutes()
            self._unsub_minutes = None

    def _on_minutes(self, minutes: int) -> None:
        self._minutes = int(minutes)
        self._attr_available = self.coordinator.available
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        return self._minutes

    async def async_update(self) -> None:
        # Manual update: ask coordinator to refresh BLE status
        async_dispatcher_send(self.hass, self._signal_refresh)
