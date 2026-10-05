"""Quảng cáo trả tiền tự động trên Meta (Facebook) bằng Marketing API, TRÍCH TỪ QUỸ MỞ RỘNG 49%.

Cách làm: mỗi chu kỳ (mặc định 7 ngày) chọn bài đăng ngách A trên Trang có tương tác tốt nhất, chạy quảng cáo
"tăng tương tác bài viết" với NGÂN SÁCH TRỌN ĐỢT (lifetime budget, Meta không tiêu quá) rồi ghi sổ khoản chi
vào Quỹ mở rộng (đã cộng thuế GTGT 10% Meta thu từ 1/7/2025). Quỹ chủ sở hữu 51% không bao giờ bị đụng tới.

Chỉ quảng cáo ngách A. Bài ngách B (lịch sử Đảng bộ) chỉ đăng tự nhiên: quảng cáo nhắc tới đảng phái dễ bị Meta
xếp vào nhóm "vấn đề xã hội, bầu cử, chính trị" phải xác minh danh tính và ghi "Được tài trợ bởi".

Chuỗi đối tượng (Marketing API): campaign (OUTCOME_ENGAGEMENT) -> ad set (lifetime_budget, ON_POST)
-> ad creative (object_story_id = id bài trên Trang) -> ad.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

GRAPH = "https://graph.facebook.com"


class AdsError(RuntimeError):
    pass


def _http(method: str, url: str, data: Optional[dict] = None) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": "automaton51/0.3"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # Meta trả lỗi dạng JSON kèm mã HTTP 400
        try:
            return json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return {"error": {"message": f"HTTP {exc.code}"}}


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(ts))


def minor_units(amount_vnd: int, currency: str, vnd_per_usd: int) -> int:
    """Ngân sách theo đơn vị nhỏ nhất của tiền tệ tài khoản quảng cáo (VND không có xu; USD tính bằng cent)."""
    cur = (currency or "").upper()
    if cur == "VND":
        return int(amount_vnd)
    if cur == "USD":
        return int(amount_vnd * 100 // max(1, int(vnd_per_usd)))
    raise AdsError(f"Tài khoản quảng cáo dùng tiền {currency}: chỉ hỗ trợ VND hoặc USD")


def boost_payloads(page_post_id: str, budget_minor: int, start: float, days: int, name: str,
                   age_min: int = 23, age_max: int = 60) -> dict[str, dict]:
    """Nội dung 4 lệnh tạo quảng cáo (tách riêng để kiểm thử được mà không gọi Meta)."""
    targeting = {"geo_locations": {"countries": ["VN"]}, "age_min": int(age_min), "age_max": int(age_max),
                 "targeting_automation": {"advantage_audience": 1}}
    return {
        "campaign": {"name": name, "objective": "OUTCOME_ENGAGEMENT", "status": "ACTIVE",
                     "special_ad_categories": json.dumps([]), "is_adset_budget_sharing_enabled": "false"},
        "adset": {"name": name, "lifetime_budget": str(int(budget_minor)), "start_time": _iso(start),
                  "end_time": _iso(start + days * 86400), "billing_event": "IMPRESSIONS",
                  "optimization_goal": "POST_ENGAGEMENT", "destination_type": "ON_POST",
                  "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "targeting": json.dumps(targeting), "status": "ACTIVE"},
        "creative": {"name": name, "object_story_id": page_post_id},
        "ad": {"name": name, "status": "ACTIVE"},
    }


class MetaAds:
    def __init__(self, ad_account_id: str, token: str, version: str = "v25.0",
                 http: Optional[Callable[[str, str, Optional[dict]], dict]] = None):
        acct = (ad_account_id or "").strip()
        self.account = acct if acct.startswith("act_") else f"act_{acct}"
        self.token, self.version = token, version
        self.http = http or _http
        self._currency = ""

    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.version}/{path.lstrip('/')}"

    def _call(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        if method == "GET":
            q = urllib.parse.urlencode({**(data or {}), "access_token": self.token})
            out = self.http("GET", f"{self._url(path)}?{q}", None)
        else:
            out = self.http(method, self._url(path), {**(data or {}), "access_token": self.token})
        if not isinstance(out, dict) or "error" in out:
            err = out.get("error", out) if isinstance(out, dict) else out
            msg = err.get("error_user_msg") or err.get("message") if isinstance(err, dict) else str(err)
            raise AdsError(f"Meta từ chối ({path}): {msg}")
        return out

    def currency(self) -> str:
        if not self._currency:
            self._currency = str(self._call("GET", self.account, {"fields": "currency,account_status,name"}).get("currency", ""))
        return self._currency

    def check(self) -> str:
        info = self._call("GET", self.account, {"fields": "currency,account_status,name"})
        status = {1: "đang hoạt động", 2: "bị vô hiệu hoá", 3: "chưa thanh toán", 7: "đang xét duyệt"}.get(
            int(info.get("account_status", 0) or 0), f"trạng thái {info.get('account_status')}")
        return f"Tài khoản quảng cáo {info.get('name', self.account)} ({info.get('currency', '?')}), {status}"

    def boost(self, page_post_id: str, budget_vnd: int, days: int, vnd_per_usd: int, now: float, name: str,
              age_min: int = 23, age_max: int = 60) -> dict[str, str]:
        budget = minor_units(budget_vnd, self.currency(), vnd_per_usd)
        p = boost_payloads(page_post_id, budget, now, days, name, age_min, age_max)
        ids: dict[str, str] = {}
        try:
            ids["campaign_id"] = str(self._call("POST", f"{self.account}/campaigns", p["campaign"])["id"])
            ids["adset_id"] = str(self._call("POST", f"{self.account}/adsets", {**p["adset"], "campaign_id": ids["campaign_id"]})["id"])
            ids["creative_id"] = str(self._call("POST", f"{self.account}/adcreatives", p["creative"])["id"])
            ids["ad_id"] = str(self._call("POST", f"{self.account}/ads",
                                          {**p["ad"], "adset_id": ids["adset_id"],
                                           "creative": json.dumps({"creative_id": ids["creative_id"]})})["id"])
        except Exception:
            if "campaign_id" in ids:  # dọn chiến dịch dở dang để không có quảng cáo chạy ngoài sổ sách
                try:
                    self._call("POST", ids["campaign_id"], {"status": "PAUSED"})
                except Exception:  # noqa: BLE001
                    pass
            raise
        return ids

    def insights(self, campaign_id: str) -> dict[str, Any]:
        data = self._call("GET", f"{campaign_id}/insights", {"fields": "spend,impressions,reach,clicks"}).get("data") or [{}]
        return data[0] if data else {}


def post_engagement(get: Callable[[str], dict], version: str, post_id: str, token: str) -> int:
    """Tổng cảm xúc + bình luận + chia sẻ của một bài trên Trang (0 nếu không đọc được)."""
    q = urllib.parse.urlencode({"fields": "reactions.summary(true),comments.summary(true),shares", "access_token": token})
    try:
        d = get(f"{GRAPH}/{version}/{post_id}?{q}")
    except Exception:  # noqa: BLE001
        return 0
    if not isinstance(d, dict):
        return 0
    total = 0
    for k in ("reactions", "comments"):
        total += int(((d.get(k) or {}).get("summary") or {}).get("total_count", 0) or 0)
    total += int((d.get("shares") or {}).get("count", 0) or 0)
    return total
