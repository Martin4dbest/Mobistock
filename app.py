from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import json


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



# Register the currency filter for formatting prices
@app.template_filter('currency')
def format_currency(value):
    return f"${value:,.2f}"


# Define Product model
class Product(db.Model):
    __tablename__ = 'product'
    __table_args__ = (
        db.UniqueConstraint('identification_number', 'location', name='uq_product_identification_per_location'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    identification_number = db.Column(db.String(100), nullable=False)
    in_stock = db.Column(db.Integer, nullable=False)
    selling_price = db.Column(db.Float, nullable=True)
    location = db.Column(db.String(100), nullable=False)

    # Relationships
    inventory_items = db.relationship('Inventory', backref='product', lazy=True)
    orders = db.relationship('Order', backref='product', lazy=True)


# Define Inventory model
class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_in_stock = db.Column(db.Integer, nullable=False, default=0)
    quantity_sold = db.Column(db.Integer, nullable=False, default=0)
    in_stock = db.Column(db.Integer, nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Relationships
    seller = db.relationship('User', backref='inventory_items')


# Define Order model
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    selling_price = db.Column(db.Float, nullable=True)
    amount = db.Column(db.Float, nullable=True)
    in_stock = db.Column(db.Integer, nullable=False)
    date_sold = db.Column(db.DateTime, nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # ✅ NEW RELATIONSHIP
    seller = db.relationship('User', backref='orders')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)



# Define User model for authentication (admin/seller)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # "admin" or "seller"
    location = db.Column(db.String(100), nullable=True)


class StockHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # who made the change
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    change_amount = db.Column(db.Integer)  # can be + or -
    reason = db.Column(db.String(255))  # optional note
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    admin = db.relationship('User', foreign_keys=[admin_id])
    seller = db.relationship('User', foreign_keys=[seller_id])
    product = db.relationship('Product')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    sender_id = db.Column(
        db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False
    )
    receiver_id = db.Column(
        db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False
    )
    
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id], passive_deletes=True)
    receiver = db.relationship('User', foreign_keys=[receiver_id], passive_deletes=True)





import pandas as pd
from io import BytesIO
from flask import send_file

from datetime import datetime, timedelta

@app.route('/admin/export-stock-history', methods=['GET', 'POST'])
def export_stock_history_excel():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return "Unauthorized", 403

    # Get filter values from request arguments or defaults
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    admin_id = request.args.get('admin_id', '')
    product_id = request.args.get('product_id', '')
    location = request.args.get('location', '')

    query = StockHistory.query

    # Apply filters
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        query = query.filter(StockHistory.created_at >= start_date)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        query = query.filter(StockHistory.created_at <= end_date)
    if admin_id:
        query = query.filter(StockHistory.admin_id == admin_id)
    if product_id:
        query = query.filter(StockHistory.product_id == product_id)
    if location:
        query = query.join(Product).filter(Product.location == location)

    # Explicitly load product and its location field
    stock_changes = query.join(Product).all()  # Ensures that the Product model is loaded

    if not stock_changes:
        return "No stock history records found to export.", 404

    # Prepare data for Excel export
    data = []
    for entry in stock_changes:
        location_name = ''
        if entry.product:  # Ensure the product is loaded
            location_name = getattr(entry.product, 'location', '')  # Get location from product
        data.append({
            'Date': entry.created_at.strftime('%Y-%m-%d %H:%M:%S') if entry.created_at else '',
            'Admin': getattr(entry.admin, 'username', entry.admin_id) if entry.admin else entry.admin_id,
            'Product': getattr(entry.product, 'name', entry.product_id) if entry.product else entry.product_id,
            'Seller': getattr(entry.seller, 'username', entry.seller_id) if entry.seller else entry.seller_id,
            'Change': entry.change_amount if entry.change_amount is not None else '',
            'Reason': entry.reason or '',
            'Location': location_name  # Ensure location is added
        })

    # Create Excel file
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Stock History')

    output.seek(0)
    return send_file(
        output,
        download_name='stock_history_filtered.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )





# Load user for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    #eturn User.query.get(int(user_id))
    return db.session.get(User, int(user_id))




@app.route('/')
def index():
    return render_template('index.html')

"""
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
# Function to fetch data from Google
"""

"""
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
"""


# The ID of your Google Sheet (loaded from .env)
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# Google Sheets API scope
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# Authenticate using the service account JSON from the environment
def authenticate_google_sheets():
    try:
        service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
        credentials = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=credentials)
        return service
    except Exception as e:
        print(f"❌ Error during Google Sheets authentication: {e}")
        return None




def get_google_sheet_data_by_location(sheet_name):
    service = authenticate_google_sheets()
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A2:D"
    ).execute()

    values = result.get('values', [])
    if not values:
        print(f"No data found in sheet {sheet_name}")
        return []

    sellers = User.query.filter(User.location.ilike(sheet_name), User.role == 'seller').all()
    if not sellers:
        print(f"No sellers found for location: {sheet_name}")
        return []

    formatted_data = []
    for row in values:
        name = row[0] if len(row) > 0 else ''
        identification_number = row[1] if len(row) > 1 else ''
        price = float(row[2]) if len(row) > 2 and row[2] else 0.0
        in_stock = 0
        if len(row) > 3:
            try:
                in_stock = int(row[3]) if row[3] not in [None, '', 'null', 'None'] else 0
            except ValueError:
                in_stock = 0

        formatted_data.append({
            'name': name,
            'identification_number': identification_number,
            'price': price,
            'in_stock': in_stock,
        })

    inventory_to_add = []

    for product_data in formatted_data:
        existing = Product.query.filter_by(
            identification_number=product_data['identification_number'],
            location=sheet_name
        ).first()

        if not existing:
            # Create new product if it doesn't exist
            product = Product(
                name=product_data['name'],
                identification_number=product_data['identification_number'],
                price=product_data['price'],
                selling_price=None,
                location=sheet_name,
                in_stock=product_data['in_stock']
            )
            db.session.add(product)
            db.session.commit()

            for seller in sellers:
                if seller.location == sheet_name:
                    inventory = Inventory(
                        product_id=product.id,
                        seller_id=seller.id,
                        quantity_in_stock=product_data['in_stock'],
                        in_stock=product_data['in_stock']
                    )
                    inventory_to_add.append(inventory)

        else:
            # When updating product, only increase stock if sheet stock is higher
            existing.name = product_data['name']
            existing.price = product_data['price']
            if product_data['in_stock'] > existing.in_stock:
                existing.in_stock += (product_data['in_stock'] - existing.in_stock)
            db.session.commit()

            for seller in sellers:
                if seller.location == sheet_name:
                    existing_inventory = Inventory.query.filter_by(
                        product_id=existing.id,
                        seller_id=seller.id
                    ).first()

                    if existing_inventory:
                        # Add stock from sheet if necessary, don't overwrite reduced stock
                        if product_data['in_stock'] > existing_inventory.quantity_in_stock:
                            difference = product_data['in_stock'] - existing_inventory.quantity_in_stock
                            existing_inventory.quantity_in_stock += difference
                            existing_inventory.in_stock += difference
                    else:
                        # Create new seller inventory
                        inventory = Inventory(
                            product_id=existing.id,
                            seller_id=seller.id,
                            quantity_in_stock=product_data['in_stock'],
                            in_stock=product_data['in_stock']
                        )
                        inventory_to_add.append(inventory)

    db.session.add_all(inventory_to_add)
    db.session.commit()

    print(f"✅ Imported and updated {len(formatted_data)} products for {sheet_name}")
    return formatted_data



@app.route('/import-products', methods=['POST'])
def import_all_products():
    # Get the location from the form, or default to "Accra" if not specified
    location = request.form.get('location', 'Accra')  # Default to 'Accra' if not provided

    try:
        # Get the sheet data for the given location
        sheet_data = get_google_sheet_data_by_location(location)
        
        if not sheet_data:
            flash(f"No data found for location {location}. Please check the sheet name.", "danger")
            return redirect(url_for('admin_dashboard'))

        # Process the sheet data and update the admin dashboard
        flash(f"Successfully imported products for {location}!", "success")

    except Exception as e:
        # Handle any unexpected errors
        flash(f"An error occurred while importing data: {str(e)}", "danger")

    return redirect(url_for('admin_dashboard'))



@app.route('/products/<location>')
def get_products_by_seller_location(location):
    seller = User.query.filter_by(location=location.lower(), role='seller').first()
    if not seller:
        return jsonify([])

    products = Product.query.filter_by(seller_id=seller.id).all()
    return jsonify([
        {
            "name": p.name,
            "price": p.price,
            "stock": p.in_stock,
            "id": p.identification_number
        } for p in products
    ])
@app.route('/admin/products')
def get_all_products_for_admin():
    # Optional: Add admin-only check here if you have authentication
    products = Product.query.all()
    
    return jsonify([
        {
            "name": p.name,
            "price": p.price,
            "stock": p.in_stock,
            "id": p.identification_number,
            "seller": p.seller.username if p.seller else "Unknown",
            "location": p.seller.location if p.seller else "Unknown"
        } for p in products
    ])



@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get(product_id)
    if product:
        try:
            # Delete all associated inventory
            inventories = Inventory.query.filter_by(product_id=product.id).all()
            for inv in inventories:
                db.session.delete(inv)

            # Delete all associated orders
            orders = Order.query.filter_by(product_id=product.id).all()
            for order in orders:
                db.session.delete(order)

            # Finally, delete the product
            db.session.delete(product)
            db.session.commit()

            flash('Product successfully deleted!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error deleting product: {str(e)}', 'danger')
    else:
        flash('Product not found!', 'danger')

    return redirect(url_for('admin_dashboard'))



@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('login'))

    # Handle import from Google Sheets
    if request.method == 'POST' and 'import_button' in request.form:
        location = request.form.get('location')

        if not location:
            flash("Please select a location before importing data.", "danger")
            return redirect(url_for('admin_dashboard'))

        try:
            sheet_data = get_google_sheet_data_by_location(location)
            if not sheet_data:
                flash(f"No data found for location {location}.", "danger")
                return redirect(url_for('admin_dashboard'))

            for row in sheet_data:
                name = row.get('name', '').strip()
                identification_number = row.get('identification_number', '').strip()
                price = float(row.get('price', 0.0))
                in_stock = row.get('in_stock', 0)

                if name and identification_number:
                    existing = Product.query.filter_by(identification_number=identification_number).first()
                    if not existing:
                        product = Product(
                            name=name,
                            identification_number=identification_number,
                            price=price,
                            selling_price=None,
                            location=location
                        )
                        db.session.add(product)
                        db.session.commit()

                        sellers = User.query.filter(User.location.ilike(location), User.role == 'seller').all()
                        for seller in sellers:
                            inventory = Inventory(
                                product_id=product.id,
                                seller_id=seller.id,
                                quantity_in_stock=10 if in_stock else 0
                            )
                            db.session.add(inventory)

            db.session.commit()
            flash(f"Successfully imported data for location {location}!", "success")

        except Exception as e:
            flash(f"An error occurred while importing data: {str(e)}", "danger")

    # Search logic
    search_query = request.args.get('search', '').strip()
    if search_query:
        products = Product.query.filter(Product.name.ilike(f"%{search_query}%")).all()
    else:
        products = Product.query.all()

    inventories = {inv.product_id: inv for inv in Inventory.query.all()}
    orders = Order.query.all()

    # Fetch all admins and the current logged-in admin name
    admins = User.query.filter_by(role='admin').all()
    admin_name = current_user.username  # Assuming the admin's name is stored in 'username'

    return render_template(
        'admin_dashboard.html',
        products=products,
        inventories=inventories,
        orders=orders,
        user_role='admin',
        search_query=search_query,
        admins=admins,
        admin_name=admin_name  # Pass admin's name to the template
    )


@app.route('/seller_dashboard', methods=['GET', 'POST'])
@login_required
def seller_dashboard():
    if current_user.role != 'seller':
        return redirect(url_for('login'))

    # Fetch only products matching seller's location
    products = Product.query.filter_by(location=current_user.location).all()

    # Fetch inventories only for current seller and relevant products
    inventory_records = Inventory.query.filter(
        Inventory.seller_id == current_user.id,
        Inventory.product_id.in_([p.id for p in products])
    ).all()
    inventories = {inv.product_id: inv for inv in inventory_records}

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

                # Update inventory for current seller
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





@app.route('/admin/change-password', methods=['GET', 'POST'])
def change_password():
    if request.method == 'POST':
        username = request.form['username']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        user = User.query.filter_by(username=username, role='admin').first()

        if not user:
            flash('Admin user not found.', 'danger')
        elif new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
        else:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password changed successfully. Please log in.', 'success')
            return redirect(url_for('login'))

    return render_template('change_password.html')




# Route for user logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/order/<int:product_id>', methods=['POST'])
@login_required
def place_order(product_id):
    if current_user.role != 'seller':
        return redirect(url_for('login'))

    quantity = int(request.form['quantity'])
    selling_price = float(request.form['selling_price'])

    # Fetch the product and inventory details
    product = Product.query.get(product_id)
    inventory = Inventory.query.filter_by(product_id=product_id, seller_id=current_user.id).first()

    if not product or not inventory:
        flash('Product or inventory not found.', 'danger')
        return redirect(url_for('seller_dashboard'))

    # Check if there is enough stock
    if inventory.quantity_in_stock >= quantity:
        # Deduct stock from the seller's inventory
        inventory.quantity_in_stock -= quantity
        inventory.quantity_sold += quantity
        db.session.commit()

        # Update global product stock
        product.in_stock -= quantity
        db.session.commit()

        total_amount = quantity * selling_price

        # Create the new order
        new_order = Order(
            product_id=product_id,
            quantity=quantity,
            status="completed",
            selling_price=selling_price,
            amount=total_amount
        )
        db.session.add(new_order)
        db.session.commit()

        # Update admin's inventory with reduced stock
        admin_inventory = Inventory.query.filter_by(product_id=product_id).all()
        for inventory in admin_inventory:
            inventory.in_stock = inventory.quantity_in_stock  # Reflect the reduced stock for admin
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
        'Accra', 'Kumasi', 'Tamale', 'Takoradi', 'Ashaiman', 'Koforidua', 'Cape Coast',
        'Sunyani', 'Wa', 'Berekum', 'Ho', 'Nkawkaw', 'Bolgatanga', 'Obuasi', 'Sekondi'
    ]

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        location = request.form['location'] if 'location' in request.form else None

        # Ensure the location is a valid city (sheet name) from the list of cities
        if location not in ghana_cities:
            flash('Invalid location specified. Please select a valid city.', 'danger')
            return redirect(url_for('register'))

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
            flash(f'{username} registered successfully as {role} in {location}!', 'success')
            return redirect(url_for('admin_dashboard'))

    return render_template('register.html', ghana_cities=ghana_cities)


@app.route('/send-order', methods=['POST'])
def send_order():
    data = request.get_json()

    product_id = data.get('product_id')
    quantity = data.get('quantity')
    selling_price = data.get('selling_price')
    amount = data.get('amount')
    date_sold = data.get('date_sold')
    seller_id = data.get('seller_id')

    # Validate required fields
    if not all([product_id, quantity, selling_price, amount, date_sold, seller_id]):
        return jsonify({'success': False, 'error': 'All fields including seller_id are required'}), 400

    try:
        # Convert data types
        quantity = int(quantity)
        selling_price = float(selling_price)
        amount = float(amount)
        date_sold_dt = datetime.strptime(date_sold, '%Y-%m-%dT%H:%M:%S.%fZ')

        # Get product
        product = Product.query.get(product_id)
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404

        # Check stock availability
        if product.in_stock < quantity:
            return jsonify({'success': False, 'error': 'Not enough stock available'}), 400

        # Update stock
        product.in_stock -= quantity
        db.session.commit()

        # Create order
        order = Order(
            product_id=product_id,
            quantity=quantity,
            selling_price=selling_price,
            amount=amount,
            date_sold=date_sold_dt,
            in_stock=product.in_stock,
            #seller_id=seller_id
            seller_id=current_user.id
        )
        db.session.add(order)
        db.session.commit()

        return jsonify({'success': True, 'remaining_stock': product.in_stock}), 200

    except Exception as e:
        db.session.rollback()
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

    # First, delete any inventory records tied to this user (seller)
    Inventory.query.filter_by(seller_id=user.id).delete()

    # Then, delete the user
    db.session.delete(user)
    db.session.commit()

    flash(f"User {user.username} has been deleted.", "success")
    return redirect(url_for('view_users'))



from collections import defaultdict
@app.route('/admin/orders')
def view_orders():
    selected_location = request.args.get('location')
    if not selected_location:
        return redirect(url_for('select_order_location'))

    orders = (
        Order.query
        .join(Product, Product.id == Order.product_id)
        .filter(Product.location == selected_location)
        .all()
    )

    # Prepare sales_data for chart
    sales_data = []
    seller_performance = defaultdict(int)
    product_sales = defaultdict(int)  # To calculate total sales for each product

    for order in orders:
        sales_data.append({
            "product": order.product.name,
            "quantity": order.quantity,
            "date": order.created_at.strftime("%Y-%m-%d") if order.created_at else None
        })

        # Sum total quantity or amount sold per seller (using seller relationship)
        seller_name = order.seller.username if hasattr(order, 'seller') and order.seller else "Unknown Seller"
        seller_id = order.seller.id if hasattr(order, 'seller') and order.seller else "Unknown Seller ID"
        seller_performance[seller_id] = seller_performance.get(seller_id, 0) + order.quantity

        # Sum total sales for each product (for the top 5 products calculation)
        product_sales[order.product.name] += order.quantity

    # Find the best seller (from seller_id)
    if seller_performance:
        best_seller_id = max(seller_performance.items(), key=lambda x: x[1])[0]
        best_seller_name = User.query.get(best_seller_id).username  # Fetching seller name using seller_id
        best_seller_sales = seller_performance[best_seller_id]
    else:
        best_seller_name = "N/A"
        best_seller_sales = 0

    # Calculate top 5 products based on sales quantity
    top_5_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]

    return render_template(
        'admin_orders.html',
        orders=orders,
        selected_location=selected_location,
        sales_data=sales_data,
        seller_performance=dict(seller_performance),
        best_seller_name=best_seller_name,
        best_seller_sales=best_seller_sales,
        top_5_products=top_5_products  # Pass the top 5 products here
    )



@app.route('/admin/select_order_location', methods=['GET', 'POST'])
def select_order_location():
    # Static list of cities in Ghana
    ghana_cities = [
        'Accra', 'Kumasi', 'Tamale', 'Sekondi', 'Takoradi', 'Cape Coast', 
        'Sunyani', 'Bolgatanga', 'Wa', 'Ho', 'Berekum', 'Nsawam', 'New Edubiase',
        'Akim Oda', 'Landslide', 'Asamankese', 'Mampong', 'Sefwi Wiawso'
    ]
    
    locations = ghana_cities

    if request.method == 'POST':
        # Get the selected location from the form
        selected_location = request.form.get('location')
        # Redirect to the orders page with the selected location as a query parameter
        return redirect(url_for('view_orders', location=selected_location))

    # Render the location selection page with the list of locations
    return render_template('select_order_location.html', locations=locations)



@app.route('/delete-sales-by-location', methods=['POST'])
def delete_sales_by_location():
    location = request.form.get('location')

    if not location:
        flash("Location is required to delete sales records.", "danger")
        return redirect(url_for('view_orders'))

    try:
        # Fetch all orders linked to products at that location
        orders_to_delete = Order.query.join(Product).filter(Product.location == location).all()

        for order in orders_to_delete:
            db.session.delete(order)

        db.session.commit()
        flash(f"All sales records for {location} have been deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error deleting sales records: " + str(e), "danger")

    return redirect(url_for('view_orders'))



@app.route('/delete-all-products', methods=['POST'])
@login_required
def delete_all_products():
    if current_user.role != 'admin':
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('login'))

    try:
        Inventory.query.delete()  
        Product.query.delete()
        db.session.commit()
        flash("All products have been deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting products: {str(e)}", "danger")

    return redirect(url_for('admin_dashboard'))


from flask import send_file
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta

@app.route('/export_sales_data', methods=['GET'])
def export_sales_data():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return "Unauthorized", 403

    # Fetch optional filters
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    location = request.args.get('location', '')

    query = Order.query

    # Apply filters
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        query = query.filter(Order.created_at >= start_date)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        query = query.filter(Order.created_at <= end_date)
    if location:
        query = query.join(Product).filter(Product.location == location)

    orders = query.order_by(Order.created_at.desc()).all()

    # Prepare data
    data = []
    for order in orders:
        # Get the location from the related Product model
        product_location = order.product.location if order.product else 'Unknown Location'

        data.append({
            'Date Sold': order.date_sold.strftime('%Y-%m-%d %H:%M:%S') if order.date_sold else '',
            'Product Name': order.product.name if order.product else 'Unknown Product',
            'Quantity': order.quantity,
            'Amount': order.amount,
            'Seller': order.seller.username if order.seller else 'Unknown Seller',
            'Location': product_location,  # Use location here
            'Created At': order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else ''
        })

    if not data:
        data.append({
            'Date Sold': '',
            'Product Name': '',
            'Quantity': '',
            'Amount': '',
            'Seller': '',
            'Location': '',  
            'Created At': ''
        })

    # Create an Excel file
    df = pd.DataFrame(data)

    # Create an Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sales Data')

    output.seek(0)

    return send_file(
        output,
        download_name='sales_data.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )





@app.route('/chat')
@login_required
def chat():
    # For Sellers: Display a list of Admins
    if current_user.role == 'seller':
        target_users = User.query.filter_by(role='admin').all()
    # For Admins: Display a list of Sellers
    elif current_user.role == 'admin':
        target_users = User.query.filter_by(role='seller').all()

    if not target_users:
        flash("No users available to chat with.", "warning")
        return redirect(url_for('admin_dashboard') if current_user.role == 'admin' else 'seller_dashboard')

    return render_template('chat_list.html', target_users=target_users)


@app.route('/chat/<int:user_id>')
@login_required
def chat_with_user(user_id):
    # Ensure the target user exists
    target_user = User.query.get_or_404(user_id)

    # Prevent chatting with themselves
    if target_user.id == current_user.id:
        flash("You cannot chat with yourself.", "warning")
        return redirect(url_for('chat'))

    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == target_user.id)) |
        ((Message.sender_id == target_user.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()

    return render_template('chat.html', messages=messages, target_user=target_user)


@app.route('/send_message/<int:user_id>', methods=['POST'])
@login_required
def send_message(user_id):
    content = request.form['content'].strip()
    if not content:
        return redirect(url_for('chat_with_user', user_id=user_id))

    target_user = User.query.get_or_404(user_id)

    message = Message(
        sender_id=current_user.id,
        receiver_id=target_user.id,
        content=content
    )
    db.session.add(message)
    db.session.commit()

    # 🚫 No Socket.IO emit, standard form submission flow
    return redirect(url_for('chat_with_user', user_id=user_id))



"""
@app.route('/send_message/<int:user_id>', methods=['POST'])
@login_required
def send_message(user_id):
    content = request.form['content'].strip()
    if not content:
        return redirect(url_for('chat_with_user', user_id=user_id))

    target_user = User.query.get_or_404(user_id)

    message = Message(
        sender_id=current_user.id,
        receiver_id=target_user.id,
        content=content
    )
    db.session.add(message)
    db.session.commit()

    # ✅ Emit the message via Socket.IO to the shared room
    room = f"{min(current_user.id, target_user.id)}_{max(current_user.id, target_user.id)}"
    socketio.emit('new_message', {
        'message_id': message.id,
        'sender_id': current_user.id,
        'sender_username': current_user.username,
        'receiver_id': target_user.id,
        'content': content,
    }, room=room)

    return redirect(url_for('chat_with_user', user_id=user_id))

"""


"""
@socketio.on('join')
def handle_join(room):
    join_room(room)
"""


@app.route('/edit_message/<int:message_id>', methods=['POST'])
def edit_message(message_id):
    message = Message.query.get_or_404(message_id)

    if message.sender_id != current_user.id:
        return {'error': 'Unauthorized'}, 403

    data = request.get_json()  # ✅ Parse JSON body
    message.content = data.get('content')
    db.session.commit()
    return {'success': True}



@app.route('/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):
    message = Message.query.get_or_404(message_id)

    # Ensure the current user is the sender of the message
    if message.sender_id != current_user.id:
        flash("You can only delete your own messages.", 'danger')
        return redirect(url_for('chat_with_user', user_id=message.receiver_id))

    # Delete the message
    db.session.delete(message)
    db.session.commit()
    flash('Message deleted successfully!', 'success')
    return redirect(url_for('chat_with_user', user_id=message.receiver_id))



def get_chat_messages(user_id_1, user_id_2):
    return Message.query.filter(
        ((Message.sender_id == user_id_1) & (Message.receiver_id == user_id_2)) |
        ((Message.sender_id == user_id_2) & (Message.receiver_id == user_id_1))
    ).order_by(Message.timestamp.asc()).all()



@app.route('/get_messages/<int:user_id>')
@login_required
def get_messages(user_id):
    messages = get_chat_messages(current_user.id, user_id)
    return render_template('partials/message_list.html', messages=messages, current_user=current_user)



"""
# Run the app
if __name__ == '__main__':
    app.run(debug=True)

    

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)

"""
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
