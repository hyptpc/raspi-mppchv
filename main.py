import logging
from mppc_app import app

if __name__ == '__main__':
    l = logging.getLogger()
    l.addHandler(logging.FileHandler("/dev/null"))
    app.run()