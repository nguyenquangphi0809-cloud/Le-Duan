# Hướng dẫn cài đặt từng bước

Làm **một lần**, khoảng 45–60 phút. Sau đó AI tự chạy: tìm khách qua email, báo giá, nhận tiền, làm việc, giao hàng,
chia lợi nhuận 51/49 và gửi báo cáo cho bạn mỗi sáng.

Hướng dẫn viết cho **Windows 10/11**. Dùng máy Mac hoặc máy chủ Linux thì xem [Phụ lục A](#phụ-lục-a--máy-mac) và
[Phụ lục B](#phụ-lục-b--máy-chủ-linux-thuê-theo-tháng).

---

## Chuẩn bị (đánh dấu trước khi bắt đầu)

- [ ] Một **máy tính bật liên tục, có Internet** (máy để bàn hoặc laptop cắm sạc). AI chỉ làm việc khi máy này bật.
- [ ] Một **địa chỉ Gmail** dùng cho kinh doanh (có thể dùng Gmail bạn đang dùng với Claude).
- [ ] Một **tài khoản ngân hàng nhận tiền**. Nên:
  - dùng tài khoản **riêng cho kinh doanh**, để dễ tách tiền cá nhân;
  - chọn số tài khoản **không phải số điện thoại** của bạn, vì số tài khoản hiện trên mã QR khách quét;
  - mở ở ngân hàng mà SePay kết nối trực tiếp, như MB Bank, VietinBank, BIDV (danh sách:
    <https://sepay.vn/ngan-hang.html>). Các ngân hàng này đều cho mở tài khoản trên ứng dụng trong khoảng 5 phút.
- [ ] Một **thẻ Visa/Mastercard thanh toán quốc tế** để nạp khoảng **20 USD** (khoảng 520.000 đ) tiền dùng Claude.
- [ ] (Tuỳ chọn) Danh bạ Google có email của người quen.

Trong lúc làm, bạn sẽ có **3 chuỗi bí mật**: khoá API Claude, mật khẩu ứng dụng Gmail, API token SePay.
Mở **Notepad** để dán tạm chúng, dán xong vào trình cài đặt thì **xoá Notepad đi, không lưu**.
Không gửi các chuỗi này cho ai, không dán vào khung chat (kể cả khi chat với Claude), không chụp màn hình đăng lên mạng.

| Bước | Việc | Thời gian |
|---|---|---|
| 1 | Tải phần mềm về máy | 5 phút |
| 2 | Tạo mật khẩu ứng dụng Gmail | 5 phút |
| 3 | Nạp tiền và tạo khoá API Claude | 10 phút |
| 4 | Nối tài khoản ngân hàng với SePay, lấy API token | 15 phút |
| 5 | Bấm đúp tệp cài đặt, dán thông tin | 10 phút |
| 6 | (Tuỳ chọn) Nhập danh bạ | 5 phút |
| 7 | Thử một đơn | 10 phút |

---

## Bước 1 — Tải phần mềm về máy

1. Bấm vào đường dẫn sau để tải tệp nén:
   <https://github.com/nguyenquangphi0809-cloud/Le-Duan/archive/refs/heads/main.zip>
   (hoặc mở <https://github.com/nguyenquangphi0809-cloud/Le-Duan>, bấm nút xanh **Code** → **Download ZIP**).
2. Mở thư mục **Downloads** (Tải xuống). Bấm chuột phải vào tệp `Le-Duan-main.zip` → **Properties** (Thuộc tính).
   Ở cuối thẻ **General**, nếu có ô **Unblock** (Bỏ chặn) thì tích vào → **OK**. Việc này giúp Windows không hỏi lại
   nhiều lần khi chạy tệp cài đặt. Không thấy ô này thì bỏ qua.
3. Bấm chuột phải vào tệp ZIP → **Extract All...** (Giải nén tất cả). Trong ô đường dẫn, xoá hết rồi gõ `C:\` →
   bấm **Extract**. Bạn sẽ có thư mục **`C:\Le-Duan-main`**.

> Vì sao đặt ở `C:\`? Thư mục Desktop, Documents thường được OneDrive đồng bộ; OneDrive có thể khoá tệp khi AI đang ghi.
> Sau khi cài, **không đổi tên, không di chuyển** thư mục này: sổ cái 51/49, đơn hàng và khoá nằm trong
> `C:\Le-Duan-main\state`.

---

## Bước 2 — Tạo mật khẩu ứng dụng Gmail

AI dùng mật khẩu này để đọc thư khách và gửi báo giá, kết quả. Mật khẩu Gmail thật của bạn không bị dùng tới.

1. Đăng nhập Gmail kinh doanh trên trình duyệt.
2. Bật **xác minh 2 bước** (nếu chưa bật): <https://myaccount.google.com/signinoptions/two-step-verification>
   → **Turn on** (Bật) và làm theo hướng dẫn. Số điện thoại ở đây chỉ để Google xác minh bạn, khách không nhìn thấy.
3. Mở <https://myaccount.google.com/apppasswords>.
   - Ô **App name**: gõ `automaton51` → **Create** (Tạo).
   - Google hiện **16 chữ cái** trong khung (dạng `abcd efgh ijkl mnop`). Chép vào Notepad. Có dấu cách cũng được,
     trình cài đặt tự bỏ dấu cách.
   - Nếu trang báo *"The setting you are looking for is not available"*: bạn chưa bật xác minh 2 bước, hoặc đây là
     Gmail do cơ quan/trường quản lý. Hãy dùng Gmail cá nhân.
4. **Không cần bật IMAP**: từ tháng 1/2025 Gmail luôn bật sẵn.

Địa chỉ khách gửi thư tới sẽ là `tên-gmail-của-bạn+hocthuat@gmail.com` (thư vẫn về cùng hộp thư của bạn). AI chỉ xử lý
thư gửi tới địa chỉ có `+hocthuat` này, không đụng tới thư cá nhân và không đánh dấu thư của bạn là đã đọc.

---

## Bước 3 — Nạp tiền và tạo khoá API Claude

Đây là "bộ não" làm việc cho khách. Trang dành cho nhà phát triển này tính tiền **riêng**, không dùng chung với gói
Claude Pro/Max (nếu bạn có).

1. Mở <https://platform.claude.com> → đăng nhập (có thể bấm **Continue with Google** bằng Gmail ở bước 2).
2. **Nạp tiền:** mở <https://platform.claude.com/settings/billing> → **Buy credits** → nhập `20` (USD) → nhập thẻ →
   xác nhận. Tiền nạp dùng được trong 1 năm và không hoàn lại.
3. **Nên bật tự nạp** (để AI không bao giờ phải dừng vì hết tiền): cùng trang Billing, mục **Auto-reload** → **Edit** →
   bật lên, đặt "khi số dư dưới **5** USD thì nạp lên **20** USD". Nếu không bật, khi hết tiền AI sẽ gửi bạn email
   **"[CẦN BẠN] Hết tiền API Claude"**; đơn của khách được giữ nguyên chờ bạn nạp, **không bị huỷ hay hoàn tiền**.
4. **Tạo khoá:** mở <https://platform.claude.com/settings/keys> → **Create Key** → tên `automaton51` → **Add** →
   bấm **Copy**. Khoá bắt đầu bằng `sk-ant-` và **chỉ hiện một lần**, dán ngay vào Notepad.

---

## Bước 4 — Nối ngân hàng với SePay và lấy API token

SePay báo cho AI mỗi khi tài khoản nhận tiền có tiền vào, để AI biết khách nào đã trả (dựa vào mã đơn trong nội dung
chuyển khoản). SePay miễn phí **500 giao dịch/tháng trong năm đầu** cho cá nhân kinh doanh (xem
<https://sepay.vn/bang-gia.html>). SePay chỉ **xem** giao dịch, không rút được tiền của bạn.

1. Đăng ký tại <https://my.sepay.vn/register> (hướng dẫn: <https://docs.sepay.vn/dang-ky-sepay.html>).
2. Nối tài khoản ngân hàng nhận tiền: trong my.sepay.vn chọn menu **Ngân hàng** → **Kết nối tài khoản** → chọn
   **Cá nhân** → chọn ngân hàng → làm theo hướng dẫn và xác nhận trên ứng dụng ngân hàng
   (hướng dẫn chi tiết từng ngân hàng: <https://docs.sepay.vn/them-tai-khoan-ngan-hang.html>).
3. Tạo API token: menu **Cấu hình Công ty** → **API Access** → **+ Thêm API** → tên `automaton51` → **Thêm** →
   sao chép token ở cột API Token (hướng dẫn: <https://docs.sepay.vn/tao-api-token.html>). Dán vào Notepad.

---

## Bước 5 — Bấm đúp tệp cài đặt

1. Mở thư mục `C:\Le-Duan-main\deploy` → bấm đúp **`cai-dat-windows.bat`**.
   - Nếu hiện khung xanh **"Windows protected your PC"** (Windows đã bảo vệ PC của bạn): bấm **More info**
     (Thông tin thêm) → **Run anyway** (Vẫn chạy).
   - Nếu hiện **"Open File – Security Warning"**: bấm **Run** (Chạy).
   - Máy chưa có Python thì tệp tự cài Python 3.13 (1–3 phút). Windows hỏi *"Do you want to allow this app to make
     changes…?"* thì bấm **Yes**.
2. Một cửa sổ đen hiện câu hỏi. Gõ câu trả lời rồi bấm **Enter**:

   | Câu hỏi trên màn hình | Bạn nhập |
   |---|---|
   | Gmail dùng cho kinh doanh | địa chỉ Gmail ở bước 2 |
   | Tên bạn (ký tên trong thư) | ví dụ `TS. Nguyễn Văn A` |
   | Ngân hàng | `mbbank`, `vietinbank`, `bidv`, `vcb`, `tcb`, `acb`, `vpbank`, `tpbank`… |
   | Số tài khoản | số tài khoản nhận tiền (có dấu cách cũng được) |
   | Tên chủ tài khoản | gõ có dấu cũng được, hệ thống tự đổi thành `NGUYEN VAN A` |
   | Khoá API Claude | dán khoá `sk-ant-…` |
   | Mật khẩu ứng dụng Gmail | dán 16 chữ |
   | API token SePay | dán token |
   | Page access token Facebook | bấm **Enter** để bỏ qua (xem [Phụ lục C](#phụ-lục-c--trang-facebook-tuỳ-chọn)) |
   | Số tiền đã nạp vào API Claude (USD) | `20` (số bạn nạp ở bước 3) |

   **Cách dán:** bấm **chuột phải** vào cửa sổ đen (hoặc **Ctrl+V**), rồi **Enter**. Khi dán khoá và mật khẩu, màn
   hình **không hiện gì** — đó là để bảo mật, không phải lỗi. Cuối bước, dòng *"Khoá đã có"* hiện vài ký tự đầu/cuối
   để bạn đối chiếu.
3. Trình cài đặt tự **kiểm tra kết nối**. Mọi dòng phải có dấu **✓**. Có dấu **✗** thì xem
   [Xử lý sự cố](#xử-lý-sự-cố), sửa xong bấm đúp lại `cai-dat-windows.bat` (mục nào đúng rồi chỉ cần bấm Enter).
4. **Quét mã QR mẫu:** mở đường dẫn *"Mã QR mẫu"* trên màn hình bằng trình duyệt, quét bằng ứng dụng ngân hàng trên
   điện thoại. Phải hiện **đúng tên và số tài khoản của bạn**, số tiền 10.000 đ, nội dung `HTTHU01`.
   **Không cần chuyển tiền**, chỉ để kiểm tra rồi thoát.
5. Khi hỏi *"Tắt chế độ ngủ khi cắm sạc"* → bấm **Enter** (đồng ý).
6. Xong. AI chạy trong cửa sổ thu nhỏ **"automaton51 - AI dang lam viec"** trên thanh tác vụ.
   - **Đừng đóng cửa sổ này** — đóng là dừng AI.
   - Từ lần bật máy sau, AI **tự chạy** khi bạn đăng nhập Windows.
   - Xem tình hình trên trình duyệt: <http://localhost:8451> (chỉ mở được trên chính máy này).

---

## Bước 6 — (Tuỳ chọn) Nhập danh bạ

AI gửi **một** thư xin phép tới người quen có email trong danh bạ; ai đồng ý mới nhận thông tin dịch vụ. Hệ thống chỉ
dùng **tên và email**, không dùng số điện thoại, không nhắn Zalo hay SMS.

1. Mở <https://contacts.google.com> → **Export** (Xuất) → chọn **Google CSV** → **Export**. Tệp `contacts.csv` về thư
   mục Downloads (hướng dẫn của Google: <https://support.google.com/contacts/answer/7199294>).
   - Danh bạ ở iPhone (iCloud): mở <https://www.icloud.com/contacts>, chọn tất cả → **Export vCard**; vào
     contacts.google.com → **Import** tệp đó; rồi xuất Google CSV như trên.
2. Bấm đúp `C:\Le-Duan-main\deploy\lenh-nhanh-windows.bat` → gõ `7` → **Enter** → **Enter** (dùng
   `contacts.csv` trong Downloads). Tệp để chỗ khác thì kéo-thả tệp vào cửa sổ đen rồi **Enter**.
3. Màn hình báo số người ở nhóm A (người giới thiệu), B (khách tiềm năng), C (không gửi). Sau đó bạn có thể xoá tệp CSV.

Nhịp gửi: tối đa 25 thư/ngày, từ 8 đến 20 giờ, mỗi người đúng một thư; ai từ chối sẽ không bao giờ nhận thư nữa.
Chỉ liên hệ có địa chỉ email mới dùng được.

---

## Bước 7 — Thử một đơn

1. Từ **một địa chỉ email khác** (của bạn hoặc người nhà), gửi thư tới `tên-gmail-của-bạn+hocthuat@gmail.com`, tiêu đề
   `Nhờ định dạng luận văn`, đính kèm một tệp Word `.docx` vài trang.
2. Trong vài phút, địa chỉ đó nhận thư báo giá có mã đơn (dạng `HTABC234`) và mã QR.
3. Muốn thử trọn vòng: chuyển khoản đúng số tiền, đúng nội dung từ **một tài khoản khác của bạn** (tiền vẫn về túi bạn,
   chỉ tốn phí Claude xử lý). Vài phút sau có thư *"Đã nhận thanh toán"*, sau đó là thư kết quả kèm tệp.
4. Xem đơn: bấm đúp `lenh-nhanh-windows.bat` → gõ `2`.

---

## Hằng ngày bạn làm gì?

**Không phải làm gì.** 8 giờ sáng mỗi ngày bạn nhận email **"[automaton51] Báo cáo ngày …"**: tiền về, đơn đã giao,
quỹ 51 % của bạn, quỹ mở rộng 49 %.

Chỉ khi có email tiêu đề **[CẦN BẠN]** mới cần làm một việc. Mọi việc đều qua tệp
`C:\Le-Duan-main\deploy\lenh-nhanh-windows.bat` (bấm đúp, gõ số hoặc chữ, Enter):

| Email [CẦN BẠN] | Việc của bạn |
|---|---|
| Đơn HT…: hoàn tiền … đ | Trong ứng dụng ngân hàng, chuyển lại số tiền đó cho người đã chuyển khoản với nội dung là mã đơn → mở lệnh nhanh, gõ `3`, nhập mã đơn. AI tự báo khách. |
| Tiền vào thiếu mã đơn — có thể là đơn HT… | Nếu đúng là khách đó (xem tên người chuyển trong ứng dụng ngân hàng) → gõ `T`, nhập mã đơn. Không phải thì bỏ qua. |
| Hết tiền API Claude | Nạp tiền tại <https://platform.claude.com/settings/billing> (hoặc bật Auto-reload). AI tự làm tiếp. |
| Khoá API Claude bị từ chối | Tạo khoá mới (Bước 3.4) → gõ `6`, bấm Enter qua các mục, dán khoá mới. |

**Tiền 51 % của bạn:** tiền khách trả đã nằm sẵn trong tài khoản nhận tiền của bạn. Sổ cái chia mỗi đồng lợi nhuận:
51 % là của bạn, 49 % để lại cho kinh doanh (trả tiền Claude, mở rộng). Khi bạn chuyển phần 51 % sang tài khoản cá nhân,
gõ `4` để ghi sổ. Sổ cái tính bằng USD, quy đổi 1 USD = 26.000 đ (đổi được trong `state\config.json`, mục
`vnd_per_usd`).

**Menu lệnh nhanh đầy đủ:** `1` tình trạng · `2` đơn đang mở · `3` đã hoàn tiền · `T` xác nhận tiền thiếu mã ·
`4` đã rút quỹ 51 % · `5` đã nạp thêm tiền Claude · `6` đổi thông tin · `7` nhập danh bạ · `8` kiểm tra kết nối ·
`9` tạm dừng AI · `C` cho AI chạy tiếp · `B` mở bảng điều khiển · `0` thoát.

---

## Đổi thông tin (tài khoản nhận tiền, khoá, Gmail)

Bấm đúp `lenh-nhanh-windows.bat` → gõ `6`. Mục nào giữ nguyên thì bấm **Enter**, mục cần đổi thì gõ giá trị mới.
AI đang chạy sẽ tự khởi động lại trong vài phút để dùng thông tin mới. Nhớ quét lại mã QR mẫu khi đổi tài khoản
nhận tiền.

## Máy tính: vài lưu ý để AI chạy liên tục

- **Laptop:** luôn cắm sạc. Để gập máy mà không ngủ: Control Panel → Power Options → *Choose what closing the lid does*
  → *When I close the lid* (Plugged in) = **Do nothing**.
- **Windows Update** khởi động lại máy: AI tự chạy lại khi bạn **đăng nhập Windows**. Để máy ít khởi động lại vào
  ban ngày: Settings → Windows Update → Advanced options → **Active hours**.
- Máy tắt thì AI nghỉ; thư và tiền của khách vẫn được giữ, AI xử lý tiếp khi máy bật lại.
- Muốn chạy 24/7 không phụ thuộc máy ở nhà: thuê máy chủ, xem [Phụ lục B](#phụ-lục-b--máy-chủ-linux-thuê-theo-tháng).

## Tạm dừng, dừng hẳn, gỡ bỏ

- **Tạm dừng** (AI vẫn mở nhưng không làm gì): lệnh nhanh → `9`. Chạy tiếp: `C`.
- **Dừng:** đóng cửa sổ "automaton51 - AI dang lam viec". Chạy lại: bấm đúp `deploy\chay-tren-windows.bat`.
- **Bỏ tự chạy khi bật máy:** bấm `Windows + R`, gõ `shell:startup`, Enter → xoá tệp `automaton51.cmd`.
- **Gỡ hẳn:** làm bước trên, rồi xoá thư mục `C:\Le-Duan-main` (sao lưu thư mục `state` trước nếu cần giữ sổ sách).
  Thu hồi khoá: xoá khoá ở <https://platform.claude.com/settings/keys>, xoá mật khẩu ứng dụng ở
  <https://myaccount.google.com/apppasswords>, xoá API ở SePay (Cấu hình Công ty → API Access).

## Sao lưu

Thư mục `C:\Le-Duan-main\state` chứa sổ cái 51/49, đơn hàng và khoá (tệp `.env`). Thỉnh thoảng chép cả thư mục sang
USB. Giữ kín bản sao vì có khoá bên trong.

## Cập nhật phiên bản mới

1. Đóng cửa sổ "automaton51 - AI dang lam viec".
2. Tải lại tệp ZIP ở Bước 1, giải nén vào `C:\` như cũ; Windows hỏi thì chọn **Replace the files in the destination**
   (Thay thế). Thư mục `state` không có trong tệp ZIP nên sổ sách và khoá được giữ nguyên.
3. Bấm đúp `deploy\chay-tren-windows.bat`.

---

## Xử lý sự cố

| Hiện tượng / dòng có dấu ✗ | Cách sửa |
|---|---|
| `Claude API: khoá sai hoặc đã bị xoá` | Tạo khoá mới (Bước 3.4), chạy lại `cai-dat-windows.bat`, dán khoá mới. |
| `Claude API: tài khoản API chưa có tiền` | Nạp tiền (Bước 3.2). |
| `Gmail IMAP` / `Gmail SMTP: sai địa chỉ Gmail hoặc mật khẩu ứng dụng` | Tạo lại mật khẩu ứng dụng (Bước 2) cho **đúng** Gmail đã nhập. |
| `Gmail …: không kết nối được máy chủ Gmail` | Kiểm tra Internet; phần mềm diệt virus hoặc tường lửa có thể chặn, hãy cho phép Python kết nối. |
| `SEPAY_API_TOKEN: (chưa có)` hoặc `SePay: … 401` | Làm lại Bước 4.3, chạy lại cài đặt, dán token. |
| `SePay: đọc được giao dịch (0 …)` | Bình thường với tài khoản mới chưa có giao dịch. |
| Cửa sổ báo không tự cài được Python | Cài Python tại <https://www.python.org/downloads/windows/>, khi cài **tích ô "Add python.exe to PATH"**, rồi bấm đúp lại `cai-dat-windows.bat`. |
| Khung xanh "Windows protected your PC" | **More info** → **Run anyway**. |
| Mã QR mẫu sai tên hoặc số tài khoản | Lệnh nhanh → `6`, sửa ngân hàng, số tài khoản hoặc tên chủ tài khoản. |
| Không thấy email báo cáo | Ngày đầu tiên không gửi báo cáo. Xem thư mục Spam. Kiểm tra cửa sổ AI còn chạy. |
| Khách nói đã chuyển tiền mà chưa nhận kết quả | Lệnh nhanh → `2` xem trạng thái đơn. Nếu khách quên ghi mã đơn, AI tự khớp khi số tiền và tên người chuyển trùng khớp; không chắc thì AI gửi bạn email [CẦN BẠN] để xác nhận (gõ `T`). |
| Cửa sổ AI hiện "đang chạy trong một cửa sổ khác" | Bình thường: AI đã chạy rồi, cửa sổ mới tự đóng. |

Muốn xem AI đang làm gì: mở cửa sổ AI trên thanh tác vụ, hoặc <http://localhost:8451>.

---

## Phụ lục A — Máy Mac

1. Tải ZIP ở Bước 1. Safari tự giải nén thành thư mục `Le-Duan-main` trong Downloads. Kéo thư mục này vào **thư mục
   nhà** của bạn (Finder → Go → Home). Không để trong Desktop, Documents hay Downloads, vì macOS chặn chương trình chạy
   nền đọc các thư mục đó.
2. Cài Python từ <https://www.python.org/downloads/macos/>. Cài xong, mở thư mục **Applications → Python 3.x** và bấm
   đúp **Install Certificates.command** (cần để kết nối an toàn tới Gmail).
3. Làm Bước 2, 3, 4 như trên.
4. Mở **Terminal** (Applications → Utilities → Terminal), gõ:

   ```bash
   cd ~/Le-Duan-main
   bash deploy/cai-dat-mac-linux.sh
   ```

   Trả lời các câu hỏi như Bước 5. Trình cài đặt tạo mục chạy nền để AI tự chạy mỗi khi bạn đăng nhập máy Mac.
5. Để máy không ngủ khi cắm sạc: System Settings → Battery (MacBook) hoặc Energy (máy để bàn) → bật
   *Prevent automatic sleeping … when the display is off*.
6. Lệnh cho chủ sở hữu (gõ trong Terminal, sau `cd ~/Le-Duan-main`):

   | Việc | Lệnh |
   |---|---|
   | Tình trạng | `.venv/bin/python -m automaton51 --state state status` |
   | Đơn đang mở | `.venv/bin/python -m automaton51 --state state orders` |
   | Đã hoàn tiền | `.venv/bin/python -m automaton51 --state state refund HTABC234` |
   | Xác nhận tiền thiếu mã | `.venv/bin/python -m automaton51 --state state paid HTABC234` |
   | Đã rút quỹ 51 % | `.venv/bin/python -m automaton51 --state state payout` |
   | Đổi thông tin | `bash deploy/cai-dat-mac-linux.sh` |
   | Nhập danh bạ | `.venv/bin/python -m automaton51 --state state outreach import ~/Downloads/contacts.csv` |
   | Dừng hẳn | `launchctl unload ~/Library/LaunchAgents/vn.automaton51.plist` |

## Phụ lục B — Máy chủ Linux thuê theo tháng

Chạy 24/7 không phụ thuộc máy ở nhà. Máy chủ Ubuntu 22.04/24.04 nhỏ nhất (1 CPU, 1 GB RAM) là đủ.

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
sudo git clone https://github.com/nguyenquangphi0809-cloud/Le-Duan /opt/Le-Duan
cd /opt/Le-Duan && sudo bash deploy/cai-dat-mac-linux.sh      # hỏi thông tin như Bước 5, rồi kiểm tra kết nối
sudo cp deploy/automaton51.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now automaton51
journalctl -u automaton51 -f                                  # xem AI đang làm gì (Ctrl+C để thoát)
```

Chi tiết và cách mở bảng điều khiển từ xa: [deploy/README.md](deploy/README.md).

## Phụ lục C — Trang Facebook (tuỳ chọn)

Không bắt buộc: bán hàng tự động chạy qua email. Nếu muốn AI tự đăng mỗi ngày một bài lên Trang Facebook của dịch vụ:

1. Tạo Trang (nếu chưa có): <https://www.facebook.com/pages/create>. Không cần ghi số điện thoại lên Trang.
2. Tạo ứng dụng tại <https://developers.facebook.com/apps> → **Create App** → chọn trường hợp sử dụng quản lý Trang
   (Manage everything on your Page).
3. Mở Graph API Explorer <https://developers.facebook.com/tools/explorer>: chọn ứng dụng vừa tạo → thêm quyền
   `pages_show_list`, `pages_manage_posts`, `pages_read_engagement` → **Generate Access Token** → chọn Trang.
4. Đổi sang token dài hạn: dán token vào <https://developers.facebook.com/tools/debug/accesstoken> → **Extend Access
   Token**. Quay lại Graph API Explorer với token dài hạn, gọi `me/accounts`: dòng của Trang có `access_token`
   (Page access token) và `id` (ID Trang).
5. Lệnh nhanh → `6` → Enter qua các mục, dán Page access token, rồi nhập ID Trang khi được hỏi.

Hướng dẫn chính thức của Meta: <https://developers.facebook.com/docs/pages-api/getting-started>.
