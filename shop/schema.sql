-- Cấu trúc cơ sở dữ liệu của shop bán video.
-- Mọi thời gian lưu theo giờ UTC dạng 'YYYY-MM-DD HH:MM:SS'; khi hiển thị mới đổi sang giờ Việt Nam.
-- Mọi số tiền lưu bằng SỐ NGUYÊN (đơn vị: đồng), không bao giờ dùng số thực.

CREATE TABLE IF NOT EXISTS videos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    price         INTEGER NOT NULL CHECK (price > 0),
    preview_file  TEXT,                       -- file xem thử (công khai)
    original_file TEXT    NOT NULL,           -- file gốc (bí mật, chỉ tải qua link ký số)
    is_active     INTEGER NOT NULL DEFAULT 1, -- 1 = đang bán, 0 = ẩn
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_code        TEXT    NOT NULL UNIQUE, -- nội dung chuyển khoản, ví dụ DHK7Q2M9XA
    access_token        TEXT    NOT NULL UNIQUE, -- chuỗi bí mật trong link trang đơn hàng
    video_id            INTEGER NOT NULL REFERENCES videos (id),
    amount              INTEGER NOT NULL CHECK (amount > 0), -- giá tại thời điểm đặt (chụp lại)
    status              TEXT    NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'paid', 'cancelled')),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at          TEXT    NOT NULL,        -- hết hạn hiển thị QR
    paid_at             TEXT,
    paid_amount         INTEGER,                 -- số tiền thực nhận
    paid_transaction_id INTEGER REFERENCES bank_transactions (id),
    download_count      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);

-- Nhật ký MỌI webhook tiền vào từ SePay. sepay_id UNIQUE là "khóa chống trùng":
-- SePay gửi lại cùng một giao dịch bao nhiêu lần thì cũng chỉ được ghi một lần.
CREATE TABLE IF NOT EXISTS bank_transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sepay_id         INTEGER NOT NULL UNIQUE,
    gateway          TEXT,
    account_number   TEXT,
    sub_account      TEXT,
    amount           INTEGER NOT NULL,
    content          TEXT,
    code             TEXT,
    reference_code   TEXT,
    transaction_date TEXT,
    order_id         INTEGER REFERENCES orders (id),
    result           TEXT    NOT NULL, -- paid / overpaid / underpaid / duplicate_payment / unmatched / wrong_account
    note             TEXT,
    raw_body         TEXT    NOT NULL,
    received_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_result ON bank_transactions (result);
