"""
Main application file using dynamic port count from YAML configuration.
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

from modules import db_measurements as database
from modules import db_logs as log_database
from modules import serial_com
from modules.logger import log

config = None
port_labels = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages startup/shutdown and starts background threads."""
    global config, port_labels
    log("INFO", "Application startup...")
    
    worker_thread = threading.Thread(target=serial_com.worker, args=(serial_command_queue,), daemon=True)
    worker_thread.start()
    log("INFO", "Command worker thread started.")
        
    # Determine number of ports from the initialized DEVICE_PORTS
    num_configured_ports = len(serial_com.DEVICE_PORTS)

    raw_labels = config.get('port_labels', {})
    for port_id in serial_com.DEVICE_PORTS.keys():
         port_labels[port_id] = raw_labels.get(port_id, f"Port {port_id}")
    log("INFO", f"Loaded port labels: {port_labels}")

    monitoring_interval = config.get('general', {}).get('monitoring_interval', 5)
    monitoring_thread = threading.Thread(
        target=serial_com.monitoring_loop,
        # Pass the queue, interval, and the dynamically determined port list/keys
        args=(serial_command_queue, monitoring_interval, list(serial_com.DEVICE_PORTS.keys())), 
        daemon=True
    )
    monitoring_thread.start()
    log("INFO", f"Monitoring thread started for {num_configured_ports} ports. Interval: {monitoring_interval}s.")
    
    yield
    
    log("INFO", "Application shutdown.")

app = FastAPI(
    title="MPPC HV Controller API",
    description="Control and monitor HV modules.",
    version="2.5.0", # Version up for dynamic ports
    lifespan=lifespan
)
# Mount the static directory to serve CSS, JS, etc.
app.mount("/static", StaticFiles(directory="static"), name="static")

serial_command_queue = Queue()

class StructuredCommand(BaseModel):
    port_id: int; command_type: str; value: float | None = None
    ramp_steps: int | None = 10; ramp_delay_s: float | None = 0.5
class RawCommand(BaseModel):
    port_id: int; command: str

@app.get("/", response_class=HTMLResponse)
async def read_root():
    try: return FileResponse("static/index.html")
    except FileNotFoundError: log("ERROR", "static/index.html not found."); return HTMLResponse("<h1>Error: index.html not found</h1>", status_code=404)

@app.get("/raw_data", response_class=HTMLResponse)
async def get_raw_data_page():
    """Serves the raw monitoring data log page from static/raw_data.html."""
    try:
        # Use FileResponse to serve the static HTML file
        return FileResponse("static/raw_data.html")
    except FileNotFoundError:
         log("ERROR", "static/raw_data.html not found.")
         return HTMLResponse(content="<h1>Error: raw_data.html not found</h1>", status_code=404)

@app.get("/logs", response_class=HTMLResponse)
async def get_action_log_page():
    """Serves the action log page from static/logs.html."""
    try:
        # Use FileResponse to serve the static HTML file
        return FileResponse("static/logs.html")
    except FileNotFoundError:
        log("ERROR", "static/logs.html not found.")
        return HTMLResponse(content="<h1>Error: logs.html not found</h1>", status_code=404)

@app.get("/api/port-labels", tags=["Configuration"])
async def get_port_labels():
    """Returns the configured mapping of port IDs to display names."""
    global port_labels
    return port_labels

@app.get("/api/logs", tags=["Data Retrieval"])
async def get_all_action_logs():
    """API endpoint to fetch action log data as JSON."""
    return log_database.get_action_logs()

@app.post("/serial/command", tags=["Serial Control"])
async def queue_structured_command(cmd: StructuredCommand):
    """Queues a structured command, validating port_id dynamically."""
    # Validate against the actual initialized ports
    if cmd.port_id not in serial_com.DEVICE_PORTS:
        valid_ports = sorted(list(serial_com.DEVICE_PORTS.keys()))
        return {"status": "error", "message": f"port_id is invalid. Valid ports are: {valid_ports}"}
        
    cmd_type = cmd.command_type.upper()
    valid_commands = ["MONITOR", "SET_VOLTAGE", "TURN_ON", "TURN_OFF", "RESET", "RAMP_VOLTAGE"]
    if cmd_type not in valid_commands: return {"status": "error", "message": f"Invalid command_type: {cmd.command_type}"}
    if cmd_type in ["SET_VOLTAGE", "RAMP_VOLTAGE"] and cmd.value is None: return {"status": "error", "message": "A 'value' is required."}
    
    task = {"port_id": cmd.port_id, "command_info": {"command_type": cmd_type, "value": cmd.value, "ramp_steps": cmd.ramp_steps, "ramp_delay_s": cmd.ramp_delay_s}}
    serial_command_queue.put(task); log("INFO", f"Queued command: {task}")
    return {"status": "success", "message": f"Command '{cmd_type}' for port {cmd.port_id} queued."}

@app.post("/serial/raw-command", tags=["Serial Control"])
async def queue_raw_command(cmd: RawCommand):
    """Queues a raw command string, validating port_id dynamically."""
    if cmd.port_id not in serial_com.DEVICE_PORTS:
        valid_ports = sorted(list(serial_com.DEVICE_PORTS.keys()))
        return {"status": "error", "message": f"port_id is invalid. Valid ports are: {valid_ports}"}
    if not cmd.command: return {"status": "error", "message": "Raw command cannot be empty."}
    
    task = {"port_id": cmd.port_id, "command_info": {"command_type": "RAW", "raw_command": cmd.command}}
    serial_command_queue.put(task); log("INFO", f"Queued raw command: {task}")
    return {"status": "success", "message": f"Raw command '{cmd.command}' for port {cmd.port_id} queued."}

@app.get("/data", tags=["Data Retrieval"])
async def get_data():
    """API endpoint for monitoring data."""
    return database.get_data_from_db(limit=200)

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


    # Initialize Database Connections based on Config
    db_config = config.get('databases', {})
    # Get the single directory path, default to "data"
    db_directory = db_config.get('db_directory', 'data')
    # Get the suffix, default to an empty string (no suffix)
    db_suffix = db_config.get('db_suffix', '')
    try:
        # Initialize measurements.db using the directory and suffix
        database.init_database_connection(db_directory, suffix=db_suffix)
        log("INFO", f"Measurements DB connection initialized: {db_directory}/measurements{'_' if db_suffix else ''}{db_suffix}.db")
        database.init_db() # Create tables if they don't exist
        
        # Initialize action_log.db using the *same* directory and suffix
        log_database.init_database_connection(db_directory, suffix=db_suffix)
        log("INFO", f"Action Log DB connection initialized: {db_directory}/action_log{'_' if db_suffix else ''}{db_suffix}.db")
        log_database.init_db() # Create tables if they don't exist
    except Exception as e:
        log("ERROR", f"Failed to initialize databases in '{db_directory}': {e}"); exit(1)
    
    # Apply global settings from config
    is_test_mode = config.get('test_mode', {}).get('enabled', True)
    serial_com.IS_TEST_MODE = is_test_mode # Set mode in serial_com module
    
    # Initialize DeviceCommunicators based ONLY on what's in the config
    configured_ports = config.get('serial_ports', {})
    serial_com.DEVICE_PORTS.clear() # Ensure clean slate before populating
    initialization_ok = True
    
    if not configured_ports and not is_test_mode:
        log("ERROR", f"'serial_ports' section is empty or missing in '{args.config}' while not in test mode. Exiting.")
        exit(1)
        
    for port_id_str, port_name in configured_ports.items():
         try:
             port_id = int(port_id_str)
             communicator = serial_com.DeviceCommunicator(port_name, is_test_mode)
             serial_com.DEVICE_PORTS[port_id] = communicator
             log("INFO", f"Configured Port {port_id} using {port_name}")
             if not is_test_mode and not communicator.ser:
                 log("ERROR", f"Failed to open port {port_name} for Port {port_id}.")
                 initialization_ok = False
         except ValueError:
             log("WARN", f"Invalid port_id '{port_id_str}' in config. Skipping.")
         except Exception as e:
             log("ERROR", f"Error initializing communicator for port {port_id_str}: {e}")
             initialization_ok = False
             
    # If in test mode, ensure we have mock communicators for ports 0-3 if not defined
    if is_test_mode:
        for i in range(4): # Assume max 4 for UI consistency in test mode
             if i not in serial_com.DEVICE_PORTS:
                 mock_name = f"/dev/mockTTY{i}"
                 serial_com.DEVICE_PORTS[i] = serial_com.DeviceCommunicator(mock_name, True)
                 log("INFO", f"Using mock communicator for Port {i} ({mock_name}) as it was not in config.")

    if not initialization_ok and not is_test_mode:
         log("ERROR", "Exiting due to serial port initialization errors in non-test mode.")
         exit(1)
         
    if not serial_com.DEVICE_PORTS:
         log("ERROR", "No serial ports were configured or initialized successfully. Exiting.")
         exit(1)

    # Read server config
    server_config = config.get('server', {})
    host_to_run = server_config.get('host', '0.0.0.0')
    port_to_run = server_config.get('port', 8000)

    # Start Uvicorn server
    import uvicorn
    log("INFO", f"Starting server on {host_to_run}:{port_to_run}")
    uvicorn.run(app, host=host_to_run, port=port_to_run)