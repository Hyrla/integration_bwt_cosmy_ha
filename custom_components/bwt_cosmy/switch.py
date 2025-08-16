from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_NAME,
    DATA_COORDINATOR,
    SIGNAL_STATE_FMT,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coord = data[DATA_COORDINATOR]
    name = entry.data.get(CONF_NAME) or "BWT Cosmy"
    address = (entry.unique_id or entry.data.get(CONF_ADDRESS) or "").strip().upper()

    ent = BwtCosmySwitch(entry, coord, address, name)
    async_add_entities([ent], update_before_add=False)


class BwtCosmySwitch(SwitchEntity):
    """Cosmy cleaning mode switch (start/stop)."""

    _attr_icon = "mdi:robot-vacuum"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, coord, address: str, name: str) -> None:
        self.entry = entry
        self.coordinator = coord
        self.address = address

        # Let HA compose "<device name>: <translated entity name>"
        self._attr_has_entity_name = True
        self._attr_translation_key = "cleaning"

        self._attr_unique_id = f"{DOMAIN}_{address.replace(':','').lower()}_clean"
        self._attr_available = coord.available

        self._is_on: Optional[bool] = coord.cleaning
        self._minutes: int = coord.minutes

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            connections={(dr.CONNECTION_BLUETOOTH, self.address)},
            name=name,
            manufacturer="BWT",
            model="Cosmy",
        )

        key = self.address.replace(":", "").lower()
        self._signal_state = SIGNAL_STATE_FMT.format(addr=key)
        self._unsub_state = None

    async def async_added_to_hass(self) -> None:
        # Listen to state pushed by the coordinator (already on HA loop)
        self._unsub_state = async_dispatcher_connect(
            self.hass, self._signal_state, self._on_state
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    def _on_state(self, cleaning: Optional[bool], minutes: int) -> None:
        """Dispatcher callback — ensure state write happens on HA loop."""
        self._is_on = cleaning
        self._minutes = minutes
        self._attr_available = self.coordinator.available
        try:
            self.hass.loop.call_soon_threadsafe(lambda: self.async_write_ha_state())
        except Exception:
            self.hass.async_create_task(self.async_update_ha_state())

    # ---------- Switch API ----------
    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict:
        return {"minutes_remaining": self._minutes}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_start_cleaning()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_stop_cleaning()

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()
