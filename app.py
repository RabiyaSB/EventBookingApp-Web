from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, time, timedelta, date
import calendar as pycalendar
from collections import defaultdict
import random
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO


# ---------------- Config ----------------
ADMIN_USERNAME = 'Shahul'   # change if you want a different admin username
SECRET_KEY = 'replace-with-a-secure-random-key'

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///models.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------- Models ----------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    pw_hash = db.Column(db.String(255), nullable=False)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.Integer, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text)
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    from_time = db.Column(db.String(20), nullable=False)
    to_time = db.Column(db.String(20), nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    advance = db.Column(db.Float, nullable=False, default=0)
    balance = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.Column(db.String(80), nullable=True)

# ---------- Helpers ----------
def init_db():
    db.create_all()

    # --- Create admin account if not exists ---
    if not User.query.filter_by(username=ADMIN_USERNAME).first():
        admin = User(username=ADMIN_USERNAME, pw_hash=generate_password_hash('admin123'))
        db.session.add(admin)

    # --- Add default staff accounts ---
    default_staff = {
        'staff1': 'staff123',
        'staff2': 'staff123',
        'staff3': 'staff123'
    }

   # for uname, pwd in default_staff.items():
       # if not User.query.filter_by(username=uname).first():
            #db.session.add(User(username=uname, pw_hash=generate_password_hash(pwd)))

    db.session.commit()


def generate_time_slots(interval_minutes=30):
    slots = []
    t = datetime.combine(date.today(), time(0, 0))
    total = 24 * 60 // interval_minutes
    for _ in range(total):
        slots.append(t.strftime('%I:%M %p'))
        t += timedelta(minutes=interval_minutes)
    return slots

def log_action(action, user=None):
    a = AuditLog(action=action, user=user)
    db.session.add(a)
    db.session.commit()

# Make sure DB is created once (Flask 3 compatibility)
@app.before_request
def setup_once():
    if not getattr(app, "_db_initialized", False):
        init_db()
        app._db_initialized = True

# ---------- Routes ----------
@app.route('/')
def index():
    if session.get('user'):
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Login page uses a special background and hides nav/logout
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.pw_hash, password):
            session['user'] = username
            log_action(f'User {username} logged in', username)
            return redirect(url_for('home'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html', title='Login')

@app.route('/logout')
def logout():
    user = session.pop('user', None)
    if user:
        log_action(f'User {user} logged out', user)
    return redirect(url_for('login'))

@app.route('/home')
def home():
    if not session.get('user'):
        return redirect(url_for('login'))
    return render_template('home.html', hide_nav=True, user=session.get('user'),admin_username=ADMIN_USERNAME)


@app.route('/booking/new', methods=['GET', 'POST'])
def booking_new():
    if not session.get('user'):
        return redirect(url_for('login'))
    # allow prefilled date via ?date=YYYY-MM-DD
    #pre_date = request.args.get('date')
    #try:
        #pre_date_iso = date.fromisoformat(pre_date).isoformat() if pre_date else date.today().isoformat()
    #except Exception:
        #pre_date_iso = date.today().isoformat()

    slots = generate_time_slots(30)
    today_str = date.today().isoformat()

    if request.method == 'POST':
        name = request.form['name']
        phone = request.form.get('phone', '').strip() or None
        email = request.form.get('email', '').strip() or None
        details = request.form.get('details', '')
        from_date = datetime.strptime(request.form['from_date'], '%Y-%m-%d').date()
        to_date = datetime.strptime(request.form['to_date'], '%Y-%m-%d').date()
        from_time = request.form['from_time']
        to_time = request.form['to_time']
        total_amount = request.form['total_amount']
        advance = request.form['advance']
        balance = request.form['balance']

        
                # ---- Overlap / Duplicate Booking Check ----
        def time_to_minutes(t):
            dt = datetime.strptime(t, '%I:%M %p')
            return dt.hour * 60 + dt.minute

        new_start = time_to_minutes(from_time)
        new_end = time_to_minutes(to_time)

        overlapping = False
        existing = Booking.query.filter(Booking.to_date >= from_date, Booking.from_date <= to_date).all()

        for existing_b in existing:
            exist_start = time_to_minutes(existing_b.from_time)
            exist_end = time_to_minutes(existing_b.to_time)
            if (
                (from_date <= existing_b.to_date and to_date >= existing_b.from_date)
                and (new_start < exist_end and new_end > exist_start)
            ):
                overlapping = True
                break
        if not phone:
            flash("⚠️ Phone number is required.", "danger")
            return render_template('booking_form.html', time_slots=slots, today=today_str)

        if overlapping:
            flash("⚠️ This booking overlaps with another booking!", "danger")
            return render_template('booking_form.html', time_slots=slots, today=today_str)


        # ✅ Save booking
        b = Booking(
            name=name,
            phone=int(phone),
            email=email,
            details=details,
            from_date=from_date,
            to_date=to_date,
            from_time=from_time,
            to_time=to_time,
            total_amount=total_amount,
            advance=advance,
            balance=balance,
        )
        db.session.add(b)
        db.session.commit()
        log_action(f"Booking created by {session.get('user')}: {name} {from_date} {from_time} {to_date} {to_time}", session.get('user'))
        flash("✅ Booking created successfully!", "success")
        return redirect(url_for('bookings', view=b.id))

    return render_template('booking_form.html', time_slots=slots, today=today_str)

@app.route('/booking/<int:booking_id>/edit', methods=['GET', 'POST'])
def edit_booking(booking_id):
    if not session.get('user'):
        return redirect(url_for('login'))

    b = Booking.query.get_or_404(booking_id)
    slots = generate_time_slots(30)

    if request.method == 'POST':
        b.name = request.form['name']
        b.phone = request.form['phone']
        b.email = request.form['email']
        b.details = request.form.get('details', '')
        b.from_date = datetime.strptime(request.form['from_date'], '%Y-%m-%d').date()
        b.to_date = datetime.strptime(request.form['to_date'], '%Y-%m-%d').date()
        b.from_time = request.form['from_time']
        b.to_time = request.form['to_time']
        b.total_amount = float(request.form['total_amount'])
        b.advance = float(request.form['advance'])
        b.balance = float(request.form['balance'])

        # ---- Duplicate / Overlap Check ----
        def time_to_minutes(t):
            dt = datetime.strptime(t, '%I:%M %p')
            return dt.hour * 60 + dt.minute

        new_start = time_to_minutes(b.from_time)
        new_end = time_to_minutes(b.to_time)

        overlapping = False
        others = Booking.query.filter(
            Booking.id != b.id,
            Booking.to_date >= b.from_date,
            Booking.from_date <= b.to_date
        ).all()

        for o in others:
            exist_start = time_to_minutes(o.from_time)
            exist_end = time_to_minutes(o.to_time)
            if (
                (b.from_date <= o.to_date and b.to_date >= o.from_date)
                and (new_start < exist_end and new_end > exist_start)
            ):
                overlapping = True
                break

        if overlapping:
            flash("⚠️ This booking overlaps with another booking!", "danger")
            return render_template('booking_form.html', time_slots=slots, edit=True, booking=b, today=b.from_date.isoformat())

        db.session.commit()
        log_action(f"Booking {b.id} updated by {session.get('user')}", session.get('user'))
        flash("✅ Booking updated successfully!", "success")
        return redirect(url_for('bookings'))

    return render_template('booking_form.html', time_slots=slots, edit=True, booking=b, today=b.from_date.isoformat())



@app.route('/booking/<int:booking_id>/delete')
def delete_booking(booking_id):
    if not session.get('user'):
        return redirect(url_for('login'))
    b = Booking.query.get_or_404(booking_id)
    db.session.delete(b)
    db.session.commit()
    log_action(f"Booking {b.id} deleted by {session.get('user')}", session.get('user'))
    flash("Booking deleted successfully!", "success")
    return redirect(url_for('bookings'))


@app.route('/booking/<int:booking_id>/receipt')
def download_receipt(booking_id):
    b = Booking.query.get_or_404(booking_id)
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header
    p.setFont("Helvetica-Bold", 18)
    p.drawCentredString(width / 2, height - 60, "K.A.V AUDITORIUM")
    p.setFont("Helvetica", 10)
    p.drawCentredString(width / 2, height - 80, "Palakkad")

    # Booking Info
    p.setFont("Helvetica-Bold", 12)
    p.drawString(80, height - 120, "Booking Receipt")
    p.setFont("Helvetica", 10)
    lines = [
        f"Name: {b.name}",
        f"Phone: {b.phone}",
        f"Email: {b.email}",
        f"From: {b.from_date} {b.from_time}",
        f"To: {b.to_date} {b.to_time}",
        f"Total Amount: ₹{b.total_amount}",
        f"Advance: ₹{b.advance}",
        f"Balance: ₹{b.balance}",
        f"Details: {b.details or '-'}",
        f"Created At: {b.created_at.strftime('%d-%m-%Y %I:%M %p')}"
    ]
    y = height - 150
    for line in lines:
        p.drawString(80, y, line)
        y -= 20

    p.showPage()
    p.save()
    buffer.seek(0)

    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Booking_{b.id}.pdf'
    return response


@app.route('/bookings')
def bookings():
    if not session.get('user'):
        return redirect(url_for('login'))
    # Optional filters: ?date=YYYY-MM-DD and ?view=<id>
    filter_date = request.args.get('date')
    view_id = request.args.get('view', type=int)
    qs = Booking.query.order_by(Booking.from_date.desc(), Booking.from_time.asc())
    if filter_date:
        try:
            dt = date.fromisoformat(filter_date)
            qs = qs.filter(Booking.from_date <= dt, Booking.to_date >= dt)
        except Exception:
            pass
    allb = qs.all()
    return render_template('dashboard.html', bookings=allb, view_id=view_id, user=session.get('user'), admin_username=ADMIN_USERNAME)


@app.route("/calendar")
def calendar():
    bookings = Booking.query.all()
    bookings_map = {}
    events = []

    # Light palette for day view
    light_colors = ["#add8e6", "#ffb6c1", "#ffe5b4"]  # blue, pink, peach

    for i, b in enumerate(bookings):
        date_str = b.from_date.strftime("%Y-%m-%d")

        # Determine booking status
        if date_str not in bookings_map:
            bookings_map[date_str] = "free"

        if b.from_time and b.to_time:
            duration = datetime.strptime(b.to_time, "%I:%M %p") - datetime.strptime(b.from_time, "%I:%M %p")
            if duration.seconds >= 8 * 3600:
                bookings_map[date_str] = "full"
            else:
                bookings_map[date_str] = "partial"

        # Build event times
        start = f"{b.from_date}T{datetime.strptime(b.from_time, '%I:%M %p').strftime('%H:%M:%S')}"
        end = f"{b.to_date}T{datetime.strptime(b.to_time, '%I:%M %p').strftime('%H:%M:%S')}"

        # Default color based on status (for month/year)
        if bookings_map[date_str] == "full":
            color = "#ef4444"  # red
        elif bookings_map[date_str] == "partial":
            color = "#a855f7"  # purple
        else:
            color = "#22c55e"  # green

        # Alternate light colors for day view
        light_color = light_colors[i % len(light_colors)]

        events.append({
            "id": b.id,
            "title": b.name or "Booking",
            "start": start,
            "end": end,
            "color": color,
            "lightColor": light_color,
            "from_time": b.from_time,
            "to_time": b.to_time,
            "details": b.details,
        })

    return render_template("calendar.html", bookings_map=bookings_map, events=events)



@app.route('/booking/<int:booking_id>')
def booking_api(booking_id):
    """Return JSON for a booking (used by modal on dashboard)."""
    b = Booking.query.get_or_404(booking_id)
    return jsonify({
        'id': b.id,
        'name': b.name,
        'details': b.details,
        'from_date': b.from_date.isoformat(),
        'to_date': b.to_date.isoformat(),
        'from_time': b.from_time,
        'to_time': b.to_time,
        'created_at': b.created_at.isoformat()
    })

@app.route('/audit')
def audit():
    if not session.get('user'):
        return redirect(url_for('login'))
    if session.get('user') != ADMIN_USERNAME:
        flash("You don't have permission to view audit logs.", 'danger')
        return redirect(url_for('bookings'))
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(500).all()
    return render_template('audit_logs.html', logs=logs, hide_audit_nav=True, user=session.get('user'),
        admin_username=ADMIN_USERNAME)

@app.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    if not session.get('user') == ADMIN_USERNAME:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    users = User.query.all()

    if request.method == 'POST':
        action = request.form.get('action')

        # Change admin password
        if action == 'change_password':
            new_pw = request.form['new_password']
            admin = User.query.filter_by(username=ADMIN_USERNAME).first()
            admin.pw_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash("✅ Admin password updated.", "success")

        # Create staff
        elif action == 'create_staff':
            uname = request.form['staff_username']
            pw = request.form['staff_password']
            if User.query.filter_by(username=uname).first():
                flash("⚠️ Username already exists.", "danger")
            else:
                db.session.add(User(username=uname, pw_hash=generate_password_hash(pw)))
                db.session.commit()
                flash(f"✅ Staff '{uname}' created.", "success")

        # Delete staff
        elif action == 'delete_staff':
            uname = request.form['staff_to_delete']
            u = User.query.filter_by(username=uname).first()
            if u and uname != ADMIN_USERNAME:
                db.session.delete(u)
                db.session.commit()
                flash(f"🗑️ Staff '{uname}' deleted.", "info")
            else:
                flash("⚠️ Cannot delete admin or invalid user.", "danger")

        return redirect(url_for('admin_profile'))

    return render_template('admin_profile.html', users=users)


# Simple API: bookings for a date
@app.route('/api/bookings/date/<datestr>')
def api_bookings_by_date(datestr):
    try:
        dt = date.fromisoformat(datestr)
    except Exception:
        return jsonify([])
    items = Booking.query.filter(Booking.from_date <= dt, Booking.to_date >= dt).all()
    out = []
    for b in items:
        out.append({'id': b.id, 'name': b.name, 'from_time': b.from_time, 'to_time': b.to_time})
    return jsonify(out)




if __name__ == '__main__':
    app.run(debug=True)


