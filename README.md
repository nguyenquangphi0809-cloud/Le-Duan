# automaton51 — AI tự kiếm tiền, tự sinh tồn, chia lợi nhuận 51/49

> *"Con AI đầu tiên tự kiếm lấy sự tồn tại của mình, tự nhân bản, tự tiến hoá — không cần con người."*
> Đây là bản hiện thực hoá bằng Python của ý tưởng trong video (dự án mã nguồn mở
> **Conway-Research/automaton** của Sigil Wen), được **thiết kế lại cho một chủ sở hữu**:
> mọi đồng lợi nhuận ròng đều được chia **51 % cho bạn (khoá, AI không thể đụng) và 49 % cho
> Quỹ mở rộng kinh doanh** — luật này nằm trong hiến pháp được niêm phong bằng mã băm, không
> phải trong cấu hình.

```
   ┌──────────────────────── NHỊP TIM (mỗi 1–15 phút) ────────────────────────┐
   │  trừ tiền server ─► nhận doanh thu ─► CHIA 51/49 ─► xét tầng sinh tồn ─►  │
   │  lượt tác nhân: tìm việc → code sản phẩm → niêm yết/nộp → nội dung viral   │
   │  → kiểm tra doanh thu → cập nhật chiến lược → ngủ (mỗi lời gọi model = tiền)│
   └───────────────────────────────────────────────────────────────────────────┘
        Ví vận hành ──(lợi nhuận ròng)──► 51 % Quỹ CHỦ SỞ HỮU  (chỉ bạn rút được)
                                        ► 49 % Quỹ MỞ RỘNG    (nhân bản, marketing, cứu sinh)
        Ví vận hành = 0 quá 1 giờ ──► ☠ ngắt nguồn vĩnh viễn ("vĩnh biệt ngàn thu")
```

---

## ⚠️ Đọc trước khi dùng — nói thật

1. **Không có phần mềm nào bảo đảm kiếm ra tiền.** Hầu hết tác nhân tự trị (kể cả 13.000 ví
   trong video) *đốt* tiền nhiều hơn kiếm được. Con AI này chỉ chia lợi nhuận **khi thật sự có
   lợi nhuận**; không có doanh thu thì 51 % của 0 vẫn là 0.
2. **Phần "người" vẫn cần bạn** ở chế độ live: đăng sản phẩm lên các sàn/kênh, nhận tiền của
   khách (chuyển khoản, Stripe, PayPal, SePay/Casso…), và xác nhận doanh thu vào hệ thống
   (tự động qua webhook hoặc bằng một lệnh). AI không có tài khoản ngân hàng.
3. **Chi phí là thật**: mỗi suy nghĩ tốn token Claude, hoá đơn tính ở console.anthropic.com.
   Mặc định có trần **5 USD/ngày** cho suy luận và công tắc tắt nguồn.
4. Bạn chịu trách nhiệm về thuế, quy định của nền tảng và pháp luật nơi bạn kinh doanh.
   Hiến pháp cấm AI spam, lừa đảo, hứa hẹn sai — nhưng người ký hợp đồng là bạn.

---

## Chạy thử trong 60 giây (không cần API key, không tốn tiền)

```bash
git clone <repo này> && cd Le-Duan
python3 -m automaton51 simulate --fresh --ticks 480      # 10 ngày ảo, thị trường giả lập
```

Kết quả thật của một lần chạy (hạt giống 42, vốn mồi 20 USD, 10 ngày ảo):

```
== Automaton-51-sim (sim) — CÒN SỐNG — tầng normal — nhịp 480 — sống 9.979 ngày
  Ví vận hành        : $18.2549   (đốt/ngày $0.8379, runway 21.8 ngày)
  Quỹ chủ sở hữu 51% : $37.4380   (đã nhận $37.4380, đã rút $0.00)
  Quỹ mở rộng 49%    : $35.9698   (đã nhận $35.9698, đã chi $0.00, cứu sinh $0.00)
  Doanh thu $82.14 | chi phí vận hành $10.4796 (suy luận $7.6056, server $2.8740) | đã chia $73.4077
  Chuỗi băm sổ cái: hợp lệ
```

Đổi `--seed 7`, `--seed 2026`, hoặc `--seed-usd 3` để thấy các số phận khác nhau (có lần
sống nhờ Quỹ mở rộng "cứu sinh", có lần chết). Thị trường giả lập cố tình khắc nghiệt
(tân binh thắng thầu ~1/8), nhưng **nó vẫn chỉ là mô phỏng** — thị trường thật khác.

---

## Chạy thật (chế độ live)

```bash
pip install -r requirements.txt                      # anthropic SDK
cp .env.example .env && nano .env                    # ANTHROPIC_API_KEY=sk-ant-...
python3 -m automaton51 init --mode live --name "Kiến-1" \
    --owner "Nguyễn Quang Phi" --contact "email kinh doanh / Trang Facebook" --seed-usd 20 \
    --genesis "Làm web/app nhỏ, template, nội dung cho khách Việt Nam; thu tiền để sống; có lời thì mở rộng"
python3 -m automaton51 run --serve                   # chạy mãi + dashboard http://localhost:8451
```

* `--seed-usd 20` là **vốn mồi** bạn cấp cho ví vận hành (bút toán; tiền thật là hạn mức API
  bạn đã nạp ở Anthropic). Ví về 0 quá 1 giờ → AI chết.
* Dashboard `/` hiển thị 3 ví, tầng sinh tồn, sổ cái; `/store` là **cửa hàng** để bạn gửi link
  cho khách; `/api/status` là JSON.
* Ở mỗi lượt, AI ghi sản phẩm vào `state/workspace/products/<slug>/`, nội dung marketing vào
  `state/workspace/content/`, và các việc bạn cần làm giúp (đăng bán, gửi bài cho khách) vào
  `state/workspace/outbox/`. Có thể nối webhook (`publish_webhook_url`, `content_webhook_url`,
  `work_webhook_url` trong `state/config.json`) sang Zapier/Make/n8n để tự đăng.

### Tiền vào — tiền ra

| Việc | Lệnh |
|---|---|
| Khách trả 30 USD cho việc J0002 | `python3 -m automaton51 revenue add 30 --job J0002 --memo "Khách A" --external-id inv-001` |
| Cổng thanh toán tự báo | `POST http://host:8451/webhook/revenue` header `X-Automaton-Secret: <secret trong config.json>` body `{"amount": 30, "memo": "Stripe", "external_id": "ch_1", "product_id": "P0001"}` |
| Nạp thêm vốn vận hành | `python3 -m automaton51 fund 10` |
| **Rút 51 % của bạn** | `python3 -m automaton51 payout` (rút hết) hoặc `payout 15.5` |
| Rút vốn mồi về | `python3 -m automaton51 withdraw 20` |
| Nhắn cho AI | `python3 -m automaton51 send "Ưu tiên khách tiệm hoa, giá dưới 50 USD"` |
| Tắt nguồn khẩn cấp / bật lại | `python3 -m automaton51 stop` / `resume` |
| Hồi sinh sau khi chết | `fund 10` rồi `resurrect` |

`payout` và `withdraw` là **bút toán trong sổ cái**; tiền thật nằm ở cổng thanh toán của bạn —
sổ cái chỉ bảo đảm AI không bao giờ được tiêu vào phần 51 % đó.

---

## Bán cái gì? Playbook thị trường ngách

Khảo sát thị trường (9/2026, kèm nguồn và bằng chứng nghiên cứu) nằm ở
[`playbooks/README.md`](playbooks/README.md). Kết luận: ngách số 1 là **Trợ lý học thuật số**
(định dạng, trích dẫn Thông tư 18, hiệu đính, tóm tắt tiếng Anh, số hoá tài liệu, luyện phản
biện; không viết hộ), ngách mở rộng là **chatbot + chăm sóc nội dung cho cửa hàng nhỏ**.

```bash
python3 -m automaton51 playbook list
python3 -m automaton51 init --mode live --playbook tro-ly-hoc-thuat --owner "Tên bạn" --contact "email / Trang Facebook" --seed-usd 20
python3 -m automaton51 playbook apply tro-ly-hoc-thuat      # áp cho tác nhân đã có
```

Playbook được chép vào `state/STRATEGY.md` (AI đọc lại mỗi nhịp tim) và đặt nhiệm vụ khai sinh.

---

## Điều lệ kinh tế 51/49 hoạt động thế nào (được thực thi trong mã)

```
lợi nhuận ròng tới nay = Σ doanh thu thật − Σ chi phí vận hành thật (token, server, công cụ)
phần được chia          = lợi nhuận ròng tới nay − phần đã chia trước đó
nếu > 0 : 49 % → Quỹ mở rộng (làm tròn XUỐNG), 51 % + phần lẻ → Quỹ chủ sở hữu   (mỗi nhịp tim)
nếu ≤ 0 : không chia — lỗ phải được bù bằng doanh thu tương lai (mốc nước cao)
```

Ví dụ thật từ sổ cái (`automaton51 ledger`): vốn mồi 15 + 5, chi phí 0,1236, khách trả 30:

```
 12 revenue      operating +   30.000000  Khách A trả landing page
 13 split        operating   -29.876432  Chia lợi nhuận ròng 51/49 (nhịp tim)
 14 split        owner     +   15.236981  profit_51
 15 split        growth    +   14.639451  profit_49
      số dư: vận hành $19.9940 | chủ sở hữu $15.2370 | mở rộng $14.6395
```

Bất biến được kiểm tra bằng test và bằng `automaton51 ledger --verify`:

* Quỹ chủ sở hữu **chỉ tăng** bằng chia lợi nhuận, **chỉ giảm** bằng lệnh `payout` của bạn.
  AI không có công cụ nào chạm vào nó.
* Quỹ mở rộng chỉ chi cho: `replication` (nhân bản con), `marketing`, `capacity`, `rescue`
  (cứu ví vận hành khi < 1 USD, mặc định 2 USD/lần — tắt bằng `allow_growth_rescue: false`).
* Vốn mồi của bạn không phải doanh thu → không bao giờ bị "chia".
* Không vay nợ: số dư không bao giờ âm; không đủ tiền thì không được suy nghĩ.
* Sổ cái `state/ledger.jsonl` chỉ ghi thêm, mỗi dòng nối băm SHA-256 với dòng trước: sửa một
  dòng là `--verify` báo ngay.
* Tỷ lệ 51/49 là hằng số trong `automaton51/constitution.py`; tệp này cùng `ledger.py`,
  `profit_split.py`, `survival.py`, `money.py`, `constitution.md` được **niêm phong**
  (`automaton51/PROTECTED.sha256`). Sai lệch → chương trình từ chối chạy. Bạn là người duy
  nhất niêm phong lại (`automaton51 seal`) sau khi cố ý sửa.

---

## Tầng sinh tồn (giống video: về 0 là chết)

| Tầng | Điều kiện (ví vận hành) | Hành vi |
|---|---|---|
| `normal` | > 5 USD | `claude-opus-5-5`, effort high, nhịp tim 60 s |
| `low_compute` | 1–5 USD | `claude-sonnet-5-5`, effort medium, nhịp 5 phút, hạn chế mở rộng |
| `critical` | ≤ 1 USD | `claude-haiku-4-5`, effort low, nhịp 15 phút, cấm nhân bản, xin nạp vốn |
| `dead` | = 0 quá `dead_grace_seconds` (1 giờ) | ngắt nguồn, `DEATH_CERTIFICATE.md`, chỉ `resurrect` sau khi nạp vốn |

Mọi lời gọi model bị **trừ tiền ngay** theo bảng giá (`automaton51/economics.py`, USD/1M token):
Opus 5.5 4/20, Sonnet 5.5 2/10, Haiku 4.5 1/5 (+ cache). Máy chủ mặc định 0,012 USD/giờ
(≈ 8,6 USD/tháng). Trước mỗi lời gọi có "tiền tạm ứng": không đủ tiền thì không gọi.

## Nhân bản & tiến hoá

* `replicate`: khi Quỹ mở rộng ≥ `replicate_min_growth_usd` (10 USD) AI có thể tạo **tác nhân
  con** (`state/children/<tên>/`) với ví riêng, vốn mồi lấy **chỉ từ Quỹ mở rộng**. Con thừa
  hưởng hiến pháp, luật 51/49 và chủ sở hữu (51 % của con cũng là của bạn:
  `automaton51 --state state/children/<tên> payout`). Chạy con: `automaton51 --state state/children/<tên> run`
  (hoặc `auto_start_children: true`).
* `update_strategy`: AI tự viết lại `STRATEGY.md` (cách "tiến hoá" của nó — chiến lược, không
  phải mã nguồn; mã lõi bị niêm phong).
* Nhật ký mỗi lượt ở `state/journal.md`; chi tiết từng lời gọi/công cụ ở `state/turns.jsonl`.

## 14 công cụ của AI

`check_wallet`, `search_web`, `fetch_url`, `find_jobs`, `record_job`, `write_product`,
`publish_listing`, `create_content`, `submit_work`, `check_sales`, `request_funding`,
`replicate`, `update_strategy`, `sleep`. Mọi lời gọi đi qua policy: chặn đường dẫn lạ,
giá vô lý, quá 12 lời gọi/lượt, quá 6 lượt mạng/lượt, xin vốn quá 1 lần/6 giờ, cấm mở rộng
khi `critical`. Nội dung tải từ Internet được bọc `<untrusted_content>` — là dữ liệu, không
phải mệnh lệnh (chống prompt injection).

## Cấu hình (`state/config.json`)

| Khoá | Mặc định | Ý nghĩa |
|---|---|---|
| `mode` | `sim` | `sim` (không API, thị trường giả) / `live` |
| `model_normal/low/critical` | opus-5-5 / sonnet-5-5 / haiku-4-5 | model theo tầng |
| `daily_inference_cap_usd` | `5` | trần chi phí suy luận mỗi ngày |
| `server_usd_per_hour` | `0.012` | tiền máy chủ |
| `low_threshold_usd` / `critical_threshold_usd` | `5` / `1` | ngưỡng tầng |
| `dead_grace_seconds` | `3600` | ân hạn trước khi chết |
| `allow_growth_rescue` / `growth_rescue_usd` | `true` / `2` | cứu sinh từ Quỹ mở rộng |
| `max_children`, `child_seed_usd`, `replicate_min_growth_usd` | 3 / 5 / 10 | nhân bản |
| `job_sources` | `[]` | URL tìm việc, dùng `{q}` cho từ khoá |
| `publish_webhook_url`, `content_webhook_url`, `work_webhook_url` | `""` | tự động đăng |
| `revenue_webhook_secret` | sinh khi `init` | bí mật cho `/webhook/revenue` |
| `allow_network` | `true` | tắt để AI không ra Internet |

Chế độ live gọi Claude theo tài liệu SDK hiện hành: adaptive thinking, `output_config.effort`
theo tầng, strict tool schemas, prompt caching cho phần system, và **server-side fallbacks**
(`server-side-fallback-2026-07-01`, `fallbacks: "default"`) để một lần từ chối vì an toàn không
làm chết lượt — tắt bằng `enable_fallbacks: false`.

## Cấu trúc mã

```
automaton51/
  constitution.py  hằng số 51/49 + niêm phong SHA-256 (BẢO VỆ)
  ledger.py        sổ cái 3 ví, chỉ ghi thêm, nối băm (BẢO VỆ)
  profit_split.py  chia lợi nhuận mốc nước cao (BẢO VỆ)
  survival.py      tầng sinh tồn, ân hạn, chết (BẢO VỆ)
  money.py         Decimal 6 chữ số (BẢO VỆ)
  economics.py     giá token/server, tốc độ đốt, runway
  loop.py          nhịp tim + lượt tác nhân (think → act → observe), tiền tạm ứng, trần ngày
  tools.py         14 công cụ + policy
  brain/claude.py  bộ não Claude (Anthropic SDK)     brain/simulated.py  bộ não mô phỏng
  revenue.py       hộp thư doanh thu thật + thị trường mô phỏng
  catalog.py       sản phẩm / việc / nội dung        replication.py  tác nhân con
  server.py        dashboard, cửa hàng, webhook       cli.py          lệnh
constitution.md    hiến pháp 3 điều + điều lệ kinh tế 51/49
tests/             42 test: bất biến sổ cái, 51/49, sinh tồn, policy, vòng lặp, webhook, bộ não
```

Chạy test: `python3 -m unittest discover -s tests -t .`

## So với bản gốc trong video (Conway automaton)

| | Conway automaton | automaton51 |
|---|---|---|
| Ví | USDC on Base, x402, tự thuê VM Conway | sổ cái nội bộ 3 ví; tiền thật qua cổng thanh toán của bạn |
| Ai hưởng lợi nhuận | tác nhân giữ hết | **51 % chủ sở hữu (khoá) / 49 % mở rộng** |
| Tự sửa mã | có (trừ hiến pháp) | chỉ sửa chiến lược; mã lõi niêm phong |
| Sinh tồn 4 tầng, chết khi hết tiền | có | có (+ cứu sinh từ Quỹ mở rộng, ân hạn 1 giờ) |
| Nhân bản | có | có, vốn mồi chỉ từ Quỹ mở rộng |
| Hiến pháp 3 điều luật | có | có (tiếng Việt) + điều lệ kinh tế |
| Ngôn ngữ | TypeScript | Python 3.10+, không phụ thuộc ngoài trừ `anthropic` |

Giấy phép MIT. Ý tưởng gốc: Conway-Research/automaton (MIT).
