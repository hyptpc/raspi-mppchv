# MPPC High Voltage Module Controller

## Description

This application provides a web-based interface to control and monitor multiple Hamamatsu C11204-01 MPPC High Voltage Power Supply modules connected via serial ports (UART) to a Raspberry Pi or similar Linux system. It allows users to set voltages, turn outputs on/off, monitor voltage/current/temperature, and log both monitoring data and user actions.

## Directory Structure 📁

```
raspi-mppchv/
├── main.py                     # Main application entry point (FastAPI server)
├── config/
│   └── config.yaml             # Configuration file
├── data/                       # Stores database files (created automatically)
├── static/
│   ├── index.html              # Main Web UI file
│   ├── style.css               # CSS styles
│   └── script.js               # JavaScript for UI logic and charts
|   └── chart.umd.js            # Chart.js library (downloaded)
|   └── chartjs-adapter-date-fns.bundle.min.js # Date adapter for Chart.js (downloaded)
├── modules/
│   ├── __init__.py             # Makes 'modules' a Python package
│   ├── serial_com.py           # Handles serial communication logic
│   ├── db_measurements.py      # Database logic for monitoring data
│   ├── db_logs.py              # Database logic for action logs
│   └── logger.py               # Logging setup
└── requirements.txt            # Python dependencies
```

## Setup & Installation ⚙️

1.  **Clone the Repository:**
    ```bash
    git clone raspi-mppchv
    cd raspi-mppchv
    ```

2.  **Create & Activate Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure:**
    * Edit `config/config.yaml` to match your setup:
        * Set `serial_ports` device names (e.g., `/dev/ttyAMA0`, `/dev/ttyUSB0`).
        * Adjust `monitoring_interval` if needed.
        * Set `test_mode.enabled` to `false` for use with real hardware.
        * Change `server.host` and `server.port` if necessary.

5.  **Initialize Databases:**
    Create a new named database pair without connecting to hardware:
    ```bash
    python main.py --new-db run001 --init-db-only
    ```

## Usage ▶️

1.  **Start the Server:**
    Navigate to the `mppc_controller` directory in your terminal and run:
    ```bash
    python main.py --config config/config.yaml
    ```
    (You can omit `--config config/config.yaml` if the file is in the default location). The server will log the host and port it's running on (e.g., `0.0.0.0:8000`).

2.  **Access the Web UI:**

    * **From the Same Local Network:**
        Open a web browser on a device connected to the **same local network** as the server and navigate to:
        `http://<server-ip-address>:<port>`
        (e.g., `http://192.168.20.5:8000`, using the host and port defined in `config.yaml` or logged by the server).

    * **From an External Network (using SSH Tunnel):**
        If your access device (e.g., your laptop) is *not* on the same network as the server, but you can SSH into the server:
        1.  Keep the server running on the server machine.
        2.  Open a **new terminal on your local machine** (e.g., your laptop) and establish an SSH tunnel with the following command:
            ```bash
            ssh -L <local_port>:localhost:<server_port> <username>@<server_ip_address>
            ```
            * Replace `<local_port>` with an unused port on your local machine (e.g., `8080`).
            * Replace `<server_port>` with the port the server is running on (usually `8000`).
            * Replace `<username>@<server_ip_address>` with your SSH login details for the server (e.g., `pi@192.168.20.5`).
            * **Example:** `ssh -L 8080:localhost:8000 pi@192.168.20.5`
        3.  Keep this SSH terminal window open.
        4.  Open a web browser on your **local machine** and navigate to:
            `http://localhost:<local_port>`
            (e.g., `http://localhost:8080`)

3.  **Use the Interface:**
    * Use the "Structured Commands" panel for common actions.
    * Use the "Raw Command" panel to send specific device commands from the manual.
    * Monitor status in the top-right panels.
    * View live data trends in the charts below.
    * Use the "Graph Display" toggles to show/hide specific data series.
    * Access historical monitoring data via the "View Raw Data Log" link.
    * Access command history via the "View Action Log" link.


## Database runs

```bash
python main.py --new-db                    # Create a pair with a date/identifier and start
python main.py --new-db run001             # Create a named pair and start
python main.py --new-db run001 --init-db-only  # Create schemas without hardware or server
```

Files are created under `databases.db_directory`. Named runs refuse either existing
file rather than overwriting or resuming it. The selected suffix and paths are logged.
To resume a run, set `databases.db_suffix` to its suffix and start without `--new-db`.
`--init-db-only` can also initialize the configured pair without starting hardware.

Both filenames use the same `databases.db_suffix` setting:

```yaml
databases:
  db_directory: data
  db_suffix: run001
```

This selects `data/measurements_run001.db` and `data/action_log_run001.db` together.
An empty suffix selects `measurements.db` and `action_log.db`. Database creation,
application connections, and snapshot helpers share the same filename resolver.

## Optional database copies

The application does not start synchronization automatically. To keep recording
locally and publish copies elsewhere, configure a destination:

```yaml
databases:
  db_directory: data
  db_suffix: run001
database_sync:
  destination_directory: /path/to/shared/monitor-tmp
  interval_seconds: 5
```

```bash
./sync_db.sh --config config/config.yaml --dry-run  # Preview both source/target paths
./sync_db.sh --config config/config.yaml            # Repeat until Ctrl+C; reload config each cycle
./sync_db.sh --config config/config.yaml --once     # Optional single copy
./sync_db.sh --config config/config.yaml --destination /some/other/folder --suffix run002 --once
```

Each copy uses SQLite's online backup API, including committed WAL data. Both
snapshots are created and checked before publishing either file; each destination
file is replaced atomically. Sources and unrelated destination files are retained.
The databases are independent, so their snapshots are not one cross-database transaction.
Use the destination as a read-only copy location, rather than another app's writable DB directory.

The helper reads `databases.db_directory` and `databases.db_suffix` from the same
config as the controller. After using `--new-db`, either set that run's suffix in
the config or pass its printed suffix with `--suffix`. Leave the sync destination
empty when unused. No SQLite command-line program or hardware connection is needed.

`sync_db.sh` runs from the repository directory and selects the project virtual
environment, then `$HOME/.venv`, then `python3`. Set `HV_PYTHON` to override the
interpreter. The Python entry point is also available as `python -m modules.db_sync`.

To run the controller and sync together in a split tmux window, copy the generic
launcher template once and select your config:

```bash
cp -n hv_run.sh.example hv_run.sh
./hv_run.sh --config config/config.yaml
tmux attach -t hv
```

The left pane runs the controller; the right pane runs sync with the same config.
Both panes restart their command if it exits. The launcher refuses to start a
duplicate `hv` session. The template defaults to `config/config.yaml`; use
`--config PATH` or edit `CONFIG` in your local launcher for another configuration.
`hv_run.sh` and deployment configs named `config/config_*.yaml` are ignored by Git.
Existing local launchers can retain their deployment settings; repository updates
manage only the template. Configure the sync destination before starting.
Stopping the `hv` session stops both processes; an existing
`hv_controller.service` can keep using its local `hv_run.sh` as the start command.

If SQLite reports a locked database, use the same config:

```bash
./db_unlock.sh --config config/config.yaml
```

This checks both databases, waiting up to five seconds for each lock operation.
SQLite handles journal recovery; WAL databases also receive a truncate checkpoint.
The helper never kills processes or manually deletes database/journal files.
An active process must release its own lock. On failure, the helper returns a
nonzero status and lists processes using the files when `fuser` is available.
Close the process holding the lock and retry; a successful check cannot prevent
another process from acquiring a lock afterward. The controller and HV outputs
are not operated by this helper. Interpreter selection matches `sync_db.sh`.

## Serial startup

Before starting the server and command worker, each serial HV device receives `HOF`
and `HCM0`. Startup verifies output OFF and correction OFF with `HGS`, then reads
the six parameter words with `HRT`.

If needed, `HST` persistently sets all four temperature coefficients to zero,
the base voltage to approximately 20.5 V, and the base temperature to approximately
25 °C. Startup reads back changed parameters and checks OFF status again. Matching
parameters skip the persistent write. Any failure triggers another OFF attempt
and prevents server startup. Test mode simulates initialization without serial I/O.

For serial devices, `RESET` repeats this OFF and parameter-verification procedure.
It does not send `HRE` or enable HV output. Reset failures are recorded in the
action log, and existing matching parameters skip persistent writes.

Serial `TURN_ON` also repeats verification, overwrites the temporary voltage
setpoint with approximately 20.5 V while OFF, then sends `HON` and verifies output
ON with correction OFF. Repeating ON while already ON restarts at this low voltage.
Any failure triggers an OFF attempt and returns an error.

If serial monitoring detects correction enabled, it requests output OFF and records
the monitor sample as an error. A successful OFF acknowledgement is not treated as
proof of the subsequent output state; later monitoring supplies that state.

The parameter order and conversions follow K29-B61218K sections 3, 4-1 and 4-2.
Hardware power-on and `HRE` enable HV output; startup initialization cannot keep
output OFF before communication is established.

The K29-B61218K status table (section 5, p.19) and example (section 4-4, p.10)
define sensor bit 3 as 1 = connected, but section 5-4 (p.20) describes the inverse.
The sensor display and temperature conversion retain the table/example convention;
the correction interlock uses bit 6 and does not depend on bit 3. The documentation
conflict remains unresolved pending confirmation against known sensor wiring or
manufacturer clarification. Do not infer sensor wiring solely from this flag.

Mock devices start with output OFF and retain ON/OFF and voltage settings. Serial
mocks generate protocol frames and run the same response parser and interlocks as
hardware. Kikusui mock queries reflect the same state as monitoring. Mock devices
model no load by default and never open serial or VISA connections.

## Raw commands

Serial raw commands are limited to `HRT`, `HPO`, `HGS`, `HGV`, `HGC`, `HGT`, and
`HOF`. Configuration changes, ON, and hardware reset commands are rejected.

Kikusui raw commands are limited to `*IDN?`, `MEAS:VOLT?`, `MEAS:CURR?`,
`OUTP?` / `OUTP:STAT?`, `STAT:OPER:COND?`, and `STAT:QUES:EVEN?`, plus their
fully spelled forms. Query responses are read and recorded in the action log.
Raw commands ignore case and surrounding whitespace; compound commands are rejected.
Both the API and device adapters enforce these restrictions.

## Measurement units

Serial voltage requests must be within 20–90 V and the configured channel limit.
Serial OFF ramps down to 20.5 V before OFF; Kikusui OFF ramps down to 0 V.
Use `TURN_OFF`, rather than a zero-voltage request, to disable a serial output.

Measured current is stored and displayed in mA for both serial and Kikusui devices.
Kikusui current readings are converted from A to mA before rounding. Current and OCP
setpoints still use A.

Existing Kikusui measurement rows retain their original values in A. Before collecting
Kikusui data with this change, select an unused `databases.db_suffix` to create fresh
databases and avoid mixing units with historical measurements.

## Validation

Install `requirements.txt`, then run:

```bash
python -m unittest discover -s tests -v
```

Unknown or missing monitoring status is displayed as `UNKNOWN`, including HV,
protection, and temperature flags. Unknown status is not displayed as OFF or OK.

## Dependencies 📦

* FastAPI: Web framework
* Uvicorn: ASGI server
* SQLAlchemy: Database interaction (ORM)
* PySerial: Serial port communication
* PyYAML: Reading YAML configuration files
* Chart.js & chartjs-adapter-date-fns: Front-end charting libraries (loaded via CDN or locally)

## License 📜

This project is licensed under the **MIT License**. See the `LICENSE` file for details.
