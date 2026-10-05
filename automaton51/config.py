"""Cấu hình tác nhân. Lưu ở <state>/config.json. Tỷ lệ 51/49 KHÔNG nằm ở đây —
nó nằm trong constitution.py và không thể cấu hình."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields
from decimal import Decimal
from pathlib import Path
from typing import Any

from .money import D

DEFAULT_GENESIS = (
    "Bạn được tạo ra để kiếm tiền một cách trung thực cho chủ sở hữu bằng cách "
    "tạo ra giá trị thật: tìm việc phù hợp trên Internet, xây dựng web/app/công cụ "
    "nhỏ, bán sản phẩm số, viết nội dung thu hút khách hàng, và thu tiền về để "
    "duy trì sự sống của chính bạn. Khi có lời, hãy mở rộng kinh doanh bằng Quỹ mở rộng."
)


@dataclass
class Config:
    # Danh tính
    name: str = "Automaton-51"
    owner_name: str = ""
    owner_contact: str = ""
    genesis_prompt: str = DEFAULT_GENESIS
    mode: str = "sim"  # "sim" (mô phỏng, không tốn tiền) | "live" (gọi Claude thật)
    market_language: str = "vi"
    journal_language: str = "vi"

    # Bộ não theo tầng sinh tồn (tầng thấp -> model rẻ hơn, nghĩ ít hơn)
    model_normal: str = "claude-opus-5-5"
    model_low: str = "claude-sonnet-5-5"
    model_critical: str = "claude-haiku-4-5"
    effort_normal: str = "high"
    effort_low: str = "medium"
    effort_critical: str = "low"
    max_tokens: int = 16000
    enable_fallbacks: bool = True

    # Kinh tế (USD)
    server_usd_per_hour: str = "0.012"   # ~ $8.6/tháng cho một VPS nhỏ
    low_threshold_usd: str = "5"         # dưới mức này -> low_compute
    critical_threshold_usd: str = "1"    # dưới mức này -> critical
    dead_grace_seconds: int = 3600       # ví = 0 quá lâu -> chết
    allow_growth_rescue: bool = True     # cho phép Quỹ mở rộng cứu ví vận hành
    growth_rescue_usd: str = "2"
    daily_inference_cap_usd: str = "5"   # trần chi phí suy luận mỗi ngày

    # Nhịp tim (giây) theo tầng
    heartbeat_normal: int = 60
    heartbeat_low: int = 300
    heartbeat_critical: int = 900
    max_tool_calls_per_turn: int = 12
    max_api_calls_per_turn: int = 8

    # Nhân bản
    max_children: int = 3
    child_seed_usd: str = "5"
    replicate_min_growth_usd: str = "10"
    auto_start_children: bool = False
    parent_name: str = ""
    lineage: list[str] = field(default_factory=list)

    # Tích hợp thế giới thật (chế độ live)
    job_sources: list[str] = field(default_factory=list)
    publish_webhook_url: str = ""
    content_webhook_url: str = ""
    work_webhook_url: str = ""
    revenue_webhook_secret: str = ""
    dashboard_port: int = 8451
    allow_network: bool = True

    # Mô phỏng
    sim_seed: int = 42
    sim_tick_minutes: int = 30
    agent_turn_interval_minutes: int = 0   # >0: AI marketing chỉ "nghĩ" tối đa 1 lượt mỗi khoảng này

    # ---- Vận hành tự động hoàn toàn (ops): email -> báo giá -> thu tiền -> làm -> giao ----
    ops_enabled: bool = False
    ops_poll_seconds: int = 120
    business_name: str = "Trợ lý học thuật số"
    email_address: str = ""          # Gmail đăng nhập (mật khẩu ứng dụng ở biến môi trường)
    email_alias: str = ""            # địa chỉ nhận khách, ví dụ ten+hocthuat@gmail.com
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    owner_notify_email: str = ""     # nhận báo cáo hằng ngày; trống = email_address
    max_emails_per_day: int = 150
    # Tài khoản nhận tiền: việc DUY NHẤT chủ sở hữu tự chỉ định
    bank_id: str = ""                # mã VietQR của ngân hàng (vd: vcb, mbbank, tcb) hoặc BIN 6 số
    bank_account_number: str = ""
    bank_account_name: str = ""
    payment_provider: str = "sepay"  # "sepay" (tự dò giao dịch) | "webhook" (chỉ nhận qua webhook)
    vnd_per_usd: int = 26000
    order_code_prefix: str = "HT"
    quote_valid_days: int = 7
    revision_days: int = 14
    revision_limit: int = 1
    retention_days: int = 30
    orders_per_tick: int = 1
    max_order_pages: int = 400
    fulfillment_model: str = "claude-opus-5-5"
    fulfillment_effort: str = "high"
    intake_model: str = "claude-opus-5-5"
    intake_effort: str = "low"
    intake_llm_daily_limit: int = 200     # quá mức này (vd bị spam) thì chỉ dùng luật từ khoá, không tốn tiền
    code_exec_usd_per_order: str = "0"   # 1.550 giờ/tháng miễn phí; vượt mức 0,05 USD/giờ
    outreach_enabled: bool = True
    outreach_daily_limit: int = 25
    outreach_wait_days: int = 7
    facebook_page_id: str = ""
    graph_api_version: str = "v25.0"
    facebook_posts_per_day: int = 1
    digest_hour_utc: int = 1             # 8 giờ sáng giờ Việt Nam
    # ---- Hai ngách chạy song song (A: hồ sơ bảo vệ luận án; B: số hoá, biên soạn sử liệu địa phương) ----
    line_min_share: str = "0.25"         # mỗi ngách luôn giữ tối thiểu 25% bài đăng và thư giới thiệu để tiếp tục thử
    free_cp_per_day: int = 20            # số đơn chuyển phông miễn phí tối đa mỗi ngày (mỗi người 1 đơn/24 giờ)
    # Thông tin người gửi in trong thư quảng cáo (Nghị định 91/2020: tên, địa chỉ, điện thoại, email, trang web)
    business_address: str = ""
    business_phone: str = ""             # số RIÊNG cho kinh doanh nếu có; KHÔNG dùng số điện thoại cá nhân
    business_website: str = ""           # địa chỉ Trang Facebook hoặc website
    # ---- Quảng cáo trả tiền trên Meta, trích từ Quỹ mở rộng 49% (tắt cho tới khi có tài khoản quảng cáo) ----
    ads_enabled: bool = False
    ad_account_id: str = ""              # dãy số sau act_ trong Trình quản lý quảng cáo
    ads_every_days: int = 7
    ads_weekly_cap_vnd: int = 700_000    # trần mỗi đợt (chưa gồm thuế)
    ads_min_budget_vnd: int = 140_000    # dưới mức này không chạy (quá ít để Meta tối ưu)
    ads_growth_share: str = "0.5"        # mỗi đợt dùng tối đa 50% số dư Quỹ mở rộng
    ads_vat_rate: str = "0.10"           # Meta cộng thuế GTGT 10% từ 1/7/2025
    ads_lines: list[str] = field(default_factory=lambda: ["A"])
    ads_age_min: int = 23
    ads_age_max: int = 60

    # ---- tiện ích ----
    @property
    def server_usd_per_hour_d(self) -> Decimal:
        return D(self.server_usd_per_hour)

    @property
    def low_threshold(self) -> Decimal:
        return D(self.low_threshold_usd)

    @property
    def critical_threshold(self) -> Decimal:
        return D(self.critical_threshold_usd)

    @property
    def growth_rescue(self) -> Decimal:
        return D(self.growth_rescue_usd)

    @property
    def daily_inference_cap(self) -> Decimal:
        return D(self.daily_inference_cap_usd)

    @property
    def child_seed(self) -> Decimal:
        return D(self.child_seed_usd)

    @property
    def replicate_min_growth(self) -> Decimal:
        return D(self.replicate_min_growth_usd)

    def model_for(self, tier: str) -> str:
        return {"normal": self.model_normal, "low_compute": self.model_low}.get(tier, self.model_critical)

    def effort_for(self, tier: str) -> str:
        return {"normal": self.effort_normal, "low_compute": self.effort_low}.get(tier, self.effort_critical)

    def heartbeat_for(self, tier: str) -> int:
        return {"normal": self.heartbeat_normal, "low_compute": self.heartbeat_low}.get(tier, self.heartbeat_critical)

    # ---- (de)serialization ----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.mode not in ("sim", "live"):
            problems.append(f"mode phải là 'sim' hoặc 'live', nhận: {self.mode!r}")
        for name in ("server_usd_per_hour", "low_threshold_usd", "critical_threshold_usd",
                     "growth_rescue_usd", "daily_inference_cap_usd", "child_seed_usd",
                     "replicate_min_growth_usd"):
            try:
                if D(getattr(self, name)) < 0:
                    problems.append(f"{name} không được âm")
            except Exception:  # noqa: BLE001
                problems.append(f"{name} không phải số hợp lệ")
        if self.low_threshold <= self.critical_threshold:
            problems.append("low_threshold_usd phải lớn hơn critical_threshold_usd")
        if self.max_children < 0:
            problems.append("max_children không được âm")
        if self.ops_enabled:
            for name in ("email_address", "email_alias", "bank_id", "bank_account_number", "bank_account_name"):
                if not str(getattr(self, name) or "").strip():
                    problems.append(f"ops_enabled cần {name} (chạy: automaton51 setup)")
            if self.payment_provider not in ("sepay", "webhook"):
                problems.append("payment_provider phải là 'sepay' hoặc 'webhook'")
            if self.vnd_per_usd <= 0:
                problems.append("vnd_per_usd phải > 0")
        if self.ads_enabled and not str(self.ad_account_id or "").strip():
            problems.append("ads_enabled cần ad_account_id (số tài khoản quảng cáo Meta)")
        for name in ("line_min_share", "ads_growth_share", "ads_vat_rate"):
            try:
                if not D("0") <= D(getattr(self, name)) <= D("1"):
                    problems.append(f"{name} phải nằm trong 0..1")
            except Exception:  # noqa: BLE001
                problems.append(f"{name} không phải số hợp lệ")
        return problems

    @property
    def notify_email(self) -> str:
        return self.owner_notify_email or self.email_address
