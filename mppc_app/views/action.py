from flask import Blueprint, render_template, request, redirect, jsonify
from mppc_app import app, db
from mppc_app.controllers.serial_comm import monitor, get_status, set_hv, turn_on, turn_off, reset
from mppc_app.models.log import Log
from mppc_app.models.mppc_data import MPPC_data
action_bp = Blueprint('action', __name__)

from apscheduler.schedulers.background import BackgroundScheduler
import numpy as np
import json
from datetime import datetime

def save_mppc_data():
    with app.app_context():
        hv, curr, temp = [], [], []
        for i in range(4):
            monitor_values = monitor(i)
            hv.append(monitor_values[0])
            curr.append(monitor_values[1])
            temp.append(monitor_values[2])
        data = MPPC_data(
            hv1 = hv[0], curr1 = curr[0], temp1 = temp[0],
            hv2 = hv[1], curr2 = curr[1], temp2 = temp[1],
            hv3 = hv[2], curr3 = curr[2], temp3 = temp[2],
            hv4 = hv[3], curr4 = curr[3], temp4 = temp[3]
        )
        db.session.add(data)
        db.session.commit()

# スケジューラのセットアップ
scheduler = BackgroundScheduler()
scheduler.add_job(save_mppc_data, 'interval', seconds=app.config["MONITORING_INTERVAL"])
scheduler.start()

@action_bp.route('/_fetch_mppc_data')
def fetch_mppc_data():
    n = MPPC_data.query.count()
    n_show = 100
    latest_data = MPPC_data.query.offset(n-n_show).limit(n_show).all()
    x = [ data.time.isoformat() for data in latest_data]
    y = np.array([
        [
            data.hv1, data.curr1*10, data.temp1,
            data.hv2, data.curr2*10, data.temp2,
            data.hv3, data.curr3*10, data.temp3,
            data.hv4, data.curr4*10, data.temp4,
        ] for data in latest_data
    ]).T.tolist()
    return jsonify({"x": x, "y": y})

@action_bp.route("/_get_interval_time")
def get_interval_time():
    return jsonify({"interval_time": app.config["PLOT_INTERVAL"]})

@action_bp.route('/_fetch_log')
def fetch_log():
    n = Log.query.count()
    n_show = 30
    latest_log = Log.query.offset(n-n_show).limit(n_show).all()[::-1]
    logs = [dict( time=log.time, module_id=log.module_id, cmd_tx=log.cmd_tx, cmd_rx=log.cmd_rx, status=log.status ) for log in latest_log]

    return jsonify(logs=logs)

# スイッチの初期状態を返すエンドポイント
@app.route('/_get_switch_status')
def get_switch_status():
    # ここでJavaScriptから送信されたモジュールIDとスイッチの名前を受け取る
    module_id = request.args.get('module_id', type=int)
    switch_name = request.args.get('name', type=str)

    status = get_status(module_id)
    initial_state = 'off'
    initial_text = switch_name + ' OFF'
    if switch_name == "HV":
        if status["hv_output"]:
            initial_state = 'on'
            initial_text = switch_name + ' ON'
    elif switch_name == "Temp":
        if status["temp_corr"]:
            initial_state = 'on'
            initial_text = switch_name + ' ON'
        
    return jsonify({'state': initial_state, 'text': initial_text})

@action_bp.route('/_send_cmd')
def send_cmd():
    module_id = request.args.get('module_id', type=int)
    cmd_type  = request.args.get('cmd_type', type=str)
    is_success = False
    if cmd_type == "on":
        is_success = turn_on(module_id)
    elif cmd_type == "off":
        is_success = turn_off(module_id)
    elif cmd_type == "reset":
        is_success = reset(module_id)

    return jsonify({'is_success': is_success})

@action_bp.route('/_change_hv')
def change_hv():
    module_id = request.args.get('module_id', type=int)
    hv = request.args.get('hv_value', type=float)
    name = request.args.get('name', type=str)
    print(name)
    
    if (hv < 0 or app.config["VMAX_MODULE{}".format(module_id)] < hv):
        return jsonify({'status_code': 2}) # out of range
    is_success = set_hv(module_id, hv)
    status_code = 0 if is_success else 1
    return jsonify({'status_code': status_code}) 

@action_bp.route('/_check_status')
def check_status():
    module_id = request.args.get('module_id', type=int)
    status = get_status(module_id)
    detail_status = []
    detail_status.append(
        dict(
            label = "Time",
            value = datetime.now(),
            bit   = None
        )
    )
    detail_status.append(
        dict(
            label = "HV Output",
            value = "ON" if status["hv_output"] else "OFF",
            bit   = status["hv_output"]
        )
    )
    detail_status.append(
        dict(
            label = "Overcurrent Protection",
            value = "Active" if status["over_curr_prot"] else "Not Active",
            bit   = status["over_curr_prot"]
        )
    )
    detail_status.append(
        dict(
            label = "Current Value",
            value = "Out of Spec" if status["over_curr"] else "Within Spec",
            bit   = status["over_curr"]
        )
    )
    detail_status.append(
        dict(
            label = "Temp Sensor Connection",
            value = "Connected" if status["with_temp_sens"] else "Not Connected",
            bit   = status["with_temp_sens"]
        )
    )
    detail_status.append(
        dict(
            label = "Temp Range",
            value = "Out of Spec" if status["over_temp"] else "Within Spec",
            bit   = status["over_temp"]
        )
    )
    detail_status.append(
        dict(
            label = "Temp Correction",
            value = "Enabled" if status["temp_corr"] else "Disabled",
            bit   = status["temp_corr"]
        )
    )

    return jsonify(detail_status=detail_status)