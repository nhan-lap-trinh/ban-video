"""Trang QUẢN LÝ (chỉ chủ shop): đăng nhập, doanh thu, video, đơn hàng, giao dịch."""

import secrets
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from . import payments
from .db import VN_TZ, get_db, transaction, utc_now
from .security import admin_required, check_admin_credentials

bp = Blueprint("admin", __name__)  # đường dẫn gốc lấy từ ADMIN_PATH khi đăng ký

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
TEST_EXTENSIONS = {".txt"}  # chỉ cho phép khi ALLOW_TEST_FILES bật
MIN_PRICE, MAX_PRICE = 1_000, 100_000_000


# ---------------------------------------------------------------------------
# Đăng nhập / đăng xuất
# ---------------------------------------------------------------------------

@bp.route("/dang-nhap", methods=["GET", "POST"])
def login():
    throttle = current_app.extensions["login_throttle"]
    ip = request.remote_addr or "?"
    error = None
    if request.method == "POST":
        if throttle.is_blocked(ip):
            error = "Sai quá nhiều lần. Vui lòng thử lại sau 15 phút."
        elif check_admin_credentials(
            current_app.config, request.form.get("username", ""), request.form.get("password", "")
        ):
            throttle.reset(ip)
            session.clear()  # tạo phiên mới hoàn toàn sau khi đăng nhập
            session["is_admin"] = True
            next_url = request.args.get("next", "")
            # chỉ cho chuyển hướng trong trang quản lý, chặn chuyển sang web lạ
            admin_root = current_app.config["ADMIN_PATH"] + "/"
            if not (next_url == current_app.config["ADMIN_PATH"] or next_url.startswith(admin_root)) \
                    or next_url.startswith("//"):
                next_url = url_for("admin.dashboard")
            return redirect(next_url)
        else:
            throttle.record_fail(ip)
            error = "Sai tên đăng nhập hoặc mật khẩu."
    return render_template("admin/login.html", error=error), (401 if error else 200)


@bp.route("/dang-xuat", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("store.index"))


# ---------------------------------------------------------------------------
# Tổng quan doanh thu
# ---------------------------------------------------------------------------

@bp.route("/")
@admin_required
def dashboard():
    db = get_db()
    now_vn = utc_now().astimezone(VN_TZ)
    today = now_vn.strftime("%Y-%m-%d")
    month = now_vn.strftime("%Y-%m")

    def revenue(where, params=()):
        row = db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(paid_amount), 0) AS total FROM orders"
            " WHERE status = 'paid' " + where,
            params,
        ).fetchone()
        return row["n"], row["total"]

    # date(paid_at, '+7 hours') = ngày theo giờ Việt Nam
    stats = {
        "today": revenue("AND date(paid_at, '+7 hours') = ?", (today,)),
        "month": revenue("AND strftime('%Y-%m', paid_at, '+7 hours') = ?", (month,)),
        "all": revenue(""),
    }
    placeholders = ",".join("?" * len(payments.NEEDS_REVIEW))
    review_count = db.execute(
        f"SELECT COUNT(*) FROM bank_transactions WHERE result IN ({placeholders})",
        payments.NEEDS_REVIEW,
    ).fetchone()[0]
    daily = db.execute(
        "SELECT date(paid_at, '+7 hours') AS day, COUNT(*) AS n, SUM(paid_amount) AS total"
        " FROM orders WHERE status = 'paid' GROUP BY day ORDER BY day DESC LIMIT 14"
    ).fetchall()
    return render_template(
        "admin/dashboard.html", stats=stats, review_count=review_count, daily=daily
    )


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

def _extension(file_storage):
    return Path(secure_filename(file_storage.filename or "")).suffix.lower()


def _save_upload(file_storage, folder):
    """Lưu file với tên ngẫu nhiên, để không ai đoán được tên file gốc."""
    name = secrets.token_hex(16) + _extension(file_storage)
    file_storage.save(Path(folder) / name)
    return name


@bp.route("/video", methods=["GET", "POST"])
@admin_required
def videos():
    db = get_db()
    errors = []
    original_exts = set(VIDEO_EXTENSIONS)
    if current_app.config["ALLOW_TEST_FILES"]:
        original_exts |= TEST_EXTENSIONS
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price_text = request.form.get("price", "").strip().replace(".", "").replace(",", "")
        preview = request.files.get("preview_file")
        original = request.files.get("original_file")
        has_preview = bool(preview and preview.filename)

        if not title:
            errors.append("Chưa nhập tên video.")
        if not price_text.isdigit():
            errors.append("Giá phải là số nguyên (đơn vị đồng), ví dụ 50000.")
        elif not MIN_PRICE <= int(price_text) <= MAX_PRICE:
            errors.append("Giá phải từ 1.000 đ đến 100.000.000 đ.")
        if not original or not original.filename:
            errors.append("Chưa chọn file gốc.")
        elif _extension(original) not in original_exts:
            errors.append("File gốc chỉ nhận: " + ", ".join(sorted(original_exts)))
        if has_preview and _extension(preview) not in VIDEO_EXTENSIONS:
            errors.append("File xem thử chỉ nhận video: " + ", ".join(sorted(VIDEO_EXTENSIONS)))

        # Kiểm tra hết rồi mới lưu file, để không để lại file rác khi form có lỗi
        if not errors:
            original_name = _save_upload(original, current_app.config["ORIGINAL_DIR"])
            preview_name = (
                _save_upload(preview, current_app.config["PREVIEW_DIR"]) if has_preview else None
            )
            with transaction(db):
                db.execute(
                    "INSERT INTO videos (title, description, price, preview_file, original_file)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (title, description, int(price_text), preview_name, original_name),
                )
            flash(f"Đã thêm sản phẩm: {title}")
            return redirect(url_for("admin.videos"))

    rows = db.execute(
        "SELECT v.*, (SELECT COUNT(*) FROM orders o WHERE o.video_id = v.id AND o.status = 'paid')"
        " AS sold FROM videos v ORDER BY v.id DESC"
    ).fetchall()
    return render_template("admin/videos.html", videos=rows, errors=errors), (400 if errors else 200)


@bp.route("/video/<int:video_id>/bat-tat", methods=["POST"])
@admin_required
def toggle_video(video_id):
    db = get_db()
    with transaction(db):
        changed = db.execute(
            "UPDATE videos SET is_active = 1 - is_active WHERE id = ?", (video_id,)
        ).rowcount
    if not changed:
        abort(404)
    return redirect(url_for("admin.videos"))


# ---------------------------------------------------------------------------
# Đơn hàng và giao dịch ngân hàng
# ---------------------------------------------------------------------------

@bp.route("/don-hang")
@admin_required
def orders():
    rows = get_db().execute(
        "SELECT o.*, v.title AS video_title FROM orders o JOIN videos v ON v.id = o.video_id"
        " ORDER BY o.id DESC LIMIT 300"
    ).fetchall()
    items = [(row, payments.order_display_status(row)) for row in rows]
    return render_template("admin/orders.html", items=items)


@bp.route("/giao-dich")
@admin_required
def transactions():
    only_review = request.args.get("can-xem") == "1"
    sql = (
        "SELECT t.*, o.payment_code FROM bank_transactions t"
        " LEFT JOIN orders o ON o.id = t.order_id"
    )
    params = ()
    if only_review:
        sql += " WHERE t.result IN (" + ",".join("?" * len(payments.NEEDS_REVIEW)) + ")"
        params = payments.NEEDS_REVIEW
    sql += " ORDER BY t.id DESC LIMIT 300"
    rows = get_db().execute(sql, params).fetchall()
    return render_template(
        "admin/transactions.html",
        rows=rows,
        only_review=only_review,
        needs_review=set(payments.NEEDS_REVIEW),
    )
