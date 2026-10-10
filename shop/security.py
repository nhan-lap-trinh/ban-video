"""Các lớp bảo vệ chung: chống giả mạo form (CSRF), đăng nhập admin, chặn dò mật khẩu."""

import hmac
import secrets
import time
from functools import wraps

from flask import abort, redirect, request, session, url_for
from werkzeug.security import check_password_hash

# ---------------------------------------------------------------------------
# CSRF: một trang web lạ không được phép "bấm hộ" nút trên web của mình.
# Mỗi phiên có một token bí mật; mọi form POST phải gửi kèm token đó.
# ---------------------------------------------------------------------------

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def check_csrf():
    sent = request.form.get("_csrf", "")
    real = session.get("_csrf", "")
    if not real or not hmac.compare_digest(sent.encode(), real.encode()):
        abort(400, description="Phiên làm việc không hợp lệ, hãy tải lại trang rồi thử lại.")


# ---------------------------------------------------------------------------
# Đăng nhập admin
# ---------------------------------------------------------------------------

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def check_admin_credentials(config, username, password):
    expected_user = config["ADMIN_USERNAME"]
    password_hash = config["ADMIN_PASSWORD_HASH"]
    if not expected_user or not password_hash:
        return False  # chưa cấu hình admin -> không ai đăng nhập được
    user_ok = hmac.compare_digest(username.encode(), expected_user.encode())
    # Luôn kiểm tra mật khẩu kể cả khi sai tên, để thời gian phản hồi như nhau
    try:
        pass_ok = check_password_hash(password_hash, password)
    except ValueError:
        return False
    return user_ok and pass_ok


class LoginThrottle:
    """Sai mật khẩu quá MAX_FAILS lần trong WINDOW giây thì khóa tạm IP đó.
    Lưu trong bộ nhớ: đủ cho server chạy 1 tiến trình ở giai đoạn này."""

    MAX_FAILS = 5
    WINDOW = 15 * 60

    def __init__(self):
        self._fails = {}

    def _recent(self, key):
        now = time.time()
        recent = [t for t in self._fails.get(key, []) if now - t < self.WINDOW]
        self._fails[key] = recent
        return recent

    def is_blocked(self, key):
        return len(self._recent(key)) >= self.MAX_FAILS

    def record_fail(self, key):
        self._recent(key).append(time.time())

    def reset(self, key):
        self._fails.pop(key, None)
