# Ôn thi trắc nghiệm

- `on_thi.html` — trang ôn thi (372 câu), mở bằng bất kỳ trình duyệt nào, kể cả Safari trên iPhone, không cần mạng.
- `Bo_cau_hoi.xlsx` — bộ câu hỏi gốc.
- `tao_trang_on_thi.py` + `mau_on_thi.html` — tạo lại trang khi sửa/bổ sung câu hỏi:

```
pip install openpyxl
python on-thi/tao_trang_on_thi.py
```

Chế độ: Luyện tập (biết đúng/sai ngay, kèm chú giải), Thi thử (ngẫu nhiên, tính giờ, chấm điểm),
Ôn câu sai (tự lưu trên trình duyệt), Xem đáp án. Có thể lọc theo chủ đề (TD.01 … TD.13).
