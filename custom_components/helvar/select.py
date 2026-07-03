"""Support for Helvar Groups and Scenes."""
import logging

import aiohelvar

# Import the device class from the component that you want to support
from homeassistant.components.select import SelectEntity

from .const import (
    DOMAIN as HELVAR_DOMAIN,
    OFF_OPTION,
    OPT_OFF_SCENES,
    OPT_SCENE_NAMES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    """Not currently used."""


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Helvar groups from a config entry."""

    router = hass.data[HELVAR_DOMAIN][config_entry.entry_id]

    groups = [
        HelvarGroup(group, router, config_entry)
        for group in router.api.groups.groups.values()
    ]

    _LOGGER.info("Adding %s groups", len(groups))

    async_add_entities(groups)


class HelvarGroup(SelectEntity):
    """A Helvar group, exposed as a select of its scenes."""

    def __init__(self, group: aiohelvar.groups.Group, router, config_entry=None):
        """Initialize a HelvarGroup."""
        self.router = router
        self.group = group
        self.config_entry = config_entry
        self._attr_current_option = None
        self.register_subscription()

    @property
    def _scene_name_overrides(self):
        """User-defined display names, keyed by "<group>.<block>.<scene>"."""
        if self.config_entry is None:
            return {}
        return self.config_entry.options.get(OPT_SCENE_NAMES, {})

    @property
    def _off_scene(self):
        """The scene address string ("<block>.<scene>") recalled for Off, if set."""
        if self.config_entry is None:
            return None
        off_scenes = self.config_entry.options.get(OPT_OFF_SCENES, {})
        return off_scenes.get(str(self.group.group_id))

    def _render_scene_name(self, scene):
        """Render a scene option label, honouring user display-name overrides."""
        if scene is None:
            return None
        key = f"{scene.address.group}.{scene.address.block}.{scene.address.scene}"
        name = self._scene_name_overrides.get(key) or scene.display_name
        return f"{name} - {scene.address}"

    @property
    def current_option(self):
        """Get current selected option."""
        current_scene_address = self.group.get_last_scene_address()
        if current_scene_address is None:
            return None
        current_scene = self.router.api.scenes.get_scene_safe(current_scene_address)

        return self._render_scene_name(current_scene)

    @property
    def unique_id(self):
        """Get unique id."""
        return f"{self.group.group_id}-select"

    @property
    def available(self):
        """The group is controllable while the router connection is up."""
        return bool(self.router.api and self.router.api.connected)

    @property
    def options(self):
        """All selectable scenes of the group, plus an explicit Off entry.

        Includes unnamed scenes (with the library's generated fallback names),
        so groups whose scenes have no router-stored names still get
        selectable options.
        """
        scenes = self.router.api.scenes.get_selectable_scenes_for_group(
            self.group.group_id, include_unnamed=True
        )

        options = [self._render_scene_name(scene) for scene in scenes]
        options.append(OFF_OPTION)
        return options

    def register_subscription(self):
        """Register subscription."""

        async def async_router_callback_group(group_id):
            _LOGGER.info("Group %s update callback has been received", group_id)
            self.async_write_ha_state()

        result = self.router.api.groups.register_subscription(
            self.group.group_id, async_router_callback_group
        )

        if result is not True:
            _LOGGER.error(
                "Could not register for a callback for group %s", self.group.group_id
            )

    @property
    def name(self):
        """Return the display name of this group."""
        return f"Group: {self.group.name}"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""

        if option == OFF_OPTION:
            await self._async_turn_off()
            return

        # translate UI string back to address. (Hass should really be using key:value pairs...)
        scene_address = _scene_string_to_address(option)

        # call scene change for group
        await self.router.api.groups.set_scene(scene_address)

    async def _async_turn_off(self):
        """Turn the group off.

        Recalls the user-configured off scene for the group if one is set in
        the options flow; otherwise forces the whole group to level 0 with a
        direct group level (C:13), which also drives channels whose
        scene-table entry is "*" (ignore scene command).
        """
        off_scene = self._off_scene
        if off_scene:
            block, scene = (int(part) for part in off_scene.split("."))
            await self.router.api.groups.set_scene(
                aiohelvar.SceneAddress(int(self.group.group_id), block, scene)
            )
            return

        await self.router.api.groups.set_group_level(self.group.group_id, 0)


def _scene_string_to_address(scene_string):
    """Convert hass name for scene to a SceneAddress."""

    scene_address = scene_string.rsplit(" - ", maxsplit=1)[1].strip(" ")
    return aiohelvar.SceneAddress.fromString(scene_address)
