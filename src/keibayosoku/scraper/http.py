"""netkeiba.com向けの共通HTTPクライアント。

- robots.txt を実行時に取得して許可されたパスかどうかを確認する
- リクエスト間隔を空けてサーバー負荷を抑える (デフォルト2秒)
- netkeiba (db.netkeiba.com) は EUC-JP エンコーディングを使っているため明示的にデコードする
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "KeibaYosokuBot/1.0 (+https://github.com/sugaimo15/keibayosoku; personal research use)"

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}


class RobotsDisallowedError(RuntimeError):
    """robots.txt がアクセスを許可していない場合に送出される。"""


@dataclass
class NetkeibaClient:
    """レート制限とrobots.txt尊重を組み込んだシンプルなHTTPクライアント。"""

    min_interval_sec: float = 2.0
    timeout_sec: float = 15.0
    session: requests.Session = field(default_factory=requests.Session)
    _robot_parsers: dict = field(default_factory=dict)
    _last_request_ts: dict = field(default_factory=dict)

    def _get_robot_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robot_parsers:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{origin}/robots.txt")
            try:
                rp.read()
            except Exception:
                # robots.txt が取得できない場合は安全側に倒し、後続のアクセスは許可扱いにしない
                rp = None
            self._robot_parsers[origin] = rp
        return self._robot_parsers[origin]

    def _check_allowed(self, url: str) -> None:
        rp = self._get_robot_parser(url)
        if rp is None:
            # robots.txt を取得できなかった場合は判断不能として警告を出しつつ続行はしない
            raise RobotsDisallowedError(
                f"robots.txt を取得できなかったため安全のためアクセスを中止します: {url}"
            )
        if not rp.can_fetch(USER_AGENT, url):
            raise RobotsDisallowedError(f"robots.txt により許可されていないURLです: {url}")

    def _throttle(self, url: str) -> None:
        parsed = urlparse(url)
        origin = parsed.netloc
        now = time.monotonic()
        last = self._last_request_ts.get(origin)
        if last is not None:
            elapsed = now - last
            wait = self.min_interval_sec - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_request_ts[origin] = time.monotonic()

    def get(self, url: str, *, encoding: str | None = None, retries: int = 3) -> str:
        """URLを取得してデコード済みのHTML文字列を返す。robots.txtで禁止されていれば例外。"""
        self._check_allowed(url)
        self._throttle(url)

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self.session.get(
                    url, headers=DEFAULT_HEADERS, timeout=self.timeout_sec
                )
                resp.raise_for_status()
                if encoding:
                    resp.encoding = encoding
                return resp.text
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        assert last_exc is not None
        raise last_exc

    def get_soup(self, url: str, *, encoding: str | None = None) -> BeautifulSoup:
        html = self.get(url, encoding=encoding)
        return BeautifulSoup(html, "lxml")
