# Basic Home Assistant integration setup
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
from .cosmy import CosmyClient

DOMAIN = "bwt_cosmy"
_LOGGER = logging.getLogger(__name__)

SERVICE_TURN_ON = "turn_on"
SERVICE_TURN_OFF = "turn_off"
SERVICE_QUERY_STATUS = "query_status"

SERVICE_SCHEMA = {
	"address": str,
	"timeout": float,
}

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
	"""Set up the BWT Cosmy integration (YAML setup not supported, use UI)."""
	return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Set up BWT Cosmy from a config entry (UI)."""
	_LOGGER.debug("Setting up BWT Cosmy config entry: %s", entry.entry_id)
	hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
	await hass.config_entries.async_forward_entry_setups(entry, ["switch"])
	return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Unload a config entry."""
	_LOGGER.debug("Unloading BWT Cosmy config entry: %s", entry.entry_id)
	hass.data[DOMAIN].pop(entry.entry_id, None)
	return True
