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
        # print(args)
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
            status = status
        )
        db.session.add(data)
        db.session.commit()

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
def send_cmd(module_id, cmd, value):
    print("{} {}".format(cmd, value))
    return "{} {}".format(cmd, value)

@flag_manager
def get_status(module_id):
    print("HGS")
    cmd_rx = "44"
    status = dict(
        hv = 0,
        over_curr_prot = 0,
        over_curr = 0,
        with_temp_sens = 0,
        over_temp = 0,
        temp_corr = 0
    )
    return status
