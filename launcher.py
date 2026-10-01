# -*- coding: utf-8 -*-
"""
FACEBOOK TRAFFIC MASTER — LAUNCHER (KHỞI ĐỘNG VIÊN THÔNG MINH)
- Tự động phát hiện Python trên máy, nếu thiếu tự động tải & cài đặt Python 3.12 chính thức
- Lần 1: Cài đặt tài nguyên, kiểm tra thư viện và tải Playwright Chromium
- Lần 2 trở đi: Dọn dẹp terminal cũ, mở server WebUI ngầm và tự bật trình duyệt web local http://127.0.0.1:5001
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


def kiem_tra_python_hoat_dong(cmd: str) -> bool:
    """Kiểm tra lệnh python có thực thi được và là Python 3 hay không."""
    if not cmd:
        return False
    try:
        res = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
        out = (res.stdout or "") + (res.stderr or "")
        return res.returncode == 0 and "Python 3." in out
    except Exception:
        return False


def tai_file_da_tang(url: str, target_path: str) -> bool:
    """Tải file từ internet với cơ chế đa tầng, tự động vượt lỗi SSL của Sandbox/máy mới."""
    # Tầng 1: Python urllib với unverified SSL context
    try:
        import urllib.request
        import ssl
        ctx = ssl._create_unverified_context()
        print("  -> Đang kết nối máy chủ tải về...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp, open(target_path, "wb") as out_f:
            tong_bytes = int(resp.headers.get("Content-Length") or 0)
            da_tai = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out_f.write(chunk)
                da_tai += len(chunk)
                if tong_bytes > 0:
                    pct = int(da_tai * 100 / tong_bytes)
                    mb = da_tai / (1024 * 1024)
                    tong_mb = tong_bytes / (1024 * 1024)
                    print(f"\r  -> Tiến độ tải: {pct}% ({mb:.1f} MB / {tong_mb:.1f} MB)...", end="", flush=True)
            print()
        if os.path.exists(target_path) and os.path.getsize(target_path) > 1000000:
            return True
    except Exception as e:
        print(f"\n  (Tầng 1 urllib gặp lỗi: {e}. Đang chuyển sang Tầng 2 curl...)")

    # Tầng 2: Dùng curl.exe tích hợp sẵn của Windows (cờ -k bỏ qua lỗi chứng chỉ SSL)
    try:
        cmd_curl = ["curl.exe", "-k", "-L", "-o", target_path, url]
        res = subprocess.run(cmd_curl, timeout=180)
        if res.returncode == 0 and os.path.exists(target_path) and os.path.getsize(target_path) > 1000000:
            return True
    except Exception:
        pass

    # Tầng 3: Dùng PowerShell bypass SSL
    try:
        ps = f"[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {{$true}}; (New-Object System.Net.WebClient).DownloadFile('{url}', '{target_path}')"
        res = subprocess.run(["powershell.exe", "-Command", ps], timeout=180)
        if res.returncode == 0 and os.path.exists(target_path) and os.path.getsize(target_path) > 1000000:
            return True
    except Exception:
        pass

    return False


def tu_dong_cai_dat_python() -> str:
    """Tự động tải và cài đặt Python 3.12 chính thức cho máy chưa có Python (hỗ trợ cả máy mới & Sandbox)."""
    print("=" * 70)
    print("  ⚠️ PHÁT HIỆN MÁY TÍNH NÀY CHƯA CÀI ĐẶT MÔI TRƯỜNG PYTHON 3.12!")
    print("=" * 70)
    print("\n  👉 Hệ thống đang tự động tải và cài đặt Python 3.12 từ python.org...")
    print("     (Quá trình chỉ mất khoảng 1-2 phút, tự động 100%)")

    installer_url = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
    installer_path = os.path.join(APP_DIR, "python_setup.exe")

    try:
        print("\n  [1/2] Đang tải bộ cài Python 3.12 chính thức...")
        ok_tai = tai_file_da_tang(installer_url, installer_path)
        if not ok_tai or not os.path.exists(installer_path):
            raise Exception("Không thể tải file bộ cài Python sau 3 tầng dự phòng.")

        print("  -> Tải hoàn tất.")

        print("\n  [2/2] Đang tự động cấu hình và cài đặt Python...")
        # Cài đặt tự động với cờ PrependPath=1, Include_pip=1
        cmd = [installer_path, "/passive", "InstallAllUsers=1", "PrependPath=1", "Include_pip=1"]
        subprocess.run(cmd, timeout=300)

        try:
            os.remove(installer_path)
        except Exception:
            pass

        # Quét lại các đường dẫn sau khi cài
        time.sleep(2)
        common_paths = [
            r"C:\Program Files\Python312\python.exe",
            r"C:\Python312\python.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python312", "python.exe"),
        ]
        for p in common_paths:
            if os.path.exists(p) and kiem_tra_python_hoat_dong(p):
                print("  🎉 ĐÃ CÀI ĐẶT THÀNH CÔNG PYTHON 3.12!")
                return p

        # Kiểm tra qua PATH
        if shutil.which("python") and kiem_tra_python_hoat_dong("python"):
            return "python"
    except Exception as e:
        print(f"\n  ❌ Không thể tự động cài đặt Python: {e}")
        print("  👉 Vui lòng vào https://www.python.org/downloads/ để cài đặt Python 3.12.")
        print("     (Lưu ý quan trọng: Nhớ tick chọn 'Add python.exe to PATH' khi cài đặt)")
        input("\nNhấn Enter để thoát...")
        sys.exit(1)

    return ""


def tim_lenh_python() -> str:
    """Tìm đường dẫn thực thi của Python trên máy (ưu tiên runtime nhúng sẵn -> máy khách -> tự cài)."""
    # 0. Ưu tiên số 1: Thư mục Python Portable nhúng sẵn trong tool (nếu có)
    portable_py = os.path.join(APP_DIR, "python_runtime", "python.exe")
    if os.path.exists(portable_py) and kiem_tra_python_hoat_dong(portable_py):
        return portable_py

    # 1. Nếu đang chạy script python
    if not getattr(sys, 'frozen', False):
        if kiem_tra_python_hoat_dong(sys.executable):
            return sys.executable

    # 2. Tìm trong PATH
    candidates = ["python", "python3", "py"]
    for c in candidates:
        py_path = shutil.which(c)
        if py_path and kiem_tra_python_hoat_dong(py_path):
            return py_path

    # 3. Thử các đường dẫn Python mặc định phổ biến trên Windows
    user_prof = os.environ.get("USERPROFILE", "")
    local_app = os.environ.get("LOCALAPPDATA", "")
    common_paths = [
        os.path.join(local_app, "Programs", "Python", "Python312", "python.exe"),
        os.path.join(local_app, "Programs", "Python", "Python311", "python.exe"),
        os.path.join(local_app, "Programs", "Python", "Python310", "python.exe"),
        r"C:\Program Files\Python312\python.exe",
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
    ]
    for p in common_paths:
        if os.path.exists(p) and kiem_tra_python_hoat_dong(p):
            return p

    # 4. Nếu hoàn toàn không tìm thấy Python hoạt động -> Tự động tải và cài đặt
    py_cai = tu_dong_cai_dat_python()
    if py_cai:
        return py_cai

    print("❌ Lỗi: Không thể khởi chạy do thiếu Python.")
    input("Nhấn Enter để thoát...")
    sys.exit(1)


def kiem_tra_thu_vien_day_du(py_cmd: str) -> bool:
    """Kiểm tra xem môi trường Python đã có đủ các thư viện cốt lõi hay chưa."""
    try:
        cmd = [py_cmd, "-c", "import flask, playwright, openpyxl, requests"]
        res = subprocess.run(cmd, capture_output=True, timeout=10)
        return res.returncode == 0
    except Exception:
        return False


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
            cmd = [
                py_cmd, "-m", "pip", "install", "-r", req_file,
                "--trusted-host", "pypi.org",
                "--trusted-host", "files.pythonhosted.org",
                "--trusted-host", "pypi.python.org",
                "--quiet"
            ]
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

    # Phân chia rạch ròi 2 lần chạy:
    # - Nếu chưa có file cờ installed.flag -> LẦN 1: Cài đặt tài nguyên và tạo cờ
    # - Nếu đã có file cờ installed.flag -> LẦN 2 TRỞ ĐI: Mở thẳng WebUI 5001
    if not os.path.exists(FLAG_FILE):
        chay_lan_dau(py_cmd)
    else:
        chay_cac_lan_sau(py_cmd)


if __name__ == "__main__":
    main()
