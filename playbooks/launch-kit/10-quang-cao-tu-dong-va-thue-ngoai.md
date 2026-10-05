# Quảng cáo: kênh tự động và phương án thuê ngoài

Số liệu khảo sát tháng 10/2026 (đoạn trích công khai trên mạng, chưa đối chiếu hết trang gốc; tỷ giá 1 USD ≈ 26.000 đ).
Nguyên tắc chung: **tiền quảng cáo chỉ lấy từ Quỹ mở rộng 49%**; Quỹ chủ sở hữu 51% không bao giờ bị đụng tới.

## 1. Kênh tự động hệ thống đang chạy (0 đồng)

| Kênh | Hệ thống làm gì | Bạn làm gì |
|---|---|---|
| Trang Facebook | 1 bài/ngày từ tệp 08, chia lượt hai ngách theo lãi gộp, tự gắn lời mời cuối bài | Tạo Trang một lần, dán token khi `setup` |
| Email danh bạ | Một thư xin phép [QC] cho mỗi người nhóm A, B, G; chỉ người trả lời "có" mới nhận bảng giá | Xuất danh bạ CSV, chạy `outreach import` |
| Mồi câu khách | Checklist 20 lỗi (A), chuyển phông miễn phí (B) | Không |
| Báo cáo | Lãi gộp, tỷ trọng từng ngách, tiền quảng cáo đã chi, mỗi sáng | Đọc |

Trang Facebook phải là **Trang** (Page). Không thể đăng tự động lên trang cá nhân: Facebook đã bỏ quyền này từ 2018.
Bạn có thể đặt tên Trang theo tên mình kèm lĩnh vực, ví dụ "[Tên bạn] – Hồ sơ bảo vệ luận án & sử liệu địa phương";
Trang thuộc quyền quản trị của tài khoản Facebook cá nhân của bạn.

## 2. Quảng cáo trả tiền tự động (tuỳ chọn, mặc định TẮT)

**Cách chạy:** mỗi 7 ngày hệ thống chọn bài ngách A có nhiều tương tác nhất trong 21 ngày, chạy quảng cáo "tăng tương
tác bài viết" với ngân sách trọn đợt = min(700.000 đ; 50% Quỹ mở rộng ÷ 1,1). Meta cộng thuế GTGT 10% (từ 1/7/2025),
hệ thống ghi sổ cả phần thuế. Mỗi đợt tối thiểu 140.000 đ và chỉ dùng tối đa một nửa quỹ, nên Quỹ mở rộng dưới khoảng
310.000 đ thì chưa chạy. Bài ngách B không bao giờ được chạy quảng cáo
(quảng cáo nhắc tới đảng phái dễ bị Meta xếp vào nhóm "chính trị", phải xác minh danh tính và ghi "Được tài trợ bởi").

**Bật một lần (khoảng 40 phút):**

1. Vào https://business.facebook.com, tạo "Danh mục đầu tư kinh doanh" (Business portfolio), thêm Trang của bạn.
2. Trong Cài đặt doanh nghiệp → Tài khoản quảng cáo → Tạo mới: tiền tệ **VND**, múi giờ Hồ Chí Minh. Thêm phương thức
   thanh toán (thẻ Visa/Master, hoặc nạp trước qua ví điện tử). Có thể đặt **giới hạn chi tiêu tài khoản** để chặn thêm một lớp.
3. Vào https://developers.facebook.com → Ứng dụng của tôi → Tạo ứng dụng loại "Doanh nghiệp", thêm sản phẩm
   "Marketing API", chuyển ứng dụng sang chế độ **Live** (bài đăng ở chế độ phát triển có thể chỉ người trong ứng dụng thấy).
4. Cài đặt doanh nghiệp → Người dùng → **Người dùng hệ thống** → Thêm; gán tài sản: Trang (toàn quyền) và tài khoản
   quảng cáo (toàn quyền). Bấm "Tạo mã", chọn ứng dụng ở bước 3, chọn quyền: `ads_management`, `ads_read`,
   `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`.
5. Chạy `automaton51 setup` (hoặc lenh-nhanh mục 6): dán mã ở dòng "Token quảng cáo Meta" (gõ ẩn, lưu vào tệp `.env`
   trong thư mục state, không lên GitHub), rồi nhập số tài khoản quảng cáo (dãy số sau `act_`). Hệ thống tự bật quảng cáo.
6. Chạy `automaton51 doctor`: dòng "Quảng cáo Meta: … đang hoạt động" là xong. Xem tình hình: `automaton51 ads status`.

Không bao giờ gửi mã, mật khẩu hay mã 2 lớp qua chat, email hay cho người lạ. Muốn dừng: đặt `ads_enabled` thành
`false` trong `config.json` (hoặc tắt chiến dịch trong Trình quản lý quảng cáo).

## 3. Chi phí tham khảo

| Hạng mục | Con số | Độ tin cậy |
|---|---|---|
| Meta tại Việt Nam: CPM | khoảng 15.000–73.000 đ / 1.000 lượt hiển thị | thấp–trung bình |
| Meta: CPC | 1.500–6.000 đ/lượt bấm; 3.000–12.000 đ/tin nhắn (chủ yếu ngành bán lẻ) | thấp |
| Google Ads nhóm "khoá học" | 10.000–50.000 đ/lượt bấm | thấp–trung bình |
| Thuế | Meta và Google cộng 10% GTGT trên hoá đơn; hộ kinh doanh thường không khấu trừ được | cao |
| Thuê freelancer | 3–5 triệu/tháng (bán thời gian) | thấp–trung bình |
| Agency Facebook | phí 15–20% ngân sách, nhiều nơi yêu cầu ngân sách tối thiểu khoảng 9–10 triệu/tháng | trung bình |
| Chăm sóc Trang (15 bài/tháng) | 2,5–5 triệu/tháng | trung bình |

Lưu ý: nhiều bảng "giá click ngành giáo dục" trên blog Việt Nam là số liệu Mỹ quy đổi, không dùng được.

## 4. Ba phương án (tổng mỗi tháng, đã gồm thuế)

| Phương án | Tổng/tháng | Khi nào chọn |
|---|---|---|
| **Tự chạy bằng hệ thống** | tối đa 770.000 đ mỗi 7 ngày (đã gồm thuế), tức khoảng 3,3 triệu/tháng, tuỳ Quỹ mở rộng | 2–3 tháng đầu: đo chi phí trên mỗi khách thật |
| **Freelancer theo KPI** | 6,5–10 triệu (4–6 triệu quảng cáo + phí 2–3 triệu + thưởng theo khách) | Khi đã biết bài nào ra khách, muốn tăng tốc |
| **Agency** | 10–12 triệu (13–17 triệu nếu thuê thêm chăm sóc Trang) | Khi Quỹ mở rộng đều đặn trên 10 triệu/tháng và chi phí/khách đã kiểm chứng |

**Khuyến nghị:** thị trường nghiên cứu sinh nhỏ (cả nước tuyển khoảng 2.000 người/năm), nên tháng 1–3 dùng kênh tự
động + quảng cáo tự chạy ngân sách nhỏ; uy tín và giới thiệu của thầy cô là kênh chính. Chỉ thuê ngoài khi chi phí trên
mỗi đơn trả tiền đã rõ và thấp hơn 15% giá trị đơn.

## 5. Mẫu điều khoản khi thuê người chạy quảng cáo

- **Khách đủ điều kiện:** nghiên cứu sinh/học viên ghi rõ trường, ngành, dự kiến bảo vệ trong 12 tháng, email thật,
  nhu cầu cụ thể; loại khách trùng.
- **Cách trả (chọn một):** (1) cố định 1,5–2 triệu + 100.000–200.000 đ mỗi khách đủ điều kiện, có trần tháng;
  (2) 5–10% giá trị đơn chốt trong 60 ngày, đối soát bằng email; (3) thử 30 ngày với KPI chi phí/khách.
- **Luôn ghi trong hợp đồng:** tài khoản quảng cáo, Trang, dữ liệu thuộc về bạn; báo cáo kèm số liệu gốc; cấm tương
  tác ảo ("seeding"); không dùng lời hứa "đỗ", "trọn gói", "viết thuê".
- Sau mỗi lần trả tiền cho người chạy quảng cáo, ghi sổ để Quỹ mở rộng phản ánh đúng:
  `automaton51 ads spend 2500000 --memo "Freelancer tháng 11"`.

## 6. Rủi ro và cách phòng

1. **Lừa "chạy quảng cáo giá rẻ":** đã có vụ chiếm đoạt khoảng 1,5 tỷ đồng (2024–2025). Chỉ nạp tiền vào tài khoản
   quảng cáo đứng tên mình.
2. **Mất Trang:** ứng dụng giả mạo "Ad Manager" đánh cắp đăng nhập. Không đưa mật khẩu, mã 2 lớp; cấp quyền đối tác qua
   Meta Business Suite, chỉ quyền cần dùng, bạn giữ toàn quyền.
3. **Thuê "tài khoản agency":** tài khoản thuộc bên cho thuê, bị khoá là mất hết. Dùng tài khoản của mình.
4. **Số liệu ảo:** tài khoản đứng tên bạn nên bạn xem được số liệu gốc; chỉ trả cho khách đã xác minh.
5. **Vi phạm chính sách:** Google cấm dịch vụ gian lận học thuật (viết bài, thi hộ); quảng cáo về luận văn hay bị
   duyệt chặt. Mô tả đúng: biên tập, định dạng, dịch; công khai "không viết hộ".
6. **Danh tiếng:** cộng đồng giám sát liêm chính học thuật rất lớn. Không bao giờ quảng cáo kiểu "đảm bảo qua", "trọn gói".
