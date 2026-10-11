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

// Sau khi bấm "Tải video về máy": trang vẫn đứng yên (file tải về ở góc trình duyệt),
// nên tự hỏi lại máy chủ còn bao nhiêu lượt tải và cập nhật con số ngay trên trang.
(function () {
  var khu = document.getElementById("khu-tai");
  var nut = document.getElementById("nut-tai");
  var box = document.getElementById("order");
  if (!khu || !nut || !box) return;
  var url = box.dataset.statusUrl;
  var soLuot = document.getElementById("so-luot");
  var dongLuot = document.getElementById("luot-tai");
  var hetLuot = document.getElementById("het-luot");

  function hien(conLai) {
    khu.dataset.conLai = conLai;
    if (soLuot) soLuot.textContent = conLai;
    var het = conLai <= 0;
    nut.hidden = het;
    if (dongLuot) dongLuot.hidden = het;
    if (hetLuot) hetLuot.hidden = !het;
  }

  nut.addEventListener("click", function () {
    var truoc = parseInt(khu.dataset.conLai, 10);
    var lan = 0;
    function hoi() {
      lan += 1;
      fetch(url, { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (typeof d.downloads_left === "number" && d.downloads_left !== truoc) {
            hien(d.downloads_left);
          } else if (lan < 8) {
            setTimeout(hoi, 1500);   // máy chủ chưa ghi nhận lượt tải -> hỏi lại sau
          }
        })
        .catch(function () { if (lan < 8) setTimeout(hoi, 2000); });
    }
    setTimeout(hoi, 1200);
  });
})();
