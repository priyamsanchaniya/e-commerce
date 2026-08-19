from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime, timedelta
import re, uuid

from db import fetch_one, fetch_all, execute_query
from auth import login_required, current_user

app = Flask(__name__)
app.secret_key = 'shopsocial-secret-key-change-this-later-2026'
app.jinja_env.globals['len'] = len
# 🟢 SOCKET.IO INITIALIZATION
socketio = SocketIO(app, cors_allowed_origins="*")

# ==================================================
#   GLOBAL: user + cart count available in ALL pages
# ==================================================
@app.context_processor
def inject_globals():
    cart_count = 0
    if 'user_id' in session:
        row = fetch_one(
            "SELECT COALESCE(SUM(quantity),0) AS c FROM cart_items WHERE user_id = %s",
            (session['user_id'],)
        )
        cart_count = row['c'] if row else 0
    return dict(user=current_user(), cart_count=cart_count)


# ==================================================
#                   HOME PAGE
# ==================================================
@app.route('/')
def home():
    products = fetch_all("SELECT * FROM products WHERE is_active = TRUE LIMIT 8")
    categories = fetch_all("SELECT * FROM categories WHERE is_active = TRUE")
    return render_template('index.html', products=products, categories=categories)


# ==================================================
#                    REGISTER
# ==================================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

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
        if fetch_one("SELECT user_id FROM users WHERE email = %s", (email,)):
            errors.append("This email is already registered. Try logging in.")

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('register.html', full_name=full_name, email=email, phone=phone)

        user_id = execute_query(
            """INSERT INTO users (full_name, email, password, phone, role)
               VALUES (%s, %s, %s, %s, 'customer') RETURNING user_id""",
            (full_name, email, generate_password_hash(password), phone),
            return_id=True
        )

        if user_id:
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))
        flash('Something went wrong. Please try again.', 'error')

    return render_template('register.html')


# ==================================================
#                      LOGIN
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
            session['user_id'] = user['user_id']
            session['full_name'] = user['full_name']
            session['email'] = user['email']
            session['role'] = user['role']
            session.permanent = True
            flash(f"Welcome back, {user['full_name'].split()[0]}! 👋", 'success')
            return redirect(request.args.get('next') or url_for('home'))
        flash('Invalid email or password. Please try again.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('home'))


@app.route('/profile')
@login_required
def profile():
    user_data = fetch_one(
        "SELECT user_id, full_name, email, phone, role, created_at FROM users WHERE user_id = %s",
        (session['user_id'],)
    )
    return render_template('profile.html', user_data=user_data)


# ==================================================
#                PRODUCT CATALOG
# ==================================================
@app.route('/products')
def products():
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '')
    sort_by = request.args.get('sort', '')

    query = """SELECT p.*, c.name AS category_name FROM products p
               JOIN categories c ON p.category_id = c.category_id
               WHERE p.is_active = TRUE"""
    params = []
    if search_query:
        query += " AND (p.name ILIKE %s OR p.brand ILIKE %s OR p.description ILIKE %s)"
        like = f"%{search_query}%"
        params += [like, like, like]
    if category_filter:
        query += " AND c.name = %s"
        params.append(category_filter)
    if sort_by == 'price_low':
        query += " ORDER BY (p.price * (100 - p.discount_percent) / 100) ASC"
    elif sort_by == 'price_high':
        query += " ORDER BY (p.price * (100 - p.discount_percent) / 100) DESC"
    else:
        query += " ORDER BY p.created_at DESC"

    return render_template(
        'products.html',
        products=fetch_all(query, tuple(params)),
        categories=fetch_all("SELECT * FROM categories WHERE is_active = TRUE"),
        search=search_query,
        selected_category=category_filter,
        sort=sort_by
    )


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = fetch_one(
        """SELECT p.*, c.name AS category_name FROM products p
           JOIN categories c ON p.category_id = c.category_id
           WHERE p.product_id = %s""", (product_id,))
    if not product:
        flash("Product not found!", "error")
        return redirect(url_for('products'))
    related = fetch_all(
        """SELECT * FROM products WHERE category_id = %s
           AND product_id != %s AND is_active = TRUE LIMIT 4""",
        (product['category_id'], product['product_id']))
    return render_template('product-detail.html', product=product, related=related)


# ==================================================
#                      CART
# ==================================================
def get_cart_data(user_id):
    items = fetch_all("""
        SELECT ci.cart_item_id, ci.quantity, p.*,
               (p.price * (100 - p.discount_percent) / 100) AS final_price
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.product_id
        WHERE ci.user_id = %s
        ORDER BY ci.added_at DESC
    """, (user_id,))
    subtotal = sum(float(i['final_price']) * i['quantity'] for i in items)
    mrp_total = sum(float(i['price']) * i['quantity'] for i in items)
    savings = mrp_total - subtotal
    delivery = 0 if subtotal >= 499 or subtotal == 0 else 49
    total = subtotal + delivery
    return items, {
        'subtotal': round(subtotal, 2),
        'mrp_total': round(mrp_total, 2),
        'savings': round(savings, 2),
        'delivery': delivery,
        'total': round(total, 2)
    }


@app.route('/cart')
@login_required
def cart():
    items, totals = get_cart_data(session['user_id'])
    return render_template('cart.html', items=items, totals=totals)


@app.route('/add-to-cart/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    qty = int(request.form.get('quantity', 1))
    user_id = session['user_id']
    product = fetch_one("SELECT * FROM products WHERE product_id = %s", (product_id,))
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for('products'))
    if product['stock_quantity'] < qty:
        flash(f"Only {product['stock_quantity']} left in stock!", "error")
        return redirect(url_for('product_detail', product_id=product_id))
    existing = fetch_one(
        "SELECT * FROM cart_items WHERE user_id = %s AND product_id = %s",
        (user_id, product_id))
    if existing:
        execute_query("UPDATE cart_items SET quantity = quantity + %s WHERE cart_item_id = %s",
                      (qty, existing['cart_item_id']))
    else:
        execute_query("INSERT INTO cart_items (user_id, product_id, quantity) VALUES (%s,%s,%s)",
                      (user_id, product_id, qty))
    flash(f"{product['name']} added to cart!", "success")
    return redirect(request.referrer or url_for('products'))


@app.route('/update-cart/<int:cart_item_id>/<action>')
@login_required
def update_cart(cart_item_id, action):
    item = fetch_one("SELECT * FROM cart_items WHERE cart_item_id = %s AND user_id = %s",
                     (cart_item_id, session['user_id']))
    if not item:
        return redirect(url_for('cart'))
    if action == 'increase':
        execute_query("UPDATE cart_items SET quantity = quantity + 1 WHERE cart_item_id = %s",
                      (cart_item_id,))
    elif action == 'decrease':
        if item['quantity'] <= 1:
            execute_query("DELETE FROM cart_items WHERE cart_item_id = %s", (cart_item_id,))
        else:
            execute_query("UPDATE cart_items SET quantity = quantity - 1 WHERE cart_item_id = %s",
                          (cart_item_id,))
    return redirect(url_for('cart'))


@app.route('/remove-from-cart/<int:cart_item_id>')
@login_required
def remove_from_cart(cart_item_id):
    execute_query("DELETE FROM cart_items WHERE cart_item_id = %s AND user_id = %s",
                  (cart_item_id, session['user_id']))
    flash("Item removed from cart.", "success")
    return redirect(url_for('cart'))


# ==================================================
#                    WISHLIST
# ==================================================
@app.route('/wishlist')
@login_required
def wishlist():
    items = fetch_all("""
        SELECT w.wishlist_id, p.* FROM wishlist w
        JOIN products p ON w.product_id = p.product_id
        WHERE w.user_id = %s ORDER BY w.added_at DESC
    """, (session['user_id'],))
    return render_template('wishlist.html', items=items)


@app.route('/add-to-wishlist/<int:product_id>')
@login_required
def add_to_wishlist(product_id):
    exists = fetch_one("SELECT * FROM wishlist WHERE user_id = %s AND product_id = %s",
                       (session['user_id'], product_id))
    if exists:
        flash("Already in your wishlist ❤️", "success")
    else:
        execute_query("INSERT INTO wishlist (user_id, product_id) VALUES (%s,%s)",
                      (session['user_id'], product_id))
        flash("Added to wishlist ❤️", "success")
    return redirect(request.referrer or url_for('products'))


@app.route('/remove-wishlist/<int:wishlist_id>')
@login_required
def remove_wishlist(wishlist_id):
    execute_query("DELETE FROM wishlist WHERE wishlist_id = %s AND user_id = %s",
                  (wishlist_id, session['user_id']))
    flash("Removed from wishlist.", "success")
    return redirect(url_for('wishlist'))


# ==================================================
#              CHECKOUT + PASSPORT GENERATION
# ==================================================
def generate_passport(order_item_id, product, user_id, category_id):
    """Feature 5: Creates a Digital Product Passport"""
    passport_id = "PP-" + uuid.uuid4().hex[:10].upper()
    auth_code = "AC-" + uuid.uuid4().hex[:8].upper()
    purchase_date = datetime.now().date()
    warranty_days = 365 if category_id == 1 else 180
    warranty_expiry = purchase_date + timedelta(days=warranty_days)

    execute_query("""
        INSERT INTO product_passports
        (passport_id, order_item_id, product_id, current_owner_id, original_owner_id,
         purchase_date, warranty_expiry, authenticity_code, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active')
    """, (passport_id, order_item_id, product['product_id'], user_id, user_id,
          purchase_date, warranty_expiry, auth_code))

    execute_query("""INSERT INTO passport_history (passport_id, event_type, description)
                    VALUES (%s, 'purchase', %s)""",
                   (passport_id, f"Purchased brand new from ShopSocial."))


@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    user_id = session['user_id']
    items, totals = get_cart_data(user_id)

    if not items:
        flash("Your cart is empty!", "error")
        return redirect(url_for('cart'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        city = request.form.get('city', '').strip()
        pincode = request.form.get('pincode', '').strip()
        payment_method = request.form.get('payment_method', 'COD')

        if not all([full_name, phone, address, city, pincode]):
            flash("Please fill all delivery details.", "error")
            return render_template('checkout.html', items=items, totals=totals)

        full_address = f"{address}, {city} - {pincode}"

        order_id = execute_query("""
            INSERT INTO orders (user_id, full_name, phone, address, total_amount,
                                payment_method, payment_status, order_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'placed') RETURNING order_id
        """, (user_id, full_name, phone, full_address, totals['total'],
              payment_method, 'pending' if payment_method == 'COD' else 'paid'), return_id=True)

        if not order_id:
            flash("Order failed. Try again.", "error")
            return redirect(url_for('cart'))

        passports_created = 0
        for item in items:
            order_item_id = execute_query("""
                INSERT INTO order_items (order_id, product_id, quantity, price_at_purchase)
                VALUES (%s,%s,%s,%s) RETURNING order_item_id
            """, (order_id, item['product_id'], item['quantity'], item['final_price']),
                return_id=True)
            execute_query("UPDATE products SET stock_quantity = stock_quantity - %s WHERE product_id = %s",
                          (item['quantity'], item['product_id']))
            for _ in range(item['quantity']):
                generate_passport(order_item_id, item, user_id, item['category_id'])
                passports_created += 1

        execute_query("DELETE FROM cart_items WHERE user_id = %s", (user_id,))
        flash(f"Order placed successfully! {passports_created} Passport(s) generated.", "success")
        return redirect(url_for('order_detail', order_id=order_id))

    return render_template('checkout.html', items=items, totals=totals)


# ==================================================
#                     ORDERS
# ==================================================
@app.route('/orders')
@login_required
def orders():
    order_list = fetch_all("""
        SELECT o.*, COUNT(oi.order_item_id) AS item_count
        FROM orders o
        LEFT JOIN order_items oi ON o.order_id = oi.order_id
        WHERE o.user_id = %s
        GROUP BY o.order_id
        ORDER BY o.created_at DESC
    """, (session['user_id'],))
    return render_template('orders.html', orders=order_list)


@app.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    order = fetch_one("SELECT * FROM orders WHERE order_id = %s AND user_id = %s",
                      (order_id, session['user_id']))
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for('orders'))
    items = fetch_all("""
        SELECT oi.*, p.name, p.brand, p.category_id
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """, (order_id,))
    for it in items:
        it['passports'] = fetch_all("SELECT * FROM product_passports WHERE order_item_id = %s",
                                     (it['order_item_id'],))
    return render_template('order-detail.html', order=order, items=items)


@app.route('/cancel-order/<int:order_id>')
@login_required
def cancel_order(order_id):
    order = fetch_one("SELECT * FROM orders WHERE order_id = %s AND user_id = %s",
                      (order_id, session['user_id']))
    if order and order['order_status'] == 'placed':
        execute_query("UPDATE orders SET order_status = 'cancelled' WHERE order_id = %s", (order_id,))
        flash("Order cancelled.", "success")
    else:
        flash("Can't cancel this order.", "error")
    return redirect(url_for('orders'))


# ==================================================
#         FEATURE 5: PRODUCT PASSPORT ROUTES
# ==================================================
@app.route('/my-passports')
@login_required
def my_passports():
    passports = fetch_all("""
        SELECT pp.*, p.name, p.brand, p.category_id
        FROM product_passports pp
        JOIN products p ON pp.product_id = p.product_id
        WHERE pp.current_owner_id = %s AND pp.status = 'active'
        ORDER BY pp.created_at DESC
    """, (session['user_id'],))
    return render_template('my_passports.html', passports=passports)


@app.route('/passport/<passport_id>')
@login_required
def passport_detail(passport_id):
    pp = fetch_one("""
        SELECT pp.*, p.name, p.brand, p.description, p.category_id
        FROM product_passports pp
        JOIN products p ON pp.product_id = p.product_id
        WHERE pp.passport_id = %s
    """, (passport_id,))
    if not pp:
        flash("Passport not found!", "error")
        return redirect(url_for('my_passports'))
    if pp['current_owner_id'] != session['user_id'] and session.get('role') != 'admin':
        flash("Unauthorized access.", "error")
        return redirect(url_for('home'))
    history = fetch_all(
        "SELECT * FROM passport_history WHERE passport_id = %s ORDER BY event_date DESC",
        (passport_id,))
    return render_template('passport_detail.html', pp=pp, history=history)


# ==================================================
#                         API
# ==================================================
@app.route('/api/db-test')
def db_test():
    products = fetch_all("SELECT * FROM products")
    return jsonify({"status": "success", "count": len(products)})

# ==================================================
#         🟢 FEATURE 1: SOCIAL CART (GROUP BUYING)
# ==================================================

def calculate_group_discount(member_count):
    """Tiered discount: 2=5%, 3-4=10%, 5+=15%"""
    if member_count >= 5:
        return 15
    elif member_count >= 3:
        return 10
    elif member_count >= 2:
        return 5
    else:
        return 0


@app.route('/social-cart')
@login_required
def social_cart_create():
    """Create a new shared cart session"""
    session_id = "SC-" + uuid.uuid4().hex[:8].upper()
    user_id = session['user_id']

    # Create the social cart
    execute_query(
        "INSERT INTO social_carts (session_id, created_by, group_discount_percent, status) VALUES (%s,%s,0,'active')",
        (session_id, user_id)
    )

    # Add creator as first member
    execute_query(
        "INSERT INTO social_cart_members (session_id, user_id) VALUES (%s,%s)",
        (session_id, user_id)
    )

    flash("Social Cart created! Share the link with friends!", "success")
    return redirect(url_for('social_cart_view', session_id=session_id))


@app.route('/social-cart/<session_id>')
@login_required
def social_cart_view(session_id):
    """View/join a shared cart"""
    user_id = session['user_id']

    # Check if cart exists and is active
    cart = fetch_one("SELECT * FROM social_carts WHERE session_id = %s AND status = 'active'", (session_id,))
    if not cart:
        flash("Social cart not found or expired.", "error")
        return redirect(url_for('home'))

    # Auto-join if not already a member
    is_member = fetch_one(
        "SELECT * FROM social_cart_members WHERE session_id = %s AND user_id = %s",
        (session_id, user_id)
    )
    if not is_member:
        execute_query(
            "INSERT INTO social_cart_members (session_id, user_id) VALUES (%s,%s)",
            (session_id, user_id)
        )
        flash("You joined the social cart! 🎉", "success")

    # Get all data
    members = fetch_all("""
        SELECT scm.*, u.full_name, u.email
        FROM social_cart_members scm
        JOIN users u ON scm.user_id = u.user_id
        WHERE scm.session_id = %s
        ORDER BY scm.joined_at ASC
    """, (session_id,))

    items = fetch_all("""
        SELECT sci.*, p.name, p.brand, p.category_id, p.price, p.discount_percent,
               (p.price * (100 - p.discount_percent) / 100) AS final_price
        FROM social_cart_items sci
        JOIN products p ON sci.product_id = p.product_id
        WHERE sci.session_id = %s
        ORDER BY sci.added_at DESC
    """, (session_id,))

    messages = fetch_all("""
        SELECT scm.*, u.full_name
        FROM social_cart_messages scm
        JOIN users u ON scm.user_id = u.user_id
        WHERE scm.session_id = %s
        ORDER BY scm.sent_at ASC
    """, (session_id,))

    # All products for the picker
    all_products = fetch_all("SELECT * FROM products WHERE is_active = TRUE AND stock_quantity > 0")

    # Calculate discount
    discount = calculate_group_discount(len(members))
    execute_query("UPDATE social_carts SET group_discount_percent = %s WHERE session_id = %s",
                  (discount, session_id))

    # Calculate totals
    subtotal = sum(float(i['final_price']) * i['quantity'] for i in items)
    group_savings = (subtotal * discount) / 100
    total = subtotal - group_savings
    per_person = total / len(members) if len(members) > 0 else total

    return render_template(
        'social-cart.html',
        session_id=session_id,
        members=members,
        items=items,
        messages=messages,
        all_products=all_products,
        discount=discount,
        subtotal=subtotal,
        group_savings=group_savings,
        total=total,
        per_person=per_person
    )


@app.route('/social-cart/<session_id>/add/<int:product_id>', methods=['POST'])
@login_required
def social_cart_add(session_id, product_id):
    """Add a product to the shared cart"""
    user_id = session['user_id']
    qty = int(request.form.get('quantity', 1))

    # Verify user is a member
    is_member = fetch_one(
        "SELECT * FROM social_cart_members WHERE session_id = %s AND user_id = %s",
        (session_id, user_id)
    )
    if not is_member:
        flash("You must join the cart first!", "error")
        return redirect(url_for('social_cart_view', session_id=session_id))

    # Check if product already in social cart
    existing = fetch_one(
        "SELECT * FROM social_cart_items WHERE session_id = %s AND product_id = %s",
        (session_id, product_id)
    )

    if existing:
        execute_query("UPDATE social_cart_items SET quantity = quantity + %s WHERE id = %s",
                      (qty, existing['id']))
    else:
        execute_query(
            "INSERT INTO social_cart_items (session_id, product_id, added_by, quantity) VALUES (%s,%s,%s,%s)",
            (session_id, product_id, user_id, qty)
        )

    # Broadcast to all members in the room
    socketio.emit('cart_updated', {'message': f"{session['full_name']} added a product!"}, room=session_id)

    return redirect(url_for('social_cart_view', session_id=session_id))


@app.route('/social-cart/<session_id>/remove/<int:item_id>')
@login_required
def social_cart_remove(session_id, item_id):
    """Remove an item from the shared cart"""
    execute_query("DELETE FROM social_cart_items WHERE id = %s AND session_id = %s",
                  (item_id, session_id))
    socketio.emit('cart_updated', {'message': "An item was removed"}, room=session_id)
    return redirect(url_for('social_cart_view', session_id=session_id))


@app.route('/social-cart/<session_id>/checkout', methods=['POST'])
@login_required
def social_cart_checkout(session_id):
    """Checkout the shared cart (creator places the order)"""
    user_id = session['user_id']

    cart = fetch_one("SELECT * FROM social_carts WHERE session_id = %s", (session_id,))
    if not cart:
        flash("Cart not found.", "error")
        return redirect(url_for('home'))

    items = fetch_all("""
        SELECT sci.*, p.name, p.brand, p.category_id, p.price, p.discount_percent,
               (p.price * (100 - p.discount_percent) / 100) AS final_price
        FROM social_cart_items sci
        JOIN products p ON sci.product_id = p.product_id
        WHERE sci.session_id = %s
    """, (session_id,))

    if not items:
        flash("Cart is empty!", "error")
        return redirect(url_for('social_cart_view', session_id=session_id))

    # Calculate totals
    subtotal = sum(float(i['final_price']) * i['quantity'] for i in items)
    discount = cart['group_discount_percent']
    group_savings = (subtotal * discount) / 100
    total = subtotal - group_savings

    # Create order
    order_id = execute_query("""
        INSERT INTO orders (user_id, full_name, phone, address, total_amount,
                            payment_method, payment_status, order_status)
        VALUES (%s,%s,%s,%s,%s,'COD','pending','placed') RETURNING order_id
    """, (user_id, session['full_name'], 'N/A', 'Social Cart Order', total), return_id=True)

    if not order_id:
        flash("Order failed.", "error")
        return redirect(url_for('social_cart_view', session_id=session_id))

    # Create order items + passports
    for item in items:
        order_item_id = execute_query("""
            INSERT INTO order_items (order_id, product_id, quantity, price_at_purchase)
            VALUES (%s,%s,%s,%s) RETURNING order_item_id
        """, (order_id, item['product_id'], item['quantity'], item['final_price']), return_id=True)

        execute_query("UPDATE products SET stock_quantity = stock_quantity - %s WHERE product_id = %s",
                      (item['quantity'], item['product_id']))

        for _ in range(item['quantity']):
            generate_passport(order_item_id, item, user_id, item['category_id'])

    # Mark social cart as checked out
    execute_query("UPDATE social_carts SET status = 'checked_out' WHERE session_id = %s", (session_id,))

    # Notify all members
    socketio.emit('cart_checked_out', {'message': "Order placed by " + session['full_name'] + "!"}, room=session_id)

    flash(f"🎉 Group order placed! Total: ₹{total:.0f} (saved ₹{group_savings:.0f} with {discount}% group discount)", "success")
    return redirect(url_for('order_detail', order_id=order_id))


# ==================================================
#         🟢 SOCKET.IO EVENT HANDLERS
# ==================================================
@socketio.on('join_cart')
def handle_join_cart(data):
    """User joins a social cart room"""
    session_id = data.get('session_id')
    user_id = session.get('user_id')
    user_name = session.get('full_name', 'Anonymous')

    if session_id and user_id:
        join_room(session_id)
        emit('member_joined', {
            'user_name': user_name,
            'message': f"{user_name} joined the cart!"
        }, room=session_id)


@socketio.on('leave_cart')
def handle_leave_cart(data):
    """User leaves a social cart room"""
    session_id = data.get('session_id')
    user_name = session.get('full_name', 'Anonymous')

    if session_id:
        leave_room(session_id)
        emit('member_left', {
            'user_name': user_name,
            'message': f"{user_name} left the cart."
        }, room=session_id)


@socketio.on('chat_message')
def handle_chat_message(data):
    """Handle chat messages in the social cart"""
    session_id = data.get('session_id')
    message = data.get('message', '').strip()
    user_id = session.get('user_id')
    user_name = session.get('full_name', 'Anonymous')

    if session_id and message:
        # Save to database
        execute_query(
            "INSERT INTO social_cart_messages (session_id, user_id, message) VALUES (%s,%s,%s)",
            (session_id, user_id, message)
        )
        # Broadcast to all in room
        emit('new_message', {
            'user_name': user_name,
            'message': message,
            'timestamp': datetime.now().strftime('%H:%M')
        }, room=session_id)


@socketio.on('disconnect')
def handle_disconnect():
    """Clean up on disconnect"""
    pass
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)