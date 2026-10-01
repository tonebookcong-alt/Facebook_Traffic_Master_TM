# -*- coding: utf-8 -*-
"""
FACEBOOK TRAFFIC MASTER — LAUNCHER (KHỞI ĐỘNG VIÊN)
- Lần 1: Cài đặt tài nguyên, kiểm tra thư viện và tải Playwright Chromium
- Lần 2 trở đi: Mở server WebUI ngầm và tự động bật trình duyệt web local http://127.0.0.1:5001
"""

import os
import sys
import time
import subprocess
import webbrowser
import shutil

# Xác định thư mục chứa file chạy
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(APP_DIR)

FLAG_FILE = os.path.join(APP_DIR, "installed.flag")
PORT = 5001
URL = f"http://127.0.0.1:{PORT}"


def tim_lenh_python() -> str:
    """Tìm đường dẫn thực thi của Python trên máy."""
    # Nếu đang chạy script python
    if not getattr(sys, 'frozen', False):
        return sys.executable

    # Nếu đang chạy từ file EXE đóng gói
    # 1. Thử sys.executable nếu là python
    # 2. Tìm trong PATH
    candidates = ["python", "python3", "py"]
    for c in candidates:
        py_path = shutil.which(c)
        if py_path:
            return py_path

    # Thử các đường dẫn Python mặc định phổ biến trên Windows
    user_prof = os.environ.get("USERPROFILE", "")
    local_app = os.environ.get("LOCALAPPDATA", "")
    common_paths = [
        os.path.join(local_app, "Programs", "Python", "Python312", "python.exe"),
        os.path.join(local_app, "Programs", "Python", "Python311", "python.exe"),
        os.path.join(local_app, "Programs", "Python", "Python310", "python.exe"),
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p

    return "python"


def chay_lan_dau(py_cmd: str):
    """Quy trình cài đặt tài nguyên lần đầu tiên."""
    print("=" * 70)
    print("  👑 FACEBOOK TRAFFIC MASTER — THIẾT LẬP TÀI NGUYÊN LẦN ĐẦU TIÊN")
    print("=" * 70)
    print("\n[1/3] Đang kiểm tra cấu trúc thư mục ứng dụng...")

    thu_muc_can_thiet = [
        "du_lieu_traffic",
        "du_lieu_exel",
        "du_lieu_fb",
        "du_lieu_images",
        "du_lieu_luong",
        "du_lieu_reel",
        "music"
    ]
    for d in thu_muc_can_thiet:
        p = os.path.join(APP_DIR, d)
        if not os.path.exists(p):
            os.makedirs(p, exist_ok=True)
    print("  -> Cấu trúc thư mục: HOÀN TẤT.")

    # [2/3] Kiểm tra và cài đặt thư viện cần thiết
    print("\n[2/3] Đang kiểm tra và cài đặt các thư viện Python cần thiết...")
    req_file = os.path.join(APP_DIR, "requirements.txt")
    if os.path.exists(req_file):
        try:
            cmd = [py_cmd, "-m", "pip", "install", "-r", req_file, "--quiet"]
            print("  -> Đang nạp các gói hỗ trợ (vui lòng đợi 30-60 giây)...")
            res = subprocess.run(cmd, cwd=APP_DIR)
            if res.returncode == 0:
                print("  -> Thư viện Python: HOÀN TẤT.")
            else:
                print("  -> Cảnh báo cài đặt thư viện (tiến trình vẫn tiếp tục).")
        except Exception as e:
            print(f"  -> Bỏ qua cài đặt pip: {e}")

    # [3/3] Cài đặt trình duyệt Playwright Chromium
    print("\n[3/3] Đang tải và cài đặt trình duyệt cào bài Playwright Chromium...")
    print("  -> Quá trình này chỉ diễn ra duy nhất một lần (khoảng 1-2 phút)...")
    try:
        cmd_pw = [py_cmd, "-m", "playwright", "install", "chromium"]
        res_pw = subprocess.run(cmd_pw, cwd=APP_DIR)
        if res_pw.returncode == 0:
            print("  -> Trình duyệt cào bài: CÀI ĐẶT THÀNH CÔNG!")
        else:
            print("  -> Thử lệnh playwright cài đặt lần 2...")
            subprocess.run(["playwright", "install", "chromium"], cwd=APP_DIR)
    except Exception as e:
        print(f"  -> Lỗi khi tải chromium: {e}")

    # Tạo cờ đánh dấu đã cài đặt thành công
    with open(FLAG_FILE, "w", encoding="utf-8") as f:
        f.write(f"Installed at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    print("\n" + "=" * 70)
    print("  🎉 CHÚC MỪNG! BẠN ĐÃ THIẾT LẬP THÀNH CÔNG TOÀN BỘ TÀI NGUYÊN!")
    print("=" * 70)
    print("\n  👉 Từ bây giờ, bạn chỉ cần mở file FacebookTrafficMaster.exe (LẦN 2)")
    print("     để tự động mở giao diện web và sử dụng full tính năng!")
    print("\n" + "-" * 70)
    input("Nhấn Enter để đóng cửa sổ cài đặt...")


def giai_phong_tien_trinh_cu(port: int = PORT):
    """Tự động phát hiện và dọn dẹp sạch sẽ các terminal/tiến trình cũ bị treo đang chiếm port 5001."""
    try:
        out = subprocess.check_output('netstat -ano -p tcp', shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
        current_pid = os.getpid()
        killed = []
        for line in out.splitlines():
            line = line.strip()
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                try:
                    pid = int(parts[-1])
                    if pid != current_pid and pid > 0 and pid not in killed:
                        print(f"  🧹 Phát hiện phiên làm việc cũ (PID {pid}) đang chạy ngầm trên cổng {port}.")
                        print("     Đang tự động dọn dẹp và giải phóng tài nguyên...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        killed.append(pid)
                except (ValueError, IndexError):
                    pass
        if killed:
            time.sleep(0.8)
            print("  -> Đã giải phóng cổng kết nối sạch sẽ!")
    except Exception:
        pass


def chay_cac_lan_sau(py_cmd: str):
    """Quy trình khởi chạy WebUI từ lần 2 trở đi."""
    print("=" * 70)
    print("  🚀 FACEBOOK TRAFFIC MASTER PRO — ĐANG KHỞI CHẠY HỆ THỐNG...")
    print("=" * 70)
    print("\n  [1] Đang kiểm tra cổng kết nối và khởi tạo máy chủ...")

    # Tự động dọn dẹp mọi tiến trình cũ bị treo ngầm trên cổng 5001
    giai_phong_tien_trinh_cu(PORT)

    webui_file = os.path.join(APP_DIR, "webui.py")
    if not os.path.exists(webui_file):
        print(f"❌ Lỗi: Không tìm thấy file {webui_file}")
        input("Nhấn Enter để thoát...")
        return

    # Khởi chạy server webui.py
    proc = subprocess.Popen([py_cmd, webui_file], cwd=APP_DIR)

    # Đợi 2 giây cho web server khởi động xong
    time.sleep(2.5)

    print("  [2] Đang tự động mở trình duyệt web...")
    try:
        webbrowser.open(URL)
    except Exception:
        pass

    print("\n" + "=" * 70)
    print(f"  ✅ HỆ THỐNG ĐÃ SẴN SÀNG! ĐANG CHẠY TẠI:")
    print(f"     👉 {URL}")
    print("=" * 70)
    print("\n  💡 LƯU Ý QUAN TRỌNG:")
    print("     1. Giữ cửa sổ này luôn mở trong suốt quá trình bạn dùng tool.")
    print("     2. Để dừng tool, bạn chỉ cần đóng cửa sổ này hoặc bấm Ctrl + C.")
    print("\n" + "-" * 70)

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nĐang dừng hệ thống...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        print("Hệ thống đã dừng an toàn.")


def main():
    py_cmd = tim_lenh_python()

    if not os.path.exists(FLAG_FILE):
        # LẦN 1: Cài đặt tài nguyên cần thiết
        chay_lan_dau(py_cmd)
    else:
        # LẦN 2 TRỞ ĐI: Mở WebUI và tự bật trình duyệt
        chay_cac_lan_sau(py_cmd)


if __name__ == "__main__":
    main()
