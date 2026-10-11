"""Khởi tạo ứng dụng Flask: đọc cấu hình, nối database, đăng ký các trang."""

import os
import re
import secrets
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from . import db as dbmod
from .db import VN_TZ, from_db_time
from .security import LoginThrottle, check_csrf, csrf_token

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_int(name, default):
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def load_config():
    load_dotenv(BASE_DIR / ".env")
    data_dir = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
    production = os.environ.get("PRODUCTION") == "1"
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY", ""),
        "PRODUCTION": production,
        "DATABASE": str(data_dir / "shop.db"),
        "PREVIEW_DIR": str(data_dir / "preview"),     # file xem thử: được phép công khai
        "ORIGINAL_DIR": str(data_dir / "originals"),  # file gốc: KHÔNG bao giờ công khai
        "ADMIN_USERNAME": os.environ.get("ADMIN_USERNAME", ""),
        "ADMIN_PASSWORD_HASH": os.environ.get("ADMIN_PASSWORD_HASH", ""),
        # Cách đơn giản cho Render: đặt mật khẩu thường, web tự băm khi khởi động
        "ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD", ""),
        # Cho phép bán file .txt để test (mặc định: được khi chạy trên máy, không được khi chạy thật)
        "ALLOW_TEST_FILES": os.environ.get("TEST_FILES") == "1" or not production,
        # Tự tạo sẵn 1 sản phẩm .txt để test nếu shop đang trống (tiện cho Render vì ổ đĩa bị xóa mỗi lần cập nhật)
        "TEST_PRODUCT_PRICE": _env_int("TEST_PRODUCT_PRICE", 0),
        "TEST_PRODUCT_TEXT": os.environ.get("TEST_PRODUCT_TEXT", "Chuc mung! Thanh toan thanh cong."),
        # Chạy sau proxy (Render) thì phải tin header X-Forwarded-* để biết IP và https thật
        "TRUST_PROXY": os.environ.get("TRUST_PROXY") == "1",
        "SEPAY_AUTH_MODE": os.environ.get("SEPAY_AUTH_MODE", "apikey").strip().lower(),
        "SEPAY_API_KEY": os.environ.get("SEPAY_API_KEY", ""),
        "SEPAY_WEBHOOK_SECRET": os.environ.get("SEPAY_WEBHOOK_SECRET", ""),
        "BANK_ACCOUNT_NUMBER": os.environ.get("BANK_ACCOUNT_NUMBER", "").strip(),
        "BANK_CODE": os.environ.get("BANK_CODE", "").strip(),
        "BANK_ACCOUNT_NAME": os.environ.get("BANK_ACCOUNT_NAME", "").strip(),
        # Dịch vụ vẽ ảnh QR của SePay. qr.sepay.vn và vietqr.app là của cùng SePay.
        "QR_IMAGE_BASE": os.environ.get("QR_IMAGE_BASE", "https://vietqr.app/img").strip(),
        # Đường dẫn trang quản lý. Đổi thành chuỗi khó đoán để người lạ không biết trang quản lý ở đâu.
        "ADMIN_PATH": "/" + os.environ.get("ADMIN_PATH", "quan-ly").strip().strip("/"),
        "PAYMENT_PREFIX": os.environ.get("PAYMENT_PREFIX", "DH").strip().upper(),
        "ORDER_EXPIRE_MINUTES": _env_int("ORDER_EXPIRE_MINUTES", 15),
        "DOWNLOAD_LINK_SECONDS": _env_int("DOWNLOAD_LINK_SECONDS", 300),
        "MAX_DOWNLOADS": _env_int("MAX_DOWNLOADS", 5),
        # Link xem thử sống bao lâu (giây). Đủ để xem hết video xem thử, nhưng không dùng lại được lâu.
        "PREVIEW_LINK_SECONDS": _env_int("PREVIEW_LINK_SECONDS", 1800),
        # Chữ chạy trên video xem thử
        "SHOP_NAME": os.environ.get("SHOP_NAME", "").strip(),
        # Chữ trong hoa văn watermark phủ lên video xem thử (mặc định = SHOP_NAME)
        "WATERMARK_TEXT": (os.environ.get("WATERMARK_TEXT") or os.environ.get("SHOP_NAME") or "").strip(),
        # 1 = chỉ mở khóa khi chuyển ĐÚNG số tiền (thiếu hay dư đều không mở khóa)
        "STRICT_AMOUNT": os.environ.get("STRICT_AMOUNT", "1") != "0",
        "MAX_CONTENT_LENGTH": _env_int("MAX_UPLOAD_MB", 2048) * 1024 * 1024,
    }


def validate_config(config):
    problems = []
    if len(config["SECRET_KEY"]) < 32:
        problems.append("SECRET_KEY thiếu hoặc quá ngắn (cần ít nhất 32 ký tự)")
    prefix = config["PAYMENT_PREFIX"]
    if not (2 <= len(prefix) <= 5 and prefix.isalpha() and prefix.isascii()):
        problems.append("PAYMENT_PREFIX phải gồm 2-5 chữ cái (giống cấu hình trên SePay)")
    if config.get("ADMIN_PASSWORD") and len(config["ADMIN_PASSWORD"]) < 12:
        problems.append("ADMIN_PASSWORD phải có ít nhất 12 ký tự")
    if not re.fullmatch(r"/[A-Za-z0-9_-]{3,64}", config.get("ADMIN_PATH", "/quan-ly")):
        problems.append("ADMIN_PATH chỉ gồm chữ không dấu, số, '-' hoặc '_' (3-64 ký tự)")
    if config["SEPAY_AUTH_MODE"] not in ("apikey", "hmac"):
        problems.append("SEPAY_AUTH_MODE chỉ nhận 'apikey' hoặc 'hmac'")
    if problems:
        raise RuntimeError("Cấu hình .env chưa đúng:\n - " + "\n - ".join(problems))


def _seed_test_product(config):
    """Nếu đặt TEST_PRODUCT_PRICE và shop chưa có sản phẩm nào, tạo sẵn 'File test'."""
    price = config.get("TEST_PRODUCT_PRICE") or 0
    if price <= 0:
        return
    conn = dbmod.connect(config["DATABASE"])
    try:
        if conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]:
            return
        name = secrets.token_hex(16) + ".txt"
        (Path(config["ORIGINAL_DIR"]) / name).write_text(config["TEST_PRODUCT_TEXT"] + "\n", encoding="utf-8")
        conn.execute(
            "INSERT INTO videos (title, description, price, original_file) VALUES (?, ?, ?, ?)",
            ("File test", "Sản phẩm tự tạo để test thanh toán", price, name),
        )
    finally:
        conn.close()


def create_app(test_config=None):
    app = Flask(__name__)
    config = load_config()
    if test_config:
        config.update(test_config)
    validate_config(config)
    if config.get("ADMIN_PASSWORD") and not config.get("ADMIN_PASSWORD_HASH"):
        config["ADMIN_PASSWORD_HASH"] = generate_password_hash(config["ADMIN_PASSWORD"])
    config.pop("ADMIN_PASSWORD", None)  # không giữ mật khẩu thường trong bộ nhớ app
    app.config.update(config)
    if config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,      # JavaScript không đọc được cookie phiên
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config["PRODUCTION"],  # chạy thật thì cookie chỉ đi qua HTTPS
    )

    for key in ("PREVIEW_DIR", "ORIGINAL_DIR"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    dbmod.init_db(app.config["DATABASE"])
    _seed_test_product(app.config)

    app.teardown_appcontext(dbmod.close_db)
    app.extensions["login_throttle"] = LoginThrottle()

    from .admin import bp as admin_bp
    from .store import bp as store_bp

    app.register_blueprint(store_bp)
    app.register_blueprint(admin_bp, url_prefix=app.config["ADMIN_PATH"])

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return render_template("error.html", code=exc.code, message=exc.description), exc.code

    # Mọi request POST phải có CSRF token, trừ webhook (SePay không có token,
    # webhook được bảo vệ bằng API Key / HMAC thay thế).
    csrf_exempt = {"store.sepay_webhook"}

    @app.before_request
    def _csrf_protect():
        if request.method == "POST" and request.endpoint not in csrf_exempt:
            check_csrf()

    @app.after_request
    def _security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        # Không gửi địa chỉ trang (có chứa mã bí mật của đơn) sang web khác,
        # ví dụ khi trình duyệt tải ảnh QR từ SePay.
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            # img-src cho phép mọi ảnh https: dịch vụ QR có thể chuyển tiếp sang máy chủ ảnh khác.
            # Ảnh không chạy được mã nên mở rộng chỗ này không ảnh hưởng an toàn.
            "default-src 'self'; img-src 'self' https: data:; "
            "media-src 'self' blob:; "
            "script-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; "
            "base-uri 'none'"
        )
        if config["PRODUCTION"]:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.template_filter("vnd")
    def _vnd(amount):
        if amount is None:
            return ""
        return f"{int(amount):,}".replace(",", ".") + " đ"

    @app.template_filter("vntime")
    def _vntime(text):
        if not text:
            return ""
        return from_db_time(text).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")

    @app.cli.command("init-db")
    def _init_db_cmd():
        """Tạo các bảng trong cơ sở dữ liệu (chạy tự động khi khởi động)."""
        dbmod.init_db(app.config["DATABASE"])
        click.echo("Đã khởi tạo cơ sở dữ liệu.")

    return app
