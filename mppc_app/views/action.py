from flask import Blueprint, request, jsonify
from mppc_app import app, db
from mppc_app.controllers.serial_comm import monitor, get_status, set_hv, set_temp_corr, turn_on, turn_off, reset
from mppc_app.models.log import Log
from mppc_app.models.mppc_data import MPPC_data
action_bp = Blueprint('action', __name__)

from apscheduler.schedulers.background import BackgroundScheduler
import numpy as np
from datetime import datetime

# Function to save MPPC data
def save_mppc_data():
    with app.app_context():
        # Initialize lists for HV, current, and temperature
        hv, curr, temp = [], [], []
        # Loop through 4 modules
        for i in range(4):
            # Monitor values for each module
            monitor_values = monitor(i, verbose=False)
            hv.append(monitor_values[0])
            curr.append(monitor_values[1])
            temp.append(monitor_values[2])
        # Create MPPC_data object and commit to the database
        data = MPPC_data(
            hv1=hv[0], temp1=temp[0], curr1=curr[0],
            hv2=hv[1], temp2=temp[1], curr2=curr[1],
            hv3=hv[2], temp3=temp[2], curr3=curr[2],
            hv4=hv[3], temp4=temp[3], curr4=curr[3],
        )
        db.session.add(data)
        db.session.commit()

# Setup scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(save_mppc_data, 'interval', seconds=app.config["MONITORING_INTERVAL"])
scheduler.start()

# get plot interval time
@action_bp.route("/_get_interval_time")
def get_interval_time():
    return jsonify({"intervalTime": app.config["PLOT_INTERVAL"]})

# fetch MPPC data
@action_bp.route('/_fetch_mppc_data')
def fetch_mppc_data():
    # Query latest MPPC data
    n = MPPC_data.query.count()
    n_show = 100
    latest_data = MPPC_data.query.offset(n - n_show).limit(n_show).all()
    # Extract x and y values for plot
    x = [data.time.isoformat() for data in latest_data]
    curr_plot_factor = 10
    y = np.array([
        [
            data.hv1, data.temp1, data.curr1 * curr_plot_factor,
            data.hv2, data.temp2, data.curr2 * curr_plot_factor, 
            data.hv3, data.temp3, data.curr3 * curr_plot_factor,
            data.hv4, data.temp4, data.curr4 * curr_plot_factor
        ] for data in latest_data
    ]).T.tolist()
    return jsonify({"x": x, "y": y})

# fetch logs
@action_bp.route('/_fetch_log')
def fetch_log():
    # Query latest logs
    n = Log.query.count()
    n_show = 30
    latest_log = Log.query.offset(n - n_show).limit(n_show).all()[::-1]
    # Prepare logs data
    logs = [dict(time=log.time, moduleId=log.module_id, cmd_tx=log.cmd_tx, cmd_rx=log.cmd_rx, status=log.status) for log in latest_log]
    return jsonify(logs=logs)

# get switch status
@app.route('/_get_switch_status')
def get_switch_status():
    # Get module ID and switch type from request
    module_id = request.args.get('moduleId', type=int)
    switch_type = request.args.get('type', type=str)

    # Get status for the module
    status = get_status(module_id)
    initial_state = 'off'
    initial_text = switch_type + ' OFF'
    if switch_type == "HV":
        if status["hv_output"]:
            initial_state = 'on'
            initial_text = switch_type + ' ON'
    elif switch_type == "Temp":
        if status["temp_corr"]:
            initial_state = 'on'
            initial_text = switch_type + ' ON'

    return jsonify({'state': initial_state, 'text': initial_text})

# send command to module
@action_bp.route('/_send_cmd')
def send_cmd():
    module_id = request.args.get('moduleId', type=int)
    cmd_type = request.args.get('cmdType', type=str)
    is_success = False
    if cmd_type == "on":
        is_success = turn_on(module_id)
    elif cmd_type == "off":
        is_success = turn_off(module_id)
    elif cmd_type == "reset":
        is_success = reset(module_id)

    return jsonify({'isSuccess': is_success})

# change HV value
@action_bp.route('/_change_hv')
def change_hv():
    module_id = request.args.get('moduleId', type=int)
    hv_value = request.args.get('hvValue', type=float)
    hv_type = request.args.get('hvType', type=str)

    if hv_value < 0 or app.config[f"MODULE{module_id}"]["VMAX"] < hv_value:
        return jsonify({'statusCode': 2})  # out of range
    is_success = False
    if hv_type == "Norm":
        is_success = set_hv(module_id, hv_value)
    elif hv_type == "Temp":
        app.config[f"MODULE{module_id}"]["V0"] = hv_value
        is_success = set_temp_corr(
            module_id,
            hv_value,
            app.config[f"MODULE{module_id}"]["T0"],
            app.config[f"MODULE{module_id}"]["DELTA_T_HIGH"],
            app.config[f"MODULE{module_id}"]["DELTA_T_HIGH_PRIME"],
            app.config[f"MODULE{module_id}"]["DELTA_T_LOW"],
            app.config[f"MODULE{module_id}"]["DELTA_T_LOW_PRIME"]
        )
    return jsonify({'statusCode': 0 if is_success else 1})

# check module status
@action_bp.route('/_check_status')
def check_status():
    module_id = request.args.get('moduleId', type=int)
    status_dict = get_status(module_id)
    detail_status = []
    detail_status.append(
        dict(
            label="Time",
            value=datetime.now(),
            bit=None
        )
    )
    detail_status.append(
        dict(
            label="HV Output",
            value="ON" if status_dict["hv_output"] else "OFF",
            bit=status_dict["hv_output"]
        )
    )
    detail_status.append(
        dict(
            label="Overcurrent Protection",
            value="Active" if status_dict["over_curr_prot"] else "Not Active",
            bit=status_dict["over_curr_prot"]
        )
    )
    detail_status.append(
        dict(
            label="Current Value",
            value="Out of Spec" if status_dict["over_curr"] else "Within Spec",
            bit=status_dict["over_curr"]
        )
    )
    detail_status.append(
        dict(
            label="Temp Sensor Connection",
            value="Connected" if status_dict["with_temp_sens"] else "Not Connected",
            bit=status_dict["with_temp_sens"]
        )
    )
    detail_status.append(
        dict(
            label="Temp Range",
            value="Out of Spec" if status_dict["over_temp"] else "Within Spec",
            bit=status_dict["over_temp"]
        )
    )
    detail_status.append(
        dict(
            label="Temp Correction",
            value="Enabled" if status_dict["temp_corr"] else "Disabled",
            bit=status_dict["temp_corr"]
        )
    )

    return jsonify(detailStatus=detail_status)