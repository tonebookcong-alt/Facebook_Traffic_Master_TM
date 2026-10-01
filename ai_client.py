# -*- coding: utf-8 -*-
"""
Gọi AI dùng chung cho mọi bước viết/nhận diện của tool.

Chế độ theo config.json -> ai.provider:
  - mock      : KHÔNG cần key — trả kết quả giả (chạy thử toàn bộ luồng)
  - openai    : API OpenAI  (chat completions, openai-compatible)
  - anthropic : API Claude
  - gemini    : API Google Gemini

Điền key ở config.json:
  "ai": { "provider": "openai", "api_key": "sk-...", "model": "gpt-4o-mini" }
"""

import hashlib
import re

from config import load_config

# ===================================================================
# Chế độ mock — trả kết quả giả ổn định để test luồng khi chưa có key
# ===================================================================
def _goi_mock(he_thong, nguoi_dung, nhiet_do=0.7, toi_da_tu=1500):
    """Trả lời giả theo "ý định" của prompt (nhận biết qua vài từ khoá)."""
    noi_dung = (he_thong + "\n" + nguoi_dung)
    # --- viết lại caption (3 bản): nhận bằng nhãn VERSION/đầu đề prompt caption.
    # Kiểm tra TRƯỚC nhánh nhân vật vì prompt caption cũng nhắc "nhân vật"
    # (quy tắc giữ cốt truyện), còn prompt nhan_dien chỉ chứa chữ "caption"
    # chung chung nên không khớp được các điều kiện dưới đây.
    if ("VERSION 1" in he_thong or "VIẾT LẠI CAPTION" in he_thong.upper()
            or "PROMPT VIẾT LẠI" in he_thong.upper()):
        tam = re.sub(r"\s+", " ", nguoi_dung)[:300]
        return ("VERSION 1\n" + tam + " — [bản 1]\n\n"
                "VERSION 2\n" + tam + " — [bản 2]\n\n"
                "VERSION 3\n" + tam + " — [bản 3]")
    # --- viết bài báo — trước nhánh nhân vật vì prompt báo cũng nhắc "nhân vật"
    if "1500" in he_thong or "bài viết tiếng Anh" in he_thong:
        return ("[MOCK BÀI BÁO — 1500-1700 từ] "
                "Nội dung mẫu sinh từ caption gốc, đủ 7-8 đề mục. "
                "Khi có key API thật, nội dung này sẽ là bài báo thật.")
    # --- nhận diện nhân vật ---
    if "Nhân vật" in he_thong or "nhân vật" in he_thong:
        # ưu tiên từ gợi ý: dòng 'Nhân vật gợi ý: A, B, C'
        m = re.search(r"gợi ý[:\s]+([^\n]+)", nguoi_dung)
        if m and m.group(1).strip():
            ten = m.group(1).strip().split(",")[0].strip()
            if ten:
                return ten[:60]
        return "Chủ đề chung"
    # --- mặc định ---
    dai = min(len(nguoi_dung) + 50, toi_da_tu)
    return nguoi_dung[:dai]


# ===================================================================
# Gọi AI thật
# ===================================================================
def _goi_openai(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu):
    import requests
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": he_thong},
                {"role": "user", "content": nguoi_dung},
            ],
            "temperature": nhiet_do,
            "max_tokens": toi_da_tu,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _goi_anthropic(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu):
    import requests
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model or "claude-sonnet-4-5",
            "max_tokens": toi_da_tu,
            "temperature": nhiet_do,
            "system": he_thong,
            "messages": [{"role": "user", "content": nguoi_dung}],
        },
        timeout=180,
    )
    resp.raise_for_status()
    return "".join(b["text"] for b in resp.json()["content"] if b["type"] == "text").strip()


def _goi_gemini(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu):
    import requests
    ten = model or "gemini-1.5-flash"
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{ten}:generateContent",
        params={"key": api_key},
        json={
            "system_instruction": {"parts": [{"text": he_thong}]},
            "contents": [{"parts": [{"text": nguoi_dung}]}],
            "generationConfig": {
                "temperature": nhiet_do,
                "maxOutputTokens": toi_da_tu,
            },
        },
        timeout=120,
    )
    resp.raise_for_status()
    du_lieu = resp.json()
    return du_lieu["candidates"][0]["content"]["parts"][0]["text"].strip()


def _goi_deepseek(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu):
    import requests
    resp = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model or "deepseek-chat",
            "messages": [
                {"role": "system", "content": he_thong},
                {"role": "user", "content": nguoi_dung},
            ],
            "temperature": nhiet_do,
            "max_tokens": max(toi_da_tu, 4000) if toi_da_tu > 1000 else toi_da_tu,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# Cache những (endpoint|model) đã bị từ chối cờ tắt reasoning (HTTP 4xx) —
# từ giờ trở đi KHÔNG gửi cờ nữa cho tổ hợp đó, gọi bình thường như cũ.
_KHOI_CACHE_KHONG_HO_TRO: set = set()


def _doc_stream_sse(resp) -> str:
    """Đọc dữ liệu Server-Sent Events (SSE) từ streaming API để triệt tiêu lỗi Cloudflare 524."""
    import json
    chunks = []
    finish_reason = None
    for line in resp.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8", errors="replace")
        if decoded.startswith("data: "):
            data_str = decoded[6:].strip()
            if data_str == "[DONE]":
                break
            try:
                c_json = json.loads(data_str)
                choice = (c_json.get("choices") or [{}])[0]
                if "finish_reason" in choice and choice["finish_reason"]:
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta", {})
                part = delta.get("content") or ""
                if isinstance(part, list):
                    part = "".join(p.get("text", "") for p in part if isinstance(p, dict))
                if part:
                    chunks.append(part)
            except Exception:
                pass
    kq = "".join(chunks).strip()
    if not kq and finish_reason == "length":
        raise RuntimeError("AI trả về rỗng vì đụng trần token (finish_reason='length').")
    return kq


def _rut_gon_loi_html(status_code: int, raw_text: str) -> str:
    """Rút gọn thông báo lỗi HTML từ Cloudflare/Nginx thành thông điệp tiếng Việt dễ hiểu."""
    t_low = (raw_text or "").lower()
    if "<!doctype" in t_low or "<html" in t_low:
        if status_code == 524:
            return "Cloudflare 524 (Gateway Timeout): Máy chủ AI phản hồi quá 100s do quá tải hoặc đang xử lý tác vụ quá nặng"
        if status_code == 502:
            return "Bad Gateway 502: Máy chủ AI bị mất kết nối tạm thời"
        if status_code == 503:
            return "Service Unavailable 503: Dịch vụ AI đang bận hoặc quá tải"
        if status_code == 504:
            return "Gateway Timeout 504: Cổng mạng AI hết thời gian chờ phản hồi"
        return f"Máy chủ AI trả về lỗi HTTP {status_code}"
    return (raw_text or "")[:250]


def _goi_custom(api_key, base_url, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu,
                them_payload=None, ten_coi_retry="", cho_phep_stream: bool = True):
    """Gọi custom provider tương thích chuẩn OpenAI (OpenRouter, Groq, vLLM, Ollama, VyceAI, ...).

    Tích hợp:
    1. Streaming (SSE) mặc định: nhận token ngay lập tức, ngăn Cloudflare ngắt kết nối (triệt tiêu lỗi 524).
    2. Tự động Thử Lại (Retry) với exponential backoff khi gặp lỗi mạng, 524, 502, 503, 504, 429.
    3. Tự động bóc tách thông báo lỗi sạch thay vì in cả cụm HTML Cloudflare.
    """
    import requests
    import time
    import json

    url = (base_url or "").strip().rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": he_thong},
            {"role": "user", "content": nguoi_dung},
        ],
        "temperature": nhiet_do,
        "max_tokens": toi_da_tu,
    }
    if them_payload and ten_coi_retry and ten_coi_retry in _KHOI_CACHE_KHONG_HO_TRO:
        them_payload = None  # Lần trước server đã báo không nhận cờ -> lần này bỏ qua luôn
    if them_payload:
        payload.update(them_payload)

    max_so_lan = 3
    dung_stream = cho_phep_stream
    loi_cuoi = ""

    for lan in range(max_so_lan):
        try:
            payload["stream"] = dung_stream
            resp = requests.post(url, headers=headers, json=payload, stream=dung_stream, timeout=240)

            # Endpoint từ chối stream hoặc cờ phụ (HTTP 400/404/415/422) -> thử fallback lại non-streaming
            if resp.status_code in (400, 404, 415, 422):
                thay_doi = False
                payload_moi = dict(payload)
                if dung_stream:
                    payload_moi["stream"] = False
                    dung_stream = False
                    thay_doi = True
                if them_payload and any(k in payload_moi for k in them_payload):
                    for k in them_payload:
                        payload_moi.pop(k, None)
                    _KHOI_CACHE_KHONG_HO_TRO.add(ten_coi_retry)
                    thay_doi = True
                if thay_doi:
                    try:
                        resp = requests.post(url, headers=headers, json=payload_moi, stream=False, timeout=240)
                    except Exception:
                        pass

            # Xử lý các lỗi Cloudflare timeout / gateway / rate limit cần retry (524, 502, 503, 504, 429)
            if resp.status_code in (524, 502, 503, 504, 520, 521, 522, 429):
                raw_text = resp.text if not dung_stream else (resp.raw.read(1000).decode("utf-8", errors="ignore") if hasattr(resp, "raw") else "")
                loi_cuoi = _rut_gon_loi_html(resp.status_code, raw_text)
                if lan < max_so_lan - 1:
                    # Nếu model nặng bị nghẽn gateway (524), tự động chuyển sang model flash phản hồi nhanh hơn
                    curr_model = payload.get("model", "")
                    if "v4.1" in curr_model:
                        payload["model"] = curr_model.replace("v4.1", "v4-flash")
                        print(f"  [ai_client] Gặp {loi_cuoi}, tự động chuyển model sang '{payload['model']}' để vượt timeout...", flush=True)
                    cho = int(resp.headers.get("Retry-After") or ((lan + 1) * 4))
                    cho = min(max(cho, 3), 20)
                    print(f"  [ai_client] Tạm chờ {cho}s rồi tự động thử lại (lần {lan + 2}/{max_so_lan})...", flush=True)
                    time.sleep(cho)
                    continue
                else:
                    raise RuntimeError(f"HTTP {resp.status_code}: {loi_cuoi}")

            if resp.status_code >= 400:
                try:
                    j = resp.json()
                    err_obj = j.get("error", {})
                    msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                    if not msg:
                        msg = j.get("message") or resp.text[:200]
                except Exception:
                    msg = _rut_gon_loi_html(resp.status_code, resp.text[:300])
                raise RuntimeError(f"HTTP {resp.status_code}: {msg}")

            # Đọc kết quả thành công
            if dung_stream:
                kq = _doc_stream_sse(resp)
                if kq:
                    return kq
                # Nếu stream trả về rỗng, fallback thử đọc JSON bình thường ở lần sau
                dung_stream = False
                continue
            else:
                data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                finish_reason = choice.get("finish_reason")
                choi = choice.get("message", {}).get("content")
                if isinstance(choi, list):
                    choi = "".join(p.get("text", "") for p in choi if isinstance(p, dict))
                kq = (choi or "").strip()
                if not kq:
                    if finish_reason == "length":
                        raise RuntimeError("AI trả về rỗng vì đụng trần token (finish_reason='length'). Model đã dùng hết token để suy nghĩ. Hãy tắt reasoning hoặc tăng toi_da_tu.")
                    raise RuntimeError("AI trả về kết quả rỗng (content=null/empty).")
                return kq

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            loi_cuoi = f"Mất kết nối tới máy chủ AI ({type(e).__name__})"
            if lan < max_so_lan - 1:
                cho = (lan + 1) * 5
                print(f"  [ai_client] Lỗi mạng: {e}, chờ {cho}s thử lại...", flush=True)
                time.sleep(cho)
                continue
            raise RuntimeError(loi_cuoi)

    raise RuntimeError(loi_cuoi or "Không thể lấy kết quả từ AI sau nhiều lần thử")


def kiem_tra_api_key(provider=None, api_key=None, model=None, base_url=None) -> dict:
    """Gửi 1 câu lệnh nhỏ tới provider để xác nhận key còn dùng được.

    Trả về dict: {"ok": bool, "message": str} — thân thiện để hiện trên WebUI.
    Không cần nhập key khi provider='mock' (luôn thành công).
    """
    provider = (provider or "").strip()
    api_key = (api_key or "").strip()
    model = (model or "").strip()
    base_url = (base_url or "").strip()

    if provider == "mock":
        return {"ok": True, "message": "Chế độ mock — không cần API key, luôn chạy thử được."}

    if provider == "custom":
        if not base_url:
            return {"ok": False, "message": "Chưa nhập Base URL cho custom provider."}
        if not model:
            return {"ok": False, "message": "Chưa nhập Model cho custom provider."}
        cau = "Hãy trả lời đúng 1 từ: OK"
        try:
            tra_loi = _goi_custom(api_key, base_url, model, "Bạn là trợ lý.", cau, 0.2, 20)
        except Exception as e:
            chi_tiet = str(e)
            # _goi_custom ném "HTTP <code>: <thông điệp provider>"
            if chi_tiet.startswith("HTTP "):
                thong_diep = chi_tiet.split(": ", 1)[1] if ": " in chi_tiet else chi_tiet
                return {"ok": False, "message": thong_diep.strip()[:220]}
            if "401" in chi_tiet or "403" in chi_tiet:
                return {"ok": False, "message": "API key hoặc base URL sai — thử lại."}
            if "404" in chi_tiet:
                return {"ok": False, "message": f"Base URL/endpoint không đúng (404): {chi_tiet[:120]}"}
            return {"ok": False, "message": f"Lỗi kết nối: {chi_tiet[:180]}"}
        if tra_loi:
            return {"ok": True, "message": f"Kết nối OK với custom ({model}). Phản hồi: {tra_loi[:40]}"}
        return {"ok": True, "message": "Kết nối OK với custom (model trả về rỗng)."}

    if not api_key:
        return {"ok": False, "message": "Chưa nhập API key."}

    cau = "Hãy trả lời đúng 1 từ: OK"
    try:
        if provider == "deepseek":
            tra_loi = _goi_deepseek(api_key, model, "Bạn là trợ lý.", cau, 0.2, 20)
        elif provider == "openai":
            tra_loi = _goi_openai(api_key, model, "Bạn là trợ lý.", cau, 0.2, 20)
        elif provider == "anthropic":
            tra_loi = _goi_anthropic(api_key, model, "Bạn là trợ lý.", cau, 0.2, 20)
        elif provider == "gemini":
            tra_loi = _goi_gemini(api_key, model, "Bạn là trợ lý.", cau, 0.2, 20)
        else:
            return {"ok": False, "message": f"Provider không hợp lệ: {provider}"}
    except Exception as e:
        chi_tiet = str(e)
        # Bọc lỗi HTTP để dễ đọc (vd 401 = key sai)
        if "401" in chi_tiet or "Invalid API key" in chi_tiet or "Unauthorized" in chi_tiet:
            return {"ok": False, "message": f"API key bị từ chối (401). Key không đúng hoặc hết hạn. Chi tiết: {chi_tiet[:200]}"}
        if "429" in chi_tiet:
            return {"ok": False, "message": f"Vượt giới hạn (429) hoặc key hết hạn. Chi tiết: {chi_tiet[:200]}"}
        return {"ok": False, "message": f"Lỗi khi gọi {provider}: {chi_tiet[:200]}"}

    if tra_loi:
        return {"ok": True, "message": f"Kết nối OK với {provider} ({model or 'model mặc định'}). Phản hồi: {tra_loi[:40]}"}
    return {"ok": True, "message": f"Kết nối OK với {provider} (model trả về rỗng)."}


def goi_ai(he_thong, nguoi_dung, nhiet_do=0.7, toi_da_tu=1500,
           tat_reasoning: bool = False) -> str:
    """Gọi AI theo provider trong config.json. Ném lỗi rõ ràng khi thiếu key.

    `tat_reasoning=True`: với provider 'custom' (OpenAI-compatible như api.b.ai),
    gửi kèm cờ `chat_template_kwargs.enable_thinking=false` để model hybrid KHÔNG
    sinh reasoning token -> nhanh hơn nhiều (~6x với qwen3.8-flash).
    AN TOÀN VỚI MODEL KHÁC: nếu endpoint/model không nhận cờ (HTTP 4xx),
    _goi_custom TỰ ĐỘNG retry không kèm cờ và ghi nhớ để lần sau bỏ cờ — không bao
    giờ gây lỗi cho bài viết chỉ vì model mới không hỗ trợ.
    """
    cfg = load_config()
    provider = cfg["ai"]["provider"] or "mock"
    api_key = (cfg["ai"].get("api_key") or "").strip()
    model = (cfg["ai"].get("model") or "").strip()
    base_url = (cfg["ai"].get("base_url") or "").strip()

    if provider == "mock":
        return _goi_mock(he_thong, nguoi_dung, nhiet_do, toi_da_tu)

    if provider == "custom":
        if not base_url:
            raise RuntimeError("config.json chưa có ai.base_url cho custom provider.")
        them = None
        if tat_reasoning:
            them = {
                "reasoning_effort": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            }
        return _goi_custom(api_key, base_url, model, he_thong, nguoi_dung, nhiet_do,
                           toi_da_tu, them_payload=them,
                           ten_coi_retry=f"{base_url}|{model}")

    if not api_key:
        raise RuntimeError(
            "config.json chưa có ai.api_key. Hoặc điền key API, hoặc để "
            "provider='mock' để chạy thử không cần key.")

    if provider == "deepseek":
        return _goi_deepseek(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu)
    if provider == "openai":
        return _goi_openai(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu)
    if provider == "anthropic":
        return _goi_anthropic(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu)
    if provider == "gemini":
        return _goi_gemini(api_key, model, he_thong, nguoi_dung, nhiet_do, toi_da_tu)
    raise RuntimeError(f"ai.provider không hợp lệ: {provider} "
                       "(chỉ nhận: mock, deepseek, openai, anthropic, gemini, custom)")


if __name__ == "__main__":
    # test nhanh: python ai_client.py
    cfg = load_config()
    print(f"Provider: {cfg['ai']['provider']}")
    print(goi_ai("Bạn là trợ lý.", "Chào bạn, giới thiệu 1 câu.")[:200])
