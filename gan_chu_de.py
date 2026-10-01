# -*- coding: utf-8 -*-
"""
Module GAN_CHU_DE — Phân loại bài viết vào chủ đề (NFL, NBA, MLB, ...).

Quy tắc:
1. KEY của bài khớp (chứa từ khoá trong `chu_de_key.json`) → dùng chủ đề đó ngay.
2. Không có KEY hoặc không khớp → gọi AI phân loại theo nội dung.

Bảng map lưu trong `chu_de_key.json` (tự tạo dần theo thời gian).
"""

import json
import os
import re

from config import DUONG_DAN
from ai_client import goi_ai

FILE_MAP = os.path.join(DUONG_DAN, "chu_de_key.json")

# Chủ đề mặc định khi AI trả về thứ lạ / không nhận diện được
CHU_DE_MAC_DINH = "Fake News"

_cached_map = None


def nap_map_chu_de(force=False) -> dict:
    """Nạp bảng map KEY→chủ đề từ chu_de_key.json (cache trong tiến trình)."""
    global _cached_map
    if _cached_map is not None and not force:
        return _cached_map
    if os.path.isfile(FILE_MAP):
        try:
            with open(FILE_MAP, "r", encoding="utf-8") as f:
                _cached_map = json.load(f)
        except (json.JSONDecodeError, OSError):
            _cached_map = {}
    else:
        _cached_map = {}
    return _cached_map


def danh_sach_chu_de() -> list:
    """Danh sách các chủ đề đã cấu hình (theo thứ tự trong file)."""
    m = nap_map_chu_de()
    ds = m.get("danh_sach_chu_de") or []
    # Luôn bổ sung những chủ đề có trong map_key nhưng thiếu trong danh_sach
    for cd in (m.get("map_key") or {}).keys():
        if cd not in ds:
            ds.append(cd)
    return ds


def _khớp_từ_khoá(key_low: str, tu_low: str) -> bool:
    """Kiểm tra từ khóa `tu_low` có trong `key_low` không (đúng từ, không match con).

    - Nếu từ khóa ≥ 4 ký tự: match đơn giản (chứa chuỗi con).
    - Nếu từ khóa < 4 ký tự: match nguyên từ (word boundary, hoặc bắt đầu/kết thúc chuỗi).
    """
    if not tu_low or not key_low:
        return False
    if len(tu_low) >= 4:
        return tu_low in key_low
    # Từ ngắn (< 4 ký tự): match nguyên từ (bị cô lập bởi dấu cách/đầu/cuối)
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(tu_low)}(?![a-z0-9])", key_low))


def gan_chu_de_tu_key(key: str) -> str | None:
    """Tìm chủ đề khớp từ khoá KEY (không phân biệt hoa/thường, match từ).

    Ưu tiên: khớp thẳng tên chủ đề -> bảng `key_alias` trong chu_de_key.json
    (VD "WNBA" -> "NBA", "Nascar" -> "NASCAR") -> match từ khoá của chủ đề.
    """
    if not key:
        return None
    m = nap_map_chu_de()
    map_key = m.get("map_key") or {}
    key_low = str(key).strip().lower()
    if not key_low:
        return None
    # 1. KEY trùng tên chủ đề (bỏ dấu cách: 'Nascar' -> 'NASCAR', 'pga golf')
    for chu_de in map_key:
        if chu_de.strip().lower().replace(" ", "") == key_low.replace(" ", ""):
            return chu_de
    # 2. Bảng alias KEY -> chủ đề (key_alias: {"WNBA": "NBA", ...} — thêm trong JSON)
    for k_alias, chu_de in (m.get("key_alias") or {}).items():
        if str(k_alias).strip().lower().replace(" ", "") == key_low.replace(" ", ""):
            if chu_de in map_key:
                return chu_de
    # 3. Match từ khoá như cũ
    for chu_de, ds_tu in map_key.items():
        for tu in ds_tu:
            tu_low = str(tu).strip().lower()
            if _khớp_từ_khoá(key_low, tu_low):
                return chu_de
    return None


def _chuan_hoa_chu_de(tra_ve: str) -> str:
    """Ép kết quả AI về 1 chủ đề hợp lệ trong danh sách."""
    tra_ve = str(tra_ve or "").strip()
    if not tra_ve:
        return CHU_DE_MAC_DINH
    ds = danh_sach_chu_de()
    # Đúng tên (không phân biệt hoa/thường)
    for cd in ds:
        if cd.lower() == tra_ve.lower():
            return cd
    # Gần đúng: tên chứa chủ đề hoặc ngược lại
    for cd in ds:
        cd_low = cd.lower()
        if cd_low in tra_ve.lower() or tra_ve.lower() in cd_low:
            return cd
    # Tách chủ đề chính (bỏ phần phía sau dấu /, -, :)
    phan_chinh = re.split(r"[/\-:,|]", tra_ve)[0].strip()
    for cd in ds:
        if cd.lower() == phan_chinh.lower():
            return cd
    return CHU_DE_MAC_DINH


def gan_chu_de_tu_ai(noi_dung: str) -> str:
    """Gọi AI phân loại nội dung bài viết vào 1 trong các chủ đề đã cấu hình."""
    ds = danh_sach_chu_de()
    ds_text = ", ".join(ds)
    he_thong = (
        "Phân loại tin tức theo CHỦ ĐỀ CHÍNH của bài (không phải từ lẻ xuất hiện "
        "tình cờ). Đọc nội dung và trả về đúng 1 chủ đề trong danh sách: "
        f"{ds_text}. Chỉ trả tên chủ đề, không giải thích."
    )
    nguoi_dung = f"{_chuan_hoa_noi_dung(noi_dung)[:2500]}"
    try:
        ket_qua = goi_ai(he_thong, nguoi_dung, nhiet_do=0.1, toi_da_tu=20,
                         tat_reasoning=True)
    except Exception:
        return CHU_DE_MAC_DINH
    return _chuan_hoa_chu_de(ket_qua)


def gan_chu_de_cho_bai_khong_ai(key: str, noi_dung: str) -> str | None:
    """Gán nhanh chủ đề KHÔNG gọi AI.

    Luật (2026-09-14): bài lấy từ kho nguồn → KEY là tên chủ đề/file, GIỮ NGUYÊN.
    Chỉ bài không có KEY (nhập link ngoài) mới dò từ khoá trong nội dung.
    """
    k = str(key or "").strip()
    if k:
        return k
    if noi_dung:
        chu_de = _tim_chu_de_trong_noi_dung(noi_dung)
        if chu_de:
            return chu_de
    return None


# Caption hay bị thay chữ Latin bằng ký tự nhìn giống (Cyrillic/Greek) để lách
# Facebook: "Icelaпd" (п), "Brυssels" (υ)... Quy đổi về ASCII trước khi match.
_HOMOGLYPH = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "к": "k", "і": "i", "ѕ": "s", "ց": "c", "ո": "h", "ԁ": "d",
    "п": "n", "т": "t", "м": "m", "л": "n", "ד": "d", "օ": "o",
    "α": "a", "β": "b", "ε": "e", "ν": "v", "ο": "o", "ρ": "p",
    "υ": "u", "ω": "w", "т": "t",
})


def _chuan_hoa_noi_dung(text: str) -> str:
    """Lowercase trước rồi mới quy homoglyph (caption đa số viết HOA)."""
    return str(text or "").lower().translate(_HOMOGLYPH)


def _diem_tu_khoa_theo_chu_de(noi_dung_low: str) -> dict:
    """Đếm số từ khoá KHÁC NHAU khớp với nội dung, theo từng chủ đề."""
    m = nap_map_chu_de()
    map_key = m.get("map_key") or {}
    diem = {}
    for chu_de, ds_tu in map_key.items():
        khop = set()
        for tu in ds_tu:
            tu_low = str(tu).strip().lower()
            if tu_low and _khớp_từ_khoá(noi_dung_low, tu_low):
                khop.add(tu_low)
        if khop:
            diem[chu_de] = khop
    return diem


def _tim_chu_de_trong_noi_dung(noi_dung: str, so_khop_toi_thieu: int = 2) -> str | None:
    """Tìm chủ đề từ khoá trong nội dung (không cần AI).

    Chỉ chấp nhận chủ đề thắng khi có >= `so_khop_toi_thieu` từ khoá phân biệt
    cùng khớp. Trước đây chỉ cần 1 từ là ăn -> 'political heavyweights' trong bài
    chính trị bị bắt keyword 'heavyweight' và gán nhầm thành UFC/Boxing.
    """
    if not noi_dung:
        return None
    noi_dung_low = _chuan_hoa_noi_dung(noi_dung)
    diem = _diem_tu_khoa_theo_chu_de(noi_dung_low)
    if not diem:
        return None
    chu_de = max(diem, key=lambda c: len(diem[c]))
    if len(diem[chu_de]) >= max(1, so_khop_toi_thieu):
        return chu_de
    return None


def gan_chu_de_cho_bai(key: str, noi_dung: str) -> str:
    """Gán chủ đề cho 1 bài.

    Luật (2026-09-14): bài lấy từ kho nguồn có KEY → chủ đề = chính KEY (giữ
    nguyên tên, mỗi KEY một file Excel). Chỉ bài KHÔNG KEY (nhập link ngoài)
    mới tự bắt chủ đề: từ khoá trong nội dung trước, rồi tới AI.
    """
    # 1. KEY = chủ đề
    k = str(key or "").strip()
    if k:
        return k

    # 2. Không KEY: từ khóa trong nội dung (cần >= 2 từ khớp để tránh nhầm)
    chu_de = _tim_chu_de_trong_noi_dung(noi_dung)
    if chu_de:
        return chu_de

    # 3. AI phân loại
    return gan_chu_de_tu_ai(noi_dung or "")


if __name__ == "__main__":
    # test nhanh: python gan_chu_de.py
    print("Danh sách chủ đề:", danh_sach_chu_de())
    for key in ["NFL", "Patrick Mahomes", "Lakers", "UFC", "", "nascar cup"]:
        print(f"KEY={key!r:20} -> {gan_chu_de_tu_key(key)}")
