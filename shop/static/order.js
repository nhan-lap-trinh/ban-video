// Trang đơn hàng: mỗi 3 giây hỏi server "đơn đã trả chưa?".
// Khi trạng thái thay đổi (đã trả / hết hạn) thì tải lại trang để hiện nội dung mới.
// Lưu ý: JavaScript chỉ HỎI trạng thái, không bao giờ tự quyết định đơn đã trả.
// Nút "Sao chép": chép số tài khoản / số tiền / nội dung để dán vào app ngân hàng.
(function () {
  document.querySelectorAll("[data-sao-chep]").forEach(function (nut) {
    nut.addEventListener("click", function () {
      var chu = nut.getAttribute("data-sao-chep");
      function daChep() {
        nut.textContent = "Đã chép";
        nut.classList.add("da-chep");
        setTimeout(function () { nut.textContent = "Sao chép"; nut.classList.remove("da-chep"); }, 2000);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(chu).then(daChep, function () {});
      }
    });
  });
})();

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
