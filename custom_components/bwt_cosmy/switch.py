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
from homeassistant.components.bluetooth import async_ble_device_from_address, BluetoothServiceInfoBleak
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Cosmy switch from a config entry using Home Assistant BLE API."""
    address = entry.data["address"]
    timeout = entry.data.get("timeout", 20)
    # Récupère le service_info Bluetooth de Home Assistant
    bluetooth = hass.data[DOMAIN][entry.entry_id]["service_info"]
    # Récupère le BLEDevice depuis service_info ou via l'adresse
    ble_device = bluetooth.device if bluetooth else await async_ble_device_from_address(hass, address, connectable=True)
    coordinator = CosmyCoordinator(hass, ble_device, timeout)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([CosmySwitch(coordinator, address, timeout)])

class CosmyCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, ble_device, timeout):
        super().__init__(hass, _LOGGER, name=f"Cosmy", update_interval=None)
        self._client = CosmyClient(ble_device, hass)
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
