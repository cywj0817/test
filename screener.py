"""
US Stock Screener Bot
- 매일 아침 실행하여 추천 종목과 진입가/익절가/손절가 출력
- 모멘텀 + 추세 + RSI 멀티 팩터 스크리닝
- ATR 기반 동적 손절/익절 계산
"""
from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pandas_ta as ta
import yfinance as yf
from tabulate import tabulate

import news_analyzer
from universe import get_universe

# Windows cp949 환경에서도 유니코드 출력이 깨지지 않도록 stdout을 UTF-8로 재설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


@dataclass
class Recommendation:
    ticker: str
    score: float
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    rsi: float
    momentum_1m: float
    momentum_3m: float


def download_data(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    """Yahoo Finance에서 다종목 OHLCV 일괄 다운로드."""
    print(f"[*] {len(tickers)}개 종목 데이터 다운로드 중...")
    df = yf.download(
        tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    return df


def analyze(ticker: str, ohlcv: pd.DataFrame) -> Recommendation | None:
    """단일 종목 분석. 모든 필터 통과 시 Recommendation 반환."""
    if ohlcv is None or ohlcv.empty:
        return None

    close = ohlcv["Close"].dropna()
    if len(close) < 200:
        return None

    high = ohlcv["High"].dropna()
    low = ohlcv["Low"].dropna()
    volume = ohlcv["Volume"].dropna()

    # 기술적 지표 계산
    sma50 = ta.sma(close, length=50)
    sma200 = ta.sma(close, length=200)
    rsi = ta.rsi(close, length=14)
    atr = ta.atr(high, low, close, length=14)
    avg_vol = volume.rolling(20).mean()

    last_close = float(close.iloc[-1])
    last_sma50 = float(sma50.iloc[-1])
    last_sma200 = float(sma200.iloc[-1])
    last_rsi = float(rsi.iloc[-1])
    last_atr = float(atr.iloc[-1])
    last_vol = float(avg_vol.iloc[-1])

    # --- 기본 필터 ---
    if last_close < 10:                # 페니주식 회피
        return None
    if last_vol < 1_000_000:           # 유동성 부족 회피
        return None
    if last_sma50 < last_sma200:       # 골든크로스 상태만 (장기 상승추세)
        return None
    if last_close < last_sma50:        # 50일선 위에 있는 종목만
        return None
    if last_rsi < 40 or last_rsi > 70: # 너무 차갑거나 너무 뜨거운 구간 제외
        return None

    # --- 모멘텀 측정 ---
    mom_1m = (last_close / float(close.iloc[-21]) - 1) * 100
    mom_3m = (last_close / float(close.iloc[-63]) - 1) * 100
    if mom_1m < 0:                     # 최근 1개월 손실 종목 제외
        return None

    # --- 종합 점수 (높을수록 매력적) ---
    trend_strength = (last_close / last_sma200 - 1) * 100
    score = mom_1m * 0.4 + mom_3m * 0.3 + trend_strength * 0.3

    # --- ATR 기반 진입/익절/손절 ---
    entry = last_close
    stop_loss = entry - 2.0 * last_atr     # 2 ATR 아래 손절
    take_profit = entry + 3.0 * last_atr   # 3 ATR 위 익절 (R:R = 1.5)
    risk_reward = (take_profit - entry) / (entry - stop_loss)

    return Recommendation(
        ticker=ticker,
        score=score,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        rsi=last_rsi,
        momentum_1m=mom_1m,
        momentum_3m=mom_3m,
    )


def screen(tickers: list[str], top_n: int = 10) -> list[Recommendation]:
    data = download_data(tickers)
    results: list[Recommendation] = []
    failed: list[str] = []

    for ticker in tickers:
        try:
            if ticker not in data.columns.get_level_values(0):
                failed.append(ticker)
                continue
            ohlcv = data[ticker]
            rec = analyze(ticker, ohlcv)
            if rec:
                results.append(rec)
        except Exception as e:
            failed.append(f"{ticker}({e})")

    if failed:
        print(f"[!] 분석 실패/제외: {len(failed)}개", file=sys.stderr)

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


def print_results(recs: list[Recommendation]) -> None:
    if not recs:
        print("\n[X] 조건을 만족하는 종목이 없습니다. (시장 전반 약세 가능성)")
        return

    rows = []
    for r in recs:
        stop_pct = (r.stop_loss / r.entry - 1) * 100
        tp_pct = (r.take_profit / r.entry - 1) * 100
        rows.append([
            r.ticker,
            f"{r.score:.1f}",
            f"${r.entry:.2f}",
            f"${r.stop_loss:.2f} ({stop_pct:+.1f}%)",
            f"${r.take_profit:.2f} ({tp_pct:+.1f}%)",
            f"{r.risk_reward:.2f}",
            f"{r.rsi:.0f}",
            f"{r.momentum_1m:+.1f}%",
            f"{r.momentum_3m:+.1f}%",
        ])
    headers = ["Ticker", "Score", "Entry", "Stop Loss", "Take Profit",
               "R:R", "RSI", "1M", "3M"]
    print()
    print(tabulate(rows, headers=headers, tablefmt="github"))
    print()
    print("[!] 이것은 투자 자문이 아니라 기술적 스크리닝 결과입니다.")
    print("    실제 매매 전 펀더멘털, 뉴스, 시장 상황을 반드시 직접 확인하세요.")


def _sentiment_label(score: int) -> str:
    if score >= 7: return "매우 긍정"
    if score >= 3: return "긍정"
    if score >= -2: return "중립"
    if score >= -6: return "부정"
    return "매우 부정"


def _print_claude_analysis(client, recs: list[Recommendation]) -> None:
    print()
    print("=" * 78)
    print("  뉴스 분석 (Claude Opus 4.7)")
    print("=" * 78)

    for r in recs:
        print(f"\n>>> {r.ticker}  (스크리닝 점수: {r.score:.1f})")
        print("-" * 78)
        result = news_analyzer.analyze_ticker(client, r.ticker)
        if result is None:
            print("  (최근 뉴스가 없거나 분석에 실패했습니다.)")
            continue

        print(f"  감성: {result.sentiment_score:+d}/10 ({_sentiment_label(result.sentiment_score)}) "
              f"| 신뢰도: {result.confidence}")
        print(f"\n  요약: {result.summary}")
        print(f"\n  호재:")
        for c in result.catalysts:
            print(f"    + {c}")
        print(f"\n  리스크:")
        for risk in result.risks:
            print(f"    - {risk}")


# 야후 파이낸스 추천 등급 한국어 표기
_RECOMMENDATION_KR = {
    "strong_buy": "강력 매수",
    "buy": "매수",
    "hold": "보유",
    "underperform": "비중축소",
    "sell": "매도",
    "strong_sell": "강력 매도",
    "none": "의견 없음",
}


def _print_free_analysis(recs: list[Recommendation]) -> None:
    print()
    print("=" * 78)
    print("  뉴스 분석 (무료 모드: VADER 감성 + 야후 애널리스트 컨센서스)")
    print("=" * 78)
    print("  [i] Claude Opus 4.7 분석을 원하시면 ANTHROPIC_API_KEY를 설정하세요.")

    for r in recs:
        print(f"\n>>> {r.ticker}  (스크리닝 점수: {r.score:.1f})")
        print("-" * 78)
        result = news_analyzer.analyze_ticker_free(r.ticker)

        # 헤드라인 감성
        if result.headlines:
            print(f"  헤드라인 감성: {result.sentiment_score:+d}/10 "
                  f"({_sentiment_label(result.sentiment_score)})")
        else:
            print("  (최근 뉴스 없음)")

        # 애널리스트 컨센서스
        if result.analyst_recommendation or result.target_mean_price:
            rec_kr = _RECOMMENDATION_KR.get(
                result.analyst_recommendation or "", result.analyst_recommendation or "?"
            )
            line = f"  애널리스트 의견: {rec_kr}"
            if result.num_analysts:
                line += f" ({result.num_analysts}명)"
            print(line)

            if result.target_mean_price:
                upside_str = (
                    f" (상승여력 {result.target_upside_pct:+.1f}%)"
                    if result.target_upside_pct is not None else ""
                )
                print(f"  애널리스트 평균 목표가: ${result.target_mean_price:.2f}{upside_str}")
        else:
            print("  애널리스트 데이터: 조회 실패")

        # 최근 헤드라인
        if result.headlines:
            print(f"\n  최근 헤드라인:")
            for i, h in enumerate(result.headlines, 1):
                print(f"    {i}. {h}")


def print_news_analysis(recs: list[Recommendation]) -> None:
    """추천 종목별 뉴스 분석 결과 출력. API 키 있으면 Claude, 없으면 무료 모드."""
    client = news_analyzer.get_client()
    if client is not None:
        _print_claude_analysis(client, recs)
    else:
        _print_free_analysis(recs)


def main():
    parser = argparse.ArgumentParser(description="미국 주식 스크리닝 봇")
    parser.add_argument("--top", type=int, default=10, help="상위 N개 출력 (기본 10)")
    parser.add_argument("--no-sp500", action="store_true",
                        help="S&P 500 대신 핵심 대형주 폴백 유니버스 사용")
    parser.add_argument("--with-news", action="store_true",
                        help="추천 종목 뉴스를 Claude로 분석 (ANTHROPIC_API_KEY 필요)")
    parser.add_argument("--html", type=str, default=None,
                        help="HTML 리포트를 지정 경로에 생성 (예: docs/index.html)")
    args = parser.parse_args()

    print("=" * 78)
    print(f"  US Stock Screener  -  {pd.Timestamp.now():%Y-%m-%d %H:%M}")
    print("=" * 78)

    universe = get_universe(use_sp500=not args.no_sp500)
    recs = screen(universe, top_n=args.top)
    print_results(recs)

    if args.with_news and recs:
        print_news_analysis(recs)

    if args.html:
        from report import generate_html
        generate_html(recs, Path(args.html))


if __name__ == "__main__":
    main()
