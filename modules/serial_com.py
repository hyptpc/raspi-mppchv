"""
Manages hardware communication via serial ports.
Includes the DeviceCommunicator class and the worker/monitoring threads.
"""
import serial
import time
from queue import Queue
# Use absolute import based on project structure
from modules import db_measurements as database
from modules import db_logs as log_database
from modules.logger import log
import random
import math

# --- Configuration (Set by main.py) ---
IS_TEST_MODE = True # Default, overwritten by main.py based on config
# This dictionary will be populated by main.py after reading config
DEVICE_PORTS = {}

# --- Constants for parsing ---
# Indices for slicing the response string from the HPO command
STATUS_START, STATUS_END = 4, 8
VOLTAGE_START, VOLTAGE_END = 12, 16
CURRENT_START, CURRENT_END = 16, 20
TEMP_START, TEMP_END = 20, 24

class DeviceCommunicator:
    """Handles low-level serial communication for a single device."""
    CONV_FACTOR_VOLT = 1.812e-3
    CONV_FACTOR_CURR = 4.980e-3
    
    def __init__(self, port_name: str, is_test_mode: bool):
        self.port_name = port_name
        self.ser = None # Initialize serial port object as None
        self.is_test_mode = is_test_mode # Store the mode

        if self.is_test_mode:
            log("MOCK", f"Initialized mock communicator for {self.port_name}")
            # In test mode, just set 'ser' to True to indicate it's 'ready'
            self.ser = True 
            return # Don't try to open a real port in test mode

        # Attempt to open the real serial port only if not in test mode
        try:
            self.ser = serial.Serial(
                port_name,
                baudrate=38400,
                parity=serial.PARITY_EVEN,
                timeout=1
            )
            log("INFO", f"Successfully opened real serial port: {self.port_name}")
        except serial.SerialException as e:
            log("ERROR", f"FATAL: Could not open port {self.port_name}. {e}")
            # Ensure self.ser remains None if opening failed
            self.ser = None 
    
    def _calculate_checksum(self, command: bytes) -> bytes:
        """Calculates the checksum for a given command."""
        # Sum of bytes from command + STX (0x02) + ETX (0x03) = 5
        total_sum = sum(command) + 5
        # Convert sum to hex, take last two characters, encode to bytes
        checksum_hex = hex(total_sum)[-2:]
        return checksum_hex.encode()

    def _format_command(self, command: bytes) -> bytes:
        """Builds the full command packet with STX, ETX, checksum, etc."""
        stx = b"\x02"
        etx = b"\x03"
        delimiter = b"\x0D"
        checksum = self._calculate_checksum(command)
        # Assemble the full packet
        full_command_packet = stx + command + etx + checksum + delimiter
        return full_command_packet

    def send_and_receive(self, command: bytes) -> bytes:
        """Sends a formatted command to the real hardware and returns the response."""
        # Check if the serial port is properly initialized and open
        if not self.ser or (not self.is_test_mode and not self.ser.is_open):
            log("ERROR", f"[{self.port_name}] Attempted send but port is not open or initialized.")
            return b"ERROR:PORT_NOT_OPEN"
            
        full_command = self._format_command(command)
        log("SEND", f"[{self.port_name}] {full_command}")
        
        try:
            # Write the command to the serial port
            self.ser.write(full_command)
            # Ensure data is sent
            self.ser.flush()
            # Wait a short time for the device to process and respond
            time.sleep(0.1)
            # Read the response line from the device
            response = self.ser.readline()
            log("RECV", f"[{self.port_name}] {response}")
            return response
        except serial.SerialException as e:
            # Handle potential communication errors (e.g., device disconnected)
            log("ERROR", f"[{self.port_name}] Serial communication error: {e}")
            return b"ERROR:SERIAL_COMM_FAILED"

    def _generate_mock_monitor_data(self) -> dict:
        """Generates a realistic dictionary of mock data for testing."""
        time.sleep(0.05) # Simulate hardware delay
        mock_status_int = random.randint(0, 2**7)
        status_flags = {
            "is_hv_on": random.choice([True, False]),
            "is_overcurrent_protection_active": (mock_status_int >> 1) & 1 == 1,
            "is_current_out_of_spec": (mock_status_int >> 2) & 1 == 1,
            "is_temp_sensor_connected": (mock_status_int >> 3) & 1 == 1,
            "is_temp_in_range": (mock_status_int >> 4) & 1 == 0, # Bit 0 means IN range
            "is_temp_correction_enabled": (mock_status_int >> 6) & 1 == 1,
        }
        mock_data = {
            "status_raw": mock_status_int,
            "status_flags": status_flags,
            "voltage": round(random.uniform(65.0, 75.0), 3),
            "current": round(random.uniform(0.01, 0.1), 3),
            "temperature": round(random.uniform(20.0, 35.0), 3),
            "raw_response": "mock data"
        }
        log("MOCK", f"Generated data for {self.port_name}")
        return mock_data

    # --- High-level device commands ---
    def turn_on(self):
        """Sends the HON command."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating TURN_ON")
            return b"hon_ok" # Simulate a successful response
        return self.send_and_receive(b"HON")
    
    def turn_off(self):
        """Sends the HOF command."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating TURN_OFF")
            return b"hof_ok"
        return self.send_and_receive(b"HOF")

    def reset_device(self):
        """Sends HRE (Reset), waits, sends HOF (HV OFF), and returns combined responses."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating RESET followed by HV OFF")
            time.sleep(0.6)
            # Simulate a combined response
            return b"hre_ok|hof_ok|hcm0_ok" 

        # reset
        reset_response = self.send_and_receive(b"HRE")
        log("INFO", f"[{self.port_name}] Device reset command sent. Response: {reset_response}. Waiting...")
        time.sleep(0.2) 

        # HV off
        off_response = self.send_and_receive(b"HOF")
        log("INFO", f"[{self.port_name}] HV OFF command sent after reset. Response: {off_response}")

        # turn off temp. corr.
        hcm_response = self.send_and_receive(b"HCM0")
        log("INFO", f"[{self.port_name}] Temp Corr OFF command sent after reset. Response: {hcm_response}")

        combined_response = reset_response.strip() + b" | " + off_response.strip() + b" | " + hcm_response.strip()
        return combined_response

    def send_raw_command(self, command_str: str):
        """Sends a user-provided raw command string."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating RAW command: {command_str}")
            return b"raw_ok"
        return self.send_and_receive(command_str.encode())

    def set_voltage(self, voltage: float):
        """Sends the HBV command to set voltage."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating SET_VOLTAGE to {voltage}V")
            return b"hbv_ok"
            
        # Convert voltage to 4-digit hex string required by the device
        hex_voltage_value = int(voltage / self.CONV_FACTOR_VOLT)
        hex_voltage_string = format(hex_voltage_value, "04x").encode()
        command = b"HBV" + hex_voltage_string
        return self.send_and_receive(command)

    def monitor(self) -> dict:
        """Sends HPO command and parses the response, or returns mock data."""
        if self.is_test_mode:
            return self._generate_mock_monitor_data()

        response_bytes = self.send_and_receive(b"HPO")
        if not response_bytes or b"ERROR" in response_bytes:
            log("ERROR", f"[{self.port_name}] No valid response received for MONITOR command.")
            return {"error": "No response", "raw_response": response_bytes.decode(errors='ignore')}
        
        try:
            # Decode the response bytes to an ASCII string
            response_string = response_bytes.decode('ascii')
            
            # Extract hex values based on command reference indices
            status_hex = response_string[STATUS_START:STATUS_END]
            voltage_hex = response_string[VOLTAGE_START:VOLTAGE_END]
            current_hex = response_string[CURRENT_START:CURRENT_END]
            temp_hex = response_string[TEMP_START:TEMP_END]

            # Convert hex status to integer for bitwise operations
            status_int = int(status_hex, 16)
            
            # Parse individual status flags using bitwise operations
            status_flags = {
                "is_hv_on": (status_int >> 0) & 1 == 1,
                "is_overcurrent_protection_active": (status_int >> 1) & 1 == 1,
                "is_current_out_of_spec": (status_int >> 2) & 1 == 1,
                "is_temp_sensor_connected": (status_int >> 3) & 1 == 1,
                "is_temp_in_range": (status_int >> 4) & 1 == 0, # Bit 0 means IN range
                "is_temp_correction_enabled": (status_int >> 6) & 1 == 1,
            }

            # Convert hex values to physical units using conversion factors
            voltage = int(voltage_hex, 16) * self.CONV_FACTOR_VOLT
            current = int(current_hex, 16) * self.CONV_FACTOR_CURR
            temp_raw = int(temp_hex, 16)
            # Apply temperature conversion formula
            temperature = (temp_raw * 1.907e-5 - 1.035) / (-5.5e-3)

            # Return parsed data as a dictionary
            return {
                "status_raw": status_int,
                "status_flags": status_flags,
                "voltage": round(voltage, 3),
                "current": round(current, 3),
                "temperature": round(temperature, 3),
                "raw_response": response_string.strip() # Include raw string for debugging
            }
        except Exception as e:
            # Catch potential errors during decoding or parsing
            log("ERROR", f"[{self.port_name}] Failed to parse response '{response_bytes}': {e}")
            return {"error": f"Parse error: {e}", "raw_response": response_bytes.decode(errors='ignore')}


def generate_ramp_up_steps(start_voltage: float, target_voltage: float, num_steps: int) -> list[float]:
    """Generates a list of voltage steps with an ease-out curve (smaller steps near target)."""
    steps = []
    voltage_range = target_voltage - start_voltage

    # Handle invalid inputs gracefully
    if voltage_range <= 0 or num_steps <= 0:
        log("WARN", f"Invalid ramp parameters: range={voltage_range}, steps={num_steps}. Returning only target.")
        return [target_voltage]

    for i in range(1, num_steps + 1):
        progress = i / num_steps
        # Apply quadratic ease-out function: starts fast, ends slow
        ease_out_progress = 1 - (1 - progress)**2
        step_voltage = start_voltage + voltage_range * ease_out_progress
        steps.append(round(step_voltage, 3))

    # Ensure the final step is exactly the target voltage
    if steps and steps[-1] != target_voltage:
        # Check if the last calculated step is very close to avoid tiny final step
        if abs(steps[-1] - target_voltage) > 0.001:
             steps.append(target_voltage)
             
    # Remove potential duplicate if the last calculated step was very close
    if len(steps) > 1 and abs(steps[-2] - steps[-1]) < 0.001:
         steps.pop(-2)
         
    return steps

def generate_ramp_down_steps(start_voltage: float, target_voltage: float, num_steps: int) -> list[float]:
    """Generates voltage steps with an ease-in curve (slow start)."""
    steps = []
    voltage_range = start_voltage - target_voltage
    if voltage_range <= 0 or num_steps <= 0:
        return [target_voltage] # Already at or below target
        
    for i in range(1, num_steps + 1):
        progress = i / num_steps
        # Use a quadratic ease-in function: x^2
        # This makes the steps small at the beginning (high voltage)
        # and larger at the end (low voltage).
        ease_in_progress = progress ** 2
        step_voltage = start_voltage - (voltage_range * ease_in_progress)
        steps.append(round(step_voltage, 3))
        
    # Ensure the final step is exactly the target
    if steps and steps[-1] != target_voltage:
         steps.append(target_voltage)
         
    return steps

def worker(q: Queue):
    """The main worker function that processes tasks from the queue sequentially."""
    log("WORKER", "Thread started and waiting for tasks...")
    while True:
        task = q.get()
        port_id = task["port_id"]
        command_info = task["command_info"]
        log("WORKER", f"Got task for port {port_id}: {command_info}")
        
        communicator = DEVICE_PORTS.get(port_id)
        if not communicator or not communicator.ser:
            log("ERROR", f"Communicator for port {port_id} not available or failed. Skipping task.")
            q.task_done(); continue
            
        cmd_type = command_info["command_type"].upper()
        response = b""
        command_str_for_log = ""

        try:
            if cmd_type == "MONITOR":
                monitor_data = communicator.monitor()
                database.save_monitor_data(port_id, monitor_data)
            
            elif cmd_type == "RAMP_VOLTAGE":
                target_voltage = command_info["value"]
                command_str_for_log = f"RAMP_VOLTAGE to {target_voltage}V"
                
                log("RAMP", f"Getting current voltage for port {port_id} before ramping...")
                current_monitor_data = communicator.monitor()
                start_voltage = 20.0 # Default start voltage
                
                if "voltage" in current_monitor_data and current_monitor_data["voltage"] is not None:
                    start_voltage = current_monitor_data["voltage"]
                    log("RAMP", f"Current voltage is {start_voltage}V. Starting ramp from this value.")
                else:
                    log("WARN", f"Could not get current voltage for port {port_id}. Starting ramp from {start_voltage}V.")
                    # Optionally log the monitor error
                    if "error" in current_monitor_data:
                         log("ERROR", f"Monitor error: {current_monitor_data.get('error')}")

                # Ensure start voltage is not above target voltage for ramp up
                if start_voltage >= target_voltage:
                    log("WARN", f"Start voltage ({start_voltage}V) is already at or above target ({target_voltage}V). Setting directly.")
                    steps = [target_voltage] # Just set the target directly
                else:
                    num_steps = command_info.get("ramp_steps", 10)
                    steps = generate_ramp_up_steps(start_voltage, target_voltage, num_steps)
                
                delay_s = command_info.get("ramp_delay_s", 0.5)
                log("RAMP", f"Starting ramp on port {port_id}: {steps}")
                
                step_responses = []
                for voltage_step in steps:
                    log("RAMP", f"Setting port {port_id} to {voltage_step}V")
                    # set vol
                    step_response = communicator.set_voltage(voltage_step)
                    step_responses.append(step_response)
                    # monitor
                    monitor_data = communicator.monitor()
                    database.save_monitor_data(port_id, monitor_data)
                    time.sleep(delay_s)
                    
                response = step_responses[-1] if step_responses else b"RAMP_OK"
                log("RAMP", f"Ramp-up complete for port {port_id}. Final voltage: {target_voltage}V")

            elif cmd_type == "SET_VOLTAGE":
                target_voltage = command_info["value"]
                command_str_for_log = f"SET_VOLTAGE: {target_voltage}V"
                response = communicator.set_voltage(target_voltage)

            elif cmd_type == "TURN_ON":
                command_str_for_log = "TURN_ON"
                response = communicator.turn_on()

            # elif cmd_type == "TURN_OFF":
            #     command_str_for_log = "TURN_OFF"
            #     response = communicator.turn_off()
            elif cmd_type == "TURN_OFF":
                command_str_for_log = "RAMP_DOWN_AND_OFF"
                log("RAMP", f"Starting ramp down for port {port_id}...")
                
                # 1. Get current voltage
                current_monitor_data = communicator.monitor()
                start_voltage = 20.0 # Default start voltage
                if "voltage" in current_monitor_data and current_monitor_data["voltage"] is not None:
                    start_voltage = current_monitor_data["voltage"]
                    log("RAMP", f"Current voltage is {start_voltage}V.")
                else:
                    log("WARN", f"Could not get current voltage for {port_id}. Assuming {start_voltage}V.")

                # 2. Ramp down to 20V
                target_voltage = 20.5 # min HV value 20 V, then a bit higher vol is set
                if start_voltage > target_voltage:
                    num_steps = 10 # Use default 10 steps
                    delay_s = 0.5  # Use a faster 0.5s delay for ramp down
                    voltage_steps = generate_ramp_down_steps(start_voltage, target_voltage, num_steps)
                    log("RAMP", f"Ramping down on port {port_id}: {voltage_steps}")
                    
                    step_responses = []
                    for voltage_step in voltage_steps:
                        log("RAMP", f"Setting port {port_id} to {voltage_step}V")
                        # set vol
                        step_res = communicator.set_voltage(voltage_step)
                        step_responses.append(step_res)
                        # monitor
                        monitor_data = communicator.monitor()
                        database.save_monitor_data(port_id, monitor_data)
                        time.sleep(delay_s)
                    log("RAMP", f"Port {port_id} ramp down to 20V complete.")
                else:
                    log("RAMP", f"Voltage {start_voltage}V is already at or below 20V. Skipping ramp.")

                # 3. Send final HOF command
                log("INFO", f"Sending final TURN_OFF (HOF) to port {port_id}.")
                response = communicator.turn_off()

            elif cmd_type == "RESET":
                command_str_for_log = "RESET"
                response = communicator.reset_device()

            elif cmd_type == "RAW":
                raw_cmd = command_info.get("raw_command", "")
                command_str_for_log = f"RAW: {raw_cmd}"
                response = communicator.send_raw_command(raw_cmd)
            
            else:
                log("ERROR", f"Unknown command type received by worker: {cmd_type}")

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
    """Periodically queues MONITOR commands for the specified active ports."""
    log("MONITOR", f"Loop started. Interval: {interval_seconds}s for ports: {port_ids_to_monitor}.")
    time.sleep(2) # Give worker thread time to initialize fully
    while True:
        log("MONITOR", f"Queuing MONITOR commands for ports: {port_ids_to_monitor}...")
        active_port_count = 0
        
        # Iterate over the list of port IDs provided by main.py
        for port_id in port_ids_to_monitor:
            # Double-check if the port communicator exists and is operational
            if port_id in DEVICE_PORTS and DEVICE_PORTS[port_id].ser:
                task = {
                    "port_id": port_id,
                    "command_info": { "command_type": "MONITOR" }
                }
                q.put(task)
                active_port_count += 1
                
        if active_port_count == 0:
            log("WARN", "Monitoring loop found no active/configured ports to monitor.")
            
        time.sleep(interval_seconds)