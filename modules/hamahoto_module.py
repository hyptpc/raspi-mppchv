"""
Manages hardware communication via serial ports using pyserial.
This class, SerialCommunicator (formerly DeviceCommunicator), handles the
custom command protocol (STX, ETX, Checksum) for Hamamatsu HV modules.

It provides a common interface (turn_on, set_voltage, monitor, etc.)
that the polymorphic hardware_manager worker can use.
"""
import serial
import time
from modules.logger import log
import random

# --- Constants for parsing the 'HPO' command response ---
# Indices for slicing the response string
STATUS_START, STATUS_END = 4, 8
VOLTAGE_START, VOLTAGE_END = 12, 16
CURRENT_START, CURRENT_END = 16, 20
TEMP_START, TEMP_END = 20, 24

class SerialCommunicator:
    """Handles low-level serial communication for a single serial (Hamamatsu) device."""
    
    # Conversion factors for parsing HPO response
    CONV_FACTOR_VOLT = 1.812e-3
    CONV_FACTOR_CURR = 4.980e-3
    
    def __init__(self, port_name: str, is_test_mode: bool):
        self.port_name = port_name
        self.ser = None # Initialize serial port object as None
        self.is_test_mode = is_test_mode # Store the mode

        if self.is_test_mode:
            log("MOCK", f"[Serial] Initialized mock communicator for {self.port_name}")
            # In test mode, just set 'ser' to True to indicate it's 'ready'
            self.ser = True 
            return # Don't try to open a real port in test mode

        # Attempt to open the real serial port only if not in test mode
        try:
            self.ser = serial.Serial(
                port_name,
                baudrate=38400,
                parity=serial.PARITY_EVEN,
                timeout=1 # Set a 1-second read timeout
            )
            log("INFO", f"[Serial] Successfully opened real serial port: {self.port_name}")
        except serial.SerialException as e:
            log("ERROR", f"[Serial] FATAL: Could not open port {self.port_name}. {e}")
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

    def _send_and_receive(self, command: bytes) -> bytes:
        """Sends a formatted command to the real hardware and returns the response."""
        # Check if the serial port is properly initialized and open
        if not self.ser or (not self.is_test_mode and not self.ser.is_open):
            log("ERROR", f"[Serial] [{self.port_name}] Attempted send but port is not open or initialized.")
            return b"ERROR:PORT_NOT_OPEN"
            
        full_command = self._format_command(command)
        log("SEND", f"[Serial] [{self.port_name}] {full_command}")
        
        try:
            # Clear input and output buffers
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            
            # Write the command to the serial port
            self.ser.write(full_command)
            # Ensure data is sent
            self.ser.flush()
            # Wait a short time for the device to process and respond
            time.sleep(0.1) # 100ms delay for device processing
            # Read the response line from the device
            response = self.ser.readline()
            log("RECV", f"[Serial] [{self.port_name}] {response}")
            return response
        except serial.SerialException as e:
            # Handle potential communication errors (e.g., device disconnected)
            log("ERROR", f"[Serial] [{self.port_name}] Serial communication error: {e}")
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
        log("MOCK", f"[Serial] Generated data for {self.port_name}")
        return mock_data

    # --- High-level device commands (Common Interface) ---
    
    def turn_on(self):
        """Sends the HON (HV ON) command."""
        if self.is_test_mode:
            log("MOCK", f"[Serial] [{self.port_name}] Simulating TURN_ON")
            return b"hon_ok" # Simulate a successful response
        return self._send_and_receive(b"HON")
    
    def turn_off(self):
        """Sends the HOF (HV OFF) command."""
        if self.is_test_mode:
            log("MOCK", f"[Serial] [{self.port_name}] Simulating TURN_OFF")
            return b"hof_ok"
        return self._send_and_receive(b"HOF")

    def reset_device(self):
        """Sends HRE (Reset), waits, sends HOF (HV OFF), and returns combined responses."""
        if self.is_test_mode:
            log("MOCK", f"[Serial] [{self.port_name}] Simulating RESET followed by HV OFF")
            time.sleep(0.6)
            return b"hre_ok|hof_ok|hcm0_ok" 

        # reset
        reset_response = self._send_and_receive(b"HRE")
        log("INFO", f"[Serial] [{self.port_name}] Device reset. Response: {reset_response}. Waiting...")
        time.sleep(0.2) 

        # HV off
        off_response = self._send_and_receive(b"HOF")
        log("INFO", f"[Serial] [{self.port_name}] HV OFF after reset. Response: {off_response}")

        # turn off temp. corr.
        hcm_response = self._send_and_receive(b"HCM0")
        log("INFO", f"[Serial] [{self.port_name}] Temp Corr OFF after reset. Response: {hcm_response}")

        combined_response = reset_response.strip() + b" | " + off_response.strip() + b" | " + hcm_response.strip()
        return combined_response

    def send_raw_command(self, command_str: str):
        """Sends a user-provided raw command string (e.g., "HCM1")."""
        if self.is_test_mode:
            log("MOCK", f"[Serial] [{self.port_name}] Simulating RAW command: {command_str}")
            return b"raw_ok"
        # Encode the user's string to bytes for the protocol
        return self._send_and_receive(command_str.encode('ascii'))

    def set_voltage(self, voltage: float):
        """Sends the HBV command to set voltage."""
        if self.is_test_mode:
            log("MOCK", f"[Serial] [{self.port_name}] Simulating SET_VOLTAGE to {voltage}V")
            return b"hbv_ok"
            
        # Convert voltage to 4-digit hex string required by the device
        hex_voltage_value = int(voltage / self.CONV_FACTOR_VOLT)
        hex_voltage_string = format(hex_voltage_value, "04x").encode()
        command = b"HBV" + hex_voltage_string
        return self._send_and_receive(command)

    def monitor(self) -> dict:
        """
        Sends HPO command and parses the response, or returns mock data.
        This is the source of temperature data.
        """
        if self.is_test_mode:
            return self._generate_mock_monitor_data()

        response_bytes = self._send_and_receive(b"HPO")
        if not response_bytes or b"ERROR" in response_bytes:
            log("ERROR", f"[Serial] [{self.port_name}] No valid response for MONITOR command.")
            return {"error": "No response", "raw_response": response_bytes.decode(errors='ignore')}
        
        try:
            # Decode the response bytes to an ASCII string
            response_string = response_bytes.decode('ascii')
            
            # Check for minimum length to avoid slicing errors
            if len(response_string) < TEMP_END:
                log("ERROR", f"[{self.port_name}] Received truncated response: '{response_string}'")
                return {"error": "Truncated response", "raw_response": response_string}

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
            
            temperature = None
            if status_flags["is_temp_sensor_connected"]:
                # Apply temperature conversion formula ONLY if sensor is connected
                try:
                    temperature = (temp_raw * 1.907e-5 - 1.035) / (-5.5e-3)
                    temperature = round(temperature, 3)
                except ZeroDivisionError:
                    log("WARN", f"[{self.port_name}] Temperature calculation error (ZeroDivision).")
            else:
                log("DEBUG", f"[{self.port_name}] Temp sensor not connected, temp set to None.")


            # Return parsed data as a dictionary
            return {
                "status_raw": status_int,
                "status_flags": status_flags,
                "voltage": round(voltage, 3),
                "current": round(current, 3),
                "temperature": temperature, # Will be None if sensor is not connected
                "raw_response": response_string.strip() # Include raw string for debugging
            }
        except Exception as e:
            # Catch potential errors during decoding or parsing (e.g., int(..., 16))
            log("ERROR", f"[{self.port_name}] Failed to parse response '{response_bytes}': {e}")
            return {"error": f"Parse error: {e}", "raw_response": response_bytes.decode(errors='ignore')}
