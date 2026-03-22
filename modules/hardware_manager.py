"""
Handles the hardware command queue worker and monitoring loop.
DEVICE_PORTS / DEVICE_MAPPINGS / PORT_VOLTAGE_LIMITS_V are populated by main.py.

The worker is polymorphic: SerialCommunicator and KikusuiCommunicator share a common command interface.
"""
import time
from queue import Queue
import threading
from modules import db_measurements as database
from modules import db_logs as log_database
from modules.logger import log

from modules.hamahoto_module import SerialCommunicator
from modules.kikusui_module import KikusuiCommunicator

DEVICE_PORTS = {}
DEVICE_MAPPINGS = {}
IS_TEST_MODE = True
# port_id -> max setpoint (V); key absent = no software ceiling for that port.
PORT_VOLTAGE_LIMITS_V: dict[int, float] = {}

# --- Ramp / safety (overwritten from main.py from config) ---
RAMP_VOLTAGE_TARGET_V_PER_S = 5.0
# Used only for the first ramp step before we have a measured cycle time.
RAMP_VOLTAGE_DEFAULT_CYCLE_S = 0.1
# 1.0 = size each step from the last measured cycle only (best average rate match).
RAMP_VOLTAGE_CYCLE_EWMA_ALPHA = 1.0
# Hard cap on |ΔV| per step (V); limits the first step when default_cycle is conservative.
RAMP_VOLTAGE_MAX_STEP_V: float | None = 0.5
# If True, pad each step with sleep so wall time >= dV/v_per_s (fast bus ≈ fixed-delay feel; slow bus unchanged).
RAMP_PAD_STEP_TO_TARGET_RATE = True
RAMP_VOLTAGE_DOWN_TARGET_V_PER_S: float | None = None
REQUIRE_ON_FOR_VOLTAGE_INCREASE = True
VOLTAGE_EQ_EPSILON_V = 0.001
RAMP_MAX_ITERATIONS = 20000
RAMP_MIN_DELTA_V = 0.001

is_system_busy = False
system_busy_lock = threading.Lock()

_port_lock_registry_lock = threading.Lock()
_port_locks: dict[int, threading.Lock] = {}


def get_port_lock(port_id: int) -> threading.Lock:
    with _port_lock_registry_lock:
        if port_id not in _port_locks:
            _port_locks[port_id] = threading.Lock()
        return _port_locks[port_id]


def parse_output_on(monitor_data: dict) -> bool | None:
    """Unified ON state: Kikusui uses is_on; Serial uses status_flags.is_hv_on."""
    if "error" in monitor_data:
        return None
    if "is_on" in monitor_data:
        return bool(monitor_data["is_on"])
    flags = monitor_data.get("status_flags") or {}
    if "is_hv_on" in flags:
        return bool(flags["is_hv_on"])
    return None


def _wants_voltage_increase(current_v: float, target_v: float) -> bool:
    return target_v > current_v + VOLTAGE_EQ_EPSILON_V


def check_max_voltage_allowed(port_id: int, target_voltage: float) -> tuple[bool, str | None]:
    """Reject target above configured per-port ceiling (if any)."""
    lim = PORT_VOLTAGE_LIMITS_V.get(port_id)
    if lim is None:
        return True, None
    if target_voltage > lim + VOLTAGE_EQ_EPSILON_V:
        return False, f"Target voltage exceeds configured limit ({lim} V) for this channel."
    return True, None


def check_set_voltage_safety(primary_monitor: dict, target_voltage: float) -> tuple[bool, str | None]:
    """
    Returns (allowed, error_message).
    When REQUIRE_ON_FOR_VOLTAGE_INCREASE is False, always allowed.
    """
    if not REQUIRE_ON_FOR_VOLTAGE_INCREASE:
        return True, None
    if "error" in primary_monitor:
        return False, "Monitor error; cannot verify state for voltage change."
    current_v = primary_monitor.get("voltage")
    if current_v is None:
        return False, "Voltage reading unavailable."
    if not _wants_voltage_increase(current_v, target_voltage):
        return True, None
    on = parse_output_on(primary_monitor)
    if on is True:
        return True, None
    if on is False:
        return False, "Output is OFF; voltage increase is not allowed. Turn ON first."
    return False, "Output state unknown; voltage increase is not allowed."


def _combine_primary_with_temp(port_id: int, primary_data: dict) -> dict:
    """Merge temperature from mapped serial port into a copy of primary_data."""
    out = primary_data.copy()
    temp_port_id = DEVICE_MAPPINGS.get(port_id)
    if temp_port_id is None:
        return out
    temp_communicator = DEVICE_PORTS.get(temp_port_id)
    if not temp_communicator or not isinstance(temp_communicator, SerialCommunicator):
        return out
    temp_data = temp_communicator.monitor()
    if "error" in temp_data:
        log("WARN", f"Could not get temp data from {temp_port_id} during ramp/monitor combine.")
        return out
    out["temperature"] = temp_data.get("temperature")
    out["status_flags"] = temp_data.get("status_flags", {})
    out["status_raw"] = temp_data.get("status_raw")
    out["raw_response"] = (
        f"PRIMARY_RAW: {primary_data.get('raw_response', '')} | "
        f"TEMP_RAW: {temp_data.get('raw_response', '')}"
    )
    return out


def monitor_primary_then_save_combined(port_id: int, communicator) -> dict:
    """Primary monitor, optional temp merge, save to DB. Returns combined dict or error dict."""
    primary = communicator.monitor()
    if "error" in primary:
        database.save_monitor_data(port_id, primary)
        return primary
    combined = _combine_primary_with_temp(port_id, primary)
    database.save_monitor_data(port_id, combined)
    return combined


def run_adaptive_voltage_ramp(
    port_id: int,
    communicator,
    v_target: float,
    v_per_s: float,
) -> bytes:
    """
    Ramp toward v_target with ΔV ≈ v_per_s * T_prev (T_prev = previous step wall time).
    If RAMP_PAD_STEP_TO_TARGET_RATE, each step waits until at least dV/v_per_s has
    elapsed so fast links do not outrun the target rate (similar to fixed delay).
    """
    t_default = RAMP_VOLTAGE_DEFAULT_CYCLE_S
    alpha = RAMP_VOLTAGE_CYCLE_EWMA_ALPHA
    t_prev = t_default
    last_response = b"OK"
    primary0 = communicator.monitor()
    if "error" in primary0:
        return b"ERROR:MONITOR_FAILED"
    v_now = primary0.get("voltage")
    if v_now is None:
        return b"ERROR:NO_VOLTAGE"

    if abs(v_target - v_now) <= VOLTAGE_EQ_EPSILON_V:
        monitor_primary_then_save_combined(port_id, communicator)
        return b"OK_NOOP"

    iterations = 0
    while abs(v_target - v_now) > VOLTAGE_EQ_EPSILON_V:
        iterations += 1
        if iterations > RAMP_MAX_ITERATIONS:
            log("ERROR", f"Adaptive ramp exceeded max iterations on port {port_id}")
            return b"ERROR:RAMP_MAX_ITERATIONS"

        remaining = v_target - v_now
        sign = 1.0 if remaining > 0 else -1.0
        dV_mag = min(abs(remaining), v_per_s * t_prev)
        if RAMP_VOLTAGE_MAX_STEP_V is not None:
            dV_mag = min(dV_mag, RAMP_VOLTAGE_MAX_STEP_V)
        if dV_mag < RAMP_MIN_DELTA_V:
            dV_mag = min(abs(remaining), RAMP_MIN_DELTA_V)
        v_next = round(v_now + sign * dV_mag, 3)
        if abs(v_next - v_now) < RAMP_MIN_DELTA_V * 0.5 and abs(v_target - v_now) > VOLTAGE_EQ_EPSILON_V:
            v_next = round(v_target, 3)

        dV_cmd = abs(v_next - v_now)

        t0 = time.perf_counter()
        last_response = communicator.set_voltage(v_next)
        combined = monitor_primary_then_save_combined(port_id, communicator)
        t_cycle = max(time.perf_counter() - t0, 1e-4)

        if RAMP_PAD_STEP_TO_TARGET_RATE and v_per_s > 1e-12 and dV_cmd > 1e-12:
            need_s = dV_cmd / v_per_s
            pad = need_s - t_cycle
            if pad > 0:
                time.sleep(pad)
            t_cycle = t_cycle + max(0.0, pad)

        t_prev = alpha * t_cycle + (1.0 - alpha) * t_prev

        if "error" in combined:
            log("WARN", f"Monitor error during adaptive ramp port {port_id}")
            return last_response

        # Advance ramp state by the *commanded* step. Using only MEASure:VOLTage here
        # causes an apparent stall (same reading while the supply slews), which repeats
        # set_voltage at the same level and looks like infinite traffic.
        v_now = v_next

    if abs(v_target - v_now) > VOLTAGE_EQ_EPSILON_V:
        last_response = communicator.set_voltage(round(v_target, 3))
        monitor_primary_then_save_combined(port_id, communicator)

    return last_response


def worker(q: Queue):
    global is_system_busy

    log("WORKER", "Polymorphic worker thread started and waiting for tasks...")
    while True:
        task = q.get()
        port_id = task["port_id"]
        command_info = task["command_info"]
        log("WORKER", f"Got task for port {port_id}: {command_info}")

        communicator = DEVICE_PORTS.get(port_id)

        if not communicator:
            log("ERROR", f"Communicator for port {port_id} not available. Skipping task.")
            q.task_done()
            continue

        is_initialized = False
        if hasattr(communicator, "ser"):
            is_initialized = is_initialized or communicator.ser
        if hasattr(communicator, "instrument"):
            is_initialized = is_initialized or communicator.instrument

        if not is_initialized:
            log("ERROR", f"Communicator for port {port_id} failed initialization. Skipping task.")
            q.task_done()
            continue

        cmd_type = command_info["command_type"].upper()
        response = b""
        command_str_for_log = ""
        value = command_info.get("value")

        is_blocking_task = cmd_type in ["SET_VOLTAGE", "TURN_OFF"]

        try:
            if is_blocking_task:
                with system_busy_lock:
                    is_system_busy = True
                log("INFO", f"System BUSY due to task on port {port_id}: {cmd_type}")

            if cmd_type == "MONITOR":
                command_str_for_log = ""
                primary_data = communicator.monitor()
                if "error" in primary_data:
                    log("ERROR", f"Monitor error on primary port {port_id}: {primary_data.get('error')}")
                    database.save_monitor_data(port_id, primary_data)
                    continue  # finally: task_done() exactly once (do not call task_done here)

                temp_port_id = DEVICE_MAPPINGS.get(port_id)

                if temp_port_id is not None:
                    log("DEBUG", f"Port {port_id} needs temp data from Port {temp_port_id}.")
                    temp_communicator = DEVICE_PORTS.get(temp_port_id)

                    if temp_communicator and isinstance(temp_communicator, SerialCommunicator):
                        temp_data = temp_communicator.monitor()

                        if "error" in temp_data:
                            log("WARN", f"Could not get temp data from {temp_port_id}: {temp_data.get('error')}")
                            combined_data = primary_data
                        else:
                            combined_data = primary_data.copy()
                            combined_data["temperature"] = temp_data.get("temperature")
                            combined_data["status_flags"] = temp_data.get("status_flags", {})
                            combined_data["status_raw"] = temp_data.get("status_raw")
                            combined_data["raw_response"] = (
                                f"PRIMARY_RAW: {primary_data.get('raw_response', '')} | "
                                f"TEMP_RAW: {temp_data.get('raw_response', '')}"
                            )
                            log("DEBUG", f"Combined data for Port {port_id}: {combined_data}")

                        database.save_monitor_data(port_id, combined_data)

                    else:
                        log(
                            "WARN",
                            f"Mapped temp port {temp_port_id} for {port_id} is not a valid SerialCommunicator or doesn't exist.",
                        )
                        database.save_monitor_data(port_id, primary_data)

                else:
                    is_mapped_temp_sensor = port_id in DEVICE_MAPPINGS.values()

                    if is_mapped_temp_sensor and isinstance(communicator, SerialCommunicator):
                        log("DEBUG", f"Port {port_id} is a mapped temp sensor. Skipping standalone save.")
                    else:
                        log("DEBUG", f"Port {port_id} is standalone. Saving its data.")
                        database.save_monitor_data(port_id, primary_data)

            elif cmd_type == "SET_VOLTAGE":
                command_str_for_log = f"SET_VOLTAGE (adaptive): {value}V"
                port_lock = get_port_lock(port_id)
                with port_lock:
                    ok_max, max_err = check_max_voltage_allowed(port_id, float(value))
                    if not ok_max:
                        response = max_err.encode("utf-8", errors="replace")
                        log("WARN", f"SET_VOLTAGE rejected port {port_id}: {max_err}")
                    else:
                        primary = communicator.monitor()
                        ok, s_err = check_set_voltage_safety(primary, float(value))
                        if not ok:
                            response = s_err.encode("utf-8", errors="replace")
                            log("WARN", f"SET_VOLTAGE rejected port {port_id}: {s_err}")
                        else:
                            response = run_adaptive_voltage_ramp(
                                port_id, communicator, float(value), RAMP_VOLTAGE_TARGET_V_PER_S
                            )
                            log("RAMP", f"Adaptive SET_VOLTAGE complete for port {port_id}.")

            elif cmd_type == "TURN_ON":
                command_str_for_log = "TURN_ON"
                response = communicator.turn_on()

            elif cmd_type == "TURN_OFF":
                command_str_for_log = "TURN_OFF (with adaptive ramp down)"
                port_lock = get_port_lock(port_id)
                with port_lock:
                    floor_v = 20.5
                    down_rate = RAMP_VOLTAGE_DOWN_TARGET_V_PER_S
                    if down_rate is None:
                        down_rate = RAMP_VOLTAGE_TARGET_V_PER_S
                    primary_off = communicator.monitor()
                    start_v = 20.0
                    if "error" not in primary_off and primary_off.get("voltage") is not None:
                        start_v = primary_off["voltage"]
                    else:
                        log("WARN", f"Could not get current voltage for {port_id}. Assuming {start_v}V for ramp decision.")

                    if start_v > floor_v + VOLTAGE_EQ_EPSILON_V:
                        log("RAMP", f"Starting adaptive ramp down for port {port_id} before turning off...")
                        run_adaptive_voltage_ramp(port_id, communicator, floor_v, down_rate)
                    else:
                        log("INFO", f"Port {port_id} at or below floor {floor_v}V; skipping ramp down.")

                    log("INFO", f"Sending final TURN_OFF to port {port_id}.")
                    response = communicator.turn_off()
                    monitor_primary_then_save_combined(port_id, communicator)

            elif cmd_type == "RESET":
                command_str_for_log = "RESET"
                response = communicator.reset_device()

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

            elif cmd_type == "DISABLE_OCP":
                command_str_for_log = "DISABLE_OCP"
                if hasattr(communicator, "disable_ocp"):
                    response = communicator.disable_ocp()
                else:
                    response = b"ERROR:COMMAND_NOT_SUPPORTED"
                    log("WARN", f"Port {port_id} (Type: {type(communicator).__name__}) does not support DISABLE_OCP.")

            elif cmd_type == "CLEAR_TRIP":
                command_str_for_log = "CLEAR_TRIP"
                if hasattr(communicator, "clear_protection_trip"):
                    response = communicator.clear_protection_trip()
                else:
                    response = b"ERROR:COMMAND_NOT_SUPPORTED"
                    log("WARN", f"Port {port_id} (Type: {type(communicator).__name__}) does not support CLEAR_TRIP.")

            elif cmd_type == "RAW":
                raw_cmd = command_info.get("raw_command", "")
                command_str_for_log = f"RAW: {raw_cmd}"
                response = communicator.send_raw_command(raw_cmd)

            else:
                log("ERROR", f"Unknown command type received by worker: {cmd_type}")
                response = b"ERROR:UNKNOWN_COMMAND_TYPE"

            if command_str_for_log:
                log_database.save_action_log(port_id, command_str_for_log, response)
                log("ACTION", f"Logged for port {port_id}: {command_str_for_log}")

        except Exception as e:
            log("ERROR", f"Exception during command {cmd_type} for port {port_id}: {e}")
            error_cmd_str = f"ERROR executing {cmd_type}"
            log_database.save_action_log(port_id, error_cmd_str, str(e).encode())

        finally:
            if is_blocking_task:
                with system_busy_lock:
                    is_system_busy = False
                log("INFO", f"System IDLE after task on port {port_id}: {cmd_type}")
            q.task_done()


def _communicator_initialized(communicator) -> bool:
    ok = False
    if hasattr(communicator, "ser"):
        ok = ok or bool(communicator.ser)
    if hasattr(communicator, "instrument"):
        ok = ok or bool(communicator.instrument)
    return ok


def api_precheck_set_voltage(port_id: int, target_voltage: float) -> str | None:
    """
    Synchronous check before queuing SET_VOLTAGE. Returns error message or None if OK.
    Uses the per-port lock to avoid concurrent bus access with the worker.
    """
    communicator = DEVICE_PORTS.get(port_id)
    if not communicator:
        return "Communicator for this port is not available."
    if not _communicator_initialized(communicator):
        return "Communicator is not initialized."
    ok_lim, lim_err = check_max_voltage_allowed(port_id, float(target_voltage))
    if not ok_lim:
        return lim_err
    with get_port_lock(port_id):
        primary = communicator.monitor()
        ok, err = check_set_voltage_safety(primary, float(target_voltage))
        if not ok:
            return err
    return None


def monitoring_loop(q: Queue, interval_seconds: int, port_ids_to_monitor: list[int]):
    global is_system_busy

    log("MONITOR", f"Loop started. Interval: {interval_seconds}s for ports: {port_ids_to_monitor}.")
    time.sleep(2)
    while True:
        system_is_currently_busy = False
        try:
            with system_busy_lock:
                system_is_currently_busy = is_system_busy
        except Exception as lock_e:
            log("ERROR", f"Error checking system busy status: {lock_e}")
            time.sleep(0.1)
            continue

        if system_is_currently_busy:
            log("DEBUG", "Monitoring loop: System is busy. Skipping MONITOR task queuing.")
        else:
            log("MONITOR", f"Queuing MONITOR commands for ports: {port_ids_to_monitor}...")
            active_port_count = 0

            for port_id in port_ids_to_monitor:
                if port_id in DEVICE_PORTS:
                    communicator = DEVICE_PORTS[port_id]

                    is_initialized = False
                    if hasattr(communicator, "ser"):
                        is_initialized = is_initialized or communicator.ser
                    if hasattr(communicator, "instrument"):
                        is_initialized = is_initialized or communicator.instrument

                    if communicator and is_initialized:
                        task = {"port_id": port_id, "command_info": {"command_type": "MONITOR"}}
                        q.put(task)
                        active_port_count += 1
                    else:
                        log("WARN", f"Skipping monitor for port {port_id}: communicator not initialized.")
                else:
                    log("WARN", f"Skipping monitor for port {port_id}: port not configured in DEVICE_PORTS.")

            if active_port_count == 0:
                log("WARN", "Monitoring loop found no active/configured ports to monitor.")

        time.sleep(interval_seconds)
