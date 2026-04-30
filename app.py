from flask import Flask, render_template, request, redirect
from werkzeug.utils import secure_filename
import psycopg2
import os    
import psycopg2.extras
from datetime import datetime

app = Flask(__name__)

def get_next_due(due_days, today):
    days = []

    for d in due_days.split(","):
        if "-" in d:  # support old data
            days.append(int(d.split("-")[2]))
        else:
            days.append(int(d))

    days.sort()

    for day in days:
        try:
            candidate = datetime(today.year, today.month, day).date()
            if candidate >= today:
                return candidate
        except:
            continue

    # next month
    if today.month == 12:
        return datetime(today.year + 1, 1, days[0]).date()
    else:
        return datetime(today.year, today.month + 1, days[0]).date()

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = 'static/uploads'


def get_db():
    DATABASE_URL = os.environ.get("DATABASE_URL")

    if not DATABASE_URL:
        print(" No DATABASE_URL found. Using fallback.")
        DATABASE_URL = "postgresql://loan_db_338f_user:zXga9jmAW84uLdaa5lfVgRdwtKRfZM00@dpg-d7pht7svikkc73aetrr0-a.oregon-postgres.render.com/loan_db_338f"

    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id SERIAL PRIMARY KEY,
            name TEXT,
            type TEXT,
            total_amount REAL,
            charges REAL,
            image TEXT,
            due_date TEXT,
            month TEXT,
            due_days TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            loan_id INTEGER,
            amount REAL,
            payment_date TEXT,
            proof_image TEXT
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()

init_db()


# ========================= HOME =========================
@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM loans")
    loans = cursor.fetchall()

    loan_list = []
    today = datetime.today().date()

    # =========================
    # 📊 DASHBOARD VARIABLES
    # =========================
    total_paid_month = 0
    overdue_count = 0
    due_today_count = 0
    upcoming_count = 0

    for loan in loans:
        # =========================
        # 💰 TOTAL PAID (ALL TIME)
        # =========================
        cursor2 = conn.cursor()
        cursor2.execute(
            "SELECT SUM(amount) as total FROM payments WHERE loan_id=%s",
            (loan['id'],)
        )
        payments = cursor2.fetchone()
        cursor2.close()

        paid = payments['total'] if payments and payments['total'] else 0
        remaining = (loan['total_amount'] + loan['charges']) - paid

        # =========================
        # 💰 TOTAL PAID THIS MONTH
        # =========================
        cursor3 = conn.cursor()
        cursor3.execute("""
            SELECT SUM(amount) as total 
            FROM payments 
            WHERE loan_id=%s
            AND DATE_TRUNC('month', payment_date::date) = DATE_TRUNC('month', CURRENT_DATE)
        """, (loan['id'],))
        month_pay = cursor3.fetchone()
        cursor3.close()

        if month_pay and month_pay['total']:
            total_paid_month += month_pay['total']

        # =========================
        # 📅 DUE DATE
        # =========================
        if loan['due_date']:
            try:
                due_date = datetime.strptime(
                    str(loan['due_date']).strip(),
                    "%Y-%m-%d"
                ).date()
            except:
                due_date = today
        else:
            due_date = today

        days_left = (due_date - today).days

        # =========================
        # 📊 STATUS + COUNTS
        # =========================
        if days_left < 0:
            status = "overdue"
            overdue_count += 1
        elif days_left == 0:
            status = "today"
            due_today_count += 1
        elif days_left <= 3:
            status = "warning"
            upcoming_count += 1
        else:
            status = "normal"

        # =========================
        # 📦 APPEND
        # =========================
        loan_list.append({
            'id': loan['id'],
            'name': loan['name'],
            'type': loan['type'] or 'loan',
            'total': loan['total_amount'],
            'charges': loan['charges'],
            'paid': paid,
            'remaining': remaining,
            'image': loan['image'],
            'due_date': due_date,
            'status': status
        })

    # =========================
    # 📊 SUMMARY TOTALS
    # =========================
    loan_total = 0
    loan_paid = 0
    loan_remaining = 0

    utility_total = 0
    utility_paid = 0
    utility_remaining = 0

    for item in loan_list:
        if item['type'] == 'utility':
            utility_total += item['total']
            utility_paid += item['paid']
            utility_remaining += item['remaining']
        else:
            loan_total += item['total']
            loan_paid += item['paid']
            loan_remaining += item['remaining']

    # =========================
    # 📅 CALENDAR EVENTS (FIXED)
    # =========================
    events = []

    for loan in loan_list:
        if loan['due_date']:
            due = loan['due_date']
            days_left = (due - today).days

            # 🎨 COLOR LOGIC
            if days_left < 0:
                color = "#ef4444"   # 🔴 overdue
            elif days_left <= 2:
                color = "#facc15"   # 🟡 near due
            else:
                color = "#22c55e"   # 🟢 upcoming

            events.append({
                "title": loan['name'],
                "start": str(due),
                "id": loan['id'],
                "color": color
            })

    # =========================
    # ✅ RETURN
    # =========================
    return render_template(
        'index.html',
        loans=loan_list,
        now=datetime.now(),

        loan_total=loan_total,
        loan_paid=loan_paid,
        loan_remaining=loan_remaining,

        utility_total=utility_total,
        utility_paid=utility_paid,
        utility_remaining=utility_remaining,

        total_paid_month=total_paid_month,
        overdue_count=overdue_count,
        due_today_count=due_today_count,
        upcoming_count=upcoming_count,

        events=events
    )
# ========================= ADD PAYMENT =========================
@app.route('/add_payment/<int:loan_id>', methods=['GET', 'POST'])
def add_payment(loan_id):
    conn = get_db()

    if request.method == 'POST':
        amount = request.form['amount']
        date = request.form.get('date')

        if not date:
            date = datetime.today().strftime("%Y-%m-%d")

        file = request.files.get('proof')

        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        else:
            filename = None

        # =========================
        # ✅ SAVE PAYMENT
        # =========================
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO payments (loan_id, amount, payment_date, proof_image) VALUES (%s, %s, %s, %s)",
            (loan_id, amount, date, filename)
        )
        conn.commit()
        cursor.close()

        # =========================
        # ✅ GET LOAN
        # =========================
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM loans WHERE id=%s",
            (loan_id,)
        )
        loan = cursor.fetchone()
        cursor.close()

        # =========================
        # ✅ FIXED DUE LOGIC
        # =========================
        today_dt = datetime.strptime(date, "%Y-%m-%d").date()

        if loan:
            # 🔥 MULTIPLE SCHEDULE
            if loan['due_days']:
                days = []

                for d in loan['due_days'].split(","):
                    if "-" in d:
                        days.append(int(d.split("-")[2]))
                    else:
                        days.append(int(d))

                days.sort()

                next_due = None

                # check current month
                for day in days:
                    try:
                        candidate = datetime(today_dt.year, today_dt.month, day).date()
                        if candidate > today_dt:
                            next_due = candidate
                            break
                    except:
                        continue

                # move to next month if needed
                if not next_due:
                    if today_dt.month == 12:
                        next_due = datetime(today_dt.year + 1, 1, days[0]).date()
                    else:
                        next_due = datetime(today_dt.year, today_dt.month + 1, days[0]).date()

            # 🔥 SINGLE SCHEDULE
            else:
                due_date_obj = datetime.strptime(loan['due_date'], "%Y-%m-%d").date()

                if due_date_obj.month == 12:
                    next_due = due_date_obj.replace(year=due_date_obj.year + 1, month=1)
                else:
                    next_due = due_date_obj.replace(month=due_date_obj.month + 1)

            # =========================
            # ✅ UPDATE NEXT DUE
            # =========================
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE loans
                SET due_date=%s
                WHERE id=%s
            """, (next_due.strftime("%Y-%m-%d"), loan_id))

            conn.commit()
            cursor.close()

        return redirect('/')

    return render_template('add_payment.html', loan_id=loan_id)

# ========================= EDIT =========================
@app.route('/edit_loan/<int:id>', methods=['POST'])
def edit_loan(id):
    conn = get_db()

    name = request.form.get('name')
    total = request.form.get('total')
    charges = request.form.get('charges')

    schedule = request.form.get('schedule')
    day1 = request.form.get('day1')
    day2 = request.form.get('day2')

    # =========================
    # ✅ DUE LOGIC
    # =========================
    if schedule == "multiple":
        if day1 and day2:
            due_days = f"{int(day1[-2:])},{int(day2[-2:])}"
            due_date = day1
        else:
            due_days = None
            due_date = datetime.today().strftime("%Y-%m-%d")
    else:
        due_days = None
        due_date = request.form.get('due_date') or datetime.today().strftime("%Y-%m-%d")

    # =========================
    # ✅ IMAGE FIX
    # =========================
    file = request.files.get('image')

    cursor = conn.cursor()
    cursor.execute("SELECT image FROM loans WHERE id=%s", (id,))
    current = cursor.fetchone()
    current_image = current['image'] if current else None
    cursor.close()

    if file and file.filename.strip() != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    else:
        filename = current_image

    # =========================
    # ✅ FIXED UPDATE (ALWAYS RUN)
    # =========================
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE loans 
        SET name=%s, total_amount=%s, charges=%s, due_date=%s, due_days=%s, image=%s
        WHERE id=%s
    """, (name, total, charges, due_date, due_days, filename, id))

    conn.commit()
    cursor.close()

    return redirect('/')

# ========================= DELETE =========================
@app.route('/delete_loan/<int:loan_id>', methods=['POST'])
def delete_loan(loan_id):
    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("DELETE FROM payments WHERE loan_id=%s", (loan_id,))
    cursor.execute("DELETE FROM loans WHERE id=%s", (loan_id,))

    conn.commit()
    cursor.close()

    return redirect('/')


# ========================= HISTORY =========================
@app.route('/history/<int:loan_id>')
def history(loan_id):
    conn = get_db()

    cursor = conn.cursor()
    cursor.execute(
    "SELECT * FROM loans WHERE id=%s",
    (loan_id,)
)

    loan = cursor.fetchone()

    cursor2 = conn.cursor()
    cursor2.execute("""
            SELECT * FROM payments 
            WHERE loan_id=%s 
            ORDER BY payment_date DESC
        """, (loan_id,))
    payments = cursor2.fetchall()
    cursor2.close()

    return render_template('history.html', loan=loan, payments=payments)

@app.route('/calendar')
def calendar():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, due_date FROM loans")
    loans = cursor.fetchall()
    cursor.close()

    events = []

    for loan in loans:
        if loan['due_date']:
            events.append({
                "title": loan['name'],
                "start": loan['due_date'],
                "id": loan['id']
            })

    return render_template("calendar.html", events=events)

@app.route('/add_loan', methods=['GET', 'POST'])
def add_loan():
    conn = get_db()

    if request.method == 'POST':
        name = request.form.get('name')
        total = request.form.get('total')
        charges = request.form.get('charges') or 0
        loan_type = request.form.get('type') or 'loan'

        schedule = request.form.get('schedule')
        due_date = request.form.get('due_date')
        day1 = request.form.get('day1')
        day2 = request.form.get('day2')

        # =========================
        # 📅 SCHEDULE LOGIC
        # =========================
        if schedule == "multiple" and day1 and day2:
            due_days = f"{int(day1[-2:])},{int(day2[-2:])}"
            due_date = day1
        else:
            due_days = None
            due_date = due_date or datetime.today().strftime("%Y-%m-%d")

        # =========================
        # 🖼 IMAGE
        # =========================
        file = request.files.get('image')

        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        else:
            filename = None

        # =========================
        # 💾 SAVE
        # =========================
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO loans (name, type, total_amount, charges, image, due_date, due_days)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (name, loan_type, total, charges, filename, due_date, due_days))

        conn.commit()
        cursor.close()

        return redirect('/')

    return render_template('add_loan.html')

@app.route('/debug')
def debug():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, due_date, due_days FROM loans")
    loans = cursor.fetchall()

    cursor.close()

    # since we use RealDictCursor, loans is already dict
    return str(loans)

@app.route('/reset')
def reset():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM payments")
    cursor.execute("DELETE FROM loans")

    conn.commit()
    cursor.close()

    return "Database cleared"

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)