"""Xử lý video bằng ffmpeg: cắt đoạn mẫu chạy "boomerang" cho trang danh sách video.

Boomerang = đoạn 4,5 giây đầu của video XEM THỬ chạy xuôi rồi chạy ngược lại,
lặp mãi. Khung ngang 16:9 như YouTube, 854x480 (480p), không có tiếng.
Video dọc (kiểu Reels/TikTok) được đặt giữa khung, hai bên là chính video đó phóng to
và làm mờ, nên không bị cắt mất nội dung và không có viền đen.
Dùng video xem thử (đã có watermark), không bao giờ dùng video gốc.
"""

import shutil
import subprocess
from pathlib import Path

LOOP_SECONDS = 4.5
WIDTH, HEIGHT = 854, 480  # 16:9

# Nền: phóng to cho phủ kín khung rồi làm mờ. Trên cùng: video thu vừa khung, đặt giữa.
FRAME_16_9 = (
    f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
    "boxblur=20:2,eq=brightness=-0.06[nen];"
    f"[fg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[tren];"
    "[nen][tren]overlay=(W-w)/2:(H-h)/2,setsar=1"
)


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
        # đưa về khung 16:9, chia 2 nhánh, 1 nhánh quay ngược, rồi nối xuôi + ngược
        f"[0:v]fps=24,split[bg][fg];[bg]{FRAME_16_9},split[xuoi][b];[b]reverse[nguoc];"
        "[xuoi][nguoc]concat=n=2:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",   # crf càng nhỏ càng nét
        "-movflags", "+faststart",                       # phát được ngay khi mới tải một phần
        str(out_dir / loop_name),
    ]
    poster_cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-ss", "0.3", "-i", str(src), "-frames:v", "1", "-q:v", "3",
        "-filter_complex", f"[0:v]split[bg][fg];[bg]{FRAME_16_9}",
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
