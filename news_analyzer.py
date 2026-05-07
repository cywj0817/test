"""
뉴스 분석 모듈
- yfinance에서 종목별 최근 뉴스 수집
- Claude API로 요약 + 감성 점수 + 핵심 호재/악재 추출
- prompt caching으로 시스템 프롬프트 캐시 (반복 호출 비용 절감)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Literal

import anthropic
import yfinance as yf
from pydantic import BaseModel, Field
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

MODEL = "claude-opus-4-7"
MAX_NEWS_PER_TICKER = 8

SYSTEM_PROMPT = """\
You are a senior equity analyst specializing in U.S. stock markets.
Your job is to analyze recent news for a single ticker and produce a concise,
actionable assessment for a retail investor.

Rules:
1. Sentiment score is an integer from -10 (very bearish) to +10 (very bullish).
   Base it ONLY on the news content provided, not on price action.
2. Focus on factual catalysts: earnings, guidance, contracts, regulation,
   product launches, leadership changes, macro impacts.
3. Be skeptical of clickbait headlines and pump/dump signals.
4. If news is sparse or stale (>1 week old, no major events), reflect that
   in a low-confidence flag and a neutral score (-2 to +2).
5. Summary must be 2-3 sentences in Korean (한국어).
6. catalysts and risks: 2-4 short bullet points each, in Korean.
7. Always respond in valid JSON matching the requested schema.
"""


class NewsAnalysis(BaseModel):
    sentiment_score: int = Field(
        ge=-10, le=10,
        description="감성 점수 (-10 매우 부정 ~ +10 매우 긍정)"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="분석 신뢰도 (뉴스가 충분하고 명확하면 high)"
    )
    summary: str = Field(description="최근 뉴스 종합 요약 (한국어 2-3문장)")
    catalysts: list[str] = Field(description="긍정적 호재 2-4개 (한국어)")
    risks: list[str] = Field(description="잠재적 악재/리스크 2-4개 (한국어)")


def fetch_news(ticker: str, max_items: int = MAX_NEWS_PER_TICKER) -> list[dict]:
    """yfinance에서 최근 뉴스 수집. 헤드라인+요약만 추출."""
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception as e:
        print(f"  [!] {ticker} 뉴스 조회 실패: {e}", file=sys.stderr)
        return []

    items = []
    for entry in raw[:max_items]:
        # yfinance 응답 스키마 변동 대응 (content 키 / 직접 키 둘 다 처리)
        content = entry.get("content", entry)
        title = content.get("title") or entry.get("title", "")
        summary = content.get("summary") or content.get("description", "")
        publisher = (
            content.get("provider", {}).get("displayName")
            or content.get("publisher")
            or entry.get("publisher", "")
        )
        pub_date = content.get("pubDate") or content.get("providerPublishTime", "")

        if not title:
            continue
        items.append({
            "title": title.strip(),
            "summary": (summary or "").strip()[:500],
            "publisher": publisher,
            "pub_date": str(pub_date),
        })
    return items


def _format_news_for_prompt(ticker: str, news: list[dict]) -> str:
    if not news:
        return f"Ticker: {ticker}\n\n(No recent news available.)"

    lines = [f"Ticker: {ticker}", f"Number of news items: {len(news)}", ""]
    for i, item in enumerate(news, 1):
        lines.append(f"--- News #{i} ---")
        lines.append(f"Title: {item['title']}")
        if item["publisher"]:
            lines.append(f"Publisher: {item['publisher']}")
        if item["pub_date"]:
            lines.append(f"Published: {item['pub_date']}")
        if item["summary"]:
            lines.append(f"Summary: {item['summary']}")
        lines.append("")
    return "\n".join(lines)


def analyze_ticker(
    client: anthropic.Anthropic,
    ticker: str,
) -> NewsAnalysis | None:
    """단일 종목 뉴스 분석. 분석 실패/뉴스 없음이면 None 반환."""
    news = fetch_news(ticker)
    if not news:
        return None

    user_content = _format_news_for_prompt(ticker, news)

    try:
        # cache_control로 시스템 프롬프트 캐싱 (10개 종목 분석 시 큰 비용 절감)
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
            output_format=NewsAnalysis,
        )
        return response.parsed_output
    except anthropic.APIError as e:
        print(f"  [!] {ticker} Claude 분석 실패: {e}", file=sys.stderr)
        return None


def get_client() -> anthropic.Anthropic | None:
    """ANTHROPIC_API_KEY가 있으면 클라이언트 반환, 없으면 None."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic()


# ----------------------------------------------------------------------------
# 무료 분석 (Claude API 키 불필요): VADER 감성 + yfinance 애널리스트 데이터
# ----------------------------------------------------------------------------

@dataclass
class FreeNewsAnalysis:
    sentiment_score: int             # -10 ~ +10
    headlines: list[str] = field(default_factory=list)
    analyst_recommendation: str | None = None  # "strong_buy", "buy", "hold", ...
    target_mean_price: float | None = None
    target_upside_pct: float | None = None     # 현재가 대비 목표가 상승여력 %
    num_analysts: int | None = None


_VADER = SentimentIntensityAnalyzer()


def _vader_score(headlines: list[str]) -> int:
    """VADER 복합 점수 평균을 -10 ~ +10 정수로 변환."""
    if not headlines:
        return 0
    compounds = [_VADER.polarity_scores(h)["compound"] for h in headlines]
    avg = sum(compounds) / len(compounds)
    return int(round(avg * 10))


def _fetch_analyst_data(ticker: str) -> dict:
    """yfinance에서 애널리스트 컨센서스 추출. 실패 시 빈 dict."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return {}

    target_mean = info.get("targetMeanPrice")
    current = info.get("currentPrice") or info.get("regularMarketPrice")
    upside = None
    if target_mean and current:
        try:
            upside = (float(target_mean) / float(current) - 1) * 100
        except (TypeError, ZeroDivisionError):
            upside = None

    return {
        "recommendation": info.get("recommendationKey"),
        "target_mean_price": target_mean,
        "target_upside_pct": upside,
        "num_analysts": info.get("numberOfAnalystOpinions"),
    }


def analyze_ticker_free(ticker: str) -> FreeNewsAnalysis:
    """API 키 불필요 분석. 뉴스가 없어도 애널리스트 데이터는 시도."""
    news = fetch_news(ticker, max_items=10)
    headlines = [n["title"] for n in news[:5]]

    sentiment_score = _vader_score([n["title"] for n in news])
    analyst = _fetch_analyst_data(ticker)

    return FreeNewsAnalysis(
        sentiment_score=sentiment_score,
        headlines=headlines,
        analyst_recommendation=analyst.get("recommendation"),
        target_mean_price=analyst.get("target_mean_price"),
        target_upside_pct=analyst.get("target_upside_pct"),
        num_analysts=analyst.get("num_analysts"),
    )


if __name__ == "__main__":
    # 단독 실행 테스트
    client = get_client()
    if client is None:
        print("ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.")
        sys.exit(1)

    test_ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    print(f"\n=== {test_ticker} 뉴스 분석 ===\n")
    result = analyze_ticker(client, test_ticker)
    if result:
        print(f"감성 점수: {result.sentiment_score:+d} ({result.confidence})")
        print(f"\n요약: {result.summary}")
        print(f"\n호재:")
        for c in result.catalysts:
            print(f"  + {c}")
        print(f"\n리스크:")
        for r in result.risks:
            print(f"  - {r}")
    else:
        print("분석 실패 또는 뉴스 없음")
