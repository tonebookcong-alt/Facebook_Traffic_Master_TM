# -*- coding: utf-8 -*-
"""
CÔNG CỤ TẠO VÀ QUẢN LÝ BẢN QUYỀN CHO ADMIN (DÀNH RIÊNG CHO CHỦ TOOL)
- Tự động sinh key bản quyền
- Đẩy trực tiếp lên cơ sở dữ liệu Supabase qua RPC
- Hỗ trợ reset mã máy (Machine ID) khi khách đổi máy hoặc cài lại Win
"""

import sys
import json
import secrets
import urllib.request
import urllib.error
from datetime import datetime, timedelta

SUPABASE_URL = "https://pxgduaxqckpczkocqrig.supabase.co"
SUPABASE_KEY = "sb_publishable_sRf4Xscmpjc2nlPAnuKJcA_I7dGFMl5"
ADMIN_SECRET = "FTM_ADMIN_SECRET_2026"


def tao_key_ngau_nhien() -> str:
    """Sinh mã License Key định dạng: FTM-XXXX-XXXX-XXXX"""
    p1 = secrets.token_hex(2).upper()
    p2 = secrets.token_hex(2).upper()
    p3 = secrets.token_hex(2).upper()
    return f"FTM-{p1}-{p2}-{p3}"


def main():
    print("=" * 65)
    print("  👑 FACEBOOK TRAFFIC MASTER — TOOL CẤP BẢN QUYỀN (ADMIN)")
    print("=" * 65)

    print("\nChọn chức năng:")
    print("  1. Tạo License Key mới cho khách hàng")
    print("  2. Reset máy cho Key đã có (cho phép khách chuyển sang máy mới)")
    mode = input("Nhập lựa chọn [1-2] (Mặc định 1): ").strip() or "1"

    if mode == "2":
        target_key = input("\nNhập License Key cần reset máy: ").strip().upper()
        if not target_key:
            print("❌ Chưa nhập key!")
            return
        payload = {
            "p_admin_secret": ADMIN_SECRET,
            "p_license_key": target_key,
            "p_client_name": "Reset Machine",
            "p_plan": "vinh_vien",
            "p_expires_at": None,
            "p_note": "Reset mã máy bởi Admin"
        }
        _gui_rpc(payload, target_key, "Reset máy thành công! Khách có thể kích hoạt trên máy mới.")
        input("\nNhấn Enter để thoát...")
        return

    # Tạo key mới
    client_name = input("\nNhập tên khách hàng (vd: Nguyễn Văn A / FB: TungHa): ").strip()
    if not client_name:
        client_name = "Khách Hàng"

    print("\nChọn gói thời hạn:")
    print("  1. 1 Tháng (30 ngày)")
    print("  2. 3 Tháng (90 ngày)")
    print("  3. 6 Tháng (180 ngày)")
    print("  4. 1 Năm (365 ngày)")
    print("  5. Vĩnh Viễn (Trọn đời)")
    opt = input("Nhập số [1-5] (Mặc định 5): ").strip() or "5"

    now = datetime.utcnow()
    expires_at = None
    plan = "vinh_vien"

    if opt == "1":
        plan = "1_thang"
        expires_at = (now + timedelta(days=30)).isoformat() + "Z"
    elif opt == "2":
        plan = "3_thang"
        expires_at = (now + timedelta(days=90)).isoformat() + "Z"
    elif opt == "3":
        plan = "6_thang"
        expires_at = (now + timedelta(days=180)).isoformat() + "Z"
    elif opt == "4":
        plan = "1_nam"
        expires_at = (now + timedelta(days=365)).isoformat() + "Z"
    else:
        plan = "vinh_vien"
        expires_at = None

    note = input("Ghi chú thêm (vd: Giá 1tr, Zalo 09xx): ").strip()
    new_key = tao_key_ngau_nhien()

    payload = {
        "p_admin_secret": ADMIN_SECRET,
        "p_license_key": new_key,
        "p_client_name": client_name,
        "p_plan": plan,
        "p_expires_at": expires_at,
        "p_note": note
    }

    _gui_rpc(payload, new_key, f"Tạo bản quyền mới thành công! Khách: {client_name} ({plan.upper()})")

    sql_command = f"""INSERT INTO public.licenses (license_key, client_name, plan, expires_at, is_active, note)
VALUES ('{new_key}', '{client_name}', '{plan}', {'NULL' if not expires_at else f"'{expires_at}'"}, TRUE, '{note}')
ON CONFLICT (license_key) DO UPDATE SET machine_id = NULL;"""

    print("\n" + "=" * 65)
    print("🎉 THÔNG TIN BẢN QUYỀN CẤP CHO KHÁCH:")
    print(f"  👉 Tên khách hàng : {client_name}")
    print(f"  👉 Gói bản quyền  : {plan.upper()}")
    print(f"  👉 Hạn sử dụng    : {'Vĩnh viễn' if not expires_at else expires_at[:10]}")
    print(f"  🔑 LICENSE KEY    : {new_key}")
    print("=" * 65)
    print("\n💡 Câu lệnh SQL dự phòng (nếu cần dán trên Supabase SQL Editor):")
    print(sql_command)
    print("-" * 65)

    input("\nNhấn Enter để thoát...")


def _gui_rpc(payload: dict, key: str, success_msg: str):
    print("Đang đồng bộ lên cơ sở dữ liệu Supabase...")
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/rpc/admin_upsert_license",
            data=data,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if res_data.get("success"):
                print(f"✅ {success_msg}")
            else:
                print(f"⚠️ Supabase thông báo: {res_data.get('message')}")
    except Exception as e:
        print(f"⚠️ Lưu ý: Chưa nạp hàm admin_upsert_license trên Supabase hoặc lỗi mạng: {e}")


if __name__ == "__main__":
    main()
