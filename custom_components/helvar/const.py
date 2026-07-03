"""Constants for the HelvarNet integration."""

DOMAIN = "helvar"

CONF_HOST = "host"
CONF_PORT = "port"
# Optional advanced settings; when both are set they are passed to aiohelvar
# with use_specified_ids=True. Left empty, the library discovers the real
# cluster/router ids from the router at runtime (C:101/C:102).
CONF_CLUSTER_ID = "cluster_id"
CONF_ROUTER_ID = "router_id"

DEFAULT_PORT = 50000

# Config entry options (managed by the options flow, never stored in the
# repository): per-scene display name overrides and per-group "Off" scenes.
OPT_SCENE_NAMES = "scene_names"  # {"<group>.<block>.<scene>": "Friendly name"}
OPT_OFF_SCENES = "off_scenes"  # {"<group>": "<block>.<scene>"}

# The explicit "Off" entry appended to every group's scene select.
OFF_OPTION = "Off"

# HelvarNet fade times are in units of 1/100 s (50 == 0.5 s).
DEFAULT_FADE_TIME = 50

SERVICE_RECALL_SCENE = "recall_scene"
SERVICE_SET_GROUP_LEVEL = "set_group_level"

ATTR_GROUP = "group"
ATTR_BLOCK = "block"
ATTR_SCENE = "scene"
ATTR_LEVEL = "level"
ATTR_FADE = "fade"

DEFAULT_ON_GROUP_SCENE = 1
DEFAULT_ON_GROUP_BLOCK = 1
DEFAULT_OFF_GROUP_BLOCK = 1
DEFAULT_OFF_GROUP_SCENE = 15
VALID_OFF_GROUP_SCENES = (15, 16)
