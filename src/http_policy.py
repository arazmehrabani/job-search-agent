from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .utils import canonical_url, is_safe_http_url


@dataclass
class FetchResult:
    status_code: int = 0
    text: str = ""
    url: str = ""
    from_cache: bool = False
    robots_allowed: bool = True
    error: str = ""


class HttpPolicy:
    """Polite, cached HTTP access for arbitrary career pages.

    Official source APIs continue to use their own connectors. This policy is for
    live-page verification/enrichment where the agent fetches a public job URL.
    """

    def __init__(self, cfg: dict | None = None):
        hcfg = ((cfg or {}).get("http", {}) or {})
        self.min_delay = max(0.0, float(hcfg.get("min_delay_per_host_seconds", 1.5) or 0.0))
        self.jitter = max(0.0, float(hcfg.get("delay_jitter_seconds", 0.25) or 0.0))
        self.max_retries = max(0, int(hcfg.get("max_retries", 2) or 0))
        self.backoff = max(0.0, float(hcfg.get("retry_backoff_seconds", 2.0) or 0.0))
        self.max_retry_after = max(0.0, float(hcfg.get("max_retry_after_seconds", 60.0) or 60.0))
        self.cache_minutes = max(0.0, float(hcfg.get("page_cache_minutes", 120) or 0.0))
        self.robots_enabled = bool(hcfg.get("respect_robots_txt", True))
        self.robots_fail_open = bool(hcfg.get("robots_fail_open", True))
        self.robots_cache_hours = max(0.0, float(hcfg.get("robots_cache_hours", 12) or 0.0))
        self.max_body_chars = max(50_000, int(hcfg.get("max_cached_body_chars", 750_000) or 750_000))
        self.timeout = max(3, int(hcfg.get("timeout_seconds", 20) or 20))
        self.user_agent = str(hcfg.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobSearchAgent/1.8.2"))
        self.robots_user_agent = str(hcfg.get("robots_user_agent", "JobSearchAgent"))
        self.cache_file = Path(str(hcfg.get("cache_file", "output/http_cache.json")))
        self.session = requests.Session()
        self._last_request: dict[str, float] = {}
        self._robots_mem: dict[str, tuple[float, RobotFileParser | None, bool]] = {}
        self._lock = threading.Lock()
        self._cache = self._load_cache()
        self._stats = {
            "page_fetches": 0,
            "cache_hits": 0,
            "network_requests": 0,
            "robots_requests": 0,
            "retries": 0,
            "errors": 0,
            "throttle_sleep_seconds": 0.0,
        }

    def _load_cache(self) -> dict:
        if self.cache_minutes <= 0 and self.robots_cache_hours <= 0:
            return {"pages": {}, "robots": {}}
        try:
            if self.cache_file.exists():
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("pages", {})
                    data.setdefault("robots", {})
                    return data
        except Exception:
            pass
        return {"pages": {}, "robots": {}}

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(self.cache_file.suffix + ".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_file)
        except Exception:
            # Caching must never break job processing.
            pass

    @staticmethod
    def _epoch() -> float:
        return time.time()

    def _throttle(self, host: str) -> None:
        if not host or self.min_delay <= 0:
            return
        with self._lock:
            last = self._last_request.get(host, 0.0)
            target = self.min_delay + (random.uniform(0, self.jitter) if self.jitter else 0.0)
            wait = target - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
                self._stats["throttle_sleep_seconds"] += float(wait)
            self._last_request[host] = time.monotonic()

    def _raw_get(self, url: str, timeout: int | None = None) -> requests.Response:
        host = urlsplit(url).netloc.lower()
        attempts = self.max_retries + 1
        last_response = None
        for attempt in range(attempts):
            self._throttle(host)
            response = self.session.get(
                url,
                timeout=timeout or self.timeout,
                allow_redirects=True,
                headers={"User-Agent": self.user_agent},
            )
            last_response = response
            retryable = response.status_code == 429 or 500 <= response.status_code <= 599
            if not retryable or attempt >= attempts - 1:
                return response
            self._stats["retries"] += 1
            wait = self._retry_wait(response, attempt)
            if wait > 0:
                time.sleep(wait)
        return last_response  # pragma: no cover

    def _retry_wait(self, response: requests.Response, attempt: int) -> float:
        raw = str(response.headers.get("Retry-After", "") or "").strip()
        wait = 0.0
        if raw:
            try:
                wait = float(raw)
            except ValueError:
                try:
                    dt = parsedate_to_datetime(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    wait = max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
                except Exception:
                    wait = 0.0
        if wait <= 0:
            wait = self.backoff * (2 ** attempt)
        return min(self.max_retry_after, max(0.0, wait))

    def _robots_parser(self, url: str) -> tuple[RobotFileParser | None, bool]:
        """Return parser plus whether policy was successfully obtained."""
        host = urlsplit(url).netloc.lower()
        now = self._epoch()
        cached = self._robots_mem.get(host)
        ttl = self.robots_cache_hours * 3600
        if cached and (now - cached[0]) <= ttl:
            return cached[1], cached[2]

        persisted = self._cache.get("robots", {}).get(host, {})
        if persisted and now - float(persisted.get("fetched_at", 0) or 0) <= ttl:
            try:
                rp = RobotFileParser()
                rp.set_url(f"{urlsplit(url).scheme}://{host}/robots.txt")
                rp.parse(str(persisted.get("text", "")).splitlines())
                ok = bool(persisted.get("ok", True))
                self._robots_mem[host] = (now, rp, ok)
                return rp, ok
            except Exception:
                pass

        robots_url = f"{urlsplit(url).scheme}://{host}/robots.txt"
        try:
            self._stats["robots_requests"] += 1
            self._stats["network_requests"] += 1
            r = self._raw_get(robots_url, timeout=min(self.timeout, 12))
            if r.status_code == 404:
                rp = RobotFileParser(); rp.set_url(robots_url); rp.parse([])
                ok = True
            elif 200 <= r.status_code < 300:
                text = (r.text or "")[:200_000]
                rp = RobotFileParser(); rp.set_url(robots_url); rp.parse(text.splitlines())
                ok = True
                self._cache.setdefault("robots", {})[host] = {"fetched_at": now, "text": text, "ok": True}
                self._save_cache()
            else:
                rp, ok = None, False
        except Exception:
            rp, ok = None, False
        self._robots_mem[host] = (now, rp, ok)
        return rp, ok

    def robots_allowed(self, url: str) -> bool:
        if not self.robots_enabled:
            return True
        rp, ok = self._robots_parser(url)
        if not ok or rp is None:
            return self.robots_fail_open
        try:
            return bool(rp.can_fetch(self.robots_user_agent, url))
        except Exception:
            return self.robots_fail_open

    def _cached_page(self, url: str) -> FetchResult | None:
        if self.cache_minutes <= 0:
            return None
        key = canonical_url(url)
        if not key:
            return None
        item = self._cache.get("pages", {}).get(key)
        if not item:
            return None
        if self._epoch() - float(item.get("fetched_at", 0) or 0) > self.cache_minutes * 60:
            return None
        return FetchResult(
            status_code=int(item.get("status_code", 0) or 0),
            text=str(item.get("text", "")),
            url=str(item.get("url", key)),
            from_cache=True,
        )

    def stats(self) -> dict:
        out = dict(self._stats)
        out["throttle_sleep_seconds"] = round(float(out.get("throttle_sleep_seconds", 0.0)), 3)
        return out

    def fetch(self, url: str, timeout: int | None = None, force_refresh: bool = False) -> FetchResult:
        self._stats["page_fetches"] += 1
        if not is_safe_http_url(url):
            return FetchResult(url=str(url or ""), robots_allowed=False, error="unsafe_url_scheme")
        if not force_refresh:
            cached = self._cached_page(url)
            if cached is not None:
                self._stats["cache_hits"] += 1
                return cached
        if not self.robots_allowed(url):
            return FetchResult(url=url, robots_allowed=False, error="robots_disallowed")
        try:
            self._stats["network_requests"] += 1
            r = self._raw_get(url, timeout=timeout)
        except Exception as exc:
            self._stats["errors"] += 1
            return FetchResult(url=url, error=str(exc))
        result = FetchResult(
            status_code=int(r.status_code),
            text=(r.text or "")[: self.max_body_chars],
            url=str(r.url or url),
            robots_allowed=True,
        )
        if self.cache_minutes > 0 and r.status_code not in {401, 403, 429} and r.status_code < 500:
            key = canonical_url(url)
            if key:
                self._cache.setdefault("pages", {})[key] = {
                    "fetched_at": self._epoch(),
                    "status_code": result.status_code,
                    "url": result.url,
                    "text": result.text,
                }
                self._save_cache()
        return result
