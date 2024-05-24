from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config.from_object('mppc_app.config')

db = SQLAlchemy(app)
from mppc_app.models import log, mppc_data
# import mppc_app.views

# Blueprintの登録
from mppc_app.views.index import index_bp
from mppc_app.views.action import action_bp
app.register_blueprint(index_bp)
app.register_blueprint(action_bp)