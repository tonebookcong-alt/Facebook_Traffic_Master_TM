# -*- coding: utf-8 -*-
"""
Module DANG_WEB — Đăng bài báo lên Website đích qua REST API (BlogBio).
Hỗ trợ 2 website theo khu vực: `web='us'` hoặc `web='global'` (BẮT BUỘC chọn).

Hợp đồng API đã ĐO THỰC TẾ (probe 2026-09-13):
- POST /api/posts, form-encoded, Bearer token -> 201 {link, slug, postId}.
  Field THAT được dùng: title, content, permalink, category, tags[],
  feature_image, seokeyword.  (meta_description / apply_image_to_all /
  skip_intro / status BỊ SERVER LỜ ĐI — không gửi vô ích.)
- `category` và `tags[]` phải là ID SỐ của danh mục/thẻ ĐÃ TỒN TẠI;
  gửi tên tự chế sẽ SINH RÁC category/tag mới trên site.
  -> module tự GET /api/categories + /api/tags, cache, và chỉ gửi ID khớp.
- `content` render như HTML thô: Markdown KHÔNG được dịch -> tự bọc <p>.
  Meta description của page = ~160 ký tự đầu -> đoạn đầu tiên phải là lead.
- Presigned ảnh: POST /api/uploads/presigned-image-url {fileName, contentType,
  size} -> PUT file vào upload.url (R2) -> dùng fileUrl làm feature_image.
- permalink trùng: server tự thêm hậu tố -1, -2 (không lỗi).
- 422 = validation error (không retry); 429 tôn trọng Retry-After.

Chế độ GIẢ LẬP (Mock) giữ nguyên khi web đó chưa cấu hình api_url.
"""

import json
import os
import re
import threading
import time
import html as _html
import requests
from datetime import datetime

from config import DUONG_DAN, load_config

WEB_HOP_LE = ("us", "global")

# Windows: bỏ mọi proxy hệ thống (kể cả fake VPN kiểu proxy) ở tầng requests.
_NO_PROXY = {"http": None, "https": None}

# Danh mục ưu tiên khi không map được chủ đề (tên, sẽ đối chiếu ID qua taxonomy)
_CATEGORY_UU_TIEN = ("sport", "entertainment", "news")

# Bộ thẻ luôn ưu tiên gắn nếu site có sẵn (đều là ID hợp lệ, không sinh rác)
_TAGS_CO_DINH = ("news", "athlete", "storytelling")

_TAXONOMY_LOCK = threading.Lock()
_TAXONOMY_CACHE = {}          # host -> {"categories": {...}, "tags": {...}, "ts": float}
_TAXONOMY_FILE = os.path.join(DUONG_DAN, "du_lieu_traffic", "api_taxonomy.json")


# ----------------------------------------------------------------------
# Tiện ích chung
# ----------------------------------------------------------------------
def _tao_slug(text: str) -> str:
    """Tạo slug URL từ tiêu đề hoặc tên nhân vật."""
    if not text:
        return "article"
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:60] or "article"


def _hop_le_slug(slug: str) -> str:
    """Chuẩn slug về ASCII [a-z0-9-]. Server blogbio từ chối 422 "permalink
    contains invalid characters" khi permalink còn ký tự ngoài bảng chữ Latinh
    (homoglyph Cyrillic/Hy Lạp trà trộn trong caption cào về, emoji, ...) —
    chỉ tiếng Việt có dấu thì server tự transliterate được.
    Ở đây: NFD tách dấu khỏi chữ cái -> giữ nguyên âm Việt (mở->mo, cửa->cua),
    chữ Cy/Hy Lạp không phân tách được nên rớt lại bị loại thành '-'.
    Nếu sau khi lọc rỗng -> fallback 'article' để KHÔNG bao giờ gửi permalink hư."""
    import unicodedata

    s = (slug or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "article"


def _suy_host(api_url: str) -> str:
    """api_url dạng https://host/api/posts hoặc https://host -> https://host."""
    host = (api_url or "").strip()
    for suf in ("/api/posts", "/api/post", "/api", "/"):
        if host.endswith(suf):
            host = host[: -len(suf)]
            break
    return host.rstrip("/")


def _mime_cua(ten_file: str) -> str:
    low = (ten_file or "").lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith(".webp"):
        return "image/webp"
    if low.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


# ----------------------------------------------------------------------
# Taxonomy: categories + tags thật của từng site (cache trong RAM + file)
# ----------------------------------------------------------------------
def _doc_taxonomy_file() -> dict:
    try:
        if os.path.exists(_TAXONOMY_FILE):
            with open(_TAXONOMY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _ghi_taxonomy_file(data: dict):
    try:
        os.makedirs(os.path.dirname(_TAXONOMY_FILE), exist_ok=True)
        with open(_TAXONOMY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _ep_chuan(text: str) -> str:
    """Chuẩn hoá tên để so khớp: thường hoá, bỏ khoảng trắng thừa."""
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _lay_taxonomy(host: str, api_token: str, max_tuoi_giay: int = 6 * 3600) -> dict:
    """Lấy {'categories': {ten_chuan_hoa: id}, 'tags': {...}} của 1 site.

    Thứ tự: cache RAM -> gọi API -> cache file cũ (khi API lỗi/VPN chặn).
    Không bao giờ raise; thất bại hoàn toàn trả dict rỗng.
    """
    now = time.time()
    with _TAXONOMY_LOCK:
        cu = _TAXONOMY_CACHE.get(host)
        if cu and (now - cu.get("ts", 0)) < max_tuoi_giay:
            return dict(cu, nguon="cache-ram")

    ket_qua = {"categories": {}, "tags": {}, "ts": 0.0, "nguon": "khong"}
    headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json",
               "User-Agent": "Mozilla/5.0 (compatible; TrafficFB/1.0)"}
    ok = True
    try:
        for kieu, duong_dan in (("categories", "/api/categories"), ("tags", "/api/tags")):
            r = requests.get(host + duong_dan, headers=headers, timeout=30, proxies=_NO_PROXY)
            r.raise_for_status()
            ds = r.json()
            if isinstance(ds, dict):
                ds = ds.get("data") or []
            for m in ds or []:
                ten = _ep_chuan(m.get("name"))
                mid = m.get("id")
                if ten and mid is not None:
                    ket_qua[kieu][ten] = int(mid)
    except Exception as e:
        ok = False
        print(f"  [!] Không lấy được taxonomy {host}: {e} (dùng cache file nếu có)")

    if ok and ket_qua["categories"]:
        ket_qua["ts"] = now
        ket_qua["nguon"] = "live-api"
        with _TAXONOMY_LOCK:
            _TAXONOMY_CACHE[host] = dict(ket_qua)
        # đồng bộ ra file để lần sau offline/vẫn còn bản mới nhất
        du_lieu = _doc_taxonomy_file()
        du_lieu[host] = {"categories": ket_qua["categories"], "tags": ket_qua["tags"]}
        _ghi_taxonomy_file(du_lieu)
        return dict(ket_qua)

    # API lỗi -> đọc cache file (coi như taxonomy ít đổi)
    du_lieu = _doc_taxonomy_file()
    if du_lieu.get(host):
        ket_qua = {"categories": du_lieu[host].get("categories", {}),
                   "tags": du_lieu[host].get("tags", {}), "ts": now - 60,
                   "nguon": "cache-file (API bị chặn — chưa kết nối thật)"}
        with _TAXONOMY_LOCK:
            _TAXONOMY_CACHE[host] = dict(ket_qua)
    return dict(ket_qua)


def _chon_category_id(key: str, taxonomy: dict) -> int:
    """Ánh xạ chủ đề (NFL/WNBA/Fake News...) -> ID danh mục ĐÃ TỒN TẠI.

    Nguyên tắc sống còn: KHÔNG gửi tên lung tung — sẽ sinh category rác.
    Không khớp gì -> ưu tiên Sport/Entertainment/News -> ID nhỏ nhất có sẵn.
    """
    cats = taxonomy.get("categories") or {}
    if not cats:
        return 0
    for thu in (_ep_chuan(key),):
        if thu and thu in cats:
            return cats[thu]
    for thu in _CATEGORY_UU_TIEN:
        if thu in cats:
            return cats[thu]
    return min(cats.values())


def _chon_tag_ids(key: str, nhan_vat: str, taxonomy: dict, toi_da: int = 6) -> list:
    """Chọn ID THẺ hợp lệ (tồn tại trên site) — không bao giờ tạo thẻ rác."""
    tags = taxonomy.get("tags") or {}
    if not tags:
        return []
    ket_qua, thay = [], set()

    def them(ten: str):
        t = _ep_chuan(ten)
        if t and t in tags and tags[t] not in thay:
            ket_qua.append(tags[t])
            thay.add(tags[t])

    them(key)
    them(nhan_vat)
    for t in _TAGS_CO_DINH:
        if len(ket_qua) >= toi_da:
            break
        them(t)
    # bổ sung thẻ chung hay có nếu site dùng hệ thẻ phim/truyện
    for t in ("lifestory", "drama", "popculture"):
        if len(ket_qua) >= min(4, toi_da) and len(ket_qua) >= 3:
            break
        them(t)
    return ket_qua[:toi_da]


# ----------------------------------------------------------------------
# Nội dung: text thuần -> HTML an toàn cho BlogBio
# ----------------------------------------------------------------------
def esc(text: str) -> str:
    """Escape các ký tự HTML nguy hiểm, GIỮ nguyên nháy/phẩy (quote=False).

    Bài gốc là text thuần, chỉ cần chặn < > & để khỏi vỡ thẻ; apostrophe
    (’ ') và ngoặc kép nên giữ nguyên cho tự nhiên."""
    return _html.escape(str(text or ""), quote=False)


def _tach_cau(dong: str) -> list:
    """Tách 1 dòng chứa nhiều câu thành nhiều câu (dự phòng khi AI gộp câu).

    Chỉ tách khi dòng dài (>200 ký tự) và có >=2 câu phân cách bởi
    [.!?] + khoảng trắng + chữ HOA. Giữ an toàn cho các viết tắt phổ biến
    (Dr., Mr., U.S., St., vs., Nr., No., Jr., Sr., Prof., a.m., p.m., số).
    Ngắn thì trả nguyên 1 phần tử."""
    if len(dong) <= 200:
        return [dong]
    tach = re.split(r'(?<=[.!?])\s+(?=[A-Z"\u201c])', dong)
    if len(tach) < 2:
        return [dong]
    # Gộp lại các mảnh vỡ do viết tắt: mảnh trước kết thúc bằng dấu '.' mà
    # không phải câu thực (quá ngắn) -> nối lại với mảnh sau.
    ket_qua = []
    for mh in tach:
        if ket_qua and re.search(r'\b(?:Dr|Mr|Mrs|Ms|St|Jr|Sr|Prof|vs|No|Nr|a\.m|p\.m|[A-Z])\.$',
                                 ket_qua[-1].strip()):
            ket_qua[-1] = ket_qua[-1].rstrip() + " " + mh
        elif ket_qua and len(ket_qua[-1].strip()) <= 4 and not ket_qua[-1].strip().endswith("."):
            ket_qua[-1] = ket_qua[-1].rstrip() + " " + mh
        else:
            ket_qua.append(mh)
    return [k.strip() for k in ket_qua if k.strip()]


def _format_noi_dung(noi_dung: str) -> str:
    """Bọc text thuần thành HTML cho BlogBio: MỖI CÂU/DÒNG = 1 <p> riêng.
    - Site render content thô (Markdown không được dịch) nên phải tự chia đoạn.
    - Bài chuẩn trên site (đo từ bài mẫu): ~124 thẻ <p>, mỗi thẻ 1 câu ngắn
      (10–40 ký tự tới ~200 ký tự), kèm các <h2> cho đề mục. Không gộp nhiều
      câu vào một <p>.
    - Dòng "## Đề mục" -> <h2>. Dòng "---" -> <hr>. Bỏ dấu gạch đầu dòng.
    - Meta description của page = ~160 ký tự đầu -> dòng đầu là lead, giữ gọn.
    - Nếu nội dung đã có sẵn tag HTML thì giữ nguyên, không đụng tới.
    """
    if not noi_dung:
        return "<p>Nội dung cập nhật.</p>"
    if re.search(r"<(p|h2|h3|ul|ol|li|br|div|strong|em)\b", noi_dung, re.I):
        return noi_dung.strip()

    ket_qua = []
    for raw in noi_dung.replace("\r\n", "\n").split("\n"):
        dong = raw.strip()
        if not dong:
            continue
        n = re.sub(r"^#+\s*", "", dong)            # "## Heading" -> "Heading"
        if dong.startswith("#") and len(n) <= 120 and "." not in n:
            ket_qua.append(f"<h2>{esc(n)}</h2>")
            continue
        if dong in ("---", "***", "___"):
            ket_qua.append("<hr>")
            continue
        dong = re.sub(r"^[#\-*•]+\s*", "", dong)       # bullet / hash thừa -> dòng thường sạch sẽ
        if dong:
            for cau in _tach_cau(dong):             # dự phòng: AI gộp câu dài
                ket_qua.append(f"<p>{esc(cau)}</p>")

    if not ket_qua:
        ket_qua = [f"<p>{esc(noi_dung.strip())}</p>"]
    return "\n".join(ket_qua)


def _chen_anh_vao_body(noi_dung_html: str, url_anh: str, alt: str = "") -> str:
    """Chèn <img> vào thân bài (sau đoạn lead).

    Đã đo: `feature_image` chỉ vào og:image (SEO/social), KHÔNG hiển thị
    trong thân bài. Ảnh inline thì server giữ nguyên, kể cả `alt`.
    Vì vậy muốn bài có ảnh phải nhúng thẳng vào content.
    """
    if not url_anh or "<img" in (noi_dung_html or "").lower():
        return noi_dung_html
    alt = re.sub(r'["<>]', "", (alt or "photo"))[:90] or "photo"
    the_anh = f'<p style="text-align:center"><img src="{url_anh}" alt="{alt}" loading="lazy"></p>'
    vi_tri = noi_dung_html.find("</p>")
    if vi_tri == -1:
        return the_anh + "\n" + noi_dung_html
    vi_tri += len("</p>")
    return noi_dung_html[:vi_tri] + "\n" + the_anh + noi_dung_html[vi_tri:]


def _seo_keyword(tieu_de: str, key: str, nhan_vat: str) -> str:
    """seokeyword (đoạn đầu title) + key + nhân vật -> xuất ra meta keywords."""
    phan = []
    if key:
        phan.append(str(key).strip())
    if nhan_vat:
        phan.append(str(nhan_vat).strip())
    t = re.sub(r"\b(the|a|an|of|in|on|at|and|to|for|with|is|was|are|has|have)\b", " ",
               (tieu_de or "").lower(), flags=re.I)
    t = re.sub(r"[^\w\s-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t and t not in [p.lower() for p in phan]:
        phan.append(t[:80])
    return ", ".join(dict.fromkeys([p for p in phan if p]))[:250]


# ----------------------------------------------------------------------
# Upload ảnh qua presigned URL (BlogBio / R2)
# ----------------------------------------------------------------------
def _tai_len_blogbio(anh_path: str, api_token: str, base_url: str = "") -> str:
    """Upload ảnh lên BlogBio qua presigned URL, trả về fileUrl ("" nếu lỗi).

    Flow (đã đo): POST /api/uploads/presigned-image-url (form: fileName,
    contentType, size) -> {data:{upload:{url}, fileUrl}} -> PUT file vào url.
    """
    if not anh_path or not api_token:
        return ""
    if str(anh_path).startswith("http"):
        return anh_path
    if not os.path.isfile(anh_path):
        return ""

    base = (base_url or "").rstrip("/")
    if not base:
        return ""
    presign_url = base + "/api/uploads/presigned-image-url"

    ten_file = os.path.basename(anh_path) or "image.jpg"
    kich_thuoc = os.path.getsize(anh_path)
    mime = _mime_cua(ten_file)

    try:
        r = requests.post(
            presign_url,
            headers={"Authorization": f"Bearer {api_token}"},
            data={"fileName": ten_file, "contentType": mime, "size": kich_thuoc},
            timeout=60,
            proxies=_NO_PROXY,
        )
        r.raise_for_status()
        d = r.json()
        upload = (d.get("data") or {}).get("upload") or {}
        file_url = (d.get("data") or {}).get("fileUrl") or ""
        up_url = upload.get("url") or ""
        if not up_url or not file_url:
            return ""

        with open(anh_path, "rb") as f:
            up = requests.put(up_url, data=f, headers={"Content-Type": mime},
                              timeout=120, proxies=_NO_PROXY)
        if up.status_code not in (200, 201, 204):
            return ""
        return file_url
    except Exception as e:
        print(f"  [!] Lỗi upload ảnh BlogBio: {e}")
        return ""


# ----------------------------------------------------------------------
# Đăng bài: BlogBio
# ----------------------------------------------------------------------
def _dang_blogbio(api_url: str, api_token: str, tieu_de: str, noi_dung: str,
                  anh_path: str = "", nhan_vat: str = "", key: str = "",
                  max_retries: int = 2) -> dict:
    """Đăng bài theo flow BlogBio đã xác minh bằng probe thật."""
    host = _suy_host(api_url)

    # 0) Taxonomy thật của site (ID category/tag — tránh sinh rác)
    taxonomy = _lay_taxonomy(host, api_token)
    category_id = _chon_category_id(key, taxonomy)
    tag_ids = _chon_tag_ids(key, nhan_vat, taxonomy)

    # 1) Upload ảnh (nếu có) -> feature_image
    feature_image = ""
    if anh_path:
        feature_image = _tai_len_blogbio(anh_path, api_token, base_url=host)

    # 2) Slug: chuẩn hoá + hậu tố thời gian (trùng server tự thêm -1 cũng ổn)
    slug = _tao_slug(tieu_de) if tieu_de else _tao_slug(key or nhan_vat)
    if not slug:
        slug = f"bai-{int(time.time())}"
    slug = f"{slug}-{int(time.time()) % 1000000}"

    noi_dung_html = _format_noi_dung(noi_dung)
    if feature_image:
        noi_dung_html = _chen_anh_vao_body(
            noi_dung_html, feature_image,
            alt=(tieu_de or nhan_vat or key)[:90])

    data = {
        "title": (tieu_de or f"Story on {nhan_vat or key}")[:200],
        "content": noi_dung_html,
        "permalink": _hop_le_slug(slug),
    }
    if category_id:
        data["category"] = str(category_id)
    if tag_ids:
        data["tags[]"] = [str(t) for t in tag_ids]
    if feature_image:
        data["feature_image"] = feature_image
    seo = _seo_keyword(tieu_de, key, nhan_vat)
    if seo:
        data["seokeyword"] = seo

    headers = {"Authorization": f"Bearer {api_token}",
               "User-Agent": "Mozilla/5.0 (compatible; TrafficFB/1.0)"}

    for lan in range(max_retries + 1):
        try:
            resp = requests.post(api_url, headers=headers, data=data,
                                 timeout=90, proxies=_NO_PROXY)
            if resp.status_code == 429:
                cho = int(resp.headers.get("Retry-After") or (10 * (lan + 1)))
                cho = min(max(cho, 5), 60)
                print(f"  [!] Web báo 429 (quá tải), chờ {cho}s rồi thử lại...")
                time.sleep(cho)
                continue
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                # 422/401/403: lỗi payload/auth — retry y nguyên vô ích
                try:
                    chi_tiet = json.dumps(resp.json(), ensure_ascii=False)[:400]
                except Exception:
                    chi_tiet = resp.text[:400]
                if resp.status_code == 403 and ("Just a moment" in chi_tiet
                                                or "cf-" in chi_tiet.lower()):
                    return {"success": False, "article_url": "", "article_id": "",
                            "message": "BỊ CHẶN BỞI VPN — Cloudflare trả 403 challenge. "
                                       "ĐÃ kiểm chứng: Proton, Hide.me và fake VPN đều bị chặn. "
                                       "TẮT hẳn VPN (disconnect về IP thật) rồi chạy lại. "
                                       "Không phải lỗi token hay code."}
                return {"success": False, "article_url": "", "article_id": "",
                        "message": f"API từ chối {resp.status_code}: {chi_tiet}"}
            resp.raise_for_status()
            d = resp.json()
            # BlogBio trả {link, slug, postId}; bản cũ bọc data -> đọc cả 2 tầng
            inner = d.get("data") if isinstance(d.get("data"), dict) else {}
            article_url = (inner.get("link") or inner.get("url")
                           or d.get("link") or d.get("url") or d.get("article_url") or "")
            if not article_url:
                sl = inner.get("slug") or d.get("slug") or ""
                if sl:
                    article_url = host + "/blog/" + str(sl).strip("/")
            article_id = (inner.get("id") or inner.get("postId")
                          or d.get("postId") or d.get("id") or "")
            if article_url:
                return {
                    "success": True,
                    "article_url": article_url,
                    "article_id": str(article_id),
                    "message": "Đăng web thành công",
                }
            err_msg = d.get("message") or str(d)[:200]
            if lan == max_retries:
                return {"success": False, "article_url": "", "article_id": "",
                        "message": f"API không trả link: {err_msg}"}
        except requests.HTTPError as e:
            try:
                chi_tiet = str(e.response.json())[:300]
            except Exception:
                chi_tiet = str(e)
            if lan == max_retries:
                return {"success": False, "article_url": "", "article_id": "",
                        "message": f"Lỗi HTTP: {chi_tiet}"}
        except Exception as e:
            if lan == max_retries:
                return {"success": False, "article_url": "", "article_id": "",
                        "message": f"Lỗi kết nối web: {e}"}
            time.sleep(2 * (lan + 1))
    return {"success": False, "article_url": "", "article_id": "",
            "message": "Lỗi không xác định"}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def dang_bai_web(tieu_de: str, noi_dung: str, anh_path: str = "",
                 nhan_vat: str = "", key: str = "", max_retries: int = 2,
                 web: str = None) -> dict:
    """Đăng bài viết lên website theo khu vực (`web` = 'us' | 'global' — BẮT BUỘC).

    Trả về dict kết quả:
    {
        "success": True/False,
        "article_url": "https://...",
        "article_id": "...",
        "message": "...",
        "web": "us" | "global"
    }
    """
    web = (web or "").strip().lower()
    if web not in WEB_HOP_LE:
        return {
            "success": False, "article_url": "", "article_id": "",
            "message": "Chưa chọn web đăng bài (US hay GLOBAL) — bắt buộc chọn trước khi chạy",
            "web": web or None,
        }

    cfg = load_config()
    web_cfg = ((cfg.get("website") or {}).get(web)) or {}
    api_url = (web_cfg.get("api_url") or "").strip()
    api_token = (web_cfg.get("api_token") or "").strip()
    mode = (web_cfg.get("mode") or "json").strip().lower()

    # Tự động gắn Mã nhận diện (Title Prefix) vào tiêu đề bài báo nếu có cấu hình (ví dụ: "TH - ...")
    ma_nhan_dien = (cfg.get("ma_nhan_dien") or "").strip()
    if not ma_nhan_dien:
        try:
            from license_manager import lay_ma_nhan_dien_hien_tai
            ma_nhan_dien = lay_ma_nhan_dien_hien_tai()
        except Exception:
            pass
    if ma_nhan_dien and tieu_de:
        tieu_de_clean = tieu_de.strip()
        prefix = f"{ma_nhan_dien} - "
        if not (tieu_de_clean.startswith(prefix) or 
                tieu_de_clean.startswith(f"{ma_nhan_dien}:") or 
                tieu_de_clean.startswith(f"[{ma_nhan_dien}]") or
                tieu_de_clean.startswith(f"{ma_nhan_dien} ")):
            tieu_de = f"{prefix}{tieu_de_clean}"

    # -------------------------------------------------------------
    # 1. CHẾ ĐỘ GIẢ LẬP (KHI WEB ĐÓ CHƯA CÓ API URL THẬT)
    # -------------------------------------------------------------
    if not api_url:
        stamp = int(time.time())
        slug_nv = _tao_slug(nhan_vat) if nhan_vat else _tao_slug(key)
        slug_td = _tao_slug(tieu_de)[:40] if tieu_de else "breaking-news"
        mock_url = f"https://dailysportswire.com/articles/{slug_nv}-{slug_td}-{stamp % 10000}"

        log_dir = os.path.join(DUONG_DAN, "du_lieu_fb")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "web_posts_simulated.json")

        record = {
            "time": datetime.now().isoformat(),
            "web": web,
            "key": key,
            "nhan_vat": nhan_vat,
            "tieu_de": tieu_de or f"Latest update on {nhan_vat or key}",
            "noi_dung_sample": (noi_dung[:300] + "...") if noi_dung else "",
            "anh_path": anh_path,
            "mock_article_url": mock_url,
        }

        danh_sach = []
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    danh_sach = json.load(f)
            except (json.JSONDecodeError, OSError):
                danh_sach = []
        danh_sach.append(record)
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(danh_sach, f, ensure_ascii=False, indent=2)

        print(f"  [i] [GIẢ LẬP WEB {web.upper()}] Đã tạo Article URL: {mock_url}")
        return {
            "success": True,
            "article_url": mock_url,
            "article_id": f"mock_{stamp}",
            "message": "Đăng thành công ở chế độ giả lập (Simulation)",
            "web": web,
        }

    # -------------------------------------------------------------
    # 2. CHẾ ĐỘ GỌI API THẬT
    # -------------------------------------------------------------
    if mode == "blogbio":
        kq = _dang_blogbio(api_url, api_token, tieu_de, noi_dung,
                           anh_path=anh_path, nhan_vat=nhan_vat, key=key,
                           max_retries=max_retries)
        kq["web"] = web
        return kq

    # Mode JSON (API thường, tương thích ngược)
    headers = {
        "Authorization": f"Bearer {api_token}" if api_token else "",
        "Content-Type": "application/json",
    }
    payload = {
        "title": tieu_de or f"Story on {nhan_vat or key}",
        "content": noi_dung,
        "category": key,
        "tags": [nhan_vat, key] if nhan_vat else [key],
        "image": anh_path,
        "status": "published",
        "published_at": datetime.now().isoformat(),
    }
    for lan in range(max_retries + 1):
        try:
            resp = requests.post(api_url, headers=headers, json=payload,
                                 timeout=90, proxies=_NO_PROXY)
            resp.raise_for_status()
            d = resp.json()
            article_url = (d.get("url") or d.get("link") or d.get("article_url")
                           or (d.get("data") or {}).get("url", ""))
            if article_url:
                return {"success": True, "article_url": article_url,
                        "article_id": str(d.get("id", "")),
                        "message": "Đăng web thành công", "web": web}
            return {"success": False, "article_url": "", "article_id": "",
                    "message": f"API không trả link: {str(d)[:200]}", "web": web}
        except Exception as e:
            if lan == max_retries:
                print(f"  [!] Lỗi đăng website sau {max_retries} lần thử: {e}")
                return {"success": False, "article_url": "", "article_id": "",
                        "message": f"Lỗi không xác định: {e}", "web": web}
            time.sleep(2 * (lan + 1))
    return {"success": False, "article_url": "", "article_id": "",
            "message": "Lỗi không xác định", "web": web}


def kiem_tra_ket_noi(web: str) -> dict:
    """Kiểm tra nhanh 1 site: token sống + lấy taxonomy. Không đăng bài.

Lưu ý: khi VPN tunnel bật, API bị Cloudflare 403 -> hàm này đọc cache cũ
và trả ok=False kèm nguồn 'cache-file' để KHÔNG báo giả 'ok'.
"""
    web = (web or "").strip().lower()
    if web not in WEB_HOP_LE:
        return {"ok": False, "message": f"web phải là {WEB_HOP_LE}"}
    cfg = load_config()
    web_cfg = ((cfg.get("website") or {}).get(web)) or {}
    api_url = (web_cfg.get("api_url") or "").strip()
    token = (web_cfg.get("api_token") or "").strip()
    if not api_url:
        return {"ok": False, "message": "Chưa cấu hình api_url"}
    host = _suy_host(api_url)
    try:
        tax = _lay_taxonomy(host, token, max_tuoi_giay=0)
        nguon = tax.get("nguon", "?")
        if tax.get("categories"):
            if nguon.startswith("live-api"):
                return {"ok": True,
                        "message": f"Kết nối THẬT OK — {len(tax['categories'])} danh mục, "
                                   f"{len(tax.get('tags', {}))} thẻ",
                        "host": host, "nguon": nguon}
            # chỉ đọc được cache -> KHÔNG phải kết nối thật (VPN/Cloudflare đang chặn)
            return {"ok": False,
                    "message": "KHÔNG kết nối được API (403/chặn). "
                               f"Đang dùng cache cũ ({len(tax['categories'])} danh mục) "
                               "=> phải TẮT hẳn VPN rồi mới đăng được "
                               "(Proton/Hide.me/fake VPN đều bị Cloudflare chặn).",
                    "host": host, "nguon": nguon}
        return {"ok": False, "message": "Gọi /api/categories không có dữ liệu "
                                        "(sai token hoặc VPN/Cloudflare chặn) và chưa có cache",
                "host": host, "nguon": nguon}
    except Exception as e:
        return {"ok": False, "message": f"Lỗi: {e}", "host": host}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for w in WEB_HOP_LE:
        print(w, "->", kiem_tra_ket_noi(w))
