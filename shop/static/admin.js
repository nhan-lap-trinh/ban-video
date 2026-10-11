// Tiện ích cho trang quản lý:
//  1. Ô giá tiền tự thêm dấu chấm phân cách hàng nghìn khi gõ (5000 -> 5.000).
//  2. Ô chọn file nhận cả kéo-thả.
// Đây chỉ là tiện ích hiển thị. Máy chủ vẫn tự bỏ dấu chấm và kiểm tra lại giá,
// nên dù JavaScript có bị tắt hay bị sửa thì dữ liệu lưu vào vẫn đúng.

// "50000" -> "50.000". Chỉ giữ chữ số, bỏ số 0 vô nghĩa ở đầu.
function dinhDangNghin(chuoi) {
  var so = String(chuoi).replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  return so.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// Đếm số chữ số nằm bên trái vị trí con trỏ.
function demChuSo(chuoi, viTri) {
  return String(chuoi).slice(0, viTri).replace(/\D/g, "").length;
}

// Tìm vị trí trong chuỗi mới sao cho bên trái có đúng `n` chữ số.
function viTriSauNChuSo(chuoi, n) {
  if (n === 0) return 0;
  var dem = 0;
  for (var i = 0; i < chuoi.length; i++) {
    if (/\d/.test(chuoi[i]) && ++dem === n) return i + 1;
  }
  return chuoi.length;
}

function ganOGia(o) {
  function capNhat() {
    var cu = o.value;
    var soChuSoTruocConTro = demChuSo(cu, o.selectionStart == null ? cu.length : o.selectionStart);
    var moi = dinhDangNghin(cu);
    if (moi !== cu) {
      o.value = moi;
      // Giữ con trỏ đúng chỗ, để gõ/xóa ở giữa không bị nhảy về cuối
      var p = viTriSauNChuSo(moi, soChuSoTruocConTro);
      try { o.setSelectionRange(p, p); } catch (e) {}
    }
  }
  o.addEventListener("input", capNhat);
  capNhat(); // định dạng sẵn giá trị cũ (khi form bị trả về vì lỗi)
}

function kichThuocDep(byte) {
  if (byte >= 1073741824) return (byte / 1073741824).toFixed(2) + " GB";
  if (byte >= 1048576) return (byte / 1048576).toFixed(1) + " MB";
  if (byte >= 1024) return Math.round(byte / 1024) + " KB";
  return byte + " byte";
}

function ganVungKeoTha(vung) {
  var input = vung.querySelector('input[type="file"]');
  var nhan = vung.querySelector(".ten-file");
  if (!input) return;

  function hienTen() {
    if (!nhan) return;
    var f = input.files && input.files[0];
    nhan.textContent = f ? "Đã chọn: " + f.name + " (" + kichThuocDep(f.size) + ")" : "";
  }

  vung.addEventListener("dragover", function (e) {
    e.preventDefault();               // bắt buộc, nếu không trình duyệt sẽ không cho thả
    vung.classList.add("dang-keo");
  });
  vung.addEventListener("dragleave", function () { vung.classList.remove("dang-keo"); });
  vung.addEventListener("drop", function (e) {
    e.preventDefault();               // chặn trình duyệt tự mở file
    vung.classList.remove("dang-keo");
    var files = e.dataTransfer && e.dataTransfer.files;
    if (!files || !files.length) return;
    // Chỉ lấy file đầu tiên (mỗi ô chỉ nhận 1 file)
    var dt = new DataTransfer();
    dt.items.add(files[0]);
    input.files = dt.files;
    hienTen();
  });
  // Bấm vào vùng (ngoài nút) cũng mở hộp chọn file
  vung.addEventListener("click", function (e) {
    if (e.target !== input) input.click();
  });
  input.addEventListener("change", hienTen);
}

// Gửi form thêm video bằng JavaScript để theo dõi được % đã tải lên,
// trong lúc đó hiện màn chờ có vòng xoay.
function ganFormTaiLen(form) {
  var lop = document.getElementById("lop-cho");
  var phanTram = document.getElementById("phan-tram");
  var thanh = document.getElementById("thanh-tien-trinh");
  var hopLoi = document.getElementById("loi-tai-len");
  var dangGui = false;

  function hienLoi(danhSach) {
    hopLoi.textContent = "";
    danhSach.forEach(function (loi) {
      var khung = document.createElement("div");
      khung.className = "thong-bao loi";
      var p = document.createElement("p");
      p.textContent = loi;            // textContent: không bao giờ chèn HTML lạ vào trang
      khung.appendChild(p);
      hopLoi.appendChild(khung);
    });
    hopLoi.scrollIntoView({ block: "center" });
  }

  form.addEventListener("submit", function (e) {
    if (typeof FormData === "undefined" || typeof XMLHttpRequest === "undefined") return; // trình duyệt quá cũ: gửi kiểu thường
    e.preventDefault();
    if (dangGui) return;               // chặn bấm 2 lần tạo 2 sản phẩm
    dangGui = true;
    hopLoi.textContent = "";
    document.getElementById("dang-tai").hidden = false;
    document.getElementById("da-xong").hidden = true;
    phanTram.textContent = "0%";
    thanh.value = 0;
    lop.hidden = false;

    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.getAttribute("action") || window.location.href);
    xhr.setRequestHeader("X-Upload-Ajax", "1");
    xhr.upload.addEventListener("progress", function (ev) {
      if (!ev.lengthComputable) return;
      var pt = Math.floor((ev.loaded / ev.total) * 100);
      thanh.value = pt;
      phanTram.textContent = pt < 100 ? pt + "%" : "100%";
      if (pt >= 100) document.querySelector("#dang-tai .tieu-de-cho").textContent = "Đang lưu video, sắp xong...";
    });
    xhr.addEventListener("load", function () {
      var data = null;
      try { data = JSON.parse(xhr.responseText); } catch (err) {}
      if (xhr.status === 200 && data && data.ok) {
        dangGui = false;                        // xong rồi, không cần hỏi khi rời trang nữa
        // Đổi vòng xoay thành dấu tích, để người dùng thấy rõ là đã xong rồi mới chuyển trang
        document.getElementById("dang-tai").hidden = true;
        document.getElementById("da-xong").hidden = false;
        setTimeout(function () { window.location.href = data.redirect; }, 1500);
        return;
      }
      dangGui = false;
      lop.hidden = true;
      if (data && data.errors) hienLoi(data.errors);
      else if (xhr.status === 413) hienLoi(["File quá lớn, vượt giới hạn cho phép."]);
      else hienLoi(["Tải lên thất bại (mã " + xhr.status + "). Hãy tải lại trang rồi thử lại."]);
    });
    xhr.addEventListener("error", function () {
      dangGui = false;
      lop.hidden = true;
      hienLoi(["Mất kết nối khi đang tải lên. Kiểm tra mạng rồi thử lại."]);
    });
    xhr.send(new FormData(form));
  });

  // Đang tải dở mà lỡ bấm đóng tab: trình duyệt hỏi lại
  window.addEventListener("beforeunload", function (e) {
    if (dangGui && lop && !lop.hidden) { e.preventDefault(); e.returnValue = ""; }
  });
}

if (typeof document !== "undefined") {
  var formTai = document.getElementById("form-tai-video");
  if (formTai) ganFormTaiLen(formTai);
  document.querySelectorAll("input[data-gia]").forEach(ganOGia);
  document.querySelectorAll(".dropzone").forEach(ganVungKeoTha);
  // Lỡ thả file ra ngoài vùng: không để trình duyệt mở file đó và rời khỏi trang
  window.addEventListener("dragover", function (e) { e.preventDefault(); });
  window.addEventListener("drop", function (e) { e.preventDefault(); });
}

if (typeof module !== "undefined") {
  module.exports = { dinhDangNghin: dinhDangNghin, demChuSo: demChuSo, viTriSauNChuSo: viTriSauNChuSo };
}
