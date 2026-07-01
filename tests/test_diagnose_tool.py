"""Tests for the read-only diagnostics tool (tools/helvar_diagnose.py).

The tool is standalone (no Home Assistant, no specific aiohelvar version), so
these tests import it directly from the file and exercise it with an injected
fake client, plus one real localhost socket round-trip.
"""

import asyncio
import importlib.util
import pathlib
import sys

import pytest

# Import the standalone tool from tools/ without polluting sys.path. The module
# is registered in sys.modules before execution so that dataclasses defined
# under `from __future__ import annotations` can resolve their own module.
_TOOL_PATH = pathlib.Path(__file__).resolve().parent.parent / "tools" / "helvar_diagnose.py"
_spec = importlib.util.spec_from_file_location("helvar_diagnose", _TOOL_PATH)
diag = importlib.util.module_from_spec(_spec)
sys.modules["helvar_diagnose"] = diag
_spec.loader.exec_module(diag)


# Synthetic replies keyed by command id (no real device data).
MODERN_REPLIES = {
    107: "?V:2,C:107=MockWorkgroup#",
    190: "?V:2,C:190=5.4.2#",
    191: "?V:2,C:191=2#",
    101: "?V:2,C:101=1#",
    165: "?V:2,C:165=1,2#",
    100: "?V:2,C:100,@0.1.1=1@1,1@2#",
}
LEGACY_REPLIES = {
    107: "!V:2,C:107=15#",
    190: "?V:2,C:190=2.3.1#",
    191: "?V:2,C:191=1#",
    101: "?V:2,C:101=1#",
    165: "!V:2,C:165=15#",
    100: "!V:2,C:100,@0.1.1=15#",
}


def _command_id(command: str) -> int:
    # ">V:2,C:107#" or ">V:2,C:100,@0.1.1#" -> 107 / 100
    body = command.split("C:", 1)[1]
    digits = ""
    for ch in body:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits)


def make_client_factory(replies, timeout_ids=frozenset(), connect_error=None):
    """Build a fake client_factory compatible with run_probes()."""

    class _FakeClient:
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port

        async def __aenter__(self):
            if connect_error is not None:
                raise connect_error
            return self

        async def __aexit__(self, *exc):
            return None

        async def query(self, command):
            cid = _command_id(command)
            if cid in timeout_ids:
                raise asyncio.TimeoutError()
            return replies[cid]

    return _FakeClient


# --- pure helpers ---------------------------------------------------------


class TestPureHelpers:
    def test_parse_reply_ok(self):
        assert diag.parse_reply("?V:2,C:190=5.4.2#") == ("?", "5.4.2")

    def test_parse_reply_error(self):
        assert diag.parse_reply("!V:2,C:100,@0.1.1=15#") == ("!", "15")

    def test_parse_reply_no_result(self):
        assert diag.parse_reply("?V:2,C:107=#") == ("?", "")

    def test_derive_cluster_router_from_ipv4(self):
        assert diag.derive_cluster_router("192.168.10.20") == (10, 20)

    def test_derive_cluster_router_hostname_fallback(self):
        assert diag.derive_cluster_router("router.local") == (0, 1)

    def test_build_probe_plan_uses_address(self):
        plan = diag.build_probe_plan(2, 3)
        discovery = [p for p in plan if p[2] == diag.CMD_DEVICE_DISCOVERY][0]
        assert "@2.3.1" in discovery[1]
        # every probe is a read-only query command
        assert all(cmd.startswith(">V:2,C:") for _, cmd, _ in plan)

    def test_fallback_describe(self):
        assert diag._fallback_describe(15) == "Invalid message command"
        assert diag._fallback_describe("15") == "Invalid message command"
        assert "Unknown error code" in diag._fallback_describe(999)

    def test_fallback_is_unsupported(self):
        assert diag._fallback_is_unsupported(15) is True
        assert diag._fallback_is_unsupported(9) is False

    def test_active_describe_matches(self):
        # Whether backed by the library or the fallback, code 15 is stable.
        assert diag._describe(15) == "Invalid message command"


# --- run_probes with an injected fake client ------------------------------


class TestRunProbes:
    pytestmark = pytest.mark.asyncio

    async def test_modern_router_ok(self):
        factory = make_client_factory(MODERN_REPLIES)
        report = await diag.run_probes(
            "192.0.2.10", 50000, timeout=1.0, client_factory=factory
        )
        assert report.reachable is True
        assert report.get(diag.CMD_WORKGROUP).result == "MockWorkgroup"
        assert report.get(diag.CMD_ROUTER_VERSION).result == "5.4.2"
        assert report.supports(diag.CMD_DEVICE_DISCOVERY) is True
        assert report.verdict()[0] == "ok"

    async def test_legacy_router_flags_error_15(self):
        factory = make_client_factory(LEGACY_REPLIES)
        report = await diag.run_probes(
            "192.0.2.10", 50000, timeout=1.0, client_factory=factory
        )
        assert report.reachable is True
        assert report.get(diag.CMD_ROUTER_VERSION).result == "2.3.1"
        discovery = report.get(diag.CMD_DEVICE_DISCOVERY)
        assert discovery.status == "ERROR"
        assert discovery.error_code == 15
        assert "Invalid message command" in discovery.detail
        assert report.supports(diag.CMD_DEVICE_DISCOVERY) is False
        level, message = report.verdict()
        assert level == "warning"
        assert "device discovery" in message

    async def test_timeout_is_reported_not_hung(self):
        factory = make_client_factory(MODERN_REPLIES, timeout_ids={diag.CMD_DEVICE_DISCOVERY})
        report = await asyncio.wait_for(
            diag.run_probes("192.0.2.10", 50000, timeout=0.2, client_factory=factory),
            timeout=5.0,
        )
        assert report.get(diag.CMD_DEVICE_DISCOVERY).status == "TIMEOUT"
        assert report.supports(diag.CMD_DEVICE_DISCOVERY) is None
        assert report.verdict()[0] == "warning"

    async def test_unreachable_router(self):
        factory = make_client_factory(
            MODERN_REPLIES, connect_error=ConnectionRefusedError("refused")
        )
        report = await diag.run_probes(
            "192.0.2.10", 50000, timeout=0.5, client_factory=factory
        )
        assert report.reachable is False
        assert report.connect_error is not None
        assert report.verdict()[0] == "error"

    async def test_report_text_and_json_render(self):
        factory = make_client_factory(LEGACY_REPLIES)
        report = await diag.run_probes(
            "192.0.2.10", 50000, timeout=1.0, client_factory=factory
        )
        text = report.to_text()
        assert "HelvarNet diagnostics for 192.0.2.10:50000" in text
        assert "Verdict: WARNING" in text
        data = report.to_dict()
        assert data["supports_device_discovery"] is False
        assert data["verdict"]["level"] == "warning"


# --- one real localhost socket round-trip --------------------------------


class TestRealSocket:
    pytestmark = pytest.mark.asyncio

    async def _serve(self, replies):
        async def handle(reader, writer):
            try:
                while True:
                    try:
                        line = await reader.readuntil(b"#")
                    except asyncio.IncompleteReadError:
                        break
                    cid = _command_id(line.decode())
                    writer.write(replies.get(cid, f"?V:2,C:{cid}=#").encode())
                    await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        return server, port

    async def test_against_real_legacy_socket(self):
        server, port = await self._serve(LEGACY_REPLIES)
        try:
            report = await diag.run_probes("127.0.0.1", port, timeout=2.0)
        finally:
            server.close()
            await server.wait_closed()

        assert report.reachable is True
        assert report.supports(diag.CMD_DEVICE_DISCOVERY) is False
        assert report.get(diag.CMD_DEVICE_DISCOVERY).error_code == 15
        assert report.verdict()[0] == "warning"
