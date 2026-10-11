"""Toàn bộ logic liên quan đến TIỀN nằm ở file này.

Gồm 4 phần:
1. Tạo đơn hàng + mã thanh toán ngẫu nhiên khó đoán.
2. Tạo link ảnh QR VietQR.
3. Xác minh webhook đúng là do SePay gửi (API Key hoặc HMAC-SHA256).
4. Xử lý webhook: khớp mã đơn, kiểm tra số tiền, chống xử lý trùng.
5. Link tải video có chữ ký số và hết hạn.
"""

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from datetime import timedelta
from urllib.parse import quote, urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .db import from_db_time, to_db_time, transaction, utc_now

# Bảng chữ cái cho mã thanh toán: bỏ 0/O và 1/I/L để khách gõ tay không nhầm.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_SUFFIX_LENGTH = 8  # 31^8 ≈ 850 tỷ khả năng -> không thể đoán mò

# Các kết quả xử lý giao dịch
PAID = "paid"                      # đúng tiền -> đơn đã trả
OVERPAID = "overpaid"              # dư tiền -> mở khóa hay không tùy STRICT_AMOUNT, luôn cần xem lại
UNDERPAID = "underpaid"            # thiếu tiền -> KHÔNG mở khóa
DUPLICATE_PAYMENT = "duplicate_payment"  # đơn đã trả rồi mà khách chuyển thêm lần nữa
UNMATCHED = "unmatched"            # không tìm thấy mã đơn trong nội dung
WRONG_ACCOUNT = "wrong_account"    # tiền vào tài khoản khác tài khoản bán hàng

NEEDS_REVIEW = (OVERPAID, UNDERPAID, DUPLICATE_PAYMENT, UNMATCHED, WRONG_ACCOUNT)


# ---------------------------------------------------------------------------
# 1. Tạo đơn hàng
# ---------------------------------------------------------------------------

def new_payment_code(prefix):
    suffix = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_SUFFIX_LENGTH))
    return prefix + suffix


def create_order(db, video, config):
    """Tạo đơn mới cho một video. Giá được CHỤP LẠI vào đơn, để nếu sau này
    bạn đổi giá video thì đơn đang chờ vẫn giữ đúng số tiền khách đã thấy."""
    now = utc_now()
    expires = now + timedelta(minutes=config["ORDER_EXPIRE_MINUTES"])
    for _ in range(10):  # trùng mã là cực hiếm, nhưng vẫn thử lại cho chắc
        code = new_payment_code(config["PAYMENT_PREFIX"])
        token = secrets.token_urlsafe(24)
        try:
            with transaction(db):
                cur = db.execute(
                    "INSERT INTO orders (payment_code, access_token, video_id, amount,"
                    " created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (code, token, video["id"], video["price"], to_db_time(now), to_db_time(expires)),
                )
            return db.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("Không tạo được mã thanh toán duy nhất")


def order_display_status(order):
    """'paid' | 'pending' | 'expired' | 'cancelled'.
    'expired' không lưu trong DB mà tính ra: đơn chưa trả và đã quá hạn."""
    if order["status"] == "pending" and utc_now() > from_db_time(order["expires_at"]):
        return "expired"
    return order["status"]


# ---------------------------------------------------------------------------
# 2. Link ảnh QR
# ---------------------------------------------------------------------------

def qr_image_url(config, amount, content):
    """Ảnh QR theo chuẩn VietQR (dịch vụ của SePay). App ngân hàng quét sẽ
    điền sẵn số tài khoản, số tiền và nội dung chuyển khoản."""
    # Cùng định dạng với mã nhúng trên trang "Tạo QR" của SePay (my.sepay.vn/createqr),
    # chỉ thêm 2 tham số thay đổi theo từng đơn: amount (số tiền) và des (mã đơn).
    params = {
        "bank": config["BANK_CODE"],
        "acc": config["BANK_ACCOUNT_NUMBER"],
        "template": "compact",
        "amount": amount,
        "des": content,
    }
    if config["BANK_ACCOUNT_NAME"]:
        params["showinfo"] = "true"
        params["holder"] = config["BANK_ACCOUNT_NAME"]
    query = urlencode(params, quote_via=quote)  # quote: dấu cách thành %20 giống link của SePay
    return f"{config['QR_IMAGE_BASE']}?{query}"


# ---------------------------------------------------------------------------
# 3. Xác minh webhook
# ---------------------------------------------------------------------------

def verify_webhook(config, headers, raw_body):
    """Trả về True nếu request đúng là SePay gửi. Thiếu cấu hình -> luôn từ chối
    (nguyên tắc "fail closed": không chắc thì không cho qua)."""
    mode = config["SEPAY_AUTH_MODE"]

    if mode == "apikey":
        key = config["SEPAY_API_KEY"]
        if not key:
            return False
        expected = f"Apikey {key}"
        received = headers.get("Authorization", "")
        # compare_digest so sánh mất thời gian như nhau dù sai ở ký tự nào,
        # để kẻ tấn công không thể đo thời gian phản hồi mà đoán dần khóa.
        return hmac.compare_digest(expected.encode(), received.encode())

    if mode == "hmac":
        secret = config["SEPAY_WEBHOOK_SECRET"]
        if not secret:
            return False
        signature = headers.get("X-SePay-Signature", "")
        timestamp = headers.get("X-SePay-Timestamp", "")
        if not timestamp.isdigit():
            return False
        # Chống "replay": kẻ xấu chép lại một webhook cũ rồi gửi lại.
        if abs(time.time() - int(timestamp)) > 300:
            return False
        message = timestamp.encode() + b"." + raw_body
        expected = "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected.encode(), signature.encode())

    return False


# ---------------------------------------------------------------------------
# 4. Xử lý webhook
# ---------------------------------------------------------------------------

class InvalidPayload(ValueError):
    pass


def _as_int(value, field):
    # bool là con của int trong Python, phải loại riêng
    if isinstance(value, bool):
        raise InvalidPayload(f"{field} không hợp lệ")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise InvalidPayload(f"{field} không hợp lệ")


def parse_payload(raw_body):
    try:
        data = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidPayload("Body không phải JSON") from exc
    if not isinstance(data, dict):
        raise InvalidPayload("Body phải là object JSON")
    sepay_id = _as_int(data.get("id"), "id")
    amount = _as_int(data.get("transferAmount"), "transferAmount")
    if amount <= 0:
        raise InvalidPayload("transferAmount phải > 0")
    return data, sepay_id, amount


def find_order_candidates(data, prefix):
    """Danh sách mã đơn có thể có trong giao dịch, theo thứ tự ưu tiên:
    trường `code` SePay đã bóc sẵn, rồi tới các chuỗi khớp mẫu trong nội dung."""
    candidates = []
    code = data.get("code")
    if isinstance(code, str) and code.strip():
        candidates.append(code.strip().upper())
    text = " ".join(str(data.get(k) or "") for k in ("content", "description")).upper()
    # (?=...) cho phép tìm các vị trí chồng lấn, phòng trường hợp ngân hàng dính chữ
    pattern = rf"(?={re.escape(prefix)}([{CODE_ALPHABET}]{{{CODE_SUFFIX_LENGTH}}}))"
    for suffix in re.findall(pattern, text):
        candidates.append(prefix + suffix)
    seen, unique = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def process_webhook(db, config, raw_body):
    """Xử lý một webhook ĐÃ được xác minh. Trả về (kết quả, ghi chú).

    Toàn bộ chạy trong một transaction: ghi nhật ký giao dịch và cập nhật đơn
    hoặc cùng thành công, hoặc cùng bị hủy.
    """
    data, sepay_id, amount = parse_payload(raw_body)

    # Chỉ quan tâm tiền VÀO. Tiền ra khỏi tài khoản thì bỏ qua, không lưu.
    if data.get("transferType") != "in":
        return "ignored", "Không phải giao dịch tiền vào"

    prefix = config["PAYMENT_PREFIX"]
    raw_text = raw_body.decode("utf-8", errors="replace")

    with transaction(db):
        # Chống trùng: SePay có thể gửi lại cùng giao dịch (retry). Đã có thì thôi.
        if db.execute("SELECT 1 FROM bank_transactions WHERE sepay_id = ?", (sepay_id,)).fetchone():
            return "duplicate_webhook", "Giao dịch này đã xử lý trước đó"

        result, note, order = None, None, None

        # Kiểm tra tiền có vào đúng tài khoản bán hàng không
        expected_acc = config["BANK_ACCOUNT_NUMBER"]
        accounts = {str(data.get("accountNumber") or ""), str(data.get("subAccount") or "")}
        if expected_acc and expected_acc not in accounts:
            result, note = WRONG_ACCOUNT, "Tiền vào tài khoản khác tài khoản bán hàng"
        else:
            for code in find_order_candidates(data, prefix):
                order = db.execute(
                    "SELECT * FROM orders WHERE payment_code = ?", (code,)
                ).fetchone()
                if order:
                    break
            if order is None:
                result, note = UNMATCHED, "Không tìm thấy mã đơn trong nội dung chuyển khoản"
            elif order["status"] == "paid":
                result, note = DUPLICATE_PAYMENT, "Đơn đã thanh toán trước đó, khách chuyển thêm"
            elif order["status"] != "pending":
                result, note = UNMATCHED, f"Đơn đang ở trạng thái {order['status']}"
            elif amount < order["amount"]:
                result = UNDERPAID
                note = f"Thiếu {order['amount'] - amount:,} đ".replace(",", ".")
            elif amount > order["amount"] and config["STRICT_AMOUNT"]:
                # Chế độ "đúng tuyệt đối": dư tiền cũng KHÔNG mở khóa, chủ shop xử lý hoàn tiền
                result = OVERPAID
                note = f"Dư {amount - order['amount']:,} đ - chưa mở khóa (chế độ đúng tuyệt đối)".replace(",", ".")
            else:
                result = PAID if amount == order["amount"] else OVERPAID
                if amount > order["amount"]:
                    note = f"Dư {amount - order['amount']:,} đ - đã mở khóa".replace(",", ".")
                if utc_now() > from_db_time(order["expires_at"]):
                    note = ((note + "; ") if note else "") + "Thanh toán sau khi đơn hết hạn (vẫn chấp nhận)"

        cur = db.execute(
            "INSERT INTO bank_transactions (sepay_id, gateway, account_number, sub_account,"
            " amount, content, code, reference_code, transaction_date, order_id, result, note,"
            " raw_body, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sepay_id,
                data.get("gateway"),
                data.get("accountNumber"),
                data.get("subAccount"),
                amount,
                data.get("content"),
                data.get("code"),
                data.get("referenceCode"),
                data.get("transactionDate"),
                order["id"] if order else None,
                result,
                note,
                raw_text,
                to_db_time(utc_now()),
            ),
        )

        unlock = result == PAID or (result == OVERPAID and not config["STRICT_AMOUNT"])
        if unlock:
            # Điều kiện "status = 'pending'" ngay trong câu UPDATE là chốt an toàn cuối:
            # chỉ đổi được từ chưa trả -> đã trả đúng một lần.
            updated = db.execute(
                "UPDATE orders SET status = 'paid', paid_at = ?, paid_amount = ?,"
                " paid_transaction_id = ? WHERE id = ? AND status = 'pending'",
                (to_db_time(utc_now()), amount, cur.lastrowid, order["id"]),
            ).rowcount
            if updated != 1:
                raise RuntimeError("Trạng thái đơn thay đổi bất thường")

    return result, note


# ---------------------------------------------------------------------------
# 5. Link tải có chữ ký
# ---------------------------------------------------------------------------

def _serializer(config):
    return URLSafeTimedSerializer(config["SECRET_KEY"], salt="download-link")


def make_download_token(config, order):
    return _serializer(config).dumps({"o": order["id"], "t": order["access_token"][:8]})


def read_download_token(config, token):
    """Trả về (order_id, phần đầu access_token) hoặc None nếu link giả/hết hạn."""
    try:
        data = _serializer(config).loads(token, max_age=config["DOWNLOAD_LINK_SECONDS"])
    except (SignatureExpired, BadSignature):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("o"), int):
        return None
    return data["o"], data.get("t")
