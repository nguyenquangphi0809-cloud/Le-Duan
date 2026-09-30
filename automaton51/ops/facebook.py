"""Đăng bài lên Trang Facebook của chủ sở hữu qua Graph API (/{page-id}/feed). Không đăng vào nhóm,
không nhắn tin cho người lạ (trái quy định nền tảng)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Callable, Optional

GRAPH = "https://graph.facebook.com"


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"User-Agent": "automaton51/0.2"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "automaton51/0.2"}), timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class FacebookPublisher:
    def __init__(self, page_id: str, token: str, version: str = "v25.0",
                 post: Optional[Callable[[str, dict], dict]] = None, get: Optional[Callable[[str], dict]] = None):
        self.page_id, self.token, self.version = page_id, token, version
        self.post = post or _post_form
        self.get = get or _get_json

    def publish(self, message: str) -> str:
        data = self.post(f"{GRAPH}/{self.version}/{self.page_id}/feed", {"message": message, "access_token": self.token})
        if "id" not in data:
            raise RuntimeError(f"Facebook từ chối: {data.get('error', data)}")
        return str(data["id"])

    def check(self) -> str:
        q = urllib.parse.urlencode({"fields": "name", "access_token": self.token})
        data = self.get(f"{GRAPH}/{self.version}/{self.page_id}?{q}")
        if "name" not in data:
            raise RuntimeError(f"token không hợp lệ: {data.get('error', data)}")
        return f"Trang: {data['name']}"


def launch_kit_posts(path) -> list[str]:
    """Tách 7 bài mẫu trong playbooks/launch-kit/03-... thành danh sách bài đăng."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return []
    parts = text.split("\n## ")[1:]
    posts = []
    for part in parts:
        lines = part.splitlines()[1:]
        body = "\n".join(lines).strip()
        if body:
            posts.append(body)
    return posts
