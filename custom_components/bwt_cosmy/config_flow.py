import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_TIMEOUT
from .const import DOMAIN

DEFAULT_TIMEOUT = 20.0

class CosmyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BWT Cosmy BLE."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_bluetooth(self, discovery_info):
        """Handle a flow initialized by bluetooth discovery."""
        address = discovery_info[CONF_ADDRESS]
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        # Pré-remplir le formulaire avec l'adresse détectée
        return await self.async_step_user({CONF_ADDRESS: address})

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # TODO: Optionally validate BLE address
            return self.async_create_entry(title=user_input[CONF_ADDRESS], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): float,
            }),
            errors=errors,
        )
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_TIMEOUT
from .const import DOMAIN

DEFAULT_TIMEOUT = 20.0

class CosmyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BWT Cosmy BLE."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # TODO: Optionally validate BLE address
            return self.async_create_entry(title=user_input[CONF_ADDRESS], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): float,
            }),
            errors=errors,
        )
