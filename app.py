from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import re

from db import fetch_one, fetch_all, execute_query
from auth import login_required, current_user

app = Flask(__name__)
app.secret_key = 'shopsocial-secret-key-change-this-later-2026'


# Makes current_user() available inside ALL html templates
@app.context_processor
def inject_user():
    return dict(user=current_user())


# ==================================================
#                   HOME PAGE
# ==================================================
@app.route('/')
def home():
    products = fetch_all("SELECT * FROM products WHERE is_active = TRUE LIMIT 8")
    categories = fetch_all("SELECT * FROM categories WHERE is_active = TRUE")
    return render_template('index.html', products=products, categories=categories)


# ==================================================
#                   REGISTER
# ==================================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    # If already logged in, no need to register
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # ---------- VALIDATION ----------
        errors = []

        if len(full_name) < 3:
            errors.append("Name must be at least 3 characters.")

        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            errors.append("Please enter a valid email address.")

        if phone and not re.match(r'^\d{10}$', phone):
            errors.append("Phone number must be exactly 10 digits.")

        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")

        if password != confirm_password:
            errors.append("Passwords do not match.")

        # Check if email already registered
        existing = fetch_one("SELECT user_id FROM users WHERE email = %s", (email,))
        if existing:
            errors.append("This email is already registered. Try logging in.")

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('register.html',
                                   full_name=full_name, email=email, phone=phone)

        # ---------- SAVE USER ----------
        hashed_password = generate_password_hash(password)

        user_id = execute_query(
            """INSERT INTO users (full_name, email, password, phone, role)
               VALUES (%s, %s, %s, %s, 'customer')
               RETURNING user_id""",
            (full_name, email, hashed_password, phone),
            return_id=True
        )

        if user_id:
            flash('Account created successfully! Please login. 🎉', 'success')
            return redirect(url_for('login'))
        else:
            flash('Something went wrong. Please try again.', 'error')

    return render_template('register.html')


# ==================================================
#                     LOGIN
# ==================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = fetch_one("SELECT * FROM users WHERE email = %s", (email,))

        if user and check_password_hash(user['password'], password):
            # Store user info in session
            session['user_id'] = user['user_id']
            session['full_name'] = user['full_name']
            session['email'] = user['email']
            session['role'] = user['role']
            session.permanent = True

            flash(f"Welcome back, {user['full_name'].split()[0]}! 👋", 'success')

            # Redirect to page they wanted before login (if any)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home'))
        else:
            flash('Invalid email or password. Please try again.', 'error')

    return render_template('login.html')


# ==================================================
#                     LOGOUT
# ==================================================
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('home'))


# ==================================================
#              PROFILE (Protected Page)
# ==================================================
@app.route('/profile')
@login_required
def profile():
    user_data = fetch_one(
        "SELECT user_id, full_name, email, phone, role, created_at FROM users WHERE user_id = %s",
        (session['user_id'],)
    )
    return render_template('profile.html', user_data=user_data)


# ==================================================
#                   API ROUTES
# ==================================================
@app.route('/api/db-test')
def db_test():
    products = fetch_all("SELECT * FROM products")
    return jsonify({
        "status": "success",
        "message": f"Found {len(products)} products in database",
        "products": products
    })
# ==================================================
#               PRODUCT CATALOG PAGE
# ==================================================
@app.route('/products')
def products():
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '')
    sort_by = request.args.get('sort', '')

    # Base SQL query
    query = "SELECT p.*, c.name as category_name FROM products p JOIN categories c ON p.category_id = c.category_id WHERE p.is_active = TRUE"
    params = []

    # 1. Search filter
    if search_query:
        query += " AND (p.name ILIKE %s OR p.brand ILIKE %s OR p.description ILIKE %s)"
        like_pattern = f"%{search_query}%"
        params.extend([like_pattern, like_pattern, like_pattern])

    # 2. Category filter
    if category_filter:
        query += " AND c.name = %s"
        params.append(category_filter)

    # 3. Sorting logic
    if sort_by == 'price_low':
        query += " ORDER BY (p.price * (100 - p.discount_percent) / 100) ASC"
    elif sort_by == 'price_high':
        query += " ORDER BY (p.price * (100 - p.discount_percent) / 100) DESC"
    else:
        query += " ORDER BY p.created_at DESC"

    products_list = fetch_all(query, tuple(params))
    categories = fetch_all("SELECT * FROM categories WHERE is_active = TRUE")

    return render_template('products.html', 
                           products=products_list, 
                           categories=categories,
                           search=search_query,
                           selected_category=category_filter,
                           sort=sort_by)


# ==================================================
#               PRODUCT DETAIL PAGE
# ==================================================
@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = fetch_one(
        "SELECT p.*, c.name as category_name FROM products p JOIN categories c ON p.category_id = c.category_id WHERE p.product_id = %s",
        (product_id,)
    )
    
    if not product:
        flash("Product not found!", "error")
        return redirect(url_for('products'))
        
    # Fetch related products (same category, excluding current product)
    related = fetch_all(
        "SELECT * FROM products WHERE category_id = %s AND product_id != %s AND is_active = TRUE LIMIT 4",
        (product['category_id'], product['product_id'])
    )
    
    return render_template('product-detail.html', product=product, related=related)

if __name__ == '__main__':
    app.run(debug=True, port=5000)