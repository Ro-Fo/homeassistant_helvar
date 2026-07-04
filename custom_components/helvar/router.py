"""Helvar Router."""
import asyncio
import logging

import aiohelvar
from aiohelvar.exceptions import CommandResponseTimeout

from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_CLUSTER_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_ROUTER_ID,
    DEFAULT_PORT,
)

_LOGGER = logging.getLogger(__name__)


def create_router(data):
    """Create an aiohelvar Router from config entry data.

    When both cluster_id and router_id are configured they are forced with
    use_specified_ids=True; otherwise aiohelvar discovers the real ids from
    the router at runtime (C:101/C:102).
    """
    host = data[CONF_HOST]
    port = data.get(CONF_PORT, DEFAULT_PORT)
    cluster_id = data.get(CONF_CLUSTER_ID)
    router_id = data.get(CONF_ROUTER_ID)

    if cluster_id is not None and router_id is not None:
        return aiohelvar.Router(
            host,
            port,
            cluster_id=int(cluster_id),
            router_id=int(router_id),
            use_specified_ids=True,
        )
    return aiohelvar.Router(host, port)


class HelvarRouter:
    """Manages a Helvar Router."""

    def __init__(self, hass, config_entry):
        """Initialize the system."""
        self.config_entry = config_entry
        self.hass = hass
        self.available = True
        self.api = None

    @property
    def host(self):
        """Return the host of this router."""
        return self.config_entry.data[CONF_HOST]

    @property
    def port(self):
        """Return the port of this router."""
        return self.config_entry.data.get(CONF_PORT, DEFAULT_PORT)

    async def async_setup(self, tries=0):
        """Set up a helvar router based on host parameter."""
        host = self.host
        hass = self.hass

        router = create_router(self.config_entry.data)

        try:
            await router.connect()
            await router.initialize()

        except (
            ConnectionError,
            OSError,
            asyncio.TimeoutError,
            CommandResponseTimeout,
        ) as err:
            # Router unreachable or not answering right now (e.g. HA
            # restarted before the network is up, the router is rebooting,
            # or it is too busy to answer a start-up query in time). Raising
            # ConfigEntryNotReady makes HA retry the setup with backoff.
            _LOGGER.error(
                "Error connecting to the Helvar router at %s: %r", host, err
            )
            try:
                await router.disconnect()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Error disconnecting after failed setup", exc_info=True)
            raise ConfigEntryNotReady from err

        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unknown error connecting with Helvar router at %s", host)
            return False

        self.api = router
        # Once connected, aiohelvar keeps the TCP session alive itself
        # (keepalive queries + automatic reconnect), so entities created below
        # survive router reconnects; they report unavailable via the shared
        # `router.api.connected` flag while the link is down.

        hass.async_create_task(
            hass.config_entries.async_forward_entry_setups(self.config_entry, ["light"]),
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setups(self.config_entry, ["select"]),
        )

        return True
