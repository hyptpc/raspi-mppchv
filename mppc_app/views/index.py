from mppc_app import app
from flask import Blueprint, render_template, request, redirect
index_bp = Blueprint('index', __name__)

@index_bp.route("/")
def index():
    dict_data = dict(
        v0 = app.config["V0"],
        t0 = app.config["T0"],
        delta_t_h       = app.config["DELTA_T_HIGH"],
        delta_t_h_prime = app.config["DELTA_T_HIGH_PRIME"],
        delta_t_l       = app.config["DELTA_T_LOW"],
        delta_t_l_prime = app.config["DELTA_T_LOW_PRIME"]    
    )
    return render_template('index.html', dict_data=dict_data)