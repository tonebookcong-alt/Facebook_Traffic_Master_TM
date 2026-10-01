# -*- coding: utf-8 -*-
"""Vùng dữ liệu (US / GLOBAL) — nền tảng phân tách 2 kho nguồn cào.

Mọi chỗ cần biết "đang làm việc với vùng nào" đều đi qua module này, không
tham số hoá dây chuyền khắp nơi:

  * `lay_vung()`      : vùng HIỆN ĐANG CHỌN trên giao diện (persist qua restart)
  * `dat_vung(v)`     : công tắc vùng — webui gọi khi người dùng bấm chuyển
  * `chuan_vung(v)`   : chuẩn hoá mọi cách gọi về 'us' | 'global' (mặc định 'us')
  * `duong_dan_nguon` : kho nguồn cào riêng từng vùng
  * `duong_dan_danh_ba`: danh bạ UID riêng từng vùng (chạy master)
  * `duong_dan_master` : file MASTER_DANG_BAI_<VUNG>.xlsx
  * `thu_muc_excel`    : du_lieu_exel\\us\\ và du_lieu_exel\\global\\

Quy tắc dữ liệu: MỖI BÀI trong Content Pool mang cột "Vung" ('us'|'global') ghi
lại nó được cào từ kho nguồn nào. Vùng của bài QUYẾT ĐỊNH bài báo đăng lên
website nào (web='us' → primevista24, web='global' → dailyreveal281) và chỉ
được xuất vào master/excel của đúng vùng đó. Chống trùng cũng tính riêng theo
vùng (2 vùng khác nguồn nên không va chạm).

File vùng hiện tại: du_lieu_traffic\\vung_hien_tai.txt (chỉ 'us' hoặc 'global'),
mặc định 'us' — giữ nguyên hành vi cũ cho mọi luồng chưa kịp truyền vùng.
"""
import json
import os
import threading

DUONG_DAN = os.path.dirname(os.path.abspath(__file__))

US = "us"
GLOBAL = "global"
CAC_VUNG = (US, GLOBAL)

TEN_VUNG = {US: "🇺🇸 US", GLOBAL: "🌍 GLOBAL"}
TEN_NGAN = {US: "US", GLOBAL: "GLOBAL"}

DAU_CACH = {
    US: "🇺🇸",
    GLOBAL: "🌍",
}

# ------------------------------------------------------------------ đường dẫn
DU_LIEU_TRAFFIC = os.path.join(DUONG_DAN, "du_lieu_traffic")
DU_LIEU_EXEL = os.path.join(DUONG_DAN, "du_lieu_exel")
NGOAI_TOOL = os.path.join(DUONG_DAN, "ngoài tool")

FILE_VUNG = os.path.join(DU_LIEU_TRAFFIC, "vung_hien_tai.txt")

FILES_NGUON = {
    US: os.path.join(DU_LIEU_TRAFFIC, "nguon_us.json"),
    GLOBAL: os.path.join(DU_LIEU_TRAFFIC, "nguon_global.json"),
}
FILES_DANH_BA = {
    US: os.path.join(NGOAI_TOOL, "danh_sach_uid.xlsx"),
    GLOBAL: os.path.join(NGOAI_TOOL, "danh_sach_uid_global.xlsx"),
}
FILES_MASTER = {
    US: os.path.join(DU_LIEU_EXEL, "MASTER_DANG_BAI_US.xlsx"),
    GLOBAL: os.path.join(DU_LIEU_EXEL, "MASTER_DANG_BAI_GLOBAL.xlsx"),
}

# Master 2 (dành riêng cho US khi có thêm danh bạ thứ 2)
FILES_DANH_BA_2 = {
    US: os.path.join(NGOAI_TOOL, "danh_sach_uid_2.xlsx"),
    GLOBAL: os.path.join(NGOAI_TOOL, "danh_sach_uid_global.xlsx"),
}
FILES_MASTER_2 = {
    US: os.path.join(DU_LIEU_EXEL, "MASTER_DANG_BAI_US_2.xlsx"),
    GLOBAL: os.path.join(DU_LIEU_EXEL, "MASTER_DANG_BAI_GLOBAL.xlsx"),
}

# File cũ (trước khi tách vùng) — chỉ để tham chiếu lúc di trú, code không đọc.
FILE_SOURCE_CU = os.path.join(DU_LIEU_TRAFFIC, "source_config.json")
FILE_MASTER_CU = os.path.join(DU_LIEU_EXEL, "MASTER_DANG_BAI.xlsx")

_KHOA = threading.RLock()
_vung_cache = None


# ------------------------------------------------------------------ chuẩn hoá
def chuan_vung(gia_tri, mac_dinh: str = US) -> str:
    """'US'/'us'/'My'/'Mỹ' → 'us'; 'GLOBAL'/'the giới'/'toàn cầu' → 'global'.

    Giá trị lạ/rỗng → `mac_dinh` (mặc định 'us' để mọi luồng cũ chạy y như trước).
    """
    v = str(gia_tri or "").strip().lower()
    if v in CAC_VUNG:
        return v
    if v in ("us", "mỹ", "my", "nuoc my", "hoa ky", "hk", "🇺🇸"):
        return US
    if v in ("global", "toan cau", "toàn cầu", "the gioi", "thế giới", "g", "🌍"):
        return GLOBAL
    return mac_dinh


# --------------------------------------------------------- vùng hiện chọn
def lay_vung() -> str:
    """Vùng đang chọn trên giao diện (đọc file, cache trong bộ nhớ tiến trình)."""
    global _vung_cache
    with _KHOA:
        if _vung_cache is None:
            try:
                with open(FILE_VUNG, "r", encoding="utf-8") as f:
                    _vung_cache = chuan_vung(f.read())
            except OSError:
                _vung_cache = US
        return _vung_cache


def dat_vung(gia_tri) -> str:
    """Chuyển vùng hiện tại. Trả về vùng đã chuẩn hoá."""
    global _vung_cache
    v = chuan_vung(gia_tri)
    with _KHOA:
        os.makedirs(DU_LIEU_TRAFFIC, exist_ok=True)
        with open(FILE_VUNG, "w", encoding="utf-8") as f:
            f.write(v)
        _vung_cache = v
    return v


def ten_vung(gia_tri=None) -> str:
    return TEN_VUNG[chuan_vung(gia_tri or lay_vung())]


def dau_vung(gia_tri=None) -> str:
    return DAU_CACH[chuan_vung(gia_tri or lay_vung())]


# ------------------------------------------------------------------ đường dẫn
def duong_dan_nguon(gia_tri=None) -> str:
    """Kho nguồn cào của vùng: nguon_us.json / nguon_global.json."""
    return FILES_NGUON[chuan_vung(gia_tri or lay_vung())]


def duong_dan_danh_ba(gia_tri=None, loai_master=1) -> str:
    v = chuan_vung(gia_tri or lay_vung())
    if str(loai_master) == "2" and v == US:
        p2 = FILES_DANH_BA_2[US]
        if not os.path.exists(p2):
            p2_alt = os.path.join(NGOAI_TOOL, "danh_sach_uid_us_2.xlsx")
            if os.path.exists(p2_alt):
                return p2_alt
        return p2
    return FILES_DANH_BA[v]


def duong_dan_master(gia_tri=None, loai_master=1) -> str:
    v = chuan_vung(gia_tri or lay_vung())
    if str(loai_master) == "2" and v == US:
        return FILES_MASTER_2[US]
    return FILES_MASTER[v]


def thu_muc_excel(gia_tri=None) -> str:
    """Thư mục chứa san_sang_*.xlsx của vùng (tự tạo nếu chưa có)."""
    fp = os.path.join(DU_LIEU_EXEL, chuan_vung(gia_tri or lay_vung()))
    os.makedirs(fp, exist_ok=True)
    return fp


def vung_cua_bai(dong: dict) -> str:
    """Đọc cột Vung của 1 dòng Content Pool (dòng cũ chưa có → 'us')."""
    return chuan_vung((dong or {}).get("Vung") or (dong or {}).get("vung"))


def dung_vung(dong: dict, gia_tri=None) -> bool:
    """Bài này có thuộc vùng `gia_tri` không (mặc định = vùng đang chọn).

    Dòng chưa có cột Vung được coi là bài US — toàn bộ kho trước 15/09 là US.
    """
    return vung_cua_bai(dong) == chuan_vung(gia_tri or lay_vung())


def doc_kho_nguon(gia_tri=None) -> list:
    """Đọc list nguồn [{KEY, 'Facebook nguồn', 'Nhân vật gợi ý', Vung}] của vùng."""
    fp = duong_dan_nguon(gia_tri)
    try:
        with open(fp, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return []
    return doc if isinstance(doc, list) else []


def thong_ke_nguon(gia_tri=None) -> dict:
    """{vung, file, so_dong, so_key, that_bai} — cho UI/CLI báo cáo."""
    v = chuan_vung(gia_tri or lay_vung())
    ds = doc_kho_nguon(v)
    return {
        "vung": v,
        "ten": TEN_VUNG[v],
        "file": os.path.basename(duong_dan_nguon(v)),
        "so_dong": len(ds),
        "so_key": len({str(r.get("KEY") or "").strip() for r in ds if str(r.get("KEY") or "").strip()}),
    }


def danh_sach_key(gia_tri=None) -> list:
    """Các KEY (chủ đề) có trong kho nguồn của vùng, theo thứ tự xuất hiện."""
    seen = []
    for r in doc_kho_nguon(gia_tri):
        k = str(r.get("KEY") or "").strip()
        if k and k not in seen:
            seen.append(k)
    return seen
