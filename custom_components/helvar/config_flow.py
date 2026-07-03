"""Config flow for HelvarNet integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohelvar
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, selector

from .const import (
    CONF_CLUSTER_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_ROUTER_ID,
    DEFAULT_PORT,
    DOMAIN,
    OPT_OFF_SCENES,
    OPT_SCENE_NAMES,
)
from .router import create_router

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        # Advanced: force the HelvarNet cluster/router ids. Leave both empty
        # to let aiohelvar discover the real ids from the router at runtime.
        vol.Optional(CONF_CLUSTER_ID): vol.All(vol.Coerce(int), vol.Range(min=0, max=253)),
        vol.Optional(CONF_ROUTER_ID): vol.All(vol.Coerce(int), vol.Range(min=1, max=254)),
    }
)

_MULTILINE_TEXT = selector.TextSelector(selector.TextSelectorConfig(multiline=True))


def parse_scene_name_lines(text: str | None) -> dict[str, str]:
    """Parse scene display-name overrides from options-flow text.

    One override per line, "<group>.<block>.<scene> = <friendly name>", e.g.
    "1.1.3 = Dinner". Blank lines and lines starting with "#" are ignored.
    Raises vol.Invalid on malformed lines.
    """
    mapping: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        address, sep, name = line.partition("=")
        address = address.strip()
        name = name.strip()
        if not sep or not name:
            raise vol.Invalid(f"Expected '<group>.<block>.<scene> = <name>': {line}")
        mapping[_validate_scene_key(address)] = name
    return mapping


def _validate_scene_key(address: str) -> str:
    """Validate and normalise a "<group>.<block>.<scene>" key."""
    parts = address.split(".")
    if len(parts) != 3:
        raise vol.Invalid(f"Scene address must be <group>.<block>.<scene>: {address}")
    try:
        group, block, scene = (int(part) for part in parts)
    except ValueError as err:
        raise vol.Invalid(f"Scene address must be numeric: {address}") from err
    if group < 0 or not 1 <= block <= 253 or not 1 <= scene <= 16:
        raise vol.Invalid(f"Scene address out of range: {address}")
    return f"{group}.{block}.{scene}"


def parse_off_scene_lines(text: str | None) -> dict[str, str]:
    """Parse per-group "Off" scenes from options-flow text.

    One entry per line, "<group> = <block>.<scene>", e.g. "1 = 1.15". Groups
    without an entry are switched off with a direct group level of 0 instead.
    Raises vol.Invalid on malformed lines.
    """
    mapping: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        group, sep, scene = line.partition("=")
        group = group.strip()
        scene = scene.strip()
        if not sep or not scene:
            raise vol.Invalid(f"Expected '<group> = <block>.<scene>': {line}")
        try:
            group_id = int(group)
        except ValueError as err:
            raise vol.Invalid(f"Group must be numeric: {line}") from err
        parts = scene.split(".")
        if len(parts) != 2:
            raise vol.Invalid(f"Off scene must be <block>.<scene>: {line}")
        try:
            block, scene_id = (int(part) for part in parts)
        except ValueError as err:
            raise vol.Invalid(f"Off scene must be numeric: {line}") from err
        if group_id < 0 or not 1 <= block <= 253 or not 1 <= scene_id <= 16:
            raise vol.Invalid(f"Off scene out of range: {line}")
        mapping[str(group_id)] = f"{block}.{scene_id}"
    return mapping


def format_mapping_lines(mapping: dict[str, str] | None) -> str:
    """Render a stored options mapping back into options-flow text."""
    if not mapping:
        return ""
    return "\n".join(f"{key} = {value}" for key, value in sorted(mapping.items()))


@config_entries.HANDLERS.register(DOMAIN)
class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Helvar."""

    VERSION = 1

    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize the Helvar flow."""
        self.router: aiohelvar.Router | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return OptionsFlowHandler(config_entry)

    async def validate_input(
        self, hass: HomeAssistant, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate the user input allows us to connect.

        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        router = create_router(data)

        try:
            await router.connect()
        except (ConnectionError, OSError) as initial_exception:
            raise CannotConnect() from initial_exception

        workgroup_name = router.workgroup_name
        try:
            await router.disconnect()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug("Error disconnecting validation router", exc_info=True)

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

        # cluster_id / router_id only make sense as a pair.
        if (CONF_CLUSTER_ID in user_input) != (CONF_ROUTER_ID in user_input):
            errors["base"] = "cluster_router_pair"
        else:
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

        _LOGGER.info("Creating Helvar config entry")
        return self.async_create_entry(title=info["title"], data=user_input)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options for a configured Helvar router.

    Lets the user override scene display names per scene address and define
    an explicit "Off" scene per group. Both live in the config entry options,
    so site-specific data never ends up in the repository.
    """

    def __init__(self, config_entry):
        """Initialize the options flow."""
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the Helvar options."""
        errors = {}

        if user_input is not None:
            try:
                scene_names = parse_scene_name_lines(user_input.get(OPT_SCENE_NAMES))
                off_scenes = parse_off_scene_lines(user_input.get(OPT_OFF_SCENES))
            except vol.Invalid as err:
                _LOGGER.warning("Invalid Helvar options: %s", err)
                errors["base"] = "invalid_options"
            else:
                return self.async_create_entry(
                    title="",
                    data={OPT_SCENE_NAMES: scene_names, OPT_OFF_SCENES: off_scenes},
                )

        options = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_SCENE_NAMES,
                    description={
                        "suggested_value": format_mapping_lines(
                            options.get(OPT_SCENE_NAMES)
                        )
                    },
                ): _MULTILINE_TEXT,
                vol.Optional(
                    OPT_OFF_SCENES,
                    description={
                        "suggested_value": format_mapping_lines(
                            options.get(OPT_OFF_SCENES)
                        )
                    },
                ): _MULTILINE_TEXT,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
