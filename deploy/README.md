# Chạy automaton51 24/7

AI chỉ làm việc khi máy chạy nó đang bật. Hướng dẫn đầy đủ từng bước, có đường dẫn: [HUONG-DAN-CAI-DAT.md](../HUONG-DAN-CAI-DAT.md).

| Tệp | Dùng khi nào |
|---|---|
| `cai-dat-windows.bat` | Windows: bấm đúp để cài (tự cài Python nếu thiếu), trả lời câu hỏi, tự chạy khi bật máy. Chạy lại để đổi thông tin. |
| `chay-tren-windows.bat` | Windows: chạy AI liên tục trong một cửa sổ; tự bật lại sau 30 giây nếu dừng. |
| `lenh-nhanh-windows.bat` | Windows: menu cho chủ sở hữu (tình trạng, đơn, hoàn tiền, rút quỹ 51 %, đổi thông tin, danh bạ, tạm dừng). |
| `cai-dat-mac-linux.sh` | macOS/Linux: `bash deploy/cai-dat-mac-linux.sh` (tạo `.venv`, cài, hỏi thông tin; macOS tự tạo mục chạy nền). |
| `automaton51.service` | Linux: dịch vụ systemd chạy 24/7. |

## Máy chủ Linux thuê theo tháng

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
sudo git clone https://github.com/nguyenquangphi0809-cloud/Le-Duan /opt/Le-Duan
cd /opt/Le-Duan && sudo bash deploy/cai-dat-mac-linux.sh      # hỏi tài khoản nhận tiền + khoá, rồi kiểm tra kết nối
sudo cp deploy/automaton51.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now automaton51
journalctl -u automaton51 -f                                  # xem nhật ký
```

Bảng điều khiển chỉ mở trên chính máy chủ (127.0.0.1:8451). Xem từ máy bạn qua đường hầm SSH:
`ssh -L 8451:127.0.0.1:8451 ten@may-chu` rồi mở http://localhost:8451.

Đổi thông tin trên máy chủ: `cd /opt/Le-Duan && sudo bash deploy/cai-dat-mac-linux.sh` (Enter để giữ mục cũ).
AI đang chạy tự khởi động lại để dùng thông tin mới.

## Cập nhật phiên bản mới

```bash
cd /opt/Le-Duan && sudo git pull && sudo systemctl restart automaton51
```

Windows: đóng cửa sổ AI, tải lại tệp ZIP và giải nén đè vào `C:\`, rồi bấm đúp `deploy\chay-tren-windows.bat`.

Thư mục `state/` (sổ cái, đơn hàng, khoá trong `.env`) không nằm trong git và tệp ZIP nên không bị ghi đè khi cập nhật.
