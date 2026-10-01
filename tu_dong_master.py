# -*- coding: utf-8 -*-
"""Mô-đun TỰ ĐỘNG CẬP NHẬT MASTER GLOBAL & US TRƯỚC 4 KHUNG GIỜ (0h, 8h, 16h, 20h)
Chạy trước 120 phút (2 tiếng):
  - Ca 00:00 -> Chạy lúc 22:00 (hôm trước)
  - Ca 08:00 -> Chạy lúc 06:00
  - Ca 16:00 -> Chạy lúc 14:00
  - Ca 20:00 -> Chạy lúc 18:00

Quy tắc lấp đầy bài (Phải làm mọi cách cho đủ bài):
  1. Kiểm tra kho bài HOAN_THANH chưa xuất Master.
  2. Nếu thiếu bài cho chủ đề nào:
     - Cấp 1: Lấy bài thô/chờ xử lý trong pool (NEW, CHO_XU_LY, WEB_POSTED) -> AI viết -> Cắt ảnh -> Tạo Reel 10s -> Hoàn thành.
     - Cấp 2: Nếu kho thô cũng cạn -> Tự động cào thêm từ fanpage nguồn của chủ đề đó -> Chuyển qua Cấp 1.
  3. Xuất file Master mới cho Global, US 1 và US 2 (nếu có danh bạ).
  4. Đồng bộ file Master ra cả du_lieu_exel/ và Downloads/.
"""
import copy
import json
import os
import shutil
import threading
import time
from datetime import datetime, timedelta

# Import các mô-đun trong hệ thống
import cao_fb
import google_sheets
import luong_b
import reel
import scraper
import vung
import xuat_master

DUONG_DAN = os.path.dirname(os.path.abspath(__file__))
THU_MUC_TRAFFIC = os.path.join(DUONG_DAN, "du_lieu_traffic")
FILE_CAU_HINH = os.path.join(THU_MUC_TRAFFIC, "cau_hinh_tu_dong_master.json")
FILE_TRANG_THAI = os.path.join(THU_MUC_TRAFFIC, "trang_thai_tu_dong_master.json")

KHOA_TU_DONG = threading.Lock()
STOP_EVENT = threading.Event()
DAEMON_THREAD = None
CHU_TRINH_THREAD = None  # thread đang thực thi chu trình cập nhật Master (nếu có)


# ==============================================================================
# 1. ĐỌC / GHI CẤU HÌNH & TRẠNG THÁI
# ==============================================================================

def doc_cau_hinh() -> dict:
    """Đọc cấu hình tự động Master từ file JSON."""
    os.makedirs(THU_MUC_TRAFFIC, exist_ok=True)
    mac_dinh = {
        "bat_tu_dong": True,
        "khung_gio_dang": ["00:00", "08:00", "16:00", "20:00"],
        "chay_truoc_phut": 120,
        "cac_master": {
            "global": True,
            "us_1": True,
            "us_2": True
        },
        "tu_dong_bu_bai": True,
        "tu_dong_cao_khi_thieu": True,
        "dong_bo_downloads": True,
    }
    if os.path.exists(FILE_CAU_HINH):
        try:
            with open(FILE_CAU_HINH, "r", encoding="utf-8") as f:
                c = json.load(f)
                mac_dinh.update(c)
        except Exception:
            pass
    return mac_dinh


def luu_cau_hinh(cfg: dict):
    """Lưu cấu hình tự động Master vào file JSON."""
    os.makedirs(THU_MUC_TRAFFIC, exist_ok=True)
    with open(FILE_CAU_HINH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def doc_trang_thai() -> dict:
    """Đọc trạng thái hoạt động của tiến trình tự động Master."""
    os.makedirs(THU_MUC_TRAFFIC, exist_ok=True)
    mac_dinh = {
        "dang_chay": False,
        "ca_hien_tai": "",
        "tien_do": "Chờ kích hoạt",
        "lan_chay_cuoi": "",
        "ca_da_chay_gan_nhat": "",
        "ca_chay_tiep_theo": "",
        "thoi_gian_kich_hoat_tiep_theo": "",
        "phut_con_lai": 0,
        "thong_ke": {},
        "logs": [],
    }
    if os.path.exists(FILE_TRANG_THAI):
        try:
            with open(FILE_TRANG_THAI, "r", encoding="utf-8") as f:
                st = json.load(f)
                mac_dinh.update(st)
        except Exception:
            pass
    # Tự động tính toán ca tiếp theo để hiển thị chính xác
    tiep_theo = tinh_ca_tiep_theo()
    mac_dinh.update(tiep_theo)
    # Kèm trạng thái bật/tắt từ cấu hình để UI hiển thị đúng badge
    mac_dinh["bat_tu_dong"] = doc_cau_hinh().get("bat_tu_dong", True)
    return mac_dinh


def khoi_phuc_trang_thai_ket() -> bool:
    """Reset cờ 'dang_chay' nếu không còn tiến trình chạy THẬT trong process này.

    Xảy ra khi tool bị tắt/khởi động lại giữa chừng 1 chu trình: file trạng thái
    vẫn ghi dang_chay=True -> daemon từ chối chạy ca mới và nút 'Cập nhật Master
    ngay' bị khóa vĩnh viễn. Gọi hàm này mỗi lần webui khởi động / bật tự động.
    """
    st = doc_trang_thai()
    if not st.get("dang_chay"):
        return False
    if CHU_TRINH_THREAD is not None and CHU_TRINH_THREAD.is_alive():
        return False
    cap_nhat_trang_thai(
        dang_chay=False,
        ca_hien_tai="",
        tien_do="Đã khôi phục (lần chạy trước bị gián đoạn giữa chừng)",
        log_moi="♻️ Phát hiện trạng thái 'đang chạy' bị kẹt từ phiên trước -> đã tự khôi phục."
    )
    return True


def cap_nhat_trang_thai(**kwargs):
    """Cập nhật trạng thái an toàn đa luồng."""
    os.makedirs(THU_MUC_TRAFFIC, exist_ok=True)
    with KHOA_TU_DONG:
        st = doc_trang_thai()
        for k, v in kwargs.items():
            if k == "log_moi" and v:
                logs = st.get("logs", [])
                gio = datetime.now().strftime("%H:%M:%S")
                logs.append(f"[{gio}] {v}")
                st["logs"] = logs[-300:]  # Giữ tối đa 300 dòng
            else:
                st[k] = v
        with open(FILE_TRANG_THAI, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)


# ==============================================================================
# 2. TÍNH TOÁN LẬP LỊCH 4 KHUNG GIỜ
# ==============================================================================

def tinh_ca_tiep_theo(now: datetime = None) -> dict:
    """Tính toán ca đăng tiếp theo và thời điểm chạy trước 120 phút."""
    cfg = doc_cau_hinh()
    khung_gio = cfg.get("khung_gio_dang", ["00:00", "08:00", "16:00", "20:00"])
    chay_truoc = int(cfg.get("chay_truoc_phut") or 120)

    if now is None:
        now = datetime.now()

    # Tạo danh sách các mốc kích hoạt ứng với các ca trong hôm nay và ngày mai
    danh_sach_moc = []
    for ngay_offset in [0, 1]:
        ngay_xet = now.date() + timedelta(days=ngay_offset)
        for gio_str in khung_gio:
            h, m = [int(x) for x in gio_str.split(":")]
            dt_dang = datetime(ngay_xet.year, ngay_xet.month, ngay_xet.day, h, m, 0)
            dt_chay = dt_dang - timedelta(minutes=chay_truoc)
            danh_sach_moc.append({
                "ca": gio_str,
                "ngay_dang": dt_dang.strftime("%Y-%m-%d"),
                "dt_dang": dt_dang,
                "dt_chay": dt_chay,
                "id_ca": f"{dt_dang.strftime('%Y-%m-%d')}_{gio_str}"
            })

    # Tìm mốc chạy tiếp theo trong tương lai
    for moc in danh_sach_moc:
        if moc["dt_chay"] > now:
            con_lai_giay = (moc["dt_chay"] - now).total_seconds()
            con_lai_phut = int(con_lai_giay // 60)
            return {
                "ca_chay_tiep_theo": f"{moc['ca']} (ngày {moc['ngay_dang']})",
                "thoi_gian_kich_hoat_tiep_theo": moc["dt_chay"].strftime("%Y-%m-%d %H:%M:%S"),
                "phut_con_lai": con_lai_phut,
                "id_ca_tiep_theo": moc["id_ca"],
            }

    # Dự phòng
    return {
        "ca_chay_tiep_theo": "Không xác định",
        "thoi_gian_kich_hoat_tiep_theo": "",
        "phut_con_lai": 0,
        "id_ca_tiep_theo": "",
    }


# ==============================================================================
# 3. QUY TRÌNH BÙ BÀI TỰ ĐỘNG (LÀM MỌI CÁCH CHO ĐỦ BÀI)
# ==============================================================================

def _nap_bai_cao_vao_pool(bai_moi_cao: list, store, vung_target: str,
                          chu_de_can: str, goi_y_nguon: list = None) -> list:
    """Nạp các bài vừa cào vào CONTENT POOL: lọc bài không chữ, chống trùng kho,
    nhận diện nhân vật rồi ghi status=NEW (giống luồng nạp của Web UI).
    Trả về danh sách Content ID của các bài nạp được."""
    from content_pool import chong_trung, them_content, chuan_hoa_text
    from nhan_dien import nhan_dien_nhan_vat

    phien = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " [AUTO-MASTER]"
    import cao_fb
    bai_co_chu = [b for b in bai_moi_cao
                  if cao_fb.la_caption_hop_le(b.get("text") or "")]
    bai_moi = chong_trung(bai_co_chu, store, phien=phien, vung=vung_target)

    cids = []
    for b in bai_moi:
        txt = (b.get("text") or "").strip()
        if not b.get("post_id"):
            # Không có post_id (hiếm) -> tự sinh ID ổn định từ nội dung + link
            import hashlib
            b["post_id"] = "bai_" + hashlib.md5(
                (txt[:200] + str(b.get("post_url") or "")).encode("utf-8")
            ).hexdigest()[:12]
        try:
            nv = nhan_dien_nhan_vat(txt, chu_de_can, goi_y_nguon or [])
        except Exception:
            nv = "Chung"
        dong = them_content(b, chu_de_can, nv,
                            b.get("_source_url") or chu_de_can,
                            store, phien=phien, vung=vung_target)
        cid = dong.get("Content ID")
        if cid:
            cids.append(cid)
    return cids


def bu_bai_cho_chu_de(vung_target: str, chu_de_can: str, so_luong_can: int,
                      callback_log=None) -> int:
    """Tự động sản xuất đủ số lượng bài hoàn thành cho 1 chủ đề cụ thể:
    - Bước 1: Quét pool tìm bài WEB_POSTED / SAN_SANG -> Cắt ảnh + Reel -> HOAN_THANH.
    - Bước 2: Quét pool tìm bài NEW / CHO_XU_LY có media -> Gọi AI viết bài -> Cắt ảnh + Reel -> HOAN_THANH.
    - Bước 3: Nếu vẫn thiếu -> Cào bài mới từ fanpage nguồn của chủ đề -> Chạy qua AI & hoàn thành.
    Trả về số bài đã sản xuất thành công.
    """
    vung_target = vung.chuan_vung(vung_target)
    store = google_sheets.lay_store()
    pool = store.lay_tat_ca("CONTENT POOL")
    so_da_bu = 0

    def log(msg):
        if callback_log:
            callback_log(msg)
        cap_nhat_trang_thai(log_moi=msg)

    log(f"🛠️ [BÙ BÀI] [{vung.ten_vung(vung_target)}] Chủ đề '{chu_de_can}': Đang thiếu {so_luong_can} bài -> Bắt đầu quy trình làm bài...")

    # --------------------------------------------------------------------------
    # BƯỚC 1: Xử lý bài đã có bài báo (WEB_POSTED / SAN_SANG) chưa cắt ảnh / reel
    # --------------------------------------------------------------------------
    for r in pool:
        if STOP_EVENT.is_set():
            log("⏹️ Nhận lệnh DỪNG từ người dùng -> kết thúc bù bài sớm.")
            return so_da_bu
        if so_da_bu >= so_luong_can:
            break
        if str(r.get("Da_xuat_MASTER") or "").strip():
            continue
        v_bai = vung.vung_cua_bai(r)
        if v_bai != vung_target:
            continue
        k_bai = xuat_master.chuan_hoa_chu_de(r.get("KEY") or r.get("Chủ đề") or "")
        if k_bai.lower() != chu_de_can.lower() and chu_de_can.lower() not in k_bai.lower():
            continue

        st = str(r.get("Status") or "").upper()
        cid = r.get("Content ID")
        if st in ("WEB_POSTED", "SAN_SANG") and r.get("Article URL"):
            log(f"  ⚡ [{so_da_bu+1}/{so_luong_can}] Hoàn thiện bài sẵn có: {cid} (Đang ở {st})...")
            try:
                res_anh = luong_b.xu_ly_anh_hoan_thanh_mot_bai(cid, format_type="1:1")
                if res_anh.get("success"):
                    anh_p = res_anh.get("data", {}).get("anh_path")
                    if anh_p:
                        reel.tao_reel(anh_p)
                    so_da_bu += 1
                    log(f"  ✅ Đã hoàn thành bài: {cid} (Ảnh + Reel 100%)")
            except Exception as e_b1:
                log(f"  ⚠️ Lỗi hoàn thiện bài {cid}: {e_b1}")

    if so_da_bu >= so_luong_can:
        log(f"🎉 [HOÀN TẤT BÙ BÀI] Đã bù đủ {so_da_bu}/{so_luong_can} bài cho '{chu_de_can}' qua kho sẵn có.")
        return so_da_bu

    # --------------------------------------------------------------------------
    # BƯỚC 2: AI viết bài mới từ bài thô trong kho (NEW / CHO_XU_LY)
    # --------------------------------------------------------------------------
    pool = store.lay_tat_ca("CONTENT POOL")  # Làm mới pool
    for r in pool:
        if STOP_EVENT.is_set():
            log("⏹️ Nhận lệnh DỪNG từ người dùng -> kết thúc bù bài sớm.")
            return so_da_bu
        if so_da_bu >= so_luong_can:
            break
        if str(r.get("Da_xuat_MASTER") or "").strip():
            continue
        v_bai = vung.vung_cua_bai(r)
        if v_bai != vung_target:
            continue
        k_bai = xuat_master.chuan_hoa_chu_de(r.get("KEY") or r.get("Chủ đề") or "")
        if k_bai.lower() != chu_de_can.lower() and chu_de_can.lower() not in k_bai.lower():
            continue

        st = str(r.get("Status") or "").upper()
        cid = r.get("Content ID")
        if st in ("NEW", "CHO_XU_LY") and r.get("Media"):
            log(f"  🤖 [{so_da_bu+1}/{so_luong_can}] AI bắt đầu viết bài thô: {cid}...")
            try:
                res_ai = luong_b.xu_ly_ai_mot_bai(cid, web=vung_target)
                if res_ai.get("success"):
                    res_anh = luong_b.xu_ly_anh_hoan_thanh_mot_bai(cid, format_type="1:1")
                    anh_p = res_anh.get("data", {}).get("anh_path")
                    if anh_p:
                        reel.tao_reel(anh_p)
                    so_da_bu += 1
                    log(f"  ✅ AI viết & hoàn thành thành công: {cid}")
                else:
                    log(f"  ⚠️ AI viết bài {cid} thất bại: {res_ai.get('message')}")
            except Exception as e_b2:
                log(f"  ⚠️ Lỗi xử lý AI bài {cid}: {e_b2}")

    if so_da_bu >= so_luong_can:
        log(f"🎉 [HOÀN TẤT BÙ BÀI] Đã bù đủ {so_da_bu}/{so_luong_can} bài cho '{chu_de_can}'.")
        return so_da_bu

    # --------------------------------------------------------------------------
    # BƯỚC 3: CÀO BÀI MỚI TỪ NGUỒN FANPAGE NẾU VẪN CÒN THIẾU
    # --------------------------------------------------------------------------
    con_thieu = so_luong_can - so_da_bu
    log(f"🌐 [CÀO THÊM NGUỒN] Kho thô không đủ, vẫn thiếu {con_thieu} bài cho '{chu_de_can}' -> Bắt đầu cào từ Fanpage...")

    if not doc_cau_hinh().get("tu_dong_cao_khi_thieu", True):
        log(f"⏸️ Cấu hình đang TẮT 'tự động cào khi thiếu' -> '{chu_de_can}' còn thiếu {con_thieu} bài, bỏ qua bước cào.")
        return so_da_bu

    cac_nguon = vung.doc_kho_nguon(vung_target)
    nguon_phu_hop = []
    goi_y_nguon = []
    for s in cac_nguon:
        key_nguon = (s.get("KEY") or "").strip().lower()
        url = s.get("Facebook nguồn")
        if key_nguon and url and str(url).startswith("http") and (
                chu_de_can.lower() in key_nguon or key_nguon in chu_de_can.lower()):
            nguon_phu_hop.append(url)
            goi_y_nguon += [g.strip() for g in str(s.get("Nhân vật gợi ý") or "").split(",") if g.strip()]

    if not nguon_phu_hop:
        log(f"⚠️ Không tìm thấy link Fanpage nguồn nào cho chủ đề '{chu_de_can}' trong kho nguồn {vung_target}.")
        return so_da_bu

    try:
        log(f"  📡 Đang cào bài từ {min(len(nguon_phu_hop), 3)} trang nguồn cho '{chu_de_can}'...")
        ket_qua_cao, _ = scraper.run_cào(
            nguon_phu_hop[:3],
            pages=2,
            per_page=max(3, con_thieu + 2),
            output="du_lieu",
            no_images=False,
            bo_qua_bai_cu=True,
            stop_flag=STOP_EVENT
        )
        # Nạp bài mới vào Content Pool
        bai_moi_cao = []
        for p_url, posts in ket_qua_cao.items():
            for p in posts:
                p["_source_url"] = p_url
                bai_moi_cao.append(p)

        if bai_moi_cao:
            log(f"  📥 Cào được {len(bai_moi_cao)} bài mới. Đang nạp vào Content Pool...")
            cids_nap = _nap_bai_cao_vao_pool(bai_moi_cao, store, vung_target,
                                             chu_de_can, goi_y_nguon)
            log(f"  Đã nạp {len(cids_nap)} bài vào pool. Tiến hành cho AI viết ngay...")

            for cid in cids_nap:
                if STOP_EVENT.is_set():
                    log("⏹️ Nhận lệnh DỪNG từ người dùng -> kết thúc bù bài sớm.")
                    return so_da_bu
                if so_da_bu >= so_luong_can:
                    break
                try:
                    res_ai = luong_b.xu_ly_ai_mot_bai(cid, web=vung_target)
                    if res_ai.get("success"):
                        res_anh = luong_b.xu_ly_anh_hoan_thanh_mot_bai(cid, format_type="1:1")
                        anh_p = res_anh.get("data", {}).get("anh_path")
                        if anh_p:
                            reel.tao_reel(anh_p)
                        so_da_bu += 1
                        log(f"  ✅ Đã viết & hoàn thành bài mới cào: {cid}")
                except Exception as e_new:
                    log(f"  ⚠️ Lỗi xử lý bài mới cào {cid}: {e_new}")
        else:
            log(f"  ℹ️ Không cào được bài mới nào từ các trang nguồn.")
    except Exception as e_cao:
        log(f"  ❌ Lỗi khi cào bài mới: {e_cao}")

    log(f"🏁 [KẾT QUẢ BÙ BÀI] Chủ đề '{chu_de_can}': Đã hoàn thành bù {so_da_bu}/{so_luong_can} bài.")
    return so_da_bu


# ==============================================================================
# 4. QUY TRÌNH CẬP NHẬT 1 FILE MASTER
# ==============================================================================

def cap_nhat_mot_master(vung_target: str, loai_master: int = 1,
                        callback_log=None) -> dict:
    """Kiểm tra kho bài -> Tự động bù bài cho đủ -> Xuất Master -> Tạo Reel -> Đồng bộ Downloads."""
    v = vung.chuan_vung(vung_target)
    ten_v = vung.ten_vung(v)
    store = google_sheets.lay_store()

    def log(msg):
        if callback_log:
            callback_log(msg)
        cap_nhat_trang_thai(log_moi=msg)

    log(f"============================================================")
    log(f"🚀 BẮT ĐẦU CẬP NHẬT MASTER: {ten_v.upper()} (Master {loai_master})")
    log(f"============================================================")

    # 1. Đọc danh bạ
    try:
        danh_ba = xuat_master.doc_danh_ba(vung=v, loai_master=loai_master)
    except FileNotFoundError as e_db:
        log(f"ℹ️ Bỏ qua {ten_v} Master {loai_master}: {e_db}")
        return {"ok": False, "ly_do": "Khong_co_danh_ba", "vung": v, "loai_master": loai_master}
    except Exception as e_db:
        log(f"⚠️ Lỗi đọc danh bạ {ten_v} Master {loai_master}: {e_db}")
        return {"ok": False, "ly_do": str(e_db), "vung": v, "loai_master": loai_master}

    if not danh_ba:
        log(f"⚠️ Danh bạ {ten_v} Master {loai_master} không có profile nào.")
        return {"ok": False, "ly_do": "Danh_ba_rong", "vung": v, "loai_master": loai_master}

    # 2. Phân tích số bài cần theo từng chủ đề
    kho = xuat_master.lay_kho_cho(store, vung=v, loai_master=loai_master)
    kho_sim = copy.deepcopy(kho)

    cho_bai_list = []
    for p in danh_ba:
        if xuat_master.du_chien(p.get("Trang thai")):
            bai = xuat_master._lay_bai_phu_hop(kho_sim, p.get("Chu de"))
            if not bai:
                cho_bai_list.append((p.get("PROFILE"), p.get("Chu de")))

    # 3. Nếu thiếu bài -> Gọi tự động bù bài cho từng chủ đề thiếu
    if cho_bai_list:
        from collections import Counter
        cnt_thieu = Counter(cd for prof, cd in cho_bai_list)
        log(f"⚠️ Phát hiện {len(cho_bai_list)} profile chưa có bài trong kho:")
        for cd, sl in cnt_thieu.items():
            log(f"  • Chủ đề '{cd}': thiếu {sl} bài")

        # Tự động bù bài cho từng chủ đề thiếu
        cfg = doc_cau_hinh()
        if cfg.get("tu_dong_bu_bai", True):
            for cd, sl in cnt_thieu.items():
                bu_bai_cho_chu_de(v, cd, sl, callback_log=callback_log)
    else:
        log(f"✅ Kho hoàn thành hiện tại đã ĐỦ 100% bài cho tất cả {len(danh_ba)} profile!")

    # 4. Xuất Master mới
    log(f"📑 Đang xuất file Master mới cho {ten_v} (Master {loai_master})...")
    try:
        res_xuat = xuat_master.xuat_master(store=store, ghi_dau=True, vung=v, loai_master=loai_master)
    except PermissionError as e_pe:
        log(f"❌ {e_pe}")
        return {"ok": False, "ly_do": "File_dang_mo_excel", "vung": v, "loai_master": loai_master}
    except Exception as e_x:
        log(f"❌ Lỗi xuất file Master {loai_master}: {e_x}")
        return {"ok": False, "ly_do": str(e_x), "vung": v, "loai_master": loai_master}
    file_master = res_xuat.get("file")
    log(f"  Đã ghi Master: {file_master} ({res_xuat.get('so_bai_xuat')}/{res_xuat.get('tong_dong')} dòng có bài)")

    # 5. Bổ sung Reel 100% cho mọi dòng có bài
    log(f"🎬 Kiểm tra và bổ sung Reel 10s cho các dòng có bài...")
    wb_m = xuat_master._doc_master(file_master)
    so_reel_them = xuat_master.bo_sung_dong_co_bai(wb_m, store=store, vung=v)
    xuat_master._ghi_master(file_master, wb_m)
    log(f"  Đã hoàn tất Reel: +{so_reel_them} reel mới được gắn.")

    # 6. Đồng bộ sang thư mục Downloads
    cfg = doc_cau_hinh()
    if cfg.get("dong_bo_downloads", True) and os.path.exists(file_master):
        user_dl = os.path.expanduser(r"~\Downloads")
        if os.path.exists(user_dl):
            ten_file = os.path.basename(file_master)
            dst_dl = os.path.join(user_dl, ten_file)
            try:
                shutil.copy2(file_master, dst_dl)
                log(f"📂 Đã đồng bộ file Master ra Downloads: {dst_dl}")
            except Exception as e_cp:
                log(f"⚠️ Không thể copy ra Downloads: {e_cp}")

    # 7. Cập nhật cache bài nổ
    try:
        import kiem_tra_bai_no
        kiem_tra_bai_no.nap_master_cache(force=True)
        log(f"🔄 Đã làm mới cache giám sát bài nổ theo Master mới.")
    except Exception:
        pass

    log(f"✨ HOÀN THÀNH CẬP NHẬT MASTER {ten_v.upper()} (Master {loai_master}): {res_xuat.get('so_bai_xuat')}/{res_xuat.get('tong_dong')} profile có bài!")
    return {
        "ok": True,
        "vung": v,
        "loai_master": loai_master,
        "file": file_master,
        "tong_dong": res_xuat.get("tong_dong"),
        "so_bai_xuat": res_xuat.get("so_bai_xuat"),
        "so_reel_them": so_reel_them,
    }


# ==============================================================================
# 5. CHU TRÌNH CHẠY TOÀN BỘ CÁC MASTER TRONG 1 LẦN
# ==============================================================================

def chay_chu_trinh_master(id_ca: str = None) -> dict:
    """Thực thi đầy đủ quy trình cập nhật tất cả Master: Global, US 1 và US 2."""
    global CHU_TRINH_THREAD
    CHU_TRINH_THREAD = threading.current_thread()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    id_ca = id_ca or f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    cap_nhat_trang_thai(
        dang_chay=True,
        ca_hien_tai=id_ca,
        tien_do="Bắt đầu chu trình cập nhật tất cả file Master...",
        log_moi=f"🔔 [KÍCH HOẠT CHU TRÌNH MASTER] Ca: {id_ca} lúc {now_str}"
    )

    ket_qua = {}
    cfg = doc_cau_hinh()
    cac_master = cfg.get("cac_master", {"global": True, "us_1": True, "us_2": True})

    # Danh sách các file Master cần cập nhật theo cấu hình
    ke_hoach = []
    if cac_master.get("global", True):
        ke_hoach.append(("global", "global", 1, "Đang cập nhật MASTER GLOBAL..."))
    if cac_master.get("us_1", True):
        ke_hoach.append(("us_1", "us", 1, "Đang cập nhật MASTER US 1..."))
    if cac_master.get("us_2", True):
        ke_hoach.append(("us_2", "us", 2, "Đang cập nhật MASTER US 2..."))

    bi_dung_giua_chung = False
    try:
        for khoa, v_target, loai, td in ke_hoach:
            if STOP_EVENT.is_set():
                bi_dung_giua_chung = True
                cap_nhat_trang_thai(
                    tien_do="Đã dừng theo lệnh người dùng",
                    log_moi="⏹️ Nhận lệnh DỪNG từ người dùng -> kết thúc chu trình Master sớm."
                )
                break
            cap_nhat_trang_thai(tien_do=td)
            ket_qua[khoa] = cap_nhat_mot_master(v_target, loai_master=loai)

        if bi_dung_giua_chung:
            return {"success": False, "error": "stopped_by_user", "ket_qua": ket_qua}

        thoi_gian_xong = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_thanh_cong = "🏆 [HOÀN TẤT CHU TRÌNH MASTER] Toàn bộ file Master đã được cập nhật chuẩn bị cho ca đăng!"

        cap_nhat_trang_thai(
            tien_do=f"Đã cập nhật xong lúc {thoi_gian_xong}",
            log_moi=log_thanh_cong
        )
        return {"success": True, "ket_qua": ket_qua}

    except Exception as e_all:
        err_msg = f"❌ Lỗi chu trình cập nhật Master: {e_all}"
        cap_nhat_trang_thai(
            tien_do=f"Lỗi: {e_all}",
            log_moi=err_msg
        )
        return {"success": False, "error": str(e_all)}

    finally:
        # Luôn giải phóng cờ dang_chay dù thành công / lỗi / bị dừng giữa chừng
        CHU_TRINH_THREAD = None
        cap_nhat_trang_thai(
            dang_chay=False,
            ca_hien_tai="",
            lan_chay_cuoi=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ca_da_chay_gan_nhat=id_ca,
            thong_ke=ket_qua,
        )


# ==============================================================================
# 6. VÒNG LẶP DAEMON TỰ ĐỘNG 24/24 THEO LỊCH 4 KHUNG GIỜ
# ==============================================================================

def _vong_lap_daemon_master():
    """Chạy ngầm kiểm tra liên tục mỗi 15 giây. Khi đến giờ chạy trước X phút
    của các ca đăng -> tự động chạy. Mọi lỗi được bắt lại để daemon không bao
    giờ chết âm thầm."""
    while not STOP_EVENT.is_set():
        try:
            cfg = doc_cau_hinh()
            if not cfg.get("bat_tu_dong", True):
                STOP_EVENT.wait(15)
                continue

            now = datetime.now()
            khung_gio = cfg.get("khung_gio_dang", ["00:00", "08:00", "16:00", "20:00"])
            chay_truoc = int(cfg.get("chay_truoc_phut") or 120)

            st = doc_trang_thai()
            ca_da_chay = st.get("ca_da_chay_gan_nhat") or ""

            # Kiểm tra từng ca hôm nay và ngày mai
            for ngay_offset in [0, 1]:
                ngay_xet = now.date() + timedelta(days=ngay_offset)
                for gio_str in khung_gio:
                    h, m = [int(x) for x in gio_str.split(":")]
                    dt_dang = datetime(ngay_xet.year, ngay_xet.month, ngay_xet.day, h, m, 0)
                    dt_chay = dt_dang - timedelta(minutes=chay_truoc)
                    id_ca = f"{dt_dang.strftime('%Y-%m-%d')}_{gio_str}"

                    # Nếu thời điểm hiện tại nằm trong khoảng [dt_chay, dt_chay + 10 phút] và ca này chưa chạy:
                    do_lech_giay = (now - dt_chay).total_seconds()
                    if 0 <= do_lech_giay <= 600 and ca_da_chay != id_ca and not st.get("dang_chay"):
                        cap_nhat_trang_thai(
                            log_moi=f"⏰ [ĐÚNG GIỜ HẸN] Đã tới thời điểm cập nhật trước {chay_truoc} phút cho ca {gio_str} (ngày {dt_dang.strftime('%Y-%m-%d')}) -> Tự động kích hoạt!"
                        )
                        chay_chu_trinh_master(id_ca=id_ca)
                        break
        except Exception as e_loop:
            try:
                cap_nhat_trang_thai(log_moi=f"⚠️ Lỗi vòng lặp daemon tự động Master: {e_loop}")
            except Exception:
                pass

        STOP_EVENT.wait(15)  # thoát NGAY khi người dùng bấm Tắt, không chờ hết 15s


def bat_dau_tu_dong() -> tuple[bool, str]:
    """Bắt đầu tiến trình daemon tự động Master 24/24."""
    global DAEMON_THREAD
    cfg = doc_cau_hinh()
    da_bat_truoc = cfg.get("bat_tu_dong", True)
    cfg["bat_tu_dong"] = True
    luu_cau_hinh(cfg)
    STOP_EVENT.clear()

    # Tự khôi phục nếu trạng thái 'đang chạy' bị kẹt từ phiên trước
    khoi_phuc_trang_thai_ket()

    if DAEMON_THREAD is not None and DAEMON_THREAD.is_alive():
        return True, "Dịch vụ tự động cập nhật Master đang hoạt động."
    DAEMON_THREAD = threading.Thread(target=_vong_lap_daemon_master, daemon=True)
    DAEMON_THREAD.start()
    if not da_bat_truoc:
        cap_nhat_trang_thai(log_moi="🟢 Đã khởi động dịch vụ tự động cập nhật Master 24/24.")
    return True, "Đã bật tự động cập nhật Master theo các khung giờ đã cài!"


def dung_tu_dong() -> tuple[bool, str]:
    """Tạm dừng tiến trình daemon tự động Master (dừng mềm: chu trình đang
    chạy sẽ kết thúc sớm ở điểm kiểm tra gần nhất, không giết thread giữa chừng)."""
    global DAEMON_THREAD
    cfg = doc_cau_hinh()
    da_bat_truoc = cfg.get("bat_tu_dong", True)
    cfg["bat_tu_dong"] = False
    luu_cau_hinh(cfg)
    STOP_EVENT.set()
    if DAEMON_THREAD is not None and DAEMON_THREAD.is_alive():
        DAEMON_THREAD.join(timeout=5)
    DAEMON_THREAD = None
    if da_bat_truoc:
        # Chỉ ghi log khi trạng thái thực sự chuyển BẬT -> TẮT (chống log trùng)
        cap_nhat_trang_thai(log_moi="🔴 Đã tắt dịch vụ tự động cập nhật Master.")
    return True, "Đã tắt tự động cập nhật Master."


def chay_ngay_thu_cong() -> tuple[bool, str]:
    """Kích hoạt chạy cập nhật Master ngay lập tức trong thread riêng."""
    # Tự khôi phục nếu cờ 'đang chạy' bị kẹt từ phiên trước (tool tắt giữa chừng)
    khoi_phuc_trang_thai_ket()
    st = doc_trang_thai()
    if st.get("dang_chay"):
        return False, "Tiến trình cập nhật Master đang chạy, vui lòng đợi hoàn thành."

    # Chạy thủ công lúc dịch vụ đang TẮT: STOP_EVENT đang set -> phải clear
    # (daemon đã dừng hẳn nên không ảnh hưởng lịch tự động).
    if STOP_EVENT.is_set() and (DAEMON_THREAD is None or not DAEMON_THREAD.is_alive()):
        STOP_EVENT.clear()

    def _chay():
        chay_chu_trinh_master(id_ca=f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

    t = threading.Thread(target=_chay, daemon=True)
    t.start()
    return True, "Đã kích hoạt cập nhật tất cả file Master thành công!"
