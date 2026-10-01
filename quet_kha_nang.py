# -*- coding: utf-8 -*-
"""Quet kha nang THAT cua tung KEY — doc thong ke, khong ghi bat ky file nao.

Cho moi chu de (KEY) trong Content Pool:
  * so bai HOAN_THANH cua vung dang chon
  * trong do: co bai bao (Article URL) / co anh bo_bai / co reel .mp4 ton tai
  * so bai du dieu kien dang len MASTER = HOAN_THANH + co Article URL + co anh
  * danh sach UID trong danh_ba_master.json theo KEY va vung
Muc tieu: biet duoc KEY nao du bai cho vong 1, KEY nao thieu bao nhieu.
"""
import json
import os
import sys

DUONG_DAN = os.path.dirname(os.path.abspath(__file__))
if DUONG_DAN not in sys.path:
    sys.path.insert(0, DUONG_DAN)

import vung as vung_mod  # noqa: E402
import content_pool as cp  # noqa: E402
import luong_b  # noqa: E402

STATUS_HOAN_THANH = luong_b.STATUS_HOAN_THANH
FOLDER_GOI_FB = os.path.join(DUONG_DAN, "du_lieu_fb")


def _doc_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def thu_thap():
    store = cp.get_store()
    ten_cot, dong = store.lay_bang("CONTENT POOL")
    i_status = ten_cot.index("Status")
    i_key = ten_cot.index("KEY")
    i_url = ten_cot.index("Article URL")
    i_cid = ten_cot.index("Content ID")
    col_vung = ten_cot.index("Vung") if "Vung" in ten_cot else None

    # bo sung cot Vung cho bai cu (mac dinh 'us') de loc dung
    dong_cp = []
    for d in dong:
        dd = dict(d)
        if col_vung is None or not (dd.get("Vung") or "").strip():
            dd["Vung"] = "us"
        dong_cp.append(dd)

    # index Goi_FB theo Content ID -> co file bo_bai?
    bo_bai_cid = set()
    for root, _dirs, files in os.walk(FOLDER_GOI_FB):
        for fn in files:
            if fn.startswith("bo_bai_") and fn.endswith(".json"):
                bo_bai_cid.add(fn[len("bo_bai_"):-len(".json")])

    theo_key = {}
    cho_dem_trung = {}
    for d in dong_cp:
        key = (d.get(i_key) or "").strip()
        if not key:
            continue
        k = theo_key.setdefault(key, {"HOAN_THANH": 0, "co_url": 0, "co_bo_bai": 0,
                                      "co_reel": 0, "du_kien": 0,
                                      "thieu_url": [], "thieu_reel": 0})
        st = (d.get(i_status) or "").strip()
        cid = (d.get(i_cid) or "").strip()
        if st != STATUS_HOAN_THANH:
            continue
        if not vung_mod.dung_vung(d, vung_mod.lay_vung()):
            continue
        k["HOAN_THANH"] += 1
        co_url = bool((d.get(i_url) or "").strip())
        co_bb = cid in bo_bai_cid
        co_reel = bool(luong_b.duong_dan_reel(cid))
        if co_url:
            k["co_url"] += 1
        else:
            k["thieu_url"].append(cid)
        if co_bb:
            k["co_bo_bai"] += 1
        if co_reel:
            k["co_reel"] += 1
        else:
            k["thieu_reel"] += 1
        if co_url and co_bb:
            k["du_kien"] += 1
        cho_dem_trung[cid] = cho_dem_trung.get(cid, 0) + 1

    # trùng lặp: đếm bài có So_lan_trung > 1 theo KEY
    trung = {}
    for d in dong_cp:
        key = (d.get(i_key) or "").strip()
        if not key:
            continue
        try:
            n = int(float(d.get("So_lan_trung") or 1))
        except Exception:
            n = 1
        if n > 1:
            trung[key] = trung.get(key, 0) + (n - 1)

    db = _doc_json(os.path.join(DUONG_DAN, "du_lieu_traffic", "danh_ba_master.json")) or {}
    ds_uid = []
    for uid, row in db.items():
        if not isinstance(row, dict):
            continue
        if (row.get("vung") or "us") != vung_mod.lay_vung():
            continue
        ds_uid.append({"uid": uid, "key": (row.get("key") or "").strip(),
                       "page": (row.get("page_name") or "").strip(),
                       "profile": (row.get("profile") or "").strip(),
                       "status": (row.get("trang_thai") or "").strip()})
    return theo_key, ds_uid, trung


def main():
    v = vung_mod.lay_vung()
    theo_key, ds_uid, trung = thu_thap()
    print(f"=== QUY HOACH VONG 1 — vung={v} ===")
    print(f"Danh ba {v}: {len(ds_uid)} UID "
          f"(live/trang thai khac: "
          f"{sum(1 for u in ds_uid if u['status'] != 'Live')})")
    print()
    print(f"{'KEY':<46}{'HT':>4}{'coURL':>6}{'coBB':>5}{'coReel':>7}{'duKien':>7}"
          f"{'thieuReel':>10}{'UID':>5}{'trung':>6}")
    tong_du = 0
    tong_uid = 0
    for key in sorted(theo_key, key=lambda k: -theo_key[k]["du_kien"]):
        s = theo_key[key]
        n_uid = sum(1 for u in ds_uid if u["key"] == key)
        tong_du += s["du_kien"]
        tong_uid += n_uid
        kt = key if len(key) <= 44 else key[:41] + "..."
        print(f"{kt:<46}{s['HOAN_THANH']:>4}{s['co_url']:>6}{s['co_bo_bai']:>5}"
              f"{s['co_reel']:>7}{s['du_kien']:>7}{s['thieu_reel']:>10}{n_uid:>5}"
              f"{trung.get(key, 0):>6}")
    print()
    print(f"TONG: du kien dang duoc {tong_du} bai | {tong_uid} UID trong danh ba {v}")
    thieu = [(k, s["HOAN_THANH"] - s["du_kien"]) for k, s in theo_key.items()
             if s["HOAN_THANH"] - s["du_kien"] > 0]
    if thieu:
        print("HOAN_THANH nhung CHUA du kien (thieu URL hoac thieu file bo_bai):")
        for k, n in sorted(thieu, key=lambda x: -x[1]):
            print(f"  - {k}: {n}")
    chi_phi = cp.lay_chi_phi() or {}
    print(f"\nTRANG THAI VIET TAT (content_pool.json): {json.dumps(chi_phi, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
