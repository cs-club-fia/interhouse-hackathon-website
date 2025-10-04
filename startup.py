"""
Startup Script for School Hackathon Server
Checks dependencies, creates directories/files, runs server
Compatible with Python 3.10+
"""
import os
import subprocess
import sys

def make_venv():
    if not os.path.exists('.venv'):
        print("Python version: ", sys.version)
        print("Creating virtual environment...")
        try:
            subprocess.check_call([sys.executable, '-m', 'venv', '.venv'])
            print("Virtual environment created.")
            # Upgrade pip inside the venv
            vpy = get_venv_python()
            if vpy and os.path.exists(vpy):
                print("Upgrading pip inside virtualenv...")
                subprocess.check_call([vpy, '-m', 'pip', 'install', '--upgrade', 'pip'])
        except Exception as e:
            print(f"Failed to create virtualenv: {e}")
            raise
        
    else:
        print("Virtual environment already exists.")
def check_dependencies():
    print("Checking dependencies...")
    # Prefer to check imports inside the virtualenv (if present); otherwise check current interpreter
    python_exec = get_venv_python() if os.path.exists('.venv') else sys.executable
    check_cmd = [python_exec, '-c', 'import flask, flask_login, werkzeug, cryptography, psutil']
    try:
        res = subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            print(f"All dependencies importable in interpreter: {python_exec}")
            return
    except Exception:
        pass

    # If we get here, dependencies are not importable in the chosen interpreter; attempt install
    print(f"Dependencies missing in {python_exec}. Installing from requirements.txt...")
    if not os.path.exists('requirements.txt'):
        print('requirements.txt not found, skipping automatic install.')
        return
    try:
        subprocess.check_call([python_exec, '-m', 'pip', 'install', '-r', 'requirements.txt'])
    except Exception as e:
        print(f"Failed to install dependencies into {python_exec}: {e}")
        raise

def create_dirs():
    print("Creating directories...")
    dirs = [
        'app/static', 'app/templates', 'app/questions', 'app/submissions', 'app/uploads'
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    # Ensure img folder exists for logos, etc.
    os.makedirs(os.path.join('app', 'img'), exist_ok=True)
    # Ensure logs directory exists for server output
    os.makedirs(os.path.join('app', 'logs'), exist_ok=True)

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
    print("Starting server...")
    python_exec = get_venv_python() if os.path.exists('.venv') else sys.executable
    # Replace the current process with the server process so logs and signals behave
    # exactly as when running `python app/server.py` directly.
    # We still print the log file location for convenience.
    log_path = os.path.join('app', 'logs', 'server.log')
    print(f"Server will write output to: {log_path} (server process will now start)")
    # Ensure the environment is unbuffered so output appears promptly
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    # Use os.execv to replace the current process
    try:
        os.execv(python_exec, [python_exec, 'app/server.py'])
    except Exception as e:
        print(f"Failed to exec server process: {e}")
        raise


def get_venv_python():
    """Return the path to the virtualenv python executable if .venv exists."""
    if os.name == 'nt':
        return os.path.join('.venv', 'Scripts', 'python.exe')
    else:
        return os.path.join('.venv', 'bin', 'python')

if __name__ == '__main__':
    make_venv()
    check_dependencies()
    create_dirs()
    create_files()
    run_server()
