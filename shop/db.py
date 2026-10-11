"""Kết nối cơ sở dữ liệu SQLite.

Mỗi request mở một kết nối riêng (lưu trong `g`) và đóng khi request kết thúc.
Kết nối chạy ở chế độ autocommit (isolation_level=None); khi cần ghi nhiều câu lệnh
"cùng sống cùng chết" thì dùng `with transaction(db):` để bọc lại.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app, g

VN_TZ = timezone(timedelta(hours=7))  # Việt Nam không có giờ mùa hè nên cố định UTC+7
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def utc_now():
    return datetime.now(timezone.utc)


def to_db_time(dt):
    """datetime -> chuỗi UTC để lưu vào DB."""
    return dt.astimezone(timezone.utc).strftime(TIME_FORMAT)


def from_db_time(text):
    """Chuỗi UTC trong DB -> datetime có múi giờ."""
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc)


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction(db):
    """Bọc một nhóm câu lệnh ghi.

    BEGIN IMMEDIATE khóa quyền ghi ngay từ đầu, nên nếu hai webhook đến cùng lúc,
    cái thứ hai phải đợi cái thứ nhất xong rồi mới đọc dữ liệu. Nhờ vậy không có chuyện
    cả hai cùng thấy đơn "chưa trả" rồi cùng đánh dấu "đã trả".
    Có lỗi giữa chừng thì ROLLBACK: hoặc ghi hết, hoặc không ghi gì.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def init_db(path):
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(schema)
        # Database cũ (tạo trước khi có cột mới) -> thêm cột còn thiếu
        cols = {row[1] for row in conn.execute("PRAGMA table_info(videos)")}
        for col in ("loop_file", "poster_file"):
            if col not in cols:
                conn.execute(f"ALTER TABLE videos ADD COLUMN {col} TEXT")
    finally:
        conn.close()
