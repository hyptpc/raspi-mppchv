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
from modules.logger import log
import random

class KikusuiCommunicator:
    # --- Constants for Status Register Bits for PMX18-2A ---
    # From the STATus:OPERation register
    # Bit 4: CC mode (1 = is in CC mode)
    CC_MODE_BIT = 4

    # From the STATus:QUEStionable register
    # Bit 4: OCP (1 = OCP has tripped)
    OCP_TRIP_BIT = 4

    """Handles low-level PyVISA communication for a single KIKUSUI device."""
    
    def __init__(self, resource_string: str, is_test_mode: bool):
        self.resource_string = resource_string
        self.instrument = None # Initialize instrument object as None
        self.is_test_mode = is_test_mode

        if self.is_test_mode:
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
            
            # --- MODIFIED ---
            # Do NOT send *RST on connect. Only clear errors.
            self.instrument.write('*CLS')
            idn = self.instrument.query('*IDN?')
            log("INFO", f"[Kikusui] Successfully connected to {self.resource_string}. ID: {idn.strip()}")
            # --- END MOD ---
            
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

    def _generate_mock_monitor_data(self) -> dict:
        """Generates a realistic dictionary of mock data for testing."""
        time.sleep(0.05) # Simulate hardware delay
        mock_is_on = random.choice([True, False])
        mock_status_info = {
            "is_cc_mode": random.choice([True, False]) if mock_is_on else False,
            "has_ocp_tripped": False # OCP trips should be rare
        }
        mock_data = {
            "is_on": mock_is_on,
            "voltage": round(random.uniform(65.0, 75.0), 3) if mock_is_on else 0.0,
            "current": round(random.uniform(0.01, 0.1), 3) if mock_is_on else 0.0,
            "status_info": mock_status_info,
            "raw_response": "mock data"
        }
        log("MOCK", f"[Kikusui] Generated data for {self.resource_string}")
        return mock_data

    # --- High-level device commands (Common Interface) ---
    
    def turn_on(self):
        """Sends the OUTP ON command """
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating TURN_ON")
            return b"OK_ON"
        return self._write("OUTPut:STATe ON")
    
    def turn_off(self):
        """Sends the OUTP OFF command """
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating TURN_OFF")
            return b"OK_OFF"
        return self._write("OUTPut:STATe OFF")

    def reset_device(self):
        """Sends *RST (Reset) and *CLS (Clear Status)."""
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating RESET")
            return b"OK_RST"
        # Reset and clear can be combined in a single write.
        return self._write("*RST; *CLS")

    def send_raw_command(self, command_str: str):
        """
        Sends a user-provided raw SCPI command.
        This is a 'write' operation. For queries, use a specific method.
        """
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating RAW command: {command_str}")
            return b"OK_RAW"
        return self._write(command_str)

    def set_voltage(self, voltage: float):
        """Sends the SOURce:VOLTage command to set the output voltage."""
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating SET_VOLTAGE to {voltage}V")
            return b"OK_VOLT"
        
        command = f"SOURce:VOLTage {voltage:.3f}"
        return self._write(command)

    # --- KIKUSUI-specific methods (Not in the common interface) ---

    def set_current(self, current: float):
        """Sets the Constant Current (CC) level (SOURce:CURRent)."""
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating SET_CURRENT to {current}A")
            return b"OK_CURR"
        command = f"SOURce:CURRent {current:.3f}"
        return self._write(command)

    def enable_ocp(self, trip_current: float):
        """Enables Over-Current Protection (OCP) and sets the trip level."""
        if self.is_test_mode:
            log("MOCK", f"[Kikusui] [{self.resource_string}] Simulating ENABLE_OCP to {trip_current}A")
            return b"OK_OCP"
        
        # Set level and enable OCP in one command
        command = f"CURRent:PROTection:LEVel {trip_current:.3f}; CURRent:PROTection:STATe ON"
        return self._write(command)

    def disable_ocp(self):
        """Disables Over-Current Protection (OCP)."""
        if self.is_test_mode:
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
        This is the source of HV data (V, I, Status).
        """
        if self.is_test_mode:
            return self._generate_mock_monitor_data()

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
            current = float(current_str)
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
                "current": round(current, 3),
                "status_info": {
                    "is_cc_mode": is_cc_mode,
                    "has_ocp_tripped": has_ocp_tripped
                },
                "raw_response": f"V:{voltage_str},C:{current_str},S:{status_str},OP:{operation_cond_str},Q_EV:{questionable_event_str}"
            }
        except Exception as e:
            log("ERROR", f"[Kikusui] [{self.resource_string}] Failed to parse response: {e}")
            return {"error": f"Parse error: {e}", "raw_response": "PARSE_FAILED"}
