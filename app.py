from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "meeting.db")

app = Flask(__name__)
app.secret_key = "hk253-damh-nhom01-demo-secret"

# Khung giờ hiển thị trên lưới lịch tuần/ngày 
GRID_START_HOUR = 7
GRID_END_HOUR = 19
ROW_HEIGHT_PX = 50

# Bảng màu sự kiện: cuộc họp do tôi tạo vs được mời
COLOR_MINE = {"bg": "#DCEBF9", "border": "#2E75B6", "text": "#14456e"}
COLOR_INVITED = {"bg": "#FDECD6", "border": "#e08a2e", "text": "#7a4a0e"}
COLOR_CANCELLED = {"bg": "#f3f3f3", "border": "#AAAAAA", "text": "#888888"}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    if not os.path.exists(DB_PATH):
        db = sqlite3.connect(DB_PATH)
        with open(os.path.join(BASE_DIR, "schema.sql"), "r", encoding="utf-8") as f:
            db.executescript(f.read())
        db.commit()
        db.close()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM employees WHERE id = ?", (uid,)).fetchone()


def require_roles(*roles):
    """Decorator: chỉ cho phép các role được liệt kê truy cập route."""
    def decorator(view_func):
        from functools import wraps
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None or user["role"] not in roles:
                flash("Bạn không có quyền truy cập chức năng này.", "danger")
                return redirect(url_for("calendar_view"))
            return view_func(*args, **kwargs)
        return wrapped
    return decorator


@app.before_request
def require_login():
    if request.endpoint in ("login", "static"):
        return
    if not session.get("user_id"):
        return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("calendar_view"))


# ---------- Đăng nhập (US-01: email + mật khẩu) ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    db = get_db()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.execute("SELECT * FROM employees WHERE lower(email) = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Email hoặc mật khẩu không đúng.", "danger")
            return render_template("login.html", email=email)
        if user["is_locked"]:
            flash("Tài khoản của bạn đã bị khóa. Vui lòng liên hệ Administrator.", "danger")
            return render_template("login.html", email=email)
        session["user_id"] = user["id"]
        return redirect(url_for("calendar_view"))
    return render_template("login.html", email="")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def notify_users(db, employee_ids, message, meeting_id=None):
    """Tạo thông báo thật (lưu CSDL) cho danh sách người nhận."""
    for emp_id in set(employee_ids):
        db.execute(
            "INSERT INTO notifications (employee_id, meeting_id, message) VALUES (?, ?, ?)",
            (emp_id, meeting_id, message),
        )


def _user_meetings_in_range(db, user_id, start_dt, end_dt):
    """Lấy toàn bộ cuộc họp (tôi tạo hoặc được mời) giao với khoảng [start_dt, end_dt)."""
    start_s = start_dt.strftime("%Y-%m-%d %H:%M")
    end_s = end_dt.strftime("%Y-%m-%d %H:%M")
    rows = db.execute(
        """SELECT m.*, r.name AS room_name, e.name AS creator_name
           FROM meetings m
           JOIN rooms r ON r.id = m.room_id
           JOIN employees e ON e.id = m.creator_id
           WHERE (m.creator_id = :uid OR m.id IN
                  (SELECT meeting_id FROM meeting_participants WHERE employee_id = :uid))
             AND m.start_time < :end_s AND m.end_time > :start_s
           ORDER BY m.start_time""",
        {"uid": user_id, "start_s": start_s, "end_s": end_s},
    ).fetchall()
    return rows


# ---------- Lịch họp cá nhân (Ngày / Tuần / Tháng) ----------
@app.route("/calendar")
def calendar_view():
    db = get_db()
    user = current_user()
    view = request.args.get("view", "week")
    date_str = request.args.get("date")
    try:
        ref_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now().date()
    except ValueError:
        ref_date = datetime.now().date()

    today = datetime.now().date()

    if view == "day":
        days = [ref_date]
        range_start = datetime.combine(ref_date, datetime.min.time())
        range_end = range_start + timedelta(days=1)
        prev_date = ref_date - timedelta(days=1)
        next_date = ref_date + timedelta(days=1)
        title = ref_date.strftime("Ngày %d/%m/%Y")
    elif view == "month":
        first_of_month = ref_date.replace(day=1)
        if first_of_month.month == 12:
            next_month = first_of_month.replace(year=first_of_month.year + 1, month=1)
        else:
            next_month = first_of_month.replace(month=first_of_month.month + 1)
        # Lưới tháng bắt đầu từ Thứ 2 của tuần chứa ngày 1
        grid_start = first_of_month - timedelta(days=(first_of_month.weekday()))
        grid_end = grid_start + timedelta(days=42)
        range_start = datetime.combine(grid_start, datetime.min.time())
        range_end = datetime.combine(grid_end, datetime.min.time())
        days = [grid_start + timedelta(days=i) for i in range(42)]
        prev_date = (first_of_month - timedelta(days=1)).replace(day=1)
        next_date = next_month
        title = "Tháng " + ref_date.strftime("%m/%Y")
    else:  # week
        view = "week"
        week_start = ref_date - timedelta(days=ref_date.weekday())
        days = [week_start + timedelta(days=i) for i in range(7)]
        range_start = datetime.combine(week_start, datetime.min.time())
        range_end = range_start + timedelta(days=7)
        prev_date = week_start - timedelta(days=7)
        next_date = week_start + timedelta(days=7)
        title = f"Tuần {week_start.strftime('%d/%m')} – {(week_start + timedelta(days=6)).strftime('%d/%m/%Y')}"

    rows = _user_meetings_in_range(db, user["id"], range_start, range_end)

    # Gom sự kiện theo từng ngày + tính vị trí hiển thị trên lưới (chỉ cần cho view day/week)
    events_by_day = {d.isoformat(): [] for d in days}
    month_counts = {d.isoformat(): 0 for d in days} if view == "month" else None

    for m in rows:
        m_start = datetime.strptime(m["start_time"], "%Y-%m-%d %H:%M")
        m_end = datetime.strptime(m["end_time"], "%Y-%m-%d %H:%M")
        day_key = m_start.date().isoformat()
        if day_key not in events_by_day:
            continue
        is_mine = (m["creator_id"] == user["id"])
        colors = COLOR_CANCELLED if m["status"] != "active" else (COLOR_MINE if is_mine else COLOR_INVITED)

        if view in ("day", "week"):
            start_hour = max(m_start.hour + m_start.minute / 60, GRID_START_HOUR)
            end_hour = min(m_end.hour + m_end.minute / 60, GRID_END_HOUR)
            top = (start_hour - GRID_START_HOUR) * ROW_HEIGHT_PX
            height = max((end_hour - start_hour) * ROW_HEIGHT_PX, 22)
            events_by_day[day_key].append({
                "id": m["id"], "title": m["title"], "room_name": m["room_name"],
                "start_time": m_start.strftime("%H:%M"), "end_time": m_end.strftime("%H:%M"),
                "top": round(top, 1), "height": round(height, 1),
                "colors": colors, "is_mine": is_mine, "status": m["status"],
            })
        else:
            month_counts[day_key] = month_counts.get(day_key, 0) + 1
            events_by_day[day_key].append({
                "id": m["id"], "title": m["title"], "colors": colors, "status": m["status"],
            })

    hours = list(range(GRID_START_HOUR, GRID_END_HOUR + 1))

    return render_template(
        "calendar.html", user=user, view=view, ref_date=ref_date, today=today,
        days=days, events_by_day=events_by_day, hours=hours,
        row_height=ROW_HEIGHT_PX, prev_date=prev_date, next_date=next_date, title=title,
        current_month=ref_date.month,
    )


# =========================================================================
# MODULE 2 — QUẢN LÝ PHÒNG HỌP (Meeting Manager)
# Quyền truy cập: role = manager hoặc admin
# =========================================================================

@app.route("/rooms")
def rooms_view():
    """Nhân viên: chỉ xem danh sách phòng (read-only) để tham khảo khi đặt lịch."""
    db = get_db()
    user = current_user()
    rooms = db.execute("SELECT * FROM rooms WHERE status != 'deleted' ORDER BY name").fetchall()
    return render_template("rooms.html", user=user, rooms=rooms)


@app.route("/manager/rooms")
@require_roles("manager", "admin")
def manager_rooms():
    db = get_db()
    user = current_user()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    rooms = db.execute("SELECT * FROM rooms WHERE status != 'deleted' ORDER BY name").fetchall()

    rooms_data = []
    for r in rooms:
        in_use = db.execute(
            """SELECT 1 FROM meetings WHERE room_id = ? AND status = 'active'
               AND start_time <= ? AND end_time > ? LIMIT 1""",
            (r["id"], now_str, now_str),
        ).fetchone()
        total_hours = db.execute(
            """SELECT COALESCE(SUM(
                 (julianday(end_time) - julianday(start_time)) * 24
               ), 0) AS hrs
               FROM meetings WHERE room_id = ? AND status = 'active'""",
            (r["id"],),
        ).fetchone()["hrs"]
        rooms_data.append({"room": r, "in_use": bool(in_use), "total_hours": round(total_hours, 1)})

    return render_template("manager_rooms.html", user=user, rooms_data=rooms_data)


@app.route("/manager/rooms/new", methods=["GET", "POST"])
@require_roles("manager", "admin")
def manager_room_new():
    db = get_db()
    user = current_user()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        capacity = request.form.get("capacity", "").strip()
        equipment = request.form.get("equipment", "").strip()
        errors = []
        if not name:
            errors.append("Tên phòng là bắt buộc.")
        if not capacity.isdigit() or int(capacity) <= 0:
            errors.append("Sức chứa phải là số nguyên dương.")
        existing = db.execute("SELECT 1 FROM rooms WHERE name = ? AND status != 'deleted'", (name,)).fetchone()
        if existing:
            errors.append("Tên phòng đã tồn tại.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("manager_room_form.html", user=user, form=request.form, mode="new")
        db.execute(
            "INSERT INTO rooms (name, capacity, equipment, status) VALUES (?, ?, ?, 'active')",
            (name, int(capacity), equipment),
        )
        db.commit()
        flash(f"✅ Đã thêm phòng họp \u201c{name}\u201d.", "success")
        return redirect(url_for("manager_rooms"))
    return render_template("manager_room_form.html", user=user, form={}, mode="new")


@app.route("/manager/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@require_roles("manager", "admin")
def manager_room_edit(room_id):
    db = get_db()
    user = current_user()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        flash("Không tìm thấy phòng họp.", "danger")
        return redirect(url_for("manager_rooms"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        capacity = request.form.get("capacity", "").strip()
        equipment = request.form.get("equipment", "").strip()
        status = request.form.get("status", "active")
        errors = []
        if not name:
            errors.append("Tên phòng là bắt buộc.")
        if not capacity.isdigit() or int(capacity) <= 0:
            errors.append("Sức chứa phải là số nguyên dương.")
        dup = db.execute("SELECT 1 FROM rooms WHERE name = ? AND id != ? AND status != 'deleted'",
                          (name, room_id)).fetchone()
        if dup:
            errors.append("Tên phòng đã tồn tại.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("manager_room_form.html", user=user, form=request.form, mode="edit", room=room)
        db.execute(
            "UPDATE rooms SET name=?, capacity=?, equipment=?, status=? WHERE id=?",
            (name, int(capacity), equipment, status, room_id),
        )
        db.commit()
        flash("✅ Cập nhật thông tin phòng họp thành công.", "success")
        return redirect(url_for("manager_rooms"))

    form = {"name": room["name"], "capacity": str(room["capacity"]),
            "equipment": room["equipment"] or "", "status": room["status"]}
    return render_template("manager_room_form.html", user=user, form=form, mode="edit", room=room)


@app.route("/manager/rooms/<int:room_id>/delete", methods=["POST"])
@require_roles("manager", "admin")
def manager_room_delete(room_id):
    db = get_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    has_upcoming = db.execute(
        """SELECT 1 FROM meetings WHERE room_id = ? AND status = 'active' AND end_time > ? LIMIT 1""",
        (room_id, now_str),
    ).fetchone()
    if has_upcoming:
        flash("Không thể xóa: phòng này còn cuộc họp sắp diễn ra hoặc đang diễn ra. Hãy hủy/di dời các cuộc họp đó trước.", "danger")
    else:
        db.execute("UPDATE rooms SET status = 'deleted' WHERE id = ?", (room_id,))
        db.commit()
        flash("🗑️ Đã xóa phòng họp.", "success")
    return redirect(url_for("manager_rooms"))


@app.route("/manager/rooms/<int:room_id>/history")
@require_roles("manager", "admin")
def manager_room_history(room_id):
    db = get_db()
    user = current_user()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        flash("Không tìm thấy phòng họp.", "danger")
        return redirect(url_for("manager_rooms"))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    bookings = db.execute(
        """SELECT m.*, e.name AS creator_name FROM meetings m
           JOIN employees e ON e.id = m.creator_id
           WHERE m.room_id = ? ORDER BY m.start_time DESC""",
        (room_id,),
    ).fetchall()
    return render_template("manager_room_history.html", user=user, room=room, bookings=bookings, now_str=now_str)


# =========================================================================
# MODULE 3 — ADMINISTRATOR
# Quyền truy cập: role = admin
# =========================================================================

@app.route("/admin/accounts")
@require_roles("admin")
def admin_accounts():
    db = get_db()
    user = current_user()
    accounts = db.execute("SELECT * FROM employees ORDER BY name").fetchall()
    return render_template("admin_accounts.html", user=user, accounts=accounts)


@app.route("/admin/accounts/new", methods=["GET", "POST"])
@require_roles("admin")
def admin_account_new():
    db = get_db()
    user = current_user()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "employee")
        errors = []
        if not name:
            errors.append("Họ tên là bắt buộc.")
        if not email:
            errors.append("Email là bắt buộc.")
        if len(password) < 6:
            errors.append("Mật khẩu phải có ít nhất 6 ký tự.")
        if role not in ("employee", "manager", "admin"):
            role = "employee"
        existing = db.execute("SELECT 1 FROM employees WHERE lower(email) = ?", (email,)).fetchone()
        if existing:
            errors.append("Email đã được sử dụng.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin_account_form.html", user=user, form=request.form, mode="new")
        db.execute(
            "INSERT INTO employees (name, email, password_hash, role, is_locked) VALUES (?, ?, ?, ?, 0)",
            (name, email, generate_password_hash(password, method="pbkdf2:sha256"), role),
        )
        db.commit()
        flash(f"✅ Đã tạo tài khoản cho {name}.", "success")
        return redirect(url_for("admin_accounts"))
    return render_template("admin_account_form.html", user=user, form={}, mode="new")


@app.route("/admin/accounts/<int:emp_id>/toggle-lock", methods=["POST"])
@require_roles("admin")
def admin_account_toggle_lock(emp_id):
    db = get_db()
    user = current_user()
    if emp_id == user["id"]:
        flash("Bạn không thể tự khóa tài khoản của chính mình.", "danger")
        return redirect(url_for("admin_accounts"))
    emp = db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if not emp:
        flash("Không tìm thấy tài khoản.", "danger")
        return redirect(url_for("admin_accounts"))
    new_state = 0 if emp["is_locked"] else 1
    db.execute("UPDATE employees SET is_locked = ? WHERE id = ?", (new_state, emp_id))
    db.commit()
    flash(("🔒 Đã khóa" if new_state else "🔓 Đã mở khóa") + f" tài khoản {emp['name']}.", "success")
    return redirect(url_for("admin_accounts"))


@app.route("/admin/accounts/<int:emp_id>/role", methods=["POST"])
@require_roles("admin")
def admin_account_role(emp_id):
    db = get_db()
    user = current_user()
    role = request.form.get("role")
    if role not in ("employee", "manager", "admin"):
        flash("Vai trò không hợp lệ.", "danger")
        return redirect(url_for("admin_accounts"))
    if emp_id == user["id"] and role != "admin":
        flash("Bạn không thể tự hạ quyền admin của chính mình.", "danger")
        return redirect(url_for("admin_accounts"))
    db.execute("UPDATE employees SET role = ? WHERE id = ?", (role, emp_id))
    db.commit()
    flash("✅ Đã cập nhật phân quyền.", "success")
    return redirect(url_for("admin_accounts"))


@app.route("/admin/dashboard")
@require_roles("admin")
def admin_dashboard():
    db = get_db()
    user = current_user()

    now = datetime.now()
    month_start = now.strftime("%Y-%m-01 00:00")
    if now.month == 12:
        next_month_start = now.replace(year=now.year + 1, month=1, day=1).strftime("%Y-%m-%d 00:00")
    else:
        next_month_start = now.replace(month=now.month + 1, day=1).strftime("%Y-%m-%d 00:00")

    meetings_this_month = db.execute(
        """SELECT COUNT(*) AS c FROM meetings
           WHERE status = 'active' AND start_time >= ? AND start_time < ?""",
        (month_start, next_month_start),
    ).fetchone()["c"]

    total_meetings = db.execute("SELECT COUNT(*) AS c FROM meetings WHERE status = 'active'").fetchone()["c"]
    cancelled_meetings = db.execute("SELECT COUNT(*) AS c FROM meetings WHERE status = 'cancelled'").fetchone()["c"]

    room_usage = db.execute(
        """SELECT r.name, COALESCE(SUM((julianday(m.end_time) - julianday(m.start_time)) * 24), 0) AS hours,
                  COUNT(m.id) AS meeting_count
           FROM rooms r
           LEFT JOIN meetings m ON m.room_id = r.id AND m.status = 'active'
                 AND m.start_time >= ? AND m.start_time < ?
           WHERE r.status != 'deleted'
           GROUP BY r.id ORDER BY hours DESC""",
        (month_start, next_month_start),
    ).fetchall()

    top_organizers = db.execute(
        """SELECT e.name, COUNT(m.id) AS meeting_count
           FROM employees e JOIN meetings m ON m.creator_id = e.id
           WHERE m.status = 'active' AND m.start_time >= ? AND m.start_time < ?
           GROUP BY e.id ORDER BY meeting_count DESC LIMIT 5""",
        (month_start, next_month_start),
    ).fetchall()

    total_accounts = db.execute("SELECT COUNT(*) AS c FROM employees").fetchone()["c"]
    locked_accounts = db.execute("SELECT COUNT(*) AS c FROM employees WHERE is_locked = 1").fetchone()["c"]

    max_hours = max([r["hours"] for r in room_usage], default=0) or 1

    return render_template(
        "admin_dashboard.html", user=user,
        month_label=now.strftime("%m/%Y"),
        meetings_this_month=meetings_this_month,
        total_meetings=total_meetings, cancelled_meetings=cancelled_meetings,
        room_usage=room_usage, top_organizers=top_organizers, max_hours=max_hours,
        total_accounts=total_accounts, locked_accounts=locked_accounts,
    )


# ---------- Trang tài khoản: xem + cập nhật thông tin cá nhân ----------
@app.route("/account")
def account_view():
    user = current_user()
    return render_template("account.html", user=user)


@app.route("/account/update", methods=["GET", "POST"])
def account_update():
    db = get_db()
    user = current_user()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        errors = []
        if not name:
            errors.append("Họ tên là bắt buộc.")
        if not email:
            errors.append("Email là bắt buộc.")
        dup = db.execute(
            "SELECT 1 FROM employees WHERE lower(email) = ? AND id != ?", (email, user["id"])
        ).fetchone()
        if dup:
            errors.append("Email này đã được tài khoản khác sử dụng.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("account_update.html", user=user, form=request.form)
        db.execute("UPDATE employees SET name = ?, email = ? WHERE id = ?", (name, email, user["id"]))
        db.commit()
        flash("✅ Cập nhật thông tin cá nhân thành công.", "success")
        return redirect(url_for("account_view"))
    return render_template("account_update.html", user=user, form={"name": user["name"], "email": user["email"]})


@app.route("/account/change-password", methods=["GET", "POST"])
def account_change_password():
    db = get_db()
    user = current_user()
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        errors = []
        if not check_password_hash(user["password_hash"], old_password):
            errors.append("Mật khẩu hiện tại không đúng.")
        if len(new_password) < 6:
            errors.append("Mật khẩu mới phải có ít nhất 6 ký tự.")
        if new_password != confirm_password:
            errors.append("Xác nhận mật khẩu mới không khớp.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("account_change_password.html", user=user)
        db.execute(
            "UPDATE employees SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password, method="pbkdf2:sha256"), user["id"]),
        )
        db.commit()
        flash("✅ Đổi mật khẩu thành công. Lần đăng nhập sau hãy dùng mật khẩu mới.", "success")
        return redirect(url_for("account_view"))
    return render_template("account_change_password.html", user=user)


# ---------- Trang thông báo ----------
@app.route("/notifications")
def notifications_view():
    db = get_db()
    user = current_user()
    notes = db.execute(
        """SELECT n.*, m.title AS meeting_title FROM notifications n
           LEFT JOIN meetings m ON m.id = n.meeting_id
           WHERE n.employee_id = ? ORDER BY n.created_at DESC, n.id DESC""",
        (user["id"],),
    ).fetchall()
    db.execute("UPDATE notifications SET is_read = 1 WHERE employee_id = ? AND is_read = 0", (user["id"],))
    db.commit()
    return render_template("notifications.html", user=user, notifications=notes)


def unread_notification_count(db, user_id):
    return db.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE employee_id = ? AND is_read = 0", (user_id,)
    ).fetchone()["c"]


@app.context_processor
def inject_unread_count():
    if session.get("user_id"):
        db = get_db()
        return {"unread_notif_count": unread_notification_count(db, session["user_id"])}
    return {"unread_notif_count": 0}


# ---------- Quản lý cuộc họp (danh sách) ----------
@app.route("/meetings")
def meeting_list():
    db = get_db()
    user = current_user()
    created = db.execute(
        """SELECT m.*, r.name AS room_name FROM meetings m
           JOIN rooms r ON r.id = m.room_id
           WHERE m.creator_id = ? ORDER BY m.start_time DESC""",
        (user["id"],),
    ).fetchall()
    invited = db.execute(
        """SELECT m.*, r.name AS room_name, e.name AS creator_name, mp.response
           FROM meetings m
           JOIN rooms r ON r.id = m.room_id
           JOIN employees e ON e.id = m.creator_id
           JOIN meeting_participants mp ON mp.meeting_id = m.id
           WHERE mp.employee_id = ? ORDER BY m.start_time DESC""",
        (user["id"],),
    ).fetchall()
    return render_template("meeting_list.html", user=user, created=created, invited=invited,
                            now=datetime.now(), now_str=datetime.now().strftime("%Y-%m-%d %H:%M"))


# ---------- API: kiểm tra phòng trống & người tham gia bận theo thời gian ----------
# (phục vụ UI-2: lọc phòng trống động + cảnh báo ⚠️ người tham gia bận ngay trên form)
@app.route("/api/availability")
def api_availability():
    db = get_db()
    start_time = request.args.get("start", "").replace("T", " ")
    end_time = request.args.get("end", "").replace("T", " ")
    exclude_id = request.args.get("exclude_meeting_id", type=int)
    participant_ids = [p for p in request.args.get("participant_ids", "").split(",") if p]

    all_rooms = db.execute("SELECT * FROM rooms WHERE status = 'active' ORDER BY name").fetchall()

    if not start_time or not end_time or start_time >= end_time:
        return jsonify({
            "available_room_ids": [r["id"] for r in all_rooms],
            "busy_participant_ids": [],
        })

    available_room_ids = []
    for r in all_rooms:
        q = """SELECT 1 FROM meetings WHERE room_id = ? AND status = 'active'
               AND start_time < ? AND end_time > ?"""
        params = [r["id"], end_time, start_time]
        if exclude_id:
            q += " AND id != ?"
            params.append(exclude_id)
        conflict = db.execute(q, params).fetchone()
        if not conflict:
            available_room_ids.append(r["id"])

    busy_participant_ids = []
    for pid in participant_ids:
        q = """SELECT 1 FROM meetings m
               JOIN meeting_participants mp ON mp.meeting_id = m.id
               WHERE mp.employee_id = ? AND m.status = 'active'
               AND m.start_time < ? AND m.end_time > ?"""
        params = [pid, end_time, start_time]
        if exclude_id:
            q += " AND m.id != ?"
            params.append(exclude_id)
        busy = db.execute(q, params).fetchone()
        if busy:
            busy_participant_ids.append(int(pid))

    return jsonify({
        "available_room_ids": available_room_ids,
        "busy_participant_ids": busy_participant_ids,
    })


# ---------- Tạo lịch họp mới (US-04) ----------
@app.route("/meetings/new", methods=["GET", "POST"])
def meeting_new():
    db = get_db()
    user = current_user()
    rooms = db.execute("SELECT * FROM rooms WHERE status = 'active' ORDER BY name").fetchall()
    employees = db.execute(
        "SELECT * FROM employees WHERE id != ? ORDER BY name", (user["id"],)
    ).fetchall()
    employees_json = [{"id": e["id"], "name": e["name"], "email": e["email"]} for e in employees]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        room_id = request.form.get("room_id")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        description = request.form.get("description", "").strip()
        participant_ids = request.form.getlist("participants")

        errors = []
        if not title:
            errors.append("Tiêu đề cuộc họp là bắt buộc.")
        if len(title) > 200:
            errors.append("Tiêu đề tối đa 200 ký tự.")
        if not room_id:
            errors.append("Vui lòng chọn phòng họp.")
        if not start_time or not end_time:
            errors.append("Vui lòng chọn thời gian bắt đầu và kết thúc.")
        else:
            if start_time >= end_time:
                errors.append("Thời gian kết thúc phải lớn hơn thời gian bắt đầu.")
            if start_time < datetime.now().strftime("%Y-%m-%dT%H:%M"):
                errors.append("Không được chọn thời gian trong quá khứ.")

        room_conflict = False
        busy_participants = []
        if room_id and start_time and end_time and not errors:
            st = start_time.replace("T", " ")
            et = end_time.replace("T", " ")
            conflict = db.execute(
                """SELECT * FROM meetings
                   WHERE room_id = ? AND status = 'active'
                   AND start_time < ? AND end_time > ?""",
                (room_id, et, st),
            ).fetchone()
            if conflict:
                room_conflict = True
                errors.append(f"Phòng họp đã được đặt trong khung giờ này (trùng với cuộc họp '{conflict['title']}').")

            for pid in participant_ids:
                busy = db.execute(
                    """SELECT m.title FROM meetings m
                       JOIN meeting_participants mp ON mp.meeting_id = m.id
                       WHERE mp.employee_id = ? AND m.status = 'active'
                       AND m.start_time < ? AND m.end_time > ?""",
                    (pid, et, st),
                ).fetchone()
                if busy:
                    emp = db.execute("SELECT name FROM employees WHERE id = ?", (pid,)).fetchone()
                    busy_participants.append(emp["name"])

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "meeting_form.html", user=user, rooms=rooms, employees=employees,
                employees_json=employees_json,
                form=request.form, participant_ids=participant_ids, mode="new"
            )

        st = start_time.replace("T", " ")
        et = end_time.replace("T", " ")
        cur = db.execute(
            """INSERT INTO meetings (title, room_id, start_time, end_time, description, creator_id, status)
               VALUES (?, ?, ?, ?, ?, ?, 'active')""",
            (title, room_id, st, et, description, user["id"]),
        )
        meeting_id = cur.lastrowid
        for pid in participant_ids:
            db.execute(
                "INSERT INTO meeting_participants (meeting_id, employee_id, response) VALUES (?, ?, 'pending')",
                (meeting_id, pid),
            )
        if participant_ids:
            notify_users(
                db, participant_ids,
                f"{user['name']} đã mời bạn tham gia cuộc họp \u201c{title}\u201d lúc {st} tại {next(r['name'] for r in rooms if str(r['id']) == str(room_id))}.",
                meeting_id,
            )
        db.commit()

        if busy_participants:
            flash("⚠️ Đã tạo cuộc họp. Lưu ý: " + ", ".join(busy_participants) + " đang bận trong khung giờ này.", "warning")
        flash("✅ Tạo lịch họp thành công. Đã gửi thông báo mời họp đến người tham gia.", "success")
        return redirect(url_for("meeting_list"))

    return render_template(
        "meeting_form.html", user=user, rooms=rooms, employees=employees,
        employees_json=employees_json,
        form={}, participant_ids=[], mode="new"
    )


# ---------- Sửa cuộc họp (US-05) ----------
@app.route("/meetings/<int:meeting_id>/edit", methods=["GET", "POST"])
def meeting_edit(meeting_id):
    db = get_db()
    user = current_user()
    meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if not meeting:
        flash("Không tìm thấy cuộc họp.", "danger")
        return redirect(url_for("meeting_list"))
    if meeting["creator_id"] != user["id"]:
        flash("Chỉ người tạo cuộc họp mới có quyền sửa.", "danger")
        return redirect(url_for("meeting_list"))

    rooms = db.execute("SELECT * FROM rooms WHERE status = 'active' ORDER BY name").fetchall()
    employees = db.execute("SELECT * FROM employees WHERE id != ? ORDER BY name", (user["id"],)).fetchall()
    employees_json = [{"id": e["id"], "name": e["name"], "email": e["email"]} for e in employees]
    current_participants = [
        str(r["employee_id"]) for r in db.execute(
            "SELECT employee_id FROM meeting_participants WHERE meeting_id = ?", (meeting_id,)
        ).fetchall()
    ]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        room_id = request.form.get("room_id")
        start_time = request.form.get("start_time", "").replace("T", " ")
        end_time = request.form.get("end_time", "").replace("T", " ")
        description = request.form.get("description", "").strip()
        participant_ids = request.form.getlist("participants")

        errors = []
        if not title:
            errors.append("Tiêu đề cuộc họp là bắt buộc.")
        if start_time >= end_time:
            errors.append("Thời gian kết thúc phải lớn hơn thời gian bắt đầu.")

        conflict = db.execute(
            """SELECT * FROM meetings WHERE room_id = ? AND status = 'active' AND id != ?
               AND start_time < ? AND end_time > ?""",
            (room_id, meeting_id, end_time, start_time),
        ).fetchone()
        if conflict:
            errors.append(f"Phòng họp đã được đặt trong khung giờ này (trùng với cuộc họp '{conflict['title']}').")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "meeting_form.html", user=user, rooms=rooms, employees=employees,
                employees_json=employees_json,
                form=request.form, participant_ids=participant_ids, mode="edit", meeting=meeting
            )

        db.execute(
            """UPDATE meetings SET title=?, room_id=?, start_time=?, end_time=?, description=?
               WHERE id=?""",
            (title, room_id, start_time, end_time, description, meeting_id),
        )
        db.execute("DELETE FROM meeting_participants WHERE meeting_id = ?", (meeting_id,))
        for pid in participant_ids:
            db.execute(
                "INSERT INTO meeting_participants (meeting_id, employee_id, response) VALUES (?, ?, 'pending')",
                (meeting_id, pid),
            )
        if participant_ids:
            notify_users(
                db, participant_ids,
                f"{user['name']} đã cập nhật cuộc họp \u201c{title}\u201d — thời gian mới: {start_time} → {end_time}.",
                meeting_id,
            )
        db.commit()
        flash("✅ Cập nhật cuộc họp thành công. Đã gửi thông báo cập nhật đến người tham gia.", "success")
        return redirect(url_for("meeting_list"))

    form = {
        "title": meeting["title"],
        "room_id": str(meeting["room_id"]),
        "start_time": meeting["start_time"].replace(" ", "T"),
        "end_time": meeting["end_time"].replace(" ", "T"),
        "description": meeting["description"] or "",
    }
    return render_template(
        "meeting_form.html", user=user, rooms=rooms, employees=employees,
        employees_json=employees_json,
        form=form, participant_ids=current_participants, mode="edit", meeting=meeting
    )


# ---------- Hủy cuộc họp (US-06) ----------
@app.route("/meetings/<int:meeting_id>/cancel", methods=["POST"])
def meeting_cancel(meeting_id):
    db = get_db()
    user = current_user()
    meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if not meeting:
        flash("Không tìm thấy cuộc họp.", "danger")
    elif meeting["creator_id"] != user["id"]:
        flash("Chỉ người tạo cuộc họp mới có quyền hủy.", "danger")
    else:
        db.execute("UPDATE meetings SET status = 'cancelled' WHERE id = ?", (meeting_id,))
        participant_ids = [
            r["employee_id"] for r in db.execute(
                "SELECT employee_id FROM meeting_participants WHERE meeting_id = ?", (meeting_id,)
            ).fetchall()
        ]
        if participant_ids:
            notify_users(
                db, participant_ids,
                f"{user['name']} đã hủy cuộc họp \u201c{meeting['title']}\u201d (dự kiến {meeting['start_time']}).",
                meeting_id,
            )
        db.commit()
        flash("🚫 Đã hủy cuộc họp. Phòng họp đã được giải phóng và thông báo hủy đã gửi đến người tham gia.", "success")
    return redirect(url_for("meeting_list"))


# ---------- Xác nhận tham gia (US-07) ----------
@app.route("/meetings/<int:meeting_id>/respond", methods=["POST"])
def meeting_respond(meeting_id):
    db = get_db()
    user = current_user()
    response = request.form.get("response")
    meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()

    if not meeting:
        flash("Không tìm thấy cuộc họp.", "danger")
        return redirect(url_for("meeting_list"))
    if meeting["start_time"] < datetime.now().strftime("%Y-%m-%d %H:%M") and meeting["status"] == "active":
        flash("Cuộc họp đã bắt đầu, không thể thay đổi phản hồi.", "danger")
        return redirect(url_for("meeting_list"))
    if response not in ("accepted", "declined"):
        flash("Phản hồi không hợp lệ.", "danger")
        return redirect(url_for("meeting_list"))

    db.execute(
        "UPDATE meeting_participants SET response = ? WHERE meeting_id = ? AND employee_id = ?",
        (response, meeting_id, user["id"]),
    )
    label = "Đồng ý" if response == "accepted" else "Từ chối"
    notify_users(
        db, [meeting["creator_id"]],
        f"{user['name']} đã phản hồi \u201c{label}\u201d cho lời mời họp \u201c{meeting['title']}\u201d.",
        meeting_id,
    )
    db.commit()
    flash(f"Bạn đã phản hồi: {label}.", "success")
    return redirect(url_for("meeting_list"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
