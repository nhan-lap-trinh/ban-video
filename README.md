# Shop bán video AI — Giai đoạn 1: test thanh toán SePay

Web bán video AI viết bằng **Python + Flask**, giao diện nền trắng chữ đen để test thuật toán.

- **Trang khách hàng**: xem danh sách video, xem thử, bấm **Mua** → hiện mã QR ngân hàng → chuyển khoản → trang tự chuyển sang "Đã thanh toán" → tải video gốc.
- **Trang quản lý** (`/quan-ly`): doanh thu hôm nay / tháng / tổng, thêm video, danh sách đơn hàng, nhật ký giao dịch ngân hàng (đánh dấu rõ giao dịch thiếu tiền, dư tiền, không khớp mã).
- **Webhook SePay** (`/webhook/sepay`): nhận thông báo tiền vào, tự đối chiếu mã đơn và số tiền.

---

## ★ Cách test nhanh nhất: GitHub + Render (không cần chạy lệnh trên máy)

GitHub **lưu code**, Render **chạy code** (máy chủ Python miễn phí). Mỗi lần bạn đưa code mới lên GitHub, Render tự cập nhật web trong vài phút. Bạn chỉ cần mở web bằng Chrome.

1. **GitHub**: tạo repository mới, chọn **Private**. Bấm *Add file → Upload files*, kéo **toàn bộ nội dung** thư mục `ban-video-ai` vào (không kéo `.env`, `.venv`, `data` nếu có) → *Commit changes*.
2. **Render** (render.com): đăng nhập bằng GitHub → *New → Blueprint* → chọn repository vừa tạo. Render đọc file `render.yaml` và hỏi các giá trị:
   - `ADMIN_USERNAME`, `ADMIN_PASSWORD` (≥ 12 ký tự): tài khoản vào trang quản lý
   - `BANK_ACCOUNT_NUMBER`, `BANK_CODE`, `BANK_ACCOUNT_NAME`: tài khoản nhận tiền (đã liên kết SePay)
   - `SEPAY_API_KEY`: chuỗi dài tự đặt, dùng chung với webhook SePay
   - `TEST_PRODUCT_TEXT`: nội dung file `.txt` khách nhận được sau khi trả tiền
   
   Bấm *Apply*. Vài phút sau có địa chỉ dạng `https://ban-video-ai-xxxx.onrender.com`.
3. **SePay** (chế độ thật, tắt Test mode):
   - *Cấu trúc mã thanh toán*: tiền tố `DH`, hậu tố 8–8, **Số và chữ**
   - *Webhook*: URL `https://ban-video-ai-xxxx.onrender.com/webhook/sepay`, tiền vào, xác thực **API Key** = `SEPAY_API_KEY`
4. **Test**: mở địa chỉ Render bằng Chrome → *File test* (5.000 đ, tự tạo sẵn) → **Mua** → dùng tài khoản khác quét QR, chuyển đúng 5.000 đ → trang tự chuyển "Đã thanh toán" → tải file.

Lưu ý gói miễn phí của Render:
- Không có ai vào web 15 phút thì máy chủ "ngủ", lần mở tiếp theo mất khoảng 1 phút để thức dậy. **Hãy mở trang web trước rồi mới chuyển tiền** (trang đơn hàng tự hỏi trạng thái mỗi 3 giây nên máy chủ không ngủ khi đang chờ).
- Ổ đĩa bị **xóa sạch** mỗi lần cập nhật code hoặc khởi động lại: đơn hàng và giao dịch cũ mất (sản phẩm *File test* thì tự tạo lại). Chấp nhận được khi test; khi chạy thật sẽ chuyển sang database bền vững.
- Doanh thu thật luôn kiểm tra bằng **sao kê ngân hàng**.

---

## 1. Cấu trúc thư mục

```
ban-video-ai/
├── app.py                  ← chạy file này để mở web
├── requirements.txt        ← danh sách thư viện
├── render.yaml             ← cấu hình để Render tự chạy web từ GitHub
├── .env.example            ← file mẫu cấu hình (file .env thật KHÔNG được đưa lên GitHub)
├── shop/
│   ├── __init__.py         ← khởi tạo app, đọc cấu hình, lớp bảo vệ chung
│   ├── payments.py         ← ★ TOÀN BỘ LOGIC TIỀN: tạo đơn, QR, xác minh + xử lý webhook, link tải
│   ├── store.py            ← các trang khách hàng + địa chỉ webhook
│   ├── admin.py            ← các trang quản lý
│   ├── security.py         ← chống giả mạo form (CSRF), đăng nhập admin, chặn dò mật khẩu
│   ├── db.py               ← kết nối cơ sở dữ liệu
│   ├── schema.sql          ← cấu trúc các bảng
│   ├── templates/          ← giao diện HTML
│   └── static/order.js     ← tự kiểm tra trạng thái đơn mỗi 3 giây
├── scripts/
│   ├── thiet_lap.py        ← tạo file .env lần đầu (khóa bí mật + tài khoản admin)
│   └── gia_lap_webhook.py  ← giả lập SePay gửi webhook để test trên máy
├── tests/test_shop.py      ← 67 bài test tự động cho các tình huống tiền
└── data/                   ← (tự tạo khi chạy) database + file video. KHÔNG đưa lên GitHub
```

---

## 2. Chạy trên Windows

Mở **Command Prompt**, rồi:

```bat
cd C:\Projects\ban-video-ai
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts\thiet_lap.py
```

`thiet_lap.py` hỏi tên đăng nhập và mật khẩu admin (ít nhất 12 ký tự), rồi tạo file `.env`.

Mở file `.env` bằng VS Code và điền thông tin **tài khoản ngân hàng nhận tiền**:

```
BANK_ACCOUNT_NUMBER=số tài khoản của bạn
BANK_CODE=MBBank          (tên ngắn ngân hàng: MBBank, Vietcombank, ACB, TPBank, VPBank, BIDV...)
BANK_ACCOUNT_NAME=VO TRONG NHAN
SEPAY_API_KEY=đặt một chuỗi dài, ngẫu nhiên (dùng chung với SePay ở bước 4)
```

Chạy web:

```bat
python app.py
```

- Trang khách hàng: http://127.0.0.1:5000
- Trang quản lý: http://127.0.0.1:5000/quan-ly → đăng nhập → mục **Video** → thêm video đầu tiên.

Mỗi lần mở cửa sổ lệnh mới, nhớ chạy lại `.venv\Scripts\activate` trước.

---

## 3. Test thanh toán KHÔNG cần SePay (giả lập)

1. Ở trang khách hàng, chọn video → bấm **Mua** → ghi lại **mã thanh toán** (ví dụ `DHBA5HM5KM`). Để nguyên trang đó.
2. Mở **cửa sổ lệnh thứ hai**, activate `.venv`, rồi thử từng tình huống:

```bat
python scripts\gia_lap_webhook.py DHBA5HM5KM 50000 --sai-khoa   :: webhook giả mạo  -> bị từ chối (401)
python scripts\gia_lap_webhook.py DHBA5HM5KM 20000              :: chuyển thiếu    -> KHÔNG mở khóa
python scripts\gia_lap_webhook.py DHBA5HM5KM 50000 --id 777     :: chuyển đúng     -> trang tự chuyển "Đã thanh toán"
python scripts\gia_lap_webhook.py DHBA5HM5KM 50000 --id 777     :: gửi lại cùng id -> không xử lý lần 2
```

3. Vào **Quản lý → Giao dịch** để xem từng giao dịch đã được phân loại thế nào.

---

## 4. Test với SePay thật (Test mode)

SePay cần gọi được tới web của bạn qua **Internet**, nhưng web đang chạy ở `127.0.0.1` (chỉ máy bạn thấy). Dùng **Cloudflare Tunnel** để tạm mở một đường hầm:

```bat
winget install Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:5000
```

Nó in ra một địa chỉ dạng `https://abc-xyz.trycloudflare.com` (đổi mỗi lần chạy).

Trên **my.sepay.vn**, bật **Test mode** (thấy banner vàng), rồi:

1. **Cấu hình mã thanh toán** (trong Test mode): tiền tố `DH`, hậu tố tối thiểu `8`, tối đa `8`, loại ký tự **Số và chữ**.
2. **Webhook → Thêm webhook**:
   - URL: `https://abc-xyz.trycloudflare.com/webhook/sepay`
   - Loại sự kiện: tiền vào
   - Xác thực: **API Key**, dán đúng chuỗi `SEPAY_API_KEY` trong `.env`
3. Tài khoản ngân hàng Test mode: dùng **cùng số tài khoản** với `BANK_ACCOUNT_NUMBER` (web sẽ từ chối tiền vào tài khoản khác).
4. Trên web: bấm **Mua** để lấy mã đơn.
5. SePay → **Giao dịch → Mô phỏng**: số tiền đúng giá, nội dung là mã đơn → bấm Mô phỏng.
6. Trang đơn hàng phải tự chuyển sang "Đã thanh toán" trong vài giây. Kiểm tra **Lịch sử gửi** của webhook trên SePay phải báo thành công.

Khi chạy thật, nên chuyển sang **HMAC-SHA256** (an toàn hơn): trên SePay chọn HMAC, rồi trong `.env` đặt `SEPAY_AUTH_MODE=hmac` và `SEPAY_WEBHOOK_SECRET=<secret của SePay>`.

---

## 5. Chạy test tự động

```bat
python -m unittest discover -s tests -v
```

67 bài test kiểm tra: webhook giả mạo, chữ ký HMAC sai / bị sửa / quá cũ, chuyển đúng / thiếu / dư, webhook gửi trùng, khách chuyển 2 lần, sai tài khoản nhận, trả tiền sau khi đơn hết hạn, đổi giá khi đơn đang chờ, link tải giả / hết hạn / hết lượt, chặn lấy file gốc qua đường dẫn lạ, đăng nhập admin, chặn dò mật khẩu...

**Mỗi lần sửa code liên quan đến tiền, chạy lại lệnh này. Tất cả phải OK.**

---

## 6. Quy tắc an toàn đã cài sẵn

| Quy tắc | Ở đâu |
|---|---|
| Chỉ webhook đã xác minh mới được đánh dấu "đã thanh toán"; trình duyệt chỉ được HỎI trạng thái | `store.py`, `payments.py` |
| Mã thanh toán ngẫu nhiên 8 ký tự (~850 tỷ khả năng), không đoán được | `payments.new_payment_code` |
| Giá lưu bằng số nguyên (đồng), chụp lại vào đơn lúc đặt | `schema.sql`, `create_order` |
| Chống xử lý trùng bằng `sepay_id` UNIQUE + khóa ghi `BEGIN IMMEDIATE` | `process_webhook` |
| Thiếu tiền → không mở khóa; dư / trùng / sai tài khoản → mở khóa hoặc không tùy trường hợp, nhưng luôn **ghi lại để bạn xem** | `process_webhook` |
| File gốc nằm thư mục riêng, tên ngẫu nhiên, chỉ tải qua link ký số sống 5 phút, tối đa 5 lượt | `store.download_file` |
| Không gửi địa chỉ trang đơn hàng sang web khác (Referrer-Policy) | `__init__.py` |
| Thiếu cấu hình khóa → webhook từ chối tất cả ("fail closed") | `verify_webhook` |

---

## 7. Lưu ý về GitHub và tên miền

- **GitHub** dùng để **lưu code** (và quản lý phiên bản). File `.env` và thư mục `data/` đã có trong `.gitignore`, không bao giờ bị đưa lên.
- **GitHub Pages KHÔNG chạy được web này**: GitHub Pages chỉ phát file HTML tĩnh, không chạy được Python, không nhận được webhook và không có database. Vì vậy dùng **Render** (mục ★ ở trên) để chạy. Khi bán thật, có thể gắn tên miền riêng vào Render.

## 8. Chưa làm (các bước sau)

- Nút xác nhận tay / ghi chú cho giao dịch "cần xem lại" trong trang quản lý.
- Đối soát định kỳ qua API SePay (phòng khi webhook bị mất).
- Tự tạo bản xem thử có watermark, chất lượng thấp từ file gốc.
- Đưa lên máy chủ thật + HTTPS + tên miền.
- Trang trí giao diện.

## Trang quản lý tách riêng

- Trang khách hàng **không có bất kỳ đường dẫn nào** tới trang quản lý, kể cả khi trình duyệt đang đăng nhập admin.
- Trang quản lý dùng giao diện riêng (`templates/admin/base_admin.html`), có chữ **TRANG QUẢN LÝ** ở đầu.
- Muốn giấu địa chỉ trang quản lý: thêm biến môi trường `ADMIN_PATH` (ví dụ `ADMIN_PATH=nhan-admin-7k2p`), khi đó trang quản lý ở `/nhan-admin-7k2p` và `/quan-ly` trả về 404.

## Video xem thử: các lớp "gây khó"

Không lớp nào chặn được quay màn hình tuyệt đối (kể cả DRM kiểu Netflix cũng không chắc chắn trên Chrome máy tính). Mục tiêu là làm khó và làm bản quay xấu đi:
- Link xem thử có chữ ký, hết hạn sau `PREVIEW_LINK_SECONDS` (mặc định 30 phút).
- Trình phát không có nút tải, chặn chuột phải, chặn cửa sổ nổi (picture-in-picture).
- Hoa văn watermark: lưới hình thoi, xen kẽ hàng "XEM THỬ" và hàng tên thương hiệu `WATERMARK_TEXT`, phủ kín video và trôi chậm.
- Thanh điều khiển riêng: nút góc phải dưới vừa vào vừa thoát toàn màn hình.
- Chuyển tab / chuyển cửa sổ: video tự dừng và bị che mờ.
- Lớp quan trọng nhất vẫn là: video xem thử có watermark, chất lượng thấp, ngắn; video gốc không bao giờ phát trên web.

## Giao diện

- `shop/static/theme.css`: màu và kiểu chữ dùng chung (giấy vở, mực tím, bút đỏ cho giá tiền, xanh lá khi xong).
- `shop/static/store.css`: trang khách hàng. `shop/static/admin.css`: trang quản lý.
- Font: Be Vietnam Pro (chữ thường) và Dancing Script (chữ "Thầy cô Ơi!"), tải từ Google Fonts.
