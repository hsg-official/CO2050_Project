import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid # Used to generate unique random names for files

app = Flask(__name__)
app.secret_key = 'forensic_system_secret' # Required for session management

# Configure File Uploads
UPLOAD_FOLDER = 'static/uploads/evidence'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists when the app starts
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Database connection configuration
# --- SUPABASE CONNECTION SETUP ---
DB_HOST = "aws-1-ap-southeast-2.pooler.supabase.com" # Replace with your Supabase Host
DB_NAME = "postgres"
DB_USER = "postgres.wutuohcipwrsxyjgbaxd" # Replace with your Supabase User
DB_PASSWORD = "H$g2OO41113" # Use the password you created for Supabase, NOT your old local password
DB_PORT = "5432" # Or 5432 depending on your string

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT
    )

def log_action(user_id, action_description):
    """Utility function to easily record system events."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO AuditLog (UserID, Action) VALUES (%s, %s)", 
        (user_id, action_description)
    )
    conn.commit()
    cursor.close()
    conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Checking credentials against the database 
        cursor.execute('SELECT * FROM Users WHERE Username = %s AND PasswordHash = %s', (username, password))
        account = cursor.fetchone()
        
        cursor.close()
        conn.close()

        if account:
            # Create session data [cite: 60, 61]
            session['loggedin'] = True
            session['id'] = account['userid']
            session['username'] = account['username']
            session['role'] = account['userrole']
            session['staff_id'] = account['staffid']

            log_action(account['userid'], "User logged into the system.")
            return redirect(url_for('dashboard'))
        else:
            flash('Incorrect username or password!')

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'loggedin' in session:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Fetch a quick statistic for the dashboard (e.g., Total Open Cases)
        cursor.execute("SELECT COUNT(*) as open_cases FROM MedicoLegalCase WHERE CaseStatus = 'Open'")
        result = cursor.fetchone()
        open_cases = result['open_cases'] if result else 0
        
        cursor.close()
        conn.close()

        log_action(session['id'], "Viewed the dashboard.")

        # Render the HTML template and pass the data to it
        return render_template('dashboard.html', 
                               username=session['username'], 
                               role=session['role'], 
                               open_cases=open_cases)
    
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    if session.get('loggedin') and session.get('id'):
        log_action(session['id'], "User logged out of the system.")
    session.clear()
    return redirect(url_for('login'))

@app.route('/register_patient', methods=['GET', 'POST'])
def register_patient():
    # Ensure the user is logged in
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    # Optional Security: Restrict this page to Admin and Clerical staff
    if session['role'] not in ['Admin', 'Clerical']:
        flash("You do not have permission to register patients.")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        full_name = request.form['full_name']
        age = request.form['age']
        gender = request.form['gender']
        address = request.form['address']
        contact_info = request.form['contact_info']

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Insert the new patient into the database
        cursor.execute(
            'INSERT INTO Patient (FullName, Age, Gender, Address, ContactInfo) VALUES (%s, %s, %s, %s, %s)',
            (full_name, age, gender, address, contact_info)
        )
        conn.commit()
        log_action(session['id'], "Registered a new patient.")
        
        cursor.close()
        conn.close()

        flash('Patient registered successfully!')
        return redirect(url_for('register_patient'))

    return render_template('register_patient.html', role=session['role'])

@app.route('/create_case', methods=['GET', 'POST'])
def create_case():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    # Restrict to authorized roles
    if session['role'] not in ['Admin', 'Doctor', 'JMO']:
        flash("You do not have permission to manage cases.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        case_id = request.form['case_id']
        patient_id = request.form['patient_id']
        assigned_jmo = request.form['assigned_jmo']
        case_type = request.form['case_type']
        incident_date = request.form['incident_date']
        case_status = request.form['case_status']

        try:
            cursor.execute(
                '''INSERT INTO MedicoLegalCase 
                   (CaseID, PatientID, AssignedJMO, CaseType, IncidentDate, CaseStatus) 
                   VALUES (%s, %s, %s, %s, %s, %s)''',
                (case_id, patient_id, assigned_jmo, case_type, incident_date, case_status)
            )
            conn.commit()
            log_action(session['id'], "Created a new medico-legal case.")
            flash('Medico-Legal Case created successfully!')
        except mysql.connector.Error as err:
            # This catches errors like trying to use a CaseID that already exists
            flash(f'Database Error: {err}')
        
        return redirect(url_for('create_case'))

    # For GET requests: Fetch data for the dropdown menus
    cursor.execute("SELECT PatientID, FullName FROM Patient")
    patients = cursor.fetchall()

    cursor.execute("SELECT StaffID, FullName, Role FROM Staff WHERE Role IN ('Doctor', 'JMO', 'Admin')")
    doctors = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('create_case.html', patients=patients, doctors=doctors, role=session['role'])

@app.route('/view_cases', methods=['GET'])
def view_cases():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    search_query = request.args.get('search', '')
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # We use WHERE 1=1 so we can easily append AND conditions dynamically
    query = """
        SELECT c.CaseID, p.FullName AS PatientName, s.FullName AS JMOName, 
               c.CaseType, c.IncidentDate, c.CaseStatus, c.AssignedJMO
        FROM MedicoLegalCase c
        LEFT JOIN Patient p ON c.PatientID = p.PatientID
        LEFT JOIN Staff s ON c.AssignedJMO = s.StaffID
        WHERE 1=1
    """
    params = []
    
    # 🚨 Data-Level Security: If the user is a Doctor, ONLY show their assigned cases
    if session['role'] in ['Doctor', 'JMO']:
        query += " AND c.AssignedJMO = %s"
        params.append(session['staff_id'])
        
    # Apply search filter if one exists
    if search_query:
        query += " AND (c.CaseID LIKE %s OR p.FullName LIKE %s OR c.CaseStatus LIKE %s)"
        like_pattern = f"%{search_query}%"
        params.extend([like_pattern, like_pattern, like_pattern])
        
    cursor.execute(query, tuple(params))
    cases = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('view_cases.html', cases=cases, search_query=search_query, current_user_id=session.get('staff_id'), role=session['role'])

@app.route('/update_case_status', methods=['POST'])
def update_case_status():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
        
    case_id = request.form['case_id']
    new_status = request.form['case_status']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE MedicoLegalCase SET CaseStatus = %s WHERE CaseID = %s", (new_status, case_id))
    conn.commit()
    
    # Optional: Log this action using our helper function!
    log_action(session['id'], f"Updated case status for {case_id} to {new_status}")
    
    cursor.close()
    conn.close()
    
    flash(f"Case {case_id} status updated to {new_status}!")
    return redirect(url_for('view_cases'))

@app.route('/postmortem', methods=['GET', 'POST'])
def postmortem():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    # Restrict access to medical personnel
    if session['role'] not in ['Admin', 'Doctor', 'JMO']:
        flash("You do not have permission to enter postmortem findings.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        case_id = request.form['case_id']
        doctor_id = request.form['doctor_id']
        exam_date = request.form['examination_date']
        findings = request.form['findings']
        cause_of_death = request.form['cause_of_death']

        cursor.execute(
            '''INSERT INTO Postmortem (CaseID, DoctorID, ExaminationDate, Findings, CauseOfDeath) 
               VALUES (%s, %s, %s, %s, %s)''',
            (case_id, doctor_id, exam_date, findings, cause_of_death)
        )
        conn.commit()
        log_action(session['id'], "Recorded a postmortem report.")
        flash('Postmortem report saved securely!')
        return redirect(url_for('postmortem'))

    # GET requests: Fetch dropdown data
    cursor.execute("SELECT CaseID FROM MedicoLegalCase WHERE CaseStatus != 'Closed'")
    cases = cursor.fetchall()

    cursor.execute("SELECT StaffID, FullName FROM Staff WHERE Role IN ('Doctor', 'JMO')")
    doctors = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('postmortem.html', cases=cases, doctors=doctors)

@app.route('/manage_evidence', methods=['GET', 'POST'])
def manage_evidence():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    if session['role'] not in ['Admin', 'Lab', 'Doctor', 'JMO']:
        flash("You do not have permission to manage evidence.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        case_id = request.form['case_id']
        evidence_type = request.form['evidence_type']
        storage_location = request.form['storage_location']
        collected_by = request.form['collected_by']
        collection_date = request.form['collection_date']
        status = request.form['status']
        
        # --- NEW: Image Upload Logic ---
        filename = None
        if 'evidence_image' in request.files:
            file = request.files['evidence_image']
            if file and file.filename != '' and allowed_file(file.filename):
                # Secure the filename and add a unique ID to prevent overwriting images with the same name
                original_filename = secure_filename(file.filename)
                unique_id = str(uuid.uuid4())[:8] 
                filename = f"{case_id}_{unique_id}_{original_filename}"
                
                # Save the file to the static/uploads/evidence folder
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)

        # Update SQL to include the ImagePath
        cursor.execute(
            '''INSERT INTO Evidence (CaseID, EvidenceType, StorageLocation, CollectedBy, CollectionDate, Status, ImagePath) 
               VALUES (%s, %s, %s, %s, %s, %s, %s)''',
            (case_id, evidence_type, storage_location, collected_by, collection_date, status, filename)
        )
        conn.commit()
        
        # Log the action if your helper function is active
        # log_action(session['id'], f"Logged evidence {evidence_type} for case {case_id}")
        
        flash('Evidence and image logged securely!')
        return redirect(url_for('manage_evidence'))

    # GET requests: Fetch existing data for the form
    cursor.execute("SELECT CaseID FROM MedicoLegalCase WHERE CaseStatus != 'Closed'")
    cases = cursor.fetchall()

    cursor.execute("SELECT StaffID, FullName, Role FROM Staff WHERE Role IN ('Lab', 'Doctor', 'JMO', 'Admin')")
    staff = cursor.fetchall()
    
    # Fetch all evidence to display in a table
    cursor.execute("""
        SELECT e.*, s.FullName as CollectorName 
        FROM Evidence e 
        LEFT JOIN Staff s ON e.CollectedBy = s.StaffID 
        ORDER BY e.EvidenceID DESC
    """)
    evidence_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('manage_evidence.html', cases=cases, staff=staff, evidence_list=evidence_list)

@app.route('/lab_test', methods=['GET', 'POST'])
def lab_test():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    # Restrict to lab staff and admins
    if session['role'] not in ['Admin', 'Lab']:
        flash("You do not have permission to record laboratory tests.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        evidence_id = request.form['evidence_id']
        lab_staff_id = request.form['lab_staff_id']
        test_type = request.form['test_type']
        result = request.form['result']
        test_date = request.form['test_date']

        cursor.execute(
            '''INSERT INTO LaboratoryTest (EvidenceID, LabStaffID, TestType, Result, TestDate) 
               VALUES (%s, %s, %s, %s, %s)''',
            (evidence_id, lab_staff_id, test_type, result, test_date)
        )
        conn.commit()
        log_action(session['id'], "Recorded laboratory test results.")
        flash('Laboratory test results saved successfully!')
        return redirect(url_for('lab_test'))

    # Fetch data for the dropdowns
    cursor.execute("""
        SELECT e.EvidenceID, e.EvidenceType, e.CaseID 
        FROM Evidence e 
        WHERE e.Status IN ('Stored', 'In Lab')
    """)
    evidence_items = cursor.fetchall()

    cursor.execute("SELECT StaffID, FullName FROM Staff WHERE Role IN ('Lab', 'Admin')")
    lab_staff = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('lab_test.html', evidence_items=evidence_items, lab_staff=lab_staff)

@app.route('/court_report', methods=['GET', 'POST'])
def court_report():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    # Restrict to doctors, JMOs, and admins
    if session['role'] not in ['Admin', 'Doctor', 'JMO']:
        flash("You do not have permission to generate court reports.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        case_id = request.form['case_id']
        prepared_by = request.form['prepared_by']
        submission_date = request.form['submission_date']
        status = request.form['status']

        cursor.execute(
            '''INSERT INTO CourtReport (CaseID, PreparedBy, SubmissionDate, Status) 
               VALUES (%s, %s, %s, %s)''',
            (case_id, prepared_by, submission_date, status)
        )
        conn.commit()
        log_action(session['id'], "Generated a court report.")
        flash('Court report logged successfully!')
        return redirect(url_for('court_report'))

    # GET request data
    cursor.execute("SELECT CaseID FROM MedicoLegalCase")
    cases = cursor.fetchall()

    cursor.execute("SELECT StaffID, FullName FROM Staff WHERE Role IN ('Doctor', 'JMO', 'Admin')")
    doctors = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('court_report.html', cases=cases, doctors=doctors)

@app.route('/manage_staff', methods=['GET', 'POST'])
def manage_staff():
    # Strict security check: Kick out anyone who isn't logged in or isn't an Admin
    if 'loggedin' not in session or session.get('role') != 'Admin':
        flash("Access Denied: You must be an Administrator to view this page.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        full_name = request.form['full_name']
        role = request.form['role']
        contact_no = request.form['contact_no']
        username = request.form['username']
        password = request.form['password']

        # Map the Staff Role to the UserRole enum in the database
        role_map = {
            'Doctor': 'Doctor',
            'JMO': 'Doctor',
            'Laboratory Staff': 'Lab',
            'Clerical Officer': 'Clerical',
            'Admin': 'Admin'
        }
        user_role = role_map.get(role, 'Clerical')

        try:
            # 1. Insert into Staff Table
            cursor.execute(
                "INSERT INTO Staff (FullName, Role, ContactNo) VALUES (%s, %s, %s)",
                (full_name, role, contact_no)
            )
            new_staff_id = cursor.lastrowid # Grabs the ID that MySQL just auto-generated

            # 2. Insert into Users Table
            cursor.execute(
                "INSERT INTO Users (StaffID, Username, PasswordHash, UserRole) VALUES (%s, %s, %s, %s)",
                (new_staff_id, username, password, user_role)
            )
            conn.commit()
            log_action(session['id'], "Created a new staff account.")
            flash(f'{role} account created successfully!')
            
        except mysql.connector.Error as err:
            conn.rollback() # If one insert fails, cancel both to prevent broken data
            flash(f'Database Error: Username might already be taken. ({err})')

        return redirect(url_for('manage_staff'))

    # GET request: Fetch a list of all current staff to display on the page
    cursor.execute("SELECT s.StaffID, s.FullName, s.Role, u.Username FROM Staff s LEFT JOIN Users u ON s.StaffID = u.StaffID")
    staff_list = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return render_template('manage_staff.html', staff_list=staff_list)

@app.route('/edit_staff/<int:staff_id>', methods=['GET', 'POST'])
def edit_staff(staff_id):
    if 'loggedin' not in session or session.get('role') != 'Admin':
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        new_role = request.form['role']
        
        # Map the Staff Role to the system UserRole
        role_map = {
            'Doctor': 'Doctor', 'JMO': 'Doctor', 
            'Laboratory Staff': 'Lab', 'Clerical Officer': 'Clerical', 
            'Admin': 'Admin'
        }
        user_role = role_map.get(new_role, 'Clerical')

        # Update both tables to keep them synchronized
        cursor.execute("UPDATE Staff SET Role = %s WHERE StaffID = %s", (new_role, staff_id))
        cursor.execute("UPDATE Users SET UserRole = %s WHERE StaffID = %s", (user_role, staff_id))
        conn.commit()
        log_action(session['id'], "Updated a staff role.")
        
        flash('Staff role updated successfully!')
        return redirect(url_for('manage_staff'))

    # GET request: Fetch current staff details to populate the form
    cursor.execute("SELECT * FROM Staff WHERE StaffID = %s", (staff_id,))
    staff_member = cursor.fetchone()
    
    cursor.close()
    conn.close()

    return render_template('edit_staff.html', staff=staff_member)

@app.route('/delete_staff/<int:staff_id>', methods=['POST'])
def delete_staff(staff_id):
    if 'loggedin' not in session or session.get('role') != 'Admin':
        return redirect(url_for('dashboard'))
    
    # Security: Prevent the Admin from accidentally deleting their own logged-in account
    if staff_id == session.get('staff_id'):
        flash('Error: You cannot delete your own active administrator account.')
        return redirect(url_for('manage_staff'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Deleting the staff member automatically cascades to delete their login user account
    cursor.execute("DELETE FROM Staff WHERE StaffID = %s", (staff_id,))
    conn.commit()
    log_action(session['id'], "Deleted a staff account from the system.")
    
    cursor.close()
    conn.close()
    
    flash('Staff account securely removed from the system.')
    return redirect(url_for('manage_staff'))

@app.route('/audit_logs')
def audit_logs():
    # Strict Security Check
    if 'loggedin' not in session or session.get('role') != 'Admin':
        flash("Access Denied: You must be an Administrator to view system logs.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Join tables to get readable names instead of just User IDs
    # ORDER BY LogTime DESC ensures the newest actions are at the top
    query = """
        SELECT a.LogID, a.Action, a.LogTime, u.Username, s.FullName, s.Role
        FROM AuditLog a
        LEFT JOIN Users u ON a.UserID = u.UserID
        LEFT JOIN Staff s ON u.StaffID = s.StaffID
        ORDER BY a.LogTime DESC 
        LIMIT 200
    """
    cursor.execute(query)
    logs = cursor.fetchall()

    log_action(session['id'], "Viewed audit logs.")
    
    cursor.close()
    conn.close()

    return render_template('audit_logs.html', logs=logs)

@app.route('/manage_patients')
def manage_patients():
    if 'loggedin' not in session or session['role'] not in ['Admin', 'Clerical']:
        flash("Access Denied: Only Clerical staff can manage patient records.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM Patient ORDER BY PatientID DESC")
    patients = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('manage_patients.html', patients=patients)

@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
def edit_patient(patient_id):
    if 'loggedin' not in session or session['role'] not in ['Admin', 'Clerical']:
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        full_name = request.form['full_name']
        age = request.form['age']
        gender = request.form['gender']
        contact_info = request.form['contact_info']
        address = request.form['address']

        cursor.execute(
            "UPDATE Patient SET FullName=%s, Age=%s, Gender=%s, ContactInfo=%s, Address=%s WHERE PatientID=%s",
            (full_name, age, gender, contact_info, address, patient_id)
        )
        conn.commit()
        log_action(session['id'], f"Updated patient record for PatientID: {patient_id}")
        flash('Patient details updated successfully!')
        return redirect(url_for('manage_patients'))

    # GET: Fetch current details for the form
    cursor.execute("SELECT * FROM Patient WHERE PatientID = %s", (patient_id,))
    patient = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('edit_patient.html', patient=patient)

@app.route('/reports')
def reports():
    # Security: Restrict reports to medical directors and admins
    if 'loggedin' not in session or session.get('role') not in ['Admin', 'Doctor', 'JMO']:
        flash("Access Denied: Only authorized medical staff can view system analytics.")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Case Status Breakdown (Open vs Pending vs Closed)
    cursor.execute("SELECT CaseStatus, COUNT(*) as count FROM MedicoLegalCase GROUP BY CaseStatus")
    case_status_data = cursor.fetchall()

    # 2. Incident Type Breakdown (Assault, Accident, etc.)
    cursor.execute("SELECT CaseType, COUNT(*) as count FROM MedicoLegalCase GROUP BY CaseType")
    case_type_data = cursor.fetchall()

    # 3. Monthly Statistics (Grouping by Year-Month)
    cursor.execute("""
        SELECT DATE_FORMAT(IncidentDate, '%Y-%m') as MonthLabel, COUNT(*) as CaseCount 
        FROM MedicoLegalCase 
        GROUP BY MonthLabel 
        ORDER BY MonthLabel DESC 
        LIMIT 6
    """)
    monthly_data = cursor.fetchall()

    # 4. Pending Action Items
    cursor.execute("SELECT COUNT(*) as pending_cases FROM MedicoLegalCase WHERE CaseStatus != 'Closed'")
    pending_cases = cursor.fetchone()['pending_cases']

    cursor.execute("SELECT COUNT(*) as pending_reports FROM CourtReport WHERE Status != 'Submitted'")
    pending_reports = cursor.fetchone()['pending_reports']

    cursor.close()
    conn.close()

    # Pass the data to the frontend
    return render_template('reports.html', 
                           case_status_data=case_status_data, 
                           case_type_data=case_type_data,
                           monthly_data=monthly_data,
                           pending_cases=pending_cases,
                           pending_reports=pending_reports)

@app.route('/')
def index():
    # If the user is already logged in, send them straight to the dashboard
    if 'loggedin' in session:
        return redirect(url_for('dashboard'))
    # Otherwise, show the beautiful animated landing page
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)