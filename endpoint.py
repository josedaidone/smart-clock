import os
import json
from flask import Flask, abort, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_httpauth import HTTPBasicAuth
from secret_db import users
import random

app = Flask(__name__, static_url_path="")

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["1 per second","45 per minute"],
    application_limits=["1 per second","45 per minute"]
)

auth = HTTPBasicAuth()

@auth.get_password
def get_pw(username):
    if username in users:
        return users.get(username)
    return None

@app.route('/')
def root():
    return app.send_static_file('index.html')

@app.route('/start/')
@auth.login_required
def start():
     os.system('sudo python /home/pi/dev/digital_clock_python/clock.py restart')
     return 'starting'

@app.route('/stop/')
@auth.login_required
def stop():
    os.system('sudo python /home/pi/dev/digital_clock_python/clock.py stop')
    return 'stopping'

@app.route('/text/<msg>')
@auth.login_required
@limiter.shared_limit("1 per 1 seconds", "teste")
def text(msg):
    os.system('sudo python /home/pi/dev/digital_clock_python/clock.py msg "' + msg + '"')
    return 'sending msg: '+msg

@app.route('/msg/', methods=['POST'])
@auth.login_required
@limiter.shared_limit("1 per 10 seconds", "teste")
def msg():
    if not request.json:
        abort(400)
    msg = request.json['msg']
    os.system('sudo python /home/pi/dev/digital_clock_python/clock.py msg "' + msg + '"')
    return json.dumps(request.json)

if __name__ == '__main__':
    # subprocess.call("python /home/pi/dev/digital_clock_python/clock.py &",shell=True)
    app.run(debug=True, host='0.0.0.0')
