"""Chạy MỘT LẦN đầu tiên: tạo file .env với khóa bí mật ngẫu nhiên và tài khoản admin.

    python scripts/thiet_lap.py

Các thông tin ngân hàng và SePay bạn tự điền thêm vào .env sau (xem README).
"""

import getpass
import secrets
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

BASE = Path(__file__).resolve().parent.parent
ENV = BASE / ".env"
EXAMPLE = BASE / ".env.example"


def main():
    if ENV.exists():
        print("Đã có file .env. Nếu muốn làm lại, hãy xóa/đổi tên file .env cũ trước.")
        sys.exit(1)

    username = input("Tên đăng nhập admin: ").strip()
    if not username:
        print("Tên đăng nhập không được để trống.")
        sys.exit(1)
    while True:
        password = getpass.getpass("Mật khẩu admin (ít nhất 12 ký tự, gõ sẽ không hiện): ")
        if len(password) < 12:
            print("Mật khẩu quá ngắn, hãy dùng ít nhất 12 ký tự.")
            continue
        if password != getpass.getpass("Nhập lại mật khẩu: "):
            print("Hai lần nhập không giống nhau, thử lại.")
            continue
        break

    values = {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "ADMIN_USERNAME": username,
        # Chỉ lưu bản BĂM của mật khẩu, không lưu mật khẩu thật.
        # Đặt trong dấu nháy đơn vì chuỗi băm có ký tự '$'.
        "ADMIN_PASSWORD_HASH": "'" + generate_password_hash(password) + "'",
    }
    lines = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip()
        if key in values and not line.lstrip().startswith("#"):
            lines.append(f"{key}={values[key]}")
        else:
            lines.append(line)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Đã tạo file .env. Mở file đó để điền thông tin ngân hàng và SePay (xem README).")


if __name__ == "__main__":
    main()
