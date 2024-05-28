from mppc_app import app
from flask import Blueprint, render_template
index_bp = Blueprint('index', __name__)

@index_bp.route("/")
def index():
    param_data = dict(
        module1= dict(
            v0 = app.config["MODULE1"]["V0"],
            t0 = app.config["MODULE1"]["T0"],
            delta_t_h       = app.config["MODULE1"]["DELTA_T_HIGH"],
            delta_t_h_prime = app.config["MODULE1"]["DELTA_T_HIGH_PRIME"],
            delta_t_l       = app.config["MODULE1"]["DELTA_T_LOW"],
            delta_t_l_prime = app.config["MODULE1"]["DELTA_T_LOW_PRIME"]
        ),
        module2= dict(
            v0 = app.config["MODULE2"]["V0"],
            t0 = app.config["MODULE2"]["T0"],
            delta_t_h       = app.config["MODULE2"]["DELTA_T_HIGH"],
            delta_t_h_prime = app.config["MODULE2"]["DELTA_T_HIGH_PRIME"],
            delta_t_l       = app.config["MODULE2"]["DELTA_T_LOW"],
            delta_t_l_prime = app.config["MODULE2"]["DELTA_T_LOW_PRIME"]
        ),
        module3= dict(
            v0 = app.config["MODULE3"]["V0"],
            t0 = app.config["MODULE3"]["T0"],
            delta_t_h       = app.config["MODULE3"]["DELTA_T_HIGH"],
            delta_t_h_prime = app.config["MODULE3"]["DELTA_T_HIGH_PRIME"],
            delta_t_l       = app.config["MODULE3"]["DELTA_T_LOW"],
            delta_t_l_prime = app.config["MODULE3"]["DELTA_T_LOW_PRIME"]
        ),
        module4= dict(
            v0 = app.config["MODULE4"]["V0"],
            t0 = app.config["MODULE4"]["T0"],
            delta_t_h       = app.config["MODULE4"]["DELTA_T_HIGH"],
            delta_t_h_prime = app.config["MODULE4"]["DELTA_T_HIGH_PRIME"],
            delta_t_l       = app.config["MODULE4"]["DELTA_T_LOW"],
            delta_t_l_prime = app.config["MODULE4"]["DELTA_T_LOW_PRIME"]
        )
    )
    return render_template('index.html', param_data=param_data)