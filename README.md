# School Hackathon Flask Server

This project is a secure, efficient, and modern Flask-based web server for school hackathons. It supports login, timed question access, file uploads, real-time statistics, and a beautiful glassmorphism UI.

## Features
- HTTPS with auto-generated SSL certificates
- User login via JSON credentials
- Timed access to 5 questions
- Individual .py file uploads per question
- Responsive, modern UI (glassmorphism)
- Real-time admin dashboard: stats, submissions, errors
- Automatic setup and dependency check

## Setup
1. Create a Python 3.10+ virtual environment in the `website` folder.
2. Run `startup.py` to set up directories, dependencies, and start the server.

## Usage
- Students log in and submit answers to questions before their timers expire.
- Admins monitor submissions, errors, and system status in real time.

## Directory Structure
- `app/static/` - CSS, JS, images
- `app/templates/` - HTML templates
- `app/questions/` - Question text files
- `app/submissions/` - Student submissions
- `app/logins.json` - User credentials
- `app/question_manager.py` - Question logic
- `app/server.py` - Main Flask server
- `startup.py` - Setup and run script

## Improvements
## How to Apply Improvements

**Production Concurrency:**
- Use Gunicorn (Linux/macOS) or Waitress (Windows) to run the server for better performance:
    - Gunicorn: `gunicorn app.server:app --certfile=app/cert.pem --keyfile=app/key.pem --threads 8`
    - Waitress: `waitress-serve --port=443 --call app.server:app`

**Scalable Submission Tracking:**
- Replace in-memory submission tracking with SQLite:
    - Use `sqlite3` to store submissions and user activity for reliability and scalability.
    - Update `question_manager.py` to use a database for all submission and timer logic.

**Real-time Updates:**
- Integrate Flask-SocketIO for live admin dashboard updates:
    - Add `Flask-SocketIO` to `requirements.txt`.
    - Use SocketIO events to push stats and errors to the admin dashboard in real time.

## License
MIT
