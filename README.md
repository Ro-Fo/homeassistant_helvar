# homeassistant helvar

This is a simple Home Assistant Integration for Helvar Lighting Systems.  Specifically the 9XX series Routers. 

All the heavy lifting is done by the [aiohelvar](https://github.com/tomplayford/aiohelvar) library.

## Features

You can control:
 - Individual lights (on DALI, DMX and SBUS)
   - Dimming, dimming over time
 - Groups
   - Setting scenes
     - Dimming between scenes, dimming over time
   - Relative and absolute adjustments to groups

The integration will receive push notifications (if you enable them on the router) about scene changes from the router. These are fed back to the entities state, so things show the current levels. Updates from individual devices are not sent by the router. 

For general use, this should cover most needs. I use it at home and it works well. 

## Installation

You'll need to install HACS first, then set this up as a custom repository.

## Usage

Enable the integration and you'll be prompted for your router's IP address and port.

Two optional fields are also available:

- **Cluster ID** and **Router ID** — leave these blank on a normal setup, where
  they're derived from the router's IP (3rd/4th octet of a `10.254.C.R`
  address). Set them if your router is reached on an unrelated network (for
  example via a bridge on a `192.168.x.y` address), where that derivation would
  otherwise be wrong and device discovery would find nothing.

The integration will then pull all lighting devices, groups and scenes. 

- The lighting devices will be added as light entities.
- The groups will be added as select entities, and you'll be able to select from the group's available scenes.

## Limitations 

Many! But the following are probably the most significant:

  - Not tested with more than one Router (I only have one)
  - Not tested with RGB or WW/CW adjustable lights 
  - Helvar does not provide API access to input devices, so they're not available 
  - All the other limitations listed on the library README.
  - I'm sure there are bugs. 


## Diagnostics & Troubleshooting

If the integration won't connect, appears to hang while being added, or finds no
devices, run the read-only diagnostics that ship with the `aiohelvar` library
(installed as this integration's dependency) **before** digging through logs:

```bash
python -m aiohelvar diagnose <your-router-ip>
```

It checks in a few seconds whether the router is reachable and whether its
firmware supports the queries the integration needs, then prints a clear
verdict. It only sends read-only queries and needs nothing but the router's
address. A common result on older routers is:

```
Device discovery    : ERROR   -> error 15: Invalid message command
Verdict: WARNING - Router reachable, but device discovery (query C:100) is not
supported by this firmware ...
```

which means the router firmware is too old to enumerate devices over HelvarNet.
You can also test against a fake router with `python -m aiohelvar mock` (no
hardware required); see the [aiohelvar README](https://github.com/tomplayford/aiohelvar)
for details.

## Help

I don't really like the Home Assistant select card scene integration - perhaps we need a custom one. Or integration with the HomeAssistant scenes setup. Not sure.

Submit to HomeAssistant. 


  ## Disclaimer

Halvar (TM) is a registered trademark of Helvar Ltd.

This software is not officially endorsed by Helvar Ltd. in any way.

The authors of this software provide no support, guarantees, or warranty for its use, features, safety, or suitability for any task. We do not recommend you use it for anything at all, and we don't accept any liability for any damages that may result from its use.

This software is licensed under the Apache License 2.0. See the LICENCE file for more details. 




