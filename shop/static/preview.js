// Các lớp "gây khó" cho video XEM THỬ. Lưu ý: KHÔNG lớp nào chặn được quay màn hình
// một cách tuyệt đối. Mục tiêu là làm việc lấy video phiền hơn và bản quay được xấu hơn.
(function () {
  var khung = document.getElementById("khung-xem-thu");
  var video = document.getElementById("video-xem-thu");
  var chu = document.getElementById("chu-chay");
  var manChe = document.getElementById("man-che");
  var nutToanManHinh = document.getElementById("nut-toan-man-hinh");
  if (!khung || !video) return;

  // 1. Chặn chuột phải (menu "Lưu video thành...") và kéo video ra ngoài
  khung.addEventListener("contextmenu", function (e) { e.preventDefault(); });
  khung.addEventListener("dragstart", function (e) { e.preventDefault(); });

  // 2. Chữ "XEM THỬ" nhảy tới vị trí ngẫu nhiên mỗi 3 giây, để không thể
  //    che hay cắt bỏ nó ở một chỗ cố định trong bản quay
  function doiViTri() {
    if (!chu) return;
    var maxLeft = Math.max(0, khung.clientWidth - chu.offsetWidth - 8);
    var maxTop = Math.max(0, khung.clientHeight - chu.offsetHeight - 8);
    chu.style.left = Math.round(Math.random() * maxLeft) + "px";
    chu.style.top = Math.round(Math.random() * maxTop) + "px";
  }
  doiViTri();
  setInterval(doiViTri, 3000);

  // 3. Rời khỏi tab hoặc chuyển sang cửa sổ/ứng dụng khác -> dừng video và che lại
  function che() {
    if (!video.paused) video.pause();
    khung.classList.add("bi-che");
    if (manChe) manChe.hidden = false;
  }
  function boChe() {
    khung.classList.remove("bi-che");
    if (manChe) manChe.hidden = true;
  }
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) che();
  });
  window.addEventListener("blur", function () {
    // Chỉ che khi đang xem dở, để không làm phiền lúc mới vào trang
    if (video.currentTime > 0) che();
  });
  if (manChe) manChe.addEventListener("click", function () { boChe(); video.play(); });
  video.addEventListener("play", boChe);

  // 4. Toàn màn hình cho CẢ KHUNG (video + chữ chạy), thay vì nút toàn màn hình
  //    mặc định của trình duyệt (chỉ phóng to video, làm mất chữ chạy)
  if (nutToanManHinh) {
    nutToanManHinh.addEventListener("click", function () {
      var req = khung.requestFullscreen || khung.webkitRequestFullscreen;
      if (req) req.call(khung);
      else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen(); // iPhone cũ
    });
  }
  document.addEventListener("fullscreenchange", function () { setTimeout(doiViTri, 100); });
})();
