#!/usr/bin/env python3
"""Read-only HelvarNet connection & capability check for the Helvar integration.

Run this on the machine that hosts Home Assistant (for example your Raspberry
Pi) to find out, in a few seconds, whether a Helvar router is reachable and
whether its firmware supports the queries this integration relies on. It is
strictly **read-only**: it only sends HelvarNet *query* commands and never
changes any device, group or scene.

Why this exists: older routers answer newer queries (such as device discovery,
``C:100``) with error code 15, "Invalid message command". When that happens the
integration can appear to hang or silently find no devices. This tool surfaces
that immediately, with a clear verdict, instead of leaving you guessing.

Usage::

    python3 tools/helvar_diagnose.py <router-host> [--port 50000]
                                     [--timeout 5] [--cluster N] [--router N]
                                     [--json]

Examples::

    python3 tools/helvar_diagnose.py 192.0.2.10
    python3 tools/helvar_diagnose.py 192.0.2.10 --json

The tool talks to the router directly over TCP, so it works with any installed
version of the aiohelvar library (and even if it isn't installed). If the
enhanced aiohelvar (>= 0.9.9) is present, its error-code descriptions are used;
otherwise a built-in copy is used.

To test this tool without a real router, start the mock router that ships with
aiohelvar >= 0.9.9 and point the tool at it::

    python -m aiohelvar mock --profile legacy --port 50000
    python3 tools/helvar_diagnose.py 127.0.0.1
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Mirrors custom_components/helvar/const.py DEFAULT_PORT. Kept as a literal so
# this script has no dependency on Home Assistant being importable.
DEFAULT_PORT = 50000
DEFAULT_TIMEOUT = 5.0
COMMAND_TERMINATOR = b"#"


# --- Error-code descriptions ---------------------------------------------
# A built-in copy of the HelvarNet error codes so this tool is fully standalone.
# Reference: HelvarNet Overview, "Error / Diagnostic Messages".
_FALLBACK_ERROR_CODES = {
    0: "Success",
    1: "Invalid group index parameter",
    2: "Invalid cluster parameter",
    3: "Invalid router index parameter",
    4: "Invalid subnet parameter",
    5: "Invalid device parameter",
    6: "Invalid sub device parameter",
    7: "Invalid block parameter",
    8: "Invalid scene parameter",
    9: "Cluster does not exist",
    10: "Router does not exist",
    11: "Device does not exist",
    12: "Property does not exist",
    13: "Invalid RAW message size",
    14: "Invalid message type",
    15: "Invalid message command",
    16: "Missing ASCII terminator",
    17: "Missing ASCII parameter",
    18: "Incompatible version",
}
# Codes meaning "the router does not understand this command" (old firmware).
_UNSUPPORTED_CODES = {14, 15, 18}


def _fallback_describe(code) -> str:
    try:
        numeric = int(code)
    except (ValueError, TypeError):
        return f"Unknown error code ({code!r})"
    return _FALLBACK_ERROR_CODES.get(numeric, f"Unknown error code ({numeric})")


def _fallback_is_unsupported(code) -> bool:
    try:
        return int(code) in _UNSUPPORTED_CODES
    except (ValueError, TypeError):
        return False


# Prefer the library's table (single source of truth) when a new enough
# aiohelvar is installed, so the tool and the library never disagree. Otherwise
# use the built-in copy above - the tool then works with any aiohelvar version.
try:
    from aiohelvar.error_codes import describe as _describe
    from aiohelvar.error_codes import is_unsupported_command as _is_unsupported
except Exception:  # noqa: BLE001 - any import problem falls back gracefully
    _describe = _fallback_describe
    _is_unsupported = _fallback_is_unsupported


# Command ids of the read-only queries we probe.
CMD_WORKGROUP = 107
CMD_ROUTER_VERSION = 190
CMD_HELVARNET_VERSION = 191
CMD_CLUSTERS = 101
CMD_GROUPS = 165
CMD_DEVICE_DISCOVERY = 100


def derive_cluster_router(host: str) -> Tuple[int, int]:
    """Derive (cluster, router) from an IPv4 host the way the integration does.

    The integration/aiohelvar default takes the cluster from the 3rd octet and
    the router from the 4th octet of the router's IPv4 address. We mirror that
    here so the device-discovery probe uses the *same* address the integration
    would, which also makes an address mismatch visible in the report. Falls
    back to (0, 1) for hostnames or non-IPv4 inputs.

    Per the Designer 5 Quick Start Guide (section 3.4), this 3rd/4th-octet split
    only holds for the Helvar default cluster mask 255.255.255.0 with the usual
    10.254.C.R layout. If the router is reached on an unrelated network (e.g.
    via a bridge on 192.168.x.y), the derived ids will be wrong - pass
    --cluster/--router explicitly. (The HelvarNet port is 50000; 60005 is the
    separate inter-router "cluster comms" port, not this one.)
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return 0, 1
    if isinstance(ip, ipaddress.IPv4Address):
        octets = str(ip).split(".")
        return int(octets[2]), int(octets[3])
    return 0, 1


def build_probe_plan(cluster: int, router: int) -> List[Tuple[str, str, int]]:
    """Return the read-only probe plan as (label, command_string, command_id)."""
    # A syntactically valid address for the discovery probe. The exact value
    # doesn't affect capability detection (error 15 => unsupported, anything
    # else => supported); we use the integration's derived address for realism.
    probe_router = router if 1 <= router <= 254 else 1
    probe_cluster = cluster if 0 <= cluster <= 253 else 0
    discovery_addr = f"@{probe_cluster}.{probe_router}.1"
    return [
        ("Workgroup name", ">V:2,C:107#", CMD_WORKGROUP),
        ("Router version", ">V:2,C:190#", CMD_ROUTER_VERSION),
        ("HelvarNet version", ">V:2,C:191#", CMD_HELVARNET_VERSION),
        ("Clusters", ">V:2,C:101#", CMD_CLUSTERS),
        ("Groups", ">V:2,C:165#", CMD_GROUPS),
        ("Device discovery", f">V:2,C:100,{discovery_addr}#", CMD_DEVICE_DISCOVERY),
    ]


def parse_reply(raw: str) -> Tuple[str, Optional[str]]:
    """Parse a raw HelvarNet reply into (message_type_char, result_or_None).

    Reply examples:
        ?V:2,C:190=5.4.2#   -> ("?", "5.4.2")
        !V:2,C:100,@0.1.1=15# -> ("!", "15")
    """
    raw = raw.strip()
    if not raw:
        return "", None
    message_type = raw[0]
    result: Optional[str] = None
    if "=" in raw:
        result = raw.split("=", 1)[1]
        if result.endswith("#"):
            result = result[:-1]
    return message_type, result


@dataclass
class ProbeOutcome:
    label: str
    command_id: int
    status: str  # "OK" | "ERROR" | "TIMEOUT"
    detail: str = ""
    result: Optional[str] = None
    error_code: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "label": self.label,
            "command_id": self.command_id,
            "status": self.status,
            "detail": self.detail,
            "result": self.result,
            "error_code": self.error_code,
        }


@dataclass
class Report:
    host: str
    port: int
    cluster: int
    router: int
    reachable: bool = False
    connect_error: Optional[str] = None
    probes: List[ProbeOutcome] = field(default_factory=list)

    def get(self, command_id: int) -> Optional[ProbeOutcome]:
        for probe in self.probes:
            if probe.command_id == command_id:
                return probe
        return None

    def supports(self, command_id: int) -> Optional[bool]:
        probe = self.get(command_id)
        if probe is None:
            return None
        if probe.status == "OK":
            return True
        if probe.status == "ERROR":
            return not _is_unsupported(probe.error_code)
        return None  # TIMEOUT

    def verdict(self) -> Tuple[str, str]:
        if not self.reachable:
            detail = f" ({self.connect_error})" if self.connect_error else ""
            return (
                "error",
                f"Could not open a TCP connection to {self.host}:{self.port}{detail}. "
                "Check the host/port and that HelvarNet/TCP is enabled on the router.",
            )
        discovery = self.get(CMD_DEVICE_DISCOVERY)
        if (
            discovery is not None
            and discovery.status == "ERROR"
            and _is_unsupported(discovery.error_code)
        ):
            return (
                "warning",
                "Router reachable, but device discovery (query C:100) is not supported "
                f"by this firmware (error {discovery.error_code}: "
                f"{_describe(discovery.error_code)}). The integration relies on device "
                "discovery to enumerate lights, so it will not find any devices on this "
                "firmware. This is a firmware capability limit, not a wiring or network "
                "problem.",
            )
        if self.supports(CMD_DEVICE_DISCOVERY) is None:
            return (
                "warning",
                "Router reachable, but device discovery (query C:100) did not respond "
                "within the timeout.",
            )
        if discovery is not None and discovery.status == "ERROR":
            return (
                "warning",
                "Router reachable and it understands device discovery, but the probe "
                f"at {self._discovery_address()} returned error {discovery.error_code}: "
                f"{_describe(discovery.error_code)}. This usually means the "
                "cluster/router address does not match this router.",
            )
        return (
            "ok",
            "Router reachable and responds to device discovery. This router looks "
            "compatible with the integration.",
        )

    def _discovery_address(self) -> str:
        return f"@{self.cluster}.{self.router}.1"

    def to_dict(self) -> Dict:
        level, message = self.verdict()
        return {
            "host": self.host,
            "port": self.port,
            "cluster": self.cluster,
            "router": self.router,
            "reachable": self.reachable,
            "connect_error": self.connect_error,
            "supports_device_discovery": self.supports(CMD_DEVICE_DISCOVERY),
            "verdict": {"level": level, "message": message},
            "probes": [p.to_dict() for p in self.probes],
        }

    def to_text(self) -> str:
        lines = []
        title = f"HelvarNet diagnostics for {self.host}:{self.port}"
        lines.append(title)
        lines.append("=" * len(title))
        lines.append(f"{'TCP connection':<20}: {'OK' if self.reachable else 'FAILED'}")
        if self.reachable:
            lines.append(
                f"{'Probe address':<20}: {self._discovery_address()} "
                f"(cluster {self.cluster}, router {self.router})"
            )
            for probe in self.probes:
                if probe.status == "OK":
                    suffix = f"-> {probe.result}"
                else:
                    suffix = f"-> {probe.detail}" if probe.detail else ""
                lines.append(f"{probe.label:<20}: {probe.status:<7} {suffix}".rstrip())
        elif self.connect_error:
            lines.append(f"{'Error':<20}: {self.connect_error}")
        level, message = self.verdict()
        lines.append("")
        lines.append(f"Verdict: {level.upper()} - {message}")
        return "\n".join(lines)


class RawHelvarClient:
    """A tiny, read-only HelvarNet TCP client: open, query sequentially, close."""

    def __init__(self, host: str, port: int, timeout: float):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def __aenter__(self) -> "RawHelvarClient":
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.timeout
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (OSError, asyncio.TimeoutError):  # pragma: no cover - best effort
                pass

    async def query(self, command: str) -> str:
        """Send one command and return its raw reply. Bounded by the timeout."""
        assert self._writer is not None and self._reader is not None
        self._writer.write(command.encode("utf-8"))
        await self._writer.drain()
        raw = await asyncio.wait_for(
            self._reader.readuntil(COMMAND_TERMINATOR), self.timeout
        )
        return raw.decode("utf-8", errors="replace")


async def run_probes(
    host: str,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    cluster: Optional[int] = None,
    router: Optional[int] = None,
    client_factory=RawHelvarClient,
) -> Report:
    """Run the read-only probe plan and return a Report. Never sends writes."""
    if cluster is None or router is None:
        derived_cluster, derived_router = derive_cluster_router(host)
        cluster = derived_cluster if cluster is None else cluster
        router = derived_router if router is None else router

    report = Report(host=host, port=port, cluster=cluster, router=router)

    try:
        client = client_factory(host, port, timeout)
        async with client:
            report.reachable = True
            for label, command, command_id in build_probe_plan(cluster, router):
                try:
                    raw = await client.query(command)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    report.probes.append(
                        ProbeOutcome(
                            label, command_id, "TIMEOUT", f"no response within {timeout}s"
                        )
                    )
                    continue
                except Exception as err:  # noqa: BLE001 - report, don't crash
                    report.probes.append(
                        ProbeOutcome(label, command_id, "ERROR", f"exception: {err}")
                    )
                    continue

                message_type, result = parse_reply(raw)
                if message_type == "!":
                    try:
                        code = int(result) if result is not None else None
                    except (ValueError, TypeError):
                        code = None
                    report.probes.append(
                        ProbeOutcome(
                            label,
                            command_id,
                            "ERROR",
                            f"error {result}: {_describe(result)}",
                            result,
                            code,
                        )
                    )
                else:
                    report.probes.append(
                        ProbeOutcome(label, command_id, "OK", str(result), result)
                    )
    except (OSError, asyncio.TimeoutError) as err:
        report.reachable = False
        report.connect_error = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__

    return report


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only HelvarNet connection & capability check.",
    )
    parser.add_argument("host", help="router hostname or IP address")
    parser.add_argument(
        "-p", "--port", type=int, default=DEFAULT_PORT, help=f"TCP port (default {DEFAULT_PORT})"
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=DEFAULT_TIMEOUT, help="per-query timeout in seconds"
    )
    parser.add_argument(
        "--cluster",
        type=int,
        default=None,
        help="cluster id for the discovery probe (default: 3rd IP octet; set this "
        "if the router isn't on a standard 10.254.C.R / 255.255.255.0 network)",
    )
    parser.add_argument(
        "--router",
        type=int,
        default=None,
        help="router id for the discovery probe (default: 4th IP octet)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    report = asyncio.run(
        run_probes(
            args.host,
            args.port,
            timeout=args.timeout,
            cluster=args.cluster,
            router=args.router,
        )
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_text())
    level, _ = report.verdict()
    return 0 if level == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
