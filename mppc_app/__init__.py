from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

import yaml
with open('param/config.yaml', 'r') as file:
    config = yaml.safe_load(file)
app.config.update(config)


db = SQLAlchemy(app)
from mppc_app.models import log, mppc_data

# Blueprintの登録
from mppc_app.views.index import index_bp
from mppc_app.views.action import action_bp
app.register_blueprint(index_bp)
app.register_blueprint(action_bp)


# db = SQLAlchemy()

# def initialize_app():
#     # appの設定
#     app = Flask(__name__)
#     app.config.from_pyfile('config.py')

#     # DBの設定
#     db.init_app(app)
#     from flask_app import models

#     # Blueprintの登録
#     from flask_app.views.index import index_bp
#     from flask_app.views.sample import sample_bp
#     app.register_blueprint(index_bp)
#     app.register_blueprint(sample_bp)

#     return app