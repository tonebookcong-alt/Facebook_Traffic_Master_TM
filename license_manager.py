# -*- coding: utf-8 -*-
"""
Module Quản Lý Bản Quyền Thương Mại (License Manager)
- Khóa theo phần cứng máy tính (Machine ID duy nhất: CPU + Mainboard UUID)
- Xác thực trực tiếp qua cơ sở dữ liệu Supabase
- Khách hàng kích hoạt 1 lần duy nhất, dùng vĩnh viễn trên máy đó
- Chặn 100% việc copy sang máy khác
"""

import os
import sys
import json
import time
import hashlib
import platform
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

DIR_ROOT = os.path.dirname(os.path.abspath(__file__))
FILE_LICENSE = os.path.join(DIR_ROOT, "license.dat")
FILE_CONFIG = os.path.join(DIR_ROOT, "config.json")

SUPABASE_URL = "https://pxgduaxqckpczkocqrig.supabase.co"
SUPABASE_KEY = "sb_publishable_sRf4Xscmpjc2nlPAnuKJcA_I7dGFMl5"

SECRET_SALT = "FTM_SECURE_AUTH_2026_@_DEEPSEEK_TRAFFIC_FB"


def lay_ma_may() -> str:
    """Lấy Mã Máy phần cứng duy nhất của máy tính (Hardware Fingerprint)."""
    raw_parts = []
    
    # 1. Mainboard UUID
    try:
        out = subprocess.check_output(['wmic', 'csproduct', 'get', 'uuid'], stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
        lines = [line.strip() for line in out.splitlines() if line.strip() and 'uuid' not in line.lower()]
        if lines:
            raw_parts.append(lines[0])
    except Exception:
        pass

    # 2. CPU Processor ID
    try:
        out = subprocess.check_output(['wmic', 'cpu', 'get', 'processorid'], stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
        lines = [line.strip() for line in out.splitlines() if line.strip() and 'processorid' not in line.lower()]
        if lines:
            raw_parts.append(lines[0])
    except Exception:
        pass

    # Fallback nếu wmic bị chặn
    if not raw_parts:
        try:
            ps_cmd = "(Get-CimInstance Win32_ComputerSystemProduct).UUID"
            out = subprocess.check_output(['powershell', '-NoProfile', '-Command', ps_cmd], stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
            val = out.strip()
            if val:
                raw_parts.append(val)
        except Exception:
            pass

    if not raw_parts:
        raw_parts.append(platform.node())
        raw_parts.append(platform.machine())

    combined = "|".join(raw_parts)
    h = hashlib.sha256(combined.encode('utf-8')).hexdigest().upper()
    return f"FTM-{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"


def _tao_chu_ky(data: dict) -> str:
    """Tạo chữ ký băm chống chỉnh sửa file license thủ công."""
    str_data = f"{data.get('license_key')}|{data.get('machine_id')}|{data.get('plan')}|{data.get('expires_at')}|{SECRET_SALT}"
    return hashlib.sha256(str_data.encode('utf-8')).hexdigest()


def doc_license_cuc_bo() -> dict:
    """Đọc thông tin bản quyền đã lưu trên máy."""
    if not os.path.exists(FILE_LICENSE):
        return {}
    try:
        with open(FILE_LICENSE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Kiểm tra chữ ký chống sửa
        sig = data.get("signature")
        if not sig or sig != _tao_chu_ky(data):
            return {}
        return data
    except Exception:
        return {}


def luu_license_cuc_bo(data: dict):
    """Lưu bản quyền vào file license.dat."""
    data["signature"] = _tao_chu_ky(data)
    data["updated_at"] = datetime.now().isoformat()
    with open(FILE_LICENSE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def lay_ma_nhan_dien_hien_tai() -> str:
    """Đọc mã nhận diện (tiền tố tiêu đề bài báo) từ config hoặc license."""
    lic = doc_license_cuc_bo()
    if lic.get("ma_nhan_dien"):
        return lic["ma_nhan_dien"].strip()

    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                c = json.load(f)
            return (c.get("ma_nhan_dien") or "").strip()
        except Exception:
            pass
    return ""


def cap_nhat_ma_nhan_dien(ma: str):
    """Lưu mã nhận diện vào file config.json và license."""
    ma = ma.strip()
    # 1. Lưu config
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                c = json.load(f)
            c["ma_nhan_dien"] = ma
            with open(FILE_CONFIG, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # 2. Lưu license
    lic = doc_license_cuc_bo()
    if lic:
        lic["ma_nhan_dien"] = ma
        luu_license_cuc_bo(lic)


def kiem_tra_ban_quyen(force_online: bool = False) -> dict:
    """
    Kiểm tra trạng thái bản quyền của máy hiện tại.
    Trả về dict:
    {
        "valid": True/False,
        "message": "...",
        "client_name": "...",
        "plan": "...",
        "expires_at": "...",
        "ma_nhan_dien": "...",
        "machine_id": "..."
    }
    """
    current_machine_id = lay_ma_may()
    lic = doc_license_cuc_bo()

    if not lic or not lic.get("license_key"):
        return {
            "valid": False,
            "message": "Chưa kích hoạt bản quyền. Vui lòng nhập License Key!",
            "machine_id": current_machine_id,
            "ma_nhan_dien": lay_ma_nhan_dien_hien_tai()
        }

    # Kiểm tra khóa máy: nếu máy hiện tại khác mã máy đã lưu -> CHẶN NGAY
    if lic.get("machine_id") and lic.get("machine_id") != current_machine_id:
        return {
            "valid": False,
            "message": "Bản quyền này đã được kích hoạt trên máy tính khác! Không thể dùng chung.",
            "machine_id": current_machine_id,
            "ma_nhan_dien": lay_ma_nhan_dien_hien_tai()
        }

    license_key = lic.get("license_key")
    ma_nhan_dien = lic.get("ma_nhan_dien") or lay_ma_nhan_dien_hien_tai()

    # Kiểm tra online với Supabase (hoặc khi yêu cầu kiểm tra online)
    online_checked = False
    try:
        payload = json.dumps({
            "p_key": license_key,
            "p_machine_id": current_machine_id
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/rpc/check_or_activate_license",
            data=payload,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            online_checked = True

            if not data.get("success"):
                return {
                    "valid": False,
                    "message": data.get("message") or "Bản quyền không hợp lệ!",
                    "machine_id": current_machine_id,
                    "ma_nhan_dien": ma_nhan_dien
                }

            # Cập nhật thông tin mới nhất từ Supabase vào file cục bộ
            lic["client_name"] = data.get("client_name") or lic.get("client_name", "")
            lic["plan"] = data.get("plan") or lic.get("plan", "vinh_vien")
            lic["expires_at"] = data.get("expires_at")
            lic["machine_id"] = current_machine_id
            lic["ma_nhan_dien"] = ma_nhan_dien
            luu_license_cuc_bo(lic)

            return {
                "valid": True,
                "message": "Bản quyền hợp lệ",
                "client_name": lic.get("client_name"),
                "plan": lic.get("plan"),
                "expires_at": lic.get("expires_at"),
                "ma_nhan_dien": ma_nhan_dien,
                "machine_id": current_machine_id
            }
    except Exception as e:
        # Nếu mất mạng internet hoặc timeout, sử dụng cache cục bộ (nếu còn hạn)
        if not online_checked:
            # Kiểm tra ngày hết hạn cục bộ nếu có
            exp_str = lic.get("expires_at")
            if exp_str:
                try:
                    exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                    if exp_dt < datetime.now(exp_dt.tzinfo):
                        return {
                            "valid": False,
                            "message": "Bản quyền đã hết hạn sử dụng!",
                            "machine_id": current_machine_id,
                            "ma_nhan_dien": ma_nhan_dien
                        }
                except Exception:
                    pass

            return {
                "valid": True,
                "message": "Bản quyền hợp lệ (Chế độ Offline)",
                "client_name": lic.get("client_name"),
                "plan": lic.get("plan"),
                "expires_at": lic.get("expires_at"),
                "ma_nhan_dien": ma_nhan_dien,
                "machine_id": current_machine_id
            }

    return {
        "valid": False,
        "message": "Không thể xác thực bản quyền.",
        "machine_id": current_machine_id,
        "ma_nhan_dien": ma_nhan_dien
    }


def kich_hoat_ban_quyen(license_key: str, ma_nhan_dien: str) -> dict:
    """
    Kích hoạt License Key lần đầu tiên trên máy tính này.
    Gắn chặt Machine ID vào bản quyền trên Supabase.
    """
    license_key = (license_key or "").strip()
    ma_nhan_dien = (ma_nhan_dien or "").strip()
    current_machine_id = lay_ma_may()

    if not license_key:
        return {"ok": False, "message": "Vui lòng nhập License Key!"}
    if not ma_nhan_dien:
        return {"ok": False, "message": "Vui lòng nhập Mã nhận diện (ví dụ: TH)!"}

    try:
        payload = json.dumps({
            "p_key": license_key,
            "p_machine_id": current_machine_id
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/rpc/check_or_activate_license",
            data=payload,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            }
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("success"):
            return {
                "ok": False,
                "message": data.get("message") or "Kích hoạt thất bại. Vui lòng kiểm tra lại key!"
            }

        # Lưu bản quyền vào file cục bộ
        lic_data = {
            "license_key": license_key,
            "machine_id": current_machine_id,
            "ma_nhan_dien": ma_nhan_dien,
            "client_name": data.get("client_name") or "",
            "plan": data.get("plan") or "vinh_vien",
            "expires_at": data.get("expires_at"),
            "activated_at": datetime.now().isoformat()
        }
        luu_license_cuc_bo(lic_data)

        # Cập nhật mã nhận diện vào config.json
        cap_nhat_ma_nhan_dien(ma_nhan_dien)

        return {
            "ok": True,
            "message": "Kích hoạt bản quyền thành công!",
            "client_name": lic_data["client_name"],
            "plan": lic_data["plan"],
            "expires_at": lic_data["expires_at"],
            "ma_nhan_dien": ma_nhan_dien
        }
    except urllib.error.HTTPError as e:
        return {"ok": False, "message": f"Lỗi kết nối máy chủ Supabase: HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "message": f"Không thể kết nối máy chủ xác thực: {e}"}
