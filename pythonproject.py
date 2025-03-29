from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import random
import time
from flask import Flask, request, render_template, redirect, url_for, session, flash
import threading
from datetime import datetime, timedelta
import os
from threading import Lock
import hashlib
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Generate a secure random secret key
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Excel files setup
USERS_FILE = 'users.xlsx'
APPOINTMENTS_FILE = 'appointments.xlsx'

# File locks to prevent concurrent access
users_file_lock = Lock()
appointments_file_lock = Lock()

# Security questions
SECURITY_QUESTIONS = [
    "What was your childhood nickname?",
    "What is your favorite book?",
    "What was the name of your first pet?"
]

# Available cities
CITIES = ['Chennai', 'Hyderabad', 'Kolkata', 'Mumbai', 'Delhi']

# Slot allotment data (date: [time slots])
SLOT_ALLOTMENT = {
    'Chennai': {
        '2025-04-01': ['10:00', '14:00', '16:00'],
        '2025-04-03': ['11:00', '15:00']
    },
    'Hyderabad': {
        '2025-04-02': ['09:00', '13:00'],
        '2025-04-04': ['10:30', '14:30']
    },
    'Kolkata': {},  # No slots available
    'Mumbai': {
        '2025-04-05': ['12:00', '15:00']
    },
    'Delhi': {
        '2025-04-06': ['09:30', '13:30'],
        '2025-04-07': ['11:00', '16:00']
    }
}

def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please log in first')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def auto_create_excel(file_path, columns, lock):
    """Automatically create or repair Excel file if it doesn't exist or is invalid"""
    with lock:
        # Check if file exists and is readable
        if os.path.exists(file_path):
            try:
                df = pd.read_excel(file_path, engine='openpyxl')
                # If file is empty or has wrong columns, recreate it
                if df.empty or set(df.columns) != set(columns):
                    print(f"{file_path} is empty or has incorrect columns. Recreating...")
                    df = pd.DataFrame(columns=columns)
                    df.to_excel(file_path, index=False, engine='openpyxl')
                    print(f"Recreated {file_path}")
                else:
                    print(f"{file_path} is valid and loaded")
                return df
            except Exception as e:
                print(f"Error reading {file_path}: {e}. Recreating file...")
        # If file doesn't exist or reading failed, create it
        df = pd.DataFrame(columns=columns)
        try:
            df.to_excel(file_path, index=False, engine='openpyxl')
            print(f"Created {file_path}")
        except Exception as e:
            print(f"Error creating {file_path}: {e}")
            raise
        return df

def read_excel_safely(file_path, lock):
    """Read Excel file with proper error handling"""
    with lock:
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
            print(f"Successfully read {file_path}")
            return df
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            raise

def write_excel_safely(df, file_path, lock):
    """Write to Excel file with proper error handling"""
    with lock:
        try:
            df.to_excel(file_path, index=False, engine='openpyxl')
            print(f"Successfully wrote to {file_path}")
        except Exception as e:
            print(f"Error writing to {file_path}: {e}")
            raise

# Initialize Excel files automatically at startup
try:
    auto_create_excel(USERS_FILE, 
                      ['username', 'password', 'security_q1', 'security_a1', 'security_q2', 'security_a2', 'security_q3', 'security_a3'], 
                      users_file_lock)
    auto_create_excel(APPOINTMENTS_FILE, 
                      ['username', 'customer_name', 'phone_number', 'city', 'date', 'time'], 
                      appointments_file_lock)
except Exception as e:
    print(f"Failed to initialize Excel files: {e}")
    exit(1)

def generate_captcha():
    """Generate a simple numeric captcha"""
    return str(random.randint(1000, 9999))

def generate_calendar_dates():
    """Generate dates for April 2025"""
    start_date = datetime(2025, 4, 1)
    dates = []
    for i in range(30):  # April has 30 days
        date = start_date + timedelta(days=i)
        dates.append(date.strftime('%Y-%m-%d'))
    return dates

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        captcha_input = request.form.get('captcha_input', '').strip()
        captcha_value = request.form.get('captcha_value', '').strip()
        security_answer = request.form.get('security_answer', '').strip().lower()
        security_index = session.pop('security_index', None)  # Get the stored index from session

        if not all([username, password, captcha_input, captcha_value, security_answer]):
            flash('All fields are required')
            return redirect(url_for('login'))

        if security_index is None:
            flash('Invalid session')
            return redirect(url_for('login'))

        if captcha_input != captcha_value:
            flash('Invalid captcha')
            return redirect(url_for('login'))

        try:
            df = read_excel_safely(USERS_FILE, users_file_lock)
        except Exception as e:
            flash(f"Error reading user data: {str(e)}")
            return redirect(url_for('login'))

        user_exists = ((df['username'] == username) & 
                       (df['password'] == hash_password(password))).any()
        
        if not user_exists:
            flash('Invalid username or password')
            return redirect(url_for('login'))

        user_data = df[df['username'] == username].iloc[0]
        correct_answer = user_data[f'security_a{security_index + 1}'].lower()
        
        if security_answer != correct_answer:
            flash('Incorrect security answer')
            return redirect(url_for('login'))
        
        session['logged_in'] = True
        session['username'] = username
        flash('Login successful!')
        return redirect(url_for('appointment'))
    
    # Generate new security index for this session
    security_index = random.randint(0, 2)
    session['security_index'] = security_index
    
    return render_template('login.html',
                          captcha=generate_captcha(),
                          security_question=SECURITY_QUESTIONS[security_index],
                          security_index=security_index)

@app.route('/register', methods=['GET'])
def register():
    return render_template('register.html', questions=SECURITY_QUESTIONS)

@app.route('/register', methods=['POST'])
def register_post():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    security_answers = [request.form.get(f'security_a{i+1}', '').strip().lower() for i in range(3)]

    if not all([username, password, confirm_password] + security_answers):
        flash('All fields are required')
        return redirect(url_for('register'))

    if password != confirm_password:
        flash('Passwords do not match')
        return redirect(url_for('register'))

    if len(password) < 8:
        flash('Password must be at least 8 characters long')
        return redirect(url_for('register'))

    try:
        df = read_excel_safely(USERS_FILE, users_file_lock)
    except Exception as e:
        flash(f"Error reading user data: {str(e)}")
        return redirect(url_for('register'))

    if username in df['username'].values:
        flash('Username already exists')
        return redirect(url_for('register'))

    new_user = pd.DataFrame({
        'username': [username],
        'password': [hash_password(password)],
        'security_q1': [SECURITY_QUESTIONS[0]],
        'security_a1': [security_answers[0]],
        'security_q2': [SECURITY_QUESTIONS[1]],
        'security_a2': [security_answers[1]],
        'security_q3': [SECURITY_QUESTIONS[2]],
        'security_a3': [security_answers[2]]
    })
    df = pd.concat([df, new_user], ignore_index=True)
    
    try:
        write_excel_safely(df, USERS_FILE, users_file_lock)
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    except Exception as e:
        flash(f"Error saving registration: {str(e)}")
        return redirect(url_for('register'))

@app.route('/appointment', methods=['GET', 'POST'])
@login_required
def appointment():
    username = session['username']
    calendar_dates = generate_calendar_dates()
    
    if request.method == 'POST':
        city = request.form.get('city', '').strip()
        selected_date = request.form.get('selected_date', '').strip()
        selected_time = request.form.get('selected_time', '').strip()
        customer_name = request.form.get('customer_name', '').strip()
        phone_number = request.form.get('phone_number', '').strip()
        
        if not all([city, customer_name, phone_number]):
            flash('Please fill in all required fields')
            return redirect(url_for('appointment'))

        if not phone_number.isdigit() or len(phone_number) != 10:
            flash('Please enter a valid 10-digit phone number')
            return redirect(url_for('appointment'))

        available_dates = list(SLOT_ALLOTMENT.get(city, {}).keys())
        available_times = SLOT_ALLOTMENT.get(city, {}).get(selected_date, []) if selected_date else []

        if selected_time:  # Final submission
            if not selected_date or selected_date not in available_dates or selected_time not in available_times:
                flash('Invalid slot selected')
                return render_template('appointment.html', 
                                     username=username, 
                                     cities=CITIES, 
                                     selected_city=city, 
                                     calendar_dates=calendar_dates,
                                     available_dates=available_dates,
                                     selected_date=selected_date,
                                     available_times=available_times)

            try:
                # Read existing appointments
                df_appointments = read_excel_safely(APPOINTMENTS_FILE, appointments_file_lock)
                
                # Check if user already has an appointment on this date
                if ((df_appointments['username'] == username) & 
                    (df_appointments['date'] == selected_date)).any():
                    flash('You already have an appointment on this date')
                    return render_template('appointment.html', 
                                         username=username, 
                                         cities=CITIES, 
                                         selected_city=city, 
                                         calendar_dates=calendar_dates,
                                         available_dates=available_dates,
                                         selected_date=selected_date,
                                         available_times=available_times)

                # Create new appointment entry
                new_appointment = pd.DataFrame({
                    'username': [username],
                    'customer_name': [customer_name],
                    'phone_number': [phone_number],
                    'city': [city],
                    'date': [selected_date],
                    'time': [selected_time]
                })

                # Append new appointment and save
                df_appointments = pd.concat([df_appointments, new_appointment], ignore_index=True)
                write_excel_safely(df_appointments, APPOINTMENTS_FILE, appointments_file_lock)
                
                flash('Appointment scheduled successfully!')
                return redirect(url_for('appointment'))
            except Exception as e:
                flash(f"Error saving appointment: {str(e)}")
                return render_template('appointment.html', 
                                     username=username, 
                                     cities=CITIES, 
                                     selected_city=city, 
                                     calendar_dates=calendar_dates,
                                     available_dates=available_dates,
                                     selected_date=selected_date,
                                     available_times=available_times)
        
        return render_template('appointment.html', 
                             username=username, 
                             cities=CITIES, 
                             selected_city=city, 
                             calendar_dates=calendar_dates,
                             available_dates=available_dates,
                             selected_date=selected_date,
                             available_times=available_times)
    
    return render_template('appointment.html', 
                         username=username, 
                         cities=CITIES, 
                         selected_city=None, 
                         calendar_dates=calendar_dates,
                         available_dates=[],
                         selected_date=None,
                         available_times=[])

def selenium_automation():
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    try:
        # Test registration
        driver.get('http://localhost:5000/register')
        time.sleep(2)
        
        driver.find_element(By.NAME, 'username').send_keys('newuser')
        driver.find_element(By.NAME, 'password').send_keys('newpass123')
        driver.find_element(By.NAME, 'confirm_password').send_keys('newpass123')
        driver.find_element(By.NAME, 'security_a1').send_keys('nick')
        driver.find_element(By.NAME, 'security_a2').send_keys('book')
        driver.find_element(By.NAME, 'security_a3').send_keys('pet')
        driver.find_element(By.TAG_NAME, 'button').click()
        
        time.sleep(2)
        
        # Test login
        driver.get('http://localhost:5000')
        time.sleep(2)
        
        driver.find_element(By.NAME, 'username').send_keys('newuser')
        driver.find_element(By.NAME, 'password').send_keys('newpass123')
        captcha_value = driver.find_element(By.NAME, 'captcha_value').get_attribute('value')
        driver.find_element(By.NAME, 'captcha_input').send_keys(captcha_value)
        security_question = driver.find_element(By.ID, 'security-question').text
        question_index = SECURITY_QUESTIONS.index(security_question)
        security_answers = ['nick', 'book', 'pet']
        driver.find_element(By.NAME, 'security_answer').send_keys(security_answers[question_index])
        driver.find_element(By.TAG_NAME, 'button').click()
        
        time.sleep(2)
        
        # Test appointment submission
        driver.find_element(By.NAME, 'city').send_keys('Chennai')  # Select city
        time.sleep(1)
        driver.find_element(By.XPATH, "//div[@data-date='2025-04-01']").click()  # Select date
        time.sleep(1)
        driver.find_element(By.XPATH, "//input[@value='10:00']").click()  # Select time slot
        driver.find_element(By.ID, 'submit-appointment').click()  # Submit
        
        time.sleep(2)
    except Exception as e:
        print(f"Selenium error: {e}")
    finally:
        driver.quit()

def run_flask():
    app.run(debug=True, use_reloader=False)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    time.sleep(2)
    selenium_automation()