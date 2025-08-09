"""
Startup Script for School Hackathon Server
Checks dependencies, creates directories/files, runs server
Compatible with Python 3.10+
"""
import os
import subprocess
import sys

def check_dependencies():
    print("Checking dependencies...")
    try:
        import flask, flask_login, werkzeug, cryptography, psutil
    except ImportError:
        print("Installing dependencies...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])

def create_dirs():
    print("Creating directories...")
    dirs = [
        'app/static', 'app/templates', 'app/questions', 'app/submissions', 'app/uploads'
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

def create_files():
    print("Creating files...")
    # Create logins.json if not exists
    logins_path = 'app/logins.json'
    if not os.path.exists(logins_path):
        with open(logins_path, 'w') as f:
            f.write('{"students": [{"username": "student1", "password": "pass1"}], "admins": [{"username": "admin", "password": "adminpass"}]}')
    # Create sample questions if not exists
    for i in range(1, 6):
        qpath = f'app/questions/question{i}.txt'
        if not os.path.exists(qpath):
            with open(qpath, 'w') as f:
                f.write(f'Question {i}: Sample question text.')

def get_ip_address():
    import socket
    try:
        # Get all network interfaces
        hostname = socket.gethostname()
        # Get all IPs for this machine
        ips = socket.gethostbyname_ex(hostname)[2]
        # Filter out localhost
        external_ips = [ip for ip in ips if not ip.startswith('127.')]
        return external_ips[0] if external_ips else 'localhost'
    except Exception:
        return 'localhost'

def run_server():
    ip_address = get_ip_address()
    print("\nServer Information:")
    print(f"IP Address: {ip_address}")
    print(f"Port: 5000")
    print(f"Access URLs:")
    print(f"Local: http://localhost:5000")
    print(f"Network: http://{ip_address}:5000")
    print("\nStarting server...")
    subprocess.run([sys.executable, 'app/server.py'])

if __name__ == '__main__':
    check_dependencies()
    create_dirs()
    create_files()
    run_server()
