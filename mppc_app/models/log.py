from mppc_app import db
from datetime import datetime

class Log(db.Model):
    __tablename__ = 'log'
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer)
    cmd_tx = db.Column(db.String(255))
    cmd_rx = db.Column(db.String(255), default="No return")
    status = db.Column(db.String(255))
    time = db.Column(db.DateTime, nullable=False, default=datetime.now)