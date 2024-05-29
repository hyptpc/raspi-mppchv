from mppc_app import db
from datetime import datetime

class MPPC_data(db.Model):
    __bind_key__ = 'mppc_data'
    __tablename__ = 'mppc_data'
    id    = db.Column(db.Integer, primary_key=True)
    hv1   = db.Column(db.Float)
    temp1 = db.Column(db.Float)
    curr1 = db.Column(db.Float)
    hv2   = db.Column(db.Float)
    temp2 = db.Column(db.Float)
    curr2 = db.Column(db.Float)
    hv3   = db.Column(db.Float)
    temp3 = db.Column(db.Float)
    curr3 = db.Column(db.Float)
    hv4   = db.Column(db.Float)
    temp4 = db.Column(db.Float)
    curr4 = db.Column(db.Float)
    time  = db.Column(db.DateTime, nullable=False, default=datetime.now)