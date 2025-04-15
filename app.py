from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import os


# Load environment variables from .env
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure app using environment variables
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

print("Database URL loaded:", os.getenv('DATABASE_URL'))

# Define Product model
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=True)

# Define Inventory model
class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_in_stock = db.Column(db.Integer, nullable=False, default=0)
    quantity_sold = db.Column(db.Integer, nullable=False, default=0)
    product = db.relationship('Product', backref=db.backref('inventory', lazy=True))

# Define Order model
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), nullable=False, default="pending")
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))

# Define User model for authentication (admin/seller)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # "admin" or "seller"

# Load user for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if current_user.role != 'admin':
        flash("Access denied. Only admins can register new sellers.", "danger")
        return redirect(url_for('login'))  # or some error page

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        if role != 'seller':  # We only allow sellers to be registered by the admin
            flash('Invalid role specified.', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        existing_user = User.query.filter_by(username=username).first()

        if existing_user:
            flash('Username already exists!', 'danger')
        else:
            new_user = User(username=username, password=hashed_password, role=role)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Seller {username} registered successfully!', 'success')
            return redirect(url_for('admin_dashboard'))

    return render_template('admin_dashboard.html')


# Route for user login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard') if user.role == 'admin' else url_for('seller_dashboard'))
        else:
            flash('Invalid login credentials', 'danger')
    return render_template('login.html')

# Route for user logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Route for the seller dashboard
@app.route('/seller')
@login_required
def seller_dashboard():
    if current_user.role != 'seller':
        return redirect(url_for('login'))
    products = Product.query.all()
    return render_template('seller_dashboard.html', products=products)

 #Route for the admin dashboard
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('login'))  # If the user isn't an admin, redirect to login

    # Fetch the products and orders
    products = Product.query.all()
    orders = Order.query.all()

    # Render the admin dashboard template
    return render_template('admin_dashboard.html', products=products, orders=orders)



# Route to place an order (seller updates inventory)
@app.route('/order/<int:product_id>', methods=['POST'])
@login_required
def place_order(product_id):
    if current_user.role != 'seller':
        return redirect(url_for('login'))
    
    quantity = int(request.form['quantity'])  # Quantity to order
    product = Product.query.get(product_id)
    inventory = Inventory.query.filter_by(product_id=product_id).first()

    if inventory.quantity_in_stock >= quantity:
        inventory.quantity_in_stock -= quantity
        inventory.quantity_sold += quantity
        db.session.commit()

        # Create an order record
        new_order = Order(product_id=product_id, quantity=quantity, status="completed")
        db.session.add(new_order)
        db.session.commit()

        flash(f"Order placed successfully for {product.name}!", 'success')
    else:
        flash('Not enough stock available', 'danger')

    return redirect(url_for('seller_dashboard'))


# Run the app
if __name__ == '__main__':
    app.run(debug=True)
