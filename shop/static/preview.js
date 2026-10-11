// Trình phát video XEM THỬ với các lớp "gây khó".
// Lưu ý: KHÔNG lớp nào chặn được quay màn hình tuyệt đối. Mục tiêu là làm việc lấy
// video phiền hơn và bản quay được xấu hơn (hoa văn watermark phủ kín, luôn trôi).
(function () {
  var khung = document.getElementById("khung-xem-thu");
  var video = document.getElementById("video-xem-thu");
  var manChe = document.getElementById("man-che");
  var nutPhat = document.getElementById("nut-phat");
  var nutAm = document.getElementById("nut-am");
  var nutToan = document.getElementById("nut-toan-man-hinh");
  var thanhTua = document.getElementById("thanh-tua");
  var thoiGian = document.getElementById("thoi-gian");
  if (!khung || !video) return;

  // ---- Chặn chuột phải và kéo video ra ngoài ----
  khung.addEventListener("contextmenu", function (e) { e.preventDefault(); });
  khung.addEventListener("dragstart", function (e) { e.preventDefault(); });

  // ---- Phát / dừng ----
  function batTatPhat() { if (video.paused) video.play(); else video.pause(); }
  nutPhat.addEventListener("click", batTatPhat);
  video.addEventListener("click", batTatPhat);
  video.addEventListener("play", function () { khung.classList.add("dang-phat"); boChe(); });
  video.addEventListener("pause", function () { khung.classList.remove("dang-phat"); });

  // ---- Âm thanh ----
  nutAm.addEventListener("click", function () {
    video.muted = !video.muted;
    khung.classList.toggle("tat-tieng", video.muted);
  });

  // ---- Thanh tua + thời gian ----
  function dinhDangGiay(t) {
    if (!isFinite(t)) t = 0;
    var p = Math.floor(t / 60), g = Math.floor(t % 60);
    return p + ":" + (g < 10 ? "0" : "") + g;
  }
  var dangKeoTua = false;
  function capNhatThoiGian() {
    var d = video.duration || 0;
    if (!dangKeoTua && d) thanhTua.value = Math.round((video.currentTime / d) * 1000);
    thoiGian.textContent = dinhDangGiay(video.currentTime) + " / " + dinhDangGiay(d);
  }
  video.addEventListener("timeupdate", capNhatThoiGian);
  video.addEventListener("loadedmetadata", capNhatThoiGian);
  thanhTua.addEventListener("input", function () {
    dangKeoTua = true;
    if (video.duration) video.currentTime = (thanhTua.value / 1000) * video.duration;
  });
  thanhTua.addEventListener("change", function () { dangKeoTua = false; });

  // ---- Toàn màn hình: CÙNG MỘT NÚT ở góc phải dưới để vào và để thoát ----
  // Phóng to cả khung (video + hoa văn watermark), không phải riêng video.
  function dangToanManHinh() {
    return document.fullscreenElement === khung || document.webkitFullscreenElement === khung;
  }
  nutToan.addEventListener("click", function () {
    if (dangToanManHinh()) {
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    } else {
      var vao = khung.requestFullscreen || khung.webkitRequestFullscreen;
      if (vao) vao.call(khung);
      else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen(); // iPhone không hỗ trợ phóng to khung
    }
  });
  // Bấm đúp vào video cũng vào/thoát toàn màn hình
  video.addEventListener("dblclick", function () { nutToan.click(); });

  // ---- Rời tab hoặc chuyển sang cửa sổ/ứng dụng khác: dừng và che lại ----
  function che() {
    if (!video.paused) video.pause();
    khung.classList.add("bi-che");
    if (manChe) manChe.hidden = false;
  }
  function boChe() {
    khung.classList.remove("bi-che");
    if (manChe) manChe.hidden = true;
  }
  document.addEventListener("visibilitychange", function () { if (document.hidden) che(); });
  window.addEventListener("blur", function () { if (video.currentTime > 0) che(); });
  if (manChe) manChe.addEventListener("click", function () { boChe(); video.play(); });
})();
