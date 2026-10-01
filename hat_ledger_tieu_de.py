# -*- coding: utf-8 -*-
"""Seed du_lieu_traffic/tieu_de_da_dung.json từ toàn bộ bài đã đăng trên web.

Mục đích: bài MỚI không được đặt tiêu đề trùng với bài CŨ đang sống trên site
(Google đánh giá nội dung trùng = spam). Chạy 1 lần; về sau ledger tự lớn dần
mỗi lần cấp tiêu đề (viet_lai.ghi_tieu_de_da_dung).
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import viet_lai as vl  # noqa: E402

DUONG = vl._duong_dan_ledger()
da = set()
nguon = {'heading': 0, 'tieu_de': 0, 'canned': 0}

for p in glob.glob(os.path.join('du_lieu_fb', '**', 'bo_bai_*.json'), recursive=True):
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:
        continue
    for k in ('tieu_de',):
        t = vl._chuan_td(d.get(k) or '')
        if t and 'exclusive' not in t and 'insight' not in t:
            da.add(t)
            nguon['tieu_de'] += 1
    hd = vl._chuan_td(vl.heading_trong_bai(d.get('bai_bao') or ''))
    if hd:
        da.add(hd)
        nguon['heading'] += 1

ds = sorted(da)
with open(DUONG, 'w', encoding='utf-8') as f:
    json.dump({'danh_sach': ds, 'cap_nhat': 'seed tu bai da dang', 'so_luong': len(ds)},
              f, ensure_ascii=False, indent=0)
sys.stdout.buffer.write(
    f'ledger = {DUONG}\n{len(ds)} tieu de da ngan dung  {nguon}\n'.encode('utf-8'))
