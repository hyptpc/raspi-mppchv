"""
Manages hardware communication for KIKUSUI power supplies using PyVISA.
Includes methods for standard control, OCP, and detailed status monitoring.
"""
import pyvisa
import time
from modules.logger import log
import random

class KikusuiCommunicator:
    # --- Constants for Status Register Bits ---
    # Based on PMX-A Series (e.g., PMX18-2A) User's Manual
    # (Check your specific model's manual to confirm)
    
    # From the STATus:OPERation register (STAT:OPER:COND?)
    CC_MODE_BIT = 4  # Bit 4 (value 16) indicates Constant Current (CC) mode
    
    # From the STATus:QUEStionable register (STAT:QUES:EVENt? or STAT:QUES:COND?)
    # PMX-A Manual: Bit 4 (value 16) is OCP (Over-Current Protection)
    OCP_TRIP_BIT = 4 # CHANGED: Was 10 (example), now 4 for PMX-A

    """Handles low-level PyVISA communication for a single KIKUSUI device."""
    def __init__(self, resource_string: str, is_test_mode: bool):
        self.resource_string = resource_string
        self.instrument = None # Initialize instrument object as None
        self.is_test_mode = is_test_mode

        if self.is_test_mode:
            log("MOCK", f"Initialized mock communicator for {self.resource_string}")
            # In test mode, just set 'instrument' to True to indicate it's 'ready'
            self.instrument = True 
            return # Don't try to open a real instrument in test mode

        # Attempt to open the real VISA resource
        try:
            # Specify '@py' to use the pyvisa-py backend
            rm = pyvisa.ResourceManager('@py')
            self.instrument = rm.open_resource(self.resource_string)
            self.instrument.timeout = 5000 # Set a 5-second timeout
            
            # --- MODIFIED ---
            # Do NOT send *RST on connect. Only clear errors.
            self.instrument.write('*CLS') # Clear old errors from the queue
            idn = self.instrument.query('*IDN?') # Ask for identification
            log("INFO", f"Successfully connected to {self.resource_string}. ID: {idn.strip()}")
            # --- END MOD ---
            
        except pyvisa.errors.VisaIOError as e:
            log("ERROR", f"FATAL: Could not open {self.resource_string}. {e}")
            self.instrument = None # Ensure self.instrument remains None if opening failed
            
    def _write(self, command: str) -> bytes:
        """Private method to send a write-only command."""
        if not self.instrument:
            log("ERROR", f"[{self.resource_string}] Attempted write but instrument is not open.")
            return b"ERROR:NOT_OPEN"
            
        log("SEND", f"[{self.resource_string}] {command}")
        try:
            self.instrument.write(command)
            return b"OK" # Return bytes for compatibility with worker logging
        except pyvisa.errors.VisaIOError as e:
            log("ERROR", f"[{self.resource_string}] VISA write error: {e}")
            return b"ERROR:VISA_WRITE_FAILED"

    def _query(self, command: str) -> bytes:
        """Private method to send a query command and get a response."""
        if not self.instrument:
            log("ERROR", f"[{self.resource_string}] Attempted query but instrument is not open.")
            return b"ERROR:NOT_OPEN"

        log("SEND", f"[{self.resource_string}] {command}")
        try:
            response_str = self.instrument.query(command)
            return response_str.strip().encode('ascii')
        except pyvisa.errors.VisaIOError as e:
            log("ERROR", f"[{self.resource_string}] VISA query error: {e}")
            return b"ERROR:VISA_QUERY_FAILED"

    def _generate_mock_monitor_data(self) -> dict:
        """Generates a realistic dictionary of mock data for testing."""
        time.sleep(0.05) # Simulate hardware delay
        mock_is_on = random.choice([True, False])
        return {
            "is_on": mock_is_on,
            "voltage": round(random.uniform(65.0, 75.0), 3) if mock_is_on else 0.0,
            "current": round(random.uniform(0.01, 0.1), 3) if mock_is_on else 0.0,
            "status_info": {
                "is_cc_mode": random.choice([True, False]) if mock_is_on else False,
                "has_ocp_tripped": False
            },
            "raw_response": "mock data"
        }

    # --- High-level device commands (Common Interface) ---
    
    def turn_on(self):
        """Sends the OUTP ON command."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating TURN_ON")
            return b"OK_ON"
        return self._write("OUTPut:STATe ON")
    
    def turn_off(self):
        """Sends the OUTP OFF command."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating TURN_OFF")
            return b"OK_OFF"
        return self._write("OUTPut:STATe OFF")

    def reset_device(self):
        """Sends *RST (Reset) and *CLS (Clear Status)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating RESET")
            return b"OK_RST"
        return self._write("*RST; *CLS")

    def send_raw_command(self, command_str: str):
        """Sends a user-provided raw SCPI command."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating RAW command: {command_str}")
            return b"OK_RAW"
        return self._write(command_str)

    def set_voltage(self, voltage: float):
        """Sends the VOLTage command to set the output voltage."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating SET_VOLTAGE to {voltage}V")
            return b"OK_VOLT"
        command = f"SOURce:VOLTage {voltage:.3f}"
        return self._write(command)

    # --- KIKUSUI-specific methods (not in the common interface) ---

    def set_current(self, current: float):
        """Sets the Constant Current (CC) level."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating SET_CURRENT to {current}A")
            return b"OK_CURR"
        command = f"SOURce:CURRent {current:.3f}"
        return self._write(command)

    def enable_ocp(self, trip_current: float):
        """Enables Over-Current Protection (OCP) and sets the trip level."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating ENABLE_OCP to {trip_current}A")
            return b"OK_OCP"
        command = f"CURRent:PROTection:LEVel {trip_current:.3f}; CURRent:PROTection:STATe ON"
        return self._write(command)

    def disable_ocp(self):
        """Disables Over-Current Protection (OCP)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating DISABLE_OCP")
            return b"OK_OCP_OFF"
        return self._write("CURRent:PROTection:STATe OFF")
    
    def clear_protection_trip(self):
        """Clears a latched protection trip (like OCP or OVP)."""
        if self.is_test_mode:
            log("MOCK", f"[{self.resource_string}] Simulating CLEAR_TRIP")
            return b"OK_TRIP_CLEAR"
        # PMX-A series uses OUTPut:PROTection:CLEar
        return self._write("OUTPut:PROTection:CLEar")

    def monitor(self) -> dict:
        """
        Fetches measurements and status, including CC mode and OCP trip events.
        """
        if self.is_test_mode:
            return self._generate_mock_monitor_data()

        try:
            # --- MODIFIED: Use separate queries instead of batching ---
            # This is far more robust and avoids VISA timeouts if the
            # instrument doesn't perfectly handle complex batch queries.
            
            voltage_str = self.instrument.query("MEASure:VOLTage?").strip()
            current_str = self.instrument.query("MEASure:CURRent?").strip()
            status_str = self.instrument.query("OUTPut:STATe?").strip()
            operation_cond_str = self.instrument.query("STATus:OPERation:CONDition?").strip()
            questionable_event_str = self.instrument.query("STATus:QUEStionable:EVENt?").strip()

            # --- Parsing logic (unchanged) ---
            voltage = float(voltage_str)
            current = float(current_str)
            is_on = (status_str == '1')
            
            operation_cond = int(operation_cond_str)
            questionable_event = int(questionable_event_str)

            # Check the specific bits based on our constants
            is_cc_mode = (operation_cond & (1 << self.CC_MODE_BIT)) != 0
            has_ocp_tripped = (questionable_event & (1 << self.OCP_TRIP_BIT)) != 0

            if has_ocp_tripped:
                log("WARN", f"[{self.resource_string}] OCP TRIP EVENT DETECTED!")

            raw_response = f"V:{voltage_str},C:{current_str},S:{status_str},OP:{operation_cond_str},Q_EV:{questionable_event_str}"
            log("RECV", f"[{self.resource_string}] Parsed: {raw_response}")

            # Return parsed data as a dictionary.
            return {
                "is_on": is_on,
                "voltage": round(voltage, 3),
                "current": round(current, 3),
                "status_info": {
                    "is_cc_mode": is_cc_mode,
                    "has_ocp_tripped": has_ocp_tripped
                },
                "raw_response": raw_response
            }
        except pyvisa.errors.VisaIOError as e:
            # Be more specific about VISA errors
            log("ERROR", f"[{self.resource_string}] VISA communication error during monitor: {e}")
            return {"error": f"VISA error: {e}", "raw_response": "VISA_ERROR"}
        except Exception as e:
            # Catch other errors (e.g., float conversion)
            log("ERROR", f"[{self.resource_string}] Failed to parse monitor response: {e}")
            return {"error": f"Parse error: {e}", "raw_response": "PARSE_FAILED"}

