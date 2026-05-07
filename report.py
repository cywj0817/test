"""
HTML 리포트 생성 모듈 - GitHub Pages 배포용
- 모바일 친화적 반응형 디자인
- 다크모드 자동 감지 (prefers-color-scheme)
- 무료 모드 뉴스 분석 결과 포함
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import news_analyzer
from screener import Recommendation

KST = timezone(timedelta(hours=9))

_RECOMMENDATION_KR = {
    "strong_buy": "강력 매수",
    "buy": "매수",
    "hold": "보유",
    "underperform": "비중축소",
    "sell": "매도",
    "strong_sell": "강력 매도",
    "none": "의견 없음",
}


def _sentiment_label(score: int) -> str:
    if score >= 7: return "매우 긍정"
    if score >= 3: return "긍정"
    if score >= -2: return "중립"
    if score >= -6: return "부정"
    return "매우 부정"


def _table_row(r: Recommendation) -> str:
    stop_pct = (r.stop_loss / r.entry - 1) * 100
    tp_pct = (r.take_profit / r.entry - 1) * 100
    mom1_cls = "pos" if r.momentum_1m >= 0 else "neg"
    mom3_cls = "pos" if r.momentum_3m >= 0 else "neg"
    return f"""
      <tr>
        <td class="ticker">{escape(r.ticker)}</td>
        <td>{r.score:.1f}</td>
        <td>${r.entry:.2f}</td>
        <td class="neg">${r.stop_loss:.2f}<br><small>({stop_pct:+.1f}%)</small></td>
        <td class="pos">${r.take_profit:.2f}<br><small>({tp_pct:+.1f}%)</small></td>
        <td>{r.rsi:.0f}</td>
        <td class="{mom1_cls}">{r.momentum_1m:+.1f}%</td>
        <td class="{mom3_cls}">{r.momentum_3m:+.1f}%</td>
      </tr>"""


def _news_card(r: Recommendation) -> str:
    result = news_analyzer.analyze_ticker_free(r.ticker)
    score = result.sentiment_score
    badge_cls = "pos" if score >= 3 else "neg" if score <= -3 else "neutral"
    rec_kr = _RECOMMENDATION_KR.get(
        result.analyst_recommendation or "", result.analyst_recommendation or "—"
    )

    target_html = ""
    if result.target_mean_price:
        upside = result.target_upside_pct or 0
        upside_cls = "pos" if upside >= 0 else "neg"
        target_html = (
            f"<p>애널리스트 평균 목표가: "
            f"<strong>${result.target_mean_price:.2f}</strong> "
            f"(상승여력 <span class='{upside_cls}'>{upside:+.1f}%</span>)</p>"
        )

    analysts_html = ""
    if result.num_analysts:
        analysts_html = f" ({result.num_analysts}명)"

    headlines_html = ""
    if result.headlines:
        items = "".join(f"<li>{escape(h)}</li>" for h in result.headlines)
        headlines_html = f"<p><strong>최근 헤드라인:</strong></p><ul>{items}</ul>"
    else:
        headlines_html = "<p class='muted'>(최근 뉴스 없음)</p>"

    return f"""
    <div class="card">
      <h3>{escape(r.ticker)}
        <span class="badge {badge_cls}">감성 {score:+d}/10 · {_sentiment_label(score)}</span>
      </h3>
      <p>애널리스트 의견: <strong>{rec_kr}</strong>{analysts_html}</p>
      {target_html}
      {headlines_html}
    </div>"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>US Stock Screener — {date}</title>
<style>
  :root {{
    --bg: #ffffff; --bg-card: #f8f9fa; --text: #212529;
    --muted: #6c757d; --border: #dee2e6;
    --pos: #2e7d32; --neg: #c62828; --neutral: #757575;
    --accent: #1976d2;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #1a1a1a; --bg-card: #2a2a2a; --text: #e8e8e8;
      --muted: #9ca3af; --border: #404040;
      --pos: #66bb6a; --neg: #ef5350; --neutral: #9e9e9e;
      --accent: #42a5f5;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
    margin: 0; padding: 16px;
    background: var(--bg); color: var(--text);
    line-height: 1.6;
  }}
  .container {{ max-width: 980px; margin: 0 auto; }}
  header {{ margin-bottom: 24px; }}
  h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
  h2 {{ font-size: 1.25rem; margin: 32px 0 12px;
       border-bottom: 2px solid var(--accent); padding-bottom: 6px; }}
  .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table {{
    width: 100%; border-collapse: collapse;
    background: var(--bg-card); border-radius: 8px; overflow: hidden;
    font-size: 0.85rem; min-width: 580px;
  }}
  th, td {{ padding: 10px 8px; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: var(--border); font-weight: 600; font-size: 0.8rem; }}
  tr:not(:last-child) td {{ border-bottom: 1px solid var(--border); }}
  td.ticker {{ font-weight: 700; color: var(--accent); font-size: 1rem; }}
  td small {{ color: var(--muted); }}
  .pos {{ color: var(--pos); font-weight: 600; }}
  .neg {{ color: var(--neg); font-weight: 600; }}
  .muted {{ color: var(--muted); }}
  .card {{
    background: var(--bg-card); padding: 16px 18px; margin: 14px 0;
    border-radius: 8px; border-left: 4px solid var(--accent);
  }}
  .card h3 {{ margin: 0 0 10px; display: flex; align-items: center;
             flex-wrap: wrap; gap: 8px; font-size: 1.1rem; }}
  .card p {{ margin: 6px 0; }}
  .card ul {{ padding-left: 20px; margin: 6px 0; }}
  .card li {{ margin: 3px 0; }}
  .badge {{
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 0.78rem; font-weight: 500;
  }}
  .badge.pos {{ background: var(--pos); color: white; }}
  .badge.neg {{ background: var(--neg); color: white; }}
  .badge.neutral {{ background: var(--neutral); color: white; }}
  footer {{
    margin-top: 40px; padding-top: 16px;
    border-top: 1px solid var(--border);
    color: var(--muted); font-size: 0.8rem;
  }}
  @media (max-width: 600px) {{
    body {{ padding: 12px; }}
    h1 {{ font-size: 1.3rem; }}
    .card {{ padding: 14px; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>US Stock Screener</h1>
    <div class="subtitle">최종 업데이트: {date}</div>
  </header>

  <h2>스크리닝 결과 (상위 {n})</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Score</th>
          <th>Entry</th>
          <th>Stop Loss</th>
          <th>Take Profit</th>
          <th>RSI</th>
          <th>1M</th>
          <th>3M</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>

  <h2>뉴스 분석</h2>
  {news_cards}

  <footer>
    <strong>면책조항:</strong> 본 리포트는 기술적 스크리닝과 자동 뉴스 분석 결과로,
    투자 자문이 아닙니다. 실제 매매는 본인의 판단과 책임으로 진행하세요.
    Stop Loss는 -2 ATR, Take Profit은 +3 ATR 기준이며 시장 상황에 따라 조정이 필요할 수 있습니다.
    <br><br>
    감성 분석: VADER (헤드라인 기반) · 애널리스트 데이터: Yahoo Finance · 매일 한국시간 오전 7시 자동 업데이트
  </footer>
</div>
</body>
</html>
"""


def generate_html(recs: list[Recommendation], output_path: Path) -> None:
    """추천 종목 리스트를 받아 HTML 리포트를 지정 경로에 생성."""
    if not recs:
        rows = '<tr><td colspan="8" class="muted">조건을 만족하는 종목이 없습니다.</td></tr>'
        news_cards = '<p class="muted">분석할 종목이 없습니다.</p>'
    else:
        rows = "\n".join(_table_row(r) for r in recs)
        news_cards = "\n".join(_news_card(r) for r in recs)

    date_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    html = HTML_TEMPLATE.format(
        date=date_str,
        n=len(recs),
        rows=rows,
        news_cards=news_cards,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"[*] HTML 리포트 생성: {output_path.resolve()}")
