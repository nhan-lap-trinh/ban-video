# Quy tắc dự án: Shop bán video AI

## Dự án
- Web bán video AI bằng Python + Flask + SQLite. Gồm trang khách hàng (xem thử, mua, tải) và trang quản lý `/quan-ly` (doanh thu, video, đơn hàng, giao dịch).
- Thanh toán: VietQR, xác nhận tự động qua webhook SePay. Tiền đi thẳng vào tài khoản ngân hàng của chủ shop, SePay chỉ báo tin.
- Logic tiền nằm tập trung trong `shop/payments.py`.

## Cách làm việc
- Chủ dự án là học sinh đang học Python: luôn giải thích bằng tiếng Việt vì sao code hoạt động như vậy.
- Làm từng bước nhỏ, chỉ làm đúng phạm vi được yêu cầu, không tự làm trước các bước sau.
- Giao diện giữ nền trắng chữ đen cho đến khi chủ dự án yêu cầu trang trí.
- Mỗi khi xong một thay đổi: chạy `python -m unittest discover -s tests` (phải OK hết) rồi commit Git, mô tả tiếng Việt không dấu.

## Quy tắc về tiền (không được phá vỡ)
- Giá tiền là số nguyên (đơn vị đồng), không dùng số thực.
- Chỉ webhook đã xác minh (API Key hoặc HMAC) mới được đánh dấu đơn đã thanh toán. Không bao giờ tin dữ liệu từ trình duyệt.
- Phải khớp đúng mã đơn, đúng số tiền, đúng tài khoản nhận. Chống xử lý trùng theo `sepay_id`.
- Mọi giao dịch bất thường phải được GHI LẠI để chủ shop xem, không được âm thầm bỏ qua.
- File video gốc không bao giờ để ở nơi truy cập công khai; chỉ tải qua link ký số có hạn.
- Thêm tính năng liên quan đến tiền thì phải thêm test tương ứng trong `tests/test_shop.py`.

## Bảo mật
- Không bao giờ in, ghi log hay commit nội dung `.env`, API key, secret, mật khẩu.
- Mọi khóa bí mật đọc từ biến môi trường.
- Khi phát triển chỉ dùng SePay Test mode; không trỏ webhook tài khoản thật cho đến khi chủ dự án cho phép.
