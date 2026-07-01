# Helvar diagnostics tool

`helvar_diagnose.py` is a small, **read-only** command-line tool to check
whether a Helvar router is reachable and whether its firmware supports the
HelvarNet queries this integration depends on. Run it on the machine that hosts
Home Assistant (for example your Raspberry Pi) when the integration won't
connect, hangs, or finds no devices.

It only sends HelvarNet *query* commands - it never changes any device, group
or scene, and it uses no data of yours: you pass it the router host, nothing
else.

## Usage

```bash
python3 tools/helvar_diagnose.py <router-host> [options]
```

Options:

| Option | Default | Meaning |
| --- | --- | --- |
| `-p`, `--port` | `50000` | HelvarNet TCP port |
| `-t`, `--timeout` | `5` | per-query timeout, seconds |
| `--cluster N` | derived from IP | cluster id used for the device-discovery probe |
| `--router N` | derived from IP | router id used for the device-discovery probe |
| `--json` | off | print the report as JSON |

Exit code is `0` if the router looks compatible, `1` otherwise, so you can use
it in scripts.

## Example

Healthy router:

```
$ python3 tools/helvar_diagnose.py 192.0.2.10
HelvarNet diagnostics for 192.0.2.10:50000
TCP connection      : OK
Workgroup name      : OK      -> MyWorkgroup
Router version      : OK      -> 5.4.2
...
Verdict: OK - Router reachable and responds to device discovery.
```

Old firmware that doesn't support device discovery:

```
Device discovery    : ERROR   -> error 15: Invalid message command
Verdict: WARNING - Router reachable, but device discovery (query C:100) is not
supported by this firmware (error 15: Invalid message command). ...
```

`error 15` ("Invalid message command") means the router firmware doesn't
implement that query - a firmware capability limit, not a wiring or network
problem.

## Testing it without a router

`aiohelvar` (>= 0.9.9) ships a mock router you can point this tool at:

```bash
# in one shell - start a fake "old firmware" router
python -m aiohelvar mock --profile legacy --port 50000

# in another shell - diagnose it
python3 tools/helvar_diagnose.py 127.0.0.1
```

Send the mock `kill -HUP <pid>` (it prints its PID on start) to flip it between
`modern` and `legacy` behaviour while it runs.

## Cluster / router IDs, ports & firmware

Grounded in Helvar's own documentation (Designer 5 Quick Start Guide §3.4 and
the Designer Release Notes):

* **Ports:** the HelvarNet API/TCP port is **50000** (the integration default).
  Don't confuse it with **60005**, which is the inter-router *cluster comms*
  port - pointing the integration at 60005 won't work.
* **Cluster/router from IP:** Helvar derives the HelvarNet `@cluster.router`
  address from the router's IP using the *cluster mask*. With the default mask
  `255.255.255.0` and the usual `10.254.C.R` layout, cluster = 3rd octet and
  router = 4th octet - which is what the integration assumes. If your router is
  reached on an unrelated network (for example via a bridge on a `192.168.x.y`
  address), that assumption is wrong and device discovery targets the wrong
  address. The report prints the probe address so a mismatch is visible; set the
  real ids with `--cluster` / `--router`.
* **Firmware/models:** the 9xx routers (905/910/920) and the newer, Linux-based
  950 run firmware in the 5.5.x-5.8.x range. Older firmware may not implement
  newer HelvarNet queries and answers them with error 15. Helvar also recommends
  setting the router's IP *broadcast* address correctly for reliable HelvarNet
  behaviour (relevant on VLANs).

## Notes

* The tool works with any installed `aiohelvar` version, and even if it isn't
  installed at all, because it speaks the protocol directly over TCP. When a new
  enough `aiohelvar` is present, its error-code descriptions are reused.
* The device-discovery probe uses the same cluster/router address the
  integration would derive from the router's IP (3rd/4th octet). If that address
  is wrong for your setup, the report shows it, which is a hint to set the
  cluster/router explicitly with `--cluster` / `--router`.
