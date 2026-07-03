# homeassistant helvar

This is a simple Home Assistant Integration for Helvar Lighting Systems.  Specifically the 9XX series Routers. 

All the heavy lifting is done by the [aiohelvar](https://github.com/Ro-Fo/aiohelvar) library (this fork tracks the [Ro-Fo/aiohelvar](https://github.com/Ro-Fo/aiohelvar) fork, which adds runtime cluster/router discovery so the router can live on any LAN addressing, not just the Helvar `10.254.c.r` convention).

## Features

You can control:
 - Individual lights (on DALI, DMX and SBUS)
   - Dimming, dimming over time
 - Groups
   - Setting scenes
     - Dimming between scenes, dimming over time
   - Unnamed scenes are selectable too: scenes that are in use but have no
     router-stored name get a generated name like `Scene 1.7`, and you can
     override any scene's display name per scene address in the integration
     options (so your local names never need to live in a repository)
   - An explicit **Off** entry per group: it recalls a per-group off scene if
     you configured one in the options, and otherwise forces the whole group
     to level 0 with a direct group level command (which also turns off
     channels whose scene table says `*` / "ignore scene command")
 - Services for automations and scripts:
   - `helvar.recall_scene` - fields: `group` (required), `block` (default 1),
     `scene` (required), `fade` (default 50, HelvarNet 1/100 s units)
   - `helvar.set_group_level` - fields: `group` (required), `level` 0-100
     (required), `fade` (default 50)

The integration will receive push notifications (if you enable them on the router) about scene changes from the router. These are fed back to the entities state, so things show the current levels. Updates from individual devices are not sent by the router. 

The TCP session to the router is kept alive by the library (keepalive +
automatic reconnect); entities survive router reconnects and simply show as
unavailable while the connection is down. If the router is unreachable when
Home Assistant starts, the integration reports "not ready" and Home Assistant
retries the setup automatically.

For general use, this should cover most needs.

## Installation

1. Install [HACS](https://hacs.xyz/).
2. HACS -> menu -> *Custom repositories* -> add
   `Ro-Fo/homeassistant_helvar` with category *Integration*.
3. Install the "Helvar" integration from HACS and restart Home Assistant.

## Usage

Add the integration (Settings -> Devices & Services -> Add Integration ->
"HelvarNet") and you'll be prompted for:

- **Host**: the router's IP address
- **Port**: TCP port of the HelvarNet API (default `50000`)
- **Cluster id / Router id** (advanced, optional): leave both empty - the
  integration discovers the real cluster/router ids from the router at
  runtime. Only set both if you need to force specific ids (e.g. an unusual
  multi-router setup).

The integration will then pull all lighting devices, groups and scenes. 

- The lighting devices will be added as light entities.
- The groups will be added as select entities, and you'll be able to select from the group's available scenes (plus **Off**).

### Scene display names & off scenes (options)

Open the integration's *Configure* dialog to set:

- **Scene display names**: one per line, `group.block.scene = Friendly name`,
  e.g. `1.1.3 = Dinner`. These override the router-stored (or generated)
  names in the scene selects. They are stored in the config entry options in
  your Home Assistant configuration - not in this repository.
- **Off scene per group**: one per line, `group = block.scene`, e.g.
  `1 = 1.15`. Selecting **Off** in that group recalls this scene; groups
  without an entry are switched off with a direct group level of 0.

## Limitations 

Many! But the following are probably the most significant:

  - Device discovery targets the first discovered cluster/router pair
  - Not tested with RGB or WW/CW adjustable lights 
  - Helvar does not provide API access to input devices, so they're not available 
  - All the other limitations listed on the library README.
  - I'm sure there are bugs. 

## Development

Install the test dependencies and run the test suite:

```bash
pip install -r requirements-test.txt
pytest
```

## Help

I don't really like the Home Assistant select card scene integration - perhaps we need a custom one. Or integration with the HomeAssistant scenes setup. Not sure.

Submit to HomeAssistant. 


  ## Disclaimer

Halvar (TM) is a registered trademark of Helvar Ltd.

This software is not officially endorsed by Helvar Ltd. in any way.

The authors of this software provide no support, guarantees, or warranty for its use, features, safety, or suitability for any task. We do not recommend you use it for anything at all, and we don't accept any liability for any damages that may result from its use.

This software is licensed under the Apache License 2.0. See the LICENCE file for more details. 
