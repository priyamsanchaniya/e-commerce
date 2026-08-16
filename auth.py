from functools import wraps
from flask import session, redirect, url_for, flash


def login_required(f):
    """
    Decorator: put @login_required above any route
    that should only be visible to logged-in users.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator: only allows admin users"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'error')
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


def current_user():
    """Returns a dict of the logged-in user, or None"""
    if 'user_id' in session:
        return {
            'user_id': session['user_id'],
            'full_name': session.get('full_name'),
            'email': session.get('email'),
            'role': session.get('role')
        }
    return None