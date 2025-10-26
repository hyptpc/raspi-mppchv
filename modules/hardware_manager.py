"""
Handles the hardware command queue worker and monitoring loop.
This file also contains the shared DEVICE_PORTS dictionary
populated by main.py.

This worker is polymorphic: it uses hasattr() and isinstance()
to handle different communicator objects (SerialCommunicator, KikusuiCommunicator)
that share a common interface.
"""
import time
from queue import Queue
from modules import db_measurements as database
from modules import db_logs as log_database
from modules.logger import log

# --- Import BOTH Communicator Classes (for type checking) ---
from modules.hamahoto_module import SerialCommunicator
from modules.kikusui_module import KikusuiCommunicator

# --- Shared Resources ---
# These dictionaries are populated by main.py with mixed object types
DEVICE_PORTS = {}
DEVICE_MAPPINGS = {} # e.g., {3: 1} means Port 3 (Kikusui) uses Port 1 (Serial) for Temp
IS_TEST_MODE = True # Overwritten by main.py

def generate_ramp_up_steps(start_voltage: float, target_voltage: float, num_steps: int) -> list[float]:
    """Generates a list of voltage steps with an ease-out curve (smaller steps near target)."""
    steps = []
    voltage_range = target_voltage - start_voltage
    if voltage_range <= 0 or num_steps <= 0:
        return [target_voltage]
    for i in range(1, num_steps + 1):
        progress = i / num_steps
        ease_out_progress = 1 - (1 - progress)**2
        step_voltage = start_voltage + voltage_range * ease_out_progress
        steps.append(round(step_voltage, 3))
    if steps and steps[-1] != target_voltage:
        if abs(steps[-1] - target_voltage) > 0.001:
             steps.append(target_voltage)
    if len(steps) > 1 and abs(steps[-2] - steps[-1]) < 0.001:
         steps.pop(-2)
    return steps

def generate_ramp_down_steps(start_voltage: float, target_voltage: float, num_steps: int) -> list[float]:
    """Generates voltage steps with an ease-in curve (slow start)."""
    steps = []
    voltage_range = start_voltage - target_voltage
    if voltage_range <= 0 or num_steps <= 0:
        return [target_voltage]
    for i in range(1, num_steps + 1):
        progress = i / num_steps
        ease_in_progress = progress ** 2
        step_voltage = start_voltage - (voltage_range * ease_in_progress)
        steps.append(round(step_voltage, 3))
    if steps and steps[-1] != target_voltage:
         steps.append(target_voltage)
    return steps

def worker(q: Queue):
    """
    The main polymorphic worker function that processes tasks from the queue
    and "differentiates" (sumiwake) command handling based on the communicator type.
    """
    log("WORKER", "Polymorphic worker thread started and waiting for tasks...")
    while True:
        task = q.get()
        port_id = task["port_id"]
        command_info = task["command_info"]
        log("WORKER", f"Got task for port {port_id}: {command_info}")
        
        communicator = DEVICE_PORTS.get(port_id)
        
        # Check 1: Communicator exists
        if not communicator:
            log("ERROR", f"Communicator for port {port_id} not available. Skipping task.")
            q.task_done(); continue
        
        # Check 2: Communicator is initialized (handles both .ser and .instrument)
        is_initialized = False
        if hasattr(communicator, 'ser'):       # For SerialCommunicator
            is_initialized = is_initialized or communicator.ser
        if hasattr(communicator, 'instrument'): # For KikusuiCommunicator
            is_initialized = is_initialized or communicator.instrument

        if not is_initialized:
             log("ERROR", f"Communicator for port {port_id} failed initialization. Skipping task.")
             q.task_done(); continue
            
        cmd_type = command_info["command_type"].upper()
        response = b""
        command_str_for_log = ""
        value = command_info.get("value")

        try:
            # --- 1. Common Interface Commands ---
            
            if cmd_type == "MONITOR":
                command_str_for_log = "" # Don't log monitor actions
                
                # --- Data Combination Logic ---
                
                # 1. Get primary data from the port that was tasked
                primary_data = communicator.monitor()
                if "error" in primary_data:
                    log("ERROR", f"Monitor error on primary port {port_id}: {primary_data.get('error')}")
                    # Save the error state and continue
                    database.save_monitor_data(port_id, primary_data)
                    q.task_done(); continue

                # 2. Check if this port_id is a primary device in the mapping
                temp_port_id = DEVICE_MAPPINGS.get(port_id)
                
                if temp_port_id is not None: # Ensure temp_port_id is explicitly checked against None
                    # This is a primary port (e.g., Kikusui) that needs temperature data
                    log("DEBUG", f"Port {port_id} needs temp data from Port {temp_port_id}.")
                    temp_communicator = DEVICE_PORTS.get(temp_port_id)
                    
                    if temp_communicator and isinstance(temp_communicator, SerialCommunicator):
                        # 3. Get temperature data from the mapped Serial port
                        temp_data = temp_communicator.monitor()
                        
                        if "error" in temp_data:
                            log("WARN", f"Could not get temp data from {temp_port_id}: {temp_data.get('error')}")
                            # Combine anyway, but without temp data
                            combined_data = primary_data
                        else:
                            # 4. Combine the data
                            combined_data = primary_data.copy()
                            # Add temperature data from the serial device
                            combined_data["temperature"] = temp_data.get("temperature")
                            # Add serial status flags (contains temp flags)
                            combined_data["status_flags"] = temp_data.get("status_flags", {})
                            # Add serial raw status int
                            combined_data["status_raw"] = temp_data.get("status_raw")
                            
                            # Combine raw responses for debugging
                            combined_data["raw_response"] = (
                                f"PRIMARY_RAW: {primary_data.get('raw_response', '')} | "
                                f"TEMP_RAW: {temp_data.get('raw_response', '')}"
                            )
                            log("DEBUG", f"Combined data for Port {port_id}: {combined_data}")
                        
                        # 5. Save the combined data under the *primary* port_id
                        database.save_monitor_data(port_id, combined_data)
                        
                    else:
                        log("WARN", f"Mapped temp port {temp_port_id} for {port_id} is not a valid SerialCommunicator or doesn't exist.")
                        # Save just the primary data
                        database.save_monitor_data(port_id, primary_data)
                
                else:
                    # This port is not a primary mapped device.
                    # Check if it's a temp sensor that is *being used* by another port
                    is_mapped_temp_sensor = port_id in DEVICE_MAPPINGS.values()
                    
                    if is_mapped_temp_sensor and isinstance(communicator, SerialCommunicator):
                        # This is a temperature sensor. Its data is fetched by its
                        # primary port (e.g., Kikusui). To avoid double entries,
                        # we skip saving its standalone monitor task.
                        log("DEBUG", f"Port {port_id} is a mapped temp sensor. Skipping standalone save.")
                    else:
                        # This is a standalone device (e.g., another Kikusui or Serial).
                        # Save its data normally.
                        log("DEBUG", f"Port {port_id} is standalone. Saving its data.")
                        database.save_monitor_data(port_id, primary_data)
                        
                # --- ▲▲▲ END Data Combination Logic ▲▲▲ ---

            elif cmd_type == "SET_VOLTAGE":
                command_str_for_log = f"SET_VOLTAGE: {value}V"
                response = communicator.set_voltage(value)

            elif cmd_type == "TURN_ON":
                command_str_for_log = "TURN_ON"
                response = communicator.turn_on()
                
            elif cmd_type == "TURN_OFF":
                command_str_for_log = "TURN_OFF (with Ramp Down)"
                
                log("RAMP", f"Starting ramp down for port {port_id} before turning off...")
                current_monitor_data = communicator.monitor()
                start_voltage = 20.0 # temporary input some value
                if "voltage" in current_monitor_data and current_monitor_data["voltage"] is not None:
                    start_voltage = current_monitor_data["voltage"]
                else:
                    log("WARN", f"Could not get current voltage for {port_id}. Assuming {start_voltage}V.")
                
                target_voltage = 20.5 # Min HV value
                if start_voltage > target_voltage:
                    steps = generate_ramp_down_steps(start_voltage, target_voltage, 25)
                    for voltage_step in steps:
                        communicator.set_voltage(voltage_step)
                        monitor_data = communicator.monitor()
                        # Apply combination logic if needed (copy from MONITOR task)
                        temp_port_id = DEVICE_MAPPINGS.get(port_id)
                        if temp_port_id is not None:
                            temp_communicator = DEVICE_PORTS.get(temp_port_id)
                            if temp_communicator and isinstance(temp_communicator, SerialCommunicator):
                                temp_data = temp_communicator.monitor()
                                if "error" not in temp_data:
                                    monitor_data["temperature"] = temp_data.get("temperature")
                                    monitor_data["status_flags"] = temp_data.get("status_flags", {})
                                    monitor_data["status_raw"] = temp_data.get("status_raw")
                                    monitor_data["raw_response"] = f"PRI:{monitor_data.get('raw_response', '')}|TEMP:{temp_data.get('raw_response', '')}"
                                else:
                                    log("WARN", f"Could not get temp data from {temp_port_id} during ramp.")
                            else:
                                log("WARN", f"Mapped temp port {temp_port_id} invalid during ramp.")

                        database.save_monitor_data(port_id, monitor_data) # Save immediately (combined or not)
                        time.sleep(1)
                        
                monitor_task = {"port_id": port_id, "command_info": {"command_type": "MONITOR"}}
                q.put(monitor_task)
                log("INFO", f"Sending final TURN_OFF to port {port_id}.")
                response = communicator.turn_off()

            elif cmd_type == "RESET":
                command_str_for_log = "RESET"
                response = communicator.reset_device()

            elif cmd_type == "RAMP_VOLTAGE":
                command_str_for_log = f"RAMP_VOLTAGE to {value}V"
                current_monitor_data = communicator.monitor()
                start_voltage = 20.0
                if "voltage" in current_monitor_data and current_monitor_data["voltage"] is not None:
                    start_voltage = current_monitor_data["voltage"]
                
                if start_voltage >= value:
                    steps = [value]
                else:
                    steps = generate_ramp_up_steps(start_voltage, value, command_info.get("ramp_steps", 20))
                
                delay_s = command_info.get("ramp_delay_s", 0.5)
                step_responses = []
                for voltage_step in steps:
                    step_response = communicator.set_voltage(voltage_step)
                    step_responses.append(step_response)
                    log("DEBUG", f"RAMP UP step: Monitoring port {port_id} after setting {voltage_step}V")
                    monitor_data = communicator.monitor()
                    # Apply combination logic if needed (copy from MONITOR task)
                    temp_port_id = DEVICE_MAPPINGS.get(port_id)
                    if temp_port_id is not None:
                         temp_communicator = DEVICE_PORTS.get(temp_port_id)
                         if temp_communicator and isinstance(temp_communicator, SerialCommunicator):
                             temp_data = temp_communicator.monitor()
                             if "error" not in temp_data:
                                 monitor_data["temperature"] = temp_data.get("temperature")
                                 monitor_data["status_flags"] = temp_data.get("status_flags", {})
                                 monitor_data["status_raw"] = temp_data.get("status_raw")
                                 monitor_data["raw_response"] = f"PRI:{monitor_data.get('raw_response', '')}|TEMP:{temp_data.get('raw_response', '')}"
                             else:
                                 log("WARN", f"Could not get temp data from {temp_port_id} during ramp.")
                         else:
                             log("WARN", f"Mapped temp port {temp_port_id} invalid during ramp.")

                    database.save_monitor_data(port_id, monitor_data) # Save immediately (combined or not)
                    time.sleep(delay_s) # Keep the delay
                response = step_responses[-1] if step_responses else b"RAMP_OK"
                log("RAMP", f"Ramp up complete for port {port_id}.")
                
            # --- 2. Kikusui-Specific Commands ---
            # Differentiation Pattern 2 (hasattr)
            
            elif cmd_type == "SET_CURRENT":
                command_str_for_log = f"SET_CURRENT: {value}A"
                if hasattr(communicator, "set_current"):
                    response = communicator.set_current(value)
                else:
                    response = b"ERROR:COMMAND_NOT_SUPPORTED"
                    log("WARN", f"Port {port_id} (Type: {type(communicator).__name__}) does not support SET_CURRENT.")

            elif cmd_type == "ENABLE_OCP":
                command_str_for_log = f"ENABLE_OCP: {value}A"
                if hasattr(communicator, "enable_ocp"):
                    response = communicator.enable_ocp(value)
                else:
                    response = b"ERROR:COMMAND_NOT_SUPPORTED"
                    log("WARN", f"Port {port_id} (Type: {type(communicator).__name__}) does not support ENABLE_OCP.")
            
            # --- 3. Other Commands ---
            
            elif cmd_type == "RAW":
                raw_cmd = command_info.get("raw_command", "")
                command_str_for_log = f"RAW: {raw_cmd}"
                response = communicator.send_raw_command(raw_cmd)
            
            else:
                log("ERROR", f"Unknown command type received by worker: {cmd_type}")
                response = b"ERROR:UNKNOWN_COMMAND_TYPE"

            # Log actions (excluding MONITOR) after execution
            if command_str_for_log:
                log_database.save_action_log(port_id, command_str_for_log, response)
                log("ACTION", f"Logged for port {port_id}: {command_str_for_log}")

        except Exception as e:
            log("ERROR", f"Exception during command {cmd_type} for port {port_id}: {e}")
            error_cmd_str = f"ERROR executing {cmd_type}"
            log_database.save_action_log(port_id, error_cmd_str, str(e).encode())
            
        finally:
            q.task_done()

def monitoring_loop(q: Queue, interval_seconds: int, port_ids_to_monitor: list[int]):
    """Periodically queues MONITOR commands for all active ports."""
    log("MONITOR", f"Loop started. Interval: {interval_seconds}s for ports: {port_ids_to_monitor}.")
    time.sleep(2) # Give worker thread time to initialize fully
    while True:
        log("MONITOR", f"Queuing MONITOR commands for ports: {port_ids_to_monitor}...")
        active_port_count = 0
        
        for port_id in port_ids_to_monitor:
            if port_id in DEVICE_PORTS:
                communicator = DEVICE_PORTS[port_id]
                
                is_initialized = False
                if hasattr(communicator, 'ser'):
                    is_initialized = is_initialized or communicator.ser
                if hasattr(communicator, 'instrument'):
                    is_initialized = is_initialized or communicator.instrument

                if communicator and is_initialized:
                    task = {
                        "port_id": port_id,
                        "command_info": { "command_type": "MONITOR" }
                    }
                    q.put(task)
                    active_port_count += 1
                else:
                    log("WARN", f"Skipping monitor for port {port_id}: communicator not initialized.")
            else:
                log("WARN", f"Skipping monitor for port {port_id}: port not configured in DEVICE_PORTS.")
                
        if active_port_count == 0:
            log("WARN", "Monitoring loop found no active/configured ports to monitor.")
            
        time.sleep(interval_seconds)

