"""The HelvarNet integration."""
from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from aiohelvar.parser.address import SceneAddress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_BLOCK,
    ATTR_FADE,
    ATTR_GROUP,
    ATTR_LEVEL,
    ATTR_SCENE,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_FADE_TIME,
    DEFAULT_PORT,
    DOMAIN,
    SERVICE_RECALL_SCENE,
    SERVICE_SET_GROUP_LEVEL,
)
from .router import HelvarRouter

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["light", "select"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_RECALL_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROUP): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_BLOCK, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=253)
        ),
        vol.Required(ATTR_SCENE): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
        # HelvarNet fade time, units of 1/100 s (50 == 0.5 s).
        vol.Optional(ATTR_FADE, default=DEFAULT_FADE_TIME): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=65535)
        ),
    }
)

SERVICE_SET_GROUP_LEVEL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROUP): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Required(ATTR_LEVEL): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
        vol.Optional(ATTR_FADE, default=DEFAULT_FADE_TIME): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=65535)
        ),
    }
)


def _routers_for_group(hass: HomeAssistant, group_id: int):
    """All configured routers that know the given group."""
    routers = [
        router
        for router in hass.data.get(DOMAIN, {}).values()
        if router is not None and router.api is not None
    ]
    matching = [
        router for router in routers if int(group_id) in router.api.groups.groups
    ]
    if not matching:
        raise HomeAssistantError(
            f"No configured Helvar router has a group {group_id}"
        )
    return matching


def _register_services(hass: HomeAssistant) -> None:
    """Register the helvar.* services (idempotent)."""

    if hass.services.has_service(DOMAIN, SERVICE_RECALL_SCENE):
        return

    async def async_recall_scene(call: ServiceCall) -> None:
        group = call.data[ATTR_GROUP]
        address = SceneAddress(group, call.data[ATTR_BLOCK], call.data[ATTR_SCENE])
        for router in _routers_for_group(hass, group):
            await router.api.groups.set_scene(address, call.data[ATTR_FADE])

    async def async_set_group_level(call: ServiceCall) -> None:
        group = call.data[ATTR_GROUP]
        for router in _routers_for_group(hass, group):
            await router.api.groups.set_group_level(
                group, call.data[ATTR_LEVEL], call.data[ATTR_FADE]
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RECALL_SCENE,
        async_recall_scene,
        schema=SERVICE_RECALL_SCENE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_GROUP_LEVEL,
        async_set_group_level,
        schema=SERVICE_SET_GROUP_LEVEL_SCHEMA,
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options (scene names, off scenes) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass, config):
    """Set up the Helvar platform."""

    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HelvarNet from a config entry."""

    router = HelvarRouter(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = router

    if not await router.async_setup():
        hass.data[DOMAIN][entry.entry_id] = None
        return False

    _register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unload_ok:
        router = hass.data[DOMAIN].pop(entry.entry_id)
        if router is not None and router.api is not None:
            try:
                await router.api.disconnect()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Error disconnecting Helvar router", exc_info=True)

    return unload_ok
