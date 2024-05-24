from flask import Blueprint, render_template, request, redirect, jsonify
from mppc_app import app, db
from mppc_app.controllers.serial_comm import get_hv, get_current, get_temp, send_cmd, get_status
from mppc_app.models.log import Log
from mppc_app.models.mppc_data import MPPC_data
action_bp = Blueprint('action', __name__)

from apscheduler.schedulers.background import BackgroundScheduler

# for draw
import numpy as np
import json

def save_mppc_data():
    with app.app_context():
        hv, curr, temp = [], [], []
        for i in range(4):
            hv.append(get_hv(i))
            curr.append(get_current(i))
            temp.append(get_temp(i))
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
scheduler.add_job(save_mppc_data, 'interval', seconds=5)
scheduler.start()

@action_bp.route('/_fetch_data')
def fetch_data():
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
    graph_data = {"x": x, "y": y}
    graph_data_JSON = json.dumps(graph_data)
    return jsonify(graph_data=graph_data_JSON)

# スイッチの初期状態を返すエンドポイント
@app.route('/_get_switch_status')
def get_switch_status():
    # ここでJavaScriptから送信されたモジュールIDとスイッチの名前を受け取る
    module_id = request.args.get('module_id', type=int)
    switch_name = request.args.get('name', type=str)

    # 仮の初期状態を返す（実際の処理はここでモジュールIDに基づいて行う）
    status = get_status(module_id)
    initial_state = 'off'
    initial_text = switch_name + ' OFF'
    if switch_name == "HV":
        if status["hv"]:
            initial_state = 'on'
            initial_text = switch_name + ' ON'
    elif switch_name == "Temp":
        if status["temp_corr"]:
            initial_state = 'on'
            initial_text = switch_name + ' ON'
        
    return jsonify({'state': initial_state, 'text': initial_text})













@action_bp.route('/_send')
def send():
    module_id = request.args.get('module_id', type=int)
    cmd   = request.args.get('cmd', type=str)
    value = request.args.get('value', type=float)

    cmd_tx = "{} {}".format(cmd, value)
    cmd_rx = send_cmd(module_id, cmd, value)

    with app.app_context():
        data = Log(
            module_id = module_id,
            cmd_tx = cmd_tx,
            cmd_rx = cmd_rx
        )
        db.session.add(data)
        db.session.commit()

    n = Log.query.count()
    print(n)
    n_show = 10
    latest_data = Log.query.offset(n-n_show).limit(n_show).all()
    results = [dict( module_id=data.module_id, cmd_tx=data.cmd_tx, cmd_rx=data.cmd_rx ) for data in latest_data]

    return jsonify(results=results)

@action_bp.route('/_check_status')
def check_status():
    module_id = request.args.get('module_id', type=int)
    cmd_tx = "HGS"
    cmd_rx = get_status(module_id)

    n = Log.query.count()
    print(n)
    n_show = 10
    latest_data = Log.query.offset(n-n_show).limit(n_show).all()
    results = [dict( module_id=data.module_id, cmd_tx=data.cmd_tx, cmd_rx=data.cmd_rx ) for data in latest_data]


    return jsonify(results=results)