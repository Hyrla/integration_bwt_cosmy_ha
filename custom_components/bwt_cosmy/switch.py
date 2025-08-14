"""
Switch platform for BWT Cosmy BLE device (config entry version).
"""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .cosmy import CosmyClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Cosmy switch from a config entry."""
    address = entry.data["address"]
    timeout = entry.data.get("timeout", 20.0)
    coordinator = CosmyCoordinator(hass, address, timeout)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([CosmySwitch(coordinator, address, timeout)])

class CosmyCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, address, timeout):
        super().__init__(hass, _LOGGER, name=f"Cosmy {address}", update_interval=None)
        self._client = CosmyClient(address, timeout)
        self._address = address
        self._timeout = timeout

    async def _async_update_data(self):
        state, mins = await self._client.query_status()
        return {"state": state, "minutes": mins}

class CosmySwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, address, timeout):
        super().__init__(coordinator)
        self._address = address
        self._timeout = timeout
        self._attr_name = f"Cosmy {address}"
        self._attr_unique_id = f"cosmy_{address.replace(':','_')}"

    @property
    def is_on(self):
        return self.coordinator.data.get("state")

    @property
    def extra_state_attributes(self):
        return {"minutes": self.coordinator.data.get("minutes")}

    async def async_turn_on(self, **kwargs):
        await self.coordinator._client.power_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self.coordinator._client.power_off()
        await self.coordinator.async_request_refresh()
