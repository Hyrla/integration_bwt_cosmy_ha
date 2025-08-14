import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_TIMEOUT

CONF_MODEL = "model"
CONF_NAME = "name"
from .const import DOMAIN

DEFAULT_TIMEOUT = 20
DEFAULT_MODEL = "cosmy_100"

class CosmyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BWT Cosmy BLE."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_bluetooth(self, discovery_info):
        """Handle a flow initialized by bluetooth discovery."""
        address = discovery_info[CONF_ADDRESS]
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        # Stocke le service_info dans le flow pour l'utiliser à la création de l'entrée
        self.context["service_info"] = discovery_info
        # Pré-remplir le formulaire avec l'adresse détectée
        return await self.async_step_user({CONF_ADDRESS: address})

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Ajoute le service_info Bluetooth à l'entrée de config si présent
            data = dict(user_input)
            if "service_info" in self.context:
                data["service_info"] = self.context["service_info"]
            return self.async_create_entry(
                title=user_input.get(CONF_NAME) or user_input[CONF_ADDRESS],
                data=data
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MODEL, default=DEFAULT_MODEL): vol.In({
                    "cosmy_100": "Cosmy 100",
                    "other": "Autre"
                }),
                vol.Required(CONF_ADDRESS): str,
                vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
            }),
            errors=errors,
        )