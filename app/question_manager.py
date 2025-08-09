"""
Question Manager for School Hackathon
Handles question access, timers, and submission logic.
Compatible with Python 3.10+
"""
import os
import json
import time
from threading import Lock

class QuestionManager:
    def __init__(self, questions_dir, submissions_dir, logins_path, db_path):
        self.questions_dir = questions_dir
        self.submissions_dir = submissions_dir
        self.logins_path = logins_path
        self.db_path = db_path
        self.lock = Lock()
        self.timers = {
            "question1": 600,  # 10 min
            "question2": 900,  # 15 min
            "question3": 1200, # 20 min
            "question4": 900,  # 15 min
            "question5": 600   # 10 min
        }
        self.load_logins()
        self._init_db()

    def load_logins(self):
        with open(self.logins_path, 'r') as f:
            self.logins = json.load(f)

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
            conn.commit()

    def get_question_text(self, qname):
        qpath = os.path.join(self.questions_dir, f"{qname}.txt")
        if os.path.exists(qpath):
            with open(qpath, 'r') as f:
                return f.read()
        return None

    def start_timer(self, username, qname):
        import sqlite3, time
        with self.lock, sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT start_time FROM submissions WHERE username=? AND question=?", (username, qname))
            row = c.fetchone()
            if not row:
                c.execute("INSERT INTO submissions (username, question, submitted, start_time) VALUES (?, ?, 0, ?)", (username, qname, time.time()))
                conn.commit()

    def get_time_left(self, username, qname):
        import sqlite3, time
        with self.lock, sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT start_time FROM submissions WHERE username=? AND question=?", (username, qname))
            row = c.fetchone()
            if row and row[0]:
                elapsed = time.time() - row[0]
                left = self.timers[qname] - elapsed
                return max(0, int(left))
            return self.timers[qname]

    def can_access(self, username, qname):
        left = self.get_time_left(username, qname)
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT submitted FROM submissions WHERE username=? AND question=?", (username, qname))
            row = c.fetchone()
            submitted = row and row[0]
        return left > 0 and not submitted

    def submit_answer(self, username, qname, file_path):
        import sqlite3
        with self.lock:
            # Save submission file
            user_dir = os.path.join(self.submissions_dir, username)
            os.makedirs(user_dir, exist_ok=True)
            dest = os.path.join(user_dir, f"{qname}.py")
            os.replace(file_path, dest)
            
            # Update database
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                # Insert or update submission status
                c.execute("""
                    INSERT OR REPLACE INTO submissions 
                    (username, question, submitted, start_time)
                    VALUES (?, ?, 1, COALESCE(
                        (SELECT start_time FROM submissions WHERE username=? AND question=?),
                        ?
                    ))
                """, (username, qname, username, qname, time.time()))
                conn.commit()

    def has_submitted(self, username, qname):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT submitted FROM submissions WHERE username=? AND question=?", (username, qname))
            row = c.fetchone()
            return row and row[0]

    def get_all_submissions(self):
        import sqlite3
        result = {}
        
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT username, question, submitted FROM submissions")
            rows = c.fetchall()
            
            # Initialize result with all users who have any submission
            for username, _, _ in rows:
                if username not in result:
                    result[username] = {q: False for q in self.timers.keys()}
            
            # Update with actual submission status
            for username, question, submitted in rows:
                result[username][question] = bool(submitted)
                
            # Check file system for submissions as backup
            for username in result.keys():
                user_dir = os.path.join(self.submissions_dir, username)
                if os.path.exists(user_dir):
                    for qname in self.timers.keys():
                        if os.path.exists(os.path.join(user_dir, f"{qname}.py")):
                            result[username][qname] = True
        
        return result

    def reset(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM submissions")
            conn.commit()

# Usage example:
# qm = QuestionManager('app/questions', 'app/submissions', 'app/logins.json')
# qm.start_timer('student1', 'question1')
# print(qm.get_time_left('student1', 'question1'))
