from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN, DATA_COORDINATOR
from .coordinator import CosmyCoordinator

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address = (entry.unique_id or entry.data.get("address") or "").strip().upper()
    name = entry.data.get("name") or "BWT Cosmy"

    coord = CosmyCoordinator(hass, address, name)
    # Non-bloquant: démarre timers + planifie un refresh async
    await coord.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_COORDINATOR: coord}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data:
        coord: CosmyCoordinator = data.get(DATA_COORDINATOR)
        if coord:
            await coord.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
