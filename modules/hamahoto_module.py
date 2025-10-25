"""
Manages hardware communication for the original custom HV modules via serial.
Implements the common communicator interface required by hardware_manager.py.
"""
import serial
import time
from queue import Queue
from modules import db_measurements as database
from modules import db_logs as log_database
from modules.logger import log
import random
import math

# --- Constants for parsing ---
# Indices for slicing the response string from the HPO command
STATUS_START, STATUS_END = 4, 8
VOLTAGE_START, VOLTAGE_END = 12, 16
CURRENT_START, CURRENT_END = 16, 20
TEMP_START, TEMP_END = 20, 24

class SerialCommunicator:
    """Handles low-level serial communication for a single device."""
    CONV_FACTOR_VOLT = 1.812e-3
    CONV_FACTOR_CURR = 4.980e-3
    
    def __init__(self, port_name: str, is_test_mode: bool):
        self.port_name = port_name
        self.ser = None # Initialize serial port object as None
        self.is_test_mode = is_test_mode

        # Add 'instrument' attribute for compatibility check in worker
        # This communicator *is not* a VISA instrument.
        self.instrument = False

        if self.is_test_mode:
            log("MOCK", f"Initialized mock communicator for {self.port_name}")
            # 'ser' is the initialization flag for this class
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
            self.ser = None # Ensure self.ser remains None if opening failed
    
    def _calculate_checksum(self, command: bytes) -> bytes:
        """Calculates the checksum for a given command."""
        total_sum = sum(command) + 5 # STX (0x02) + ETX (0x03)
        checksum_hex = hex(total_sum)[-2:]
        return checksum_hex.encode()

    def _format_command(self, command: bytes) -> bytes:
        """Builds the full command packet with STX, ETX, checksum, etc."""
        stx = b"\x02"
        etx = b"\x03"
        delimiter = b"\x0D"
        checksum = self._calculate_checksum(command)
        full_command_packet = stx + command + etx + checksum + delimiter
        return full_command_packet

    def _send_and_receive(self, command: bytes) -> bytes:
        """Sends a formatted command to the real hardware and returns the response."""
        if not self.ser or (not self.is_test_mode and not self.ser.is_open):
            log("ERROR", f"[{self.port_name}] Attempted send but port is not open.")
            return b"ERROR:PORT_NOT_OPEN"
            
        full_command = self._format_command(command)
        log("SEND", f"[{self.port_name}] {full_command}")
        
        try:
            self.ser.write(full_command)
            self.ser.flush()
            time.sleep(0.1) # Wait for device to process
            response = self.ser.readline()
            log("RECV", f"[{self.port_name}] {response}")
            return response
        except serial.SerialException as e:
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
            "status_flags": status_flags, # This key is different from Kikusui
            "voltage": round(random.uniform(65.0, 75.0), 3),
            "current": round(random.uniform(0.01, 0.1), 3),
            "temperature": round(random.uniform(20.0, 35.0), 3),
            "raw_response": "mock data"
        }
        log("MOCK", f"Generated data for {self.port_name}")
        return mock_data

    # --- 1. Common Interface Methods ---
    # These methods MUST match the names in KikusuiCommunicator
    
    def turn_on(self):
        """Sends the HON command (Common Interface)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating TURN_ON")
            return b"hon_ok"
        return self._send_and_receive(b"HON")
    
    def turn_off(self):
        """Sends the HOF command (Common Interface)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating TURN_OFF")
            return b"hof_ok"
        return self._send_and_receive(b"HOF")

    def reset_device(self):
        """Sends HRE (Reset), waits, and sends HOF (HV OFF) (Common Interface)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating RESET followed by HV OFF")
            time.sleep(0.6)
            return b"hre_ok|hof_ok|hcm0_ok" 

        reset_response = self._send_and_receive(b"HRE")
        log("INFO", f"[{self.port_name}] Device reset. Resp: {reset_response}. Waiting...")
        time.sleep(0.2) 
        off_response = self._send_and_receive(b"HOF")
        log("INFO", f"[{self.port_name}] HV OFF after reset. Resp: {off_response}")
        hcm_response = self._send_and_receive(b"HCM0")
        log("INFO", f"[{self.port_name}] Temp Corr OFF after reset. Resp: {hcm_response}")

        combined_response = reset_response.strip() + b" | " + off_response.strip() + b" | " + hcm_response.strip()
        return combined_response

    def send_raw_command(self, command_str: str):
        """Sends a user-provided raw command string (Common Interface)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating RAW command: {command_str}")
            return b"raw_ok"
        return self._send_and_receive(command_str.encode())

    def set_voltage(self, voltage: float):
        """Sends the HBV command to set voltage (Common Interface)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.port_name}] Simulating SET_VOLTAGE to {voltage}V")
            return b"hbv_ok"
            
        hex_voltage_value = int(voltage / self.CONV_FACTOR_VOLT)
        hex_voltage_string = format(hex_voltage_value, "04x").encode()
        command = b"HBV" + hex_voltage_string
        return self._send_and_receive(command)

    def monitor(self) -> dict:
        """Sends HPO command and parses the response (Common Interface)."""
        if self.is_test_mode:
            return self._generate_mock_monitor_data()

        response_bytes = self._send_and_receive(b"HPO")
        if not response_bytes or b"ERROR" in response_bytes:
            log("ERROR", f"[{self.port_name}] No valid HPO response received.")
            return {"error": "No response", "raw_response": response_bytes.decode(errors='ignore')}
        
        try:
            response_string = response_bytes.decode('ascii')
            
            status_hex = response_string[STATUS_START:STATUS_END]
            voltage_hex = response_string[VOLTAGE_START:VOLTAGE_END]
            current_hex = response_string[CURRENT_START:CURRENT_END]
            temp_hex = response_string[TEMP_START:TEMP_END]

            status_int = int(status_hex, 16)
            
            status_flags = {
                "is_hv_on": (status_int >> 0) & 1 == 1,
                "is_overcurrent_protection_active": (status_int >> 1) & 1 == 1,
                "is_current_out_of_spec": (status_int >> 2) & 1 == 1,
                "is_temp_sensor_connected": (status_int >> 3) & 1 == 1,
                "is_temp_in_range": (status_int >> 4) & 1 == 0,
                "is_temp_correction_enabled": (status_int >> 6) & 1 == 1,
            }

            voltage = int(voltage_hex, 16) * self.CONV_FACTOR_VOLT
            current = int(current_hex, 16) * self.CONV_FACTOR_CURR
            temp_raw = int(temp_hex, 16)
            temperature = (temp_raw * 1.907e-5 - 1.035) / (-5.5e-3)

            return {
                "status_raw": status_int,
                "status_flags": status_flags, # Worker needs to differentiate based on this key
                "voltage": round(voltage, 3),
                "current": round(current, 3),
                "temperature": round(temperature, 3),
                "raw_response": response_string.strip()
            }
        except Exception as e:
            log("ERROR", f"[{self.port_name}] Failed to parse HPO response '{response_bytes}': {e}")
            return {"error": f"Parse error: {e}", "raw_response": response_bytes.decode(errors='ignore')}

    # --- 2. Serial-Specific Methods ---
    # (None currently, but could be added here)

