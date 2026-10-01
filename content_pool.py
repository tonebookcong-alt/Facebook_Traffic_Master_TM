# -*- coding: utf-8 -*-
"""
Content Pool — kho bài viết đã thu thập, chống trùng + vòng đời trạng thái.

Trạng thái: NEW → READY → LOCKED → PROCESSING → WEB_POSTED → FB_POSTED
           → DONE  /  ERROR  /  HET_HAN

Các hàm chính:
  - chuan_hoa_text(): chuẩn hoá caption để so trùng
  - chong_trung():    lọc bài đã có trong pool (post_id + hash caption)
  - them_content():   thêm bài mới (status NEW)
  - danh_dau_het_han(): content quá N ngày → HET_HAN
  - chon_content():   logic chọn content cho 1 Page (Luồng B)
"""

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta

from config import load_config
from google_sheets import lay_store
from vung import chuan_vung, lay_vung, vung_cua_bai


# ===================================================================
# Chuẩn hoá + chống trùng
# ===================================================================
def chuan_hoa_text(text: str) -> str:
    """Caption 'Chiefs vs Bucs!!!' và 'chiefs  vs bucs' phải ra cùng 1 hash.

    - NFKC: gỡ chữ in đậm/toán học (𝐂𝐨́ → Có), full-width, ligature...
      Cùng 1 bài Facebook cào 2 lần có thể render kiểu chữ khác nhau.
    - Bỏ link, emoji, dấu câu; gom khoảng trắng; chữ thường."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.lower()
    t = re.sub(r"https?://\S+", "", t)          # bỏ link
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", t)  # bỏ emoji
    t = re.sub(r"[^\w\s]", " ", t)              # bỏ dấu câu (giữ chữ có dấu)
    t = re.sub(r"\s+", " ", t)                  # gom khoảng trắng
    return t.strip()


def hash_caption(text: str) -> str:
    return hashlib.md5(chuan_hoa_text(text).encode("utf-8")).hexdigest()


# Độ dài tối thiểu (ký tự, sau chuẩn hoá) để coi "bản ngắn nằm trong bản dài"
# là trùng — tránh 2 bài khác nhau mà câu ngắn lại nằm trong câu dài.
NGUONG_CHUA = 40

# Dung sai ở ĐUÔI bản ngắn khi so prefix: Facebook cắt bản thu gọn GIỮA TỪ
# ('...mình dâ… Xem thêm' vs '...mình dâng trào...') nên không so khớp tuyệt đối.
DUNG_SAI_CAT = 5

# Ngưỡng đủ dài ở PHẨN ĐẦU GIỐNG NHAU khi 2 bai cao ra cung post_id gia
# ('bai_' + md5(caption[:80])). id giong nhau = 80 ky tu DAU giong nhau tung
# byte; sau chuan hoa (mo dau chu, xoa dau câu) do dai chung con ngan hon,
# nen chan o 40 ky tu de khong nhan bam 2 bai thuc su khac nhau.
_NGUONG_PREFIX_GIA = 40


# Các nhãn "Xem thêm / Ẩn bớt" Facebook dán vào ĐẦU hoặc CUOI caption.
# Nguon dung NGON NGU cua chinh Facebook (US = 'See more', VN = 'Xem thêm')
# nen cung 1 bai co the duoc cao 2 lan ra 2 dau khac nhau -> if chi cat
# 'xem them' thi 2 ban that su cung mot bai van bi tinh la 2 bai (trung dong
# trong pool, AI xu ly lai tu dau). Cat ca 2 dau, khong hoa mang chu viet.
_NHAN_CAT = ("xem thêm", "xem them", "ẩn bớt", "an bot",
             "see more", "see less", "view more", "view less")


def _bo_xem_them(s: str) -> str:
    """Cat don nhieu lan cac nhan 'Xem thêm'/'See more'/'Ẩn bớt'... o CA HAI
    dau caption da chuan hoa (chi cat khi no nam ngoai cung)."""
    s = (s or "").strip()
    changed = True
    while changed:
        changed = False
        for n in _NHAN_CAT:
            if len(s) > len(n) + NGUONG_CHUA and s.endswith(n):
                s = s[: -len(n)].strip()
                changed = True
            elif len(s) > len(n) + NGUONG_CHUA and s.startswith(n):
                s = s[len(n):].strip()
                changed = True
    return s


def _la_cung_bai(moi: str, cu: str) -> bool:
    """2 caption đã chuẩn hoá có phải cùng 1 bài không?

    Facebook cào 2 lần có thể ra bản thu gọn ('... Xem thêm') và bản đầy đủ
    ('Ẩn bớt') — bản ngắn là tiền tố (đoạn đầu) của bản dài."""
    if not moi or not cu:
        return False
    if moi == cu:
        return True
    ngan, dai = (moi, cu) if len(moi) < len(cu) else (cu, moi)
    if len(ngan) < NGUONG_CHUA:
        return False
    ngan = _bo_xem_them(ngan)
    if len(ngan) < NGUONG_CHUA:
        return False
    khop = 0
    for i in range(min(len(ngan), len(dai))):
        if ngan[i] != dai[i]:
            break
        khop += 1
    # khớp từ đầu, khác nhau chỉ ở đuôi bản ngắn (chỗ Facebook cắt '… Xem thêm')
    return khop >= len(ngan) - DUNG_SAI_CAT and khop >= NGUONG_CHUA


def _prefix_chung(a: str, b: str) -> int:
    """Số ký tự đầu GIỐNG NHAU (đã chuẩn hoá) giữa 2 caption."""
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _trung_id_gia(pid: str, id_cu: str, text_moi: str, caption_cu: str) -> bool:
    """post_id dạng 'bai_<md5 80 ky tu dau>' khop nhau = bang chung 2 caption co
    80 ky tu DAU giong het nhau. Chi du ket luan cung mot bai khi phan dau
    giống nhau THAT SU dai (>= _NGUONG_PREFIX_GIA) — tranh 2 bai khac nhau
    dung cung template mo dau.

    (Facebook cat caption khac nhau theo ngon ngu UI luong cao: ban tieng Viet
    ket '... ẩn bớt', ban tieng Anh ket '... see more' -> _la_cung_bai so
    nguyen van co the bo sot.)"""
    if not pid or not id_cu or pid != id_cu or not pid.startswith("bai_"):
        return False
    a = _bo_xem_them(chuan_hoa_text(text_moi))
    b = _bo_xem_them(chuan_hoa_text(caption_cu))
    return _prefix_chung(a, b) >= _NGUONG_PREFIX_GIA


class KiemTraPool:
    """Tra cứu nhanh 'bài này đã có trong kho chưa?' khi đang cào.

    Nạp 1 lần: tập Content ID thật + tập caption đã chuẩn hoá (kèm con của
    bài ĐANG cào so với kho không cần chính xác tuyệt đối — dùng cùng quy tắc
    `_la_cung_bai` như chong_trung để 2 nơi ra quyết định nhất quán).

    `vung`: chỉ nạp bài của vùng đang cào ('us' | 'global', mặc định = vùng đang
    chọn) — giống `chong_trung`, 2 vùng coi như 2 kho độc lập."""

    def __init__(self, store=None, vung: str = None):
        store = store or lay_store()
        v = chuan_vung(vung if vung is not None else lay_vung())
        self.vung = v
        self.ds_id = set()
        self.ds_caption = []
        self.ds_caption_gia = []   # [(content_id 'bai_...', caption_da_don_nhan)]
        _nhan = {}                 # id_gia -> ds caption da don nhan (du lieu cu)
        for dong in store.lay_tat_ca("CONTENT POOL"):
            if vung_cua_bai(dong) != v:
                continue
            pid = str(dong.get("Content ID") or "").strip()
            if pid:
                self.ds_id.add(pid)
            cap = chuan_hoa_text(dong.get("Caption") or "")
            if cap:
                self.ds_caption.append(cap)
            if pid.startswith("bai_") and cap:
                _nhan.setdefault(pid, []).append(_bo_xem_them(cap))
        for pid, ds in _nhan.items():
            for cap in ds:
                self.ds_caption_gia.append((pid, cap))

    def la_trung(self, post_id: str, text: str) -> bool:
        """True nếu post_id hoặc caption (chuẩn hoá) đã tồn tại trong kho."""
        pid = str(post_id or "").strip()
        if pid and not pid.startswith("bai_") and pid in self.ds_id:
            return True
        norm = chuan_hoa_text(text or "")
        if not norm:
            return False
        for cu in self.ds_caption:
            if _la_cung_bai(norm, cu):
                return True
        if pid.startswith("bai_"):
            for id_cu, cap_cu in self.ds_caption_gia:
                if _trung_id_gia(pid, id_cu, text, cap_cu):
                    return True
        return False


def chong_trung(cac_bai: list, store=None, phien: str = "", vung: str = None) -> list:
    """Lọc danh sách bài (dict có 'post_id' và 'text') — bỏ bài đã có trong pool.

    Tiêu chí trùng:
      1. post_id đã có trong cột "Content ID" (chỉ id thật: pfbid…/số dài —
         id dự phòng bai_<hash> có thể trùng giả giữa 2 bài khác nhau)
      2. caption đã chuẩn hoá trùng hoặc nằm trong caption cũ (bản Xem thêm)

    Nếu trùng mà bản mới ĐẦY ĐỦ hơn hẳn → cập nhật caption/link/tương tác
    của dòng cũ (giữ nguyên trạng thái, không thêm dòng mới).

    `phien`: phiên cào hiện tại. Khi gặp bài ĐÃ CÓ trong pool (trùng), ghi nhận
    vào dòng cũ: `So_lan_trung` += 1 và thêm phiên này vào `Cac_phien_gap` — để bài
    vẫn hiện trong phiên cào hiện tại (đánh dấu trùng) mà không mất phiên gốc.

    `vung`: chỉ so trùng trong ĐÚNG vùng đang cào (mặc định = vùng đang chọn).
    Bài US trùng caption với bài GLOBAL vẫn được nạp — mỗi vùng đăng web riêng,
    page riêng, xem như 2 bài độc lập."""
    store = store or lay_store()
    v = chuan_vung(vung if vung is not None else lay_vung())
    pool = [d for d in store.lay_tat_ca("CONTENT POOL")
            if vung_cua_bai(d) == v]

    def _ghi_trung(dong):
        dong["So_lan_trung"] = int(dong.get("So_lan_trung") or 0) + 1
        cac_phien = dong.get("Cac_phien_gap")
        if cac_phien is None:
            p_goc = str(dong.get("Phien_cao") or "").strip()
            cac_phien = [p_goc] if p_goc else []
        if not isinstance(cac_phien, list):
            cac_phien = [str(cac_phien)]
        if phien and phien not in cac_phien:
            cac_phien.append(phien)
        dong["Cac_phien_gap"] = cac_phien

    moi = []
    for bai in cac_bai:
        pid = str(bai.get("post_id") or "").strip()
        text = bai.get("text") or ""
        norm_moi = chuan_hoa_text(text)

        trung = False
        for chi_so, dong in enumerate(pool):
            id_cu = str(dong.get("Content ID") or "").strip()
            if pid and pid == id_cu and (
                    not pid.startswith("bai_")
                    or _trung_id_gia(pid, id_cu, text,
                                     dong.get("Caption") or "")):
                trung = True
            elif _la_cung_bai(norm_moi, chuan_hoa_text(dong.get("Caption") or "")):
                trung = True
            else:
                continue

            # bản mới đầy đủ hơn hẳn → nâng cấp caption cũ, giữ nguyên Status
            if len(text) > len(dong.get("Caption") or "") + 50:
                dong["Caption"] = text
                if bai.get("post_url"):
                    dong["Link bài"] = bai.get("post_url")
                anh_local = bai.get("images_da_tai") or []
                if anh_local:
                    dong["Media"] = "; ".join(str(u) for u in anh_local[:5])
                elif bai.get("images"):
                    dong["Media"] = "; ".join(str(u) for u in bai["images"][:5])
                dong["Cảm xúc"] = bai.get("likes") or dong.get("Cảm xúc") or 0
                dong["Bình luận"] = bai.get("comments") or dong.get("Bình luận") or 0
                dong["Chia sẻ"] = bai.get("shares") or dong.get("Chia sẻ") or 0

            _ghi_trung(dong)
            store.cap_nhat_dong("CONTENT POOL", chi_so, dong)
            break

        if not trung:
            moi.append(bai)
    return moi


# ===================================================================
# Thêm content vào pool
# ===================================================================
def them_content(bai: dict, key: str, nhan_vat: str, source: str,
                 store=None, phien: str = "", vung: str = None) -> dict:
    """Thêm 1 bài vào CONTENT POOL, status = NEW. Trả về dòng đã lưu.
    Tự động kiểm tra và loại bỏ triệt để các bài không có caption hoặc chỉ có rác header.
    """
    import cao_fb
    text = cao_fb.lam_sach_text_bai(bai.get("text") or bai.get("Caption") or "").strip()
    if not cao_fb.la_caption_hop_le(text):
        return None

    store = store or lay_store()
    pid = str(bai.get("post_id") or "")
    images = bai.get("images") or []
    # Ưu tiên ảnh ĐÃ TẢI VỀ MÁY (images_da_tai) — trình duyệt/fetch hiển thị được;
    # chỉ dùng URL external khi không có ảnh local.
    anh_local = bai.get("images_da_tai") or []
    if anh_local:
        media = "; ".join(str(u) for u in anh_local[:5])
    else:
        media = "; ".join(str(u) for u in images[:5])  # link ảnh FB (tải về lúc đăng)

    dong = {
        "Content ID": pid,
        "KEY": key,
        "Nhân vật/chủ đề": nhan_vat,
        "Source": source,
        "Caption": text,
        "Media": media,
        "Link bài": bai.get("post_url") or "",
        "Thời gian đăng": bai.get("time") or "",
        "Cảm xúc": bai.get("likes") or 0,
        "Bình luận": bai.get("comments") or 0,
        "Chia sẻ": bai.get("shares") or 0,
        "Caption mới": "",
        "Bài báo": "",
        "Article URL": "",
        "Status": "NEW",
        "Phien_cao": phien,
        "So_lan_trung": 0,
        "Cac_phien_gap": [phien] if phien else [],
        "Ghi chú": "",
        "Vung": chuan_vung(vung if vung is not None else lay_vung()),
    }
    store.them_dong("CONTENT POOL", dong)
    return dong


# ===================================================================
# Hết hạn — content quá N ngày không đăng nữa
# ===================================================================
def _goc_thoi_gian(gia_tri):
    """Chuyển 'Thời gian đăng' thành datetime nếu đọc được, không thì None."""
    if not gia_tri:
        return None
    s = str(gia_tri).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        pass
    try:  # dạng tiếng Việt: 'Thứ bảy, 22 Tháng 8, 2026 lúc 20:02'
        from cao_fb import _parse_thoi_gian
        return _parse_thoi_gian(s)
    except Exception:
        return None


def danh_dau_het_han(store=None, so_ngay: int = None) -> int:
    """Đánh HET_HAN cho content NEW/READY đăng lâu hơn so_ngay ngày.

    Trả về số dòng vừa đánh dấu. Không đọc được thời gian → giữ nguyên."""
    store = store or lay_store()
    so_ngay = so_ngay or load_config().get("content_han_ngay") or 7
    gioi_han = datetime.now() - timedelta(days=so_ngay)

    dem = 0
    for chi_so, dong in enumerate(store.lay_tat_ca("CONTENT POOL")):
        status = str(dong.get("Status") or "").strip()
        if status not in ("NEW", "READY"):
            continue
        goc = _goc_thoi_gian(dong.get("Thời gian đăng"))
        if goc is None:
            continue
        if goc < gioi_han:
            dong["Status"] = "HET_HAN"
            dong["Ghi chú"] = f"Quá {so_ngay} ngày"
            store.cap_nhat_dong("CONTENT POOL", chi_so, dong)
            dem += 1
    return dem


# ===================================================================
# Logic chọn content cho 1 Page (Luồng B) — đúng KEY trước,
# rồi ưu tiên nhân vật Page đang chạy tốt, không có thì lấy bài mới cùng KEY.
# ===================================================================
def chon_content(page_cfg: dict, tin_hieu: dict = None, store=None):
    """Chọn content phù hợp nhất cho 1 Page.

    page_cfg: 1 dòng PAGE CONFIG (có KEY).
    tin_hieu: {nhân_vật: điểm_tín_hiệu} từ PAGE PERFORMANCE (chưa có thì None
              → bootstrap: bài mới nhất đúng KEY).

    Trả về (chi_so, dong) trong pool, hoặc None nếu không có content nào."""
    store = store or lay_store()
    key = str(page_cfg.get("KEY") or "").strip()
    pool = store.lay_tat_ca("CONTENT POOL")

    # 1) đúng KEY + trạng thái chọn được
    ung_vien = []
    for chi_so, dong in enumerate(pool):
        if str(dong.get("KEY") or "").strip() != key:
            continue
        if str(dong.get("Status") or "").strip() not in ("NEW", "READY"):
            continue
        ung_vien.append((chi_so, dong))

    if not ung_vien:
        return None

    # 2) có tín hiệu → ưu tiên nhân vật đang chạy tốt
    if tin_hieu:
        thu_tu = sorted(tin_hieu.items(), key=lambda kv: kv[1], reverse=True)
        for nhan_vat, _diem in thu_tu:
            for chi_so, dong in ung_vien:
                if str(dong.get("Nhân vật/chủ đề") or "").strip() == nhan_vat:
                    return chi_so, dong

    # 3) bootstrap / không có nhân vật trùng → bài mới nhất đúng KEY
    def thu_tu_gio(dong):
        goc = _goc_thoi_gian(dong.get("Thời gian đăng"))
        return goc or datetime.min

    chi_so, dong = max(ung_vien, key=lambda u: thu_tu_gio(u[1]))
    return chi_so, dong


# ===================================================================
# Cập nhật trạng thái
# ===================================================================
def doi_status(content_id: str, status: str, ghi_chu: str = "", store=None):
    """Đổi trạng thái 1 content (tìm theo Content ID). Trả về True nếu tìm thấy."""
    store = store or lay_store()
    ket_qua = store.tim_dong("CONTENT POOL", "Content ID", content_id)
    if ket_qua is None:
        return False
    chi_so, dong = ket_qua
    dong["Status"] = status
    if ghi_chu:
        dong["Ghi chú"] = ghi_chu
    store.cap_nhat_dong("CONTENT POOL", chi_so, dong)
    return True


if __name__ == "__main__":
    # test nhanh: python content_pool.py
    from google_sheets import lay_store
    store = lay_store()
    print(f"Store: {store.mo_ta()}")
    print(f"Pool hiện có: {store.so_dong('CONTENT POOL')} dòng")
    print(f"Hết hạn: {danh_dau_het_han(store)} dòng vừa đánh dấu")
