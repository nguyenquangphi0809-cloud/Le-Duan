"""Khoá bí mật chỉ đọc từ biến môi trường (hoặc tệp .env trong thư mục state), không lưu trong config.json."""
from __future__ import annotations

import os

ENV_EMAIL_PASSWORD = "AUTOMATON51_EMAIL_APP_PASSWORD"
ENV_SEPAY_TOKEN = "SEPAY_API_TOKEN"
ENV_SEPAY_WEBHOOK_KEY = "SEPAY_WEBHOOK_KEY"
ENV_FACEBOOK_TOKEN = "FACEBOOK_PAGE_TOKEN"
ENV_ANTHROPIC = "ANTHROPIC_API_KEY"
ENV_META_ADS = "META_ADS_TOKEN"  # token có quyền ads_management (người dùng hệ thống trong Meta Business), không phải token Trang

ALL = (ENV_ANTHROPIC, ENV_EMAIL_PASSWORD, ENV_SEPAY_TOKEN, ENV_SEPAY_WEBHOOK_KEY, ENV_FACEBOOK_TOKEN, ENV_META_ADS)


def get(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def mask(value: str) -> str:
    if not value:
        return "(chưa có)"
    return value[:4] + "…" + value[-2:] if len(value) > 8 else "••••"
