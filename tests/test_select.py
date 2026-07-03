"""Tests for the Helvar scene select entity."""
import pytest
from unittest.mock import AsyncMock, Mock, patch

from aiohelvar.parser.address import SceneAddress
from aiohelvar.scenes import Scene

from custom_components.helvar.const import (
    OFF_OPTION,
    OPT_OFF_SCENES,
    OPT_SCENE_NAMES,
)
from custom_components.helvar.select import HelvarGroup, _scene_string_to_address


def _make_router(scenes):
    router = Mock()
    router.api = Mock()
    router.api.connected = True
    router.api.groups.register_subscription = Mock(return_value=True)
    router.api.groups.set_scene = AsyncMock()
    router.api.groups.set_group_level = AsyncMock()
    router.api.scenes.get_selectable_scenes_for_group = Mock(return_value=scenes)
    router.api.scenes.get_scene_safe = Mock(return_value=None)
    return router


def _make_group(group_id=1, name="Living room"):
    group = Mock()
    group.group_id = group_id
    group.name = name
    group.get_last_scene_address = Mock(return_value=None)
    return group


def _make_entry(options=None):
    entry = Mock()
    entry.options = options or {}
    return entry


@pytest.fixture
def scenes():
    named = Scene(SceneAddress(1, 1, 1), name="Day")
    unnamed = Scene(SceneAddress(1, 1, 15))
    return [named, unnamed]


class TestOptions:
    def test_options_include_unnamed_scenes_and_off(self, scenes):
        router = _make_router(scenes)
        entity = HelvarGroup(_make_group(), router, _make_entry())

        assert entity.options == [
            "Day - @1.1.1",
            "Scene 1.15 - @1.1.15",  # library fallback name for unnamed scenes
            OFF_OPTION,
        ]
        router.api.scenes.get_selectable_scenes_for_group.assert_called_with(
            1, include_unnamed=True
        )

    def test_user_scene_name_overrides_apply(self, scenes):
        router = _make_router(scenes)
        entry = _make_entry(
            {OPT_SCENE_NAMES: {"1.1.1": "Morgens", "1.1.15": "Alles aus"}}
        )
        entity = HelvarGroup(_make_group(), router, entry)

        assert entity.options == [
            "Morgens - @1.1.1",
            "Alles aus - @1.1.15",
            OFF_OPTION,
        ]

    def test_entity_without_config_entry_still_works(self, scenes):
        router = _make_router(scenes)
        entity = HelvarGroup(_make_group(), router)
        assert entity.options[-1] == OFF_OPTION


class TestSelectOption:
    @pytest.mark.asyncio
    async def test_selecting_a_scene_recalls_it(self, scenes):
        router = _make_router(scenes)
        entity = HelvarGroup(_make_group(), router, _make_entry())

        await entity.async_select_option("Day - @1.1.1")

        router.api.groups.set_scene.assert_called_once()
        (address,) = router.api.groups.set_scene.call_args[0]
        assert address == SceneAddress(1, 1, 1)

    @pytest.mark.asyncio
    async def test_off_defaults_to_direct_group_level_zero(self, scenes):
        router = _make_router(scenes)
        entity = HelvarGroup(_make_group(), router, _make_entry())

        await entity.async_select_option(OFF_OPTION)

        router.api.groups.set_group_level.assert_called_once_with(1, 0)
        router.api.groups.set_scene.assert_not_called()

    @pytest.mark.asyncio
    async def test_off_recalls_configured_off_scene(self, scenes):
        router = _make_router(scenes)
        entry = _make_entry({OPT_OFF_SCENES: {"1": "1.15"}})
        entity = HelvarGroup(_make_group(), router, entry)

        await entity.async_select_option(OFF_OPTION)

        router.api.groups.set_scene.assert_called_once()
        (address,) = router.api.groups.set_scene.call_args[0]
        assert address == SceneAddress(1, 1, 15)
        router.api.groups.set_group_level.assert_not_called()


class TestState:
    def test_current_option_is_none_without_last_scene(self, scenes):
        router = _make_router(scenes)
        entity = HelvarGroup(_make_group(), router, _make_entry())
        assert entity.current_option is None

    def test_current_option_renders_last_scene_with_override(self, scenes):
        router = _make_router(scenes)
        router.api.scenes.get_scene_safe = Mock(return_value=scenes[0])
        entry = _make_entry({OPT_SCENE_NAMES: {"1.1.1": "Morgens"}})

        group = _make_group()
        group.get_last_scene_address = Mock(return_value=SceneAddress(1, 1, 1))
        entity = HelvarGroup(group, router, entry)

        assert entity.current_option == "Morgens - @1.1.1"

    def test_available_follows_router_connection(self, scenes):
        router = _make_router(scenes)
        entity = HelvarGroup(_make_group(), router, _make_entry())
        assert entity.available is True

        router.api.connected = False
        assert entity.available is False

    def test_unique_id_and_name(self, scenes):
        router = _make_router(scenes)
        entity = HelvarGroup(_make_group(), router, _make_entry())
        assert entity.unique_id == "1-select"
        assert entity.name == "Group: Living room"


def test_scene_string_to_address():
    address = _scene_string_to_address("My name - with dash - @1.2.3")
    assert address == SceneAddress(1, 2, 3)
