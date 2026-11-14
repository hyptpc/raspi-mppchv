# MPPC HV Controller

A web interface for Hamamatsu C11204-01 HV modules over serial ports and
Kikusui PMX-A supplies over LAN/VISA. It provides voltage ramps, output control,
voltage/current/temperature monitoring, and SQLite measurement and action logs.

- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Operation](#operation)
- [Database files and runs](#database-files-and-runs)
- [Database sync](#database-sync)
- [Running in tmux](#running-in-tmux)
- [Database lock recovery](#database-lock-recovery)
- [Protocol notes](#protocol-notes)
- [Development](#development)

## Quick start

Requirements: Python 3.11 or newer. The tmux launcher additionally requires tmux.
The supplied config starts in **test mode**, using simulated devices without
opening serial or VISA connections.

```bash
git clone https://github.com/hyptpc/raspi-mppchv.git
cd raspi-mppchv
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n config/config.yaml config/config_site.yaml
python main.py --config config/config_site.yaml
```

On Windows, activate the environment with `.venv\Scripts\activate`.
Run application commands from the repository directory. Examples below use
`config/config_site.yaml`; substitute your deployment config as needed.

Open `http://localhost:8000` on the server, or `http://<server-address>:8000`
from the same network. The address and port depend on the `server` settings.

For access through SSH, run this on your local computer:

```bash
ssh -N -L 8080:localhost:8000 user@server
```

Keep the tunnel open and browse to `http://localhost:8080`.

Before using real hardware, configure the device connections and voltage limits,
then set `test_mode.enabled: false`. **Starting or restarting a controller that
includes serial HV modules sends OFF initialization commands.** Kikusui connections
preserve existing output state and setpoints. See [Operation](#operation) before
starting a real deployment.

## Configuration

Use [config/config.yaml](config/config.yaml) as the template. Local deployment
configs named `config/config_*.yaml` are ignored by Git.

| Setting | Purpose |
|---|---|
| `devices` | Unique device IDs, device types, connections, and per-channel voltage limits |
| `port_labels` | Display names for device IDs 0–3 |
| `device_mappings` | Primary device ID → serial module ID supplying its temperature data |
| `general.monitoring_interval` | Background monitoring interval in seconds |
| `general.display_time_window_minutes` | Chart history window in minutes |
| `general.ramp_voltage_target_v_per_s` | Target ramp rate in V/s |
| `general.ramp_voltage_max_step_v` | Maximum change per ramp step in V |
| `general.ramp_pad_step_to_target_rate` | Add waiting time on fast links to maintain the target ramp rate |
| `server.host`, `server.port` | Listening address and port |
| `databases.db_directory`, `databases.db_suffix` | Local database directory and shared filename suffix |
| `database_sync.destination_directory` | Optional location for database copies |
| `test_mode.enabled` | `true` for simulated devices; `false` for hardware |

A device uses `serial_hv` with a serial device path, or `kikusui_visa` with a
supply IP address. For example:

```yaml
devices:
  - id: 0
    type: serial_hv
    connection: /dev/ttyUSB0
    max_voltage_v: 58.5
  - id: 1
    type: kikusui_visa
    connection: 192.168.1.100
    max_voltage_v: 58.5

port_labels:
  0: Serial HV
  1: Kikusui HV
```

Replace the example connections and limits with values appropriate for the
connected supplies and loads. Omitting `max_voltage_v` leaves no channel-specific
software ceiling. The limit is checked when a voltage request is accepted and
again before execution; it also applies to the starting voltage for ON commands.
It does not configure the supply's hardware overvoltage protection (OVP).

For temperature mapping, list the sensor module in `devices` and map its ID in
`device_mappings`. Only temperature data and temperature flags are merged;
voltage, current, and output/protection state come from the primary supply.
Device IDs outside 0–3 are hidden from the normal UI selectors but remain
addressable through the API.

Controller configuration changes take effect after a process restart. The sync
helper independently reloads its config before each copy cycle.

## Operation

The behavior differs between the two device types:

| Action | Serial HV module | Kikusui PMX-A |
|---|---|---|
| Start or restart | Initialize output OFF and temperature correction OFF; verify stored parameters | Connect and read identification; preserve output state and setpoints |
| `TURN_ON` | Repeat OFF initialization, set approximately 20.5 V, then turn ON | If OFF, set and verify 0 V before ON; an already-ON supply is left alone |
| `SET_VOLTAGE` | Ramp within 20–90 V and the configured channel limit | Ramp to the target within the configured channel limit |
| `TURN_OFF` | Ramp down to 20.5 V when needed, then OFF | Ramp down to 0 V when needed, then OFF |
| `RESET` | Repeat OFF initialization and parameter verification | Clear the protection alarm only, like `CLEAR_TRIP` |

Repeating serial `TURN_ON` while already ON restarts the output at the low starting
voltage. Kikusui software startup does not restore settings or turn the output ON
after a hardware power loss.

### Web interface

Use **Structured Commands** for control and **Graph Display** to select chart
series. **View Raw Data Log** shows recent measurement records;
**View Action Log** shows command results.

Sending a command acknowledges that it was queued. Check the action log for its
execution result, including responses beginning with `ERROR`.

| Value | Unit |
|---|---|
| Measured and requested voltage | V |
| Measured current, status display, and current graph | mA |
| Current-limit and OCP threshold inputs | A |
| Temperature | °C |

Unknown or unavailable status appears as a gray `—`, with `Unknown` in its tooltip
and accessible label. It is not interpreted as OFF or OK.

### Ramps and OFF requests

The default ramp rate is 5 V/s. Each ramp writes successive setpoints and monitors
the result. With `ramp_pad_step_to_target_rate: true`, fast communication includes
waiting time to maintain the requested rate. Steps are sized from the previous
cycle duration and capped by `ramp_voltage_max_step_v`; the first cycle uses
`ramp_voltage_default_cycle_s`.

With the default `require_on_for_voltage_increase: true`, an increase requires
confirmed output ON. Invalid measurements or command failures stop further ramp
steps. An explicit OFF operation still attempts OFF if its ramp-down fails.

Commands run in one queue. **An OFF request waits behind an active ramp; it does
not interrupt it.** Use `TURN_OFF` to disable serial output, since a 0 V voltage
request is outside its supported range.

The browser refreshes every two seconds. Several ramp steps can therefore appear
at once, and the instrument may return repeated measurements between its own
measurement updates. Compare recorded timestamps when examining a ramp.

### Kikusui current limit and OCP

`SET_CURRENT` sets the constant-current limit in A.
**SET OCP LEVEL (Kikusui)** sets the overcurrent protection threshold in A.
Its API name remains `ENABLE_OCP` for compatibility; it sets a threshold rather
than toggling protection.

OCP levels must be finite and positive. PMX specifies 10–110% of the model's rated
current. The controller writes the threshold and reads it back before reporting
success. Unavailable, invalid, or mismatched readback produces an error; a setting
already applied to the supply is not automatically rolled back or reset.

PMX has no documented OCP enable/disable switch command. The UI has no disable
action, and `DISABLE_OCP` requests are rejected without sending device commands.
Startup leaves current-limit and OCP settings unchanged. Threshold readback checks
the setting, not the physical operation of the protection circuit.

### Raw commands

Only the following raw commands are allowed. Case and surrounding whitespace are
normalized; compound commands are rejected by both the API and device adapters.

| Device | Approved commands |
|---|---|
| Serial | `HRT`, `HPO`, `HGS`, `HGV`, `HGC`, `HGT`, `HOF` |
| Kikusui | `*IDN?`, `MEAS:VOLT?`, `MEAS:CURR?`, `OUTP?`, `OUTP:STAT?`, `STAT:OPER:COND?`, `STAT:QUES:EVEN?`, and their fully spelled forms |

`HOF` requests serial output OFF directly. `STAT:QUES:EVEN?` reads and clears the
Kikusui questionable event register. Normal monitoring uses condition registers
and preserves event history. Raw query responses are consumed and recorded in the
action log.

## Database files and runs

Measurements and actions share the suffix in the selected config:

```yaml
databases:
  db_directory: data
  db_suffix: run001
```

This selects `data/measurements_run001.db` and `data/action_log_run001.db`.
An empty suffix selects `measurements.db` and `action_log.db`. Normal startup
creates missing tables and continues using existing files.

To prepare a new named pair without starting hardware or the web server:

```bash
python main.py --config config/config_site.yaml --new-db run002 --init-db-only
```

Set `databases.db_suffix: run002` in the config, then start normally. This also
keeps the sync helper pointed at the same pair.

`--new-db` without a name generates a suffix. Omitting `--init-db-only` creates
the pair and starts the controller. A new run refuses either existing filename;
it does not overwrite or resume an existing pair. To resume one, select its suffix
in the config and start without `--new-db`.

`--init-db-only` can also initialize the configured pair without `--new-db`.
If a run is selected only through `--new-db`, copy its printed suffix into the
config or pass it to sync with `--suffix`.

Older versions stored Kikusui current in A. Those historical rows are left
unchanged. Use a fresh suffix when migrating from that format to avoid mixing A
and mA in the same measurement history.

## Database sync

Sync is optional and runs separately from the controller. Keep the working DBs
local and configure a destination for snapshots:

```yaml
database_sync:
  destination_directory: /path/to/shared/monitor-tmp
  interval_seconds: 5
```

```bash
./sync_db.sh --config config/config_site.yaml --dry-run
./sync_db.sh --config config/config_site.yaml
```

The first command previews source and destination paths. The second keeps copying
both databases until Ctrl+C, reloading the config each cycle. Use `--once` for a
single copy. `--destination`, `--suffix`, and `--interval` override the config.
Leave the destination empty when sync is unused.

Copies use SQLite's online backup API, including committed WAL data. Both files
are staged and checked before publication; each destination file is replaced
atomically. The pair is not one cross-database transaction. Sources and unrelated
destination files are retained.

Use a dedicated snapshot destination rather than another application's writable
DB directory. Readers should reopen snapshots to see subsequent replacements.

Shell helpers select `.venv/bin/python`, then `$HOME/.venv/bin/python`, then
`python3`. Set `HV_PYTHON` to override this. `sync_db.sh` and `db_unlock.sh` run from
the repository directory; the Python entry points are `modules.db_sync` and
`modules.db_unlock`.

## Running in tmux

Configure the sync destination first, then create a local launcher:

```bash
cp -n hv_run.sh.example hv_run.sh
./hv_run.sh --config config/config_site.yaml
tmux attach -t hv
```

The controller runs on the left and sync on the right. Detach with Ctrl+B, then D.
Each pane restarts its command after it exits. The launcher refuses an existing
session with the same name.

The template defaults to session `hv` and config `config/config.yaml`. Edit
`SESSION_NAME` and `CONFIG` in your local launcher for a deployment, or pass
`--config PATH` when starting. Local `hv_run.sh` is ignored by Git; updates change
only `hv_run.sh.example`. An existing `hv_controller.service` can continue using
its local launcher.

Stopping the tmux session stops both processes. Stopping the software does not
itself request HV OFF. Starting it again applies the device-specific startup
behavior in [Operation](#operation), including serial OFF initialization.

## Database lock recovery

```bash
./db_unlock.sh --config config/config_site.yaml
```

The helper checks both configured databases, waiting up to five seconds for each
lock operation. SQLite handles journal recovery; WAL databases also receive a
truncate checkpoint. No HV connection is opened.

On failure, it returns a nonzero status and, when `fuser` is available, lists
processes using the files. These are not necessarily the lock owners. Close the
process holding the lock and retry. The helper does not kill processes or manually
delete databases or journal files, and a successful check cannot prevent a later
lock.

## Protocol notes

These details explain the device-specific behavior above.

### Hamamatsu serial initialization

Startup sends `HOF` and `HCM0`, verifies output OFF and correction OFF using `HGS`,
and reads the six parameter words with `HRT`. If they differ from the required
values, `HST` persistently stores four zero temperature coefficients, a base
voltage of approximately 20.5 V, and a base temperature of approximately 25 °C.
Matching parameters skip the persistent write. Changed parameters are read back,
and OFF status is checked again before the server starts.

Initialization failures trigger another OFF attempt and prevent server startup.
Serial `TURN_ON` repeats initialization, replaces the temporary voltage setting
with approximately 20.5 V, sends `HON`, and verifies output ON with correction OFF.
Failures trigger an OFF attempt. `RESET` repeats initialization without `HRE`.
If monitoring detects correction enabled, it requests OFF and records an error;
subsequent monitoring is needed to confirm the resulting output state.

Parameter ordering and conversions follow K29-B61218K sections 3 and 4-1/4-2.
Hardware power-on and `HRE` enable output, so software cannot keep it OFF before
communication is established.

The manual's status table and example define sensor bit 3 as 1 = connected, while
section 5-4 describes the inverse. The implementation retains the table/example
convention. Correction protection uses bit 6 independently; sensor wiring should
not be inferred solely from bit 3.

### Kikusui PMX status

The [PMX interface manual](https://www.kikusui.cn/resources/001/pdf/pmx-a_interface_manual.pdf)
defines CC mode as OPERation bit 10 and active OCP as QUEStionable bit 1
(pp.105/123). QUEStionable bit 4 is overtemperature. Monitoring reads
`STATus:OPERation:CONDition?` and `STATus:QUEStionable:CONDition?` so an active OCP
condition remains visible across polls. Malformed output-state or status-register
responses are treated as monitoring errors.

Connection only queries `*IDN?`. Startup sends no output/setpoint commands,
`*RST`, or `*CLS`. Explicit `RESET` and `CLEAR_TRIP` send only
`OUTPut:PROTection:CLEar`. Remove the alarm's cause before clearing it;
turning ON is a separate operation.

## Development

```bash
python -m unittest discover -s tests -v
```

Tests use simulated devices and injected communication failures without operating
hardware. They do not verify physical protection circuits. Mock devices start OFF,
retain output/setpoint state, and model no load by default. Serial mocks use the
same protocol parser and interlocks as hardware.

| Path | Contents |
|---|---|
| `main.py` | Configuration, API, and startup |
| `modules/hamahoto_module.py`, `modules/kikusui_module.py` | Device adapters |
| `modules/hardware_manager.py` | Command queue, ramps, and safety checks |
| `modules/db_*.py` | Database storage, naming, sync, and lock checks |
| `static/` | Web UI and local Chart.js libraries |
| `config/config.yaml` | Shared example config |
| `hv_run.sh.example` | Generic tmux launcher template |
| `sync_db.sh`, `db_unlock.sh` | Standalone database helpers |
| `tests/` | Automated tests |

Python dependencies are listed in [requirements.txt](requirements.txt).
The project is distributed under the [MIT License](LICENSE).
