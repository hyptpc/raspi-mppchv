from mppc_app import app, db
from mppc_app.models.log import Log

from functools import wraps
import threading
import time
import numpy as np

# フラグを管理するためのイベントオブジェクトを作成
flag_module1 = threading.Event()
flag_module2 = threading.Event()
flag_module3 = threading.Event()
flag_module4 = threading.Event()
flag_modules = [ flag_module1, flag_module2, flag_module3, flag_module4 ]

# デコレータの実装
def flag_manager(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        flag = flag_modules[args[0]]
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
def monitor(module_id):
    print("HPO")
    rng = np.random.default_rng()
    hv = rng.normal(50, 5+module_id)
    current = rng.normal(0.5, (module_id+1)/10)
    temp = rng.normal(20, 5+module_id)
    
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
def turn_on(module_id):
    print("HON")
    rng = np.random.default_rng()
    is_success = False
    if rng.random() > 0.5:
        is_success = True
    save_log(module_id=module_id, cmd_tx="HON", cmd_rx="hon", status=is_success)
    return is_success

@flag_manager
def turn_off(module_id):
    print("HOF")
    rng = np.random.default_rng()
    is_success = False
    if rng.random() > 0.5:
        is_success = True
    save_log(module_id=module_id, cmd_tx="HOF", cmd_rx="hof", status=is_success)
    return is_success

@flag_manager
def reset(module_id):
    print("HRE")
    rng = np.random.default_rng()
    is_success = False
    if rng.random() > 0.5:
        is_success = True
    save_log(module_id=module_id, cmd_tx="HRE", cmd_rx="hre", status=is_success)
    return is_success

@flag_manager
def get_status(module_id):
    print("HGS")
    cmd_rx = "44"
    status = dict(
        hv_output = 1,
        over_curr_prot = 0,
        over_curr = 0,
        with_temp_sens = 0,
        over_temp = 0,
        temp_corr = 0
    )
    return status