"""Xử lý video bằng ffmpeg: cắt đoạn mẫu chạy "boomerang" cho trang danh sách video.

Boomerang = đoạn 4,5 giây đầu của video XEM THỬ chạy xuôi rồi chạy ngược lại,
lặp mãi. File nhỏ (rộng 320px, không có tiếng) nên trang chủ tải nhanh.
Dùng video xem thử (đã có watermark), không bao giờ dùng video gốc.
"""

import shutil
import subprocess
from pathlib import Path

LOOP_SECONDS = 4.5


def find_ffmpeg():
    """Ưu tiên ffmpeg có sẵn trên máy; không có thì dùng bản đi kèm gói imageio-ffmpeg
    (cài qua pip, chạy được trên Render mà không cần cài thêm gì)."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg  # noqa: PLC0415  (chỉ cần khi máy không có ffmpeg)
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # không có ffmpeg -> bỏ qua, trang chủ hiện dạng chữ như cũ
        return None


def make_boomerang(src, out_dir, base_name, logger=None):
    """Tạo <base_name>.mp4 (đoạn boomerang) và <base_name>.jpg (ảnh bìa).
    Trả về (tên file video, tên file ảnh); lỗi thì trả về (None, None) chứ không làm hỏng việc đăng video."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        if logger:
            logger.warning("Không tìm thấy ffmpeg, bỏ qua đoạn mẫu boomerang")
        return None, None
    out_dir = Path(out_dir)
    loop_name, poster_name = base_name + ".mp4", base_name + ".jpg"
    loop_cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-t", str(LOOP_SECONDS), "-i", str(src),        # chỉ đọc 4,5 giây đầu
        "-an",                                           # bỏ tiếng: trình duyệt mới cho tự chạy
        "-filter_complex",
        # thu nhỏ, chia làm 2 nhánh, 1 nhánh quay ngược, rồi nối xuôi + ngược
        "[0:v]fps=20,scale=320:-2,split[xuoi][b];[b]reverse[nguoc];"
        "[xuoi][nguoc]concat=n=2:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
        "-movflags", "+faststart",                       # phát được ngay khi mới tải một phần
        str(out_dir / loop_name),
    ]
    poster_cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-ss", "0.3", "-i", str(src), "-frames:v", "1", "-vf", "scale=320:-2",
        str(out_dir / poster_name),
    ]
    try:
        subprocess.run(loop_cmd, check=True, capture_output=True, timeout=180)
        subprocess.run(poster_cmd, check=True, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        if logger:
            logger.warning("Tạo đoạn mẫu boomerang thất bại: %s", exc)
        for name in (loop_name, poster_name):
            (out_dir / name).unlink(missing_ok=True)
        return None, None
    return loop_name, poster_name
