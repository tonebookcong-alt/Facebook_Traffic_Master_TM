#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GIAO DIỆN WEB UI QUẢN LÝ TOÀN DIỆN TOOL TRAFFIC FACEBOOK (4 TAB).

Chạy:  python webui.py
Mở:    IP mạng LAN của máy, cổng 5001 (VD: http://192.168.1.204:5001)
       — tự dò và tự mở trình duyệt khi chạy `python webui.py`

- Tab 1: 📥 CÀO DỮ LIỆU (Playwright, Cookies, Realtime SSE)
- Tab 2: 📋 KHO BÀI VIẾT / CONTENT POOL (Lọc, Checkbox Chọn tất cả, Xử lý hàng loạt)
- Tab 3: ✍️ XỬ LÝ AI & ẢNH (viết 1 Caption viral, Sửa trực tiếp, Bài báo 1500-1700 từ, Crop ảnh)
- Tab 4: 📦 BÀI SẴN SÀNG ĐĂNG (Copy 1-click cho Antidetect Browser, Mở Folder máy tính)
"""

import glob
import json
import os
import queue
import re
import subprocess
import threading
import time
import webbrowser
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from itertools import count

from flask import (Flask, Response, jsonify, render_template, request,
                   send_file, send_from_directory)

from config import DUONG_DAN, load_config, ghi_config
from google_sheets import lay_store
import scraper
import luong_b
import dong_goi
from viet_lai import viet_3_caption, viet_bai_bao, viet_bai_bao_va_title
import viet_lai
from media import chuan_bi_media, xu_ly_anh
import reel
import kiem_tra_bai_no
from ai_client import kiem_tra_api_key
from vung import (CAC_VUNG, GLOBAL, TEN_NGAN, TEN_VUNG, US, chuan_vung,
                  dat_vung, doc_kho_nguon, duong_dan_danh_ba, duong_dan_master,
                  duong_dan_nguon, lay_vung, thu_muc_excel, vung_cua_bai)

app = Flask(__name__)


# ===================================================================
# VÙNG DỮ LIỆU (🇺🇸 US / 🌍 GLOBAL) — helpers dùng chung cho mọi API
# ===================================================================
def _vung_cua_request(data=None) -> str:
    """Vùng của 1 request: JSON body → query string → vùng đang chọn.

    Backend LUÔN có giá trị mặc định (vùng đã lưu trong file), nên các cuộc gọi
    cũ không truyền `vung` vẫn chạy đúng như trước — không broken change."""
    if isinstance(data, dict):
        v = data.get("vung") or data.get("Vung") or data.get("region")
        if v:
            return chuan_vung(v)
    v = request.args.get("vung") if request else None
    if v:
        return chuan_vung(v)
    return lay_vung()


def _dang_bat_ky_chay() -> bool:
    """True nếu đang có tiến trình cào/AI/full-auto/ảnh/reel chạy (khoá đổi vùng)."""
    for ten in ("TRANG_THAI", "BATCH_STATUS", "ANH_STATUS", "REEL_STATUS", "FULL_AUTO"):
        try:
            if globals()[ten].get("dang_chay"):
                return True
        except Exception:
            pass
    try:
        if HEN_GIO.bat and HEN_GIO.dang_chay:
            return True
    except Exception:
        pass
    return False


@app.route("/api/vung", methods=["GET"])
def api_lay_vung():
    """Vùng đang chọn + số liệu của nó (nguồn / bài trong pool) cho công tắc UI."""
    v = _vung_cua_request()
    ds_nguon = doc_kho_nguon(v)
    try:
        pool = lay_store().lay_tat_ca("CONTENT POOL")
    except Exception:
        pool = []
    ds_pool = [d for d in pool if vung_cua_bai(d) == v]
    hoan_thanh = sum(1 for d in ds_pool if str(d.get("Status") or "").upper() == "HOAN_THANH")
    return jsonify({
        "ok": True,
        "vung": v,
        "ten": TEN_VUNG[v],
        "cac_vung": [{"vung": x, "ten": TEN_VUNG[x]} for x in CAC_VUNG],
        "dang_chay": _dang_bat_ky_chay(),
        "thong_ke": {
            "so_nguon": len(ds_nguon),
            "so_key": len({str(r.get("KEY") or "").strip() for r in ds_nguon
                           if str(r.get("KEY") or "").strip()}),
            "so_bai": len(ds_pool),
            "so_hoan_thanh": hoan_thanh,
        },
        "duong_dan": {
            "nguon": os.path.basename(duong_dan_nguon(v)),
            "danh_ba": os.path.basename(duong_dan_danh_ba(v)),
            "danh_ba_ton_tai": os.path.exists(duong_dan_danh_ba(v)),
            "master": os.path.basename(duong_dan_master(v)),
            "excel": os.path.basename(thu_muc_excel(v)),
        },
    })


@app.route("/api/vung/dat", methods=["POST"])
def api_dat_vung():
    """Công tắc vùng: chuyển kho nguồn + toàn bộ danh sách sang US hoặc GLOBAL.
    Cho phép chuyển đổi giao diện tự do ngay cả khi cào / AI đang chạy ngầm."""
    data = request.json or {}
    v = chuan_vung(data.get("vung"))
    if not data.get("vung"):
        return jsonify({"ok": False, "loi": "Thiếu tham số vung ('us' | 'global')"}), 400
    dat_vung(v)
    ds = doc_kho_nguon(v)
    note_chay = ""
    if _dang_bat_ky_chay():
        note_chay = " (Tiến trình cào/AI ngầm vẫn tiếp tục hoạt động độc lập)"
    if not ds:
        return jsonify({"ok": True, "vung": v, "ten": TEN_VUNG[v],
                        "loi": f"Kho nguồn của vùng {TEN_VUNG[v]} đang trống — "
                               f"cần nạp {os.path.basename(duong_dan_nguon(v))}"})
    return jsonify({"ok": True, "vung": v, "ten": TEN_VUNG[v],
                    "so_nguon": len(ds),
                    "message": f"Đã chuyển sang {TEN_VUNG[v]} — {len(ds)} nguồn cào{note_chay}"})



@app.after_request
def chong_cache_api(resp):
    """Chặn trình duyệt cache response API — tránh WebUI hiển thị dữ liệu CŨ
    (caption dính "Chiefs Dynasty Fans…") sau khi file đã được sửa."""
    if request.path.startswith("/api/") or resp.mimetype == "application/json" \
            or resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


# ---------------- Trạng thái chung Luồng Cào ----------------
QUEUE_SU_KIEN = queue.Queue()
LISTENERS = []                        # mỗi kết nối SSE 1 queue riêng
STOP_EVENT = threading.Event()
KHOA = threading.Lock()

# ---- Bộ đệm sự kiện: cho phép F5 / vào lại web vẫn xem được tiến độ + log ----
DUONG_DAN_LOG = os.path.join(DUONG_DAN, "du_lieu_traffic", "log_chay.jsonl")
DEM_SU_KIEN = count(1)                 # số thứ tự tăng dần cho mỗi sự kiện
BO_DEM_SU_KIEN = deque(maxlen=4000)    # vòng đệm sự kiện gần nhất (RAM)
KHOA_LOG = threading.Lock()


def _ghi_log_dia(su_kien: dict):
    """Ghi sự kiện ra file jsonl để không mất log khi tắt web / khởi động lại."""
    try:
        os.makedirs(os.path.dirname(DUONG_DAN_LOG), exist_ok=True)
        with open(DUONG_DAN_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(su_kien, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _doc_log_dia(so_dong=800):
    """Đọc N dòng cuối file log trên đĩa."""
    try:
        if not os.path.exists(DUONG_DAN_LOG):
            return []
        with open(DUONG_DAN_LOG, "r", encoding="utf-8", errors="replace") as fh:
            dong = fh.readlines()[-so_dong:]
        kq = []
        for d in dong:
            try:
                kq.append(json.loads(d))
            except Exception:
                pass
        return kq
    except Exception:
        return []


def _xoa_log_dia():
    try:
        if os.path.exists(DUONG_DAN_LOG):
            os.remove(DUONG_DAN_LOG)
    except Exception:
        pass


def _mo_dang_ky() -> queue.Queue:
    """Tạo kênh nhận sự kiện riêng cho 1 kết nối SSE (nhiều tab không giành log)."""
    q = queue.Queue(maxsize=5000)
    with KHOA:
        LISTENERS.append(q)
    return q


def _dong_dang_ky(q: queue.Queue):
    with KHOA:
        if q in LISTENERS:
            LISTENERS.remove(q)


def _lam_sach_dang_ky():
    """Dọn sự kiện tồn của mọi kênh đang mở (gọi khi bắt đầu phiên chạy mới)."""
    with KHOA:
        for q in LISTENERS:
            try:
                while True:
                    q.get_nowait()
            except Exception:
                pass

TRANG_THAI = {
    "dang_chay": False,
    "xong": False,
    "trang_ho": [],
    "trang_hien_tai": None,
    "so_bai": 0,
    "so_anh": 0,
    "xlsx": None,
    "thong_bao": None,
    # --- tiến độ / ETA ---
    "bat_dau": None, "giay_da_chay": 0, "phan_tram": 0,
    "con_lai": None, "ket_thuc_du_kien": None,
}

# ---------------- Trạng thái Xử lý Hàng loạt ----------------
BATCH_STATUS = {
    "dang_chay": False,
    "tong_so": 0,
    "da_xong": 0,
    "thanh_cong": 0,
    "dang_xu_ly": "",
    "loi": [],
    "hoan_thanh": False,
}

# Khóa bảo vệ BATCH_STATUS khi song song hóa + số bài xử lý đồng thời.
_BATCH_LOCK = threading.Lock()


def _so_luong_song_song() -> int:
    """Số bài xử lý AI đồng thời (config ai.song_song, mặc định 3)."""
    try:
        return max(1, int(load_config().get("ai", {}).get("song_song", 3)))
    except Exception:
        return 3

# ---------------- Trạng thái Cắt ảnh (Tab 4) ----------------
ANH_STATUS = {
    "dang_chay": False,
    "tong_so": 0,
    "da_xong": 0,
    "dang_xu_ly": "",
    "loi": [],
    "hoan_thanh": False,
}

# ---------------- Trạng thái Tạo Reel (Tab 4) ----------------
REEL_STATUS = {
    "dang_chay": False,
    "tong_so": 0,
    "da_xong": 0,
    "dang_xu_ly": "",
    "loi": [],
    "hoan_thanh": False,
}


def cap_nhat(**kw):
    with KHOA:
        TRANG_THAI.update(kw)


def _cap_tien_do_scrape():
    """Tính % tiến độ + ETA cho luồng cào thường (TRANG_THAI).

    Ước lượng theo số trang đã xong / tổng trang (mỗi trang cào 1 lần).
    """
    with KHOA:
        bat_dau = TRANG_THAI.get("bat_dau")
        if not bat_dau:
            return
        try:
            t0 = datetime.fromisoformat(bat_dau)
            da = (datetime.now() - t0).total_seconds()
            TRANG_THAI["giay_da_chay"] = int(da)
            ds_trang = TRANG_THAI.get("trang_ho") or []
            hien_tai = TRANG_THAI.get("trang_hien_tai")
            tong_trang = len(ds_trang)
            if tong_trang and hien_tai in ds_trang:
                thu_tu = ds_trang.index(hien_tai)          # 0-based
                # trang đang cào tính nửa chặng
                tien_do = (thu_tu + 0.5) / tong_trang
                TRANG_THAI["phan_tram"] = min(99, int(tien_do * 100))
                if thu_tu > 0 and da > 0:
                    tb = da / thu_tu                        # giây/trang
                    con = int(tb * (tong_trang - thu_tu))
                    TRANG_THAI["con_lai"] = con
                    TRANG_THAI["ket_thuc_du_kien"] = (
                        datetime.now() + timedelta(seconds=con)
                    ).strftime("%H:%M:%S")
        except Exception:
            pass


def emit(su_kien: dict):
    """Phát sự kiện tới SSE + lưu vào bộ đệm & file log (chống mất khi F5/tắt tab)."""
    su_kien = dict(su_kien)
    su_kien["seq"] = next(DEM_SU_KIEN)
    su_kien["gio"] = datetime.now().strftime("%H:%M:%S")
    with KHOA_LOG:
        BO_DEM_SU_KIEN.append(su_kien)
        _ghi_log_dia(su_kien)
    with KHOA:
        for q in LISTENERS:
            try:
                q.put_nowait(su_kien)
            except Exception:
                pass


def _nap_vao_pool(ket_qua, store, ban_do_nguon=None, vung: str = None):
    """Nạp các bài cào được vào Content Pool — dùng chung cho luồng cào và luồng full.

    Trả về (số bài nạp mới, nhãn phiên cào). Nhãn phiên để các bước sau
    (AI / Hoàn thành / xuất Excel) chỉ làm việc với đúng bài của lần chạy này,
    không lẫn bài cũ đang còn dở trong kho.

    `vung`: 'us' | 'global' — mọi bài nạp ở lần này gắn nhãn vùng này
    (mặc định = vùng đang chọn; chống trùng cũng chỉ so trong vùng).

    `ban_do_nguon`: dict tên trang nguồn → (KEY, Nhân vật gợi ý) đọc từ
    kho nguồn của vùng. Có KEY/gợi ý của nguồn thì dùng làm KEY của bài và
    truyền gợi ý cho AI nhận diện nhân vật; không có thì giữ hành vi cũ."""
    from content_pool import chong_trung, them_content, chuan_hoa_text
    from nhan_dien import nhan_dien_nhan_vat
    from vung import chuan_vung as _chuan_vung
    v = _chuan_vung(vung) if vung else lay_vung()
    phien = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 1 lần cào = 1 phiên
    tong_nap = 0
    for trang, ds_bai in ket_qua.items():
        if not ds_bai:
            continue
        thong_tin = (ban_do_nguon or {}).get(trang) or (ban_do_nguon or {}).get(trang.strip())
        key_nguon = (thong_tin[0] if thong_tin else "") or "Facebook"
        goi_y = [g.strip() for g in (thong_tin[1] if thong_tin else "").split(",") if g.strip()]
        import cao_fb
        bai_co_chu = [b for b in ds_bai if cao_fb.la_caption_hop_le(b.get("text") or "")]
        bai_moi = chong_trung(bai_co_chu, store, phien=phien, vung=v)
        for b in bai_moi:
            txt = (b.get("text") or "").strip()
            try:
                nv = nhan_dien_nhan_vat(txt, key_nguon, goi_y)
            except Exception:
                nv = "Chung"
            them_content(b, key_nguon, nv, trang, store, phien=phien, vung=v)
            tong_nap += 1
    return tong_nap, phien


# ===================================================================
# 1. API TAB 1: CÀO DỮ LIỆU (SCRAPER)
# ===================================================================
def luu_cau_hinh_proxy(data: dict):
    """Lưu 3 ô proxy trên Tab 1 vào config.json (đồng bộ cho mọi luồng/Tab).

    data: {proxies, ty_le (%), bat_proxy (bool)}. Thiếu -> giữ nguyên giá trị cũ.
    """
    try:
        cfg = load_config()
        px = cfg.setdefault("proxy", {})
        if "proxies" in data:
            px["proxies_file"] = str(data.get("proxies") or "").strip()
        if "bat_proxy" in data:
            px["bat"] = bool(data.get("bat_proxy"))
        if "ty_le" in data:
            try:
                tl = float(data.get("ty_le"))
                if tl > 1:                      # người dùng nhập 50 -> 0.5
                    tl = tl / 100.0
                px["ti_le_phien"] = min(max(tl, 0.0), 0.95)
            except Exception:
                pass
        ghi_config(cfg)
    except Exception as e:
        print(f"[!] Không lưu được cấu hình proxy: {e}")


def _canh_bao_phien_chet() -> str:
    """Chuỗi cảnh báo (rỗng nếu không có) nếu lần cào vừa rồi có PHIÊN CÀO
    bị Facebook từ chối. QUAN TRỌNG: khi đó '0 bài' KHÔNG có nghĩa là
    'trang hết bài' hay 'trang lỗi' — mà là cookie đăng nhập đã bị vô hiệu hóa."""
    phien_chet = getattr(scraper, "PHIEN_TU_CHOI_LAN_CAO", []) or []
    if not phien_chet:
        return ""
    return (" ⚠ PHIÊN CÀO " + ", ".join(phien_chet) + " BỊ FACEBOOK TỪ CHỐI "
            "(cookie đăng nhập hết hạn / bị vô hiệu hóa) — các trang của phiên đó "
            "chỉ xem được BẢN KHÁCH (1-3 bài, cuộn không ăn), KHÔNG phải trang lỗi "
            "hay 'trang hết bài'. Mở Facebook bằng trình duyệt thường → đăng nhập "
            "lại → xuất lại file cookies.txt rồi chạy tiếp.")


def tham_so_proxy(data: dict):
    """Đọc 3 tham số proxy từ request -> kwargs cho scraper.run_cào."""
    try:
        tl = float(data.get("ty_le") or 50)
        if tl > 1:
            tl = tl / 100.0
    except Exception:
        tl = 0.5
    bat = data.get("bat_proxy")
    if bat is not None and not bat:
        duong = False                        # bỏ tick "Dùng proxy" -> IP máy
    elif "proxies" in data:
        duong = str(data.get("proxies") or "").strip() or False
    else:
        duong = None                         # không gửi gì -> theo config.json
    return {"proxies_path": duong, "ti_le_phien": min(max(tl, 0.0), 0.95)}


def chay_scraper(trang_ho, per_page, pages, delay, cookies, no_images,
                 proxy_kwargs=None, nhom_key="", vung=None):
    """Cào Tab 1 → nạp pool theo `vung` (mặc định: vùng đang bật lúc CẤM NÚT)."""
    vung = chuan_vung(vung)

    def cb(s):
        emit(s)
        if s.get("loai") == "trang_bat_dau":
            cap_nhat(trang_hien_tai=s.get("page"), xong=False, thong_bao=None)
        elif s.get("loai") == "post":
            with KHOA:
                TRANG_THAI["so_bai"] += 1
        elif s.get("loai") == "anh":
            with KHOA:
                TRANG_THAI["so_anh"] += 1

    try:
        # Không nhập trang → lấy nguồn từ kho (lọc nhóm KEY nếu có)
        ban_do_nguon = {}
        if not trang_ho:
            trang_ho, ban_do_nguon = _doc_nguon_tu_kho(nhom_key, vung)
            if not trang_ho:
                emit({"loai": "log", "noi_dung": f"❌ Kho nguồn vùng {TEN_VUNG[vung]} trống — thêm vào source_config của vùng hoặc nhập trang trong Tab 1"})
                return
            emit({"loai": "log", "noi_dung": f"📚 [{TEN_VUNG[vung]}] Lấy {len(trang_ho)} nguồn từ kho (chủ đề: {(nhom_key or 'ALL').replace(';', ', ')})"})
        emit({"loai": "log", "noi_dung": f"🚀 Bắt đầu cào {len(trang_ho)} trang..."})
        ket_qua, xlsx_path = scraper.run_cào(
            trang_ho, pages=pages, per_page=per_page, output="du_lieu",
            no_images=no_images, cookies=cookies, delay=delay,
            callback=cb, stop_flag=STOP_EVENT,
            bo_qua_bai_cu=True, **(proxy_kwargs or {}),
        )
        so_bai = sum(len(p) for p in ket_qua.values())
        canh_bao_chet = _canh_bao_phien_chet()

        # Tự động nạp các bài cào được vào Content Pool (Tab 2)
        store = lay_store()
        tong_nap_pool, _ = _nap_vao_pool(ket_qua, store, ban_do_nguon=ban_do_nguon,
                                         vung=vung)

        thong_bao_xong = (f"✅ Hoàn thành: Cào được {so_bai} bài viết "
                          f"(+{tong_nap_pool} bài mới nạp kho {TEN_VUNG[vung]} — Tab 2)"
                          + canh_bao_chet)
        cap_nhat(dang_chay=False, xong=True, trang_hien_tai=None, xlsx=xlsx_path,
                 thong_bao=thong_bao_xong)
        emit({"loai": "xong", "so_bai": so_bai, "so_trang": len(ket_qua), "xlsx": xlsx_path, "nap_pool": tong_nap_pool})
        emit({"loai": "log", "noi_dung": f"\n🎉 {thong_bao_xong}"})
        emit({"loai": "log", "noi_dung": f"📊 File Excel đã tạo tại: {xlsx_path}"})
    except Exception as e:
        cap_nhat(dang_chay=False, xong=True, thong_bao=f"❌ Lỗi: {e}")
        emit({"loai": "loi", "noi_dung": str(e)})
        emit({"loai": "log", "noi_dung": f"❌ Lỗi trong quá trình cào: {e}"})
        emit({"loai": "xong", "so_bai": TRANG_THAI["so_bai"]})


def chay_ca_luong(trang_ho, per_page, pages, delay, cookies, no_images,
                  format_type, proxy_kwargs=None, nhom_key="", web="", vung=None):
    """Luồng FULL: Cào → nạp pool → viết lại (AI) từng bài mới → chỉnh ảnh → đóng gói CSV.

    `vung` chốt ngay lúc bấm nút: nguồn cào, nhãn vùng khi nạp pool và web đăng bài
    đều lấy từ vùng đó (web phải trùng vùng — đã kiểm ở route)."""
    vung = chuan_vung(vung or web or US)
    web = vung

    def cb(s):
        emit(s)
        if s.get("loai") == "trang_bat_dau":
            cap_nhat(trang_hien_tai=s.get("page"), xong=False, thong_bao=None)
        elif s.get("loai") == "post":
            with KHOA:
                TRANG_THAI["so_bai"] += 1
        elif s.get("loai") == "anh":
            with KHOA:
                TRANG_THAI["so_anh"] += 1

    try:
        store = lay_store()
        # Không nhập trang → lấy nguồn từ kho (lọc nhóm KEY nếu có)
        ban_do_nguon = {}
        if not trang_ho:
            trang_ho, ban_do_nguon = _doc_nguon_tu_kho(nhom_key, vung)
            if not trang_ho:
                emit({"loai": "log", "noi_dung": f"❌ Kho nguồn vùng {TEN_VUNG[vung]} trống — thêm nguồn hoặc nhập trang trong Tab 1"})
                cap_nhat(dang_chay=False, xong=True, thong_bao="❌ Không có nguồn để cào (kho trống)")
                return
            emit({"loai": "log", "noi_dung": f"📚 [{TEN_VUNG[vung]}] Lấy {len(trang_ho)} nguồn từ kho (chủ đề: {(nhom_key or 'ALL').replace(';', ', ')})"})
        # Nhớ các bài ĐÃ có trước khi cào → chỉ xử lý các bài MỚI vừa nạp
        truoc = {str(d.get("Content ID") or "").strip()
                 for d in store.lay_tat_ca("CONTENT POOL")}

        emit({"loai": "log", "noi_dung": f"⚡ CHẠY CẢ LUỒNG — cào {len(trang_ho)} trang..."})
        ket_qua, xlsx_path = scraper.run_cào(
            trang_ho, pages=pages, per_page=per_page, output="du_lieu",
            no_images=no_images, cookies=cookies, delay=delay,
            callback=cb, stop_flag=STOP_EVENT,
            bo_qua_bai_cu=True, **(proxy_kwargs or {}),
        )
        so_cao = sum(len(p) for p in ket_qua.values())
        canh_bao_chet = _canh_bao_phien_chet()
        nap, _ = _nap_vao_pool(ket_qua, store, ban_do_nguon=ban_do_nguon, vung=vung)
        emit({"loai": "log", "noi_dung": f"✅ Cào xong: {so_cao} bài (+{nap} bài mới nạp kho {TEN_VUNG[vung]})."
              + canh_bao_chet})

        # Bài MỚI vừa nạp: Content ID chưa có trong `truoc`
        sau = {str(d.get("Content ID") or "").strip()
               for d in store.lay_tat_ca("CONTENT POOL")}
        bai_moi_ids = [c for c in sau if c and c not in truoc]

        emit({"loai": "log", "noi_dung": f"✍️ Viết lại + chỉnh ảnh {len(bai_moi_ids)} bài mới..."})
        ok = 0
        for i, cid in enumerate(bai_moi_ids, 1):
            emit({"loai": "log", "noi_dung": f"[{i}/{len(bai_moi_ids)}] Đang xử lý {cid}..."})
            try:
                res = luong_b.xu_ly_ai_mot_bai(cid, format_type=format_type, web=web)
                if res.get("success"):
                    ok += 1
            except Exception as e:
                emit({"loai": "log", "noi_dung": f"  [!] Lỗi {cid}: {e}"})

        # Bài ĐÃ xử lý (WEB_POSTED/DONE) nhưng mất file ảnh/bo_bai (folder cũ bị xóa)
        # → dựng lại ảnh (logo+viền) KHÔNG chạy lại AI, để CSV có đường dẫn ảnh.
        goi_co = set(dong_goi._doc_bo_bai().keys())
        thieu_anh = [
            str(d.get("Content ID") or "").strip()
            for d in store.lay_tat_ca("CONTENT POOL")
            if str(d.get("Status") or "").strip() in ("WEB_POSTED", "DONE")
            and str(d.get("Content ID") or "").strip()
            and str(d.get("Content ID") or "").strip() not in goi_co
        ]
        if thieu_anh:
            emit({"loai": "log", "noi_dung": f"🖼️ Dựng lại ảnh cho {len(thieu_anh)} bài mất file ảnh..."})
            for i, cid in enumerate(thieu_anh, 1):
                emit({"loai": "log", "noi_dung": f"[{i}/{len(thieu_anh)}] Dựng ảnh lại {cid}..."})
                try:
                    luong_b.xu_ly_anh_bo_bai(cid, format_type=format_type)
                except Exception as e:
                    emit({"loai": "log", "noi_dung": f"  [!] Lỗi dựng ảnh {cid}: {e}"})

        # Đóng gói CSV toàn bộ bài đã xử lý
        emit({"loai": "log", "noi_dung": "📄 Đang đóng gói CSV..."})
        res_csv = dong_goi.tao_csv_full(store)
        csv_path = res_csv.get("csv_path") or ""
        so_csv = res_csv.get("so_dong") or 0

        thong_bao = (f"🏁 XONG LUỒNG: cào {so_cao}, xử lý {ok}/{len(bai_moi_ids)}, "
                     f"CSV {so_csv} bài tại {csv_path}" + canh_bao_chet)
        cap_nhat(dang_chay=False, xong=True, trang_hien_tai=None,
                 xlsx=xlsx_path, thong_bao=thong_bao)
        emit({"loai": "xong", "so_bai": so_cao, "nap_pool": nap,
              "xlsx": xlsx_path, "csv": csv_path, "thong_bao": thong_bao})
        emit({"loai": "log", "noi_dung": f"\n🎉 {thong_bao}"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        cap_nhat(dang_chay=False, xong=True, thong_bao=f"❌ Lỗi luồng: {e}")
        emit({"loai": "loi", "noi_dung": str(e)})
        emit({"loai": "xong", "so_bai": TRANG_THAI["so_bai"]})


@app.route("/")
def trang_chu():
    return render_template("index.html")


# ---------------- FULL AUTO: Cào kho nguồn → AI → Hoàn thành + Cắt ảnh → Excel ----------------

def _doc_nguon_tu_kho(nhom_key: str = "", vung: str = None) -> tuple:
    """Đọc danh sách fanpage nguồn từ kho cấu hình CỦA VÙNG ĐANG CHỌN
    (du_lieu_traffic/nguon_us.json / nguon_global.json, cột "Facebook nguồn").
    Trả về (list tên trang, dict nguồn → (KEY, gợi ý NV)).
    - `nhom_key` = "" hoặc "ALL" → lấy tất cả; ngược lại chỉ lấy KEY khớp (phân tách bằng ';').
    - Bỏ qua các dòng chỉ có TÊN trang (có dấu cách, chưa thay bằng link) để không cào fail."""
    nguon = []
    ban_do = {}  # "Facebook nguồn" -> (KEY, Nhân vật gợi ý)
    try:
        doc = doc_kho_nguon(vung)
        chon = [k.strip().upper() for k in re.split(r"[;|]", nhom_key or "") if k.strip()]
        lay_tat_ca = (not chon) or ("ALL" in chon)
        for r in (doc if isinstance(doc, list) else []):
            v = str(r.get("Facebook nguồn") or r.get("facebook_nguon") or "").strip()
            if not v or v in ban_do:
                continue
            # Bỏ qua dòng chỉ có tên hiển thị (chưa thay link): có dấu cách & không phải URL/username
            if " " in v and not v.lower().startswith("http"):
                continue
            k_upper = str(r.get("KEY") or "").strip().upper()
            if not lay_tat_ca:
                # Khớp chính xác hoặc khớp tiền tố cha (VD: gõ "NFL" -> lấy cả "NFL - ...")
                khop = any(c == k_upper or k_upper.startswith(c + " - ") or k_upper.startswith(c + "-") for c in chon)
                if not khop:
                    continue
            ban_do[v] = (str(r.get("KEY") or "").strip(),
                         str(r.get("Nhân vật gợi ý") or "").strip())
            nguon.append(v)
    except Exception:
        pass
    return nguon, ban_do


FULL_AUTO = {
    "dang_chay": False, "buoc": "", "chi_tiet": "", "tong_bai": 0, "xong": 0,
    "loi": [], "bat_dau": None, "hoan_thanh": False, "ket_qua": None,
    # --- tiến độ / ETA (tự khôi phục khi vào lại web) ---
    "loai_xuat": "anh", "ma_phien": None,
    "giay_da_chay": 0, "phan_tram": 0, "con_lai": None,
    "toc_do": 0.0, "ket_thuc_du_kien": None,
}


def _cap_tien_do():
    """Tính % tiến độ + ETA cho FULL_AUTO (gọi khi đã có tong_bai/xong)."""
    with KHOA:
        bat_dau = FULL_AUTO.get("bat_dau")
        if bat_dau:
            try:
                t0 = datetime.fromisoformat(bat_dau)
                da = (datetime.now() - t0).total_seconds()
                FULL_AUTO["giay_da_chay"] = int(da)
                tong = FULL_AUTO.get("tong_bai") or 0
                xong = FULL_AUTO.get("xong") or 0
                if FULL_AUTO.get("dang_chay") and tong > 0 and xong > 0:
                    toc = xong / max(da, 1)          # bài/giây
                    con = max(tong - xong, 0)
                    FULL_AUTO["toc_do"] = round(toc, 4)
                    FULL_AUTO["con_lai"] = int(con / toc) if toc > 0 else None
                    FULL_AUTO["ket_thuc_du_kien"] = (
                        datetime.now() + timedelta(seconds=FULL_AUTO["con_lai"])
                    ).strftime("%H:%M:%S") if FULL_AUTO["con_lai"] else None
                    FULL_AUTO["phan_tram"] = min(99, int(xong / tong * 100))
                elif FULL_AUTO.get("dang_chay"):
                    FULL_AUTO["phan_tram"] = 0
            except Exception:
                pass


def _full_auto_log(noi_dung: str):
    _cap_tien_do()
    emit({"loai": "log", "noi_dung": f"[FULL] {noi_dung}"})


# ===================================================================
# HẸN GIỜ FULL AUTO — lặp lại hằng giờ / hằng ngày tại phút đã chọn
# (đọc từ du_lieu_luong/hen_gio.json, chạy nền bằng 1 daemon thread)
# ===================================================================
THU_MUC_HEN = os.path.join(DUONG_DAN, "du_lieu_luong")
FILE_HEN_GIO = os.path.join(THU_MUC_HEN, "hen_gio.json")


class HenGio:
    """1 lịch hẹn cho FULL AUTO: gio='HH:MM' hoặc 'H' (mỗi giờ tại phút đó).
    lan='ngay' (mặc định) | 'gio'.  Tới giờ:
      - đang có luồng chạy -> ghi 'bo_qua', KHÔNG chạy bù
      - có hẹn khác chạy trong 30 phút gần nhất -> 'tre_hen', nhích phút
      - ngược lại -> nộp đúng bộ tham số đã lưu lúc đặt hẹn."""

    CACH_TOI_THIEU = 30 * 60  # giây giữa 2 lượt do hen kích hoạt

    def __init__(self):
        self._khoa = threading.Lock()
        self.du_lieu = {"bat": False, "gio": "", "lan": "ngay",
                        "lan_cuoi": None, "tham_so": {}}
        self._lich_su = deque(maxlen=10)   # các lượt hen đã nộp thật
        self._lan_gan_nhat = None          # datetime của lượt hen gần nhất
        self.nap()

    # ---------------- lưu / đọc ----------------
    def nap(self):
        try:
            if os.path.exists(FILE_HEN_GIO):
                with open(FILE_HEN_GIO, encoding="utf-8") as f:
                    d = json.load(f)
                gio = (d.get("gio") or "").strip()
                bat = bool(d.get("bat"))
                if not self._hop_le(gio):
                    bat, gio = False, ""
                with self._khoa:
                    self.du_lieu = {
                        "bat": bat, "gio": gio,
                        "lan": "gio" if (d.get("lan") == "gio") else "ngay",
                        "lan_cuoi": d.get("lan_cuoi"),
                        "lan_xet": d.get("lan_xet"),
                        "tham_so": d.get("tham_so") or {},
                    }
        except Exception as e:
            print(f"⚠ Không đọc được lịch hẹn giờ: {e}")

    def luu(self):
        try:
            os.makedirs(THU_MUC_HEN, exist_ok=True)
            with self._khoa:
                payload = dict(self.du_lieu)
            tmp = FILE_HEN_GIO + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, FILE_HEN_GIO)
        except Exception as e:
            print(f"⚠ Không lưu được lịch hẹn giờ: {e}")

    # ---------------- giờ giấc ----------------
    @staticmethod
    def _parse(gio):
        """'HH:MM' -> (h, m, 'ngay');  'H' (0-23) -> (None, m, 'gio')."""
        gio = (gio or "").strip()
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", gio)
        if m:
            return int(m.group(1)), int(m.group(2)), "ngay"
        m = re.fullmatch(r"([0-5]?\d)", gio)
        if m and int(m.group(1)) < 60:
            return None, int(m.group(1)), "gio"
        return None

    @classmethod
    def _hop_le(cls, gio):
        return cls._parse(gio) is not None

    @staticmethod
    def _can(gio, now):
        """Được phép chạy ngay bây giờ chưa? (hẹn phút == phút hiện tại)."""
        g = HenGio._parse(gio)
        if not g:
            return False
        h, p, lan = g
        if lan == "ngay":
            return (now.hour, now.minute) == (h, p)
        return now.minute == p

    @staticmethod
    def _ke_tiep(gio, now):
        h, p, lan = HenGio._parse(gio)
        if lan == "ngay":
            t = now.replace(hour=h, minute=p, second=0, microsecond=0)
            if t <= now:
                t += timedelta(days=1)
            return t
        t = now.replace(minute=p, second=0, microsecond=0)
        if t <= now:
            t += timedelta(hours=1)
        return t

    # ---------------- điều khiển ----------------
    def dat(self, gio, lan, tham_so):
        """Bật hẹn. gio='HH:MM' (mỗi ngày) hoặc 'M' 0-59 (mỗi giờ tại phút M)."""
        g = self._parse(gio)
        if not g:
            return {"ok": False,
                    "loi": "Giờ không hợp lệ — nhập '20:30' (mỗi ngày) hoặc '30' (mỗi giờ tại phút 30)."}
        h, p, _ = g
        lan = "gio" if lan == "gio" else "ngay"
        gio = str(p) if lan == "gio" else f"{h:02d}:{p:02d}"
        # web KHÔNG lưu cứng trong lịch: theo VÙNG đang bật tại phút chạy
        # (bài global -> web global, bài us -> web us). Đổi công tắc vùng là
        # đổi luôn web của luồng hẹn giờ.
        tham_so = dict(tham_so or {})
        tham_so.pop("web", None)
        tham_so.pop("vung", None)
        loi, mo_ta, _ = _doc_full_auto_params(tham_so)
        if loi:
            return {"ok": False, "loi": "Tham số hẹn không hợp lệ: " + loi}
        now = datetime.now()
        with self._khoa:
            self.du_lieu = {"bat": True, "gio": gio, "lan": lan,
                            "lan_cuoi": self.du_lieu.get("lan_cuoi"),
                            "lan_xet": (now.strftime("%Y-%m-%d %H:%M")
                                        if self._can(gio, now) else None),
                            "bo_qua": False, "tre_hen": False,
                            "tham_so": dict(tham_so)}
        self.luu()
        return {"ok": True, "mo_ta": mo_ta, **self.trang_thai()}

    def tat(self):
        with self._khoa:
            self.du_lieu["bat"] = False
        self.luu()
        return {"ok": True, "bat": False}

    def trang_thai(self):
        with self._khoa:
            d = dict(self.du_lieu)
        gio = d.get("gio") or ""
        next_chay = None
        if d.get("bat") and self._hop_le(gio):
            try:
                next_chay = self._ke_tiep(gio, datetime.now()).isoformat()
            except Exception:
                next_chay = None
        return {"bat": bool(d.get("bat")), "gio": gio, "lan": d.get("lan"),
                "lan_cuoi": d.get("lan_cuoi"), "next_chay": next_chay,
                "bo_qua": bool(d.get("bo_qua")),
                "tre_hen": bool(d.get("tre_hen")),
                "co_tham_so": bool(d.get("tham_so")),
                "lich_su": list(self._lich_su)[-8:]}

    # ---------------- vòng lặp nền ----------------
    def _ghi(self, **kw):
        with self._khoa:
            self.du_lieu.update(kw)
        self.luu()

    def vong_lap(self):
        _full_auto_log("⏰ Bộ hẹn giờ FULL AUTO sẵn sàng (kiểm tra mỗi 15 giây).")
        while True:
            time.sleep(15)
            try:
                now = datetime.now()
                with self._khoa:
                    bat = self.du_lieu.get("bat")
                    gio = self.du_lieu.get("gio")
                    tham_so = dict(self.du_lieu.get("tham_so") or {})
                    da_xet = self.du_lieu.get("lan_xet") or ""
                if not (bat and gio and tham_so):
                    continue
                phut = now.strftime("%Y-%m-%d %H:%M")
                if not self._can(gio, now):
                    continue
                if da_xet == phut:          # phút này đã xét rồi -> chỉ 1 lượt/phút
                    continue
                self._ghi(lan_xet=phut)
                with KHOA:
                    busy = FULL_AUTO["dang_chay"] or TRANG_THAI["dang_chay"]
                if busy:
                    self._ghi(bo_qua=True, lan_cuoi=now.isoformat())
                    emit({"loai": "log",
                          "noi_dung": f"⏰ [HEN {gio}] Đang có luồng chạy — BỎ QUA lượt này (không chạy bù)."})
                    continue
                if (self._lan_gan_nhat
                        and (now - self._lan_gan_nhat).total_seconds() < self.CACH_TOI_THIEU):
                    self._ghi(tre_hen=True, lan_cuoi=now.isoformat())
                    emit({"loai": "log",
                          "noi_dung": f"⏰ [HEN {gio}] Lượt trước mới chạy < 30 phút — TRÈ HEN lượt này."})
                    continue
                loi, mo_ta, params = _doc_full_auto_params(tham_so)
                if loi:
                    self._ghi(bo_qua=True, lan_cuoi=now.isoformat())
                    emit({"loai": "log", "noi_dung": f"⏰ [HEN {gio}] Bỏ qua lượt: {loi}"})
                    continue
                luu_cau_hinh_proxy(tham_so)
                pk = tham_so_proxy(tham_so)
                self._ghi(bo_qua=False, tre_hen=False, lan_cuoi=now.isoformat())
                self._lan_gan_nhat = now
                self._lich_su.append(now.isoformat())
                emit({"loai": "log",
                      "noi_dung": f"⏰ [HEN {gio}] Tới giờ — khởi động FULL AUTO ({mo_ta})..."})
                _khoi_dong_full_auto(params, proxy_kwargs=pk)
            except Exception as e:
                emit({"loai": "log",
                      "noi_dung": f"⏰ Lỗi bộ hẹn giờ: {str(e)[:200]}"})


HEN_GIO = HenGio()


def _doc_full_auto_params(data):
    """Kiểm + chuẩn hóa body /api/chay_full_auto -> (loi, mo_ta, kwargs) hoặc (None, None, None)."""
    data = data or {}
    # web ĐƯỢC QUYẾT BỞI VÙNG: bài global đăng web global, bài us đăng web us.
    v = chuan_vung(data.get("vung") or lay_vung())
    web = str(data.get("web") or "").strip().lower()
    if web and web not in ("us", "global"):
        return (f"web='{web}' không hợp lệ — chỉ nhận 'us' hoặc 'global'", None, None)
    if web and web != v:
        return (f"Trái vùng: công tắc đang bật {TEN_VUNG[v]} nhưng web chọn là "
                f"{TEN_NGAN[web]}. Web đăng bài phải theo vùng — "
                f"đổi công tắc vùng hoặc giữ nguyên web {TEN_NGAN[v]}.", None, None)
    web = v
    loai_xuat = (data.get("loai_xuat") or "anh").strip()
    if loai_xuat not in ("anh", "reel", "ca_hai"):
        loai_xuat = "anh"
    try:
        gioi_han = int(data.get("gioi_han") or 0)
        per_page = int(data.get("per_page") or 10)
        pages = int(data.get("pages") or 3)
        delay = float(data.get("delay") or 3.0)
    except (TypeError, ValueError):
        return ("Tham số cào không hợp lệ (per_page/pages/delay/gioi_han phải là số)", None, None)
    if gioi_han < 0:
        gioi_han = 0
    format_type = (data.get("format_type") or "1:1").strip() or "1:1"
    cookies = (data.get("cookies") or "").strip() or None
    no_images = bool(data.get("no_images", False))
    nhom_key = (data.get("nhom_key") or "").strip()   # "" / "ALL" = tất cả; "NFL;WNBA" (nhiều chủ đề)
    raw = (data.get("nguon") or "").strip()
    if not raw or raw.upper() == "KHO":
        nguon_pages = None                              # worker tự đọc từ kho
        mo_ta_nguon = ("kho nguồn — chủ đề: " + nhom_key.replace(";", ", ")
                       if nhom_key and nhom_key.upper() != "ALL" else "kho nguồn (tất cả chủ đề)")
    else:
        nguon_pages = [t.strip() for t in raw.splitlines() if t.strip()]
        mo_ta_nguon = f"{len(nguon_pages)} trang nhập tay"
    params = {
        "format_type": format_type, "per_page": per_page, "pages": pages,
        "delay": delay, "cookies": cookies, "no_images": no_images,
        "gioi_han": gioi_han, "loai_xuat": loai_xuat, "nguon_pages": nguon_pages,
        "nhom_key": nhom_key, "web": web, "vung": v,
    }
    mo_ta = (f"[{TEN_VUNG[v]}] {mo_ta_nguon} · per_page={per_page} · pages={pages} · "
             f"gioi_han={gioi_han or 'ALL'} · xuất {loai_xuat} · web {TEN_NGAN[web]}")
    return None, mo_ta, params


def _khoi_dong_full_auto(params, proxy_kwargs=None):
    """Nộp một luồng FULL AUTO vào thread nền (dùng chung cho nút bấm + hẹn giờ)."""
    with KHOA:
        if FULL_AUTO["dang_chay"] or TRANG_THAI["dang_chay"]:
            return False
    STOP_EVENT.clear()
    _lam_sach_dang_ky()
    pk = proxy_kwargs or tham_so_proxy({})
    ten_buoc = {"anh": "Cắt Ảnh", "reel": "Reel", "ca_hai": "Ảnh + Reel"}.get(params["loai_xuat"], "Cắt Ảnh")
    cap_nhat(dang_chay=True, xong=False, trang_ho=["[AUTO]"], trang_hien_tai=None,
             so_bai=0, so_anh=0, xlsx=None,
             thong_bao=f"Đang chạy FULL AUTO ({ten_buoc}, {TEN_VUNG[params['vung']]})...")
    threading.Thread(
        target=chay_full_auto,
        args=(params["format_type"], params["per_page"], params["pages"],
              params["delay"], params["cookies"], params["no_images"],
              params["gioi_han"], params["loai_xuat"], params["nguon_pages"]),
        kwargs={"proxy_kwargs": pk, "nhom_key": params["nhom_key"],
                "web": params["web"], "vung": params["vung"]},
        daemon=True,
    ).start()
    return True


def chay_full_auto(format_type="1:1", per_page=10, pages=3, delay=3.0,
                   cookies="cookies.txt", no_images=False, gioi_han=0,
                   loai_xuat="anh", nguon_pages=None, proxy_kwargs=None,
                   nhom_key="", web="", vung=None):
    """Luồng TỰ ĐỘNG đầy đủ 4 bước, không cần bấm gì thêm:
      1. Cào bài từ danh sách nguồn (kho du_lieu_traffic/source_config.json
         hoặc `nguon_pages` truyền từ textarea)
      2. AI viết lại từng bài mới (3 Caption + bài báo + link web)
      3. Hoàn thành + cắt ảnh (`loai_xuat='anh'`) HOẶC dựng video reel 10s
         (`loai_xuat='reel'`) HOẶC cả hai (`loai_xuat='ca_hai'`)
      4. Xuất Excel san_sang_<CHUDE>.xlsx vào du_lieu_exel
    Tiến độ phát qua SSE (/api/su_kien), tra cứu bằng /api/full_auto_status."""
    loai_xuat = (loai_xuat or "anh").strip()
    if loai_xuat not in ("anh", "reel", "ca_hai"):
        loai_xuat = "anh"
    # Vùng chốt lúc khởi động: web ĐĂNG BÀI = vùng (bài global → web global).
    vung = chuan_vung(vung or web or US)
    web = vung

    def fa(**kw):
        with KHOA:
            FULL_AUTO.update(kw)
        _cap_tien_do()

    try:
        fa(dang_chay=True, hoan_thanh=False, xong=0, tong_bai=0, loi=[],
           ket_qua=None, bat_dau=datetime.now().isoformat(),
           buoc="1/4 Cào dữ liệu", chi_tiet="", loai_xuat=loai_xuat,
           web=web, vung=vung)
        store = lay_store()

        # Xác định nguồn: textarea ưu tiên nếu có, không thì lấy kho (lọc theo nhóm KEY nếu có)
        if nguon_pages is None:
            nguon, ban_do_nguon = _doc_nguon_tu_kho(nhom_key, vung)
            nguon_str = f"{len(nguon)} trang trong kho {TEN_VUNG[vung]}"
            if (nhom_key or "").strip() and nhom_key.upper() != "ALL":
                nguon_str += f" (chủ đề: {nhom_key.replace(';', ', ')})"
            nguon_str += f": {', '.join(nguon[:8])}{'...' if len(nguon) > 8 else ''}"
        else:
            nguon = [t.strip() for t in nguon_pages if t and t.strip()]
            ban_do_nguon = {}
            nguon_str = f"{len(nguon)} trang từ textarea: {', '.join(nguon)}"
        if not nguon:
            raise RuntimeError("Chưa có nguồn — thêm vào kho source_config.json hoặc nhập trong textarea Tab 1")
        _full_auto_log(f"Bước 1/4: Cào bài từ {nguon_str}")

        truoc = {str(d.get("Content ID") or "").strip()
                 for d in store.lay_tat_ca("CONTENT POOL")}

        def cb(s):
            emit(s)
            if s.get("loai") == "post":
                with KHOA:
                    TRANG_THAI["so_bai"] += 1
            elif s.get("loai") == "trang_bat_dau":
                fa(chi_tiet=f"Đang cào: {s.get('page')}")

        ket_qua, _ = scraper.run_cào(
            nguon, pages=pages, per_page=per_page, output="du_lieu",
            no_images=no_images, cookies=cookies, delay=delay,
            callback=cb, stop_flag=STOP_EVENT, bo_qua_bai_cu=True,
            **(proxy_kwargs or {}),
        )
        so_cao = sum(len(p) for p in ket_qua.values())
        canh_bao_chet = _canh_bao_phien_chet()
        nap, phien_chay = _nap_vao_pool(ket_qua, store, ban_do_nguon=ban_do_nguon,
                                        vung=vung)
        _full_auto_log(f"Cào xong: {so_cao} bài, nạp mới {nap} bài vào kho (phiên {phien_chay})."
                       + canh_bao_chet)

        # Bước 2: AI viết lại cho các bài MỚI vừa nạp
        sau = {str(d.get("Content ID") or "").strip()
               for d in store.lay_tat_ca("CONTENT POOL")}
        bai_moi = [c for c in sau if c and c not in truoc]
        if gioi_han and gioi_han > 0:
            bai_moi = bai_moi[:gioi_han]
        fa(buoc="2/4 AI viết bài", tong_bai=len(bai_moi), xong=0)
        _full_auto_log(f"Bước 2/4: AI viết lại {len(bai_moi)} bài mới...")
        ok_ai = 0
        # 2 luồng song song (config ai.song_song, mặc định 2): xử lý 2 bài AI một lúc.
        # as_completed để tiến độ đếm đúng lúc TỪNG bài xong (không phải lúc giao việc).
        so_cong = max(1, _so_luong_song_song())
        da_xong = 0
        with ThreadPoolExecutor(max_workers=so_cong) as executor:
            tuong_lai = {
                executor.submit(luong_b.xu_ly_ai_mot_bai, cid,
                                format_type=format_type, web=web): cid
                for cid in bai_moi
            }
            for fu in as_completed(tuong_lai):
                cid = tuong_lai[fu]
                da_xong += 1
                fa(chi_tiet=cid, xong=da_xong)
                emit({"loai": "tien_do", "buoc": "2/4 AI", "xong": da_xong,
                      "tong": len(bai_moi)})
                if STOP_EVENT.is_set():
                    for fu2 in tuong_lai:
                        fu2.cancel()
                    _full_auto_log("Đã dừng theo yêu cầu — hủy các bài chưa bắt đầu.")
                    break
                try:
                    if fu.result().get("success"):
                        ok_ai += 1
                except Exception as e:
                    with KHOA:
                        FULL_AUTO["loi"].append({"id": cid, "err": str(e)[:150]})
        with KHOA:
            FULL_AUTO["xong"] = len(bai_moi)
        _full_auto_log(f"AI xong: {ok_ai}/{len(bai_moi)} bài thành công.")

        # Bước 3: Hoàn thành + (ảnh | reel | cả hai) theo loai_xuat
        store = lay_store()
        # CHỈ lấy bài của PHIÊN cào đang chạy (nhãn `Phien_cao`) — tránh lôi bài
        # cũ còn dở (WEB_POSTED/SAN_SANG của lần trước) vào gói của lần này.
        # `hoan_thanh_hang_loat` tự bỏ qua bài đã HOAN_THANH.
        ids_can_anh = [
            str(d.get("Content ID") or "").strip()
            for d in store.lay_tat_ca("CONTENT POOL")
            if str(d.get("Status") or "").strip() in ("WEB_POSTED", "SAN_SANG")
            and str(d.get("Phien_cao") or "").strip() == phien_chay
            and str(d.get("Content ID") or "").strip()
        ]
        if ids_can_anh and not STOP_EVENT.is_set():
            ten_buoc = {"anh": "Cắt ảnh", "reel": "Dựng Reel", "ca_hai": "Ảnh + Reel"}.get(loai_xuat, "Cắt ảnh")
            fa(buoc=f"3/4 Hoàn thành + {ten_buoc}", tong_bai=len(ids_can_anh), xong=0)
            res_ht = luong_b.hoan_thanh_hang_loat(ids_can_anh, ghi_chu="Chạy Full tự động")
            _full_auto_log(f"Bước 3/4 ({loai_xuat}): Hoàn thành {res_ht.get('so_thanh_cong', 0)} bài, bắt đầu {ten_buoc}...")
            da_xong = 0
            for i, cid in enumerate(ids_can_anh, 1):
                if STOP_EVENT.is_set():
                    _full_auto_log(f"Đã dừng giữa bước {ten_buoc}.")
                    break
                fa(chi_tiet=cid, xong=da_xong)
                emit({"loai": "tien_do", "buoc": f"3/4 {ten_buoc}",
                      "xong": da_xong, "tong": len(ids_can_anh)})
                try:
                    # 1) Crop ảnh chính (chế độ có ảnh) — hàm này tự đặt HOAN_THANH
                    if loai_xuat in ("anh", "ca_hai"):
                        luong_b.xu_ly_anh_hoan_thanh_mot_bai(cid, format_type=format_type,
                                                              co_logo=True)
                    # 2) Tạo ảnh reel (không logo) + video 10s nếu chọn reel / ca_hai
                    if loai_xuat in ("reel", "ca_hai"):
                        r2 = luong_b.xu_ly_anh_reel_mot_bai(cid, format_type=format_type)
                        anh_reel = (r2.get("data") or {}).get("anh_path") if r2.get("success") else ""
                        if not anh_reel:
                            with KHOA:
                                FULL_AUTO["loi"].append({"id": cid,
                                    "err": r2.get("message") or "Không có ảnh reel"})
                        else:
                            r3 = reel.tao_reel(anh_reel, co_nhac=True, ten_dau_ra=cid)
                            if not r3.get("success"):
                                with KHOA:
                                    FULL_AUTO["loi"].append({"id": cid,
                                        "err": "reel: " + str(r3.get("error"))[:120]})
                    # 3) Chế độ 'reel' thuần KHÔNG có bước cắt ảnh → không ai nâng
                    #    status, bài kẹt ở SAN_SANG và không bao giờ vào Excel
                    #    (điều kiện HOAN_THANH). Dựng reel xong → tự nâng tại đây.
                    if loai_xuat == "reel" and not any(
                            str(x.get("id")) == str(cid) for x in FULL_AUTO["loi"]):
                        from content_pool import doi_status
                        doi_status(cid, "HOAN_THANH",
                                   ghi_chu="Full Auto: dựng reel xong", store=store)
                except Exception as e:
                    with KHOA:
                        FULL_AUTO["loi"].append({"id": cid, "err": str(e)[:150]})
                da_xong = i
            with KHOA:
                FULL_AUTO["xong"] = da_xong
            _full_auto_log(f"{ten_buoc} xong {da_xong} bài.")

        # Bước 4: Xuất Excel theo chủ đề
        if STOP_EVENT.is_set():
            raise RuntimeError("Đã dừng trước khi xuất Excel")
        fa(buoc="4/4 Xuất Excel san_sang", chi_tiet="")
        cac_file, thu_muc = _xuat_excel_hoan_thanh_impl(phien=phien_chay, vung_hien=vung)
        ten_files = ", ".join(os.path.basename(f["file"]) for f in cac_file)
        thong_bao = (f"🏁 FULL AUTO XONG: cào {so_cao} (mới {nap}), AI {ok_ai}/{len(bai_moi)}, "
                     f"xuất {len(cac_file)} file Excel ({nap} bài phiên này): {ten_files}"
                     + locals().get("canh_bao_chet", ""))

        fa(dang_chay=False, hoan_thanh=True, buoc="Hoàn thành",
           ket_qua={"so_cao": so_cao, "nap_moi": nap, "ai_ok": ok_ai,
                    "excel_files": [f["file"] for f in cac_file]})
        cap_nhat(dang_chay=False, xong=True, thong_bao=thong_bao)
        _full_auto_log(thong_bao)
        emit({"loai": "xong", "so_bai": so_cao, "thong_bao": thong_bao})
    except Exception as e:
        import traceback
        traceback.print_exc()
        with KHOA:
            FULL_AUTO["dang_chay"] = False
            FULL_AUTO["hoan_thanh"] = False
            FULL_AUTO["buoc"] = "Lỗi"
            FULL_AUTO["loi"].append({"id": "luong", "err": str(e)[:200]})
        cap_nhat(dang_chay=False, xong=True, thong_bao=f"❌ Lỗi FULL AUTO: {e}")
        emit({"loai": "loi", "noi_dung": f"FULL AUTO lỗi: {e}"})
        emit({"loai": "xong", "so_bai": 0, "thong_bao": f"FULL AUTO lỗi: {e}"})


@app.route("/api/chay_full_auto", methods=["POST"])
def api_chay_full_auto():
    """Bật luồng TỰ ĐỘNG đầy đủ: lấy nguồn từ kho → cào → AI → (ảnh|reel|cả 2) → Excel."""
    data = request.json or {}
    loi, _, params = _doc_full_auto_params(data)
    if loi:
        return jsonify({"ok": False, "loi": loi}), 400
    luu_cau_hinh_proxy(data)
    pk = tham_so_proxy(data)
    if not _khoi_dong_full_auto(params, proxy_kwargs=pk):
        return jsonify({"ok": False, "loi": "Đang có luồng chạy, vui lòng đợi!"}), 400
    return jsonify({"ok": True})


@app.route("/api/full_auto_status", methods=["GET"])
def api_full_auto_status():
    if FULL_AUTO.get("dang_chay"):
        _cap_tien_do()
    with KHOA:
        return jsonify(FULL_AUTO)


# ---------------- API hẹn giờ FULL AUTO ----------------
@app.route("/api/hen_gio", methods=["GET"])
def api_hen_gio():
    return jsonify(HEN_GIO.trang_thai())


@app.route("/api/hen_gio/luu", methods=["POST"])
def api_hen_gio_luu():
    """Đặt/bật hẹn giờ: body = {gio, lan} + toàn bộ tham số full auto (web bắt buộc)."""
    data = request.json or {}
    gio = (data.get("gio") or "").strip()
    lan = (data.get("lan") or "").strip()
    ket_qua = HEN_GIO.dat(gio, lan, data)
    if not ket_qua.get("ok"):
        return jsonify(ket_qua), 400
    emit({"loai": "log",
          "noi_dung": f"⏰ Đã đặt hẹn FULL AUTO: {ket_qua['gio']} "
                      f"({'mỗi giờ' if ket_qua['lan'] == 'gio' else 'mỗi ngày'}) — {ket_qua.get('mo_ta', '')}"})
    return jsonify(ket_qua)


@app.route("/api/hen_gio/tat", methods=["POST"])
def api_hen_gio_tat():
    ket_qua = HEN_GIO.tat()
    emit({"loai": "log", "noi_dung": "⏰ Đã TẮT hẹn giờ FULL AUTO."})
    return jsonify(ket_qua)


@app.route("/api/trang_thai")
def api_trang_thai():
    if TRANG_THAI.get("dang_chay"):
        _cap_tien_do_scrape()
    with KHOA:
        return jsonify(TRANG_THAI)


@app.route("/api/prompt_caption", methods=["GET"])
def api_prompt_caption():
    """Prompt caption dang chay thuc te (doc truc tiep luc goi).

    Sua promtnew.txt -> roi vao dia chi nay de kiem tra no da thay doi chua.
    """
    try:
        thong_tin = viet_lai.tinh_trang_prompt_caption()
        moc = thong_tin.pop("sua_gan_nhat", None)
        if moc:
            thong_tin["sua_gan_nhat_luc"] = datetime.fromtimestamp(moc).strftime(
                "%d/%m/%Y %H:%M:%S")
        thong_tin["ok"] = True
        return jsonify(thong_tin)
    except Exception as e:
        return jsonify({"ok": False, "loi": str(e)}), 500


@app.route("/api/log", methods=["GET"])
def api_log():
    """Đọc log đã lưu trên đĩa (giữ lại sau khi F5 / khởi động lại web).

    ?tail=200   số dòng cuối (mặc định 200, tối đa 2000)
    ?clear=1    xoá sạch log
    """
    if request.args.get("clear"):
        _xoa_log_dia()
        return jsonify({"ok": True, "message": "Đã xoá file log"})
    try:
        tail = max(1, min(2000, int(request.args.get("tail") or 200)))
    except ValueError:
        tail = 200
    dong = _doc_log_dia(tail)
    return jsonify({"ok": True, "so_dong": len(dong), "file": DUONG_DAN_LOG,
                    "log": [d.get("noi_dung") or d for d in dong],
                    "log_day": dong})


@app.route("/api/su_kien")
def api_su_kien():
    """SSE: phát lại sự kiện còn trong bộ đệm (chống mất khi F5) rồi stream tiếp.

    ?since=<seq>  chỉ phát sự kiện có seq lớn hơn (mặc định: 120 sự kiện gần nhất)
    """
    try:
        since = int(request.args.get("since") or -1)
    except ValueError:
        since = -1

    def generator():
        q = _mo_dang_ky()
        try:
            with KHOA_LOG:
                dem = list(BO_DEM_SU_KIEN)
            if since >= 0:
                phat_lai = [s for s in dem if s.get("seq", 0) > since]
            else:
                phat_lai = dem[-120:]
            for s in phat_lai:
                s = dict(s)
                s["replay"] = True
                yield f"data: {json.dumps(s, ensure_ascii=False)}\n\n"
            while True:
                try:
                    su_kien = q.get(timeout=20)
                    yield f"data: {json.dumps(su_kien, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            _dong_dang_ky(q)

    return Response(generator(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/nguon/nhom", methods=["GET"])
def api_nguon_nhom():
    """Danh sách nhóm KEY (chủ đề) trong kho nguồn cho bộ tick chọn ở Tab 1 + modal Full Auto.

    `so_nguon`  = số dòng trong kho (kể cả dòng chỉ có tên, chưa thay link)
    `hop_le`    = số nguồn sẽ THỰC SỰ được cào (có link / không có dấu cách)
    `dinh_kem`  = (tùy chọn ?chi_tiet=1) danh sách nhân vật gợi ý của nhóm
    """
    fp = duong_dan_nguon(_vung_cua_request())
    from collections import Counter
    dem = Counter()
    dem_hop_le = Counter()
    ds_vung = {}
    goi_y = {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            doc = json.load(f)
        for r in (doc if isinstance(doc, list) else []):
            k = str(r.get("KEY") or "").strip()
            v = str(r.get("Facebook nguồn") or "").strip()
            if not v:
                continue
            k = k or "(không KEY)"
            # đếm cả nguồn chỉ có tên (chưa link) nhưng sẽ bị bỏ qua lúc cào
            dem[k] += 1
            if " " not in v or v.lower().startswith("http"):
                dem_hop_le[k] += 1
            vk = str(r.get("Vung") or "").strip().lower()
            if vk:
                ds_vung[k] = vk
            gy = str(r.get("Nhân vật gợi ý") or "").strip()
            if gy and k not in goi_y:
                goi_y[k] = gy
    except Exception:
        pass
    chi_tiet = request.args.get("chi_tiet")
    ds = []
    for k, v in dem.items():
        e = {"key": k, "so_nguon": v, "hop_le": dem_hop_le.get(k, 0),
             "vung": ds_vung.get(k, ""),
             "ten_vung": TEN_VUNG.get(ds_vung.get(k, ""), "")}
        if chi_tiet:
            e["goi_y"] = goi_y.get(k, "")
        ds.append(e)
    v_hien = chuan_vung(_vung_cua_request())
    return jsonify({"ok": True, "nhom": ds, "vung": v_hien,
                    "ten_vung": TEN_VUNG[v_hien],
                    "file_nguon": os.path.basename(fp)})


@app.route("/api/bat_dau", methods=["POST"])
def api_bat_dau():
    with KHOA:
        if TRANG_THAI["dang_chay"]:
            return jsonify({"ok": False, "loi": "Đang cào dữ liệu, vui lòng đợi!"}), 400

    data = request.json or {}
    nhom_key = (data.get("nhom_key") or "").strip()
    # Chốt vùng NGAY LÚC BẤM NÚT: đổi công tắc giữa chừng không làm lô đang
    # chạy bị lệch nguồn/nhãn nữa.
    v = _vung_cua_request(data)
    trang_raw = data.get("trang", "")
    trang_ho = [t.strip() for t in trang_raw.splitlines() if t.strip()]
    if not trang_ho and not nhom_key:
        return jsonify({"ok": False, "loi": "Chưa có nguồn — hãy tích CHỦ ĐỀ trong kho nguồn HOẶC nhập trang tay"}), 400

    per_page = int(data.get("per_page") or 50)
    pages = int(data.get("pages") or 10)
    delay = float(data.get("delay") or 3.0)
    cookies = (data.get("cookies") or "").strip() or None
    no_images = bool(data.get("no_images", False))

    STOP_EVENT.clear()
    _lam_sach_dang_ky()
    luu_cau_hinh_proxy(data)
    pk = tham_so_proxy(data)

    cap_nhat(dang_chay=True, xong=False, trang_ho=trang_ho,
             trang_hien_tai=(trang_ho[0] if trang_ho else f"[KHO: {nhom_key or 'TẤT CẢ'}]"),
             so_bai=0, so_anh=0, xlsx=None, phan_tram=0, con_lai=None,
             ket_thuc_du_kien=None, bat_dau=datetime.now().isoformat(),
             thong_bao=f"Đang khởi động cào dữ liệu [{TEN_VUNG[v]}]...")

    t = threading.Thread(
        target=chay_scraper,
        args=(trang_ho, per_page, pages, delay, cookies, no_images),
        kwargs={"proxy_kwargs": pk, "nhom_key": nhom_key, "vung": v},
        daemon=True,
    )
    t.start()
    return jsonify({"ok": True, "so_trang": len(trang_ho), "vung": v})


@app.route("/api/dung", methods=["POST"])
def api_dung():
    STOP_EVENT.set()
    cap_nhat(dang_chay=False, thong_bao="Đã gửi yêu cầu dừng...")
    emit({"loai": "thong_bao", "noi_dung": "Đang dừng theo yêu cầu người dùng..."})
    return jsonify({"ok": True})


@app.route("/api/chay_ca_luong", methods=["POST"])
def api_chay_ca_luong():
    """Luồng FULL: cào → viết lại → chỉnh ảnh → đóng gói CSV."""
    with KHOA:
        if TRANG_THAI["dang_chay"]:
            return jsonify({"ok": False, "loi": "Đang có tiến trình chạy, vui lòng đợi!"}), 400

    data = request.json or {}
    nhom_key = (data.get("nhom_key") or "").strip()
    v = _vung_cua_request(data)
    web = (data.get("web") or "").strip().lower()
    if web and web not in ("us", "global"):
        return jsonify({"ok": False,
                        "loi": f"web='{web}' không hợp lệ — chỉ nhận 'us' hoặc 'global'"}), 400
    if web and web != v:
        return jsonify({"ok": False,
                        "loi": f"Trái vùng: công tắc đang bật {TEN_VUNG[v]} nhưng web "
                               f"chọn {TEN_NGAN[web]} — nguồn cào và web phải cùng vùng"}), 400
    web = v
    trang_raw = data.get("trang") or data.get("nguon") or ""
    trang_ho = [t.strip() for t in trang_raw.splitlines() if t.strip()]
    if not trang_ho and not nhom_key:
        return jsonify({"ok": False, "loi": "Chưa có nguồn — hãy tích CHỦ ĐỀ trong kho nguồn HOẶC nhập trang tay"}), 400

    per_page = int(data.get("per_page") or 10)
    pages = int(data.get("pages") or 3)
    delay = float(data.get("delay") or 3.0)
    cookies = (data.get("cookies") or "").strip() or None
    no_images = bool(data.get("no_images", False))
    format_type = (data.get("format_type") or "1:1").strip() or "1:1"

    STOP_EVENT.clear()
    _lam_sach_dang_ky()
    luu_cau_hinh_proxy(data)
    pk = tham_so_proxy(data)

    cap_nhat(dang_chay=True, xong=False, trang_ho=trang_ho,
             trang_hien_tai=(trang_ho[0] if trang_ho else f"[KHO: {nhom_key or 'TẤT CẢ'}]"),
             so_bai=0, so_anh=0, xlsx=None, phan_tram=0, con_lai=None,
             ket_thuc_du_kien=None, bat_dau=datetime.now().isoformat(),
             thong_bao=f"Đang chạy luồng đầy đủ [{TEN_VUNG[v]}]...")

    t = threading.Thread(
        target=chay_ca_luong,
        args=(trang_ho, per_page, pages, delay, cookies, no_images, format_type),
        kwargs={"proxy_kwargs": pk, "nhom_key": nhom_key, "web": web, "vung": v},
        daemon=True,
    )
    t.start()
    return jsonify({"ok": True, "trang": len(trang_ho), "vung": v, "web": web})


@app.route("/api/xuat_csv", methods=["POST"])
def api_xuat_csv():
    """Đóng gói các bài đã xử lý ra file CSV (gửi ids để lọc, không thì lấy TẤT CẢ WEB_POSTED/DONE)."""
    data = request.json or {}
    ids = data.get("ids") or None
    res = dong_goi.tao_csv_full(danh_sach=ids)
    if not res.get("ok"):
        return jsonify({"ok": False, "loi": "Không thể xuất CSV"}), 500
    return jsonify({"ok": True, "csv_path": res.get("csv_path"),
                    "so_dong": res.get("so_dong"), "thu_muc": res.get("thu_muc")})


@app.route("/api/tai_csv")
def api_tai_csv():
    f = request.args.get("file")
    if not f:
        folder = os.path.join(DUONG_DAN, "du_lieu_fb")
        danh_sach = sorted(
            glob.glob(os.path.join(folder, "**", "goi_full_*.csv"), recursive=True),
            key=os.path.getmtime, reverse=True)
        if danh_sach:
            f = danh_sach[0]
    if f and os.path.isfile(f):
        return send_file(f, as_attachment=True, download_name=os.path.basename(f))
    return jsonify({"ok": False, "loi": "Không tìm thấy file CSV"}), 404


@app.route("/api/kiem_tra_cookies", methods=["POST"])
def api_kiem_tra_cookies():
    data = request.json or {}
    ten_file = (data.get("file") or "").strip()
    duong_dan = os.path.join(DUONG_DAN, ten_file) if ten_file else None
    if not duong_dan or not os.path.isfile(duong_dan):
        return jsonify({
            "ok": True,
            "so_luong": 0,
            "thong_bao": "⚡ Chế độ cào KHÔNG cần cookies (Guest mode) sẵn sàng hoạt động qua Proxy."
        })
    try:
        ck = scraper.cao_fb.doc_cookies(duong_dan)
        if not ck:
            return jsonify({
                "ok": True,
                "so_luong": 0,
                "thong_bao": f"File '{ten_file}' rỗng — Tự động chạy chế độ khách (Guest mode)."
            })
        return jsonify({
            "ok": True,
            "so_luong": len(ck),
            "thong_bao": f"Tìm thấy {len(ck)} cookies trong {ten_file} (tùy chọn)."
        })
    except Exception as e:
        return jsonify({
            "ok": True,
            "so_luong": 0,
            "thong_bao": f"Lỗi đọc {ten_file} ({e}) — Sẽ chạy chế độ khách (Guest mode)."
        })


@app.route("/api/kiem_tra_proxy", methods=["POST"])
def api_kiem_tra_proxy():
    """Test từng dòng proxies.txt: ra IP nào, ASN/org, có phải VN, có bị coi
    là datacenter/sanh không — kèm ghép cặp với các file cookie tìm được."""
    data = request.json or {}
    ten_file = (data.get("file") or "proxies.txt").strip() or "proxies.txt"
    duong_dan = os.path.join(DUONG_DAN, ten_file)
    if not os.path.isfile(duong_dan):
        return jsonify({"ok": False,
                        "loi": f"Không tìm thấy file '{ten_file}' — tạo file "
                               f"mỗi dòng một proxy (host:port hoặc "
                               f"http://user:pass@host:port)."})
    ds = scraper.cao_fb.doc_proxies(duong_dan)
    if not ds:
        return jsonify({"ok": False, "loi": f"File '{ten_file}' rỗng."})
    ket_qua = []
    for i, px in enumerate(ds[:10]):          # test tối đa 10 IP cho nhanh
        if px is None:                        # dòng 'local'/'-' -> IP máy
            kq = scraper.cao_fb.kiem_tra_proxy(None)
            kq["hien_thi"] = f"dòng {i + 1}: IP máy (không proxy)"
        else:
            kq = scraper.cao_fb.kiem_tra_proxy(px)
            kq["hien_thi"] = scraper.cao_fb._ru_mat_khau(px)
        kq["stt"] = i + 1
        ket_qua.append(kq)
    ips = [k["ip"] for k in ket_qua if k["ok"]]
    trung = len(ips) - len(set(ips))
    ds_cookie = [p["ten"] for p in scraper.nap_cac_phien(
        "cookies.txt", None, 0.5, 12)]
    khac_nuoc = [k for k in ket_qua if k["ok"] and k["quoc_gia"] != "VN"]
    return jsonify({
        "ok": True,
        "so_ip": len(ds),
        "so_test": len(ket_qua),
        "ket_qua": ket_qua,
        "thong_bao": (
            f"{sum(1 for k in ket_qua if k['ok'])}/{len(ket_qua)} IP hoạt động"
            + (f" · {trung} IP trùng nhau" if trung else "")
            + (f" · {len(khac_nuoc)} IP ngoài VN" if khac_nuoc else "")
            + f" · {len(ds_cookie)} bộ cookie"
            + (f" · {len(ds)} IP ghép 1:1 được {min(len(ds), len(ds_cookie))} phiên"
               if len(ds) or len(ds_cookie) else "")),
    })


@app.route("/api/tai_xlsx")
def api_tai_xlsx():
    f = request.args.get("file")
    if not f:
        folder = os.path.join(DUONG_DAN, "du_lieu_exel")
        danh_sach = sorted(glob.glob(os.path.join(folder, "du_lieu_*.xlsx")), key=os.path.getmtime, reverse=True)
        if danh_sach:
            f = danh_sach[0]
    if f and os.path.isfile(f):
        return send_file(f, as_attachment=True, download_name=os.path.basename(f))
    return jsonify({"ok": False, "loi": "Không tìm thấy file Excel"}), 404


# ===================================================================
# 2. API TAB 2: KHO BÀI VIẾT (CONTENT POOL)
# ===================================================================
@app.route("/api/pool", methods=["GET"])
def api_lay_pool():
    st = request.args.get("trang_thai")
    key = request.args.get("key")
    nv = request.args.get("nhan_vat")
    search = request.args.get("search")
    sort_by = request.args.get("sort_by", "default")
    phien = request.args.get("phien")
    chi_chua = request.args.get("chi_chua_xu_ly") == "1"
    danh_sach = luong_b.lay_danh_sach_pool(
        trang_thai=st, key=key, nhan_vat=nv, tim_kiem=search, sort_by=sort_by,
        phien=phien, chi_chua_xu_ly=chi_chua, vung=_vung_cua_request())
    return jsonify({"ok": True, "tong_so": len(danh_sach), "data": danh_sach})


@app.route("/api/pool/phien", methods=["GET"])
def api_lay_pool_phien():
    """Danh sách các phiên cào (thời gian cào) để chọn trong Tab Kho Bài Viết."""
    ds = luong_b.lay_cac_phien_cao(vung=_vung_cua_request())
    return jsonify({"ok": True, "data": ds})


@app.route("/api/chinh_bai", methods=["GET"])
def api_lay_chinh_bai():
    """Tab 3: bài cần xử lý = đã chạy AI chưa xong (PROCESSING) hoặc LỖI AI (ERROR), lọc theo phiên."""
    phien = request.args.get("phien")
    ds = luong_b.lay_danh_sach_pool(nhieu_trang_thai={"PROCESSING", "ERROR"},
                                    phien=phien, vung=_vung_cua_request())
    return jsonify({"ok": True, "tong_so": len(ds), "data": ds})


@app.route("/api/chinh_bai/hoan_thanh", methods=["POST"])
def api_chinh_bai_hoan_thanh():
    """Tab 3: hoàn thành hàng loạt các bài đã tick → đặt SAN_SANG, chuyển sang Tab 4."""
    data = request.json or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"ok": False, "loi": "Vui lòng tick chọn ít nhất 1 bài"}), 400
    res = luong_b.hoan_thanh_hang_loat(ids)
    return jsonify({"ok": True, "message": f"Đã hoàn thành {res['so_thanh_cong']} bài",
                    "so_thanh_cong": res["so_thanh_cong"], "so_loi": res["so_loi"],
                    "loi": res["loi"]})


@app.route("/api/chinh_bai/phien", methods=["GET"])
def api_lay_chinh_bai_phien():
    """Tab 3: phiên cào chỉ gồm bài đã chạy AI xong."""
    ds = luong_b.lay_cac_phien_chinh_bai(vung=_vung_cua_request())
    return jsonify({"ok": True, "data": ds})


@app.route("/api/pool/filters", methods=["GET"])
def api_lay_pool_filters():
    store = lay_store()
    v = _vung_cua_request()
    danh_sach = [d for d in store.lay_tat_ca("CONTENT POOL") if vung_cua_bai(d) == v]
    keys = sorted(list({str(d.get("KEY") or "").strip() for d in danh_sach if str(d.get("KEY") or "").strip()}))
    nvs = sorted(list({str(d.get("Nhân vật/chủ đề") or "").strip() for d in danh_sach if str(d.get("Nhân vật/chủ đề") or "").strip()}))
    statuses = ["NEW", "PROCESSING", "SAN_SANG", "HOAN_THANH", "WEB_POSTED", "DONE", "ERROR", "HET_HAN"]
    return jsonify({"ok": True, "keys": keys, "nhan_vats": nvs, "statuses": statuses})


import unicodedata


def _bo_dau(s: str) -> str:
    """Chuyển chuỗi tiếng Việt có dấu thành không dấu để tìm kiếm mềm."""
    if not s:
        return ""
    s = s.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize('NFKD', s)
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()


@app.route("/api/tra_cuu_nhanh", methods=["GET"])
def api_tra_cuu_nhanh():
    """Tra cứu nhanh bài viết / Profile trên toàn bộ hệ thống (Pool + Master US + Master Global)."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": True, "data": [], "tong_so": 0, "q": ""})

    q_lower = q.lower()
    q_nodau = _bo_dau(q_lower)
    store = lay_store()
    pool = store.lay_tat_ca("CONTENT POOL")

    # 1. Nạp danh bạ UID để lấy UID và Tên Page chính xác
    danh_ba_map = {}
    for db_file in ["ngoài tool/danh_sach_uid.xlsx", "ngoài tool/danh_sach_uid_global.xlsx"]:
        if os.path.exists(db_file):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(db_file, data_only=True, read_only=True)
                ws = wb.active
                for r in ws.iter_rows(values_only=True):
                    if not r or r[0] == "PROFILE":
                        continue
                    p = str(r[0] or "").strip()
                    if p:
                        ten_p = str(r[2] or "").strip() if len(r) > 2 else ""
                        uid_val = str(r[3] or "").strip() if len(r) > 3 else ""
                        danh_ba_map[p.lower()] = {"ten_page": ten_p, "uid": uid_val, "profile": p}
            except Exception:
                pass

    # 2. Nạp Master US & Global để biết bài nào đang gán profile nào
    master_info = {}
    profile_info = {}
    for v_name, fpath in [("us", "du_lieu_exel/MASTER_DANG_BAI_US.xlsx"), ("global", "du_lieu_exel/MASTER_DANG_BAI_GLOBAL.xlsx")]:
        if os.path.exists(fpath):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(fpath, data_only=True, read_only=True)
                ws = wb.active
                for r in ws.iter_rows(values_only=True):
                    if not r or r[0] == "PROFILE":
                        continue
                    prof = str(r[0] or "").strip()
                    stt = r[1] if len(r) > 1 else ""
                    cid = str(r[2] or "").strip() if len(r) > 2 else ""
                    link = str(r[9] or "").strip() if len(r) > 9 else ""
                    page = str(r[14] or "").strip() if len(r) > 14 else ""
                    db_entry = danh_ba_map.get(prof.lower(), {})
                    uid = db_entry.get("uid", "")
                    if not page:
                        page = db_entry.get("ten_page", "")
                    info_obj = {
                        "profile": prof,
                        "stt": stt,
                        "cid": cid,
                        "page": page,
                        "uid": uid,
                        "vung": v_name,
                        "link": link
                    }
                    if prof:
                        profile_info[prof.lower()] = info_obj
                    if cid and "CHỜ BÀI" not in cid:
                        master_info[cid] = info_obj
            except Exception:
                pass

    ket_qua_map = {}

    STATUS_PRIORITY = {
        "HOAN_THANH": 5,
        "DONE": 4,
        "WEB_POSTED": 3,
        "SAN_SANG": 2,
        "PROCESSING": 1,
        "NEW": 0,
        "ERROR": -1,
    }

    # 3. Quét qua CONTENT POOL
    for r in pool:
        cid = str(r.get("Content ID") or "").strip()
        if not cid:
            continue

        cap_goc = str(r.get("Caption") or "")
        cap_moi = str(r.get("Caption mới") or "")
        key = str(r.get("KEY") or "")
        nv = str(r.get("Nhân vật/chủ đề") or "")
        art_url = str(r.get("Article URL") or "")
        dxm = str(r.get("Da_xuat_MASTER") or "")
        status = str(r.get("Status") or "")
        media = str(r.get("Media") or "")
        v_bai = vung_cua_bai(r)

        m_obj = master_info.get(cid)
        if m_obj:
            profile_name = m_obj["profile"]
            page_name = m_obj["page"]
            uid_val = m_obj["uid"]
            vung_master = m_obj["vung"]
            stt_master = m_obj["stt"]
            trang_thai_master = f"Đang gán trong Master ({vung_master.upper()})"
        elif dxm:
            profile_name = dxm.split("|")[-1].strip() if "|" in dxm else dxm
            page_name = danh_ba_map.get(profile_name.lower(), {}).get("ten_page", "")
            uid_val = danh_ba_map.get(profile_name.lower(), {}).get("uid", "")
            stt_master = ""
            trang_thai_master = f"Đã từng xuất Master ({dxm.split('|')[0].strip() if '|' in dxm else ''})"
        else:
            profile_name = ""
            page_name = ""
            uid_val = ""
            stt_master = ""
            trang_thai_master = "Chưa xuất Master (Trong kho)"

        url_slug = art_url.split("/")[-1].replace("-", " ")
        search_blob = f"{cid} {profile_name} {page_name} {uid_val} {key} {nv} {cap_goc} {cap_moi} {art_url} {url_slug} {dxm}".lower()
        search_blob_nodau = _bo_dau(search_blob)

        match = False
        match_score = 0

        if q_lower == profile_name.lower() or (profile_name and q_lower in profile_name.lower()):
            match = True
            match_score = 100
        elif q_lower == cid.lower() or q_lower in cid.lower():
            match = True
            match_score = 90
        elif q_lower in url_slug.lower() or q_lower in art_url.lower():
            match = True
            match_score = 80
        elif q_lower in nv.lower() or q_lower in key.lower() or q_nodau in _bo_dau(nv) or q_nodau in _bo_dau(key):
            match = True
            match_score = 70
        elif q_lower in search_blob or q_nodau in search_blob_nodau:
            match = True
            match_score = 50

        if match:
            tieu_de = ""
            if url_slug and len(url_slug) > 5:
                parts = url_slug.split()
                if parts and parts[-1].isdigit():
                    parts = parts[:-1]
                tieu_de = " ".join(parts).title()

            item = {
                "score": match_score,
                "content_id": cid,
                "profile": profile_name or "Chưa gán profile",
                "da_gan_master": bool(m_obj or dxm),
                "trang_thai_master": trang_thai_master,
                "stt_master": stt_master,
                "page": page_name,
                "uid": uid_val,
                "key": key,
                "nhan_vat": nv,
                "vung": v_bai,
                "status": status,
                "article_url": art_url,
                "tieu_de": tieu_de,
                "caption_goc": (cap_goc[:200] + "...") if len(cap_goc) > 200 else cap_goc,
                "caption_moi": (cap_moi[:200] + "...") if len(cap_moi) > 200 else cap_moi,
                "media": media,
            }

            if cid in ket_qua_map:
                old_prio = STATUS_PRIORITY.get(ket_qua_map[cid]["status"], 0)
                new_prio = STATUS_PRIORITY.get(status, 0)
                if new_prio > old_prio or (bool(m_obj or dxm) and not ket_qua_map[cid]["da_gan_master"]):
                    ket_qua_map[cid] = item
            else:
                ket_qua_map[cid] = item

    # 3.1. Deep search: Quét sâu trong các file bo_bai_*.json nếu tìm kiếm thông thường chưa ra kết quả
    if not ket_qua_map and len(q_lower) >= 3:
        import glob
        pool_by_cid = {str(r.get("Content ID") or ""): r for r in pool if r.get("Content ID")}
        da_match_cid = set()
        for fpath in glob.glob("du_lieu_fb/du_lieu_*/bo_bai_*.json"):
            try:
                with open(fpath, "r", encoding="utf-8") as fp:
                    b_data = json.load(fp)
                b_td = str(b_data.get("tieu_de") or "")
                b_cap = str(b_data.get("caption_lua_chon") or b_data.get("caption_version_1") or b_data.get("caption_moi") or "")
                b_bb = str(b_data.get("bai_bao") or "")
                b_text = f"{b_td} {b_cap} {b_bb}".lower()
                if q_lower in b_text or q_nodau in _bo_dau(b_text):
                    b_cid = str(b_data.get("content_id") or os.path.basename(fpath).replace("bo_bai_", "").replace(".json", "")).strip()
                    if not b_cid or b_cid in da_match_cid:
                        continue
                    da_match_cid.add(b_cid)
                    r = pool_by_cid.get(b_cid, {})
                    dxm = str(r.get("Da_xuat_MASTER") or "")
                    m_obj = master_info.get(b_cid)
                    if m_obj:
                        profile_name = m_obj["profile"]
                        page_name = m_obj["page"]
                        uid_val = m_obj["uid"]
                        vung_master = m_obj["vung"]
                        stt_master = m_obj["stt"]
                        trang_thai_master = f"Đang gán trong Master ({vung_master.upper()})"
                    elif dxm:
                        profile_name = dxm.split("|")[-1].strip() if "|" in dxm else dxm
                        page_name = danh_ba_map.get(profile_name.lower(), {}).get("ten_page", "")
                        uid_val = danh_ba_map.get(profile_name.lower(), {}).get("uid", "")
                        stt_master = ""
                        trang_thai_master = f"Đã từng xuất Master ({dxm.split('|')[0].strip() if '|' in dxm else ''})"
                    else:
                        profile_name = ""
                        page_name = ""
                        uid_val = ""
                        stt_master = ""
                        trang_thai_master = "Chưa xuất Master (Trong kho)"

                    ket_qua_map[b_cid] = {
                        "score": 60,
                        "content_id": b_cid,
                        "profile": profile_name or "Chưa gán profile",
                        "da_gan_master": bool(m_obj or dxm),
                        "trang_thai_master": trang_thai_master,
                        "stt_master": stt_master,
                        "page": page_name,
                        "uid": uid_val,
                        "key": str(r.get("KEY") or b_data.get("key") or ""),
                        "nhan_vat": str(r.get("Nhân vật/chủ đề") or b_data.get("nhan_vat") or ""),
                        "vung": str(r.get("Vung") or r.get("Web") or b_data.get("web") or "us"),
                        "status": str(r.get("Status") or "HOAN_THANH"),
                        "article_url": str(r.get("Article URL") or b_data.get("article_url") or b_data.get("link_bai") or ""),
                        "tieu_de": b_td or str(b_data.get("tieu_de") or ""),
                        "caption_goc": str(r.get("Caption") or r.get("Caption gốc") or ""),
                        "caption_moi": b_cap or str(r.get("Caption mới") or ""),
                        "media": str(r.get("Media") or b_data.get("anh_path") or ""),
                    }
            except Exception:
                pass

    ket_qua = list(ket_qua_map.values())

    # 4. Bổ sung các Profile trong Master nếu query tìm theo Profile mà profile đó đang CHỜ BÀI
    for prof_l, p_obj in profile_info.items():
        if q_lower in prof_l or prof_l in q_lower:
            cid_p = p_obj.get("cid", "")
            if not cid_p or "CHỜ BÀI" in cid_p:
                already = any(x.get("profile") == p_obj["profile"] for x in ket_qua)
                if not already:
                    ket_qua.append({
                        "score": 95,
                        "content_id": "CHỜ BÀI",
                        "profile": p_obj["profile"],
                        "da_gan_master": False,
                        "trang_thai_master": f"Đang CHỜ BÀI trong Master ({p_obj['vung'].upper()})",
                        "stt_master": p_obj.get("stt", ""),
                        "page": p_obj.get("page", ""),
                        "uid": p_obj.get("uid", ""),
                        "key": "",
                        "nhan_vat": "",
                        "vung": p_obj["vung"],
                        "status": "CHO_BAI",
                        "article_url": "",
                        "tieu_de": "",
                        "caption_goc": "(Profile hiện tại chưa có bài gán, đang ở trạng thái CHỜ BÀI)",
                        "caption_moi": "",
                        "media": "",
                    })

    ket_qua.sort(key=lambda x: -x["score"])

    return jsonify({
        "ok": True,
        "q": q,
        "tong_so": len(ket_qua),
        "data": ket_qua[:50]
    })


@app.route("/api/pool/xoa", methods=["POST"])
def api_pool_xoa():
    """Xóa 1 hoặc nhiều bài khỏi Content Pool theo Content ID."""
    data = request.json or {}
    ids = data.get("ids") or []
    if not ids:
        cid = (data.get("content_id") or "").strip()
        if cid:
            ids = [cid]
    if not ids:
        return jsonify({"ok": False, "loi": "Danh sách ID rỗng"}), 400

    store = lay_store()
    da_xoa = 0
    for cid in ids:
        tim = store.tim_dong("CONTENT POOL", "Content ID", str(cid))
        if tim:
            chi_so, _ = tim
            store.xoa_dong("CONTENT POOL", chi_so)
            da_xoa += 1
    return jsonify({"ok": True, "da_xoa": da_xoa})


# ===================================================================
# 3. API TAB 3: XỬ LÝ AI & ẢNH (DEEPSEEK + PILLOW)
# ===================================================================
@app.route("/api/pool/chi_tiet/<path:content_id>", methods=["GET"])
def api_chi_tiet_bai(content_id):
    bai = luong_b.lay_chi_tiet_bai(content_id)
    if not bai:
        return jsonify({"ok": False, "loi": "Không tìm thấy bài viết"}), 404
    return jsonify({"ok": True, "data": bai})


@app.route("/api/xu_ly_ai/<path:content_id>", methods=["POST"])
def api_xu_ly_ai_don_le(content_id):
    """Tab 3: sinh nội dung (3 Caption + Bài báo + link) — KHÔNG cắt ảnh."""
    data = request.json or {}
    format_type = (data.get("format_type") or "1:1")
    web = (data.get("web") or "").strip().lower()
    tim = lay_store().tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return jsonify({"ok": False, "loi": f"Không tìm thấy bài {content_id}"}), 404
    v_bai = vung_cua_bai(tim[1])
    if not web or web != v_bai:
        web = v_bai
    res = luong_b.xuat_noi_dung_ai_bai(content_id, format_type=format_type, web=web)
    if res.get("success"):
        return jsonify({"ok": True, "data": res.get("data"), "folder": res.get("folder")})
    return jsonify({"ok": False, "loi": res.get("message")}), 500


def _worker_batch(ids, format_type, web=None):
    global BATCH_STATUS
    BATCH_STATUS["dang_chay"] = True
    BATCH_STATUS["tong_so"] = len(ids)
    BATCH_STATUS["da_xong"] = 0
    BATCH_STATUS["loi"] = []
    BATCH_STATUS["thanh_cong"] = 0
    BATCH_STATUS["hoan_thanh"] = False

    callbacks = BATCH_STATUS["loi"]
    khoa = _BATCH_LOCK
    dang_chay = set()

    def lam_mot(cid):
        with khoa:
            dang_chay.add(cid)
            BATCH_STATUS["dang_xu_ly"] = ", ".join(sorted(dang_chay))
        try:
            res = luong_b.xuat_noi_dung_ai_bai(cid, format_type=format_type, web=web)
            if not res.get("success"):
                with khoa:
                    callbacks.append({"id": cid, "err": res.get("message")})
            else:
                with khoa:
                    BATCH_STATUS["thanh_cong"] += 1
        except Exception as e:
            with khoa:
                callbacks.append({"id": cid, "err": str(e)})
        finally:
            with khoa:
                dang_chay.discard(cid)
                BATCH_STATUS["dang_xu_ly"] = ", ".join(sorted(dang_chay))
                BATCH_STATUS["da_xong"] += 1

    with ThreadPoolExecutor(max_workers=_so_luong_song_song()) as executor:
        for _ in executor.map(lam_mot, ids):
            pass

    BATCH_STATUS["dang_chay"] = False
    BATCH_STATUS["hoan_thanh"] = True
    BATCH_STATUS["dang_xu_ly"] = ""


@app.route("/api/xu_ly_hang_loat", methods=["POST"])
def api_xu_ly_hang_loat():
    global BATCH_STATUS
    if BATCH_STATUS["dang_chay"]:
        return jsonify({"ok": False, "loi": "Đang có tiến trình xử lý hàng loạt chạy ngầm"}), 400

    data = request.json or {}
    ids = data.get("ids") or []
    format_type = data.get("format_type", "1:1")
    # Web theo VÙNG đang bật; nếu truyền web phải trùng vùng — không truyền thì
    # dùng vùng hiện tại. luong_b còn kiểm chéo từng bài: bài khác vùng -> fail
    # với thông báo rõ ràng (thay vì fail âm thầm 'Chưa chọn web' như trước).
    v = _vung_cua_request(data)
    web = (data.get("web") or "").strip().lower()
    if web and web not in ("us", "global"):
        return jsonify({"ok": False,
                        "loi": f"web='{web}' không hợp lệ — chỉ nhận 'us' hoặc 'global'"}), 400
    if web and web != v:
        return jsonify({"ok": False,
                        "loi": f"Trái vùng: công tắc đang bật {TEN_VUNG[v]} nhưng web "
                               f"chọn {TEN_NGAN[web]} — đổi công tắc vùng trước khi chạy"}), 400
    web = v

    if not ids:
        return jsonify({"ok": False, "loi": "Danh sách ID rỗng"}), 400

    t = threading.Thread(target=_worker_batch, args=(ids, format_type, web), daemon=True)
    t.start()
    return jsonify({"ok": True, "tong_so": len(ids), "web": web, "vung": v,
                    "message": f"Bắt đầu xử lý {len(ids)} bài viết "
                               f"({TEN_VUNG[v]} — web {TEN_NGAN[web]})"})


@app.route("/api/tien_do_hang_loat", methods=["GET"])
def api_tien_do_hang_loat():
    return jsonify(BATCH_STATUS)


def _worker_anh(ids, format_type):
    """Cắt ảnh từng bài trong nền (Tab 4) — dùng cho thread riêng."""
    global ANH_STATUS
    ANH_STATUS["dang_chay"] = True
    ANH_STATUS["tong_so"] = len(ids)
    ANH_STATUS["da_xong"] = 0
    ANH_STATUS["loi"] = []
    ANH_STATUS["hoan_thanh"] = False

    for cid in ids:
        ANH_STATUS["dang_xu_ly"] = cid
        try:
            res = luong_b.xu_ly_anh_hoan_thanh_mot_bai(cid, format_type=format_type)
            if not res.get("success"):
                ANH_STATUS["loi"].append({"id": cid, "err": res.get("message")})
        except Exception as e:
            ANH_STATUS["loi"].append({"id": cid, "err": str(e)})
        ANH_STATUS["da_xong"] += 1

    ANH_STATUS["dang_chay"] = False
    ANH_STATUS["hoan_thanh"] = True
    ANH_STATUS["dang_xu_ly"] = ""


@app.route("/api/xu_ly_anh", methods=["POST"])
def api_xu_ly_anh():
    """Tab 4: nhận ids + format_type → chạy nền cắt ảnh từng bài."""
    global ANH_STATUS
    if ANH_STATUS["dang_chay"]:
        return jsonify({"ok": False, "loi": "Đang có tiến trình cắt ảnh chạy ngầm"}), 400

    data = request.json or {}
    ids = data.get("ids") or []
    format_type = data.get("format_type", "1:1")
    if not ids:
        return jsonify({"ok": False, "loi": "Danh sách ID rỗng"}), 400

    t = threading.Thread(target=_worker_anh, args=(ids, format_type), daemon=True)
    t.start()
    return jsonify({"ok": True, "tong_so": len(ids), "message": f"Bắt đầu cắt ảnh {len(ids)} bài"})


@app.route("/api/tien_do_anh", methods=["GET"])
def api_tien_do_anh():
    return jsonify(ANH_STATUS)


# ---------------- Tạo Reel (Tab 4) ----------------
def _worker_reel(ids, format_type):
    """Cắt ảnh như nút Xử Lí Ảnh rồi kéo dài thành video reel 10s (Tab 4)."""
    global REEL_STATUS
    REEL_STATUS["dang_chay"] = True
    REEL_STATUS["tong_so"] = len(ids)
    REEL_STATUS["da_xong"] = 0
    REEL_STATUS["loi"] = []
    REEL_STATUS["hoan_thanh"] = False
    REEL_STATUS["dang_xu_ly"] = ""

    for cid in ids:
        REEL_STATUS["dang_xu_ly"] = cid
        try:
            # Bước 1: cắt ảnh CHÍNH (CÓ logo) — đặt Status = HOAN_THANH, chuyển Tab 5.
            # Ảnh đăng FB giữ logo.
            res = luong_b.xu_ly_anh_hoan_thanh_mot_bai(cid, format_type=format_type,
                                                       co_logo=True)
            if not res.get("success"):
                REEL_STATUS["loi"].append({"id": cid, "err": res.get("message")})
            else:
                # Bước 2: tạo ẢNH REEL riêng (KHÔNG logo) rồi dựng video reel 10s.
                # Không đụng ảnh chính đã có logo.
                res_reel = luong_b.xu_ly_anh_reel_mot_bai(cid, format_type=format_type)
                anh_reel = (res_reel.get("data") or {}).get("anh_path") if res_reel.get("success") else ""
                if not anh_reel:
                    REEL_STATUS["loi"].append({"id": cid, "err": res_reel.get("message") or "Không có ảnh reel"})
                else:
                    r = reel.tao_reel(anh_reel, co_nhac=True, ten_dau_ra=cid)
                    if not r.get("success"):
                        REEL_STATUS["loi"].append({"id": cid, "err": r.get("error")})
        except Exception as e:
            REEL_STATUS["loi"].append({"id": cid, "err": str(e)})
        REEL_STATUS["da_xong"] += 1

    REEL_STATUS["dang_chay"] = False
    REEL_STATUS["hoan_thanh"] = True
    REEL_STATUS["dang_xu_ly"] = ""


@app.route("/api/xu_ly_reel", methods=["POST"])
def api_xu_ly_reel():
    """Tab 4: nhận ids + format_type + co_nhac → chạy nền cắt ảnh + tạo reel."""
    global REEL_STATUS
    if REEL_STATUS["dang_chay"]:
        return jsonify({"ok": False, "loi": "Đang có tiến trình tạo reel chạy ngầm"}), 400

    data = request.json or {}
    ids = data.get("ids") or []
    format_type = data.get("format_type", "1:1")
    if not ids:
        return jsonify({"ok": False, "loi": "Danh sách ID rỗng"}), 400
    if not data.get("co_nhac"):
        return jsonify({"ok": False, "loi": "Vui lòng tích 'Chọn nhạc ngẫu nhiên' để tạo reel"}), 400

    t = threading.Thread(target=_worker_reel, args=(ids, format_type), daemon=True)
    t.start()
    return jsonify({"ok": True, "tong_so": len(ids), "message": f"Bắt đầu tạo reel {len(ids)} bài"})


@app.route("/api/tien_do_reel", methods=["GET"])
def api_tien_do_reel():
    return jsonify(REEL_STATUS)


@app.route("/api/luu_chinh_sua", methods=["POST"])
def api_luu_chinh_sua():
    data = request.json or {}
    cid = data.get("content_id")
    if not cid:
        return jsonify({"ok": False, "loi": "Thiếu content_id"}), 400
    res = luong_b.luu_chinh_sua_bai(cid, data)
    return jsonify({"ok": res.get("success"), "message": res.get("message")})


@app.route("/api/viet_lai_caption/<path:content_id>", methods=["POST"])
def api_viet_lai_caption(content_id):
    bai = luong_b.lay_chi_tiet_bai(content_id)
    if not bai:
        return jsonify({"ok": False, "loi": "Không tìm thấy bài"}), 404
    caption_goc = bai.get("Caption") or ""
    v = vung_cua_bai(bai)
    key = bai.get("KEY") or ""
    try:
        caps = viet_3_caption(caption_goc, vung=v, key=key)
        return jsonify({"ok": True, "data": caps})
    except Exception as e:
        return jsonify({"ok": False, "loi": str(e)}), 500


@app.route("/api/viet_lai_bai_bao/<path:content_id>", methods=["POST"])
def api_viet_lai_bai_bao(content_id):
    bai = luong_b.lay_chi_tiet_bai(content_id)
    if not bai:
        return jsonify({"ok": False, "loi": "Không tìm thấy bài"}), 404
    caption_goc = bai.get("Caption") or ""
    key = bai.get("KEY") or ""
    nv = bai.get("Nhân vật/chủ đề") or ""
    v = vung_cua_bai(bai)
    try:
        kq = viet_bai_bao_va_title(caption_goc, nhan_vat=nv, key=key, vung=v)
        return jsonify({"ok": True, "bai_bao": kq["bai_bao"],
                        "tieu_de": kq["tieu_de"],
                        "nguon_tieu_de": kq["nguon_tieu_de"]})
    except Exception as e:
        return jsonify({"ok": False, "loi": str(e)}), 500


# ===================================================================
# 4. API TAB 4: BÀI SẴN SÀNG ĐĂNG (ANTIDETECT BROWSER)
# ===================================================================
@app.route("/api/san_sang", methods=["GET"])
def api_lay_san_sang():
    danh_sach = luong_b.lay_danh_sach_san_sang(vung=_vung_cua_request())
    return jsonify({"ok": True, "tong_so": len(danh_sach), "data": danh_sach})


@app.route("/api/hoan_thanh", methods=["GET"])
def api_lay_hoan_thanh():
    """Tab 5: danh sách bài đã cắt ảnh xong (Status = HOAN_THANH).

    `phien` (query) : chỉ lấy bài thuộc phiên cào này; bỏ trống = tất cả các phiên.
    """
    phien = request.args.get("phien") or None
    danh_sach = luong_b.lay_danh_sach_hoan_thanh(phien=phien, vung=_vung_cua_request())
    return jsonify({"ok": True, "tong_so": len(danh_sach), "data": danh_sach})


@app.route("/api/hoan_thanh/chua_xuat", methods=["GET"])
def api_hoan_thanh_chua_xuat():
    """Tab 5: đếm số bài trong kho CHƯA xuất master, gom theo từng chủ đề (KEY).
    Tự động phát hiện chủ đề nào HẾT BÀI hoặc GẦN HẾT BÀI (<= 2 bài)
    để đánh dấu đỏ 'CẦN BỔ SUNG' phục vụ người dùng.
    """
    import xuat_master
    from collections import Counter
    phien = request.args.get("phien") or None
    v = _vung_cua_request()
    store = lay_store()
    dem = {}
    tong = 0
    for d in store.lay_tat_ca("CONTENT POOL"):
        if vung_cua_bai(d) != v:
            continue
        if str(d.get("Da_xuat_MASTER") or "").strip():
            continue
        # Chỉ đếm bài thực sự ĐÃ HOÀN THÀNH (bài lỗi ERROR hoặc NEW chưa qua AI không thể xuất Master)
        if str(d.get("Status") or "").strip() != "HOAN_THANH":
            continue
        if phien:
            cac_phien = d.get("Cac_phien_gap")
            if cac_phien is None:
                if str(d.get("Phien_cao") or "").strip() != phien:
                    continue
            elif phien not in (cac_phien if isinstance(cac_phien, list)
                               else [str(cac_phien)]):
                continue
        # KEY = chủ đề (mỗi KEY 1 file Excel); rỗng -> gom chung
        chu_de = (str(d.get("KEY") or "").strip()
                  or str(d.get("Chủ đề") or "").strip()
                  or "(không chủ đề)")
        dem[chu_de] = dem.get(chu_de, 0) + 1
        tong += 1

    # Nhu cầu bài từ danh bạ Live
    nhu_cau = Counter()
    for lm in ([1, 2] if v == "us" else [1]):
        try:
            db = xuat_master.doc_danh_ba(vung=v, loai_master=lm)
            for p in db:
                if xuat_master.du_chien(p.get("Trang thai")):
                    cd = str(p.get("Chu de") or "").strip()
                    if cd:
                        nhu_cau[cd] += 1
        except Exception:
            pass

    # Danh sách key từ nguồn
    keys_nguon = set()
    try:
        fp_nguon = os.path.join(DUONG_DAN, "du_lieu_traffic", f"nguon_{v}.json")
        if os.path.isfile(fp_nguon):
            with open(fp_nguon, "r", encoding="utf-8") as f:
                for it in json.load(f):
                    k = str(it.get("KEY") or "").strip()
                    if k:
                        keys_nguon.add(k)
    except Exception:
        pass

    # Tổng hợp tất cả key cần theo dõi
    tat_ca_keys = set(list(nhu_cau.keys()) + list(dem.keys()))
    tat_ca_keys.update(keys_nguon)

    canh_bao_thieu = []
    danh_sach_tat_ca = []

    for k in sorted(tat_ca_keys):
        k_chuan = xuat_master.chuan_hoa_chu_de(k)
        so_bai = 0
        for pk, count in dem.items():
            if pk.lower() == k.lower() or xuat_master.chuan_hoa_chu_de(pk) == k_chuan:
                so_bai += count

        nc = nhu_cau.get(k, 0)
        la_live = (nc > 0)

        if so_bai == 0:
            item = {
                "key": k,
                "so_bai": 0,
                "nhu_cau": nc,
                "la_live": la_live,
                "trang_thai": "HET_BAI",
                "nhan": f"{k} hết bài (cần bổ sung)",
                "mau": "danger"
            }
            danh_sach_tat_ca.append(item)
            if la_live or k in keys_nguon:
                canh_bao_thieu.append(item)
        elif so_bai <= 2 or (la_live and so_bai < nc):
            item = {
                "key": k,
                "so_bai": so_bai,
                "nhu_cau": nc,
                "la_live": la_live,
                "trang_thai": "SAP_HET",
                "nhan": f"{k} còn {so_bai} bài (cần bổ sung)",
                "mau": "danger"
            }
            danh_sach_tat_ca.append(item)
            canh_bao_thieu.append(item)
        else:
            item = {
                "key": k,
                "so_bai": so_bai,
                "nhu_cau": nc,
                "la_live": la_live,
                "trang_thai": "DU_BAI",
                "nhan": f"{k}: còn {so_bai} bài",
                "mau": "success"
            }
            danh_sach_tat_ca.append(item)

    canh_bao_thieu.sort(key=lambda x: (not x["la_live"], x["so_bai"], x["key"]))
    danh_sach_tat_ca.sort(key=lambda x: (x["trang_thai"] != "HET_BAI", x["trang_thai"] != "SAP_HET", -x["so_bai"], x["key"]))

    # Sắp xếp giảm dần: chủ đề nhiều bài chưa xuất trước
    ds = sorted(dem.items(), key=lambda kv: (-kv[1], kv[0]))
    resp = jsonify({
        "ok": True,
        "tong_chua_xuat": tong,
        "theo_chu_de": ds,
        "canh_bao_thieu": canh_bao_thieu,
        "danh_sach_tat_ca": danh_sach_tat_ca,
        "vung": v,
        "phien": phien or ""
    })
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/hoan_thanh/phien", methods=["GET"])
def api_lay_phien_hoan_thanh():
    """Tab 5: danh sách phiên cào có chứa bài HOAN_THANH để chọn lọc."""
    ds = luong_b.lay_cac_phien_hoan_thanh(vung=_vung_cua_request())
    return jsonify({"ok": True, "data": ds})


@app.route("/api/xuat_excel_tab5", methods=["POST"])
def api_xuat_excel_tab5():
    """Tab 5: xuất file Excel các bài HOAN_THANH (ids rỗng = lấy tất cả)."""
    data = request.json or {}
    ids = data.get("ids") or None
    try:
        import xlsxwriter
    except Exception as e:
        return jsonify({"ok": False, "loi": f"Thiếu xlsxwriter: {e}"}), 500

    v = _vung_cua_request(data)
    danh_sach = luong_b.lay_danh_sach_hoan_thanh(vung=v)
    if ids:
        danh_sach = [d for d in danh_sach if str(d.get("Content ID") or "") in set(str(i) for i in ids)]
    if not danh_sach:
        return jsonify({"ok": False,
                        "loi": f"Không có bài HOÀN THÀNH nào của vùng {TEN_VUNG[v]} để xuất"}), 400

    cot = list(dong_goi.COT_CSV)
    # Chèn cột "Đường dẫn reel" ngay sau "Đường dẫn ảnh" (chỉ trong Excel Tab 5)
    if "Đường dẫn ảnh" in cot:
        cot.insert(cot.index("Đường dẫn ảnh") + 1, "Đường dẫn reel")
    thu_muc = thu_muc_excel(v)
    xlsx_path = os.path.join(
        thu_muc, f"hoan_thanh_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

    wb = xlsxwriter.Workbook(xlsx_path)
    ws = wb.add_worksheet(f"Hoan Thanh {v.upper()}")
    header_format = wb.add_format({"bold": True, "bg_color": "#1F4E78",
                                   "font_color": "#FFFFFF", "align": "center",
                                   "valign": "vcenter", "border": 1,
                                   "border_color": "#D9D9D9"})
    text_format = wb.add_format({"valign": "top", "text_wrap": True,
                                 "border": 1, "border_color": "#D9D9D9"})

    # Hàng tiêu đề
    ws.write_row(0, 0, ["STT"] + cot, header_format)

    # Dữ liệu
    for i, r in enumerate(danh_sach, start=1):
        goi = r.get("goi_fb") or {}
        row = [
            i,
            r.get("Content ID") or "",
            r.get("KEY") or "",
            r.get("Nhân vật/chủ đề") or "",
            r.get("Source") or "",
            r.get("Thời gian đăng") or "",
            r.get("Cảm xúc") or 0,
            r.get("Bình luận") or 0,
            r.get("Chia sẻ") or 0,
            dong_goi.lam_phang_caption(r.get("Caption") or ""),
            dong_goi.chon_caption_xuat(goi, r),
            goi.get("article_url") or r.get("Article URL") or "",
            goi.get("anh_path") or r.get("Media") or "",
            r.get("reel_path") or "",
            r.get("Status") or "",
        ]
        ws.write_row(i, 0, row, text_format)

    # Độ rộng cột theo nội dung (xlsxwriter ghi 1 chiều nên ước lượng trước)
    cot_day_du = ["STT"] + cot
    for c, tieu_de in enumerate(cot_day_du):
        do_rong = max(len(tieu_de), 10)
        for j, r in enumerate(danh_sach, start=1):
            goi = r.get("goi_fb") or {}
            gia_tri = [
                str(j),
                r.get("Content ID") or "",
                r.get("KEY") or "",
                r.get("Nhân vật/chủ đề") or "",
                r.get("Source") or "",
                r.get("Thời gian đăng") or "",
                str(r.get("Cảm xúc") or 0),
                str(r.get("Bình luận") or 0),
                str(r.get("Chia sẻ") or 0),
                dong_goi.lam_phang_caption(r.get("Caption") or ""),
                dong_goi.chon_caption_xuat(goi, r),
                goi.get("article_url") or r.get("Article URL") or "",
                goi.get("anh_path") or r.get("Media") or "",
                r.get("reel_path") or "",
                r.get("Status") or "",
            ]
            do_rong = max(do_rong, min(len(gia_tri[c]) + 4, 60))
        ws.set_column(c, c, do_rong)

    wb.close()
    return jsonify({"ok": True, "xlsx_path": xlsx_path, "so_dong": len(danh_sach), "file": xlsx_path})


def _ten_sheet_xlsx(ten: str) -> str:
    """Tên sheet Excel hợp lệ: cấm [ ] : * ? / \\ , tối đa 31 ký tự,
    không bắt đầu/kết thúc bằng dấu nháy đơn. VD: 'UFC/Boxing' -> 'UFC_Boxing'."""
    ten = re.sub(r"[\[\]:*?/\\]", "_", (ten or "").strip()) or "Khac"
    ten = ten.strip("'") or "Khac"
    return ten[:31]


def _ten_file_an_toan(ten: str) -> str:
    """Tên file an toàn trên Windows nhưng GIỮ NGUYÊN tiếng Việt có dấu.

    KEY là tên chủ đề/file (2026-09-14): 'Chính trị' -> san_sang_Chính_trị.xlsx.
    Bản cũ dùng [^a-zA-Z0-9] -> 'Chính trị' thành 'Ch_nh_tr', dễ lẫn."""
    ten = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(ten or "").strip())
    ten = re.sub(r"\s+", "_", ten).strip("_.")
    return ten[:60] or "Khac"


def _duong_dan_ghi_duoc(duong_dan: str) -> str:
    """Excel đang MỞ file đích sẽ khóa cứng (PermissionError lúc wb.close()).

    Phát hiện sớm bằng cách thử mở ghi; nếu bị khóa thì đổi sang tên có hậu tố
    giờ (…_0916.xlsx) để chủ đề đó vẫn xuất được, thay vì làm hỏng cả đợt xuất.
    """
    try:
        with open(duong_dan, "a"):
            return duong_dan
    except PermissionError:
        goc, part = os.path.split(duong_dan)
        stem, ext = os.path.splitext(part)
        moi = os.path.join(goc, f"{stem}_{datetime.now():%H%M%S}{ext}")
        print(f"[Excel] '{part}' đang mở trong Excel -> xuất sang "
              f"'{os.path.basename(moi)}'", flush=True)
        return moi
    except OSError:
        return duong_dan


def _xuat_excel_hoan_thanh_impl(phien: str | None = None,
                                vung_hien: str | None = None,
                                danh_sach: list = None) -> tuple:
    """Impl dùng chung: xuất Excel san_sang_<CHUDE>.xlsx cho mọi bài HOAN_THANH.

    `vung_hien`: vùng để xuất (mặc định = vùng đang chọn). Bài khác vùng bị loại —
    mỗi vùng có thư mục `du_lieu_exel/US|GLOBAL` riêng (vung.thu_muc_excel).
    `danh_sach`: truyền sẵn danh sách đã làm giàu thì dùng luôn (KHÔNG tự gọi
    lay_danh_sach_hoan_thanh 2 lần ở các API khác nhau -> 2 kết quả có thể lệch).
    `phien`: nếu truyền (FULL AUTO) → chỉ xuất bài của PHIÊN cào đó, không lẫn
    bài cũ đang dở trong kho. None (nút Tab 5) → xuất toàn bộ bài HOAN_THANH.
    Trả về (cac_file, thu_muc); raise ValueError nếu không có bài.
    Dùng cho cả nút Tab 5 (route) và bước 4 của FULL AUTO."""
    import xlsxwriter

    v_hien = chuan_vung(vung_hien if vung_hien is not None else lay_vung())
    if danh_sach is None:
        danh_sach = luong_b.lay_danh_sach_hoan_thanh(phien=phien, vung=v_hien)
    else:
        danh_sach = [r for r in danh_sach if vung_cua_bai(r) == v_hien]
        if phien:
            danh_sach = [r for r in danh_sach
                         if phien in (r.get("Cac_phien_gap") or [r.get("Phien_cao")])]
    if not danh_sach:
        raise ValueError(f"Không có bài HOÀN THÀNH nào của vùng {TEN_VUNG[v_hien]}"
                         + (f" (phiên {phien})" if phien else ""))

    # Bài nào chưa có chủ đề → gán nhanh bằng KEY khớp + từ khoá trong nội dung
    # (KHÔNG gọi AI ở đây để tránh treo; AI phân loại đã chạy lúc xử lý bài).
    store = lay_store()
    for r in danh_sach:
        if (r.get("chu_de") or "").strip():
            continue
        cid = str(r.get("Content ID") or "").strip()
        if not cid:
            continue
        key = r.get("KEY") or ""
        noi_dung = r.get("Caption") or r.get("Caption mới") or ""
        chu_de = luong_b.gan_chu_de_cho_bai_khong_ai(key or "", noi_dung or "")
        if chu_de:
            tim = store.tim_dong("CONTENT POOL", "Content ID", cid)
            if tim:
                idx, row = tim
                row["Chủ đề"] = chu_de
                store.cap_nhat_dong("CONTENT POOL", idx, row)
            r["chu_de"] = chu_de

    # Gom theo chủ đề
    nhom = {}
    for r in danh_sach:
        chu_de = (r.get("chu_de") or "").strip()
        if not chu_de:
            chu_de = "Khac"
        nhom.setdefault(chu_de, []).append(r)

    cot = list(dong_goi.COT_CSV)
    if "Đường dẫn ảnh" in cot:
        cot.insert(cot.index("Đường dẫn ảnh") + 1, "Đường dẫn reel")
    if "Chủ đề" not in cot:
        cot.append("Chủ đề")

    thu_muc = thu_muc_excel(v_hien)
    os.makedirs(thu_muc, exist_ok=True)
    cac_file = []

    for chu_de, ds in sorted(nhom.items()):
        ten_file_safe = _ten_file_an_toan(chu_de)
        xlsx_path = os.path.join(thu_muc, f"san_sang_{ten_file_safe}.xlsx")
        xlsx_path = _duong_dan_ghi_duoc(xlsx_path)

        wb = None
        try:
            wb = xlsxwriter.Workbook(xlsx_path)
            ws = wb.add_worksheet(_ten_sheet_xlsx(chu_de))

            header_format = wb.add_format({"bold": True, "bg_color": "#1F4E78",
                                           "font_color": "#FFFFFF", "align": "center",
                                           "valign": "vcenter", "border": 1,
                                           "border_color": "#D9D9D9"})
            text_format = wb.add_format({"valign": "top", "text_wrap": True,
                                         "border": 1, "border_color": "#D9D9D9"})

            ws.write_row(0, 0, ["STT"] + cot, header_format)
            for i, r in enumerate(ds, start=1):
                goi = r.get("goi_fb") or {}
                chu_de_this = r.get("chu_de") or ""
                row = [
                    i,
                    r.get("Content ID") or "",
                    r.get("KEY") or "",
                    r.get("Nhân vật/chủ đề") or "",
                    r.get("Source") or "",
                    r.get("Thời gian đăng") or "",
                    r.get("Cảm xúc") or 0,
                    r.get("Bình luận") or 0,
                    r.get("Chia sẻ") or 0,
                    dong_goi.lam_phang_caption(r.get("Caption") or ""),
                    dong_goi.chon_caption_xuat(goi, r),
                    goi.get("article_url") or r.get("Article URL") or "",
                    goi.get("anh_path") or r.get("Media") or "",
                    r.get("reel_path") or "",
                    r.get("Status") or "",
                    chu_de_this,
                ]
                ws.write_row(i, 0, row, text_format)
            wb.close()
            wb = None
            cac_file.append({"chu_de": chu_de, "so_bai": len(ds), "file": xlsx_path})
        except Exception as e:
            # 1 chủ đề lỗi (file bị Excel khóa, đĩa đầy...) KHÔNG làm hỏng cả đợt.
            print(f"[Excel] bo qua chu_de '{chu_de}': {type(e).__name__}: {e}", flush=True)
            if wb is not None:
                try:
                    wb.close()
                except Exception:
                    pass
            cac_file.append({"chu_de": chu_de, "so_bai": len(ds),
                             "file": xlsx_path, "loi": str(e)})

    return cac_file, thu_muc


@app.route("/api/xuat_excel_theo_chu_de", methods=["POST"])
def api_xuat_excel_theo_chu_de():
    """Xuất riêng file Excel cho mỗi chủ đề: san_sang_<CHUDE>.xlsx.

    Lấy tất cả bài HOAN_THANH, nhóm theo chủ đề, mỗi chủ đề 1 file.
    """
    try:
        cac_file, thu_muc = _xuat_excel_hoan_thanh_impl()
    except ValueError as e:
        return jsonify({"ok": False, "loi": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "loi": f"Thiếu xlsxwriter hoặc lỗi ghi file: {e}"}), 500

    return jsonify({"ok": True, "so_file": len(cac_file), "cac_file": cac_file,
                    "thu_muc": thu_muc})
@app.route("/api/xac_nhan_da_dang", methods=["POST"])
def api_xac_nhan_da_dang():
    cid = (request.json or {}).get("content_id")
    if not cid:
        return jsonify({"ok": False, "loi": "Thiếu content_id"}), 400
    luong_b.danh_dau_da_dang_fb(cid)
    return jsonify({"ok": True, "message": f"Đã đánh dấu bài {cid} hoàn tất (DONE)"})


@app.route("/api/xuat_master", methods=["POST"])
def api_xuat_master():
    """Xuất MASTER_DANG_BAI.xlsx: MỖI profile Live đúng 1 bài (round-robin trong chủ đề).

    - Chỉ lấy bài HOAN_THANH chưa có cột Da_xuat_MASTER trong Content Pool.
    - Ghi đè file master mỗi lần xuất; bài vừa gán được đánh dấu 'ngày-giờ | PROFILE'.
    - Chủ đề còn bài nhưng hết profile Live nhận -> để lại đợi lần sau + cảnh báo.
    """
    try:
        import traceback as _tb
        import xuat_master
        data = request.json or {}
        v = _vung_cua_request(data)
        loai_master = int(data.get("loai_master", 1))
        kq = xuat_master.xuat_master(store=lay_store(), ghi_dau=True, vung=v, loai_master=loai_master)
    except Exception as e:
        _tb.print_exc()
        return jsonify({"ok": False, "loi": str(e)}), 500

    return jsonify({
        "ok": True,
        "vung": kq.get("vung"), "ten_vung": kq.get("ten_vung"),
        "file": os.path.basename(kq["file"]),
        "duong_dan": kq["file"],
        "tong_dong": kq["tong_dong"],
        "so_bai_xuat": kq["so_bai_xuat"],
        "so_cho_bai": kq["tong_dong"] - kq["so_bai_xuat"],
        "cho_lan_sau": kq["cho_lan_sau"],
        "canh_bao": kq["canh_bao"][:30],
    })


@app.route("/api/va_master", methods=["POST"])
def api_va_master():
    """Vá dòng CHỜ BÀI trong MASTER_DANG_BAI.xlsx — GIỮ NGUYÊN bài đã gán.

    Chỉ điền bài mới vào dòng đang CHỜ BÀI; không bao giờ rút bài ra.
    Bấm nhiều lần không mất bài, mỗi lần lấp thêm cho đến khi đủ.
    """
    try:
        import traceback as _tb
        import xuat_master
        data = request.json or {}
        v = _vung_cua_request(data)
        loai_master = int(data.get("loai_master", 1))
        kq = xuat_master.va_master(store=lay_store(), ghi_dau=True, vung=v, loai_master=loai_master)
    except Exception as e:
        _tb.print_exc()
        return jsonify({"ok": False, "loi": str(e)}), 400

    return jsonify({
        "ok": True,
        "vung": kq.get("vung"), "ten_vung": kq.get("ten_vung"),
        "file": os.path.basename(kq["file"]),
        "duong_dan": kq["file"],
        "tong_dong": kq["tong_dong"],
        "giu_nguyen": kq["giu_nguyen"],
        "so_vao_moi": kq["so_vao_moi"],
        "con_cho_bai": kq["con_cho_bai"],
        "so_reel_bo_sung": kq.get("so_reel_bo_sung"),
        "sai_vung": kq.get("sai_vung"),
        "cho_lan_sau": kq["cho_lan_sau"],
        "canh_bao": kq["canh_bao"][:30],
    })


@app.route("/api/mo_thu_muc", methods=["POST"])
def api_mo_thu_muc():
    folder = (request.json or {}).get("folder")
    if not folder or not os.path.exists(folder):
        folder = os.path.join(DUONG_DAN, "du_lieu_fb")
    try:
        if os.name == "nt":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", folder])
        return jsonify({"ok": True, "folder": folder})
    except Exception as e:
        return jsonify({"ok": False, "loi": str(e)})


# ===================================================================
# 7. API TAB 6: CẤU HÌNH AI
# ===================================================================
@app.route("/api/cau_hinh", methods=["GET"])
def api_lay_cau_hinh():
    """Trả về cấu hình AI hiện tại (provider, api_key, model, base_url)."""
    cfg = load_config()
    return jsonify({
        "ok": True,
        "provider": cfg["ai"]["provider"],
        "api_key": cfg["ai"]["api_key"],
        "model": cfg["ai"]["model"],
        "base_url": cfg["ai"].get("base_url") or "",
    })


@app.route("/api/luu_cau_hinh", methods=["POST"])
def api_luu_cau_hinh():
    """Lưu cấu hình AI vào config.json."""
    data = request.json or {}
    cfg = load_config()
    cfg["ai"]["provider"] = (data.get("provider") or cfg["ai"]["provider"]).strip()
    cfg["ai"]["api_key"] = (data.get("api_key") or cfg["ai"]["api_key"]).strip()
    cfg["ai"]["model"] = (data.get("model") or cfg["ai"]["model"]).strip()
    cfg["ai"]["base_url"] = (data.get("base_url") or cfg["ai"].get("base_url") or "").strip()
    try:
        ghi_config(cfg)
        return jsonify({"ok": True, "message": "Đã lưu cấu hình AI thành công."})
    except Exception as e:
        return jsonify({"ok": False, "loi": f"Lỗi ghi cấu hình: {e}"}), 500


@app.route("/api/kiem_tra_ai", methods=["POST"])
def api_kiem_tra_ai():
    """Kiểm tra kết nối API (provider, api_key, model từ body)."""
    data = request.json or {}
    provider = data.get("provider") or ""
    api_key = data.get("api_key") or ""
    model = data.get("model") or ""
    base_url = data.get("base_url") or ""
    ket_qua = kiem_tra_api_key(provider, api_key, model, base_url)
    if ket_qua["ok"]:
        return jsonify({"ok": True, "message": ket_qua["message"]})
    return jsonify({"ok": False, "loi": ket_qua["message"]}), 400


@app.route("/api/ai/models", methods=["POST"])
def api_lay_danh_sach_model():
    """Lấy danh sách model của custom/OpenAI-compatible provider (endpoint /v1/models)."""
    data = request.json or {}
    base_url = data.get("base_url") or ""
    api_key = data.get("api_key") or ""
    provider = data.get("provider") or ""

    if provider != "custom":
        return jsonify({"ok": False, "loi": "Chức năng tự thêm model chỉ dùng cho Custom provider."}), 400
    if not base_url:
        return jsonify({"ok": False, "loi": "Chưa nhập Base URL."}), 400

    import requests
    url = base_url.strip().rstrip("/")
    neu_duoi = url.rsplit("/", 1)[-1]
    # Nếu người dùng nhập tới .../chat/completions thì bỏ phần đó để dùng .../models
    if neu_duoi in ("chat/completions", "completions"):
        url = url.rsplit("/", 1)[0]
    url = url + "/models"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.get(url, headers=headers, timeout=60)
    except Exception as e:
        return jsonify({"ok": False, "loi": f"Lỗi kết nối: {str(e)[:180]}"}), 400

    if resp.status_code >= 400:
        try:
            j = resp.json()
            msg = j.get("error", {}).get("message") if isinstance(j.get("error"), dict) else str(j.get("error", ""))
            msg = msg or resp.text[:200]
        except Exception:
            msg = resp.text[:200]
        return jsonify({"ok": False, "loi": f"Lỗi lấy model (HTTP {resp.status_code}): {msg[:200]}"}), 400

    try:
        data_json = resp.json()
        danh_sach = data_json.get("data", [])
    except Exception:
        return jsonify({"ok": False, "loi": "Phản hồi không đúng định dạng (không có danh sách model)."}), 400

    models = [str(m.get("id") or "").strip() for m in danh_sach if m.get("id")]
    models = [m for m in models if m]
    if not models:
        return jsonify({"ok": False, "loi": "Không tìm thấy model nào trong phản hồi."}), 400

    models = sorted(set(models))
    return jsonify({"ok": True, "models": models})


# Phục vụ file media ảnh local (bao gồm cả video reel)
@app.route("/media/<path:filename>")
def serve_media(filename):
    # Cho phép tải ảnh từ du_lieu_fb hoặc du_lieu_images, và video reel từ du_lieu_reel
    duong_dan_fb = os.path.join(DUONG_DAN, "du_lieu_fb")
    duong_dan_img = os.path.join(DUONG_DAN, "du_lieu_images")
    duong_dan_reel = os.path.join(DUONG_DAN, "du_lieu_reel")
    if os.path.exists(os.path.join(duong_dan_fb, filename)):
        return send_from_directory(duong_dan_fb, filename)
    if os.path.exists(os.path.join(duong_dan_img, filename)):
        return send_from_directory(duong_dan_img, filename)
    if os.path.exists(os.path.join(duong_dan_reel, filename)):
        return send_from_directory(duong_dan_reel, filename)
    return send_from_directory(DUONG_DAN, filename)


# ===================================================================
# API GIÁM SÁT BÀI NỔ 24/24 & CẢNH BÁO 0 CMT (OPENCLAW TELEGRAM)
# ===================================================================

@app.route("/api/bai_no/trang_thai", methods=["GET"])
def api_bai_no_trang_thai():
    st = kiem_tra_bai_no.doc_trang_thai()
    st["log"] = st.get("logs", [])
    resp = jsonify(st)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/bai_no/cau_hinh", methods=["GET", "POST"])
def api_bai_no_cau_hinh():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        cfg = kiem_tra_bai_no.doc_cau_hinh()
        if "telegram_target" in data:
            val = str(data["telegram_target"]).strip()
            if val == "5314274362":
                val = "-5314274362"
            cfg["telegram_target"] = val
        if "nguong_view" in data:
            cfg["nguong_view"] = max(1, int(data["nguong_view"] or 1000))
        if "nguong_like" in data:
            cfg["nguong_like"] = max(1, int(data["nguong_like"] or 10))
        if "so_bai_quet" in data:
            cfg["so_bai_quet"] = max(1, int(data["so_bai_quet"] or 10))
        if "chu_ky_phut" in data:
            cfg["chu_ky_phut"] = max(1, int(data["chu_ky_phut"] or 5))
        if "song_song" in data:
            cfg["song_song"] = max(1, min(6, int(data["song_song"] or 3)))
        if "masters_kich_hoat" in data:
            cfg["masters_kich_hoat"] = data["masters_kich_hoat"]
        if "danh_sach_profile" in data:
            cfg["danh_sach_profile"] = data["danh_sach_profile"]
        kiem_tra_bai_no.luu_cau_hinh(cfg)
        return jsonify({"ok": True, "thong_bao": "Đã lưu cấu hình giám sát bài nổ!", "cau_hinh": cfg})
    
    cfg = kiem_tra_bai_no.doc_cau_hinh()
    kq_3m = kiem_tra_bai_no.nap_danh_sach_profile_tu_3_master(cfg.get("masters_kich_hoat"))
    cfg["so_luong_theo_master"] = kq_3m.get("so_luong_theo_master", {})
    return jsonify(cfg)


@app.route("/api/bai_no/bat_dau", methods=["POST"])
def api_bai_no_bat_dau():
    ok, msg = kiem_tra_bai_no.bat_dau_giam_sat()
    return jsonify({"ok": ok, "thong_bao": msg})


@app.route("/api/bai_no/dung", methods=["POST"])
def api_bai_no_dung():
    ok, msg = kiem_tra_bai_no.dung_giam_sat()
    return jsonify({"ok": ok, "thong_bao": msg})


@app.route("/api/bai_no/quet_ngay", methods=["POST"])
def api_bai_no_quet_ngay():
    ok, msg = kiem_tra_bai_no.quet_thu_cong_ngay()
    return jsonify({"ok": ok, "thong_bao": msg})


@app.route("/api/bai_no/gui_test", methods=["POST"])
def api_bai_no_gui_test():
    data = request.get_json(silent=True) or {}
    target = (data.get("target") or "").strip()
    if not target:
        cfg = kiem_tra_bai_no.doc_cau_hinh()
        target = cfg.get("telegram_target", "").strip()
    if target == "5314274362":
        target = "-5314274362"
    if not target:
        return jsonify({"ok": False, "thong_bao": "Vui lòng nhập Telegram Target (Chat ID / Group ID)"})
    test_msg = (
        "🔔 [TEST KẾT NỐI OPENCLAW]\n"
        "✅ Hệ thống Giám Sát Bài Nổ 24/24 đã kết nối Telegram thành công!\n"
        f"⏰ Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok, err = kiem_tra_bai_no.gui_thong_bao_openclaw(target, test_msg)
    if ok and target.startswith("-"):
        cfg = kiem_tra_bai_no.doc_cau_hinh()
        if cfg.get("telegram_target") != target:
            cfg["telegram_target"] = target
            kiem_tra_bai_no.luu_cau_hinh(cfg)
    return jsonify({"ok": ok, "thong_bao": err if ok else f"Gửi thất bại: {err}", "target_chuan": target if ok else None})


@app.route("/api/bai_no/nap_tu_master", methods=["POST"])
def api_bai_no_nap_tu_master():
    data = request.get_json(silent=True) or {}
    cfg = kiem_tra_bai_no.doc_cau_hinh()
    masters_kich_hoat = data.get("masters_kich_hoat") or cfg.get("masters_kich_hoat", {"us": True, "us2": True, "global": True})
    cfg["masters_kich_hoat"] = masters_kich_hoat
    kq = kiem_tra_bai_no.nap_danh_sach_profile_tu_3_master(masters_kich_hoat)
    ds = kq.get("danh_sach_kich_hoat", [])
    cfg["danh_sach_profile"] = ds
    kiem_tra_bai_no.luu_cau_hinh(cfg)
    so_us = kq["so_luong_theo_master"].get("us", 0)
    so_us2 = kq["so_luong_theo_master"].get("us2", 0)
    so_glo = kq["so_luong_theo_master"].get("global", 0)
    return jsonify({
        "ok": True,
        "so_luong": len(ds),
        "so_luong_theo_master": kq["so_luong_theo_master"],
        "masters_kich_hoat": masters_kich_hoat,
        "danh_sach": ds,
        "thong_bao": f"Đã nạp {len(ds)} profile từ 3 Master (US: {so_us}, US 2: {so_us2}, Global: {so_glo})!"
    })


@app.route("/api/bai_no/lich_su", methods=["GET"])
def api_bai_no_lich_su():
    resp = jsonify(kiem_tra_bai_no.doc_lich_su())
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/bai_no/danh_dau_ok", methods=["POST"])
def api_bai_no_danh_dau_ok():
    data = request.get_json(force=True, silent=True) or {}
    identifier = data.get("id") or data.get("link_fb") or data.get("post_id") or ""
    da_gan_cmt = bool(data.get("da_gan_cmt", True))
    if not identifier:
        return jsonify({"ok": False, "thong_bao": "Thiếu mã định danh bài viết (id/post_id/link_fb)"}), 400
    ok, msg = kiem_tra_bai_no.danh_dau_bai_no_ok(identifier, da_gan_cmt=da_gan_cmt)
    return jsonify({"ok": ok, "thong_bao": msg, "da_gan_cmt": da_gan_cmt})


# ===================================================================
# TỰ ĐỘNG CẬP NHẬT MASTER 4 KHUNG GIỜ (0h, 8h, 16h, 20h - chạy trước 120p)
# ===================================================================
import tu_dong_master

@app.route("/api/tu_dong_master/trang_thai", methods=["GET"])
def api_tu_dong_master_trang_thai():
    st = tu_dong_master.doc_trang_thai()
    st["log"] = st.get("logs", [])
    return jsonify(st)

@app.route("/api/tu_dong_master/cau_hinh", methods=["GET", "POST"])
def api_tu_dong_master_cau_hinh():
    if request.method == "POST":
        data = request.json or {}
        cfg = tu_dong_master.doc_cau_hinh()
        for k in ("bat_tu_dong", "khung_gio_dang", "chay_truoc_phut", "cac_master", "tu_dong_bu_bai", "tu_dong_cao_khi_thieu", "dong_bo_downloads"):
            if k in data:
                cfg[k] = data[k]
        tu_dong_master.luu_cau_hinh(cfg)
        return jsonify({"ok": True, "cau_hinh": cfg})
    return jsonify(tu_dong_master.doc_cau_hinh())

@app.route("/api/tu_dong_master/bat", methods=["POST"])
def api_tu_dong_master_bat():
    ok, msg = tu_dong_master.bat_dau_tu_dong()
    return jsonify({"ok": ok, "thong_bao": msg})

@app.route("/api/tu_dong_master/tat", methods=["POST"])
def api_tu_dong_master_tat():
    ok, msg = tu_dong_master.dung_tu_dong()
    return jsonify({"ok": ok, "thong_bao": msg})

@app.route("/api/tu_dong_master/chay_ngay", methods=["POST"])
def api_tu_dong_master_chay_ngay():
    ok, msg = tu_dong_master.chay_ngay_thu_cong()
    return jsonify({"ok": ok, "thong_bao": msg})


def _dia_chi_trinh_duyet():
    """URL mở tự động = IP mạng LAN HIỆN HÀNH (không phải 127.0.0.1 —
    bản 127.0.0.1 bị VPN split-tunnel chặn từ tiến trình này và máy khác
    cũng không vào được). Dò động theo định tuyến mặc định nên DHCP đổi
    IP vẫn đúng; không dò được thì fallback 127.0.0.1."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))   # không gửi packet thật — chỉ chọn route
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return f"http://{ip}:5001"
    except OSError:
        pass
    return "http://127.0.0.1:5001"


def _cho_server_san_sang(url, giay_toi_da=20.0):
    """Chờ cổng 5001 thực sự nhận kết nối rồi mới mở trình duyệt,
    tránh trường hợp browser mở ra trang trắng 'không truy cập được'."""
    import socket
    cuoi = time.time() + giay_toi_da
    while time.time() < cuoi:
        for host in ("127.0.0.1", "0.0.0.0"):
            try:
                s = socket.create_connection(("127.0.0.1", 5001), timeout=0.6)
                s.close()
                return True
            except OSError:
                break
        time.sleep(0.4)
    return False


def chong_treo_he_thong():
    """Tối ưu hóa chạy 24/7 không bị treo/đơ:
    1. Tắt QuickEdit Mode của Console Windows (chống dừng tiến trình khi click chuột).
    2. Ngăn Windows đi vào chế độ Sleep / Standby / Hibernate khi tool đang chạy.
    3. Giảm tải log Werkzeug polling định kỳ (tránh nghẽn buffer terminal).
    4. Khởi động luồng dọn rác RAM định kỳ.
    """
    import ctypes
    if os.name == "nt":
        # 1. Tắt QuickEdit mode của Console
        try:
            kernel32 = ctypes.windll.kernel32
            h_stdin = kernel32.GetStdHandle(-10) # STD_INPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
                ENABLE_QUICK_EDIT_MODE = 0x0040
                ENABLE_EXTENDED_FLAGS = 0x0080
                new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
                kernel32.SetConsoleMode(h_stdin, new_mode)
        except Exception:
            pass

        # 2. Ngăn Windows Sleep / Standby khi tool đang chạy
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_AWAYMODE_REQUIRED = 0x00000040
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            )
        except Exception:
            pass

    # 3. Lọc giảm log Werkzeug: Chỉ log khi có lỗi (WARNING/ERROR),
    # ẩn các request GET polling lặp đi lặp lại 2-4 giây/lần gây tràn console.
    try:
        import logging
        wz_log = logging.getLogger('werkzeug')
        wz_log.setLevel(logging.WARNING)
    except Exception:
        pass

    # 4. Luồng dọn dẹp RAM định kỳ mỗi 60 phút
    def _don_ram_dinh_ky():
        import gc
        while True:
            time.sleep(3600)
            try:
                gc.collect()
            except Exception:
                pass
    threading.Thread(target=_don_ram_dinh_ky, daemon=True).start()


if __name__ == "__main__":
    chong_treo_he_thong()
    _url_mang = _dia_chi_trinh_duyet()
    print("=" * 60)
    print("🚀 GIAO DIỆN WEB UI TOOL TRAFFIC FACEBOOK (4 TAB)")
    print(f"👉 Mở trình duyệt tại: {_url_mang}")
    print("🛡️ Đã kích hoạt cơ chế Chống Treo Terminal & Ngăn Sleep 24/7")
    print("=" * 60)

    # Khởi động dịch vụ tự động Master nếu được bật
    try:
        # Luôn khôi phục trạng thái 'đang chạy' bị kẹt từ phiên trước
        # (kể cả khi dịch vụ tự động đang tắt) để nút Chạy ngay không bị khóa.
        tu_dong_master.khoi_phuc_trang_thai_ket()
        cfg_td = tu_dong_master.doc_cau_hinh()
        if cfg_td.get("bat_tu_dong", True):
            tu_dong_master.bat_dau_tu_dong()
    except Exception:
        pass
    threading.Thread(target=HEN_GIO.vong_lap, daemon=True).start()
    if os.environ.get("DSH_NO_BROWSER") != "1":
        # Mở trình duyệt SAU khi server đã listen (chạy ở thread nền để
        # không chặn app.run).
        threading.Thread(
            target=lambda: (_cho_server_san_sang(_url_mang),
                            webbrowser.open(_url_mang)),
            daemon=True).start()
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
