"""
Manages hardware communication via serial ports using pyserial.
This class, SerialCommunicator (formerly DeviceCommunicator), handles the
custom command protocol (STX, ETX, Checksum) for Hamamatsu HV modules.

It provides a common interface (turn_on, set_voltage, monitor, etc.)
that the polymorphic hardware_manager worker can use.
"""
import serial
import time
import math
from modules.logger import log

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
    SAFE_BASE_VOLTAGE_V = 20.5
    SAFE_BASE_TEMPERATURE_C = 25.0
    MIN_VOLTAGE_V = 20.0
    MAX_VOLTAGE_V = 90.0
    RAW_COMMANDS = frozenset({"HRT", "HPO", "HGS", "HGV", "HGC", "HGT", "HOF"})
    
    def __init__(self, port_name: str, is_test_mode: bool):
        self.port_name = port_name
        self.ser = None # Initialize serial port object as None
        self.is_test_mode = is_test_mode # Store the mode

        if self.is_test_mode:
            self._mock_hv_on = False
            self._mock_voltage_raw = int(self.SAFE_BASE_VOLTAGE_V / self.CONV_FACTOR_VOLT)
            self._mock_correction = False
            self._mock_parameters = b"0000" * 4 + b"2C31B7D7"
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
        # Keep the low byte, including a leading zero, as uppercase ASCII hex.
        return f"{total_sum & 0xFF:02X}".encode('ascii')

    def _format_command(self, command: bytes) -> bytes:
        """Builds the full command packet with STX, ETX, checksum, etc."""
        stx = b"\x02"
        etx = b"\x03"
        delimiter = b"\x0D"
        checksum = self._calculate_checksum(command)
        # Assemble the full packet
        full_command_packet = stx + command + etx + checksum + delimiter
        return full_command_packet

    def _validate_response(self, command: bytes, response: bytes) -> bytes:
        """Return a verified frame or the common ERROR result used by callers."""
        def invalid(reason):
            log("ERROR", f"[Serial] [{self.port_name}] {reason}: {response!r}")
            return f"ERROR:INVALID_RESPONSE:{reason}; raw={response!r}".encode('ascii')

        if len(response) < 8 or not response.startswith(b'\x02') or not response.endswith(b'\r'):
            return invalid('Incomplete frame')
        if response[-4:-3] != b'\x03':
            return invalid('Missing ETX')
        body = response[1:-4]
        # No embedded delimiters, binary bytes, or additional frames are allowed.
        if any(value < 0x20 or value > 0x7E for value in body):
            return invalid('Invalid ASCII body')
        hex_digits = b'0123456789ABCDEFabcdef'
        checksum = response[-3:-1]
        if any(value not in hex_digits for value in checksum):
            return invalid('Invalid checksum encoding')
        if checksum.upper() != self._calculate_checksum(body):
            return invalid('Checksum mismatch')
        if body.startswith(b'hxx'):
            log("ERROR", f"[Serial] [{self.port_name}] Device error: {response!r}")
            return b'ERROR:DEVICE_ERROR:' + body + b'; raw=' + repr(response).encode('ascii')
        response_command = command[:3].lower()
        if body[:3] != response_command:
            return invalid('Unexpected response command')

        # Fixed numeric payloads used for monitoring and the compensation interlock.
        payload_lengths = {b'hpo': 20, b'hgs': 4, b'hrt': 24,
                           b'hgv': 4, b'hgc': 4, b'hgt': 4,
                           b'hof': 0, b'hon': 0, b'hre': 0,
                           b'hcm': 0, b'hbv': 0, b'hst': 0}
        expected_length = payload_lengths.get(response_command)
        if expected_length is not None:
            payload = body[3:]
            if len(payload) != expected_length:
                return invalid('Unexpected payload length')
            if any(value not in hex_digits for value in payload):
                return invalid('Invalid hexadecimal payload')
        return response

    def _send_and_receive(self, command: bytes) -> bytes:
        """Sends a formatted command to the real hardware and returns the response."""
        if self.is_test_mode:
            response = self._mock_exchange(command)
            return self._validate_response(command, response)
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
            # Device frames end with CR, not LF.
            response = self.ser.read_until(b'\r')
            log("RECV", f"[Serial] [{self.port_name}] {response}")
            return self._validate_response(command, response)
        except serial.SerialException as e:
            # Handle potential communication errors (e.g., device disconnected)
            log("ERROR", f"[Serial] [{self.port_name}] Serial communication error: {e}")
            return b"ERROR:SERIAL_COMM_FAILED"

    def initialize_safe_state(self) -> bytes:
        """Leave output/correction OFF and persist zero coefficients with low base values.

        K29-B61218K sections 4-1/4-2: HST/HRT contain six ASCII hex words,
        ordered high/low quadratic, high/low linear, Vb, Tb. HST is persistent.
        """
        if self.is_test_mode:
            log("MOCK", f"[Serial] [{self.port_name}] Simulating safe startup")

        def request(command):
            response = self._send_and_receive(command)
            if not response or response.startswith(b"ERROR"):
                raise RuntimeError(f"{command[:3].decode('ascii')} failed: {response!r}")
            return response

        def verify_off():
            status = int(request(b"HGS")[4:8], 16)
            if status & ((1 << 0) | (1 << 6)):
                raise RuntimeError(f"Output or temperature correction is ON: {status:04X}")

        try:
            request(b"HOF")
            request(b"HCM0")
            # Verify OFF before any persistent parameter write.
            verify_off()
            parameters = request(b"HRT")[4:28]
            vb = int(self.SAFE_BASE_VOLTAGE_V / self.CONV_FACTOR_VOLT)
            tb = int((1.035 - self.SAFE_BASE_TEMPERATURE_C * 5.5e-3) / 1.907e-5)
            target = b"0000" * 4 + f"{vb:04X}{tb:04X}".encode('ascii')
            if parameters.upper() != target:
                log("INFO", f"[Serial] [{self.port_name}] Saving zero coefficients, Vb=20.5 V, Tb=25 C")
                request(b"HST" + target)
                if request(b"HRT")[4:28].upper() != target:
                    raise RuntimeError("Persistent parameter readback mismatch")
            verify_off()
            log("INFO", f"[Serial] [{self.port_name}] Startup verified: output OFF, correction OFF")
            return b"OK_SAFE_INITIALIZED_MOCK" if self.is_test_mode else b"OK_SAFE_INITIALIZED"
        except Exception as error:
            log("ERROR", f"[Serial] [{self.port_name}] Safe startup failed: {error}")
            try:
                off_response = self._send_and_receive(b"HOF")
                if not off_response or off_response.startswith(b"ERROR"):
                    log("ERROR", f"[Serial] [{self.port_name}] Fallback OFF failed: {off_response!r}")
            except Exception as off_error:
                log("ERROR", f"[Serial] [{self.port_name}] Fallback OFF raised: {off_error}")
            return f"ERROR:SAFE_INITIALIZATION:{error}".encode('utf-8', errors='replace')

    def _mock_exchange(self, command: bytes) -> bytes:
        """Model serial state using the same response parser and interlocks as hardware."""
        payload = b""
        if command == b"HOF":
            self._mock_hv_on = False
        elif command == b"HON":
            self._mock_hv_on = True
        elif command in (b"HCM0", b"HCM1"):
            self._mock_correction = command == b"HCM1"
        elif command.startswith(b"HBV") and len(command) == 7:
            self._mock_voltage_raw = int(command[3:], 16)
            self._mock_correction = False
        elif command.startswith(b"HST") and len(command) == 27:
            self._mock_parameters = command[3:].upper()
        elif command == b"HRT":
            payload = self._mock_parameters
        elif command in (b"HPO", b"HGS", b"HGV", b"HGC", b"HGT"):
            status = 8 | int(self._mock_hv_on) | (int(self._mock_correction) << 6)
            voltage = self._mock_voltage_raw if self._mock_hv_on else 0
            values = {b"HGS": f"{status:04X}".encode(),
                      b"HGV": f"{voltage:04X}".encode(), b"HGC": b"0000", b"HGT": b"B7D7"}
            payload = (f"{status:04X}0000{voltage:04X}0000B7D7".encode()
                       if command == b"HPO" else values[command])
        else:
            return self._format_command(b"hxx0005")
        return self._format_command(command[:3].lower() + payload)

    # --- High-level device commands (Common Interface) ---
    
    def turn_on(self):
        """Recheck OFF/correction/parameters and start at the low base voltage."""
        def request(command):
            response = self._send_and_receive(command)
            if not response or response.startswith(b"ERROR"):
                raise RuntimeError(f"{command[:3].decode('ascii')} failed: {response!r}")
            return response

        try:
            initialized = self.initialize_safe_state()
            if not initialized or initialized.startswith(b"ERROR"):
                raise RuntimeError(f"ON precheck failed: {initialized!r}")
            # HOF does not clear a previous temporary HBV setpoint.
            setpoint = self.set_voltage(self.SAFE_BASE_VOLTAGE_V)
            if not setpoint or setpoint.startswith(b"ERROR"):
                raise RuntimeError(f"Low-voltage setpoint failed: {setpoint!r}")
            if int(request(b"HGS")[4:8], 16) & 0x41:
                raise RuntimeError("Output or correction is ON before HON")
            response = request(b"HON")
            if int(request(b"HGS")[4:8], 16) & 0x41 != 1:
                raise RuntimeError("Output ON / correction OFF verification failed")
            return response
        except Exception as error:
            log("ERROR", f"[Serial] [{self.port_name}] TURN_ON failed: {error}")
            try:
                off_response = self.turn_off()
                log("ERROR", f"[Serial] [{self.port_name}] OFF after failed TURN_ON: {off_response!r}")
            except Exception as off_error:
                log("ERROR", f"[Serial] [{self.port_name}] OFF after failed TURN_ON raised: {off_error}")
            return f"ERROR:TURN_ON:{error}".encode('utf-8', errors='replace')
    
    def turn_off(self):
        """Sends the HOF (HV OFF) command."""
        return self._send_and_receive(b"HOF")

    def reset_device(self):
        """Reset to verified OFF settings without HRE, which enables HV output."""
        return self.initialize_safe_state()

    @classmethod
    def validate_raw_command(cls, command_str: str) -> str | None:
        if command_str.strip().upper() not in cls.RAW_COMMANDS:
            return "Only HRT, HPO, HGS, HGV, HGC, HGT, and HOF are allowed as raw commands."
        return None

    def send_raw_command(self, command_str: str):
        """Send an approved query or OFF command; never bypass output protection."""
        error = self.validate_raw_command(command_str)
        if error:
            return f"ERROR:RAW_COMMAND_NOT_ALLOWED:{error}".encode('ascii')
        command_str = command_str.strip().upper()
        # Encode the user's string to bytes for the protocol
        return self._send_and_receive(command_str.encode('ascii'))

    @classmethod
    def validate_voltage(cls, voltage: float) -> str | None:
        if not math.isfinite(voltage) or not cls.MIN_VOLTAGE_V <= voltage <= cls.MAX_VOLTAGE_V:
            return "Serial HV voltage must be between 20 and 90 V. Use TURN_OFF to disable output."
        return None

    def set_voltage(self, voltage: float):
        """Sends the HBV command to set voltage."""
        error = self.validate_voltage(voltage)
        if error:
            return f"ERROR:VOLTAGE_RANGE:{error}".encode('ascii')
        # Convert voltage to 4-digit hex string required by the device
        hex_voltage_value = max(math.ceil(self.MIN_VOLTAGE_V / self.CONV_FACTOR_VOLT),
                                int(voltage / self.CONV_FACTOR_VOLT))
        hex_voltage_string = format(hex_voltage_value, "04X").encode()
        command = b"HBV" + hex_voltage_string
        return self._send_and_receive(command)

    def monitor(self) -> dict:
        """
        Sends HPO command and parses the response, or returns mock data.
        This is the source of temperature data.
        """
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
                # Table/example convention; section 5-4 prose disagrees (see README).
                "is_temp_sensor_connected": (status_int >> 3) & 1 == 1,
                "is_temp_in_range": (status_int >> 4) & 1 == 0, # Bit 0 means IN range
                "is_temp_correction_enabled": (status_int >> 6) & 1 == 1,
            }

            if status_flags["is_temp_correction_enabled"]:
                error = "Temperature correction unexpectedly enabled; output OFF requested"
                try:
                    off_response = self.turn_off()
                except Exception as off_error:
                    off_response = f"ERROR:OFF_FAILED:{off_error}".encode('utf-8', errors='replace')
                if not off_response or off_response.startswith(b"ERROR"):
                    error += "; OFF command failed"
                log("ERROR", f"[Serial] [{self.port_name}] {error}: {off_response!r}")
                return {
                    "error": error,
                    "status_raw": status_int,
                    "status_flags": status_flags,
                    "raw_response": f"ERROR:TEMP_CORRECTION_ENABLED | HPO: {response_string.strip()} | OFF: {off_response!r}",
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
