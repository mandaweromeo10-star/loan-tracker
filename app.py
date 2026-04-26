from flask import Flask, render_template, request, redirect
import sqlite3, os
from werkzeug.utils import secure_filename
from datetime import datetime
import os

app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def get_db():
    conn = sqlite3.connect('database.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    

    conn.execute('''
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            type TEXT,
            total_amount REAL,
            charges REAL,
            image TEXT,
            due_date TEXT,
            month TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER,
            amount REAL,
            payment_date TEXT,
            proof_image TEXT
        )
    ''')

    conn.commit()
    conn.close()
    if not os.path.exists('database.db'):
        init_db()


@app.route('/')
def index():
    conn = get_db()

    current_month = datetime.now().strftime("%Y-%m")

    loans = conn.execute(
        "SELECT * FROM loans WHERE month=?",
        (current_month,)
    ).fetchall()

    loan_list = []
    total_loans = 0
    total_paid = 0
   

    for loan in loans:

        payments = conn.execute(
            "SELECT SUM(amount) as total FROM payments WHERE loan_id=?",
            (loan['id'],)
        ).fetchone()

        paid = payments['total'] if payments['total'] else 0
        remaining = (loan['total_amount'] + loan['charges']) - paid

        # 🔔 DUE DATE STATUS
        due = loan['due_date']
        today = datetime.today().date()
        due_date = datetime.strptime(due, "%Y-%m-%d").date()

        days_left = (due_date - today).days

        status = "normal"
        if days_left <= 0:
            status = "overdue"
        elif days_left <= 3:
            status = "warning"

        # 📸 LAST RECEIPT
        last_payment = conn.execute("""
            SELECT proof_image FROM payments 
            WHERE loan_id=? ORDER BY id DESC LIMIT 1
        """, (loan['id'],)).fetchone()

        receipt = last_payment['proof_image'] if last_payment else None

        loan_type = loan['type'] if 'type' in loan.keys() and loan['type'] else 'loan'

        loan_list.append({
            'id': loan['id'],
            'name': loan['name'],
            'type': loan_type,
            'total': loan['total_amount'],
            'charges': loan['charges'],
            'paid': paid,
            'remaining': remaining,
            'image': loan['image'],
            'due_date': loan['due_date'],
            'receipt': receipt,
            'status': status
        })

        total_loans += loan['total_amount']
        total_paid += paid

    # ✅ OUTSIDE LOOP
    loan_total = sum((l['total'] + l['charges']) for l in loan_list if l['type'] == 'loan')
    utility_total = sum((l['total'] + l['charges']) for l in loan_list if l['type'] == 'utility')
    loan_remaining = sum(l['remaining'] for l in loan_list if l['type'] == 'loan')
    utility_remaining = sum(l['remaining'] for l in loan_list if l['type'] == 'utility')
    loan_paid = sum(l['paid'] for l in loan_list if l['type'] == 'loan')
    utility_paid = sum(l['paid'] for l in loan_list if l['type'] == 'utility')
    loan_remaining = sum(l['remaining'] for l in loan_list if l['type'] == 'loan')
    utility_remaining = sum(l['remaining'] for l in loan_list if l['type'] == 'utility')



    return render_template(
     'index.html',
    loans=loan_list,
    total_loans=total_loans,
    total_paid=total_paid,
    loan_total=loan_total,
    utility_total=utility_total,
    loan_paid=loan_paid,
    utility_paid=utility_paid,
    loan_remaining=loan_remaining,
    utility_remaining=utility_remaining,
    now=datetime.now(),

)


@app.route('/add_loan', methods=['GET', 'POST'])
def add_loan():
    if request.method == 'POST':

        month = datetime.now().strftime("%Y-%m")

        name = request.form.get('name')
        type_ = request.form.get('type')
        total = request.form.get('total')
        charges = request.form.get('charges')
        due_date = request.form.get('due_date')

        if not name:
            return "ERROR: Name is missing!"

        file = request.files.get('image')

        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        else:
            filename = None

        conn = get_db()
        conn.execute("""
        INSERT INTO loans (name, type, total_amount, charges, image, due_date, month)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, type_, total, charges, filename, due_date, month))

        conn.commit()

        return redirect('/')

    return render_template('add_loan.html')


@app.route('/add_payment/<int:loan_id>', methods=['GET', 'POST'])
def add_payment(loan_id):
    if request.method == 'POST':
        amount = request.form['amount']
        date = request.form['date']

        file = request.files.get('proof')

        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        else:
            filename = None

        conn = get_db()
        conn.execute(
            "INSERT INTO payments (loan_id, amount, payment_date, proof_image) VALUES (?, ?, ?, ?)",
            (loan_id, amount, date, filename)
        )
        conn.commit()

        return redirect('/')

    return render_template('add_payment.html', loan_id=loan_id)

@app.route('/delete_loan/<int:loan_id>', methods=['POST'])
def delete_loan(loan_id):
    conn = get_db()

    # delete payments first (important to avoid orphan data)
    conn.execute("DELETE FROM payments WHERE loan_id=?", (loan_id,))
    conn.execute("DELETE FROM loans WHERE id=?", (loan_id,))

    conn.commit()
    conn.close()

    return redirect('/')


@app.route('/history/<int:loan_id>')
def history(loan_id):
    conn = get_db()

    loan = conn.execute(
        "SELECT * FROM loans WHERE id=?",
        (loan_id,)
    ).fetchone()

    payments = conn.execute("""
        SELECT * FROM payments 
        WHERE loan_id=? 
        ORDER BY payment_date DESC
    """, (loan_id,)).fetchall()

    return render_template('history.html', loan=loan, payments=payments)


if __name__ == '__main__':
    app.run(debug=True)