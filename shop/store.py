"""Các trang dành cho KHÁCH HÀNG + địa chỉ nhận webhook của SePay."""

from pathlib import Path

from markupsafe import escape

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import payments
from .db import get_db, transaction

bp = Blueprint("store", __name__)


def _get_order_by_token(token):
    order = get_db().execute(
        "SELECT o.*, v.title AS video_title FROM orders o JOIN videos v ON v.id = o.video_id"
        " WHERE o.access_token = ?",
        (token,),
    ).fetchone()
    if order is None:
        abort(404)
    return order


@bp.route("/")
def index():
    videos = get_db().execute(
        "SELECT id, title, price FROM videos WHERE is_active = 1 ORDER BY id DESC"
    ).fetchall()
    return render_template("index.html", videos=videos)


def _preview_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="preview-link")


@bp.route("/video/<int:video_id>")
def video_detail(video_id):
    video = get_db().execute(
        "SELECT * FROM videos WHERE id = ? AND is_active = 1", (video_id,)
    ).fetchone()
    if video is None:
        abort(404)
    preview_url = None
    if video["preview_file"]:
        # Link xem thử có chữ ký và hết hạn: copy link đem đi chỗ khác thì một lúc sau là hỏng
        signed = _preview_serializer().dumps({"v": video["id"], "f": video["preview_file"]})
        preview_url = url_for("store.preview_file", signed=signed)
    return render_template("video.html", video=video, preview_url=preview_url)


@bp.route("/hinh-mo.svg")
def watermark_svg():
    """Một ô hoa văn: lưới hình thoi, xen kẽ 2 hàng chữ "XEM THỬ" và tên thương hiệu.
    Trình duyệt lặp ô này phủ kín video xem thử."""
    brand = current_app.config["WATERMARK_TEXT"] or "XEM THỬ"
    w, h = 300, 210
    # Tâm 4 hình thoi chạm cạnh ô. Hai tâm trên/dưới thuộc cùng một hàng (hàng "XEM THỬ"),
    # hai tâm trái/phải thuộc hàng xen kẽ (hàng thương hiệu). Phần chữ bị cắt ở mép ô
    # được ô bên cạnh vẽ tiếp, nên ghép lại liền mạch.
    rows = [((w / 2, 0), "XEM THỬ"), ((w / 2, h), "XEM THỬ"), ((0, h / 2), brand), ((w, h / 2), brand)]
    texts = "".join(f'<text x="{x:g}" y="{y:g}">{escape(t)}</text>' for (x, y), t in rows)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        '<g stroke="rgba(185,185,185,0.7)" stroke-width="1.4">'
        f'<line x1="0" y1="0" x2="{w}" y2="{h}"/><line x1="{w}" y1="0" x2="0" y2="{h}"/>'
        "</g>"
        '<g font-family="Segoe Script, Brush Script MT, Lucida Handwriting, cursive" font-style="italic"'
        ' font-size="30" text-anchor="middle" dominant-baseline="middle"'
        ' fill="rgba(190,190,190,0.6)" stroke="rgba(60,60,60,0.45)" stroke-width="0.7">'
        f"{texts}</g></svg>"
    )
    resp = current_app.response_class(svg, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-cache"  # đổi tên thương hiệu là thấy ngay
    return resp


@bp.route("/xem-thu/<signed>")
def preview_file(signed):
    """Phát file xem thử. Chỉ chạy được với link còn hạn, của video đang bán.
    Thư mục file gốc nằm chỗ khác hẳn nên không thể lấy file gốc qua đường này."""
    try:
        data = _preview_serializer().loads(signed, max_age=current_app.config["PREVIEW_LINK_SECONDS"])
    except (BadSignature, SignatureExpired):
        abort(403, description="Link xem thử đã hết hạn. Hãy tải lại trang video.")
    if not isinstance(data, dict):
        abort(403)
    row = get_db().execute(
        "SELECT preview_file FROM videos WHERE id = ? AND preview_file = ? AND is_active = 1",
        (data.get("v"), data.get("f")),
    ).fetchone()
    if row is None:
        abort(404)
    resp = send_from_directory(current_app.config["PREVIEW_DIR"], row["preview_file"])
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Content-Disposition"] = "inline"
    return resp


@bp.route("/mua/<int:video_id>", methods=["POST"])
def buy(video_id):
    db = get_db()
    video = db.execute(
        "SELECT * FROM videos WHERE id = ? AND is_active = 1", (video_id,)
    ).fetchone()
    if video is None:
        abort(404)
    if not current_app.config["BANK_ACCOUNT_NUMBER"] or not current_app.config["BANK_CODE"]:
        abort(503, description="Shop chưa cấu hình tài khoản nhận tiền.")
    order = payments.create_order(db, video, current_app.config)
    return redirect(url_for("store.order_page", token=order["access_token"]))


@bp.route("/don-hang/<token>")
def order_page(token):
    order = _get_order_by_token(token)
    status = payments.order_display_status(order)
    cfg = current_app.config
    qr_url = None
    if status == "pending":
        qr_url = payments.qr_image_url(cfg, order["amount"], order["payment_code"])
    return render_template(
        "order.html",
        order=order,
        status=status,
        qr_url=qr_url,
        bank_code=cfg["BANK_CODE"],
        bank_account=cfg["BANK_ACCOUNT_NUMBER"],
        bank_name=cfg["BANK_ACCOUNT_NAME"],
        downloads_left=max(0, cfg["MAX_DOWNLOADS"] - order["download_count"]),
    )


@bp.route("/don-hang/<token>/trang-thai")
def order_status(token):
    """Trang đơn hàng gọi địa chỉ này mỗi 3 giây để biết đã thanh toán chưa.
    Chỉ trả về trạng thái, không lộ thông tin gì khác."""
    order = _get_order_by_token(token)
    resp = jsonify({"status": payments.order_display_status(order)})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/don-hang/<token>/tai")
def start_download(token):
    """Bước 1 của tải video: kiểm tra đơn đã trả, rồi cấp một link ký số sống 5 phút."""
    order = _get_order_by_token(token)
    if order["status"] != "paid":
        abort(403, description="Đơn hàng chưa được thanh toán.")
    if order["download_count"] >= current_app.config["MAX_DOWNLOADS"]:
        abort(403, description="Đơn hàng đã hết lượt tải. Vui lòng liên hệ shop.")
    signed = payments.make_download_token(current_app.config, order)
    return redirect(url_for("store.download_file", signed=signed))


@bp.route("/tai/<signed>")
def download_file(signed):
    """Bước 2: kiểm tra chữ ký + hạn dùng, trừ một lượt tải, rồi gửi file gốc."""
    cfg = current_app.config
    parsed = payments.read_download_token(cfg, signed)
    if parsed is None:
        abort(403, description="Link tải không hợp lệ hoặc đã hết hạn. Hãy quay lại trang đơn hàng để lấy link mới.")
    order_id, token_head = parsed
    db = get_db()
    with transaction(db):
        row = db.execute(
            "SELECT o.access_token, o.status, o.payment_code, v.original_file FROM orders o"
            " JOIN videos v ON v.id = o.video_id WHERE o.id = ?",
            (order_id,),
        ).fetchone()
        if row is None or row["status"] != "paid" or row["access_token"][:8] != token_head:
            abort(403)
        # Trừ lượt tải ngay trong câu UPDATE: hết lượt thì rowcount = 0
        used = db.execute(
            "UPDATE orders SET download_count = download_count + 1"
            " WHERE id = ? AND download_count < ?",
            (order_id, cfg["MAX_DOWNLOADS"]),
        ).rowcount
    if used != 1:
        abort(403, description="Đơn hàng đã hết lượt tải. Vui lòng liên hệ shop.")
    ext = Path(row["original_file"]).suffix
    resp = send_from_directory(
        cfg["ORIGINAL_DIR"], row["original_file"], as_attachment=True,
        download_name=f"video-{row['payment_code']}{ext}",  # tên file khách nhận được
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/webhook/sepay", methods=["POST"])
def sepay_webhook():
    cfg = current_app.config
    raw = request.get_data(cache=False)  # đọc bytes gốc, cần cho HMAC
    if not payments.verify_webhook(cfg, request.headers, raw):
        current_app.logger.warning("Webhook bị từ chối: xác thực sai (IP %s)", request.remote_addr)
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    try:
        result, note = payments.process_webhook(get_db(), cfg, raw)
    except payments.InvalidPayload as exc:
        current_app.logger.warning("Webhook dữ liệu sai: %s", exc)
        return jsonify({"success": False, "message": str(exc)}), 400
    current_app.logger.info("Webhook xử lý xong: %s %s", result, note or "")
    # Trả success=true để SePay không gửi lại. Kể cả giao dịch "thiếu tiền" hay
    # "không khớp" cũng đã được GHI LẠI để bạn xử lý trong trang quản lý.
    return jsonify({"success": True})
