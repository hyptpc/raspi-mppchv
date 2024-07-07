# argparse.ArgumentParserクラスをインスタンス化して、説明等を引数として渡す
# ---------------------------------------------------------------------------
import argparse
parser = argparse.ArgumentParser(
    prog="main",
    usage="python3 main.py <conf_file_path>", # プログラムの利用方法
    description="start mppc controller app", # ヘルプの前に表示
    epilog="end", # ヘルプの後に表示
    add_help=True, # -h/–-helpオプションの追加
)
parser.add_argument("conf_file_path", type=str, help="Input conf file path")
args = parser.parse_args()
# ---------------------------------------------------------------------------

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import yaml

app = Flask(__name__)

with open(args.conf_file_path, 'r') as file:
    config = yaml.safe_load(file)
app.config.update(config)

db = SQLAlchemy(app)
from mppc_app.models import log, mppc_data

# Blueprintの登録
from mppc_app.views.index import index_bp
from mppc_app.views.action import action_bp
app.register_blueprint(index_bp)
app.register_blueprint(action_bp)