# -*- coding: utf-8 -*-
"""Tool Chẩn Đoán Lỗi Hệ Thống & Kiểm Tra AI (1-Click Diagnostic)"""
import os
import sys
import json
import time
from datetime import datetime

DIR_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(DIR_ROOT, "KET_QUA_KIEM_TRA.txt")

lines = []
def log(s=""):
    print(s)
    lines.append(s)

log("=" * 70)
log("  🔍 FACEBOOK TRAFFIC MASTER — BẢNG CHẨN ĐOÁN LỖI TỰ ĐỘNG")
log(f"  Thời gian kiểm tra: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log(f"  Thư mục ứng dụng: {DIR_ROOT}")
log("=" * 70)

# 1. Kiểm tra cấu hình config.json
cfg_path = os.path.join(DIR_ROOT, "config.json")
ai_cfg = {}
if os.path.isfile(cfg_path):
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        ai_cfg = cfg.get("ai", {})
        log("\n[1] CẤU HÌNH AI TRONG CONFIG.JSON:")
        log(f"  - Provider: {ai_cfg.get('provider')}")
        log(f"  - Model: {ai_cfg.get('model')}")
        log(f"  - Base URL: {ai_cfg.get('base_url')}")
        log(f"  - Số luồng song song: {ai_cfg.get('song_song')}")
        key = ai_cfg.get("api_key", "")
        masked_key = (key[:6] + "..." + key[-4:]) if key else "CHƯA CÓ KEY"
        log(f"  - API Key: {masked_key}")
    except Exception as e:
        log(f"❌ Lỗi đọc config.json: {e}")
else:
    log("❌ KHÔNG TÌM THẤY file config.json!")

# 2. Kiểm tra phiên bản file prompt
log("\n[2] KIỂM TRA PHIÊN BẢN FILE PROMPT BÀI BÁO:")
for fn in ["promt bai bao us.txt", "promt bai bao global.txt"]:
    p = os.path.join(DIR_ROOT, "core", fn)
    if not os.path.isfile(p):
        p = os.path.join(DIR_ROOT, fn)
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read()
        so_dong = len(c.splitlines())
        la_moi = so_dong < 25
        trang_thai = "✅ BẢN MỚI TINH GỌN (Đạt chuẩn)" if la_moi else "⚠️ BẢN CŨ QUÁ TẢI (Nguyên nhân gây timeout 504!)"
        log(f"  - {fn}: {so_dong} dòng | {len(c)} ký tự -> {trang_thai}")
    else:
        log(f"  - {fn}: ❌ Không tìm thấy file!")

# 3. Test kết nối AI thực tế từ máy này
log("\n[3] THỰC NGHIỆM GỌI AI TRỰC TIẾP TỪ MÁY NÀY:")
try:
    import requests
    url = f"{ai_cfg.get('base_url', 'https://vyceai.com/v1').rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ai_cfg.get('api_key')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": ai_cfg.get("model", "deepseek-v4-flash"),
        "messages": [
            {"role": "system", "content": "You are a professional journalist. Write in American English."},
            {"role": "user", "content": "Write 2 short paragraphs about Buffalo Bills recent victory."}
        ],
        "max_tokens": 500,
        "stream": True
    }
    log(f"  -> Đang gửi yêu cầu test tới: {url} (Model: {payload['model']})...")
    t0 = time.time()
    resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=40)
    log(f"  -> HTTP Status Code: {resp.status_code}")
    
    if resp.status_code != 200:
        log(f"  ❌ Máy chủ trả về lỗi HTTP {resp.status_code}: {resp.text[:300]}")
    else:
        t_first = None
        chunks = 0
        err_stream = None
        for line in resp.iter_lines():
            if not line: continue
            dec = line.decode("utf-8", errors="ignore")
            if dec.startswith("data: "):
                d = dec[6:].strip()
                if d == "[DONE]": break
                if '"error":' in d:
                    err_stream = d
                    break
                if t_first is None:
                    t_first = time.time() - t0
                chunks += 1
        t_total = time.time() - t0
        if err_stream:
            log(f"  ❌ Lỗi trong luồng stream sau {t_total:.1f}s: {err_stream}")
        else:
            log(f"  🎉 KẾT QUẢ TEST: THÀNH CÔNG RỰC RỠ!")
            log(f"  - Thời gian token đầu tiên (TTFT): {t_first:.2f}s")
            log(f"  - Tổng thời gian hoàn thành: {t_total:.2f}s ({chunks} chunks)")
except Exception as e:
    log(f"  ❌ Ngoại lệ khi test AI: {e}")

log("\n" + "=" * 70)
log("  Hoàn tất kiểm tra! Đã lưu kết quả vào file KET_QUA_KIEM_TRA.txt.")
log("=" * 70)

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
