"""Tests for the helvar.recall_scene and helvar.set_group_level services."""
import pytest
from unittest.mock import AsyncMock, Mock

from aiohelvar.parser.address import SceneAddress
from homeassistant.exceptions import HomeAssistantError

from custom_components.helvar import (
    SERVICE_RECALL_SCENE_SCHEMA,
    SERVICE_SET_GROUP_LEVEL_SCHEMA,
    _register_services,
    _routers_for_group,
)
from custom_components.helvar.const import (
    DOMAIN,
    SERVICE_RECALL_SCENE,
    SERVICE_SET_GROUP_LEVEL,
)


def _make_router(groups=(1,)):
    router = Mock()
    router.api = Mock()
    router.api.groups.groups = {group_id: Mock() for group_id in groups}
    router.api.groups.set_scene = AsyncMock()
    router.api.groups.set_group_level = AsyncMock()
    return router


def _make_hass(routers):
    hass = Mock()
    hass.data = {DOMAIN: {f"entry{i}": router for i, router in enumerate(routers)}}
    hass.services = Mock()
    hass.services.has_service = Mock(return_value=False)
    registered = {}

    def register(domain, service, handler, schema=None):
        registered[(domain, service)] = (handler, schema)

    hass.services.async_register = Mock(side_effect=register)
    return hass, registered


class TestServiceSchemas:
    def test_recall_scene_defaults(self):
        data = SERVICE_RECALL_SCENE_SCHEMA({"group": "1", "scene": "7"})
        assert data == {"group": 1, "block": 1, "scene": 7, "fade": 50}

    def test_recall_scene_rejects_bad_scene(self):
        with pytest.raises(Exception):
            SERVICE_RECALL_SCENE_SCHEMA({"group": 1, "scene": 17})

    def test_set_group_level_defaults(self):
        data = SERVICE_SET_GROUP_LEVEL_SCHEMA({"group": 1, "level": 40})
        assert data == {"group": 1, "level": 40.0, "fade": 50}

    def test_set_group_level_rejects_out_of_range(self):
        with pytest.raises(Exception):
            SERVICE_SET_GROUP_LEVEL_SCHEMA({"group": 1, "level": 101})


class TestRoutersForGroup:
    def test_finds_routers_with_group(self):
        router1 = _make_router(groups=(1, 2))
        router2 = _make_router(groups=(3,))
        hass, _ = _make_hass([router1, router2])

        assert _routers_for_group(hass, 1) == [router1]
        assert _routers_for_group(hass, 3) == [router2]

    def test_raises_when_no_router_has_group(self):
        hass, _ = _make_hass([_make_router(groups=(1,))])
        with pytest.raises(HomeAssistantError):
            _routers_for_group(hass, 99)

    def test_ignores_failed_setups(self):
        hass, _ = _make_hass([None, _make_router(groups=(1,))])
        assert len(_routers_for_group(hass, 1)) == 1


class TestServiceHandlers:
    @pytest.mark.asyncio
    async def test_recall_scene_calls_set_scene(self):
        router = _make_router(groups=(1,))
        hass, registered = _make_hass([router])
        _register_services(hass)

        handler, schema = registered[(DOMAIN, SERVICE_RECALL_SCENE)]
        call = Mock()
        call.data = schema({"group": 1, "block": 5, "scene": 7, "fade": 100})
        await handler(call)

        router.api.groups.set_scene.assert_called_once()
        address, fade = router.api.groups.set_scene.call_args[0]
        assert address == SceneAddress(1, 5, 7)
        assert fade == 100

    @pytest.mark.asyncio
    async def test_set_group_level_calls_library(self):
        router = _make_router(groups=(1,))
        hass, registered = _make_hass([router])
        _register_services(hass)

        handler, schema = registered[(DOMAIN, SERVICE_SET_GROUP_LEVEL)]
        call = Mock()
        call.data = schema({"group": 1, "level": 42})
        await handler(call)

        router.api.groups.set_group_level.assert_called_once_with(1, 42.0, 50)

    def test_registration_is_idempotent(self):
        hass, registered = _make_hass([_make_router()])
        _register_services(hass)
        assert len(registered) == 2

        hass.services.has_service = Mock(return_value=True)
        hass.services.async_register.reset_mock()
        _register_services(hass)
        hass.services.async_register.assert_not_called()
