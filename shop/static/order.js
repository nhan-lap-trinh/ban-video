// Trang đơn hàng: mỗi 3 giây hỏi server "đơn đã trả chưa?".
// Khi trạng thái thay đổi (đã trả / hết hạn) thì tải lại trang để hiện nội dung mới.
// Lưu ý: JavaScript chỉ HỎI trạng thái, không bao giờ tự quyết định đơn đã trả.
(function () {
  var box = document.getElementById("order");
  if (!box || box.dataset.status !== "pending") return;
  var url = box.dataset.statusUrl;

  function check() {
    fetch(url, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status !== "pending") {
          window.location.reload();
        } else {
          setTimeout(check, 3000);
        }
      })
      .catch(function () { setTimeout(check, 5000); });
  }
  setTimeout(check, 3000);
})();
