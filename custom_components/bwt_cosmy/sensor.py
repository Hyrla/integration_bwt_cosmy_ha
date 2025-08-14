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
    """Remaining cleaning minutes via the shared BLE coordinator.

    Availability mirrors the BLE connection:
    - unavailable if robot/proxy is disconnected,
    - when connected: 0 if idle, N>0 if cleaning.
    """

    _attr_icon = "mdi:clock-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_should_poll = False

    def __init__(self, coord, address: str, name: str) -> None:
        self.coordinator = coord
        self.address = address

        # minutes value (None when unavailable)
        self._minutes: Optional[int] = (
            int(coord.minutes) if coord.available else None
        )

        # Unique ID to persist the entity
        base = address.replace(":", "").lower()
        self._attr_unique_id = f"{DOMAIN}_{base}_minutes"

        # Use translations: "<device name>: <translated entity name>"
        self._attr_has_entity_name = True
        self._attr_translation_key = "cleaning_minutes"

        # Attach to the same device as the switch
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{DOMAIN}_{base}")},
            connections={(dr.CONNECTION_BLUETOOTH, address)},
            name=name,
            manufacturer="BWT",
            model="Cosmy",
        )

        # availability follows coordinator
        self._attr_available = coord.available

        # Dispatcher plumbing
        self._signal_minutes = SIGNAL_MINUTES_FMT.format(addr=base)
        self._signal_refresh = SIGNAL_REFRESH_FMT.format(addr=base)
        self._unsub_minutes = None

    async def async_added_to_hass(self) -> None:
        # Subscribe to minutes pushed by the coordinator (already on HA loop)
        self._unsub_minutes = async_dispatcher_connect(
            self.hass, self._signal_minutes, self._on_minutes
        )
        # Publish initial state (may be unavailable)
        self.async_write_ha_state()
        # Ask an immediate refresh for a fresh reading
        async_dispatcher_send(self.hass, self._signal_refresh)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_minutes:
            self._unsub_minutes()
            self._unsub_minutes = None

    def _on_minutes(self, minutes: Optional[int]) -> None:
        """Dispatcher callback — reflect coordinator availability and minutes."""
        # Availability mirrors the coordinator
        self._attr_available = self.coordinator.available

        if not self._attr_available:
            # When disconnected, show sensor as unavailable (value None)
            self._minutes = None
        else:
            # Connected: if None (shouldn't happen), default to 0
            self._minutes = int(minutes) if minutes is not None else 0

        # Ensure state write happens on HA loop
        try:
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)
        except Exception:
            self.hass.async_create_task(self.async_update_ha_state())

    @property
    def native_value(self) -> Optional[int]:
        # None when unavailable; otherwise minutes (0 when idle)
        return self._minutes

    async def async_update(self) -> None:
        # Manual update → ask the coordinator to refresh BLE status
        async_dispatcher_send(self.hass, self._signal_refresh)
