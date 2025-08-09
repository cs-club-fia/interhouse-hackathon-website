"""
Main Flask Server for School Hackathon
HTTPS, login, question/timer logic, submissions, admin dashboard
Compatible with Python 3.10+
"""
# Monkey patch first, before any other imports
import eventlet
eventlet.monkey_patch()

import os
import ssl
import json
import sqlite3  # Add this import
import traceback
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import psutil
from question_manager import QuestionManager
from flask_socketio import SocketIO, emit

# --- Config ---
QUESTIONS_DIR = os.path.join(os.path.dirname(__file__), 'questions')
SUBMISSIONS_DIR = os.path.join(os.path.dirname(__file__), 'submissions')
LOGINS_PATH = os.path.join(os.path.dirname(__file__), 'logins.json')
SSL_CERT = os.path.join(os.path.dirname(__file__), 'cert.pem')
SSL_KEY = os.path.join(os.path.dirname(__file__), 'key.pem')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'py'}

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
login_manager = LoginManager()
login_manager.init_app(app)
socketio = SocketIO(
    app,
    async_mode='eventlet',
    logger=True,
    engineio_logger=True,
    cors_allowed_origins='*'
)

DB_PATH = os.path.join(os.path.dirname(__file__), 'submissions.db')
qm = QuestionManager(QUESTIONS_DIR, SUBMISSIONS_DIR, LOGINS_PATH, DB_PATH)
errors = []

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
    return render_template('dashboard.html', 
                         username=current_user.id, 
                         questions=questions)

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

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    submissions = qm.get_all_submissions()
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
                         success_message=success_message)

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

# --- Error Handling ---
@app.errorhandler(Exception)
def handle_exception(e):
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

# --- Run Server ---
def run_server():
    print("Initializing server...")
    app.debug = True
    
    # Print registered routes for debugging
    print("\nRegistered routes:")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule.methods} {rule.rule}")
    
    with app.app_context():
        socketio.run(
            app,
            host='0.0.0.0',
            port=5000,
            debug=True,
            use_reloader=False
        )

if __name__ == '__main__':
    run_server()
