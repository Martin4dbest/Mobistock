from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv  # Import the dotenv library
import os

from flask import request, jsonify
from datetime import datetime


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



print(app.config['SQLALCHEMY_DATABASE_URI'])



# Register the currency filter for formatting prices
@app.template_filter('currency')
def format_currency(value):
    return f"${value:,.2f}"

# Define Product model

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)  # Could be used for display or reference
    identification_number = db.Column(db.String(100), unique=True, nullable=False)
    in_stock = db.Column(db.Integer, nullable=False)


    selling_price = db.Column(db.Float, nullable=True)

# Define Inventory model
class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_in_stock = db.Column(db.Integer, nullable=False, default=0)
    quantity_sold = db.Column(db.Integer, nullable=False, default=0)
    product = db.relationship('Product', backref=db.backref('inventory', lazy=True))
    in_stock = db.Column(db.Integer, nullable=False)

# Define Order model


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='pending')
    selling_price = db.Column(db.Float, nullable=True)  # New field
    amount = db.Column(db.Float, nullable=True)         # New field (qty * selling_price)
    in_stock = db.Column(db.Integer, nullable=False)
    date_sold = db.Column(db.DateTime, nullable=False)

    product = db.relationship('Product', backref=db.backref('orders', lazy=True))


# Define User model for authentication (admin/seller)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # "admin" or "seller"
    location = db.Column(db.String(100), nullable=True)  # Seller's location (optional)


# Load user for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))



@app.route('/')
def index():
    return render_template('index.html')

# Path to your service account JSON file (loaded from .env)
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE_PATH')

# The ID of your Google Sheet (loaded from .env)
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# Google Sheets API scope
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# Authenticate using the service account
def authenticate_google_sheets():
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=credentials)
    return service
# Function to fetch data from Googl

def get_google_sheet_data():
    service = authenticate_google_sheets()
    sheet = service.spreadsheets()

    # Define the range of the Google Sheet (e.g., columns A to D, starting from row 2)
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A2:D"  # Ensure that the 'in_stock' column is in column D
    ).execute()

    # Extract values and handle empty data
    values = result.get('values', [])
    if not values:
        return []  # No data found

    # Debugging: log the raw values from the sheet
    print(f"Raw Google Sheet Data: {values}")

    # Convert rows into structured dictionaries
    formatted_data = []
    for row in values:
        price = float(row[2]) if len(row) > 2 and row[2] else 0.0

        # Improved handling for 'in_stock' with additional logging
        in_stock = 0  # Default to 0 if the value is invalid or missing
        if len(row) > 3 and row[3]:
            try:
                # Attempt to parse 'in_stock' as an integer
                in_stock = int(row[3])
            except ValueError:
                in_stock = 0  # Default to 0 if invalid
        else:
            print(f"Warning: Missing 'in_stock' value in row: {row}")

        # Log what's being parsed
        print(f"Row: {row}, Parsed In Stock: {in_stock}")

        formatted_data.append({
            'name': row[0] if len(row) > 0 else '',
            'identification_number': row[1] if len(row) > 1 else '',
            'price': price,
            'in_stock': in_stock
        })

    # Now we update or insert into the database
    for product_data in formatted_data:
        selling_price = product_data['price']
        identification_number = product_data['identification_number']
        in_stock = product_data['in_stock']

        # Check if the product exists in the database using identification_number
        existing_product = Product.query.filter_by(identification_number=identification_number).first()

        if existing_product:
            # If product exists, update only the changed fields
            if existing_product.name != product_data['name']:
                existing_product.name = product_data['name']
            if existing_product.price != product_data['price']:
                existing_product.price = product_data['price']

            # Update 'in_stock' only if the new value is different and represents a restock or new product
            if existing_product.in_stock != in_stock:
                # Only update if in_stock value from the sheet is greater than current stock
                if in_stock > existing_product.in_stock:
                    print(f"Restocking {existing_product.name} from {existing_product.in_stock} to {in_stock}")
                    existing_product.in_stock = in_stock  # Update only if new stock is greater
                else:
                    print(f"Skipping update for {existing_product.name} as the sheet has lower stock than current.")
            
            db.session.commit()
        else:
            # If product doesn't exist, create a new product
            new_product = Product(
                name=product_data['name'],
                identification_number=identification_number,
                price=product_data['price'],
                in_stock=in_stock  # Use the correctly parsed in_stock value
            )
            db.session.add(new_product)
            db.session.commit()

    return formatted_data



@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('login'))

    # Handle import from Google Sheets
    if request.method == 'POST' and 'import_button' in request.form:
        sheet_data = get_google_sheet_data()  # Ensure this returns a list of dicts

        for row in sheet_data:
            name = row.get('name', '').strip()
            identification_number = row.get('identification_number', '').strip()
            price = float(row.get('price', 0.0))  # Base price only
            in_stock = row.get('in_stock', 0)

            if name and identification_number:
                existing = Product.query.filter_by(identification_number=identification_number).first()
                if not existing:
                    product = Product(
                        name=name,
                        identification_number=identification_number,
                        price=price,
                        selling_price=None  # Initially not set
                    )
                    db.session.add(product)
                    db.session.commit()  # Commit to get product.id

                    inventory = Inventory(
                        product_id=product.id,
                        quantity_in_stock=10 if in_stock else 0  
                    )
                    db.session.add(inventory)

        db.session.commit()

    # Search logic
    search_query = request.args.get('search', '').strip()
    if search_query:
        products = Product.query.filter(Product.name.ilike(f"%{search_query}%")).all()
    else:
        products = Product.query.all()

    inventories = {inv.product_id: inv for inv in Inventory.query.all()}
    orders = Order.query.all()

    return render_template(
        'admin_dashboard.html',
        products=products,
        inventories=inventories,
        orders=orders,
        user_role='admin',
        search_query=search_query,
    )



@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get(product_id)
    if product:
        # Delete associated inventory
        inventory = Inventory.query.filter_by(product_id=product.id).first()
        if inventory:
            db.session.delete(inventory)

        # Delete associated orders
        orders = Order.query.filter_by(product_id=product.id).all()
        for order in orders:
            db.session.delete(order)

        # Finally, delete the product
        db.session.delete(product)
        db.session.commit()

        flash('Product successfully deleted!', 'success')
    else:
        flash('Product not found!', 'danger')

    return redirect(url_for('admin_dashboard'))  # Redirect to the correct dashboard after deletion


@app.route('/seller_dashboard', methods=['GET', 'POST'])
@login_required
def seller_dashboard():
    if current_user.role != 'seller':
        return redirect(url_for('login'))

    # Fetch all products and inventories
    products = Product.query.all()
    inventories = {inv.product_id: inv for inv in Inventory.query.all()}

    # Seller details
    seller_details = {
        "name": current_user.username,
        "location": current_user.location,
        "role": current_user.role
    }

    if request.method == 'POST':
        for product in products:
            selling_price = request.form.get(f'selling_price_{product.id}')
            quantity = request.form.get(f'quantity_{product.id}', 0)

            if selling_price and quantity:
                selling_price = float(selling_price)
                quantity = int(quantity)

                # Update product's selling price if not already set
                product.selling_price = selling_price
                db.session.add(product)

                # Create new order
                order = Order(
                    product_id=product.id,
                    quantity=quantity,
                    selling_price=selling_price,
                    amount=selling_price * quantity
                )
                db.session.add(order)

                # Update inventory
                inventory = inventories.get(product.id)
                if inventory:
                    inventory.quantity_in_stock = max(0, inventory.quantity_in_stock - quantity)
                    db.session.add(inventory)

        db.session.commit()
        flash('Selling Prices, Quantities, and Orders Updated!', 'success')

    return render_template(
        'seller_dashboard.html',
        products=products,
        inventories=inventories,
        seller_details=seller_details,
        user_role='seller'
    )


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



# Route to place/update an order (for seller)

@app.route('/order/<int:product_id>', methods=['POST'])
@login_required
def place_order(product_id):
    if current_user.role != 'seller':
        return redirect(url_for('login'))

    quantity = int(request.form['quantity'])
    selling_price = float(request.form['selling_price'])

    product = Product.query.get(product_id)
    inventory = Inventory.query.filter_by(product_id=product_id).first()

    if not product or not inventory:
        flash('Product or inventory not found.', 'danger')
        return redirect(url_for('seller_dashboard'))

    if inventory.quantity_in_stock >= quantity:
        inventory.quantity_in_stock -= quantity
        inventory.quantity_sold += quantity
        db.session.commit()

        total_amount = quantity * selling_price

        new_order = Order(
            product_id=product_id,
            quantity=quantity,
            status="completed",
            selling_price=selling_price,
            amount=total_amount
        )
        db.session.add(new_order)
        db.session.commit()

        flash(f"Order placed successfully for {product.name}!", 'success')
    else:
        flash('Not enough stock available.', 'danger')

    return redirect(url_for('seller_dashboard'))


@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if current_user.role != 'admin':
        flash("Access denied. Only admins can register new users.", "danger")
        return redirect(url_for('login'))

    # List of cities in Ghana (for demonstration; can be updated or fetched dynamically)
    ghana_cities = [
        'Accra', 'Kumasi', 'Takoradi', 'Tamale', 'Ashaiman', 'Koforidua', 'Cape Coast',
        'Sunyani', 'Wa', 'Berekum', 'Ho', 'Nkawkaw', 'Bolgatanga', 'Obuasi', 'Sekondi'
    ]

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        location = request.form['location'] if 'location' in request.form else None

        if role not in ['seller', 'admin']:  # Allow both 'seller' and 'admin' roles
            flash('Invalid role specified.', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        existing_user = User.query.filter_by(username=username).first()

        if existing_user:
            flash('Username already exists!', 'danger')
        else:
            new_user = User(username=username, password=hashed_password, role=role, location=location)
            db.session.add(new_user)
            db.session.commit()
            flash(f'{username} registered successfully as {role}!', 'success')
            return redirect(url_for('admin_dashboard'))

    return render_template('register.html', ghana_cities=ghana_cities)


@app.route('/send-order', methods=['POST'])
def send_order():
    data = request.get_json()
    product_id = data.get('product_id')
    quantity = int(data.get('quantity', 0))
    selling_price = float(data.get('selling_price', 0))
    amount = float(data.get('amount', 0))
    date_sold = data.get('date_sold')
    in_stock = int(data.get('in_stock', 0))  # The initial in_stock from frontend input

    try:
        # Retrieve the product from the database
        product = Product.query.get(product_id)

        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404

        # Calculate the new remaining stock
        new_in_stock = product.in_stock - quantity

        # Ensure the stock doesn't go below zero
        if new_in_stock < 0:
            return jsonify({'success': False, 'error': 'Not enough stock available'}), 400

        # Update the product's stock in the database
        product.in_stock = new_in_stock
        db.session.commit()  # Commit the stock update

        # Create a new order
        order = Order(
            product_id=product_id,
            quantity=quantity,
            selling_price=selling_price,
            amount=amount,
            date_sold=datetime.strptime(date_sold, '%Y-%m-%dT%H:%M:%S.%fZ'),
            in_stock=new_in_stock  # Include the updated stock in the order (optional)
        )

        # Add the order to the session and commit
        db.session.add(order)
        db.session.commit()

        return jsonify({'success': True, 'remaining_stock': new_in_stock}), 200  # Include remaining stock in response

    except Exception as e:
        print("Error saving order:", e)
        return jsonify({'success': False, 'error': str(e)}), 500



 
@app.route('/view_users')
@login_required
def view_users():
    if current_user.role != 'admin':
        flash("Access denied. Only admins can view the users list.", "danger")
        return redirect(url_for('index'))

    # Fetch all users with role 'seller' or 'admin', including their usernames
    users = User.query.filter(User.role.in_(['seller', 'admin'])).all()

    # Pass users to the template
    return render_template('view_users.html', users=users)


@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash("Access denied. Only admins can delete users.", "danger")
        return redirect(url_for('index'))

    # Find the user by ID
    user = User.query.get_or_404(user_id)

    # Delete the user
    db.session.delete(user)
    db.session.commit()

    flash(f"User {user.username} has been deleted.", "success")
    return redirect(url_for('view_users'))


@app.route('/admin/orders')
def view_orders():
    orders = Order.query.all()
    return render_template('admin_orders.html', orders=orders)

@app.route('/delete-all-sales', methods=['POST'])
def delete_all_sales():
    try:
        Order.query.delete()
        db.session.commit()
        flash("All sales records have been deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error deleting sales records: " + str(e), "danger")
    return redirect(url_for('view_orders'))  # ✅ Use your actual route name





# Run the app
if __name__ == '__main__':
    app.run(debug=True)