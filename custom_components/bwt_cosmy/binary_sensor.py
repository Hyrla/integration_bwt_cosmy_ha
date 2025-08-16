from __future__ import annotations

from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_ADDRESS, CONF_NAME, DATA_COORDINATOR, SIGNAL_IN_WATER_FMT

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coord = data[DATA_COORDINATOR]
    address = (entry.unique_id or entry.data.get(CONF_ADDRESS)).upper()
    name = entry.data.get(CONF_NAME) or "BWT Cosmy"
    async_add_entities([BwtCosmyInWaterBinarySensor(coord, address, name)], update_before_add=False)

class BwtCosmyInWaterBinarySensor(BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_should_poll = False

    def __init__(self, coordinator, address: str, name: str) -> None:
        self._coord = coordinator
        self._address = address
        self._attr_name = f"{name} In water"
        self._attr_unique_id = f"{DOMAIN}_{address.replace(':','').lower()}_inwater"
        self._attr_is_on: Optional[bool] = None
        self._attr_available = False
        self._attr_has_entity_name = True
        self._attr_translation_key = "in_water"

        self._signal = SIGNAL_IN_WATER_FMT.format(addr=address.replace(":","").lower())

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address.replace(':','').lower())},
            connections={(dr.CONNECTION_BLUETOOTH, address)},
            name=name,
            manufacturer="BWT",
            model="Cosmy",
        )

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_flag(value: Optional[bool]) -> None:
            # value is None when unavailable
            self._attr_available = value is not None
            self._attr_is_on = bool(value) if value is not None else None
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, _on_flag)
        )

        # push the current state immediately if coordinator already knows it
        _on_flag(self._coord.in_water if self._coord.available else None)

    @property
    def is_on(self) -> Optional[bool]:
        return self._attr_is_on
