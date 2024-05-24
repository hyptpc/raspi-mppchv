DEBUG = True

db_uri_log     = 'sqlite:///log.db'
db_uri_hv_temp = 'sqlite:///mppc_data.db'

SQLALCHEMY_DATABASE_URI = db_uri_log
SQLALCHEMY_BINDS = {"mppc_data": db_uri_hv_temp}

SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ECHO = False