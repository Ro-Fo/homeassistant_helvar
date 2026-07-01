"""Tests for the Helvar config flow, including the optional cluster/router ids."""
import inspect

import aiohelvar
import pytest
import voluptuous as vol
from unittest.mock import AsyncMock, Mock, patch

from custom_components.helvar.config_flow import ConfigFlow, STEP_USER_DATA_SCHEMA
from custom_components.helvar.const import (
    CONF_CLUSTER_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_ROUTER_ID,
)
from custom_components.helvar.router import build_router

# The explicit-ids path only works with an aiohelvar that supports it; the tool
# degrades gracefully otherwise, so gate that one assertion on availability.
_SUPPORTS_IDS = "use_specified_ids" in inspect.signature(
    aiohelvar.Router.__init__
).parameters


class TestBuildRouter:
    """build_router() bridges the config entry to aiohelvar.Router."""

    def test_derives_ids_from_ip_when_absent(self):
        # Standard 10.254.C.R layout: cluster = 3rd octet, router = 4th octet.
        router = build_router("10.254.1.2", 50000)
        assert router.cluster_id == 1
        assert router.router_id == 2

    @pytest.mark.skipif(
        not _SUPPORTS_IDS, reason="installed aiohelvar lacks use_specified_ids"
    )
    def test_explicit_ids_override_ip_derivation(self):
        # A router reached via a bridge on 192.168.178.48 would otherwise derive
        # cluster 178 / router 48; explicit ids must win.
        router = build_router("192.168.178.48", 50000, cluster_id=1, router_id=2)
        assert router.cluster_id == 1
        assert router.router_id == 2

    def test_partial_ids_are_ignored(self):
        # Only one id given -> fall back to IP derivation (both or nothing).
        router = build_router("10.254.5.6", 50000, cluster_id=9, router_id=None)
        assert router.cluster_id == 5
        assert router.router_id == 6


class TestSchema:
    def test_accepts_optional_ids(self):
        data = STEP_USER_DATA_SCHEMA(
            {CONF_HOST: "10.0.0.1", CONF_CLUSTER_ID: 1, CONF_ROUTER_ID: 2}
        )
        assert data[CONF_CLUSTER_ID] == 1
        assert data[CONF_ROUTER_ID] == 2

    def test_ids_are_optional(self):
        data = STEP_USER_DATA_SCHEMA({CONF_HOST: "10.0.0.1"})
        assert CONF_CLUSTER_ID not in data
        assert CONF_ROUTER_ID not in data

    def test_rejects_out_of_range_router(self):
        with pytest.raises(vol.Invalid):
            STEP_USER_DATA_SCHEMA({CONF_HOST: "10.0.0.1", CONF_ROUTER_ID: 999})


class TestValidateInput:
    @pytest.mark.asyncio
    async def test_passes_ids_to_build_router(self):
        flow = ConfigFlow()
        with patch(
            "custom_components.helvar.config_flow.build_router"
        ) as mock_build:
            mock_router = Mock()
            mock_router.connect = AsyncMock()
            mock_router.workgroup_name = "MyWorkgroup"
            mock_build.return_value = mock_router

            info = await flow.validate_input(
                Mock(),
                {
                    CONF_HOST: "192.168.178.48",
                    CONF_PORT: 50000,
                    CONF_CLUSTER_ID: 1,
                    CONF_ROUTER_ID: 2,
                },
            )

            assert info["title"] == "MyWorkgroup"
            mock_build.assert_called_once_with(
                "192.168.178.48", 50000, cluster_id=1, router_id=2
            )
            mock_router.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ids_default_to_none(self):
        flow = ConfigFlow()
        with patch(
            "custom_components.helvar.config_flow.build_router"
        ) as mock_build:
            mock_router = Mock()
            mock_router.connect = AsyncMock()
            mock_router.workgroup_name = "WG"
            mock_build.return_value = mock_router

            await flow.validate_input(Mock(), {CONF_HOST: "10.254.1.1", CONF_PORT: 50000})

            mock_build.assert_called_once_with(
                "10.254.1.1", 50000, cluster_id=None, router_id=None
            )
