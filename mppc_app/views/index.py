from flask import Blueprint, render_template, request, redirect
index_bp = Blueprint('index', __name__)

import mppc_app.config

@index_bp.route("/")
def index():
    print(mppc_app.config.VMAX_MODULE1)
    return render_template('index.html')