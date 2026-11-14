"""
Manages hardware communication for KIKUSUI power supplies using PyVISA.
This class, KikusuiCommunicator, handles the SCPI command protocol
for Kikusui PMX-A series power supplies.

It provides a common interface (turn_on, set_voltage, monitor, etc.)
that the polymorphic hardware_manager worker can use, plus specific
methods like enable_ocp.
"""
import pyvisa
import time
import math
from modules.logger import log

class KikusuiCommunicator:
    SAFE_START_VOLTAGE_V = 0.0
    # --- Constants for Status Register Bits for PMX18-2A ---
    # From the STATus:OPERation register
    # Bit 4: CC mode (1 = is in CC mode)
    CC_MODE_BIT = 4

    # From the STATus:QUEStionable register
    # Bit 4: OCP (1 = OCP has tripped)
    OCP_TRIP_BIT = 4
    RAW_QUERIES = {
        '*IDN?': '*IDN?',
        'MEAS:VOLT?': 'MEASure:VOLTage?',
        'MEASURE:VOLTAGE?': 'MEASure:VOLTage?',
        'MEAS:CURR?': 'MEASure:CURRent?',
        'MEASURE:CURRENT?': 'MEASure:CURRent?',
        'OUTP?': 'OUTPut:STATe?',
        'OUTPUT?': 'OUTPut:STATe?',
        'OUTP:STAT?': 'OUTPut:STATe?',
        'OUTPUT:STATE?': 'OUTPut:STATe?',
        'STAT:OPER:COND?': 'STATus:OPERation:CONDition?',
        'STATUS:OPERATION:CONDITION?': 'STATus:OPERation:CONDition?',
        'STAT:QUES:EVEN?': 'STATus:QUEStionable:EVENt?',
        'STATUS:QUESTIONABLE:EVENT?': 'STATus:QUEStionable:EVENt?',
    }

    """Handles low-level PyVISA communication for a single KIKUSUI device."""
    
    def __init__(self, resource_string: str, is_test_mode: bool):
        self.resource_string = resource_string
        self.instrument = None # Initialize instrument object as None
        self.is_test_mode = is_test_mode

        if self.is_test_mode:
            self._mock_is_on = False
            self._mock_voltage = 0.0
            self._mock_current_a = 0.0
            self._mock_current_limit_a = 0.0
            self._mock_ocp_enabled = False
            self._mock_ocp_level_a = 0.0
            log("MOCK", f"[Kikusui] Initialized mock communicator for {self.resource_string}")
            # In test mode, just set 'instrument' to True to indicate it's 'ready'
            self.instrument = True 
            return # Don't try to open a real instrument in test mode

        # Attempt to open the real VISA resource
        try:
            # Specify '@py' to use the pyvisa-py backend
            rm = pyvisa.ResourceManager('@py')
            self.instrument = rm.open_resource(self.resource_string)
            self.instrument.timeout = 5000 # Set a 5-second timeout
            
            # Reconnecting must preserve an already-running supply and its events.
            # Identification is a query; do not reset or clear the instrument here.
            idn = self.instrument.query('*IDN?')
            log("INFO", f"[Kikusui] Successfully connected to {self.resource_string}. ID: {idn.strip()}")
            
        except pyvisa.errors.VisaIOError as e:
            log("ERROR", f"[Kikusui] FATAL: Could not open {self.resource_string}. {e}")
            self.instrument = None # Ensure self.instrument remains None if opening failed
    
    def _write(self, command: str) -> bytes:
        """Private method to send a write-only command."""
        if not self.instrument:
            log("ERROR", f"[Kikusui] [{self.resource_string}] Attempted write but instrument is not open.")
            return b"ERROR:NOT_OPEN"
            
        log("SEND", f"[Kikusui] [{self.resource_string}] {command}")
        try:
            self.instrument.write(command)
            return b"OK" # Return bytes for compatibility with worker logging
        except pyvisa.errors.VisaIOError as e:
            log("ERROR", f"[Kikusui] [{self.resource_string}] VISA write error: {e}")
            return b"ERROR:VISA_WRITE_FAILED"

    def _query(self, command: str) -> bytes:
        """Private method to send a query command and get a response."""
        if self.is_test_mode:
            values = {'*IDN?': 'KIKUSUI,MOCK,0,0',
                      'SOURce:VOLTage?': self._mock_voltage,
                      'MEASure:VOLTage?': self._mock_voltage if self._mock_is_on else 0.0,
                      'MEASure:CURRent?': self._mock_current_a if self._mock_is_on else 0.0,
                      'OUTPut:STATe?': int(self._mock_is_on),
                      'STATus:OPERation:CONDition?': 0, 'STATus:QUEStionable:EVENt?': 0}
            return str(values[command]).encode('ascii')
        if not self.instrument:
            log("ERROR", f"[Kikusui] [{self.resource_string}] Attempted query but instrument is not open.")
            return b"ERROR:NOT_OPEN"

        log("SEND", f"[Kikusui] [{self.resource_string}] {command}")
        try:
            response_str = self.instrument.query(command)
            # Return raw bytes for compatibility with worker logging
            return response_str.strip().encode('ascii') 
        except pyvisa.errors.VisaIOError as e:
            log("ERROR", f"[Kikusui] [{self.resource_string}] VISA query error: {e}")
            # Handle specific timeout error
            if "VI_ERROR_TMO" in str(e):
                log("ERROR", f"[Kikusui] [{self.resource_string}] TIMEOUT waiting for response to '{command}'")
                return b"ERROR:VISA_TIMEOUT"
            return b"ERROR:VISA_QUERY_FAILED"

    # --- High-level device commands (Common Interface) ---

    def get_voltage_setpoint(self) -> float:
        """Read the retained setting, including while the output is OFF."""
        response = self._query('SOURce:VOLTage?')
        if not response or response.startswith(b'ERROR'):
            raise ValueError(f'Cannot read voltage setpoint: {response!r}')
        try:
            voltage = float(response.decode('ascii'))
        except (ValueError, UnicodeError) as error:
            raise ValueError('Invalid voltage setpoint response') from error
        if not math.isfinite(voltage) or voltage < 0:
            raise ValueError('Voltage setpoint must be finite and non-negative')
        return voltage
    
    def turn_on(self):
        """Enable an OFF supply only after setting and verifying zero volts."""
        state = self._query('OUTPut:STATe?')
        if state == b'1':
            return b'OK_ALREADY_ON'
        if state != b'0':
            return b'ERROR:TURN_ON:OUTPUT_STATE_UNKNOWN'
        response = self.set_voltage(self.SAFE_START_VOLTAGE_V)
        if not response or response.startswith(b'ERROR'):
            return b'ERROR:TURN_ON:ZERO_VOLTAGE_WRITE_FAILED'
        try:
            if self.get_voltage_setpoint() != self.SAFE_START_VOLTAGE_V:
                return b'ERROR:TURN_ON:ZERO_VOLTAGE_READBACK_MISMATCH'
        except ValueError as error:
            return f'ERROR:TURN_ON:{error}'.encode()
        if self.is_test_mode:
            self._mock_is_on = True
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating TURN_ON")
            return b"OK_ON"
        return self._write("OUTPut:STATe ON")
    
    def turn_off(self):
        """Sends the OUTP OFF command """
        if self.is_test_mode:
            self._mock_is_on = False
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating TURN_OFF")
            return b"OK_OFF"
        return self._write("OUTPut:STATe OFF")

    def reset_device(self):
        """Clear a protection alarm without resetting output settings."""
        return self.clear_protection_trip()

    @classmethod
    def validate_raw_command(cls, command_str: str) -> str | None:
        if command_str.strip().upper() not in cls.RAW_QUERIES:
            return "Only approved identification, measurement, and status queries are allowed."
        return None

    def send_raw_command(self, command_str: str):
        """Execute an approved query and consume its response."""
        error = self.validate_raw_command(command_str)
        if error:
            return f"ERROR:RAW_COMMAND_NOT_ALLOWED:{error}".encode('ascii')
        command_str = self.RAW_QUERIES[command_str.strip().upper()]
        return self._query(command_str)

    def set_voltage(self, voltage: float):
        """Sends the SOURce:VOLTage command to set the output voltage."""
        if self.is_test_mode:
            self._mock_voltage = voltage
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating SET_VOLTAGE to {voltage}V")
            return b"OK_VOLT"
        
        command = f"SOURce:VOLTage {voltage:.3f}"
        return self._write(command)

    # --- KIKUSUI-specific methods (Not in the common interface) ---

    def set_current(self, current: float):
        """Sets the Constant Current (CC) level (SOURce:CURRent)."""
        if self.is_test_mode:
            self._mock_current_limit_a = current
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating SET_CURRENT to {current}A")
            return b"OK_CURR"
        command = f"SOURce:CURRent {current:.3f}"
        return self._write(command)

    def enable_ocp(self, trip_current: float):
        """Enables Over-Current Protection (OCP) and sets the trip level."""
        if self.is_test_mode:
            self._mock_ocp_enabled = True
            self._mock_ocp_level_a = trip_current
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating ENABLE_OCP to {trip_current}A")
            return b"OK_OCP"
        
        # Set level and enable OCP in one command
        command = f"CURRent:PROTection:LEVel {trip_current:.3f}; CURRent:PROTection:STATe ON"
        return self._write(command)

    def disable_ocp(self):
        """Disables Over-Current Protection (OCP)."""
        if self.is_test_mode:
            self._mock_ocp_enabled = False
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating DISABLE_OCP")
            return b"OK_OCP_OFF"
        return self._write("CURRent:PROTection:STATe OFF")
    
    def clear_protection_trip(self):
        """
        Clears a latched protection trip (like OCP or OVP).
        On PMX-A, this is 'OUTPut:PROTection:CLEar'.
        """
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating CLEAR_TRIP")
            return b"OK_TRIP_CLEAR"
        return self._write("OUTPut:PROTection:CLEar")

    def monitor(self) -> dict:
        """
        Fetches measurements and status, including CC mode and OCP trip events.
        Returns voltage in V and measured current in mA for the shared DB/UI.
        """
        try:
            # --- MODIFIED: Switched to individual 'query' calls to prevent timeouts ---
            # 1. Get Voltage
            voltage_bytes = self._query("MEASure:VOLTage?")
            if b"ERROR" in voltage_bytes: raise Exception(f"Failed to query VOLT: {voltage_bytes.decode()}")
            voltage_str = voltage_bytes.decode('ascii')
            
            # 2. Get Current
            current_bytes = self._query("MEASure:CURRent?")
            if b"ERROR" in current_bytes: raise Exception(f"Failed to query CURR: {current_bytes.decode()}")
            current_str = current_bytes.decode('ascii')
            
            # 3. Get Output State
            status_bytes = self._query("OUTPut:STATe?")
            if b"ERROR" in status_bytes: raise Exception(f"Failed to query STAT: {status_bytes.decode()}")
            status_str = status_bytes.decode('ascii')
            
            # 4. Get Operation Status (for CC mode)
            op_cond_bytes = self._query("STATus:OPERation:CONDition?")
            if b"ERROR" in op_cond_bytes: raise Exception(f"Failed to query OPER:COND: {op_cond_bytes.decode()}")
            operation_cond_str = op_cond_bytes.decode('ascii')
            
            # 5. Get Questionable Status (for OCP trip)
            q_event_bytes = self._query("STATus:QUEStionable:EVENt?")
            if b"ERROR" in q_event_bytes: raise Exception(f"Failed to query QUES:EVEN: {q_event_bytes.decode()}")
            questionable_event_str = q_event_bytes.decode('ascii')
            # --- END MODIFIED SECTION ---

            voltage = float(voltage_str)
            # SCPI reports A; convert to the shared mA unit before rounding.
            current_ma = float(current_str) * 1000.0
            if not math.isfinite(voltage) or not math.isfinite(current_ma):
                raise ValueError("Non-finite voltage or current reading")
            is_on = (status_str == '1')
            
            operation_cond = int(operation_cond_str)
            questionable_event = int(questionable_event_str)

            # Check the specific bits based on constants
            is_cc_mode = (operation_cond & (1 << self.CC_MODE_BIT)) != 0
            has_ocp_tripped = (questionable_event & (1 << self.OCP_TRIP_BIT)) != 0

            if has_ocp_tripped:
                log("WARN", f"[Kikusui] [{self.resource_string}] OCP TRIP EVENT DETECTED! (Status: {questionable_event})")

            # Return parsed data as a dictionary
            # Note: No temperature data from this device.
            return {
                "is_on": is_on,
                "voltage": round(voltage, 3),
                "current": round(current_ma, 3),
                "status_info": {
                    "is_cc_mode": is_cc_mode,
                    "has_ocp_tripped": has_ocp_tripped
                },
                "raw_response": f"V:{voltage_str},C:{current_str},S:{status_str},OP:{operation_cond_str},Q_EV:{questionable_event_str}"
            }
        except Exception as e:
            log("ERROR", f"[Kikusui] [{self.resource_string}] Failed to parse response: {e}")
            return {"error": f"Parse error: {e}", "raw_response": "PARSE_FAILED"}
