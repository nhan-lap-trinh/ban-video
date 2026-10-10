"""Giả lập SePay gửi webhook vào web đang chạy trên máy bạn (không cần SePay thật).

Ví dụ (mở một cửa sổ lệnh khác trong khi `python app.py` đang chạy):

    python scripts/gia_lap_webhook.py DHABCD2345 50000
    python scripts/gia_lap_webhook.py DHABCD2345 30000        # thử chuyển thiếu
    python scripts/gia_lap_webhook.py DHABCD2345 50000 --id 777 # gửi lại cùng id để thử chống trùng
    python scripts/gia_lap_webhook.py DHABCD2345 50000 --sai-khoa # thử webhook giả mạo

Script đọc khóa từ .env và ký request y hệt cách SePay làm.
"""

import argparse
import hashlib
import hmac
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ma_don", help="Mã thanh toán hiện trên trang đơn hàng, ví dụ DHABCD2345")
    p.add_argument("so_tien", type=int, help="Số tiền chuyển (đồng)")
    p.add_argument("--id", type=int, default=None, help="ID giao dịch SePay (mặc định ngẫu nhiên)")
    p.add_argument("--url", default="http://127.0.0.1:5000/webhook/sepay")
    p.add_argument("--sai-khoa", action="store_true", help="Cố tình dùng khóa sai để thử chặn giả mạo")
    args = p.parse_args()

    payload = {
        "gateway": os.environ.get("BANK_CODE", "MBBank"),
        "transactionDate": time.strftime("%Y-%m-%d %H:%M:%S"),
        "accountNumber": os.environ.get("BANK_ACCOUNT_NUMBER", ""),
        "subAccount": None,
        "code": None,  # để trống: buộc web tự tìm mã trong nội dung, giống trường hợp khó nhất
        "content": f"{args.ma_don} thanh toan video",
        "transferType": "in",
        "description": "GIA LAP chuyen tien",
        "transferAmount": args.so_tien,
        "referenceCode": f"FT{random.randint(10**9, 10**10 - 1)}",
        "accumulated": 0,
        "id": args.id if args.id is not None else random.randint(10**6, 10**9),
    }
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}

    mode = os.environ.get("SEPAY_AUTH_MODE", "apikey").strip().lower()
    if mode == "hmac":
        secret = os.environ.get("SEPAY_WEBHOOK_SECRET", "")
        if args.sai_khoa:
            secret += "x"
        ts = str(int(time.time()))
        sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        headers["X-SePay-Timestamp"] = ts
        headers["X-SePay-Signature"] = "sha256=" + sig
    else:
        key = os.environ.get("SEPAY_API_KEY", "")
        if args.sai_khoa:
            key += "x"
        headers["Authorization"] = f"Apikey {key}"

    req = urllib.request.Request(args.url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(resp.status, resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.code, exc.read().decode())
    except urllib.error.URLError as exc:
        print("Không kết nối được tới web. Bạn đã chạy `python app.py` chưa?", exc)
        sys.exit(1)
    print("ID giao dịch đã gửi:", payload["id"])


if __name__ == "__main__":
    main()
