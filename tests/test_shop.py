"""Kiểm tra tự động các tình huống liên quan đến tiền.

Chạy:  python -m unittest discover -s tests -v
"""

import hashlib
import hmac
import io
import json
import re
import shutil
import tempfile
import time
import unittest
import warnings
from pathlib import Path

from werkzeug.security import generate_password_hash

from shop import create_app
from shop.db import connect, to_db_time, utc_now

API_KEY = "khoa-test-0123456789"
HMAC_SECRET = "bi-mat-hmac-test"
ACCOUNT = "0123456789"


class ShopTestCase(unittest.TestCase):
    auth_mode = "apikey"

    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # cảnh báo của test client, không phải lỗi code
        self.tmp = Path(tempfile.mkdtemp())
        self.app = create_app({
            "SECRET_KEY": "s" * 48,
            "DATABASE": str(self.tmp / "shop.db"),
            "PREVIEW_DIR": str(self.tmp / "preview"),
            "ORIGINAL_DIR": str(self.tmp / "originals"),
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("mat-khau-rat-manh"),
            "SEPAY_AUTH_MODE": self.auth_mode,
            "SEPAY_API_KEY": API_KEY,
            "SEPAY_WEBHOOK_SECRET": HMAC_SECRET,
            "BANK_ACCOUNT_NUMBER": ACCOUNT,
            "BANK_CODE": "MBBank",
            "BANK_ACCOUNT_NAME": "VO TRONG NHAN",
            "PAYMENT_PREFIX": "DH",
            "ORDER_EXPIRE_MINUTES": 15,
            "DOWNLOAD_LINK_SECONDS": 300,
            "MAX_DOWNLOADS": 3,
            "STRICT_AMOUNT": True,
            "PRODUCTION": False,
            "TESTING": True,
        })
        self.client = self.app.test_client()
        (self.tmp / "originals" / "goc.mp4").write_bytes(b"VIDEO-GOC-CHAT-LUONG-CAO")
        (self.tmp / "preview" / "thu.mp4").write_bytes(b"VIDEO-XEM-THU")
        self.db = connect(self.app.config["DATABASE"])
        self.video_id = self.db.execute(
            "INSERT INTO videos (title, price, preview_file, original_file) VALUES (?,?,?,?)",
            ("Video demo", 50000, "thu.mp4", "goc.mp4"),
        ).lastrowid
        self._sepay_id = 1000

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ----- tiện ích -----

    def csrf(self):
        with self.client.session_transaction() as sess:
            sess["_csrf"] = "tok"
        return "tok"

    def buy(self):
        resp = self.client.post(f"/mua/{self.video_id}", data={"_csrf": self.csrf()})
        self.assertEqual(resp.status_code, 302)
        token = resp.headers["Location"].rsplit("/", 1)[-1]
        order = self.db.execute("SELECT * FROM orders WHERE access_token = ?", (token,)).fetchone()
        return order

    def order(self, order_id):
        return self.db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    def payload(self, content, amount, sepay_id=None, **extra):
        if sepay_id is None:
            self._sepay_id += 1
            sepay_id = self._sepay_id
        data = {
            "gateway": "MBBank", "transactionDate": "2026-10-10 21:00:00",
            "accountNumber": ACCOUNT, "subAccount": None, "code": None,
            "content": content, "transferType": "in", "description": "",
            "transferAmount": amount, "referenceCode": "FT1", "accumulated": 0,
            "id": sepay_id,
        }
        data.update(extra)
        return json.dumps(data).encode()

    def send(self, body, headers=None):
        if headers is None:
            headers = {"Authorization": f"Apikey {API_KEY}"}
        return self.client.post("/webhook/sepay", data=body, headers=headers,
                                content_type="application/json")

    def last_tx(self):
        return self.db.execute("SELECT * FROM bank_transactions ORDER BY id DESC LIMIT 1").fetchone()


class TestCreateOrder(ShopTestCase):
    def test_buy_needs_csrf(self):
        resp = self.client.post(f"/mua/{self.video_id}")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)

    def test_order_has_random_code_and_snapshot_price(self):
        o1, o2 = self.buy(), self.buy()
        self.assertRegex(o1["payment_code"], r"^DH[A-Z2-9]{8}$")
        self.assertNotEqual(o1["payment_code"], o2["payment_code"])
        self.assertEqual(o1["amount"], 50000)
        self.assertEqual(o1["status"], "pending")

    def test_order_page_shows_qr_and_hides_download(self):
        o = self.buy()
        html = self.client.get(f"/don-hang/{o['access_token']}").get_data(as_text=True)
        self.assertIn("https://vietqr.app/img?", html)
        self.assertIn("template=compact", html)
        self.assertIn("bank=MBBank", html)
        self.assertIn(o["payment_code"], html)
        self.assertIn("amount=50000", html)
        self.assertNotIn("Tải video chất lượng cao", html)
        self.assertEqual(self.client.get(f"/don-hang/{o['access_token']}/tai").status_code, 403)

    def test_unknown_order_token_404(self):
        self.assertEqual(self.client.get("/don-hang/khong-ton-tai").status_code, 404)

    def test_inactive_video_cannot_be_bought(self):
        self.db.execute("UPDATE videos SET is_active = 0")
        resp = self.client.post(f"/mua/{self.video_id}", data={"_csrf": self.csrf()})
        self.assertEqual(resp.status_code, 404)


class TestWebhookAuth(ShopTestCase):
    def test_missing_auth_rejected(self):
        o = self.buy()
        resp = self.send(self.payload(o["payment_code"], 50000), headers={})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.order(o["id"])["status"], "pending")
        self.assertIsNone(self.last_tx())

    def test_wrong_key_rejected(self):
        o = self.buy()
        resp = self.send(self.payload(o["payment_code"], 50000),
                         headers={"Authorization": "Apikey sai-khoa"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.order(o["id"])["status"], "pending")

    def test_empty_configured_key_rejects_everything(self):
        self.app.config["SEPAY_API_KEY"] = ""
        o = self.buy()
        resp = self.send(self.payload(o["payment_code"], 50000), headers={"Authorization": "Apikey "})
        self.assertEqual(resp.status_code, 401)

    def test_bad_json_400(self):
        resp = self.send(b"khong phai json")
        self.assertEqual(resp.status_code, 400)

    def test_bad_amount_400(self):
        o = self.buy()
        for bad in ("50k", -5, 0, True, None, 12.5):
            resp = self.send(self.payload(o["payment_code"], bad))
            self.assertEqual(resp.status_code, 400, bad)
        self.assertEqual(self.order(o["id"])["status"], "pending")


class TestWebhookHmac(ShopTestCase):
    auth_mode = "hmac"

    def signed(self, body, secret=HMAC_SECRET, ts=None):
        ts = str(int(time.time()) if ts is None else ts)
        sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        return {"X-SePay-Timestamp": ts, "X-SePay-Signature": "sha256=" + sig}

    def test_valid_signature_pays(self):
        o = self.buy()
        body = self.payload(o["payment_code"], 50000)
        self.assertEqual(self.send(body, self.signed(body)).status_code, 200)
        self.assertEqual(self.order(o["id"])["status"], "paid")

    def test_wrong_secret_rejected(self):
        o = self.buy()
        body = self.payload(o["payment_code"], 50000)
        self.assertEqual(self.send(body, self.signed(body, secret="sai")).status_code, 401)
        self.assertEqual(self.order(o["id"])["status"], "pending")

    def test_tampered_body_rejected(self):
        o = self.buy()
        body = self.payload(o["payment_code"], 1000)
        headers = self.signed(body)
        tampered = body.replace(b"1000", b"50000")
        self.assertEqual(self.send(tampered, headers).status_code, 401)
        self.assertEqual(self.order(o["id"])["status"], "pending")

    def test_old_timestamp_rejected(self):
        o = self.buy()
        body = self.payload(o["payment_code"], 50000)
        self.assertEqual(self.send(body, self.signed(body, ts=int(time.time()) - 3600)).status_code, 401)

    def test_apikey_header_not_accepted_in_hmac_mode(self):
        o = self.buy()
        body = self.payload(o["payment_code"], 50000)
        self.assertEqual(self.send(body).status_code, 401)


class TestWebhookMoney(ShopTestCase):
    def test_exact_amount_pays(self):
        o = self.buy()
        resp = self.send(self.payload(f"{o['payment_code']} thanh toan", 50000))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"success": True})
        row = self.order(o["id"])
        self.assertEqual(row["status"], "paid")
        self.assertEqual(row["paid_amount"], 50000)
        self.assertEqual(self.last_tx()["result"], "paid")

    def test_code_found_in_messy_lowercase_content(self):
        o = self.buy()
        content = f"MBVCB.123456.{o['payment_code'].lower()}thanhtoan.CT tu 0987"
        self.send(self.payload(content, 50000))
        self.assertEqual(self.order(o["id"])["status"], "paid")

    def test_sepay_code_field_used(self):
        o = self.buy()
        self.send(self.payload("noi dung bi cat", 50000, code=o["payment_code"]))
        self.assertEqual(self.order(o["id"])["status"], "paid")

    def test_underpaid_not_unlocked(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 49999))
        self.assertEqual(self.order(o["id"])["status"], "pending")
        tx = self.last_tx()
        self.assertEqual(tx["result"], "underpaid")
        self.assertIn("Thiếu 1 đ", tx["note"])

    def test_overpaid_not_unlocked_in_strict_mode(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 60000))
        self.assertEqual(self.order(o["id"])["status"], "pending")
        tx = self.last_tx()
        self.assertEqual(tx["result"], "overpaid")
        self.assertIn("chưa mở khóa", tx["note"])

    def test_overpaid_unlocked_when_strict_off(self):
        self.app.config["STRICT_AMOUNT"] = False
        o = self.buy()
        self.send(self.payload(o["payment_code"], 60000))
        row = self.order(o["id"])
        self.assertEqual(row["status"], "paid")
        self.assertEqual(row["paid_amount"], 60000)
        self.assertEqual(self.last_tx()["result"], "overpaid")

    def test_small_amount_5000(self):
        self.db.execute("UPDATE videos SET price = 5000")
        o = self.buy()
        self.send(self.payload(o["payment_code"], 4999))
        self.assertEqual(self.order(o["id"])["status"], "pending")
        self.send(self.payload(o["payment_code"], 5001))
        self.assertEqual(self.order(o["id"])["status"], "pending")
        self.send(self.payload(o["payment_code"], 5000))
        self.assertEqual(self.order(o["id"])["status"], "paid")

    def test_duplicate_webhook_processed_once(self):
        o = self.buy()
        body = self.payload(o["payment_code"], 50000, sepay_id=777)
        self.assertEqual(self.send(body).status_code, 200)
        self.assertEqual(self.send(body).status_code, 200)
        self.assertEqual(self.send(body).status_code, 200)
        n = self.db.execute("SELECT COUNT(*) FROM bank_transactions WHERE sepay_id = 777").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(self.order(o["id"])["status"], "paid")

    def test_second_payment_for_paid_order_flagged(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 50000))
        self.send(self.payload(o["payment_code"], 50000))
        self.assertEqual(self.last_tx()["result"], "duplicate_payment")
        self.assertEqual(self.order(o["id"])["paid_amount"], 50000)

    def test_outgoing_transfer_ignored(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 50000, transferType="out"))
        self.assertEqual(self.order(o["id"])["status"], "pending")
        self.assertIsNone(self.last_tx())

    def test_no_code_unmatched(self):
        self.buy()
        self.send(self.payload("chuyen tien an trua", 50000))
        self.assertEqual(self.last_tx()["result"], "unmatched")

    def test_guessed_code_unmatched(self):
        o = self.buy()
        self.send(self.payload("DHAAAAAAAA", 50000))
        self.assertEqual(self.last_tx()["result"], "unmatched")
        self.assertEqual(self.order(o["id"])["status"], "pending")

    def test_wrong_account_not_unlocked(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 50000, accountNumber="9999999999"))
        self.assertEqual(self.order(o["id"])["status"], "pending")
        self.assertEqual(self.last_tx()["result"], "wrong_account")

    def test_payment_to_virtual_sub_account_accepted(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 50000, accountNumber="VA-KHAC", subAccount=ACCOUNT))
        self.assertEqual(self.order(o["id"])["status"], "paid")

    def test_late_payment_after_expiry_still_accepted(self):
        o = self.buy()
        past = to_db_time(utc_now().replace(year=2020))
        self.db.execute("UPDATE orders SET expires_at = ? WHERE id = ?", (past, o["id"]))
        status = self.client.get(f"/don-hang/{o['access_token']}/trang-thai").get_json()
        self.assertEqual(status["status"], "expired")
        self.send(self.payload(o["payment_code"], 50000))
        self.assertEqual(self.order(o["id"])["status"], "paid")
        self.assertIn("hết hạn", self.last_tx()["note"])

    def test_price_change_does_not_affect_pending_order(self):
        o = self.buy()
        self.db.execute("UPDATE videos SET price = 99000")
        self.send(self.payload(o["payment_code"], 50000))
        self.assertEqual(self.order(o["id"])["status"], "paid")

    def test_status_endpoint(self):
        o = self.buy()
        url = f"/don-hang/{o['access_token']}/trang-thai"
        self.assertEqual(self.client.get(url).get_json(), {"status": "pending"})
        self.send(self.payload(o["payment_code"], 50000))
        self.assertEqual(self.client.get(url).get_json()["status"], "paid")


class TestDownload(ShopTestCase):
    def paid_order(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 50000))
        return self.order(o["id"])

    def get_signed_url(self, order):
        resp = self.client.get(f"/don-hang/{order['access_token']}/tai")
        self.assertEqual(resp.status_code, 302)
        return resp.headers["Location"]

    def test_paid_order_downloads_original(self):
        o = self.paid_order()
        resp = self.client.get(self.get_signed_url(o))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"VIDEO-GOC-CHAT-LUONG-CAO")
        self.assertIn("attachment", resp.headers["Content-Disposition"])
        self.assertEqual(self.order(o["id"])["download_count"], 1)

    def test_download_limit(self):
        o = self.paid_order()
        for _ in range(3):
            self.assertEqual(self.client.get(self.get_signed_url(o)).status_code, 200)
        self.assertEqual(self.client.get(f"/don-hang/{o['access_token']}/tai").status_code, 403)

    def test_reused_signed_link_still_counts_against_limit(self):
        o = self.paid_order()
        url = self.get_signed_url(o)
        for _ in range(3):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_tampered_link_rejected(self):
        o = self.paid_order()
        url = self.get_signed_url(o)
        self.assertEqual(self.client.get(url[:-3] + "abc").status_code, 403)
        self.assertEqual(self.client.get("/tai/gia-mao").status_code, 403)

    def test_expired_link_rejected(self):
        o = self.paid_order()
        url = self.get_signed_url(o)
        self.app.config["DOWNLOAD_LINK_SECONDS"] = -1
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_link_for_unpaid_order_rejected(self):
        from shop import payments
        o = self.buy()  # chưa trả tiền
        token = payments.make_download_token(self.app.config, o)
        self.assertEqual(self.client.get(f"/tai/{token}").status_code, 403)

    def preview_url(self):
        html = self.client.get(f"/video/{self.video_id}").get_data(as_text=True)
        return re.search(r'src="(/xem-thu/[^"]+)"', html).group(1)

    def test_original_not_reachable_via_preview_or_static(self):
        for path in ("/preview/goc.mp4", "/preview/thu.mp4", "/xem-thu/goc.mp4",
                     "/static/../data/originals/goc.mp4", "/xem-thu/%2e%2e/originals/goc.mp4"):
            resp = self.client.get(path)
            self.assertNotEqual(resp.data, b"VIDEO-GOC-CHAT-LUONG-CAO", path)
            self.assertNotEqual(resp.data, b"VIDEO-XEM-THU", path)

    def test_preview_signed_link_works_and_supports_seeking(self):
        url = self.preview_url()
        resp = self.client.get(url)
        self.assertEqual(resp.data, b"VIDEO-XEM-THU")
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        part = self.client.get(url, headers={"Range": "bytes=0-4"})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part.data, b"VIDEO")

    def test_preview_link_expires_and_cannot_be_forged(self):
        url = self.preview_url()
        self.assertEqual(self.client.get(url[:-3] + "xyz").status_code, 403)
        self.app.config["PREVIEW_LINK_SECONDS"] = -1
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_preview_stops_when_video_hidden(self):
        url = self.preview_url()
        self.db.execute("UPDATE videos SET is_active = 0")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_video_page_player_protections(self):
        html = self.client.get(f"/video/{self.video_id}").get_data(as_text=True)
        for needle in ("disablePictureInPicture", "preview.js", "hoa-van", "nut-toan-man-hinh"):
            self.assertIn(needle, html)
        # Không dùng thanh điều khiển mặc định (có nút tải / toàn màn hình riêng video)
        self.assertNotRegex(html, r"<video[^>]*\scontrols")

    def test_watermark_svg_uses_text_and_escapes_it(self):
        self.app.config["WATERMARK_TEXT"] = 'Thầy cô Ơi! <script>"'
        resp = self.client.get("/hinh-mo.svg")
        self.assertEqual(resp.mimetype, "image/svg+xml")
        body = resp.get_data(as_text=True)
        self.assertIn("Thầy cô Ơi!", body)
        self.assertNotIn("<script>", body)
        self.assertEqual(body.count("<text"), 4)
        self.assertEqual(body.count("XEM THỬ"), 2)   # hàng "XEM THỬ" xen kẽ hàng thương hiệu
        self.assertEqual(body.count("<line"), 2)

    def test_watermark_url_changes_with_brand_and_no_host_shown(self):
        html1 = self.client.get(f"/video/{self.video_id}").get_data(as_text=True)
        self.app.config["WATERMARK_TEXT"] = "Thầy cô Ơi!"
        html2 = self.client.get(f"/video/{self.video_id}").get_data(as_text=True)
        u1 = re.search(r'data-hinh="([^"]+)"', html1).group(1)
        u2 = re.search(r'data-hinh="([^"]+)"', html2).group(1)
        self.assertNotEqual(u1, u2)          # đổi chữ thương hiệu -> địa chỉ hình mới
        self.assertIn("Thầy cô Ơi!", self.client.get(u2.replace("&amp;", "&")).get_data(as_text=True))
        self.assertNotIn("localhost", html2)  # không hiện địa chỉ web trên trang


class TestAdmin(ShopTestCase):
    def login(self, password="mat-khau-rat-manh"):
        return self.client.post("/quan-ly/dang-nhap", data={
            "_csrf": self.csrf(), "username": "admin", "password": password})

    def test_admin_pages_require_login(self):
        for path in ("/quan-ly/", "/quan-ly/video", "/quan-ly/don-hang", "/quan-ly/giao-dich"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertIn("/quan-ly/dang-nhap", resp.headers["Location"])

    def test_login_and_dashboard_revenue(self):
        o = self.buy()
        self.send(self.payload(o["payment_code"], 50000))
        self.send(self.payload("khong co ma", 10000))
        self.assertEqual(self.login().status_code, 302)
        html = self.client.get("/quan-ly/").get_data(as_text=True)
        self.assertIn("50.000 đ", html)
        self.assertIn("Có 1 khoản tiền cần xem lại", html)
        self.assertEqual(self.client.get("/quan-ly/giao-dich?can-xem=1").status_code, 200)
        self.assertEqual(self.client.get("/quan-ly/don-hang").status_code, 200)

    def test_wrong_password_and_lockout(self):
        for _ in range(5):
            self.assertEqual(self.login("sai").status_code, 401)
        # sau 5 lần sai, kể cả mật khẩu đúng cũng bị chặn tạm
        resp = self.login()
        self.assertEqual(resp.status_code, 401)
        self.assertIn("15 phút", resp.get_data(as_text=True))

    def test_open_redirect_blocked(self):
        resp = self.client.post("/quan-ly/dang-nhap?next=https://web-lua-dao.com", data={
            "_csrf": self.csrf(), "username": "admin", "password": "mat-khau-rat-manh"})
        self.assertEqual(resp.headers["Location"], "/quan-ly/")

    def test_upload_video(self):
        self.login()
        resp = self.client.post("/quan-ly/video", data={
            "_csrf": self.csrf(), "title": "Rồng bay", "price": "75.000", "description": "",
            "preview_file": (io.BytesIO(b"p"), "xem thu.mp4"),
            "original_file": (io.BytesIO(b"o"), "goc.mp4"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 302)
        v = self.db.execute("SELECT * FROM videos WHERE title = 'Rồng bay'").fetchone()
        self.assertEqual(v["price"], 75000)
        self.assertTrue((self.tmp / "originals" / v["original_file"]).exists())
        self.assertRegex(v["original_file"], r"^[0-9a-f]{32}\.mp4$")

    def test_ajax_upload_returns_json(self):
        self.login()
        ok = self.client.post("/quan-ly/video", headers={"X-Upload-Ajax": "1"}, data={
            "_csrf": self.csrf(), "title": "Ajax", "price": "5.000",
            "original_file": (io.BytesIO(b"x"), "a.mp4"),
        }, content_type="multipart/form-data")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.get_json(), {"ok": True, "redirect": "/quan-ly/video"})
        self.assertIn("Đã thêm sản phẩm: Ajax", self.client.get("/quan-ly/video").get_data(as_text=True))
        bad = self.client.post("/quan-ly/video", headers={"X-Upload-Ajax": "1"}, data={
            "_csrf": self.csrf(), "title": "", "price": "abc",
        }, content_type="multipart/form-data")
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(bad.get_json()["ok"])
        self.assertGreaterEqual(len(bad.get_json()["errors"]), 2)

    def test_upload_txt_without_preview_in_test_mode(self):
        self.login()
        resp = self.client.post("/quan-ly/video", data={
            "_csrf": self.csrf(), "title": "File test", "price": "5000",
            "original_file": (io.BytesIO(b"xin chao"), "test.txt"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 302)
        v = self.db.execute("SELECT * FROM videos WHERE title = 'File test'").fetchone()
        self.assertIsNone(v["preview_file"])
        self.assertTrue(v["original_file"].endswith(".txt"))
        self.assertEqual(self.client.get(f"/video/{v['id']}").status_code, 200)

    def test_txt_rejected_when_test_files_off(self):
        self.login()
        self.app.config["ALLOW_TEST_FILES"] = False
        resp = self.client.post("/quan-ly/video", data={
            "_csrf": self.csrf(), "title": "File test", "price": "5000",
            "original_file": (io.BytesIO(b"xin chao"), "test.txt"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_non_video_and_bad_price(self):
        self.login()
        resp = self.client.post("/quan-ly/video", data={
            "_csrf": self.csrf(), "title": "X", "price": "abc",
            "preview_file": (io.BytesIO(b"p"), "a.mp4"),
            "original_file": (io.BytesIO(b"o"), "virus.exe"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post("/quan-ly/video", data={
            "_csrf": self.csrf(), "title": "X", "price": "50000",
            "preview_file": (io.BytesIO(b"p"), "a.mp4"),
            "original_file": (io.BytesIO(b"o"), "virus.exe"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 1)
        # form lỗi thì không được để lại file rác
        self.assertEqual(sorted(p.name for p in (self.tmp / "originals").iterdir()), ["goc.mp4"])


class TestSecurityHeaders(ShopTestCase):
    def test_headers(self):
        resp = self.client.get("/")
        self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", resp.headers["Content-Security-Policy"])


class TestConfigValidation(unittest.TestCase):
    def test_short_secret_key_refused(self):
        with self.assertRaises(RuntimeError):
            create_app({"SECRET_KEY": "ngan", "DATABASE": ":memory:"})


class TestAdminSeparation(ShopTestCase):
    def login(self):
        return self.client.post("/quan-ly/dang-nhap", data={
            "_csrf": self.csrf(), "username": "admin", "password": "mat-khau-rat-manh"})

    def test_store_pages_never_link_to_admin_even_when_logged_in(self):
        self.login()
        o = self.buy()
        self.send(self.payload(o["payment_code"], 50000))  # đơn đã thanh toán
        for path in ("/", f"/video/{self.video_id}", f"/don-hang/{o['access_token']}", "/khong-co"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotIn("/quan-ly", html, path)
            self.assertNotIn("Doanh thu", html, path)
            self.assertNotIn("Đăng xuất", html, path)

    def test_admin_pages_have_admin_nav(self):
        self.login()
        html = self.client.get("/quan-ly/").get_data(as_text=True)
        self.assertIn("Trang quản lý", html)
        self.assertIn("Đăng xuất", html)
        self.assertIn("admin.js", html)
        self.assertIn("noindex", html)

    def test_customer_cannot_open_admin(self):
        for path in ("/quan-ly/", "/quan-ly/video", "/quan-ly/don-hang", "/quan-ly/giao-dich"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302)
            self.assertIn("dang-nhap", resp.headers["Location"])

    def test_price_with_dots_saved_as_integer(self):
        self.login()
        resp = self.client.post("/quan-ly/video", data={
            "_csrf": self.csrf(), "title": "Gia co cham", "price": "1.250.000",
            "original_file": (io.BytesIO(b"x"), "a.txt"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 302)
        v = self.db.execute("SELECT price FROM videos WHERE title = 'Gia co cham'").fetchone()
        self.assertEqual(v["price"], 1250000)

    def test_upload_form_has_dropzones_and_price_hook(self):
        self.login()
        html = self.client.get("/quan-ly/video").get_data(as_text=True)
        self.assertEqual(html.count('class="dropzone"'), 2)
        self.assertIn("data-gia", html)


class TestCustomAdminPath(ShopTestCase):
    def setUp(self):
        super().setUp()
        cfg = dict(self.app.config)
        cfg["ADMIN_PATH"] = "/bi-mat-123"
        cfg["DATABASE"] = str(self.tmp / "shop2.db")
        self.app2 = create_app({k: cfg[k] for k in (
            "SECRET_KEY", "DATABASE", "PREVIEW_DIR", "ORIGINAL_DIR", "ADMIN_USERNAME",
            "ADMIN_PASSWORD_HASH", "ADMIN_PATH", "BANK_ACCOUNT_NUMBER", "BANK_CODE")})
        self.c2 = self.app2.test_client()

    def test_old_path_gone_new_path_works(self):
        self.assertEqual(self.c2.get("/quan-ly/").status_code, 404)
        self.assertEqual(self.c2.get("/bi-mat-123/").status_code, 302)
        self.assertEqual(self.c2.get("/bi-mat-123/dang-nhap").status_code, 200)

    def test_bad_admin_path_refused(self):
        with self.assertRaises(RuntimeError):
            create_app({"SECRET_KEY": "s" * 48, "DATABASE": str(self.tmp / "x.db"),
                        "ADMIN_PATH": "/a b"})


class TestBoomerangAndPaidPage(ShopTestCase):
    def make_real_preview(self):
        import subprocess
        out = self.tmp / "nguon.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", "testsrc=duration=8:size=360x640:rate=24", "-pix_fmt", "yuv420p", str(out)],
                       check=True)
        return out

    @unittest.skipUnless(shutil.which("ffmpeg"), "cần ffmpeg")
    def test_upload_creates_boomerang_shown_on_home(self):
        import subprocess
        src = self.make_real_preview()
        with self.client.session_transaction() as sess:
            sess["_csrf"] = "tok"
        self.client.post("/quan-ly/dang-nhap", data={"_csrf": "tok", "username": "admin",
                                                    "password": "mat-khau-rat-manh"})
        resp = self.client.post("/quan-ly/video", data={
            "_csrf": self.csrf(), "title": "Có mẫu", "price": "50000",
            "original_file": (io.BytesIO(b"goc"), "goc.mp4"),
            "preview_file": (open(src, "rb"), "xemthu.mp4"),
        }, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 302)
        v = self.db.execute("SELECT * FROM videos WHERE title = 'Có mẫu'").fetchone()
        self.assertTrue(v["loop_file"].endswith(".mp4"))
        self.assertTrue(v["poster_file"].endswith(".jpg"))
        loop_path = self.tmp / "preview" / v["loop_file"]
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(loop_path)], capture_output=True, text=True).stdout)
        self.assertAlmostEqual(dur, 9.0, delta=0.5)   # 4,5 giây xuôi + 4,5 giây ngược
        wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                             "-of", "csv=p=0", str(loop_path)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(wh, "854,480")                # khung ngang 16:9
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(f"/mau/{v['loop_file']}", html)
        self.assertIn("autoplay muted loop playsinline", html)
        self.assertEqual(self.client.get(f"/mau/{v['loop_file']}").status_code, 200)
        self.assertEqual(self.client.get(f"/mau/{v['poster_file']}").status_code, 200)
        # ẩn video -> đoạn mẫu cũng không xem được nữa
        self.db.execute("UPDATE videos SET is_active = 0 WHERE id = ?", (v["id"],))
        self.assertEqual(self.client.get(f"/mau/{v['loop_file']}").status_code, 404)

    def test_loop_route_never_serves_other_files(self):
        for name in ("thu.mp4", "goc.mp4", "..%2Foriginals%2Fgoc.mp4"):
            self.assertEqual(self.client.get(f"/mau/{name}").status_code, 404, name)

    def test_paid_page_texts_and_download_count_in_status(self):
        o = self.buy()
        html = self.client.get(f"/don-hang/{o['access_token']}").get_data(as_text=True)
        self.assertNotIn("Đang chờ tiền về", html)
        self.send(self.payload(o["payment_code"], 50000))
        html = self.client.get(f"/don-hang/{o['access_token']}").get_data(as_text=True)
        self.assertIn("Cảm ơn thầy cô đã mua", html)
        self.assertIn("Tâm đã nhận 50.000 đ", html)
        url = f"/don-hang/{o['access_token']}/trang-thai"
        self.assertEqual(self.client.get(url).get_json(), {"status": "paid", "downloads_left": 3})
        self.client.get(self.client.get(f"/don-hang/{o['access_token']}/tai").headers["Location"])
        self.assertEqual(self.client.get(url).get_json()["downloads_left"], 2)

    def test_old_database_gets_new_columns(self):
        import sqlite3
        old = self.tmp / "cu.db"
        c = sqlite3.connect(old)
        c.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',"
                  " price INTEGER NOT NULL, preview_file TEXT, original_file TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,"
                  " created_at TEXT NOT NULL DEFAULT (datetime('now')))")
        c.close()
        from shop.db import init_db
        init_db(str(old))
        c = sqlite3.connect(old)
        cols = {r[1] for r in c.execute("PRAGMA table_info(videos)")}
        c.close()
        self.assertTrue({"loop_file", "poster_file"} <= cols)


class TestRenderSetup(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, **extra):
        cfg = {
            "SECRET_KEY": "s" * 48, "DATABASE": str(self.tmp / "shop.db"),
            "PREVIEW_DIR": str(self.tmp / "p"), "ORIGINAL_DIR": str(self.tmp / "o"),
            "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD_HASH": "", "ADMIN_PASSWORD": "",
            "TEST_PRODUCT_PRICE": 0,
        }
        cfg.update(extra)
        return create_app(cfg)

    def test_plain_admin_password_is_hashed(self):
        app = self.make(ADMIN_PASSWORD="mat-khau-render-123")
        self.assertNotIn("ADMIN_PASSWORD", app.config)
        self.assertTrue(app.config["ADMIN_PASSWORD_HASH"].startswith(("scrypt:", "pbkdf2:")))
        c = app.test_client()
        with c.session_transaction() as s:
            s["_csrf"] = "t"
        r = c.post("/quan-ly/dang-nhap", data={"_csrf": "t", "username": "admin", "password": "mat-khau-render-123"})
        self.assertEqual(r.status_code, 302)

    def test_short_plain_password_refused(self):
        with self.assertRaises(RuntimeError):
            self.make(ADMIN_PASSWORD="ngan")

    def test_seed_product_created_once(self):
        self.make(TEST_PRODUCT_PRICE=5000, TEST_PRODUCT_TEXT="noi dung bi mat")
        self.make(TEST_PRODUCT_PRICE=5000)  # khởi động lại: không tạo trùng
        db = connect(str(self.tmp / "shop.db"))
        rows = db.execute("SELECT * FROM videos").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], 5000)
        self.assertEqual((self.tmp / "o" / rows[0]["original_file"]).read_text(encoding="utf-8"), "noi dung bi mat\n")
        db.close()

    def test_proxy_fix_uses_forwarded_ip(self):
        app = self.make(TRUST_PROXY=True)
        seen = {}

        @app.route("/_ip")
        def _ip():
            from flask import request
            seen["ip"] = request.remote_addr
            return "ok"

        app.test_client().get("/_ip", headers={"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(seen["ip"], "1.2.3.4")


if __name__ == "__main__":
    unittest.main()
