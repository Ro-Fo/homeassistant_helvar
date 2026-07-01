"""Config flow for HelvarNet integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohelvar
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CLUSTER_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_ROUTER_ID,
    DEFAULT_PORT,
    DOMAIN,
)
from .router import build_router

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        # Optional: set these when the router isn't on a standard 10.254.C.R /
        # 255.255.255.0 network (e.g. reached via a bridge), where deriving the
        # HelvarNet cluster/router from the IP would be wrong.
        vol.Optional(CONF_CLUSTER_ID): vol.All(
            cv.positive_int, vol.Range(min=0, max=253)
        ),
        vol.Optional(CONF_ROUTER_ID): vol.All(cv.positive_int, vol.Range(min=1, max=254)),
    }
)


@config_entries.HANDLERS.register(DOMAIN)
class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Helvar."""

    VERSION = 1

    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize the Helvar flow."""
        self.router: aiohelvar.Router | None = None

    async def validate_input(
        self, hass: HomeAssistant, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate the user input allows us to connect.

        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        router = build_router(
            data[CONF_HOST],
            data[CONF_PORT],
            cluster_id=data.get(CONF_CLUSTER_ID),
            router_id=data.get(CONF_ROUTER_ID),
        )

        try:
            await router.connect()
        except ConnectionError as initial_exception:
            raise CannotConnect() from initial_exception

        workgroup_name = router.workgroup_name
        self.router = router
        # Return info that you want to store in the config entry.
        return {"title": workgroup_name}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await self.validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        if errors:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        _LOGGER.exception("Creating Helvar config entry")
        return self.async_create_entry(title=info["title"], data=user_input)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
