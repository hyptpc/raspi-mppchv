"""
Main application file supporting multiple device types (serial and VISA)
dynamically loaded from a unified YAML configuration.
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from queue import Queue
import threading
from contextlib import asynccontextmanager
import argparse
import yaml
import os
import sys
from datetime import datetime, timedelta

from modules import db_measurements as database
from modules import db_logs as log_database
from modules.logger import log

# --- Import Worker/Monitor functions and shared resources ---
from modules import hardware_manager

# --- Import BOTH Communicator Classes ---
from modules.hamahoto_module import SerialCommunicator
from modules.kikusui_module import KikusuiCommunicator


# --- 1. Pre-load config for API routes ---
_config_path = "config/config.yaml" # Default path
if "--config" in sys.argv:
    try:
        _config_path = sys.argv[sys.argv.index("--config") + 1]
    except IndexError:
        pass # Use default if arg is present but value is missing

try:
    with open(_config_path, 'r') as f:
        _api_config = yaml.safe_load(f)
except Exception:
    _api_config = {} # Use defaults if it fails
    
_general_config = _api_config.get('general', {})
DISPLAY_WINDOW_MINUTES = _general_config.get('display_time_window_minutes', 5)
SERVER_FETCH_MINUTES = DISPLAY_WINDOW_MINUTES + 5
# --- End of Pre-load ---


config = None # This global config will be loaded by __main__ for lifespan
port_labels = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages startup/shutdown and starts background threads."""
    global config, port_labels
    log("INFO", "Application startup...")
    
    # Start the worker thread from hardware_manager
    worker_thread = threading.Thread(target=hardware_manager.worker, args=(command_queue,), daemon=True)
    worker_thread.start()
    log("INFO", "Command worker thread started.")
        
    # Determine number of ports from the initialized DEVICE_PORTS
    num_configured_ports = len(hardware_manager.DEVICE_PORTS)

    # lifespan uses the 'config' loaded by __main__
    raw_labels = config.get('port_labels', {})
    for port_id in hardware_manager.DEVICE_PORTS.keys():
        if port_id in [0, 1, 2, 3]:
            port_labels[port_id] = raw_labels.get(port_id, f"Port {port_id}")
    log("INFO", f"Loaded port labels: {port_labels}")

    monitoring_interval = config.get('general', {}).get('monitoring_interval', 5)
    monitoring_thread = threading.Thread(
        target=hardware_manager.monitoring_loop,
        # Pass the queue, interval, and the dynamically determined port list/keys
        args=(command_queue, monitoring_interval, list(hardware_manager.DEVICE_PORTS.keys())),
        daemon=True
    )
    monitoring_thread.start()
    log("INFO", f"Monitoring thread started for {num_configured_ports} ports. Interval: {monitoring_interval}s.")
    
    yield
    
    log("INFO", "Application shutdown.")

app = FastAPI(
    title="MPPC HV Controller API",
    description="Control and monitor HV modules.",
    version="3.0.0", # Version bump for multi-device support
    lifespan=lifespan
)
# Mount the static directory to serve CSS, JS, etc.
app.mount("/static", StaticFiles(directory="static"), name="static")

command_queue = Queue()

class StructuredCommand(BaseModel):
    port_id: int; command_type: str; value: float | None = None
    ramp_steps: int | None = 10; ramp_delay_s: float | None = 0.5
class RawCommand(BaseModel):
    port_id: int; command: str

# --- Static Page Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    try: return FileResponse("static/index.html")
    except FileNotFoundError: log("ERROR", "static/index.html not found."); return HTMLResponse("<h1>Error: index.html not found</h1>", status_code=404)

@app.get("/raw_data", response_class=HTMLResponse)
async def get_raw_data_page():
    """Serves the raw monitoring data log page from static/raw_data.html."""
    try: return FileResponse("static/raw_data.html")
    except FileNotFoundError: log("ERROR", "static/raw_data.html not found."); return HTMLResponse(content="<h1>Error: raw_data.html not found</h1>", status_code=404)

@app.get("/logs", response_class=HTMLResponse)
async def get_action_log_page():
    """Serves the action log page from static/logs.html."""
    try: return FileResponse("static/logs.html")
    except FileNotFoundError: log("ERROR", "static/logs.html not found."); return HTMLResponse(content="<h1>Error: logs.html not found</h1>", status_code=404)

# --- API: Configuration Routes ---

@app.get("/api/port-labels", tags=["Configuration"])
async def get_port_labels():
    """Returns the configured mapping of port IDs to display names."""
    global port_labels
    return port_labels

@app.get("/api/display-window-minutes", tags=["Configuration"])
async def get_display_window():
    """Provides the configured display time window (in minutes) to the frontend."""
    return {"display_time_window_minutes": DISPLAY_WINDOW_MINUTES}

# --- API: Data Retrieval Routes ---

@app.get("/api/logs", tags=["Data Retrieval"])
async def get_action_logs():
    """API endpoint to fetch action log data as JSON."""
    return log_database.get_action_logs()

@app.get("/data", tags=["Data Retrieval"])
async def get_data():
    """API endpoint for monitoring data."""
    start_time = datetime.now() - timedelta(minutes=SERVER_FETCH_MINUTES)
    return database.get_data_from_db_since(start_time=start_time)

# --- API: Control Routes ---

@app.post("/serial/command", tags=["Control"])
async def queue_structured_command(cmd: StructuredCommand):
    """Queues a structured command, validating port_id dynamically."""
    # Validate against the actual initialized ports
    if cmd.port_id not in hardware_manager.DEVICE_PORTS:
        valid_ports = sorted(list(hardware_manager.DEVICE_PORTS.keys()))
        return {"status": "error", "message": f"port_id is invalid. Valid ports are: {valid_ports}"}
        
    cmd_type = cmd.command_type.upper()
    
    # --- MODIFIED ---
    # Relax validation: The worker thread will now be responsible
    # for checking if a command is supported by a specific device.
    # We only check for commands that require a 'value'.
    
    if cmd_type in ["SET_VOLTAGE", "RAMP_VOLTAGE", "SET_CURRENT", "ENABLE_OCP"] and cmd.value is None:
        return {"status": "error", "message": "A 'value' is required for this command."}
    
    task = {"port_id": cmd.port_id, "command_info": cmd.dict()}
    command_queue.put(task)
    log("INFO", f"Queued command: {task}")
    return {"status": "success", "message": f"Command '{cmd_type}' for port {cmd.port_id} queued."}

@app.post("/serial/raw-command", tags=["Control"])
async def queue_raw_command(cmd: RawCommand):
    """Queues a raw command string, validating port_id dynamically."""
    if cmd.port_id not in hardware_manager.DEVICE_PORTS:
        valid_ports = sorted(list(hardware_manager.DEVICE_PORTS.keys()))
        return {"status": "error", "message": f"port_id is invalid. Valid ports are: {valid_ports}"}
    if not cmd.command:
        return {"status": "error", "message": "Raw command cannot be empty."}
    
    task = {"port_id": cmd.port_id, "command_info": {"command_type": "RAW", "raw_command": cmd.command}}
    command_queue.put(task)
    log("INFO", f"Queued raw command: {task}")
    return {"status": "success", "message": f"Raw command '{cmd.command}' for port {cmd.port_id} queued."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MPPC HV Controller Server")
    parser.add_argument("--config", type=str, default="config/config.yaml", help="Path to config file")
    args = parser.parse_args()

    # Read configuration file
    try:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
        log("INFO", f"Loaded config from: {args.config}")
    except Exception as e:
        log("ERROR", f"Failed to read/parse config file {args.config}: {e}"); exit(1)

    # Initialize Database Connections
    db_config = config.get('databases', {})
    db_directory = db_config.get('db_directory', 'data')
    db_suffix = db_config.get('db_suffix', '')
    try:
        database.init_database_connection(db_directory, suffix=db_suffix)
        log("INFO", f"Measurements DB connection initialized: {db_directory}/measurements{'_' if db_suffix else ''}{db_suffix}.db")
        database.init_db()
        log_database.init_database_connection(db_directory, suffix=db_suffix)
        log("INFO", f"Action Log DB connection initialized: {db_directory}/action_log{'_' if db_suffix else ''}{db_suffix}.db")
        log_database.init_db()
    except Exception as e:
        log("ERROR", f"Failed to initialize databases in '{db_directory}': {e}"); exit(1)
    
    # Apply global settings
    is_test_mode = config.get('test_mode', {}).get('enabled', True)
    hardware_manager.IS_TEST_MODE = is_test_mode # Set mode in the manager module
    
    # --- Pass device mappings to the hardware manager ---
    hardware_manager.DEVICE_MAPPINGS = config.get('device_mappings', {})
    log("INFO", f"Loaded device mappings: {hardware_manager.DEVICE_MAPPINGS}")
    
    # --- MODIFIED: Multi-Device Initialization ---
    
    configured_devices = config.get('devices', [])
    hardware_manager.DEVICE_PORTS.clear() # Clear dict in manager module
    initialization_ok = True

    if not isinstance(configured_devices, list):
         log("ERROR", f"'devices' section in config must be a list. Check '{args.config}'. Exiting.")
         exit(1)

    if not configured_devices and not is_test_mode:
        log("ERROR", f"'devices' list is empty in '{args.config}' while not in test mode. Exiting.")
        exit(1)
        
    # Loop through config and instantiate the correct class for each device
    for device_config in configured_devices:
        try:
            port_id = int(device_config.get('id'))
            dev_type = device_config.get('type')
            connection_info = device_config.get('connection') # Serial port or IP address
            
            communicator = None

            if not all([port_id is not None, dev_type, connection_info]):
                log("WARN", f"Skipping invalid device config entry: {device_config}. 'id', 'type', and 'connection' are required.")
                continue

            # --- Differentiation based on 'type' from config.yaml ---
            if dev_type == "serial_hv":
                # Instantiate the original SerialCommunicator
                communicator = SerialCommunicator(connection_info, is_test_mode)
                log_msg = f"Configured Port {port_id} as 'serial_hv' using {connection_info}"
                
                # Check its specific initialization attribute ('ser')
                if not is_test_mode and not communicator.ser:
                    log("ERROR", f"Failed to open port {connection_info} for Port {port_id}.")
                    initialization_ok = False

            elif dev_type == "kikusui_visa":
                # Instantiate the new KikusuiCommunicator
                resource_string = f"TCPIP0::{connection_info}::inst0::INSTR"
                communicator = KikusuiCommunicator(resource_string, is_test_mode)
                log_msg = f"Configured Port {port_id} as 'kikusui_visa' using {resource_string}"

                # Check its specific initialization attribute ('instrument')
                if not is_test_mode and not communicator.instrument:
                    log("ERROR", f"Failed to open VISA resource {resource_string} for Port {port_id}.")
                    initialization_ok = False
            
            else:
                log("WARN", f"Unknown device type '{dev_type}' for Port {port_id}. Skipping.")
                continue
            
            # Add the initialized communicator (of either type) to the shared dict
            if communicator:
                hardware_manager.DEVICE_PORTS[port_id] = communicator
                log("INFO", log_msg)
        
        except ValueError:
            log("WARN", f"Invalid port_id '{device_config.get('id')}' in config. Skipping.")
        except Exception as e:
            log("ERROR", f"Error initializing communicator for config {device_config}: {e}")
            initialization_ok = False
            
    # Test mode fallback: create mock objects for both types
    if is_test_mode:
        # Check config to decide which mocks to create
        mock_serial_ids = [d.get('id') for d in configured_devices if d.get('type') == 'serial_hv']
        mock_kikusui_ids = [d.get('id') for d in configured_devices if d.get('type') == 'kikusui_visa']
        
        # Create serial mocks if not in config
        for i in [d['id'] for d in configured_devices if d['type'] == 'serial_hv']:
             if i not in hardware_manager.DEVICE_PORTS:
                mock_name = f"/dev/mockTTY{i}"
                hardware_manager.DEVICE_PORTS[i] = SerialCommunicator(mock_name, True)
                log("INFO", f"Using mock 'serial_hv' communicator for Port {i}.")
        
        # Create kikusui mocks if not in config
        for i in [d['id'] for d in configured_devices if d['type'] == 'kikusui_visa']:
             if i not in hardware_manager.DEVICE_PORTS:
                mock_resource = f"MOCK::KIKUSUI::{i}"
                hardware_manager.DEVICE_PORTS[i] = KikusuiCommunicator(mock_resource, True)
                log("INFO", f"Using mock 'kikusui_visa' communicator for Port {i}.")

    if not initialization_ok and not is_test_mode:
        log("ERROR", "Exiting due to initialization errors in non-test mode.")
        exit(1)
    if not hardware_manager.DEVICE_PORTS:
        log("ERROR", "No devices were configured or initialized successfully. Exiting.")
        exit(1)

    # Read server config
    server_config = config.get('server', {})
    host_to_run = server_config.get('host', '0.0.0.0')
    port_to_run = server_config.get('port', 8000)

    # Start Uvicorn server
    import uvicorn
    log("INFO", f"Starting server on {host_to_run}:{port_to_run}")
    uvicorn.run(app, host=host_to_run, port=port_to_run)

