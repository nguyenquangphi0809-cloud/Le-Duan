"""Tạo trang ôn thi trắc nghiệm (một file HTML) từ bộ câu hỏi Excel.

Cách dùng:
    pip install openpyxl
    python tao_trang_on_thi.py [Bo_cau_hoi.xlsx] [on_thi.html]

File Excel cần các cột: STT | Mã câu hỏi | Nội dung câu hỏi | Đáp án A | B | C | D | Đáp án | Chú Giải
Mở file HTML tạo ra bằng trình duyệt (máy tính hoặc điện thoại), không cần mạng.
"""
import json
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).parent


def doc_cau_hoi(duong_dan):
    ws = openpyxl.load_workbook(duong_dan, data_only=True).active
    cau_hoi = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or r[2] is None:
            continue
        sach = lambda v: "" if v is None else " ".join(str(v).split())
        dap_an = sach(r[7]).upper()[:1]
        if dap_an not in "ABCD" or not dap_an:
            print(f"Bỏ qua câu {r[1]}: đáp án không hợp lệ '{r[7]}'")
            continue
        cau_hoi.append({
            "id": sach(r[1]) or f"#{r[0]}",
            "q": sach(r[2]),
            "o": [sach(v) for v in r[3:7]],
            "a": "ABCD".index(dap_an),
            "g": sach(r[8]) if len(r) > 8 else "",
        })
    return cau_hoi


def main():
    nguon = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "Bo_cau_hoi.xlsx"
    dich = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "on_thi.html"
    cau_hoi = doc_cau_hoi(nguon)
    mau = (HERE / "mau_on_thi.html").read_text(encoding="utf-8")
    du_lieu = json.dumps(cau_hoi, ensure_ascii=False).replace("</", "<\\/")
    dich.write_text(mau.replace("/*__DATA__*/[]", du_lieu), encoding="utf-8")
    print(f"Đã tạo {dich} với {len(cau_hoi)} câu hỏi.")


if __name__ == "__main__":
    main()
