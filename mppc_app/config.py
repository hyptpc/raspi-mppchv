
DEBUG = True

# HV limit setting [V]
VMAX_MODULE1 = 100
VMAX_MODULE2 = 100
VMAX_MODULE3 = 100
VMAX_MODULE4 = 100

# database setting
db_uri_log     = 'sqlite:///log.db'
db_uri_hv_temp = 'sqlite:///mppc_data.db'

SQLALCHEMY_DATABASE_URI = db_uri_log
SQLALCHEMY_BINDS = {"mppc_data": db_uri_hv_temp}

SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ECHO = False