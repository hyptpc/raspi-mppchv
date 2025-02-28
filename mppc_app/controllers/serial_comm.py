from mppc_app import app, db
from mppc_app.models.log import Log

from functools import wraps
import threading
import time
import numpy as np
import serial

# フラグを管理するためのイベントオブジェクトを作成
flag_module1 = threading.Event()
flag_module2 = threading.Event()
flag_module3 = threading.Event()
flag_module4 = threading.Event()
flag_modules = [ flag_module1, flag_module2, flag_module3, flag_module4 ]

# tentative
conv_factor_Vb = 1.812*10**-3
conv_factor_volt = 1.812*10**-3
conv_factor_curr = 4.980*10**-3

id_list = [5, 2, 4, 0]

def hex2vol(hex_value):
    return int(hex_value, 16)*conv_factor_volt

def hex2curr(hex_value):
    return int(hex_value, 16)*conv_factor_curr

def hex2temp(hex_value):
    return ( int(hex_value, 16) * 1.907*10**-5 - 1.035 ) / (-5.5*10**-3)

def vol2hex(vol_value):
    # return hex( int(vol_value/conv_factor_Vb) )
    return format( int(vol_value/conv_factor_Vb), "04x" ).encode()


# デコレータの実装
def flag_manager(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        flag = flag_modules[args[0]-1]
        while flag.is_set():
            time.sleep(0.1)
        flag.set()
        result = func(*args, **kwargs)
        flag.clear()
        return result
    return wrapper

def save_log(module_id, cmd_tx, cmd_rx, status):
    with app.app_context():
        data = Log(
            module_id = module_id,
            cmd_tx = cmd_tx,
            cmd_rx = cmd_rx,
            status = "success" if status else "failure"
        )
        db.session.add(data)
        db.session.commit()

@flag_manager
def monitor(module_id, verbose = True):
    if verbose:
        print("HPO")

    # open port
    ser = serial.Serial('/dev/ttyAMA{}'.format(id_list[module_id]), baudrate=38400, parity='E', timeout=1)

    if not ser.isOpen():
        print("Port open failed")
        return

    # create command
    stx       = b"\x02"
    command   = "HPO".encode()
    etx       = b"\x03"
    check_sum = str( hex(sum(command)+5) )[-2:].encode()
    delimiter = b"\x0D"

    send_cmd = stx + command + etx + check_sum + delimiter

    # send command
    ser.write(send_cmd)
    ser.flush()

    # receive command and interpret it
    time.sleep(0.1)
    received_cmd = ser.readline()

    # close port
    ser.close()

    hv = hex2vol(received_cmd.decode()[12:16])
    current = hex2curr(received_cmd.decode()[16:20])
    temp = hex2temp(received_cmd.decode()[20:24])

    return [hv, current, temp]


@flag_manager
def get_hv(module_id):
    rng = np.random.default_rng()
    hv = rng.normal(50, 5+module_id)
    
    return hv

@flag_manager
def get_current(module_id):
    rng = np.random.default_rng()
    current = rng.normal(0.5, (module_id+1)/10)
    
    return current

@flag_manager
def get_temp(module_id):
    rng = np.random.default_rng()
    temp = rng.normal(20, 5+module_id)
    
    return temp

@flag_manager
def set_hv(module_id, hv):
    print("HBV")

    # open port
    ser = serial.Serial('/dev/ttyAMA{}'.format(id_list[module_id-1]), baudrate=38400, parity='E', timeout=1)

    if ser.isOpen():
        is_success = True
    else:
        is_success = False
        return is_success
    
    # create command
    stx       = b"\x02"
    command   = "HBV".encode() + vol2hex(hv)
    etx       = b"\x03"
    check_sum = str( hex(sum(command)+5) )[-2:].encode()
    delimiter = b"\x0D"

    send_cmd = stx + command + etx + check_sum + delimiter

    # send command
    ser.write(send_cmd)
    ser.flush()

    # receive command and interpret it
    time.sleep(0.1)
    received_cmd = ser.readline()

    cal_checksum = str( hex(sum(received_cmd[:-3])).upper() )[-2:]
    received_checksum = received_cmd[-3:-1].decode()
    print("checksum(cal/rec): {}, {}".format(cal_checksum, received_checksum))
    if cal_checksum != received_checksum:
        is_success = False
        print("wrong checksum")
    else:
        print(f"succeeded changing HV @ modele {id_list[module_id-1]}")

    save_log(module_id=module_id, cmd_tx="HBV{}".format(hv), cmd_rx="hbv", status=is_success)
    return is_success

@flag_manager
def set_temp_corr(module_id, v0, t0, delta_t_h, delta_t_h_prime, delta_t_l, delta_t_l_prime):
    rng  = np.random.default_rng()
    print("HST")
    is_success = False
    if rng.random() > 0.5:
        is_success = True
    save_log(module_id=module_id, cmd_tx="HST{}".format(v0), cmd_rx="hst", status=is_success)
    print("HRT")
    save_log(module_id=module_id, cmd_tx="HRT", cmd_rx="hrt", status=is_success)
    return is_success

def comm(module_id, cmd):
    # open port
    ser = serial.Serial('/dev/ttyAMA{}'.format(id_list[module_id-1]), baudrate=38400, parity='E', timeout=1)

    if ser.isOpen():
        is_success = True
    else:
        is_success = False
        print("Port open failed")
        return is_success

    # create command
    stx       = b"\x02"
    command   = cmd.encode()
    etx       = b"\x03"
    check_sum = str( hex(sum(command)+5) )[-2:].encode()
    delimiter = b"\x0D"

    send_cmd = stx + command + etx + check_sum + delimiter
    print("send command:     ", send_cmd)

    # send command
    ser.write(send_cmd)
    ser.flush()

    # receive command and interpret it
    time.sleep(0.1)
    received_cmd = ser.readline()

    cal_checksum = str( hex(sum(received_cmd[:-3])).upper() )[-2:]
    received_checksum = received_cmd[-3:-1].decode()
    print("checksum(cal/rec): {}, {}".format(cal_checksum, received_checksum))
    if cal_checksum != received_checksum:
        is_success = False
        print("wrong checksum")
    else:
        print(f"succeeded {cmd} @ modele {id_list[module_id-1]}")

    return is_success


@flag_manager
def turn_on(module_id):
    print("HON")
    is_success = comm(module_id, "HON")
    save_log(module_id=module_id, cmd_tx="HON", cmd_rx="hon", status=is_success)
    return is_success

@flag_manager
def turn_off(module_id):
    print("HOF")
    is_success = comm(module_id, "HOF")
    save_log(module_id=module_id, cmd_tx="HOF", cmd_rx="hof", status=is_success)
    return is_success

@flag_manager
def reset(module_id):
    print("HRE")
    is_success = comm(module_id, "HRE")
    save_log(module_id=module_id, cmd_tx="HRE", cmd_rx="hre", status=is_success)
    return is_success

@flag_manager
def get_status(module_id):
    print("HGS")

    # open port
    ser = serial.Serial('/dev/ttyAMA{}'.format(id_list[module_id-1]), baudrate=38400, parity='E', timeout=1)

    if not ser.isOpen():
        print("Port open failed")
        return

    # create command
    stx       = b"\x02"
    command   = "HGS".encode()
    etx       = b"\x03"
    check_sum = str( hex(sum(command)+5) )[-2:].encode()
    delimiter = b"\x0D"

    send_cmd = stx + command + etx + check_sum + delimiter

    # send command
    ser.write(send_cmd)
    ser.flush()

    # receive command and interpret it
    time.sleep(0.1)
    received_cmd = ser.readline()

    # close port
    ser.close()

    status = int(received_cmd.decode()[4:8], 16)
    for i in range(7):
        print(f"bit{i}: {(status >> i) & 1}")

    status_dict = dict(
        hv_output = (status >> 0) & 1,
        over_curr_prot = (status >> 1) & 1,
        over_curr = (status >> 2) & 1,
        with_temp_sens = (status >> 3) & 1,
        over_temp = (status >> 4) & 1,
        temp_corr = (status >> 6) & 1
    )
    return status_dict