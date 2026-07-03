"""Tests for the Helvar config and options flows."""
import pytest
from unittest.mock import AsyncMock, Mock, patch

import voluptuous as vol

from custom_components.helvar.config_flow import (
    ConfigFlow,
    OptionsFlowHandler,
    format_mapping_lines,
    parse_off_scene_lines,
    parse_scene_name_lines,
)
from custom_components.helvar.const import (
    CONF_CLUSTER_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_ROUTER_ID,
    OPT_OFF_SCENES,
    OPT_SCENE_NAMES,
)
from custom_components.helvar.router import create_router


class TestParseSceneNameLines:
    """Parsing of the options-flow scene display-name text."""

    def test_parses_lines(self):
        text = "1.1.3 = Dinner\n2.1.1 = Hall bright\n"
        assert parse_scene_name_lines(text) == {
            "1.1.3": "Dinner",
            "2.1.1": "Hall bright",
        }

    def test_names_may_contain_separators(self):
        assert parse_scene_name_lines("1.1.1 = A = B: C") == {"1.1.1": "A = B: C"}

    def test_skips_blank_lines_and_comments(self):
        text = "\n# comment\n1.1.1 = Day\n   \n"
        assert parse_scene_name_lines(text) == {"1.1.1": "Day"}

    def test_empty_and_none(self):
        assert parse_scene_name_lines(None) == {}
        assert parse_scene_name_lines("") == {}

    @pytest.mark.parametrize(
        "bad",
        [
            "1.1.1",  # no separator
            "1.1 = name",  # not g.b.s
            "a.b.c = name",  # non-numeric
            "1.999.1 = name",  # block out of range
            "1.1.17 = name",  # scene out of range
            "1.1.1 =",  # empty name
        ],
    )
    def test_invalid_lines_raise(self, bad):
        with pytest.raises(vol.Invalid):
            parse_scene_name_lines(bad)


class TestParseOffSceneLines:
    """Parsing of the options-flow per-group off-scene text."""

    def test_parses_lines(self):
        assert parse_off_scene_lines("1 = 1.15\n2 = 1.16") == {
            "1": "1.15",
            "2": "1.16",
        }

    @pytest.mark.parametrize(
        "bad",
        ["1", "1 = 15", "x = 1.15", "1 = 1.99", "1 = a.b"],
    )
    def test_invalid_lines_raise(self, bad):
        with pytest.raises(vol.Invalid):
            parse_off_scene_lines(bad)


def test_format_mapping_lines_round_trips():
    mapping = {"1.1.3": "Dinner", "1.1.1": "Day"}
    text = format_mapping_lines(mapping)
    assert text == "1.1.1 = Day\n1.1.3 = Dinner"
    assert parse_scene_name_lines(text) == mapping
    assert format_mapping_lines(None) == ""
    assert format_mapping_lines({}) == ""


class TestCreateRouter:
    """create_router maps optional cluster/router ids to use_specified_ids."""

    def test_defaults_to_runtime_discovery(self):
        with patch("custom_components.helvar.router.aiohelvar.Router") as mock_router:
            create_router({CONF_HOST: "192.0.2.1", CONF_PORT: 50000})
            mock_router.assert_called_once_with("192.0.2.1", 50000)

    def test_specified_ids_are_forced(self):
        with patch("custom_components.helvar.router.aiohelvar.Router") as mock_router:
            create_router(
                {
                    CONF_HOST: "192.0.2.1",
                    CONF_PORT: 50000,
                    CONF_CLUSTER_ID: 0,
                    CONF_ROUTER_ID: 1,
                }
            )
            mock_router.assert_called_once_with(
                "192.0.2.1", 50000, cluster_id=0, router_id=1, use_specified_ids=True
            )

    def test_port_defaults_to_50000(self):
        with patch("custom_components.helvar.router.aiohelvar.Router") as mock_router:
            create_router({CONF_HOST: "192.0.2.1"})
            mock_router.assert_called_once_with("192.0.2.1", 50000)


class TestConfigFlow:
    """The user step of the config flow."""

    @pytest.mark.asyncio
    async def test_cluster_without_router_id_errors(self):
        flow = ConfigFlow()
        flow.hass = Mock()

        result = await flow.async_step_user(
            {CONF_HOST: "192.0.2.1", CONF_PORT: 50000, CONF_CLUSTER_ID: 0}
        )

        assert result["type"] == "form"
        assert result["errors"] == {"base": "cluster_router_pair"}

    @pytest.mark.asyncio
    async def test_successful_flow_creates_entry(self):
        flow = ConfigFlow()
        flow.hass = Mock()

        mock_router = Mock()
        mock_router.connect = AsyncMock()
        mock_router.disconnect = AsyncMock()
        mock_router.workgroup_name = "TestWorkgroup"

        with patch(
            "custom_components.helvar.config_flow.create_router",
            return_value=mock_router,
        ):
            result = await flow.async_step_user(
                {CONF_HOST: "192.0.2.1", CONF_PORT: 50000}
            )

        assert result["type"] == "create_entry"
        assert result["title"] == "TestWorkgroup"
        assert result["data"] == {CONF_HOST: "192.0.2.1", CONF_PORT: 50000}
        mock_router.connect.assert_called_once()
        mock_router.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_failure_shows_error(self):
        flow = ConfigFlow()
        flow.hass = Mock()

        mock_router = Mock()
        mock_router.connect = AsyncMock(side_effect=ConnectionError("nope"))

        with patch(
            "custom_components.helvar.config_flow.create_router",
            return_value=mock_router,
        ):
            result = await flow.async_step_user(
                {CONF_HOST: "192.0.2.1", CONF_PORT: 50000}
            )

        assert result["type"] == "form"
        assert result["errors"] == {"base": "cannot_connect"}


class TestOptionsFlow:
    """The options flow storing scene-name overrides and off scenes."""

    def _flow(self, options=None):
        entry = Mock()
        entry.options = options or {}
        return OptionsFlowHandler(entry)

    @pytest.mark.asyncio
    async def test_shows_form_initially(self):
        flow = self._flow()
        result = await flow.async_step_init(None)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_valid_input_creates_entry_with_parsed_mappings(self):
        flow = self._flow()
        result = await flow.async_step_init(
            {OPT_SCENE_NAMES: "1.1.3 = Dinner", OPT_OFF_SCENES: "1 = 1.15"}
        )

        assert result["type"] == "create_entry"
        assert result["data"] == {
            OPT_SCENE_NAMES: {"1.1.3": "Dinner"},
            OPT_OFF_SCENES: {"1": "1.15"},
        }

    @pytest.mark.asyncio
    async def test_invalid_input_shows_error(self):
        flow = self._flow()
        result = await flow.async_step_init({OPT_SCENE_NAMES: "not valid"})

        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_options"}

    @pytest.mark.asyncio
    async def test_existing_options_prefill_the_form(self):
        flow = self._flow(
            {OPT_SCENE_NAMES: {"1.1.3": "Dinner"}, OPT_OFF_SCENES: {"1": "1.15"}}
        )
        result = await flow.async_step_init(None)
        assert result["type"] == "form"
        # The stored mappings are rendered back into the text fields.
        schema_keys = {key.schema: key for key in result["data_schema"].schema}
        assert schema_keys[OPT_SCENE_NAMES].description == {
            "suggested_value": "1.1.3 = Dinner"
        }
        assert schema_keys[OPT_OFF_SCENES].description == {
            "suggested_value": "1 = 1.15"
        }
