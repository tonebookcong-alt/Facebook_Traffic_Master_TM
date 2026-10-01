# -*- coding: utf-8 -*-
"""Chữa lỗi bài HOAN_THANH thiếu LINK BÀI BÁO (Article URL rỗng).

Nguyên nhân gốc: trước bản sửa "bắt buộc chọn web" + "tắt reasoning",
luong_b.xu_ly_ai_mot_bai() gọi dang_bai_web(web=None) -> trả về
{"success": False, "article_url": ""} nhưng bài VẪN được đặt HOAN_THANH.
Vì vậy có bài Status=HOAN_THANH mà không có link, GPM sẽ comment "READ MORE: " rỗng.

Hai nhóm cần chữa:
  A. Có sẵn bài báo trong bo_bai_*.json (chỉ thiếu link)  -> chỉ đăng lại lên web.
  B. Chưa từng có bài báo (mất cả bo_bai_*.json)          -> AI viết bài báo rồi đăng.

Cách dùng:
  python sua_link_bao.py --dry            chỉ liệt kê, không gọi API
  python sua_link_bao.py --only A         chữa nhóm A
  python sua_link_bao.py --limit 2        chữa 2 bài đầu để thử API
  python sua_link_bao.py --all            chữa hết
  python sua_link_bao.py --vac            sau khi chữa xong: vá lại MASTER_DANG_BAI.xlsx
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DUONG_DAN = os.path.dirname(os.path.abspath(__file__))
os.chdir(DUONG_DAN)
sys.path.insert(0, DUONG_DAN)

from google_sheets import lay_store                      # noqa: E402
from dang_web import dang_bai_web                        # noqa: E402
from viet_lai import chon_tieu_de, viet_bai_bao_va_title   # noqa: E402
import media                                             # noqa: E402

TEN_SHEET = "CONTENT POOL"
WEB_MAC_DINH = "us"          # 322/337 bài đã có link đều đăng qua web 'us'
DUONG_DAN_GOI_FB = os.path.join(DUONG_DAN, "du_lieu_fb")


# --------------------------------------------------------------- đọc dữ liệu
def _tim_file_goi(cid):
    """File bo_bai MỚI NHẤT của bài (du_lieu_fb/<phiên>/bo_bai_<cid>.json).

    Phải lấy mới nhất: sau khi chữa link sẽ có thêm bản ở thư mục phiên hiện tại,
    đọc bản cũ sẽ trả về article_url rỗng.
    """
    ds = glob.glob(os.path.join(DUONG_DAN, "du_lieu_fb", "**", f"bo_bai_{cid}.json"),
                   recursive=True)
    if not ds:
        return None
    return max(ds, key=lambda p: os.path.getmtime(p))


def _anh_cua_goi(goi, cid):
    """Đường dẫn ảnh 1:1 tuyệt đối, ưu tiên trong bo_bai, fallback tìm đĩa."""
    p = str(goi.get("anh_path") or "").strip()
    if p and os.path.isfile(p):
        return p
    if p and not os.path.isabs(p):
        q = os.path.normpath(os.path.join(DUONG_DAN, p))
        if os.path.isfile(q):
            return q
    nu = glob.glob(os.path.join(DUONG_DAN, "du_lieu_fb", "**", f"{cid}_1x1.jpg"),
                   recursive=True)
    if nu:
        return os.path.abspath(nu[0])
    return ""


def quy_lich(store):
    """Trả về (danh sach bai thieu link, chi so trong pool)."""
    kho = []
    pool = store.lay_tat_ca(TEN_SHEET)
    for idx, row in enumerate(pool):
        if str(row.get("Status") or "").strip() != "HOAN_THANH":
            continue
        if str(row.get("Article URL") or "").strip():
            continue
        cid = str(row.get("Content ID") or "").strip()
        if not cid:
            continue
        fp = _tim_file_goi(cid)
        goi = {}
        if fp:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    goi = json.load(f)
            except Exception:
                goi = {}
        bai_bao = str(goi.get("bai_bao") or "").strip()
        kho.append({
            "chi_so": idx,
            "cid": cid,
            "row": row,
            "nhom": "A" if len(bai_bao) >= 800 else "B",
            "bai_bao": bai_bao,
            "file_goi": fp,
            "goi": goi,
            "KEY": str(row.get("KEY") or goi.get("key") or "Chung").strip() or "Chung",
            "nhan_vat": str(row.get("Nhân vật/chủ đề") or goi.get("nhan_vat") or "Chung").strip() or "Chung",
            "caption_moi": str(row.get("Caption mới") or goi.get("caption_lua_chon") or "").strip(),
            "caption_goc": str(row.get("Caption") or "").strip(),
            "web_luu": str(row.get("Web") or goi.get("web") or "").strip().lower(),
        })
    return kho


# ------------------------------------------------------------------- 1 buoc
def xu_ly_mot_bai(store, b, web, log=print):
    cid, row = b["cid"], dict(b["row"])
    t0 = time.time()
    log(f"  [{b['nhom']}] {cid}  KEY={b['KEY'][:20]}  nv={b['nhan_vat'][:26]}")

    bai_bao = b["bai_bao"]
    tieu_de = ""
    if b["nhom"] == "B":
        nguon_text = b["caption_moi"] or b["caption_goc"]
        if not nguon_text:
            return {"ok": False, "err": "Không có caption để viết bài báo"}
        log(f"       AI viet bai bao + tieu de that (tat reasoning)...")
        try:
            kq = viet_bai_bao_va_title(nguon_text, nhan_vat=b["nhan_vat"], key=b["KEY"])
            bai_bao = kq["bai_bao"]
            tieu_de = kq["tieu_de"]
        except Exception as e:
            return {"ok": False, "err": f"viet_bai_bao loi: {type(e).__name__}: {e}"}
    if not tieu_de:
        # Nhóm A / bài đã có sẵn: lấy tiêu đề từ chính nội dung, không công thức
        tieu_de, _, _ = chon_tieu_de(
            bai_bao,
            caption_goc=b["caption_moi"] or b["caption_goc"],
            nhan_vat=b["nhan_vat"], key=b["KEY"])
        if not (bai_bao or "").strip():
            return {"ok": False, "err": "AI tra ve bai bao rong"}
        log(f"       bai_bao = {len(bai_bao)} ky")

    thu_muc = media.tao_thu_muc_ngay_gio()
    anh = _anh_cua_goi(b["goi"], cid)
    if anh:
        try:
            dich = os.path.join(thu_muc, os.path.basename(anh))
            if os.path.abspath(dich) != os.path.abspath(anh):
                shutil.copy2(anh, dich)
            anh = dich
        except Exception as e:
            log(f"       ! copy anh that bai ({e}) -> dung anh cu {anh}")
    else:
        log("       ! khong co anh 1:1 -> dang khong co feature image")

    log(f"       dang_bai_web(web={web}, tieu_de='{tieu_de[:60]}', "
        f"anh={'co' if anh and os.path.isfile(anh) else 'khong'})...")
    res = dang_bai_web(tieu_de=tieu_de, noi_dung=bai_bao,
                       anh_path=anh if anh and os.path.isfile(anh) else "",
                       nhan_vat=b["nhan_vat"], key=b["KEY"], web=web)
    url = str(res.get("article_url") or "").strip()
    if not (res.get("success") and url):
        return {"ok": False, "err": f"dang_bai_web: {res.get('message') or res}"}
    log(f"       URL = {url}")

    # --- ghi gói bài mới (đường dẫn thật, khớp chuẩn luong_b) ---
    chu_de = str(row.get("Chủ đề") or b["goi"].get("chu_de") or b["KEY"]).strip() or b["KEY"]
    goi_moi = dict(b["goi"])
    goi_moi.update({
        "content_id": cid,
        "key": b["KEY"],
        "nhan_vat": b["nhan_vat"],
        "chu_de": chu_de,
        "web": web,
        "thoi_gian_sua_link": datetime.now().isoformat(),
        "article_url": url,
        "tieu_de": tieu_de,
        "article_id": str(res.get("article_id") or ""),
        "anh_path": anh or goi_moi.get("anh_path") or "",
        "bai_bao": bai_bao,
        "folder": thu_muc,
    })
    if b["caption_moi"]:
        goi_moi.setdefault("caption_lua_chon", b["caption_moi"])
        goi_moi.setdefault("caption_version_1", b["caption_moi"])
    file_goi = os.path.join(thu_muc, f"bo_bai_{cid}.json")
    with open(file_goi, "w", encoding="utf-8") as f:
        json.dump(goi_moi, f, ensure_ascii=False, indent=2)

    # --- cập nhật pool ---
    fresh = store.lay_tat_ca(TEN_SHEET)
    idx = None
    for i, r in enumerate(fresh):
        if str(r.get("Content ID") or "").strip() == cid:
            idx = i
            break
    if idx is None:
        return {"ok": True, "url": url, "warn": "khong tim thay dong trong pool de ghi"}
    m = dict(fresh[idx])
    m["Article URL"] = url
    m["Web"] = web
    m["Bài báo"] = bai_bao[:500] + "... [xem chi tiết trong thư mục]"
    if b["caption_moi"]:
        m["Caption mới"] = b["caption_moi"]
    if not str(m.get("Media") or "").strip() and anh:
        m["Media"] = os.path.relpath(anh, DUONG_DAN)
    m["Ghi chú"] = (str(m.get("Ghi chú") or "") +
                    f" | Sua link bao {datetime.now():%Y-%m-%d %H:%M} (nhom {b['nhom']}, "
                    f"web {web})").strip(" |")
    if b["nhom"] == "B":
        m["Status"] = "HOAN_THANH"
    store.cap_nhat_dong(TEN_SHEET, idx, m)
    return {"ok": True, "url": url, "giay": round(time.time() - t0, 1),
            "ky": len(bai_bao), "file_goi": file_goi}


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="chi liet ke, khong goi API")
    ap.add_argument("--only", choices=("A", "B"), help="chi chua nhom nay")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--web", default=WEB_MAC_DINH)
    ap.add_argument("--vac", action="store_true", help="goi va_master() sau khi xong")
    a = ap.parse_args()

    store = lay_store()
    kho = quy_lich(store)
    print(f"POOL: {len(store.lay_tat_ca(TEN_SHEET))} dong | "
          f"HOAN_THANH thieu Article URL: {len(kho)}")
    for b in kho:
        print("   nhom %s  %-18s %-12s %-28s goi_fb=%s  bai_bao=%d ky  web_luu=%s" % (
            b["nhom"], b["cid"], b["KEY"][:12], b["nhan_vat"][:28],
            "co" if b["file_goi"] else "khong", len(b["bai_bao"]), b["web_luu"] or "rong"))
    if a.dry:
        return

    ds = [b for b in kho if not a.only or b["nhom"] == a.only]
    if a.limit:
        ds = ds[:a.limit]
    if not a.all and not a.limit and not a.only:
        print("\n(khong chuan tham so --all/--only/--limit -> dung)")
        return

    backup = os.path.join(DUONG_DAN, "du_lieu_traffic",
                          "content_pool.backup_truoc_sua_link_%s.json" % time.strftime("%H%M%S"))
    shutil.copy2(os.path.join(DUONG_DAN, "du_lieu_traffic", "content_pool.json"), backup)
    print(f"\nbackup pool -> {os.path.basename(backup)}")
    print(f"chua {len(ds)} bai, web={a.web}\n" + "=" * 92)

    ok, fail = [], []
    for n, b in enumerate(ds, 1):
        print("[%d/%d]" % (n, len(ds)), end=" ")
        try:
            r = xu_ly_mot_bai(store, b, a.web)
        except Exception as e:
            r = {"ok": False, "err": f"{type(e).__name__}: {e}"}
        if r.get("ok"):
            ok.append((b["cid"], r["url"]))
            print("      OK %s%s" % (r["url"], ("  (%.1fs)" % r["giay"]) if r.get("giay") else ""))
        else:
            fail.append((b["cid"], r.get("err")))
            print("      LOI:", r.get("err"))
        if n < len(ds):
            time.sleep(1.5)

    print("=" * 92)
    print(f"XONG: thanh cong {len(ok)} / {len(ds)}")
    for cid, err in fail:
        print("   LOI", cid, "->", err)

    sau = quy_lich(lay_store())
    print(f"CON TOT: {len(sau)} bai HOAN_THANH khong co Article URL")

    if a.vac:
        print("\n--- va_master(): giu het bai da co, bo sung anh/link/reel ---")
        import xuat_master
        kq = xuat_master.va_master()
        print(json.dumps({k: v for k, v in kq.items() if k != "canh_bao"},
                         ensure_ascii=False)[:600])
        for c in (kq.get("canh_bao") or [])[:6]:
            print("   !", c)


if __name__ == "__main__":
    main()
