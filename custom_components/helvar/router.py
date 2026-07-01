"""Helvar Router."""
import inspect
import logging

import aiohelvar

from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_CLUSTER_ID, CONF_HOST, CONF_PORT, CONF_ROUTER_ID

_LOGGER = logging.getLogger(__name__)


def build_router(host, port, cluster_id=None, router_id=None):
    """Create an aiohelvar.Router, using explicit cluster/router ids when given.

    By default aiohelvar derives the HelvarNet cluster/router from the router's
    IP (3rd/4th octet), which only holds for the standard 10.254.C.R layout with
    cluster mask 255.255.255.0. When both ids are provided (e.g. the router is
    reached via a bridge on an unrelated network), they are passed through
    explicitly. Degrades gracefully if the installed aiohelvar predates the
    use_specified_ids parameter.
    """
    if cluster_id is not None and router_id is not None:
        try:
            supports_ids = "use_specified_ids" in inspect.signature(
                aiohelvar.Router.__init__
            ).parameters
        except (TypeError, ValueError):
            supports_ids = False
        if supports_ids:
            return aiohelvar.Router(
                host,
                port,
                cluster_id=cluster_id,
                router_id=router_id,
                use_specified_ids=True,
            )
        _LOGGER.warning(
            "Installed aiohelvar does not support explicit cluster/router ids; "
            "deriving them from the IP address instead."
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
        """Return the host of this router."""
        return self.config_entry.data[CONF_PORT]

    @property
    def cluster_id(self):
        """Return the explicitly configured cluster id, or None to derive it."""
        return self.config_entry.data.get(CONF_CLUSTER_ID)

    @property
    def router_id(self):
        """Return the explicitly configured router id, or None to derive it."""
        return self.config_entry.data.get(CONF_ROUTER_ID)

    async def async_setup(self, tries=0):
        """Set up a helvar router based on host parameter."""
        host = self.host
        port = self.port
        hass = self.hass

        router = build_router(host, port, self.cluster_id, self.router_id)

        try:
            await router.connect()
            await router.initialize()

        except ConnectionError as err:
            _LOGGER.error("Error connecting to the Helvar router at %s", host)
            raise ConfigEntryNotReady from err

        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unknown error connecting with Helvar router at %s", host)
            return False

        self.api = router
        # self.sensor_manager = SensorManager(self)

        hass.async_create_task(
            hass.config_entries.async_forward_entry_setups(self.config_entry, ["light"]),
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setups(self.config_entry, ["select"]),
        )

        return True
