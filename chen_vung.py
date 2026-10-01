# -*- coding: utf-8 -*-
"""Di trú tách 2 vùng nguồn cào US / GLOBAL (chạy 1 lần, idempotent).

Mặc định CHỈ báo cáo (--dry), phải có --ghi mới đụng vào file.

  1. source_config.json (81 nguồn, tất cả Vung='us')
        → du_lieu_traffic/nguon_us.json
  2. Gloabalcao.xlsx (38 link; cột A=LINK, B=PAGE, C=KEY|GHI CHÚ; KEY chỉ ghi ở
     dòng ĐẦU nhóm → dòng trống KEY kế thừa nhóm trên; 6 dòng 10-15 trống KEY
     được người dùng xác nhận thuộc 'Hoàng gia Thuỵ Điển')
        → du_lieu_traffic/nguon_global.json   ("Vung":"global")
     + sửa chính tả tên KEY theo bảng SUA_KEY.
  3. content_pool.json: thêm cột "Vung"='us' cho các bài chưa có (toàn bộ bài
     hiện tại cào từ kho US) + backup content_pool.backup_truoc_tach_vung_HHMMSS.json
  4. du_lieu_exel/MASTER_DANG_BAI.xlsx → MASTER_DANG_BAI_US.xlsx
     (bản cũ dời vào du_lieu_exel\\_cu\\ để GPM không đọc nhầm file stale)
  5. Tạo du_lieu_exel/us/ + du_lieu_exel/global/, dời san_sang_*.xlsx cũ vào us/

Chạy:  python chen_vung.py --dry      xem kế hoạch
       python chen_vung.py --ghi      làm thật
"""
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

import openpyxl

DUONG_DAN = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DUONG_DAN)
from vung import (GLOBAL, US, duong_dan_danh_ba, duong_dan_master,  # noqa: E402
                  duong_dan_nguon, thu_muc_excel)

DU_LIEU_TRAFFIC = os.path.join(DUONG_DAN, "du_lieu_traffic")
DU_LIEU_EXEL = os.path.join(DUONG_DAN, "du_lieu_exel")
FILE_SOURCE_CU = os.path.join(DU_LIEU_TRAFFIC, "source_config.json")
FILE_POOL = os.path.join(DU_LIEU_TRAFFIC, "content_pool.json")
FILE_GLOBAL_XLSX = os.path.join(DUONG_DAN, "Gloabalcao.xlsx")
FILE_MASTER_CU = os.path.join(DU_LIEU_EXEL, "MASTER_DANG_BAI.xlsx")

# Chính tả tên KEY (người dùng chốt: sửa hết chính tả). KEY trong Excel → KEY chuẩn.
SUA_KEY = {
    "Hoàng gia Nauy": "Hoàng gia Na Uy",
    "Hoàng gia và đua xe dạp": "Hoàng gia và đua xe đạp",
    "Hoàng gia vói người nổi tiếng": "Hoàng gia với người nổi tiếng",
    "Hoàng gua + Vụ án Đan Mạch": "Hoàng gia + Vụ án Đan Mạch",
}

# 6 dòng (Excel 10-15) có LINK nhưng trống cả PAGE lẫn KEY → người dùng xác nhận
# thuộc nhóm Hoàng gia Thuỵ Điển. Quy tắc: KEY trống + PAGE có = kế thừa nhóm
# phía trên; KEY trống + PAGE trống = nguồn ẩn danh của nhóm FIX_KEY_DUOI.
KEY_NGUON_AN_DANH = "Hoàng gia Thuỵ Điển"


def sua_chinh_ta(key: str) -> str:
    return SUA_KEY.get(key.strip(), key.strip())


def doc_excel_toan_cau(fp: str) -> list:
    """Đọc Gloabalcao.xlsx → [{dong, link, page, key_tho, ghi_chu}] hoặc [{dong, loi}]."""
    wb = openpyxl.load_workbook(fp, data_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    ds, key_gan_nhat = [], ""
    for i, r in enumerate(rows):
        if i == 0:
            continue                                   # header LINK | PAGE | KEY
        cells = [("" if v is None else str(v).strip()) for v in (list(r) + ["", "", "", ""])[:3]]
        link, page, key_tho = cells
        if not (link or page or key_tho):
            continue
        if not link or not link.lower().startswith("http"):
            ds.append({"dong": i + 1, "loi": f"LINK thiếu/không phải URL: {link[:50]!r}"})
            continue
        if key_tho:
            cac_dong = [x.strip() for x in key_tho.splitlines() if x.strip()]
            key = cac_dong[0]
            ghi_chu = " | ".join(cac_dong[1:])
            key_gan_nhat = key
        elif not page:
            key, ghi_chu = KEY_NGUON_AN_DANH, "KEY do người dùng xác nhận (dòng trống)"
        else:
            key, ghi_chu = key_gan_nhat, ""            # kế thừa nhóm trên
        if not key:
            ds.append({"dong": i + 1, "loi": "không xác định được KEY", "link": link})
            continue
        ds.append({"dong": i + 1, "link": link, "page": page,
                   "key_tho": key, "ghi_chu": ghi_chu})
    return ds


# ------------------------------------------------------------------ từng bước
def buoc_us(ghi: bool) -> list:
    with open(FILE_SOURCE_CU, "r", encoding="utf-8") as f:
        ds = json.load(f)
    if not isinstance(ds, list):
        return ["1) ❌ source_config.json không phải list"]
    moi = [dict(r, Vung=US) for r in ds]
    fp_moi = duong_dan_nguon(US)
    bao = [f"1) {os.path.basename(FILE_SOURCE_CU)} → du_lieu_traffic/{os.path.basename(fp_moi)}"
           f"   [{len(moi)} nguồn, thêm Vung='us']"]
    bao.append("     · " + " | ".join(f"{k}:{n}" for k, n in
               Counter(str(r.get('KEY') or '').strip() for r in moi).most_common()))
    if ghi:
        with open(fp_moi, "w", encoding="utf-8") as f:
            json.dump(moi, f, ensure_ascii=False, indent=2)
        bao.append(f"     ✅ đã ghi {os.path.basename(fp_moi)}")
    return bao


def buoc_global(ghi: bool) -> list:
    if not os.path.exists(FILE_GLOBAL_XLSX):
        return [f"2) ❌ không thấy {os.path.basename(FILE_GLOBAL_XLSX)}"]
    ds = doc_excel_toan_cau(FILE_GLOBAL_XLSX)
    loi = [d for d in ds if d.get("loi")]
    ok = [d for d in ds if not d.get("loi")]

    seen, ket_qua, trung, doi_ten = set(), [], [], {}
    for d in ok:
        k_moi = sua_chinh_ta(d["key_tho"])
        if k_moi != d["key_tho"]:
            doi_ten[d["key_tho"]] = k_moi
        if d["link"] in seen:
            trung.append(d["link"])
            continue
        seen.add(d["link"])
        dong = {
            "KEY": k_moi,
            "Facebook nguồn": d["link"],
            "Tên page": d["page"],
            "Nhân vật gợi ý": "",        # user chốt: để trống, AI tự nhận diện
            "Vung": GLOBAL,
        }
        if d.get("ghi_chu"):
            dong["Ghi chú"] = d["ghi_chu"]
        ket_qua.append(dong)

    fp_moi = duong_dan_nguon(GLOBAL)
    bao = [f"2) {os.path.basename(FILE_GLOBAL_XLSX)} → du_lieu_traffic/{os.path.basename(fp_moi)}"
           f"   [{len(ket_qua)} nguồn hợp lệ]"]
    for k_old, k_new in sorted(doi_ten.items()):
        bao.append(f"     ✎ chính tả KEY: {k_old!r} → {k_new!r}")
    for k, n in Counter(r["KEY"] for r in ket_qua).most_common():
        bao.append(f"     · {k:<40} {n} nguồn")
    for d in loi:
        bao.append(f"     ⚠ bỏ qua dòng {d['dong']}: {d['loi']}")
    if trung:
        bao.append(f"     ⚠ {len(trung)} link trùng bị loại")
    if ghi:
        with open(fp_moi, "w", encoding="utf-8") as f:
            json.dump(ket_qua, f, ensure_ascii=False, indent=2)
        bao.append(f"     ✅ đã ghi {os.path.basename(fp_moi)}")
    return bao


def buoc_pool(ghi: bool) -> list:
    with open(FILE_POOL, "r", encoding="utf-8") as f:
        ds = json.load(f)
    if not isinstance(ds, list):
        return ["3) ❌ content_pool.json không phải list"]
    da_co = sum(1 for r in ds if str(r.get("Vung") or "").strip())
    moi = []
    for r in ds:
        r = dict(r)
        if not str(r.get("Vung") or "").strip():
            r["Vung"] = US
        moi.append(r)
    bao = [f"3) content_pool.json  [{len(moi)} bài · {da_co} bài đã có Vung · "
           f"gán Vung='us' cho {len(moi) - da_co} bài]"]
    bao.append("     · " + str(dict(Counter(str(r.get("Vung")) for r in moi))))
    if ghi:
        dau = datetime.now().strftime("%H%M%S")
        backup = os.path.join(DU_LIEU_TRAFFIC, f"content_pool.backup_truoc_tach_vung_{dau}.json")
        shutil.copy2(FILE_POOL, backup)
        with open(FILE_POOL, "w", encoding="utf-8") as f:
            json.dump(moi, f, ensure_ascii=False, indent=2)
        bao.append(f"     ✅ backup → {os.path.basename(backup)} → đã ghi content_pool.json")
    return bao


def buoc_master_va_excel(ghi: bool) -> list:
    bao = []
    fp_us = duong_dan_master(US)
    fp_gl = duong_dan_master(GLOBAL)
    if os.path.exists(FILE_MASTER_CU):
        bao.append(f"4) {os.path.basename(FILE_MASTER_CU)} → {os.path.basename(fp_us)}"
                   f"   (master global sẽ sinh sau: {os.path.basename(fp_gl)})")
        if ghi:
            if os.path.exists(fp_us):
                bao.append("     ⚠ MASTER_DANG_BAI_US.xlsx đã tồn tại — không đè")
            else:
                try:
                    shutil.copy2(FILE_MASTER_CU, fp_us)
                    bao.append(f"     ✅ đã tạo {os.path.basename(fp_us)}")
                except OSError as e:
                    bao.append(f"     ❌ không copy được (Excel đang mở file?): {e}")
            # dời file cũ vào _cu để GPM không đọc nhầm bản stale
            thu_cu = os.path.join(DU_LIEU_EXEL, "_cu")
            try:
                os.makedirs(thu_cu, exist_ok=True)
                if os.path.exists(FILE_MASTER_CU):
                    dich = os.path.join(thu_cu, "MASTER_DANG_BAI.xlsx")
                    if os.path.exists(dich):
                        dich = os.path.join(
                            thu_cu, "MASTER_DANG_BAI_%s.xlsx" % datetime.now().strftime("%H%M%S"))
                    shutil.move(FILE_MASTER_CU, dich)
                    bao.append(f"     ✅ đã dời bản cũ → _cu\\{os.path.basename(dich)}")
            except OSError as e:
                bao.append(f"     ⚠ không dời được MASTER_DANG_BAI.xlsx (đang bị khoá?) — "
                           f"HÃY XOÁ/ĐỔI TÊN tay, GPM phải trỏ sang MASTER_DANG_BAI_US.xlsx")
    else:
        bao.append("4) MASTER_DANG_BAI.xlsx không tồn tại — bỏ qua")

    thu_us, thu_gl = thu_muc_excel(US), thu_muc_excel(GLOBAL)
    di = [f for f in sorted(os.listdir(DU_LIEU_EXEL))
          if f.lower().endswith(".xlsx") and f.startswith("san_sang_")
          and os.path.isfile(os.path.join(DU_LIEU_EXEL, f))]
    bao.append(f"5) du_lieu_exel\\us\\ + du_lieu_exel\\global\\ — "
               f"{len(di)} file san_sang_*.xlsx cũ (bài US) → us/")
    if ghi:
        for f in di:
            try:
                shutil.move(os.path.join(DU_LIEU_EXEL, f), os.path.join(thu_us, f))
            except OSError as e:
                bao.append(f"     ⚠ không chuyển được {f}: {e}")
        bao.append("     ✅ " + thu_us)
        bao.append("     ✅ " + thu_gl)
    if not os.path.exists(duong_dan_danh_ba(GLOBAL)):
        bao.append("6) DANH BẠ GLOBAL CHƯA CÓ: ngoài tool\\danh_sach_uid_global.xlsx")
        bao.append("     → xuất master GLOBAL sẽ từ chối chạy cho tới khi nạp file này")
    return bao


def main():
    ghi = ("--ghi" in sys.argv) or ("-y" in sys.argv)
    print("=" * 78)
    print("DI TRÚ TÁCH VÙNG US / GLOBAL —", "LÀM THẬT (--ghi)" if ghi else "XEM TRƯỚC (--dry)")
    print("=" * 78)
    for fn in (buoc_us, buoc_global, buoc_pool, buoc_master_va_excel):
        for line in fn(ghi):
            print(line)
        print("-" * 78)
    if not ghi:
        print("Chưa sửa file nào. Chạy:  python chen_vung.py --ghi")


if __name__ == "__main__":
    main()
