"""
종목 유니버스 모듈
- Wikipedia에서 S&P 500 티커 목록 자동 조회
- 24시간 로컬 캐싱으로 반복 요청 회피
"""
from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_FILE = CACHE_DIR / "sp500.json"
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24시간

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# Wikipedia는 기본 urllib UA를 차단함. 일반 브라우저 UA로 우회
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _is_cache_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    age = time.time() - CACHE_FILE.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def _load_cache() -> list[str]:
    with CACHE_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_cache(tickers: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("w", encoding="utf-8") as f:
        json.dump(tickers, f, ensure_ascii=False, indent=2)


def fetch_sp500_tickers(force_refresh: bool = False) -> list[str]:
    """S&P 500 구성 종목 티커 반환. 24시간 캐싱."""
    if not force_refresh and _is_cache_fresh():
        return _load_cache()

    print("[*] Wikipedia에서 S&P 500 종목 목록 조회 중...")
    resp = requests.get(WIKI_URL, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]

    # yfinance 호환을 위해 BRK.B → BRK-B, BF.B → BF-B 형식으로 변환
    tickers = [t.replace(".", "-") for t in df["Symbol"].tolist()]

    _save_cache(tickers)
    print(f"[*] {len(tickers)}개 종목 캐시 저장 완료")
    return tickers


# 폴백용 핵심 대형주 유니버스 (Wikipedia 접근 실패 시)
FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO",
    "AMD", "ORCL", "CRM", "ADBE", "JPM", "BAC", "V", "MA", "UNH",
    "JNJ", "LLY", "WMT", "COST", "HD", "XOM", "CVX", "SPY", "QQQ",
]


def get_universe(use_sp500: bool = True) -> list[str]:
    """유니버스 반환. use_sp500=False면 폴백 사용."""
    if not use_sp500:
        return FALLBACK_UNIVERSE
    try:
        return fetch_sp500_tickers()
    except Exception as e:
        print(f"[!] S&P 500 조회 실패 ({e}), 폴백 유니버스 사용")
        return FALLBACK_UNIVERSE


if __name__ == "__main__":
    tickers = fetch_sp500_tickers(force_refresh=True)
    print(f"\n총 {len(tickers)}개 종목:")
    print(", ".join(tickers[:20]) + ", ...")
