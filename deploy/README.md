# Chạy automaton51 24/7

AI chỉ làm việc khi máy chạy nó đang bật. Chọn một trong hai cách.

## Cách 1: máy chủ Linux thuê theo tháng (khuyên dùng)

```bash
sudo apt update && sudo apt install -y python3 python3-pip git
sudo git clone https://github.com/nguyenquangphi0809-cloud/Le-Duan /opt/Le-Duan
cd /opt/Le-Duan && sudo pip3 install -r requirements.txt
sudo python3 -m automaton51 --state /opt/Le-Duan/state setup      # một lần, hỏi tài khoản nhận tiền + khoá
sudo python3 -m automaton51 --state /opt/Le-Duan/state doctor     # kiểm tra kết nối
sudo cp deploy/automaton51.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now automaton51
```

Bảng điều khiển chỉ mở trên chính máy chủ (127.0.0.1:8451). Xem từ máy bạn qua đường hầm SSH:
`ssh -L 8451:127.0.0.1:8451 ten@may-chu` rồi mở http://localhost:8451.

## Cách 2: máy tính Windows ở nhà

1. Cài Python 3.10+ từ python.org (tích "Add Python to PATH").
2. Tải kho về, mở cmd trong thư mục kho: `pip install -r requirements.txt`
3. `python -m automaton51 --state state setup` rồi `python -m automaton51 --state state doctor`
4. Nhấp đúp `deploy\chay-tren-windows.bat`. Để tự chạy khi bật máy: Task Scheduler, tạo tác vụ, Trigger "At log on",
   Action trỏ tới tệp .bat này. Tắt chế độ Sleep của máy.

## Cập nhật phiên bản mới

```bash
cd /opt/Le-Duan && sudo git pull && sudo systemctl restart automaton51
```

Thư mục `state/` (sổ cái, đơn hàng, khoá trong `.env`) không nằm trong git nên không bị ghi đè khi cập nhật.
