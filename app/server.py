"""
Main Flask Server for School Hackathon
HTTPS, login, question/timer logic, submissions, admin dashboard
Compatible with Python 3.10+
"""
# Do not use eventlet monkey-patching here. Eventlet can be incompatible with
# some Python versions (notably 3.13+) and causes import-time crashes. We force
# the safe 'threading' async mode for Flask-SocketIO so the server starts
# reliably in development environments.
USE_EVENTLET = False

import os
import ssl
import json
import sqlite3  # Add this import
import traceback
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
import psutil
from question_manager import QuestionManager
from flask_socketio import SocketIO, emit
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Config ---
QUESTIONS_DIR = os.path.join(os.path.dirname(__file__), 'questions')
SUBMISSIONS_DIR = os.path.join(os.path.dirname(__file__), 'submissions')
LOGINS_PATH = os.path.join(os.path.dirname(__file__), 'logins.json')
SSL_CERT = os.path.join(os.path.dirname(__file__), 'cert.pem')
SSL_KEY = os.path.join(os.path.dirname(__file__), 'key.pem')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'py'}

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallbacksecretkey')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
login_manager = LoginManager()
login_manager.init_app(app)
async_mode = 'threading'
socketio = SocketIO(
    app,
    async_mode=async_mode,
    logger=True,
    engineio_logger=True,
    cors_allowed_origins='*'
)
# Configure logging so that Flask/Werkzeug request logs go to stdout
import logging, sys
root_logger = logging.getLogger()
if not root_logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(h)
root_logger.setLevel(logging.INFO)

# Ensure the Werkzeug logger (HTTP request logging) also writes to stdout
werk_logger = logging.getLogger('werkzeug')
if not any(isinstance(h, logging.StreamHandler) for h in werk_logger.handlers):
    werk_logger.addHandler(logging.StreamHandler(sys.stdout))
werk_logger.setLevel(logging.INFO)
# Attach same handlers to werkzeug and app logger to ensure consistent output
for h in root_logger.handlers:
    if h not in werk_logger.handlers:
        werk_logger.addHandler(h)
app.logger.handlers = root_logger.handlers
app.logger.setLevel(logging.INFO)

# --- Request logging (ensure every HTTP request/response is recorded) ---
from flask import has_request_context


@app.before_request
def log_request_info():
    try:
        addr = request.remote_addr or 'unknown'
        app.logger.info(f"HTTP REQUEST: {request.method} {request.path} from {addr} UA={request.headers.get('User-Agent')}")
    except Exception:
        app.logger.exception('Failed to log request info')


@app.after_request
def log_response_info(response):
    try:
        addr = request.remote_addr or 'unknown'
        app.logger.info(f"HTTP RESPONSE: {request.method} {request.path} -> {response.status} to {addr}")
    except Exception:
        app.logger.exception('Failed to log response info')
    return response

DB_PATH = os.path.join(os.path.dirname(__file__), 'submissions.db')
qm = QuestionManager(QUESTIONS_DIR, SUBMISSIONS_DIR, LOGINS_PATH, DB_PATH)
errors = []

# Ensure the logs directory exists
os.makedirs(os.path.join(os.path.dirname(__file__), 'logs'), exist_ok=True)
# Initialize logging
logging.basicConfig(filename='app/logs/errors.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# --- User Model ---
class User(UserMixin):
    def __init__(self, username, is_admin=False):
        self.id = username
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    for s in qm.logins['students']:
        if s['username'] == user_id:
            return User(user_id)
    for a in qm.logins['admins']:
        if a['username'] == user_id:
            return User(user_id, is_admin=True)
    return None

# --- Helpers ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def log_error(msg):
    errors.append(msg)
    if len(errors) > 10:
        errors.pop(0)
    socketio.emit('error_update', {'errors': errors}, namespace='/admin')
    logging.error(msg)

# --- Routes ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        for s in qm.logins['students']:
            if s['username'] == username and s['password'] == password:
                login_user(User(username))
                return redirect(url_for('dashboard'))
        for a in qm.logins['admins']:
            if a['username'] == username and a['password'] == password:
                login_user(User(username, is_admin=True))
                return redirect(url_for('admin_dashboard'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html', error=None)

# Update and add explicit route for dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
        
    # Check if user has started any questions
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM submissions WHERE username=?", (current_user.id,))
        has_started = c.fetchone()[0] > 0
    
    if not has_started:
        return render_template('start_test.html', username=current_user.id)
    
    questions = list(qm.timers.keys())

    # Build a submitted map so the template can check per-question submission status
    submitted = {}
    current_question = None
    for q in questions:
        # First try the QuestionManager API
        try:
            submitted[q] = bool(qm.has_submitted(current_user.id, q))
        except Exception:
            # Fallback: check for file on disk
            submitted[q] = os.path.exists(os.path.join(SUBMISSIONS_DIR, current_user.id, f"{q}.py"))

    # Determine the current active/available question: the first question not submitted
    for q in questions:
        if not submitted.get(q):
            current_question = q
            break

    return render_template('dashboard.html', 
                         username=current_user.id, 
                         questions=questions,
                         submitted=submitted,
                         current_question=current_question)

# Add route for start test
@app.route('/start_test', methods=['GET'])
@login_required
def start_test():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return render_template('start_test.html', username=current_user.id)

# Update review route
@app.route('/review')
@login_required
def review():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    submissions = {}
    from datetime import datetime
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        questions = list(qm.timers.keys())
        for qname in questions:
            c.execute("""
                SELECT submitted, start_time 
                FROM submissions 
                WHERE username=? AND question=?
            """, (current_user.id, qname))
            row = c.fetchone()
            file_exists = os.path.exists(os.path.join(SUBMISSIONS_DIR, current_user.id, f"{qname}.py"))
            
            submissions[qname] = {
                'name': qname,
                'submitted': bool(row and row[0]) or file_exists,
                'time': datetime.fromtimestamp(row[1]).strftime('%Y-%m-%d %H:%M:%S') if row and row[1] else None
            }
    
    return render_template('review.html', submissions=submissions)

@app.route('/question', methods=['GET', 'POST'])
@login_required
def question():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    qname = request.args.get('qname')
    if not qname:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        # Support auto-submit when timer expires (client may post auto_submit=1)
        if request.form.get('auto_submit') == '1':
            try:
                # If there is no uploaded file, create an empty .py file for this user/question
                user_dir = os.path.join(SUBMISSIONS_DIR, current_user.id)
                os.makedirs(user_dir, exist_ok=True)
                dest = os.path.join(user_dir, f"{qname}.py")
                # Create an empty file only if it doesn't already exist
                if not os.path.exists(dest):
                    with open(dest, 'w', encoding='utf-8') as f:
                        f.write('# auto-submitted empty file\n')
                # Mark submission in DB (use qm.submit_answer by creating a temporary path)
                # Create a small temp file path to pass into qm.submit_answer
                temp_path = dest
                qm.submit_answer(current_user.id, qname, temp_path)

                # Redirect to next question or review
                questions = list(qm.timers.keys())
                current_idx = questions.index(qname)
                next_question = questions[current_idx + 1] if current_idx < len(questions) - 1 else None
                if next_question:
                    return redirect(url_for('question', qname=next_question))
                else:
                    return redirect(url_for('review'))
            except Exception as e:
                log_error(traceback.format_exc())
                return ("", 500)

        # Normal uploaded-file handling
        if 'answer' not in request.files:
            return render_template('question.html', qname=qname, 
                                error='No file uploaded', 
                                time_left=qm.get_time_left(current_user.id, qname),
                                question_text=qm.get_question_text(qname))
        
        file = request.files['answer']
        if file.filename == '':
            return render_template('question.html', qname=qname, 
                                error='No file selected', 
                                time_left=qm.get_time_left(current_user.id, qname),
                                question_text=qm.get_question_text(qname))
        
        if file and allowed_file(file.filename):
            try:
                filename = secure_filename(file.filename)
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file.save(temp_path)
                qm.submit_answer(current_user.id, qname, temp_path)
                
                # Find next question
                questions = list(qm.timers.keys())
                current_idx = questions.index(qname)
                next_question = questions[current_idx + 1] if current_idx < len(questions) - 1 else None
                
                if next_question:
                    return redirect(url_for('question', qname=next_question))
                else:
                    return redirect(url_for('review'))
                    
            except Exception as e:
                error = str(e)
                log_error(traceback.format_exc())
                return render_template('question.html', qname=qname, 
                                    error=error,
                                    time_left=qm.get_time_left(current_user.id, qname),
                                    question_text=qm.get_question_text(qname))
    
    # GET request handling
    if not qm.can_access(current_user.id, qname):
        return redirect(url_for('review'))
        
    return render_template('question.html', 
                         qname=qname,
                         time_left=qm.get_time_left(current_user.id, qname),
                         question_text=qm.get_question_text(qname))

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# Serve favicon to avoid 500 errors when browser requests /favicon.ico
@app.route('/favicon.ico')
def favicon():
    try:
        # Prefer a real file in static/ if present
        static_favicon = os.path.join(os.path.dirname(__file__), 'static', 'favicon.ico')
        if os.path.exists(static_favicon):
            return send_from_directory(os.path.join(os.path.dirname(__file__), 'static'), 'favicon.ico')
        # If no favicon provided, return 204 No Content so browsers stop requesting
        return ('', 204)
    except Exception:
        # Log and return a small 204 instead of causing a 500
        log_error('Failed to serve favicon.ico')
        return ('', 204)


# Serve images from app/img directory (for logos placed outside static/)
@app.route('/img/<path:filename>')
def img_file(filename):
    img_dir = os.path.join(os.path.dirname(__file__), 'img')
    return send_from_directory(img_dir, filename)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    submissions = qm.get_all_submissions()
    leave_counts = qm.get_leave_counts()
    # Count users with any timer started
    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(DISTINCT username) FROM submissions WHERE start_time IS NOT NULL")
        user_count = c.fetchone()[0]
    system_status = f"CPU: {psutil.cpu_percent()}% | RAM: {psutil.virtual_memory().percent}%"
    success_message = session.pop('success_message', None)
    return render_template('admin.html', 
                         user_count=user_count, 
                         submissions=submissions, 
                         questions=list(qm.timers.keys()), 
                         system_status=system_status, 
                         errors=errors,
                         success_message=success_message,
                         leave_counts=leave_counts)


@app.route('/admin/stats')
@login_required
def admin_stats():
    if not current_user.is_admin:
        return ("", 403)
    try:
        return {
            'cpu': psutil.cpu_percent(),
            'ram': psutil.virtual_memory().percent
        }
    except Exception as e:
        log_error(f"admin_stats error: {e}")
        return ({}, 500)


# Endpoint for students to report they left/blurred the page
@app.route('/student/leave', methods=['POST'])
@login_required
def student_leave():
    # Only allow students (not admins) to report
    if current_user.is_admin:
        return ("", 403)
    try:
        qm.increment_leave_count(current_user.id)
        return ('', 204)
    except Exception as e:
        log_error(f"student_leave error: {e}")
        return ('', 500)

@app.route('/admin/logout', methods=['POST'])
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin/download/<username>/<qname>')
@login_required
def admin_download(username, qname):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    user_dir = os.path.join(SUBMISSIONS_DIR, username)
    filename = f"{qname}.py"
    if os.path.exists(os.path.join(user_dir, filename)):
        return send_from_directory(user_dir, filename, as_attachment=True)
    return "File not found", 404

# Change the route from '/admin/reset' to '/reset-database'
@app.route('/admin/reset', methods=['POST'])  # Changed from reset-database
@login_required
def reset_database():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    try:
        # Delete all submission files
        import shutil
        if os.path.exists(SUBMISSIONS_DIR):
            shutil.rmtree(SUBMISSIONS_DIR)
            os.makedirs(SUBMISSIONS_DIR)
            
        # Reset database
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM submissions")
            conn.commit()
            
        # Clear error logs
        global errors
        errors = []
        
        session['success_message'] = "Database successfully reset. All submissions have been cleared."
        return redirect(url_for('admin_dashboard'))
        
    except Exception as e:
        log_error(f"Database reset failed: {str(e)}\n{traceback.format_exc()}")
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/logs', methods=['GET'])
@login_required
def view_logs():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))

    log_file_path = os.path.join(os.path.dirname(__file__), 'logs', 'errors.log')
    if os.path.exists(log_file_path):
        with open(log_file_path, 'r') as log_file:
            logs = log_file.readlines()
        return render_template('admin_logs.html', logs=logs)
    else:
        return render_template('admin_logs.html', logs=None)

# --- Error Handling ---
@app.errorhandler(Exception)
def handle_exception(e):
    # If it's an HTTPException (like 401, 403, 404), let Flask handle it normally
    if isinstance(e, HTTPException):
        # Return the original HTTP exception
        return e
    # Otherwise log full traceback and return generic 500
    log_error(traceback.format_exc())
    return "An error occurred. Please contact admin.", 500

# --- SSL Context ---
def get_ssl_context():
    if not os.path.exists(SSL_CERT) or not os.path.exists(SSL_KEY):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        import datetime
        # Generate key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        with open(SSL_KEY, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        # Generate cert
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u"School"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Hackathon"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
        ])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
            key.public_key()
        ).serial_number(x509.random_serial_number()).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"localhost")]), critical=False,
        ).sign(key, hashes.SHA256(), default_backend())
        with open(SSL_CERT, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(SSL_CERT, SSL_KEY)
    return context

# --- SocketIO Events ---
@socketio.on('connect', namespace='/admin')
def admin_connect():
    emit('error_update', {'errors': errors})
    emit('stats_update', {
        'cpu': psutil.cpu_percent(),
        'ram': psutil.virtual_memory().percent
    })

@socketio.on('request_stats', namespace='/admin')
def send_stats():
    emit('stats_update', {
        'cpu': psutil.cpu_percent(),
        'ram': psutil.virtual_memory().percent
    })

# --- Run Server ---
def run_server():
    print("Initializing server...")
    app.debug = True
    
    # Print registered routes for debugging
    print("\nRegistered routes:")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule.methods} {rule.rule}")
    
    with app.app_context():
        # If running in production (or if USE_WAITRESS=1), use Waitress WSGI server
        # to avoid the development server warning and provide a production-ready
        # WSGI server on Windows. Note: Waitress does not support WebSocket
        # transports — Socket.IO will fall back to polling unless eventlet/gevent
        # is used.
        use_waitress = os.getenv('USE_WAITRESS') == '1' or os.getenv('PRODUCTION') == '1'
        if use_waitress:
            try:
                from waitress import serve
                print('Starting server under Waitress WSGI server (production mode)')
                # Wrap the Socket.IO app as a WSGI application
                wsgi_app = socketio.WSGIApp(app)
                serve(wsgi_app, host='0.0.0.0', port=5000)
                return
            except Exception as e:
                print(f'Waitress not available or failed to start: {e}. Falling back to socketio.run()')

        socketio.run(
            app,
            host='0.0.0.0',
            port=5000,
            debug=True,
            use_reloader=False
        )

if __name__ == '__main__':
    run_server()

# Add indexes to the database
def _init_db(self):
    import sqlite3
    with sqlite3.connect(self.db_path) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS submissions (
            username TEXT,
            question TEXT,
            submitted INTEGER,
            start_time REAL,
            PRIMARY KEY (username, question)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_username ON submissions (username)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_question ON submissions (question)')
        conn.commit()
