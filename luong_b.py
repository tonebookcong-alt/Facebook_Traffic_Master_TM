# -*- coding: utf-8 -*-
"""
LUỒNG B — XỬ LÝ NỘI DUNG VÀ XUẤT BẢN CHO WEB UI & ANTIDETECT BROWSER.
- Đọc / Lọc / Tìm kiếm kho bài viết Content Pool
- Xử lý AI đơn lẻ và Xử lý AI hàng loạt (viết Caption + Bài báo + Cắt ảnh bằng model cấu hình trong config.json)
- Lưu chỉnh sửa trực tiếp từ Web UI
- Đóng gói xuất dữ liệu sẵn sàng cho Antidetect Browser
"""

import json
import os
import threading
import time
from datetime import datetime

from config import DUONG_DAN, load_config
from google_sheets import lay_store
from content_pool import chon_content, doi_status, _goc_thoi_gian
from viet_lai import viet_3_caption, viet_bai_bao, viet_bai_bao_va_title
from media import chuan_bi_media, tao_thu_muc_ngay_gio
from dang_web import dang_bai_web
from reel import duong_dan_reel
from gan_chu_de import gan_chu_de_cho_bai, gan_chu_de_cho_bai_khong_ai
from vung import TEN_NGAN, dung_vung, lay_vung, ten_vung, vung_cua_bai


def ten_mo_hinh() -> str:
    """Tên model AI đang cấu hình (để log/message hiển thị đúng, không hardcode)."""
    try:
        cfg = load_config() or {}
        m = (cfg.get("ai") or {}).get("model")
        return m or "AI"
    except Exception:
        return "AI"


def lay_danh_sach_pool(trang_thai=None, key=None, nhan_vat=None, tim_kiem=None,
                       sort_by="default", phien=None, chi_chua_xu_ly=False,
                       nhieu_trang_thai=None, vung=None):
    """Lấy danh sách bài viết từ Content Pool kèm lọc và sắp xếp.

    `phien`            : chỉ lấy bài thuộc phiên cào này (giá trị `Phien_cao`).
    `chi_chua_xu_ly`   : chỉ lấy bài chưa hoàn thành (Status ∈ NEW, PROCESSING).
    `nhieu_trang_thai` : set các trạng thái được phép (VD {"PROCESSING","SAN_SANG"}).
                         Nếu truyền thì ưu tiên hơn `trang_thai`.
    `vung`             : 'us' | 'global' — chỉ lấy bài của vùng này
                         (mặc định = vùng đang chọn trên giao diện).
    """
    store = lay_store()
    danh_sach = store.lay_tat_ca("CONTENT POOL")
    ket_qua = []

    for dong in danh_sach:
        cid = str(dong.get("Content ID") or "").strip()
        if not cid:
            continue
        if not dung_vung(dong, vung):
            continue

        st = str(dong.get("Status") or "NEW").strip()
        k = str(dong.get("KEY") or "").strip()
        nv = str(dong.get("Nhân vật/chủ đề") or "Chung").strip()
        cap = str(dong.get("Caption") or "").strip()

        # Bộ lọc phiên: khớp nếu phiên nằm trong `Cac_phien_gap` (gồm cả các lần trùng);
        # row cũ chưa có nhãn này → dựa vào `Phien_cao` (phiên gốc).
        if phien:
            cac_phien = dong.get("Cac_phien_gap")
            if cac_phien is None:
                if str(dong.get("Phien_cao") or "").strip() != phien:
                    continue
            elif phien not in (cac_phien if isinstance(cac_phien, list) else [str(cac_phien)]):
                continue
        if chi_chua_xu_ly and st not in ("NEW", "PROCESSING"):
            continue
        if nhieu_trang_thai:
            if st not in nhieu_trang_thai:
                continue
        elif trang_thai and trang_thai != "ALL" and st != trang_thai:
            continue
        if key and key != "ALL" and k != key:
            continue
        if nhan_vat and nhan_vat != "ALL" and nv != nhan_vat:
            continue
        if tim_kiem:
            tk = tim_kiem.lower()
            cap_moi = str(dong.get("Caption mới") or "").lower()
            art_url = str(dong.get("Article URL") or "").lower()
            dxm = str(dong.get("Da_xuat_MASTER") or "").lower()
            if (tk not in cap.lower() and tk not in nv.lower() and tk not in cid.lower()
                    and tk not in cap_moi and tk not in art_url and tk not in dxm):
                continue

        # Điểm tương tác
        try:
            cam_xuc = int(dong.get("Cảm xúc") or 0)
            binh_luan = int(dong.get("Bình luận") or 0)
            chia_se = int(dong.get("Chia sẻ") or 0)
            diem = cam_xuc + binh_luan * 2 + chia_se * 3
        except Exception:
            cam_xuc, binh_luan, chia_se, diem = 0, 0, 0, 0

        item = dict(dong)
        item["cam_xuc_num"] = cam_xuc
        item["binh_luan_num"] = binh_luan
        item["chia_se_num"] = chia_se
        item["diem_tuong_tac"] = diem
        ket_qua.append(item)

    # Sắp xếp — mặc định (default / moi) = mới nhất đăng trước (teo "Thời gian đăng")
    if sort_by == "diem":
        ket_qua.sort(key=lambda x: x["diem_tuong_tac"], reverse=True)
    elif sort_by == "like":
        ket_qua.sort(key=lambda x: x["cam_xuc_num"], reverse=True)
    elif sort_by == "cmt":
        ket_qua.sort(key=lambda x: x["binh_luan_num"], reverse=True)
    else:
        # Bài không đọc được thời gian (0) xếp cuối; mới nhất lên đầu.
        def _epoch(x):
            goc = _goc_thoi_gian(x.get("Thời gian đăng"))
            return goc.timestamp() if goc is not None else 0
        ket_qua.sort(key=_epoch, reverse=True)

    return ket_qua


def lay_cac_phien_cao(store=None, vung=None) -> list:
    """Gom bài trong Content Pool theo phiên cào (`Phien_cao`), mới nhất trước.

    Mỗi phiên trả: {phien, trang:[trang đã cào], so_bai, so_chua_xu_ly}.
    `vung`: chỉ liệt kê phiên của bài thuộc vùng đó (mặc định = vùng đang chọn).
    """
    store = store or lay_store()
    phien_map = {}
    for d in store.lay_tat_ca("CONTENT POOL"):
        if not dung_vung(d, vung):
            continue
        # Phiên của bài = Cac_phien_gap (gồm cả lần trùng) nếu có, không thì phiên gốc
        cac_phien = d.get("Cac_phien_gap")
        if cac_phien is None:
            p = str(d.get("Phien_cao") or "").strip()
            ds_phien = [p] if p else []
        else:
            ds_phien = cac_phien if isinstance(cac_phien, list) else [str(cac_phien)]
        if not ds_phien:
            continue
        trang = str(d.get("Source") or "").strip()
        st = str(d.get("Status") or "NEW").strip()
        for p in ds_phien:
            p = str(p).strip()
            if not p:
                continue
            e = phien_map.setdefault(
                p, {"phien": p, "trang": set(), "so_bai": 0, "so_chua_xu_ly": 0})
            if trang:
                e["trang"].add(trang)
            e["so_bai"] += 1
            if st in ("NEW", "PROCESSING"):
                e["so_chua_xu_ly"] += 1

    ds = []
    for p, e in phien_map.items():
        ds.append({"phien": p, "trang": sorted(e["trang"]),
                   "so_bai": e["so_bai"], "so_chua_xu_ly": e["so_chua_xu_ly"]})
    ds.sort(key=lambda x: x["phien"], reverse=True)
    return ds


def lay_cac_phien_chinh_bai(store=None, vung=None) -> list:
    """Gom phiên cào CHỈ gồm các bài cần xử lý ở Tab 3 (Status = PROCESSING hoặc ERROR).

    Dùng cho bộ lọc phiên ở Tab 3 (Chỉnh bài). Mỗi phiên: {phien, so_bai}.
    `vung`: chỉ tính bài của vùng đang chọn.
    """
    store = store or lay_store()
    phien_map = {}
    for d in store.lay_tat_ca("CONTENT POOL"):
        if not dung_vung(d, vung):
            continue
        st = str(d.get("Status") or "NEW").strip()
        if st not in ("PROCESSING", "ERROR"):
            continue
        cac_phien = d.get("Cac_phien_gap")
        if cac_phien is None:
            p = str(d.get("Phien_cao") or "").strip()
            ds_phien = [p] if p else []
        else:
            ds_phien = cac_phien if isinstance(cac_phien, list) else [str(cac_phien)]
        if not ds_phien:
            continue
        for p in ds_phien:
            p = str(p).strip()
            if not p:
                continue
            e = phien_map.setdefault(p, {"phien": p, "so_bai": 0})
            e["so_bai"] += 1

    ds = [{"phien": p, "so_bai": e["so_bai"]} for p, e in phien_map.items()]
    ds.sort(key=lambda x: x["phien"], reverse=True)
    return ds


def lay_chi_tiet_bai(content_id: str):
    """Lấy chi tiết 1 bài viết kèm dữ liệu đã xử lý (nếu có)."""
    store = lay_store()
    tim = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return None
    _, dong = tim

    # Đọc gói bo_bai mới nhất trong du_lieu_fb (nếu có)
    goi_fb = _doc_bo_bai_mot(content_id)

    res = dict(dong)
    res["goi_fb"] = goi_fb
    return res


def _doc_bo_bai_mot(content_id):
    """Đọc file bo_bai_<content_id>.json trong du_lieu_fb/ (nếu còn)."""
    fb_dir = os.path.join(DUONG_DAN, "du_lieu_fb")
    if not os.path.exists(fb_dir):
        return None
    target = f"bo_bai_{content_id}.json"
    tim = []
    for root, _, files in os.walk(fb_dir):
        if target in files:
            tim.append(os.path.join(root, target))
    # bản MỚI NHẤT thắng: sau khi chữa link, bo_bai ở phiên hiện tại mang
    # article_url thật, bản cũ vẫn rỗng.
    for duong_dan in sorted(tim, key=os.path.getmtime, reverse=True):
        try:
            with open(duong_dan, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


def xu_ly_anh_bo_bai(content_id: str, format_type: str = "1:1") -> dict:
    """Dựng lại ẢNH + bo_bai cho bài ĐÃ xử lý nhưng mất file ảnh/bo_bai.

    KHÔNG chạy lại AI (giữ caption/bài báo/link cũ nếu còn) — chỉ tải chỉnh ảnh
    (logo + viền) rồi ghi đè bo_bai_<content_id>.json để CSV không bị trống cột ảnh.
    """
    store = lay_store()
    tim = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return {"success": False, "message": f"Không tìm thấy bài {content_id}"}
    _, dong = tim
    thu_muc = tao_thu_muc_ngay_gio()

    goi_cu = _doc_bo_bai_mot(content_id) or {}
    cap_lua = goi_cu.get("caption_lua_chon") or dong.get("Caption mới") or ""
    cap_v2 = goi_cu.get("caption_version_2") or ""
    cap_v3 = goi_cu.get("caption_version_3") or ""
    bai_bao = goi_cu.get("bai_bao") or dong.get("Bài báo") or ""
    article_url = goi_cu.get("article_url") or dong.get("Article URL") or ""

    try:
        anh_path = chuan_bi_media(dong, format_type=format_type, thu_muc=thu_muc)
    except Exception as e:
        return {"success": False, "message": str(e)}

    goi_fb = {
        "content_id": content_id,
        "key": dong.get("KEY") or "",
        "nhan_vat": dong.get("Nhân vật/chủ đề") or "",
        "thoi_gian_tao": datetime.now().isoformat(),
        "article_url": article_url,
        "anh_path": anh_path,
        "caption_lua_chon": cap_lua,
        "caption_version_1": cap_lua,
        "caption_version_2": cap_v2,
        "caption_version_3": cap_v3,
        "bai_bao": bai_bao,
        "folder": thu_muc,
    }
    file_goi = os.path.join(thu_muc, f"bo_bai_{content_id}.json")
    with open(file_goi, "w", encoding="utf-8") as f:
        json.dump(goi_fb, f, ensure_ascii=False, indent=2)

    file_cap = os.path.join(thu_muc, f"caption_{content_id}.txt")
    with open(file_cap, "w", encoding="utf-8") as f:
        f.write(f"=== LINK BÀI BÁO (COMMENT ĐẦU TIÊN) ===\n{article_url}\n\n")
        f.write(f"=== VERSION 1 (MẶC ĐỊNH) ===\n{cap_lua}\n\n")
        if cap_v2:
            f.write(f"=== VERSION 2 ===\n{cap_v2}\n\n")
        if cap_v3:
            f.write(f"=== VERSION 3 ===\n{cap_v3}\n\n")

    return {"success": True, "data": goi_fb, "anh_path": anh_path, "folder": thu_muc}


def xu_ly_ai_mot_bai(content_id: str, format_type: str = "1:1", callback=None,
                     web: str = None) -> dict:
    """Chạy AI viết lại Caption (1 bản hay nhất) + Bài báo + Xử lý ảnh cho 1 bài viết.

    `web` = 'us' | 'global' — BẮT BUỘC: quyết định đăng bài báo lên website nào."""
    if not (web or "").strip():
        return {"success": False,
                "message": "Chưa chọn web đăng bài (US hay GLOBAL) — bắt buộc chọn"}
    web = web.strip().lower()
    store = lay_store()
    tim = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return {"success": False, "message": f"Không tìm thấy bài {content_id}"}
    
    chi_so, dong = tim
    # Vùng của bài QUYẾT ĐỊNH web đăng bài: bài global → bắt buộc web global.
    if web not in ("us", "global"):
        return {"success": False,
                "message": f"web='{web}' không hợp lệ — chỉ nhận 'us' hoặc 'global'"}
    v_bai = vung_cua_bai(dong)
    if not web or web != v_bai:
        web = v_bai
    cid = dong.get("Content ID")
    key = dong.get("KEY") or "Chung"
    nhan_vat = dong.get("Nhân vật/chủ đề") or "Chung"
    caption_goc = (dong.get("Caption") or "").strip()
    caption_moi = (dong.get("Caption mới") or "").strip()
    caption_to_dung = caption_goc if caption_goc else caption_moi

    if callback:
        callback({"status": "processing", "step": "lock", "message": f"Bắt đầu xử lý {cid}"})

    doi_status(cid, "PROCESSING", ghi_chu="Đang xử lý AI trên Web UI", store=store)
    thu_muc = tao_thu_muc_ngay_gio()

    try:
        # 1. AI viết lại Caption (1 bản hay nhất)
        if callback:
            callback({"status": "processing", "step": "caption", "message": f"Đang gọi {ten_mo_hinh()} viết lại Caption viral (1 bản hay nhất)..."})
        caps = viet_3_caption(caption_to_dung, vung=web, key=key)
        cap_v1 = caps.get("version_1") or ""
        cap_v2 = caps.get("version_2") or ""
        cap_v3 = caps.get("version_3") or ""

        # 2. AI Viết bài báo (kèm TIÊU ĐỀ thật do AI đặt — không còn công thức
        #    "Exclusive: … — The Untold Story" gây spam trên web)
        if callback:
            callback({"status": "processing", "step": "article", "message": f"Đang gọi {ten_mo_hinh()} viết bài báo 1500-1700 từ..."})
        goi_ai_bb = viet_bai_bao_va_title(caption_to_dung, nhan_vat=nhan_vat, key=key, vung=web)
        bai_bao = goi_ai_bb["bai_bao"]
        tieu_de = goi_ai_bb["tieu_de"]
        # CHẶN bài báo rỗng trước khi đăng web: nếu không có nội dung, bài web
        # sẽ bị "Nội dung cập nhật." và bo_bai lưu rỗng -> báo hỏng.
        if not (bai_bao or "").strip() or len(bai_bao.strip()) < 800:
            raise RuntimeError(f"Bài báo rỗng hoặc quá ngắn ({len((bai_bao or '').strip())} ký) "
                               f"— KHÔNG đăng web, đặt ERROR.")
        if not (tieu_de or "").strip():
            raise RuntimeError("Tiêu đề rỗng — KHÔNG đăng web, đặt ERROR.")

        # 3. Xử lý ảnh
        if callback:
            callback({"status": "processing", "step": "media", "message": "Đang tải và crop ảnh chuẩn tỷ lệ..."})
        anh_path = chuan_bi_media(dong, format_type=format_type, thu_muc=thu_muc)

        # 4. Giả lập đăng Web — dùng TIÊU ĐỀ AI vừa đặt (đã kiểm tra chống khuôn)
        if callback:
            callback({"status": "processing", "step": "web",
                      "message": f"Đang đăng web với tiêu đề: {tieu_de[:70]}"})
        res_web = dang_bai_web(tieu_de=tieu_de, noi_dung=bai_bao, anh_path=anh_path, nhan_vat=nhan_vat, key=key, web=web)
        article_url = res_web.get("article_url") or ""
        if not article_url:
            # CHẶN LỖI im lặng: trước đây bài không có link vẫn được đặt
            # HOAN_THANH -> MASTER thiếu cột 'Link bài báo' -> GPM comment rỗng.
            raise RuntimeError("dang_bai_web không trả về Article URL: "
                               + str(res_web.get("message") or res_web)[:600])

        # Gán chủ đề: ưu tiên KEY khớp, không khớp thì gọi AI
        chu_de = gan_chu_de_cho_bai(key, caption_to_dung or bai_bao)

        # 5. Lưu gói bài đăng
        goi_fb = {
            "content_id": cid,
            "key": key,
            "nhan_vat": nhan_vat,
            "chu_de": chu_de,
            "web": web,
            "thoi_gian_tao": datetime.now().isoformat(),
            "article_url": article_url,
            "tieu_de": tieu_de,
            "anh_path": anh_path,
            "caption_lua_chon": cap_v1,
            "caption_version_1": cap_v1,
            "caption_version_2": cap_v2,
            "caption_version_3": cap_v3,
            "bai_bao": bai_bao,
            "folder": thu_muc,
        }

        file_goi = os.path.join(thu_muc, f"bo_bai_{cid}.json")
        with open(file_goi, "w", encoding="utf-8") as f:
            json.dump(goi_fb, f, ensure_ascii=False, indent=2)

        file_cap = os.path.join(thu_muc, f"caption_{cid}.txt")
        with open(file_cap, "w", encoding="utf-8") as f:
            f.write(f"=== LINK BÀI BÁO (COMMENT ĐẦU TIÊN) ===\n{article_url}\n\n")
            f.write(f"=== VERSION 1 (MẶC ĐỊNH) ===\n{cap_v1}\n\n")
            f.write(f"=== VERSION 2 ===\n{cap_v2}\n\n")
            f.write(f"=== VERSION 3 ===\n{cap_v3}\n\n")

        # 6. Cập nhật Content Pool chuẩn xác theo chi_so
        tim_lai = store.tim_dong("CONTENT POOL", "Content ID", cid)
        if tim_lai:
            idx, row = tim_lai
            row["Caption mới"] = cap_v1
            row["Bài báo"] = bai_bao[:500] + "... [xem chi tiết trong thư mục]"
            row["Article URL"] = article_url
            row["Chủ đề"] = chu_de
            row["Web"] = web
            row["Status"] = "WEB_POSTED"
            row["Ghi chú"] = f"Đã sẵn sàng tại {os.path.basename(thu_muc)}"
            store.cap_nhat_dong("CONTENT POOL", idx, row)

        if callback:
            callback({"status": "done", "step": "done", "message": f"Hoàn thành xuất sắc bài {cid}!"})

        return {"success": True, "data": goi_fb, "folder": thu_muc}

    except Exception as e:
        # Lưu dữ liệu đã sinh (caption, bài báo, URL) vào pool trước khi báo lỗi
        try:
            tim_lai = store.tim_dong("CONTENT POOL", "Content ID", cid)
            if tim_lai and (cap_v1 or bai_bao or article_url):
                idx, row = tim_lai
                if cap_v1:
                    row["Caption mới"] = cap_v1
                if bai_bao:
                    row["Bài báo"] = bai_bao[:500] + "... [xem chi tiết trong thư mục]"
                if article_url:
                    row["Article URL"] = article_url
                store.cap_nhat_dong("CONTENT POOL", idx, row)
        except Exception:
            pass
        doi_status(cid, "ERROR", ghi_chu=f"Lỗi AI: {str(e)[:100]}", store=store)
        if callback:
            callback({"status": "error", "step": "error", "message": f"Lỗi bài {cid}: {e}"})
        return {"success": False, "message": str(e)}


def xuat_noi_dung_ai_bai(content_id: str, format_type: str = "1:1", callback=None,
                         web: str = None) -> dict:
    """Tách bước AI (Tab 3): chỉ viết lại Caption (1 bản) + Bài báo + link bài báo web.

    `web` = 'us' | 'global' — BẮT BUỘC: quyết định đăng bài báo lên website nào.

    KHÔNG cắt ảnh (`chuan_bi_media`) và KHÔNG đặt Status = WEB_POSTED — bài vẫn ở
    PROCESSING, chờ user bấm "Hoàn thành" (→ SAN_SANG) rồi cắt ảnh ở Tab 4 (→ HOAN_THANH).
    """
    if not (web or "").strip():
        return {"success": False,
                "message": "Chưa chọn web đăng bài (US hay GLOBAL) — bắt buộc chọn"}
    web = web.strip().lower()
    store = lay_store()
    tim = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return {"success": False, "message": f"Không tìm thấy bài {content_id}"}

    chi_so, dong = tim
    # Vùng của bài QUYẾT ĐỊNH web đăng bài: bài global → bắt buộc web global.
    if web not in ("us", "global"):
        return {"success": False,
                "message": f"web='{web}' không hợp lệ — chỉ nhận 'us' hoặc 'global'"}
    v_bai = vung_cua_bai(dong)
    if not web or web != v_bai:
        web = v_bai
    cid = dong.get("Content ID")
    key = dong.get("KEY") or "Chung"
    nhan_vat = dong.get("Nhân vật/chủ đề") or "Chung"
    caption_goc = (dong.get("Caption") or "").strip()
    caption_moi = (dong.get("Caption mới") or "").strip()
    caption_to_dung = caption_goc if caption_goc else caption_moi

    if callback:
        callback({"status": "processing", "step": "lock", "message": f"Bắt đầu xử lý {cid}"})

    doi_status(cid, "PROCESSING", ghi_chu="Đang sinh nội dung trên Web UI", store=store)
    thu_muc = tao_thu_muc_ngay_gio()

    # Khởi tạo biến để có thể lưu nếu có lỗi
    cap_v1 = cap_v2 = cap_v3 = ""
    bai_bao = tieu_de = article_url = chu_de = ""

    try:
        if callback:
            callback({"status": "processing", "step": "caption", "message": f"Đang gọi {ten_mo_hinh()} viết lại Caption viral (1 bản hay nhất)..."})
        caps = viet_3_caption(caption_to_dung, vung=web, key=key)
        cap_v1 = caps.get("version_1") or ""
        cap_v2 = caps.get("version_2") or ""
        cap_v3 = caps.get("version_3") or ""

        if callback:
            callback({"status": "processing", "step": "article", "message": f"Đang gọi {ten_mo_hinh()} viết bài báo 1500-1700 từ..."})
        goi_ai_bb = viet_bai_bao_va_title(caption_to_dung, nhan_vat=nhan_vat, key=key, vung=web)
        bai_bao = goi_ai_bb["bai_bao"]
        tieu_de = goi_ai_bb["tieu_de"]
        # CHẶN bài báo rỗng trước khi đăng web: nếu không có nội dung, bài web
        # sẽ bị "Nội dung cập nhật." và bo_bai lưu rỗng -> báo hỏng.
        if not (bai_bao or "").strip() or len(bai_bao.strip()) < 800:
            raise RuntimeError(f"Bài báo rỗng hoặc quá ngắn ({len((bai_bao or '').strip())} ký) "
                               f"— KHÔNG đăng web, đặt ERROR.")
        if not (tieu_de or "").strip():
            raise RuntimeError("Tiêu đề rỗng — KHÔNG đăng web, đặt ERROR.")

        if callback:
            callback({"status": "processing", "step": "web",
                      "message": f"Đang đăng web với tiêu đề: {tieu_de[:70]}"})
        # Lấy ảnh ĐẦU TIÊN (Media có thể là chuỗi nhiều ảnh cách nhau "; ") — ảnh làm thumbnail bài báo
        anh_goc = str(dong.get("Media") or "").strip().split(";")[0].strip()[:300]
        res_web = dang_bai_web(tieu_de=tieu_de, noi_dung=bai_bao, anh_path=anh_goc, nhan_vat=nhan_vat, key=key, web=web)
        article_url = res_web.get("article_url") or ""
        if not article_url:
            raise RuntimeError("dang_bai_web không trả về Article URL: "
                               + str(res_web.get("message") or res_web)[:600])

        # Gán chủ đề: ưu tiên KEY khớp, không khớp thì gọi AI
        chu_de = gan_chu_de_cho_bai(key, caption_to_dung or bai_bao)

        goi_fb = {
            "content_id": cid,
            "key": key,
            "nhan_vat": nhan_vat,
            "chu_de": chu_de,
            "web": web,
            "thoi_gian_tao": datetime.now().isoformat(),
            "article_url": article_url,
            "tieu_de": tieu_de,
            "anh_path": "",
            "caption_lua_chon": cap_v1,
            "caption_version_1": cap_v1,
            "caption_version_2": cap_v2,
            "caption_version_3": cap_v3,
            "bai_bao": bai_bao,
            "folder": thu_muc,
        }

        file_goi = os.path.join(thu_muc, f"bo_bai_{cid}.json")
        with open(file_goi, "w", encoding="utf-8") as f:
            json.dump(goi_fb, f, ensure_ascii=False, indent=2)

        file_cap = os.path.join(thu_muc, f"caption_{cid}.txt")
        with open(file_cap, "w", encoding="utf-8") as f:
            f.write(f"=== LINK BÀI BÁO (COMMENT ĐẦU TIÊN) ===\n{article_url}\n\n")
            f.write(f"=== VERSION 1 (MẶC ĐỊNH) ===\n{cap_v1}\n\n")
            f.write(f"=== VERSION 2 ===\n{cap_v2}\n\n")
            f.write(f"=== VERSION 3 ===\n{cap_v3}\n\n")

        tim_lai = store.tim_dong("CONTENT POOL", "Content ID", cid)
        if tim_lai:
            idx, row = tim_lai
            row["Caption mới"] = cap_v1
            row["Bài báo"] = bai_bao[:500] + "... [xem chi tiết trong thư mục]"
            row["Article URL"] = article_url
            row["Chủ đề"] = chu_de
            row["Web"] = web
            row["Status"] = "WEB_POSTED"
            row["Ghi chú"] = f"Đã sinh nội dung AI & đăng web ({tieu_de[:50]})"
            store.cap_nhat_dong("CONTENT POOL", idx, row)

        if callback:
            callback({"status": "done", "step": "done", "message": f"Đã sinh nội dung bài {cid}! Bấm Hoàn thành để chuyển sang bước cắt ảnh."})

        return {"success": True, "data": goi_fb, "folder": thu_muc}

    except Exception as e:
        # Lưu dữ liệu đã sinh (caption, bài báo, URL) vào pool trước khi báo lỗi
        try:
            tim_lai = store.tim_dong("CONTENT POOL", "Content ID", cid)
            if tim_lai and (cap_v1 or bai_bao or article_url):
                idx, row = tim_lai
                if cap_v1:
                    row["Caption mới"] = cap_v1
                if bai_bao:
                    row["Bài báo"] = bai_bao[:500] + "... [xem chi tiết trong thư mục]"
                if article_url:
                    row["Article URL"] = article_url
                store.cap_nhat_dong("CONTENT POOL", idx, row)
        except Exception:
            pass
        doi_status(cid, "ERROR", ghi_chu=f"Lỗi AI: {str(e)[:100]}", store=store)
        if callback:
            callback({"status": "error", "step": "error", "message": f"Lỗi bài {cid}: {e}"})
        return {"success": False, "message": str(e)}


def luu_chinh_sua_bai(content_id: str, du_lieu_sua: dict) -> dict:
    """Lưu nội dung chỉnh sửa trực tiếp (Caption, Bài báo, Bản được chọn) từ Web UI."""
    store = lay_store()
    tim = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return {"success": False, "message": "Không tìm thấy bài viết"}
    
    idx, row = tim
    cap_chon = du_lieu_sua.get("caption_lua_chon") or ""
    cap_v1 = du_lieu_sua.get("caption_version_1") or ""
    cap_v2 = du_lieu_sua.get("caption_version_2") or ""
    cap_v3 = du_lieu_sua.get("caption_version_3") or ""
    bai_bao = du_lieu_sua.get("bai_bao") or ""
    article_url = du_lieu_sua.get("article_url") or row.get("Article URL") or ""

    # Cập nhật row trong store
    row["Caption mới"] = cap_chon or cap_v1
    if bai_bao:
        row["Bài báo"] = bai_bao[:500] + "... [xem chi tiết trong thư mục]"
    row["Article URL"] = article_url
    row["Status"] = "SAN_SANG"
    store.cap_nhat_dong("CONTENT POOL", idx, row)

    # Cập nhật file bo_bai trong du_lieu_fb
    fb_dir = os.path.join(DUONG_DAN, "du_lieu_fb")
    if os.path.exists(fb_dir):
        for root, _, files in os.walk(fb_dir):
            target = f"bo_bai_{content_id}.json"
            if target in files:
                fpath = os.path.join(root, target)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        goi = json.load(f)
                    goi["caption_lua_chon"] = cap_chon
                    goi["caption_version_1"] = cap_v1
                    goi["caption_version_2"] = cap_v2
                    goi["caption_version_3"] = cap_v3
                    goi["bai_bao"] = bai_bao
                    goi["article_url"] = article_url
                    with open(fpath, "w", encoding="utf-8") as f:
                        json.dump(goi, f, ensure_ascii=False, indent=2)

                    # Cập nhật cả file txt
                    txt_path = os.path.join(root, f"caption_{content_id}.txt")
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(f"=== LINK BÀI BÁO (COMMENT ĐẦU TIÊN) ===\n{article_url}\n\n")
                        f.write(f"=== CAPTION ĐÃ CHỌN ĐĂNG ===\n{cap_chon}\n\n")
                        f.write(f"=== VERSION 1 ===\n{cap_v1}\n\n")
                        f.write(f"=== VERSION 2 ===\n{cap_v2}\n\n")
                        f.write(f"=== VERSION 3 ===\n{cap_v3}\n\n")
                    break
                except Exception as e:
                    print(f"[!] Lỗi cập nhật file gói: {e}")

    return {"success": True, "message": "Đã lưu chỉnh sửa thành công"}


def hoan_thanh_hang_loat(danh_sach_id: list, ghi_chu: str = "Đã hoàn thành hàng loạt (Tab 3)") -> dict:
    """Hoàn thành nhiều bài một lần: đặt Status = SAN_SANG, giữ caption AI đã sinh sẵn.

    Trả về {success, so_thanh_cong, so_loi, loi:[{id, err}]}.
    """
    store = lay_store()
    so_thanh_cong = 0
    loi = []
    for cid in danh_sach_id:
        cid = str(cid or "").strip()
        if not cid:
            loi.append({"id": cid, "err": "ID rỗng"})
            continue
        tim = store.tim_dong("CONTENT POOL", "Content ID", cid)
        if not tim:
            loi.append({"id": cid, "err": "Không tìm thấy bài"})
            continue
        idx, row = tim
        st = str(row.get("Status") or "").strip()
        if st == "HOAN_THANH":
            loi.append({"id": cid, "err": "Đã hoàn thành (HOAN_THANH)"})
            continue
        if st == "ERROR":
            loi.append({"id": cid, "err": "Bài đang bị lỗi AI (ERROR) - không được phép hoàn thành"})
            continue
        # Giữ caption sẵn có; nếu trống mới dùng caption gốc làm nền
        if not str(row.get("Caption mới") or "").strip():
            row["Caption mới"] = str(row.get("Caption") or "").strip()
        row["Status"] = "SAN_SANG"
        if ghi_chu:
            row["Ghi chú"] = ghi_chu
        store.cap_nhat_dong("CONTENT POOL", idx, row)
        so_thanh_cong += 1
    return {"success": True, "so_thanh_cong": so_thanh_cong, "so_loi": len(loi), "loi": loi}


def xu_ly_anh_hoan_thanh_mot_bai(content_id: str, format_type: str = "1:1", co_logo: bool = True) -> dict:
    """Bước cắt ảnh (Tab 4): tải + crop ảnh chuẩn tỷ lệ rồi đặt Status = HOAN_THANH.

    `co_logo=True` → dán logo lên ảnh (dùng cho nút Tạo Ảnh).
    `co_logo=False` → không dán logo (dùng cho ảnh reel).
    Cắt ảnh vào CHÍNH thư mục chứa `bo_bai_<id>.json` (nếu tìm thấy) để gói bài nằm cùng chỗ.
    """
    store = lay_store()
    tim = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return {"success": False, "message": f"Không tìm thấy bài {content_id}"}
    _, dong = tim

    # 1) Xác định thư mục gói bài (nếu có), không thì tạo mới
    thu_muc = None
    fb_dir = os.path.join(DUONG_DAN, "du_lieu_fb")
    if os.path.exists(fb_dir):
        for root, _, files in os.walk(fb_dir):
            if f"bo_bai_{content_id}.json" in files:
                thu_muc = root
                break
    if not thu_muc:
        thu_muc = tao_thu_muc_ngay_gio()

    try:
        anh_path = chuan_bi_media(dong, format_type=format_type, thu_muc=thu_muc,
                                  co_logo=co_logo)
        if not anh_path:
            # Không tải được ảnh — vẫn đánh dấu xong để không kẹt ở tab4
            anh_path = dong.get("Media") or ""

        # 2) Cập nhật `anh_path`/`folder` vào bo_bai_<id>.json
        if os.path.exists(fb_dir):
            for root, _, files in os.walk(fb_dir):
                if f"bo_bai_{content_id}.json" in files:
                    fp = os.path.join(root, f"bo_bai_{content_id}.json")
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            goi = json.load(f)
                        goi["anh_path"] = anh_path
                        goi["folder"] = thu_muc
                        with open(fp, "w", encoding="utf-8") as f:
                            json.dump(goi, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    break

        doi_status(content_id, "HOAN_THANH", ghi_chu=f"Đã cắt ảnh ({format_type})", store=store)
        return {"success": True, "data": {"content_id": content_id, "anh_path": anh_path}}

    except Exception as e:
        doi_status(content_id, "ERROR", ghi_chu=f"Lỗi cắt ảnh: {str(e)[:100]}", store=store)
        return {"success": False, "message": str(e)}


def xu_ly_anh_reel_mot_bai(content_id: str, format_type: str = "1:1") -> dict:
    """Tạo ẢNH REEL riêng (KHÔNG logo) trong du_lieu_reel/anh_reel/.

    Không đụng vào ảnh chính (có logo) đã lưu trong bo_bai — nên nếu bạn đã bấm
    "Tạo Ảnh" trước, ảnh đăng FB vẫn giữ logo; video reel dùng ảnh không logo.
    """
    store = lay_store()
    tim = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if not tim:
        return {"success": False, "message": f"Không tìm thấy bài {content_id}"}
    _, dong = tim
    thu_muc_reel = os.path.join(DUONG_DAN, "du_lieu_reel", "anh_reel")
    os.makedirs(thu_muc_reel, exist_ok=True)
    try:
        anh_reel = chuan_bi_media(dong, format_type=format_type, thu_muc=thu_muc_reel,
                                  co_logo=False)
        if not anh_reel:
            anh_reel = dong.get("Media") or ""
        return {"success": True, "data": {"content_id": content_id, "anh_path": anh_reel}}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ---------------------------------------------------------------------------
# CACHE DOC GOI BAI (du_lieu_fb/**/bo_bai_<cid>.json)
# Lan quet truoc day MO ~760 file JSON moi lan mo Tab 4/5 (~200-400 ms) va
# day theo moi item -> /api/hoan_thanh nang ~10 MB. Tu gio doc 1 lan, dung lai.
# ---------------------------------------------------------------------------
_GOI_CACHE = {"dir": None, "map": None, "dau": None, "expires": 0.0}
_GOI_LOCK = threading.Lock()


def _dang_ky_goi_fb(fb_dir):
    """Danh ba dinh danh tat ca file bo_bai_*.json (KHONG doc noi dung).

    Tra ve {cid: (duong_dan, (mtime, size))} va an `co_doi_thay` vao toan cuc
    de biet co them/xoa file so voi lan quet truoc.
    """
    dang_ky = {}
    if not os.path.exists(fb_dir):
        return dang_ky
    for root, _, files in os.walk(fb_dir):
        for f in files:
            if not (f.startswith("bo_bai_") and f.endswith(".json")):
                continue
            duong_dan = os.path.join(root, f)
            cid = f[len("bo_bai_"):-len(".json")]
            try:
                stt = os.stat(duong_dan)
            except OSError:
                continue
            dinh = (duong_dan, (stt.st_mtime_ns, stt.st_size))
            cu = dang_ky.get(cid)
            # Bai trung ten o nhieu thu muc: lay ban MOI NHAT (guong hanh vi cu)
            if cu is None or cu[1][0] < dinh[1][0]:
                dang_ky[cid] = dinh
    return dang_ky


def _quet_goi_fb(fb_dir: str) -> dict:
    """Doc toan bo file `bo_bai_<cid>.json` -> {cid: gói bài}, có cache 20 s.

    An toàn với file ghi trong lúc quét: `moc` = thời điểm BẮT ĐẦU quét, và vì
    os.walk đọc theo thứ tự thư mục nên một file bị sửa SAU khi đã đọc sẽ có
    mtime > moc -> vòng sau buộc đọc lại. Chỉ các sửa đổi nằm trong cửa sổ 20 s
    mới có thể chậm hiển thị một nhịp (Tab 5 tự tải lại khi xong mỗi batch).
    """
    now = time.time()
    with _GOI_LOCK:
        if (_GOI_CACHE["dir"] == fb_dir and _GOI_CACHE["map"] is not None
                and now < _GOI_CACHE["expires"]):
            return _GOI_CACHE["map"]

    cu = _GOI_CACHE["map"] if _GOI_CACHE["dir"] == fb_dir else None
    cu_dau = _GOI_CACHE["dau"] if cu is not None else None
    dang_ky = _dang_ky_goi_fb(fb_dir)
    moc = time.time()

    map_goi = {}
    for cid, (duong_dan, dinh) in dang_ky.items():
        data = None
        if cu is not None and cu_dau is not None and cu_dau.get(cid) == dinh:
            data = cu.get(cid)                      # khong doi -> tai dung trong bo nho
        if data is None:
            try:
                with open(duong_dan, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except Exception:
                data = None
        if data is not None:
            map_goi[cid] = data

    with _GOI_LOCK:
        _GOI_CACHE.update({"dir": fb_dir, "map": map_goi, "dau": dang_ky,
                           "expires": moc + 20.0})
    return map_goi


def _lam_mot_goi(goi: dict) -> dict:
    """Ban RUT GON goi bai gui len Tab 4/5: chi giu truong card/web can.

    Bai bao (500-11k ky) va caption_version_1..3 KHONG nằm ở đây nữa — chi tai
    khi mo chi tiet qua /api/pool/chi_tiet/<cid>.
    """
    return {
        "article_url": goi.get("article_url") or "",
        "anh_path": goi.get("anh_path") or "",
        "chu_de": goi.get("chu_de") or "",
        "caption_lua_chon": goi.get("caption_lua_chon") or "",
        "folder": goi.get("folder") or "",
        "tieu_de": goi.get("tieu_de") or "",
        "nhan_vat": goi.get("nhan_vat") or "",
        "web": goi.get("web") or "",
        "loai_xuat": goi.get("loai_xuat") or "",
    }


def _lay_danh_sach_theo_status(*statuses, phien=None, vung=None,
                               day_du=False, with_goi=True) -> list:
    """Gom bài trong Content Pool có Status thuộc `statuses`, kèm dữ liệu bo_bai (ảnh, caption, link).

    `phien`  : chỉ lấy bài thuộc phiên cào này (giá trị `Phien_cao`, hoặc `Cac_phien_gap` nếu có).
    `vung`   : 'us' | 'global' — chỉ lấy bài của vùng này (mặc định = vùng đang chọn
               trên giao diện; bài chưa có cột Vung được tính là US).
    `day_du` : True -> goi_fb NGUYÊN BẢN (kèm `bai_bao` + 3 caption version).
               False (mặc định) -> goi_fb RÚT GỌN, đủ cho card Tab 4/5 và Excel.
    `with_goi`: False -> KHÔNG đọc thư mục du_lieu_fb nữa (nhanh hơn nhiều) và
               các trường dẫn xuất (article_url/anh_path/folder) chỉ lấy từ Pool.
    """
    store = lay_store()
    danh_sach = store.lay_tat_ca("CONTENT POOL")
    ket_qua = []

    # `day_du=True`  -> kem TOAN BO goi_fb (chi dung cho API chi tiet 1 bai).
    # `day_du=False` -> danh sach Tab 4/5: KHONG gui nguyen goi_fb (bai bao 500-
    # 11k ky x 600 bai = ~10 MB JSON -> trinh duyet treo), chi lay vai truong can
    # hien thi/card. with_goi=False -> khong doc 700+ file bo_bai len chut nao.
    fb_dir = os.path.join(DUONG_DAN, "du_lieu_fb")
    map_goi = _quet_goi_fb(fb_dir) if (day_du or with_goi) else {}

    for row in danh_sach:
        st = str(row.get("Status") or "").strip()
        cid = str(row.get("Content ID") or "").strip()
        if not dung_vung(row, vung):
            continue
        if st not in statuses:
            continue
        if phien:
            cac_phien = row.get("Cac_phien_gap")
            if cac_phien is None:
                if str(row.get("Phien_cao") or "").strip() != phien:
                    continue
            elif phien not in (cac_phien if isinstance(cac_phien, list) else [str(cac_phien)]):
                continue
        if st in statuses:
            item = dict(row)
            goi = map_goi.get(cid) or {}
            # day_du=False: chi gui ban RUT GON (khong co `bai_bao` 11k ky) ->
            # card Tab 4/5 nhe hon ~25 lan; mo chi tiet tai rieng qua API 1 bai.
            item["goi_fb"] = goi if day_du else _lam_mot_goi(goi)
            item["anh_path"] = goi.get("anh_path") or ""
            item["reel_path"] = duong_dan_reel(cid)
            # KEY = chủ đề (mỗi KEY một file Excel). Bài nhập link ngoài không KEY
            # -> dùng chu_de AI đã gán, rồi tới Chủ đề trong pool.
            item["chu_de"] = (str(row.get("KEY") or "").strip()
                              or (goi.get("chu_de") or "")
                              or (row.get("Chủ đề") or "")).strip()
            item["caption_lua_chon"] = goi.get("caption_lua_chon") or row.get("Caption mới") or ""
            item["article_url"] = goi.get("article_url") or row.get("Article URL") or ""
            item["folder"] = goi.get("folder") or ""
            ket_qua.append(item)

    return ket_qua


def lay_danh_sach_san_sang(vung=None):
    """Tab 4: bài đã bấm Hoàn thành ở Tab 3 (Status = SAN_SANG) — chờ cắt ảnh."""
    return _lay_danh_sach_theo_status("SAN_SANG", vung=vung)


def lay_danh_sach_hoan_thanh(phien=None, vung=None, day_du=False):
    """Tab 5: bài đã cắt ảnh xong (Status = HOAN_THANH) — đầy đủ để rà lại & xuất Excel.

    `phien`  : chỉ lấy bài thuộc phiên cào này (None = tất cả các phiên).
    `vung`   : 'us' | 'global' (None = vùng đang chọn).
    `day_du` : True -> kem TOAN BO goi_fb (ca `bai_bao`). Mac dinh False = ban
    rut gon, chi dung cho Excel/MASTER (nhung truong co san trong _lam_mot_goi),
    giup /api/hoan_thanh nhe ~25 lan.
    """
    return _lay_danh_sach_theo_status("HOAN_THANH", phien=phien, vung=vung,
                                      day_du=day_du)


def lay_cac_phien_hoan_thanh(store=None, vung=None) -> list:
    """Phiên cào cho Tab 5: gom các phiên có chứa bài HOAN_THANH, mới nhất trước.

    Mỗi phiên trả: {phien, trang:[trang đã cào], so_bai}. Chỉ tính bài đúng vùng.
    """
    store = store or lay_store()
    phien_map = {}
    for d in store.lay_tat_ca("CONTENT POOL"):
        if str(d.get("Status") or "").strip() != "HOAN_THANH":
            continue
        if not dung_vung(d, vung):
            continue
        cac_phien = d.get("Cac_phien_gap")
        if cac_phien is None:
            p = str(d.get("Phien_cao") or "").strip()
            ds_phien = [p] if p else []
        else:
            ds_phien = cac_phien if isinstance(cac_phien, list) else [str(cac_phien)]
        if not ds_phien:
            continue
        trang = str(d.get("Source") or "").strip()
        for p in ds_phien:
            p = str(p).strip()
            if not p:
                continue
            e = phien_map.setdefault(
                p, {"phien": p, "trang": set(), "so_bai": 0})
            if trang:
                e["trang"].add(trang)
            e["so_bai"] += 1

    ds = []
    for p, e in phien_map.items():
        ds.append({"phien": p, "trang": sorted(e["trang"]),
                   "so_bai": e["so_bai"]})
    ds.sort(key=lambda x: x["phien"], reverse=True)
    return ds


def danh_dau_da_dang_fb(content_id: str):
    """Đánh dấu bài viết đã đăng xong lên Facebook -> DONE."""
    store = lay_store()
    return doi_status(content_id, "DONE", ghi_chu="Đã đăng Facebook hoàn tất qua Antidetect", store=store)
