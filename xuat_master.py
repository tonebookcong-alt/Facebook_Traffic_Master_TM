# -*- coding: utf-8 -*-
"""Sinh / vá MASTER_DANG_BAI.xlsx — mỗi profile đúng 1 bài.

CẤU TRÚC CỘT TỪ 2026-09-14 (bản 15 cột): PROFILE đứng cột A, đã bỏ 3 cột
Cảm xúc / Bình luận / Chia sẻ.  src.gscript đọc theo chỉ số trong CHI_SO_GSCRIPT.

Danh bạ thật theo VÙNG (see vung.py):
  US     : C:\\traffic fb\\ngoài tool\\danh_sach_uid.xlsx
  GLOBAL : C:\\traffic fb\\ngoài tool\\danh_sach_uid_global.xlsx
sheet 0, 6 cột
  A=PROFILE  B=Nguồn(page đích)  C=Tên Page  D=UID  E=Chủ đề(Key)  F=Trạng thái
Master luôn giữ ĐÚNG thứ tự dòng của danh bạ (danh bạ dòng r -> master dòng r),
nên $profile_row tìm từ danh bạ dùng được cho 2 file.

VÙNG DỮ LIỆU (kể từ 2026-09-15): hệ thống tách làm 2 kho độc lập US / GLOBAL.
Mỗi vùng có danh bạ + file MASTER riêng (MASTER_DANG_BAI_US.xlsx /
MASTER_DANG_BAI_GLOBAL.xlsx) và chỉ nhận bài có cột `Vung` đúng vùng đó.
Luu y: KHONG CO chuyen danh ba US cho vung GLOBAL — that bai co kiem soat
con im lang dung danh ba sai la bug lon nhat cua he thong nay.

Hàm công cộng:
  xuat_master(vung=None)  : vòng gán MỚI — bỏ hết bài cũ đã gán, chia lại toàn bộ (ghi đè).
  va_master(vung=None)    : GIỮ bài đã gán, chỉ điền vào dòng đang CHỜ BÀI. Không rút gì ra.
  doi_format_master()     : đổi cấu trúc cột (18 -> 15) nhưng GIỮ NGUYÊN bài đã gán.
"""
import datetime
import os
import shutil

import openpyxl

from vung import (GLOBAL, TEN_VUNG, US, NGOAI_TOOL, chuan_vung, duong_dan_danh_ba,
                  duong_dan_master, lay_vung, vung_cua_bai)

DUONG_DAN = os.path.dirname(os.path.abspath(__file__))
TEN_FILE_MASTER = "MASTER_DANG_BAI.xlsx"
GIA_TRI_CHO_BAI = "CHỜ BÀI"
# 'Đã đăng' do chính script GPM ghi đè lên cột F danh bạ sau khi đăng xong
TRANG_THAI_DU_CHIEN = ("live", "đã đăng", "da dang")

HEADER = [
    "PROFILE", "STT", "Content ID", "KEY", "Nhân vật/chủ đề",
    "Nguồn", "Thời gian đăng",
    "Caption gốc", "Caption mới", "Link bài báo",
    "Đường dẫn ảnh", "Đường dẫn reel",
    "Status", "Chủ đề", "Tên Page",
]
COL = {ten: i + 1 for i, ten in enumerate(HEADER)}
# Chỉ số cột mà src.gscript phải đọc (patch bằng _patch_gscript_cols.py)
CHI_SO_GSCRIPT = {
    "caption": COL["Caption mới"],       # 9
    "article_link": COL["Link bài báo"],  # 10
    "image_path": COL["Đường dẫn ảnh"],   # 11
    "reel_path": COL["Đường dẫn reel"],   # 12
    "page_url": COL["Nguồn"],             # 6
    "profile": COL["PROFILE"],            # 1
}


# ----------------------------------------------------------------- danh bạ
def _tim_danh_ba(vung=None, cho_phep_cu=True, loai_master=1):
    """Đường dẫn danh bạ UID của 1 vùng.

    US Master 1  : `ngoài tool\\danh_sach_uid.xlsx`, nếu chưa có thì tìm file mới nhất.
    US Master 2  : BẮT BUỘC `ngoài tool\\danh_sach_uid_2.xlsx` (hoặc `danh_sach_uid_us_2.xlsx`).
    GLOBAL       : BẮT BUỘC `ngoài tool\\danh_sach_uid_global.xlsx`.
    """
    v = chuan_vung(vung if vung is not None else lay_vung())

    # Xử lý riêng cho Master 2 của US
    if str(loai_master) == "2" and v == US:
        p2 = duong_dan_danh_ba(US, loai_master=2)
        if os.path.isfile(p2):
            return p2
        raise FileNotFoundError(
            f"Chưa tìm thấy file danh bạ Master 2: ngoài tool\\danh_sach_uid_2.xlsx (hoặc danh_sach_uid_us_2.xlsx)\n"
            f"→ Vui lòng đặt file danh bạ Master 2 mới vào thư mục 'ngoài tool\\danh_sach_uid_2.xlsx' rồi bấm lại."
        )

    duong_dan = duong_dan_danh_ba(v, loai_master=loai_master)
    if os.path.isfile(duong_dan):
        return duong_dan
    if v != US or not cho_phep_cu:
        raise FileNotFoundError(
            f"Chưa có danh bạ UID cho vùng {TEN_VUNG[v]}: {duong_dan}\n"
            f"→ Tạo file này với đúng 6 cột như danh bạ US "
            f"(ngoài tool\\danh_sach_uid.xlsx): PROFILE | Nguồn | Tên Page | UID | "
            f"Chủ đề (Key) | Trạng thái — rồi bấm xuất lại.\n"
            f"Không dùng danh bạ của vùng khác thay thế (sẽ gán nhầm bài cho page sai vùng).")
    thu_nhat = []
    for d in os.listdir(DUONG_DAN):
        full = os.path.join(DUONG_DAN, d)
        if not os.path.isdir(full):
            continue
        p = os.path.join(full, "danh_sach_uid.xlsx")
        if os.path.isfile(p) and "backup" not in os.path.basename(p).lower():
            thu_nhat.append((os.path.getmtime(p), p))
    if not thu_nhat:
        raise FileNotFoundError("Không tìm thấy danh_sach_uid.xlsx trong C:\\traffic fb\\<folder>\\")
    thu_nhat.sort(reverse=True)
    return thu_nhat[0][1]


def chuan_hoa_chu_de(k: str) -> str:
    """Chuẩn hoá tên chủ đề để tránh lệch tên giữa danh bạ và nguồn/pool."""
    s = str(k or "").strip()
    if not s:
        return ""
    # Chuẩn hoá lỗi gõ phím nkl -> nfl
    if s.lower() == "nkl":
        return "NFL"
    if s.lower().startswith("nkl - "):
        s = "NFL - " + s[6:].strip()
    elif s.lower().startswith("nkl "):
        s = "NFL - " + s[4:].strip()
    elif s.lower().startswith("nkl+"):
        s = "NFL - " + s[4:].strip()
    elif s.lower().startswith("nfl+"):
        s = "NFL - " + s[4:].strip()

    # "New Hà Lan (có tin hoàng gia)" -> "New Hà Lan"
    if s.lower().startswith("new hà lan") or s.lower().startswith("new ha lan"):
        return "New Hà Lan"
    return s


def doc_danh_ba(duong_dan=None, vung=None, loai_master=1):
    duong_dan = duong_dan or _tim_danh_ba(vung, loai_master=loai_master)
    ws = openpyxl.load_workbook(duong_dan, data_only=True).worksheets[0]
    ds = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not any(str(x or "").strip() for x in r):
            continue
        profile = str(r[0] or "").strip()
        if not profile or profile.upper().startswith("CH"):
            continue
        ds.append({
            "PROFILE": profile,
            "Nguon page": str(r[1] or "").strip(),
            "Ten page": str(r[2] or "").strip(),
            "UID": str(r[3] or "").strip(),
            "Chu de": str(r[4] or "").strip(),
            "Trang thai": str(r[5] or "").strip(),
        })
    return ds


def du_chien(ds):
    return (ds or "").strip().lower() in TRANG_THAI_DU_CHIEN


# ----------------------------------------------------------------- bài chờ
def _moc_thoi_gian(gia_tri):
    try:
        from content_pool import _goc_thoi_gian
        g = _goc_thoi_gian(gia_tri)
        if g:
            return float(g)
    except Exception:
        pass
    s = str(gia_tri or "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s[:19], fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def lay_kho_cho(store, vung=None, loai_master=1):
    """Bài HOAN_THANH chưa từng xuất master, gom theo chủ đề, mới nhất trước.

    BUỘC đi qua luong_b.lay_danh_sach_hoan_thanh(vung=...): chỉ danh sách ĐÃ LÀM GIÀU
    mới có `reel_path` (dẪN XUẤT từ file du_lieu_reel/<Content ID>.mp4 — pool
    không lưu cột nào về reel), cùng `article_url`/`anh_path` tuyệt đối lấy trong
    bo_bai_*.json. Đọc row thô trong pool -> 3 cột reel/link/anh rỗng (bug 14/09).

    `vung`: chỉ lấy bài của vùng đang xuất — bài US không bao giờ lọt vào master
    GLOBAL và ngược lại.
    `loai_master`: 1 (Master hiện tại) | 2 (Master mới US).
    """
    import luong_b
    from viet_lai import kiem_tra_caption_hop_le
    v = chuan_vung(vung if vung is not None else lay_vung())
    is_m2 = (str(loai_master) == "2" and v == US)
    kho = {}
    for r in luong_b.lay_danh_sach_hoan_thanh(vung=v):
        if is_m2:
            # Đối với Master 2 US:
            # Nếu đã từng xuất vào Master 2 rồi -> bỏ qua (tránh trùng lặp trong chính Master 2)
            if str(r.get("Da_xuat_MASTER_2") or "").strip():
                continue
            chu_de_raw = (str(r.get("chu_de") or "") or str(r.get("Chủ đề") or "")
                          or str(r.get("KEY") or "")).strip()
            cd_chuan = chuan_hoa_chu_de(chu_de_raw).upper()
            # Riêng Nascar: người dùng cho phép tái sử dụng bài đã đăng bên Master US 1
            if cd_chuan == "NASCAR":
                pass
            else:
                # Các chủ đề khác nếu đã xuất Master 1 -> bỏ qua
                if str(r.get("Da_xuat_MASTER") or "").strip():
                    continue
        else:
            if str(r.get("Da_xuat_MASTER") or "").strip():
                continue
        if vung_cua_bai(r) != v:
            continue                                   # chống rò vùng
        # Kiểm tra chất lượng caption: loại bỏ bài lỗi tiếng Việt / từ chối AI
        cap_moi = (r.get("Caption mới") or r.get("caption_moi") or "").strip()
        ok_cap, ly_do = kiem_tra_caption_hop_le(cap_moi, vung=v)
        if not ok_cap:
            continue
        chu_de = (str(r.get("chu_de") or "") or str(r.get("Chủ đề") or "")
                  or str(r.get("KEY") or "")).strip()
        if not chu_de:
            continue
        chu_de = chuan_hoa_chu_de(chu_de)
        kho.setdefault(chu_de, []).append(r)
    for ds in kho.values():
        ds.sort(key=lambda r: (_moc_thoi_gian(r.get("Thời gian đăng")),
                               str(r.get("Phien_cao") or "")), reverse=True)
    return kho


def _lay_bai_phu_hop(kho: dict, chu_de_yc: str):
    """Lấy 1 bài từ kho phù hợp với chủ đề yêu cầu trong Master / Danh bạ.

    Quy tắc nghiệp vụ:
    1. Nếu KEY chỉ có 'NFL' (hoặc gõ nhầm 'NKL'):
       -> GẮN ĐẠI ĐỘI NÀO THUỘC NFL VÀO CŨNG ĐƯỢC!
          Duyệt qua tất cả các đội bóng thuộc NFL (nhóm 'NFL - <Tên đội>') và bài thuần 'NFL'.
          Chọn bài mới nhất từ các đội NFL có bài trong kho để gán.

    2. Nếu KEY có đúng 'NFL + TÊN ĐỘI' (VD: 'NFL - Kansas City Chiefs', 'NFL Dallas Cowboys'):
       -> BẮT BUỘC PHẢI GÁN ĐÚNG ĐỘI ĐÓ!
          Chỉ tìm đúng bài của đội đó trong kho.
          Nếu đội đó hết bài -> trả về None (để chờ bài đúng đội, TUYỆT ĐỐI KHÔNG gán bài đội khác).

    3. Các chủ đề khác (Vụ án, WNBA, Nascar, NCAA, NHL, MLB...):
       - Nếu chỉ có tên giải (VD 'NCAA', 'NHL') -> gắn đại đội nào thuộc giải đó cũng được.
       - Nếu có tên đội cụ thể (VD 'NCAA - Auburn Tigers') -> bắt buộc đúng đội đó.
       - Các chủ đề đơn lẻ (Vụ án, WNBA...) -> khớp chính xác chủ đề đó.
    """
    if not kho:
        return None

    cd = chuan_hoa_chu_de(chu_de_yc).strip()
    cd_upper = cd.upper()

    # ----------------------------------------------------
    # TRƯỜNG HỢP 1: KEY CHỈ CÓ 'NFL' (hoặc 'NKL') -> GẮN ĐẠI ĐỘI NÀO CŨNG ĐƯỢC
    # ----------------------------------------------------
    if cd_upper in ("NFL", "NKL"):
        # 1.1 Nếu có bài mang nhãn thuần "NFL"
        if kho.get("NFL"):
            return kho["NFL"].pop(0)

        # 1.2 Lấy bài từ bất kỳ đội nào thuộc NFL (có tiền tố 'NFL - ')
        cac_nhom_nfl = [k for k in kho.keys() if kho[k] and k.upper().startswith("NFL - ")]
        if cac_nhom_nfl:
            # Sắp xếp các đội theo thời gian đăng bài mới nhất để gán bài mới nhất
            cac_nhom_nfl.sort(
                key=lambda k: (_moc_thoi_gian(kho[k][0].get("Thời gian đăng")),
                               str(kho[k][0].get("Phien_cao") or "")),
                reverse=True
            )
            doi_chon = cac_nhom_nfl[0]
            return kho[doi_chon].pop(0)

        return None

    # Tương tự cho các giải khác nếu người dùng chỉ ghi tên giải chung
    if cd_upper in ("NCAA", "NHL", "MLB"):
        if kho.get(cd):
            return kho[cd].pop(0)
        cac_nhom_giai = [k for k in kho.keys() if kho[k] and k.upper().startswith(f"{cd_upper} - ")]
        if cac_nhom_giai:
            cac_nhom_giai.sort(
                key=lambda k: (_moc_thoi_gian(kho[k][0].get("Thời gian đăng")),
                               str(kho[k][0].get("Phien_cao") or "")),
                reverse=True
            )
            doi_chon = cac_nhom_giai[0]
            return kho[doi_chon].pop(0)
        return None

    # ----------------------------------------------------
    # TRƯỜNG HỢP 2: CÓ ĐÚNG KEY 'NFL + TÊN ĐỘI' (HOẶC CHỦ ĐỀ CỤ THỂ KHÁC)
    # -> BẮT BUỘC GÁN ĐÚNG ĐỘI, TUYỆT ĐỐI KHÔNG GÁN BỪA ĐỘI KHÁC!
    # ----------------------------------------------------
    # 2.1 Khớp chính xác key
    if kho.get(cd):
        return kho[cd].pop(0)

    # 2.2 Khớp linh hoạt nếu người dùng gõ thiếu dấu gạch ngang (VD: "NFL Kansas City Chiefs" -> "NFL - Kansas City Chiefs")
    cd_chuan = cd_upper.replace("-", " ").replace("+", " ")
    cd_tu_khoa = [w for w in cd_chuan.split() if w]
    for k in kho.keys():
        if not kho[k]:
            continue
        k_chuan = k.upper().replace("-", " ").replace("+", " ")
        k_tu_khoa = [w for w in k_chuan.split() if w]
        if cd_tu_khoa == k_tu_khoa:
            return kho[k].pop(0)

    # Nếu có tên đội cụ thể mà đội đó hết bài -> trả về None (chờ bài đúng đội, không gán bừa)
    return None


# ----------------------------------------------------------------- dong master
def _dong_co_bai(p, bai, stt):
    import dong_goi
    import reel
    cid = bai.get("Content ID") or ""
    goi = bai.get("goi_fb") or {}
    p_anh = goi.get("anh_path") or bai.get("Media") or ""
    if p_anh and not os.path.isabs(p_anh):
        p_anh = os.path.normpath(os.path.join(DUONG_DAN, p_anh))
        
    p_reel = bai.get("reel_path") or ""
    if not p_reel and cid:
        p_reel = reel.duong_dan_reel(cid)
    # Tự động tạo reel nếu chưa có nhưng đã có ảnh hợp lệ
    if (not p_reel or not os.path.isfile(p_reel)) and p_anh and os.path.isfile(p_anh) and cid:
        try:
            res_r = reel.tao_reel(p_anh, co_nhac=True, ten_dau_ra=cid)
            if res_r.get("success"):
                p_reel = res_r.get("video_path") or ""
        except Exception:
            pass

    if p_reel and not os.path.isabs(p_reel):
        p_reel = os.path.normpath(os.path.join(DUONG_DAN, p_reel))

    return {
        "PROFILE": p["PROFILE"], "STT": stt,
        "Content ID": cid,
        "KEY": bai.get("KEY") or p["Chu de"],
        "Nhân vật/chủ đề": bai.get("Nhân vật/chủ đề") or "",
        "Nguồn": p["Nguon page"],
        "Thời gian đăng": bai.get("Thời gian đăng") or "",
        "Caption gốc": dong_goi.lam_phang_caption(bai.get("Caption") or ""),
        "Caption mới": dong_goi.chon_caption_xuat(goi, bai),
        "Link bài báo": goi.get("article_url") or bai.get("Article URL") or "",
        "Đường dẫn ảnh": p_anh,
        "Đường dẫn reel": p_reel,
        "Status": "HOÀN THÀNH", "Chủ đề": p["Chu de"], "Tên Page": p["Ten page"],
    }


def _dong_trong(p, stt, ly_do, key_override=None):
    k_val = key_override if key_override is not None else p["Chu de"]
    return {
        "PROFILE": p["PROFILE"], "STT": stt, "Content ID": "", "KEY": k_val,
        "Nhân vật/chủ đề": "", "Nguồn": p["Nguon page"], "Thời gian đăng": "",
        "Caption gốc": "", "Caption mới": GIA_TRI_CHO_BAI, "Link bài báo": "",
        "Đường dẫn ảnh": "", "Đường dẫn reel": "",
        "Status": ly_do, "Chủ đề": p["Chu de"], "Tên Page": p["Ten page"],
    }


def xlsx_dung_chuan_gpm(file_xlsx):
    """True nếu .xlsx ở định chuẩn mà EPPlus/GPM đọc được:
    CÓ xl/sharedStrings.xml và KHÔNG dùng inlineStr.
    openpyxl luôn viết inlineStr (<is><t>) + không sinh sharedStrings -> GPM báo
    'Cannot read the input excel file'. xlsxwriter thì chuẩn."""
    import zipfile
    try:
        z = zipfile.ZipFile(file_xlsx)
    except Exception:
        return False
    try:
        names = [i.filename for i in z.infolist()]
        if "xl/sharedStrings.xml" not in names:
            return False
        for n in names:
            if n.startswith("xl/worksheets/sheet"):
                if b"inlineStr" in z.read(n):
                    return False
        return True
    finally:
        z.close()


def _o_ghi_an_toan(ws, r, c, val, cell_format=None):
    """Ghi 1 ô bằng write_string() cho mọi chuỗi để dấu '='/'+/-/@' đầu ô
    KHÔNG bị hiểu thành công thức (Excel/GPM trả #NAME? hoặc mất nội dung)."""
    if cell_format is not None:
        if val is None:
            ws.write_string(r, c, "", cell_format)
        elif isinstance(val, str):
            ws.write_string(r, c, val, cell_format)
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            ws.write_number(r, c, val, cell_format)
        else:
            ws.write_string(r, c, str(val), cell_format)
    else:
        if val is None:
            ws.write_string(r, c, "")
        elif isinstance(val, str):
            ws.write_string(r, c, val)
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            ws.write_number(r, c, val)
        else:
            ws.write_string(r, c, str(val))


def _ghi_master(file_ra, dong_ds):
    """Ghi MASTER_DANG_BAI.xlsx bằng xlsxwriter.

    Khong duoc quay ve openpyxl (ke ca lam fallback im lang): openpyxl luu
    chuoi kieu inlineStr (<is><t>) va KHONG tao xl/sharedStrings.xml ->
    EPPlus/GPM Automate bao 'Cannot read the input excel file' (dau 2026-09-15).
    """
    os.makedirs(os.path.dirname(os.path.abspath(file_ra)), exist_ok=True)
    import xlsxwriter  # thieu thu vien thi bao that ra ngoai, khong im lang
    wb = xlsxwriter.Workbook(file_ra)
    try:
        ws = wb.add_worksheet("Sheet1")
        # Cột Caption mới mang block xuống dòng (Hook / thân / chốt+CTA):
        # bật text_wrap để Excel hiện đúng nhiều dòng, GPM vẫn đọc nguyên \n.
        try:
            c_caption = HEADER.index("Caption mới")
        except ValueError:
            c_caption = -1

        fmt_hdr = wb.add_format({
            "bold": True,
            "border": 1, "align": "center", "valign": "vcenter"
        })
        fmt_normal = wb.add_format({"valign": "top", "border": 1})
        wrap_fmt = wb.add_format({"text_wrap": True, "valign": "top", "border": 1})

        for col_idx, col_name in enumerate(HEADER):
            _o_ghi_an_toan(ws, 0, col_idx, col_name, fmt_hdr)

        for row_idx, row in enumerate(dong_ds, start=1):
            for col_idx, col_name in enumerate(HEADER):
                val = row.get(col_name, "")
                if col_idx == c_caption and isinstance(val, str) and "\n" in val:
                    ws.write_string(row_idx, col_idx, val, wrap_fmt)
                else:
                    _o_ghi_an_toan(ws, row_idx, col_idx, val, fmt_normal)

        if c_caption >= 0:
            ws.set_column(c_caption, c_caption, 60)
        ws.set_column(0, 0, 22)
        ws.set_column(3, 4, 25)
        ws.set_column(5, 5, 35)
        ws.set_column(9, 11, 30)
        ws.set_column(12, 12, 25)
    finally:
        try:
            wb.close()
        except Exception as e_close:
            if "Permission denied" in str(e_close) or isinstance(e_close, PermissionError):
                raise PermissionError(
                    f"⚠️ File Excel '{os.path.basename(file_ra)}' đang được mở bởi ứng dụng khác (Microsoft Excel)! "
                    f"Vui lòng đóng file trong Excel rồi thực hiện lại."
                ) from e_close
            raise e_close
    if not xlsx_dung_chuan_gpm(file_ra):        # tu kiem tra sau khi ghi
        raise RuntimeError(
            "File vừa ghi không đạt chuẩn GPM đọc được (thiếu sharedStrings "
            "hoặc dính inlineStr): " + file_ra)


def chuan_hoa_xlsx(file_vao, file_ra=None, ep_buoc=False):
    """Doc 1 file .xlsx (mo duoc bang openpyxl) va ghi LAI toan bo bang
    xlsxwriter, GIU NGUYEN tung gia tri o — ke ca chu GPM tu ghi vao
    ("Da dang" o cot Trạng thái danh bạ / Status master). Dung khi file bi
    openpyxl hay chinh GPM ghi lai theo kieu inlineStr ma GPM khong doc duoc.

    file_ra mac dinh = ghi de chinh file_vao (luu .bak_truoc_chuan_hoa truoc).
    Da dat san chuan va khong ep -> tra {ok:True, da_chuyen:False}, khong ghi gi.
    """
    file_ra = file_ra or file_vao
    try:
        wb = openpyxl.load_workbook(file_vao, data_only=True)
    except PermissionError as e:
        return {"ok": False, "loi": "File đang bị Excel/GPM mở khoá, không đọc được: %s" % e}
    except Exception as e:
        return {"ok": False, "loi": "Không mở được file: %s" % e}
    try:
        ws = wb.worksheets[0]
        dong = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    if not dong:
        return {"ok": False, "loi": "file trống", "file": file_vao}
    if not ep_buoc and xlsx_dung_chuan_gpm(file_vao) and \
            os.path.abspath(file_ra) == os.path.abspath(file_vao):
        return {"ok": True, "da_chuyen": False, "so_dong": len(dong),
                "so_cot": len(dong[0]), "file": os.path.abspath(file_vao)}
    if os.path.abspath(file_ra) == os.path.abspath(file_vao):
        try:
            bak = file_vao + ".bak_truoc_chuan_hoa"
            if not os.path.exists(bak):
                shutil.copyfile(file_vao, bak)
        except Exception:
            pass
    import xlsxwriter
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_ra)), exist_ok=True)
        nwb = xlsxwriter.Workbook(file_ra)
        try:
            nws = nwb.add_worksheet("Sheet1")
            for i, row in enumerate(dong):
                for j, val in enumerate(row):
                    _o_ghi_an_toan(nws, i, j, val)
        finally:
            nwb.close()
    except PermissionError as e:
        return {"ok": False, "loi": "Không ghi được (file đang mở): %s" % e}
    if not xlsx_dung_chuan_gpm(file_ra):
        return {"ok": False, "loi": "Ghi xong vẫn không đạt chuẩn GPM", "file": file_ra}
    return {"ok": True, "da_chuyen": True, "so_dong": len(dong),
            "so_cot": len(dong[0]), "file": os.path.abspath(file_ra)}


# giu ten cu de goi nguoc
ghi_master_tu_file = chuan_hoa_xlsx


def _doc_master(file_master):
    """Đọc master hiện có -> list dict theo TÊN cột (tương thích bản 18 cột cũ)."""
    wb = openpyxl.load_workbook(file_master, data_only=True)
    ws = wb.worksheets[0]
    dau = [str(c.value or "").strip() for c in ws[1]]
    vt = {t: i for i, t in enumerate(dau)}
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not any(str(x or "").strip() for x in r):
            rows.append(None)
            continue
        rows.append({t: r[i] for t, i in vt.items() if i < len(r)})
    wb.close()
    return rows


def _danh_dau_pool(store, da_gan, vung=None, loai_master=1):
    """Ghi `Da_xuat_MASTER` (hoặc `Da_xuat_MASTER_2`) cho các bài vừa gán — CHỈ đúng dòng của vùng đang xuất.

    Cùng 1 post Facebook có thể nằm ở cả 2 vùng (Content ID giống nhau, vì id
    lấy từ post_id thật), nên không được dùng tim_dong() (trả dòng đầu tiên):
    phải quét tìm dòng có Content ID trùng VÀ Vung trùng."""
    v = chuan_vung(vung if vung is not None else lay_vung())
    is_m2 = (str(loai_master) == "2" and v == US)
    cot_danh_dau = "Da_xuat_MASTER_2" if is_m2 else "Da_xuat_MASTER"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    pool = store.lay_tat_ca("CONTENT POOL")
    so = 0
    cap_nhat_list = []
    for chu_de, profile, bai in da_gan:
        cid = str(bai.get("Content ID") or "").strip()
        if not cid:
            continue
        for j, row in enumerate(pool):
            if str(row.get("Content ID") or "").strip() != cid:
                continue
            if vung_cua_bai(row) != v:
                continue
            row = dict(row)
            row[cot_danh_dau] = f"{now} | {profile}"
            cap_nhat_list.append((j, row))
            pool[j] = row
            so += 1
            break

    if cap_nhat_list:
        if hasattr(store, "cap_nhat_nhieu_dong"):
            store.cap_nhat_nhieu_dong("CONTENT POOL", cap_nhat_list)
        else:
            for j, row in cap_nhat_list:
                store.cap_nhat_dong("CONTENT POOL", j, row)
    return so


# ------------------------------------------------- bo sung du lieu dong cu
def bo_sung_dong_co_bai(dong_ds, store=None, vung=None):
    """Điền lại đủ reel_path / article_url / anh_path cho dòng ĐÃ có bài.
    Nếu dòng có ảnh nhưng chưa có reel trên đĩa, tự động tạo reel và gán vào luôn.
    Trả về số dòng được bổ sung reel.
    """
    import luong_b
    import reel
    enr = {str(r.get("Content ID") or "").strip(): r
           for r in luong_b.lay_danh_sach_hoan_thanh(vung=vung)}
    so_reel = 0
    for row in dong_ds:
        cid = str(row.get("Content ID") or "").strip()
        if not cid or str(row.get("Caption mới") or "").strip() == GIA_TRI_CHO_BAI:
            continue
        b = enr.get(cid)
        goi = b.get("goi_fb") if b else {}

        # 1. Đường dẫn ảnh
        anh = str(row.get("Đường dẫn ảnh") or "").strip()
        if not anh:
            anh = (goi.get("anh_path") if goi else None) or (b.get("Media") if b else None) or ""
        if anh:
            if not os.path.isabs(anh):
                anh = os.path.normpath(os.path.join(DUONG_DAN, anh))
            row["Đường dẫn ảnh"] = anh

        # 2. Đường dẫn reel
        r_path = str(row.get("Đường dẫn reel") or "").strip()
        if not r_path or not os.path.isfile(r_path):
            r_disk = reel.duong_dan_reel(cid)
            if r_disk and os.path.isfile(r_disk):
                r_path = r_disk
            elif anh and os.path.isfile(anh):
                # Tự động tạo reel nếu chưa có
                try:
                    res_r = reel.tao_reel(anh, co_nhac=True, ten_dau_ra=cid)
                    if res_r.get("success"):
                        r_path = res_r.get("video_path") or ""
                except Exception:
                    pass
        if r_path:
            if not os.path.isabs(r_path):
                r_path = os.path.normpath(os.path.join(DUONG_DAN, r_path))
            row["Đường dẫn reel"] = r_path
            so_reel += 1

        # 3. Link bài báo
        if not str(row.get("Link bài báo") or "").strip():
            row["Link bài báo"] = (goi.get("article_url") if goi else None) or (b.get("Article URL") if b else None) or ""

    return so_reel


# ----------------------------------------------------------------- 1. vòng mới
def xuat_master(store=None, ghi_dau=True, file_ra=None, danh_ba=None, vung=None, loai_master=1):
    """Vòng gán MỚI cho 1 vùng: rút hết bài đã gán, chia lại, ghi đè master của vùng đó.

    `vung`: 'us' | 'global' — mặc định = vùng đang chọn trên giao diện.
    `loai_master`: 1 (Master hiện tại) | 2 (Master mới US).
    Danh bạ, file master và kho bài đều lấy theo vùng; không bao giờ dùng chéo."""
    v = chuan_vung(vung if vung is not None else lay_vung())
    if store is None:
        from google_sheets import lay_store
        store = lay_store()
    danh_ba = danh_ba if danh_ba is not None else doc_danh_ba(vung=v, loai_master=loai_master)
    kho = lay_kho_cho(store, vung=v, loai_master=loai_master)

    dong_ds, da_gan, canh_bao = [], [], []
    for i, p in enumerate(danh_ba):
        stt = i + 1
        cd_p = chuan_hoa_chu_de(p["Chu de"])
        bai = _lay_bai_phu_hop(kho, p["Chu de"]) if du_chien(p["Trang thai"]) else None
        if bai:
            da_gan.append((cd_p, p["PROFILE"], bai))
            dong_ds.append(_dong_co_bai(p, bai, stt))
        else:
            if not du_chien(p["Trang thai"]):
                canh_bao.append(f"Profile {p['PROFILE']} Trạng thái '{p['Trang thai']}' -> để trống")
                ly_do = f"KHÔNG LIVE - {p['Trang thai']}"
            else:
                ly_do = "CHỜ BÀI"
            dong_ds.append(_dong_trong(p, stt, ly_do))

    cho = {cd: len(ds) for cd, ds in kho.items() if ds}
    for cd, n in cho.items():
        canh_bao.append(f"Chủ đề '{cd}' còn {n} bài HOÀN THÀNH chưa có profile nhận -> đợi lần sau")

    file_ra = file_ra or duong_dan_master(v, loai_master=loai_master)
    _ghi_master(file_ra, dong_ds)
    so_danh_dau = _danh_dau_pool(store, da_gan, vung=v, loai_master=loai_master) if ghi_dau else 0
    return {"ok": True, "file": file_ra, "vung": v, "ten_vung": TEN_VUNG[v],
            "loai_master": int(loai_master),
            "tong_dong": len(dong_ds),
            "so_bai_xuat": len(da_gan), "so_danh_dau": so_danh_dau,
            "cho_lan_sau": cho, "canh_bao": canh_bao}


# ----------------------------------------------------------------- 2. vá CHỜ BÀI
def va_master(store=None, file_master=None, danh_ba=None, ghi_dau=True, file_ra=None,
              vung=None, loai_master=1):
    """GIỮ NGUYÊN mọi dòng đã có bài; chỉ điền bài mới vào dòng đang CHỜ BÀI.

    Không bao giờ rút bài ra -> bấm nhiều lần không mất bài, mỗi lần lấp thêm.
    `vung`: 'us' | 'global' — master + danh bạ + kho bài đều của vùng đó.
    `loai_master`: 1 (Master hiện tại) | 2 (Master mới US).
    """
    v = chuan_vung(vung if vung is not None else lay_vung())
    if store is None:
        from google_sheets import lay_store
        store = lay_store()
    file_master = file_master or duong_dan_master(v, loai_master=loai_master)
    if not os.path.isfile(file_master):
        raise FileNotFoundError(f"Chưa có {os.path.basename(file_master)} — "
                                f"hãy bấm 'Xuất MASTER' cho vùng {TEN_VUNG[v]} (Master {loai_master}) trước.")
    danh_ba = danh_ba if danh_ba is not None else doc_danh_ba(vung=v, loai_master=loai_master)
    cu = _doc_master(file_master)

    if len(cu) != len(danh_ba):
        raise ValueError("Master (%d dòng) lệch với danh bạ (%d dòng) -> không dám vá. "
                         "Hãy bấm 'Xuất MASTER' để dựng lại file." % (len(cu), len(danh_ba)))
    lech = [(i + 1, str(cu[i].get("PROFILE") or "")[:20], danh_ba[i]["PROFILE"])
            for i in range(len(danh_ba))
            if cu[i] and str(cu[i].get("PROFILE") or "").strip() != danh_ba[i]["PROFILE"]]
    if lech:
        raise ValueError("PROFILE dòng %s không khớp danh bạ -> không dám vá." % str(lech[:3]))

    kho = lay_kho_cho(store, vung=v, loai_master=loai_master)
    da_giu = 0
    dong_ds, da_gan, canh_bao = [], [], []
    for i, p in enumerate(danh_ba):
        stt = i + 1
        row_cu = cu[i] or {}
        caption = str(row_cu.get("Caption mới") or "").strip()
        if du_chien(p["Trang thai"]) and caption and caption != GIA_TRI_CHO_BAI:
            da_giu += 1                                   # giữ y nguyên, không đụng
            dong_ds.append({t: row_cu.get(t, "") for t in HEADER})
            dong_ds[-1]["PROFILE"] = p["PROFILE"]
            dong_ds[-1]["Nguồn"] = p["Nguon page"]
            dong_ds[-1]["Tên Page"] = p["Ten page"]
            dong_ds[-1]["Chủ đề"] = p["Chu de"]
            dong_ds[-1]["STT"] = stt
            continue
        chu_de_can_gan = str(row_cu.get("KEY") or row_cu.get("Chủ đề") or p.get("Chu de") or "").strip()
        cd_p = chuan_hoa_chu_de(chu_de_can_gan)
        bai = _lay_bai_phu_hop(kho, chu_de_can_gan) if du_chien(p["Trang thai"]) else None
        if bai:
            da_gan.append((cd_p, p["PROFILE"], bai))
            dong_ds.append(_dong_co_bai(p, bai, stt))
        else:
            ly_do = f"KHÔNG LIVE - {p['Trang thai']}" if not du_chien(p["Trang thai"]) else "CHỜ BÀI"
            dong_ds.append(_dong_trong(p, stt, ly_do, key_override=chu_de_can_gan))
            if not du_chien(p["Trang thai"]):
                canh_bao.append(f"Profile {p['PROFILE']} Trạng thái '{p['Trang thai']}' -> không được cấp bài")

    con_trong = sum(1 for r in dong_ds if str(r.get("Caption mới") or "").strip() == GIA_TRI_CHO_BAI)
    cho = {cd: len(ds) for cd, ds in kho.items() if ds}
    for cd, n in cho.items():
        canh_bao.append(f"Chủ đề '{cd}' còn {n} bài HOÀN THÀNH chưa gán được -> đợi lần sau")

    # Kiểm tra vùng của các dòng ĐANG GIỮ: master của vùng này không được chứa
    # bài của vùng khác (dấu vết của file master cũ dựng trước khi tách vùng).
    v_cua_bai = {}
    for row in store.lay_tat_ca("CONTENT POOL"):
        cid_r = str(row.get("Content ID") or "").strip()
        if cid_r:
            v_cua_bai.setdefault(cid_r, set()).add(vung_cua_bai(row))
    sai_vung = []
    for i, r in enumerate(dong_ds):
        cid_r = str(r.get("Content ID") or "").strip()
        if not cid_r or str(r.get("Caption mới") or "").strip() == GIA_TRI_CHO_BAI:
            continue
        cac_vung = v_cua_bai.get(cid_r) or set()
        if cac_vung and v not in cac_vung:
            sai_vung.append(f"dòng {i + 2}: {cid_r} thuộc "
                            f"{'/'.join(sorted(cac_vung))}")

    file_ra = file_ra or file_master
    so_reel_vo = bo_sung_dong_co_bai(dong_ds, store, vung=v)
    _ghi_master(file_ra, dong_ds)
    so_danh_dau = _danh_dau_pool(store, da_gan, vung=v, loai_master=loai_master) if ghi_dau else 0
    kq = {"ok": True, "file": file_ra, "vung": v, "ten_vung": TEN_VUNG[v],
          "loai_master": int(loai_master),
          "tong_dong": len(dong_ds),
          "giu_nguyen": da_giu, "so_vao_moi": len(da_gan), "so_danh_dau": so_danh_dau,
          "so_reel_bo_sung": so_reel_vo,
          "con_cho_bai": con_trong, "cho_lan_sau": cho, "canh_bao": canh_bao}
    if sai_vung:
        kq["sai_vung"] = sai_vung
        kq["canh_bao"] = canh_bao + [
            f"⚠ {len(sai_vung)} dòng đang giữ là bài của vùng khác (không phải "
            f"{TEN_VUNG[v]}) — nên bấm 'Xuất MASTER' để dựng lại: "
            + " ; ".join(sai_vung[:5])]
    return kq


# ----------------------------------------------------------------- 3. đổi format cột
def doi_format_master(file_master=None, file_ra=None, vung=None):
    """Đọc master bản cũ (18 cột, có Cảm xúc/Bình luận/Chia sẻ) -> ghi bản 15 cột.

    Giữ nguyên 100% bài đã gán: không đụng Content Pool, không đổi Da_xuat_MASTER.
    """
    file_master = file_master or duong_dan_master(vung)
    cu = _doc_master(file_master)
    if not cu:
        raise ValueError("File master rỗng")
    dong_ra = []
    for r in cu:
        dong_ra.append({t: r.get(t, "") for t in HEADER})
    file_ra = file_ra or file_master
    _ghi_master(file_ra, dong_ra)
    return {"ok": True, "file": file_ra, "tong_dong": len(dong_ra)}


if __name__ == "__main__":
    import json
    import sys
    dry = "--dry" in sys.argv
    vung_cli = "us"
    for i, a in enumerate(sys.argv):
        if a == "--vung" and i + 1 < len(sys.argv):
            vung_cli = sys.argv[i + 1]
    kq = xuat_master(ghi_dau=not dry, vung=vung_cli,
                     file_ra=os.path.join(DUONG_DAN, "du_lieu_exel", "MASTER_TEST.xlsx") if dry else None)
    print(json.dumps(kq, ensure_ascii=False, indent=2)[:3000])
