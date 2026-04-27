"""
주식 분석 블로그 콘텐츠 생성 모듈
비용 최적화:
  차트 분석 → Haiku Vision  (Sonnet 대비 ~80% 절감)
  본문 작성 → Sonnet        (품질 유지)
"""

import os
import re
import anthropic


DISCLAIMER = """\
<div style="background:#fff3cd;border-left:4px solid #ffc107;padding:14px 18px;margin:20px 0;border-radius:6px;font-size:14px;">
<strong>⚠️ 투자 유의사항</strong><br>
본 글은 투자 참고 정보이며, 매수·매도 권유가 아닙니다. 투자 결정은 본인 책임이며 원금 손실 가능성이 있습니다.
</div>"""

RELATED_FOOTER = """\
<hr style="border:none;border-top:1px solid #e0e0e0;margin:30px 0;">
<div style="background:#f0f4ff;border:1px solid #c5d0f0;padding:20px;margin:20px 0;border-radius:8px;">
<h3 style="margin-top:0;color:#2c3e50;font-size:16px;">함께 보면 좋은 정보</h3>
<ul style="margin:0;padding-left:20px;line-height:2.4;">
  <li><a href="https://winone-life.com" target="_blank" rel="noopener">생활 속 금융·절세 꿀팁 — winone-life.com</a></li>
  <li><a href="https://winone-worekr.com" target="_blank" rel="noopener">직장인 재테크·노무 정보 — winone-worekr.com</a></li>
</ul>
</div>"""


def _fmt(n, unit="원") -> str:
    if n is None:
        return "N/A"
    try:
        n = float(n)
        if abs(n) >= 1e12: return f"{n/1e12:.1f}조{unit}"
        if abs(n) >= 1e8:  return f"{n/1e8:.0f}억{unit}"
        if abs(n) >= 1e4:  return f"{n/1e4:.0f}만{unit}"
        return f"{n:,.0f}{unit}"
    except Exception:
        return str(n)


class ContentGenerator:
    def __init__(self):
        self.client      = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model       = "claude-sonnet-4-6"
        self.cheap_model = "claude-haiku-4-5-20251001"

    def _call(self, system: str, user: str, max_tokens: int,
              cheap: bool = False, chart_b64: str = None) -> str:
        import time
        model = self.cheap_model if cheap else self.model
        content = []
        if chart_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": chart_b64}
            })
        content.append({"type": "text", "text": user})

        for attempt in range(3):
            try:
                msg = self.client.messages.create(
                    model=model, max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": content}]
                )
                return self._clean(msg.content[0].text)
            except Exception as e:
                if "529" in str(e) or "overloaded" in str(e).lower():
                    wait = 30 * (attempt + 1)
                    print(f"  Claude 과부하. {wait}초 대기...")
                    time.sleep(wait)
                else:
                    raise

    def _clean(self, text: str) -> str:
        text = re.sub(r"^```html\s*|^```\s*|\s*```$|```html|```", "", text.strip())
        return text.strip()

    # ── [Haiku Vision] 차트 분석 ────────────────────────────────
    def _analyze_chart(self, chart_b64: str, stock: dict) -> str:
        """Haiku Vision 사용 — Sonnet 대비 ~80% 비용 절감"""
        name  = stock["name"]
        price = stock.get("price", 0)
        chg   = stock.get("change_pct", 0)
        w52h  = f"{stock['week52_high']:,.0f}" if stock.get("week52_high") else "N/A"
        w52l  = f"{stock['week52_low']:,.0f}"  if stock.get("week52_low")  else "N/A"

        system = "주식 기술적 분석가. HTML만 출력(```없이). 허용 태그: p strong ul li."

        user = (
            f"{name} 3개월 차트. 현재가 {price:,.0f}원({chg:+.2f}%), "
            f"52주 고/저 {w52h}/{w52l}원. "
            "종가선(파랑) MA5(노랑) MA20(빨강) 거래량 포함.\n\n"
            "4항목을 각각 <p>로 작성:\n"
            "1. <strong>추세 분석</strong> — 단기/중기 추세, 이동평균 배열\n"
            "2. <strong>주요 가격대</strong> — 지지선·저항선, 현재가 위치\n"
            "3. <strong>거래량 분석</strong> — 패턴, 가격과의 관계\n"
            "4. <strong>기술적 신호</strong> — 주목할 신호 및 주의 패턴"
        )

        return self._call(system, user, max_tokens=800, cheap=True, chart_b64=chart_b64)

    # ── [Sonnet] 본문 작성 ───────────────────────────────────────
    def _write_body(self, stock: dict, chart_analysis: str) -> str:
        name  = stock["name"]
        code  = stock["code"]
        price = stock.get("price", 0)
        chg   = stock.get("change_pct", 0)

        per  = f"{stock['per']:.1f}배"       if stock.get("per")            else "N/A"
        pbr  = f"{stock['pbr']:.2f}배"       if stock.get("pbr")            else "N/A"
        roe  = f"{stock['roe']*100:.1f}%"    if stock.get("roe")            else "N/A"
        eps  = f"{stock['eps']:,.0f}원"      if stock.get("eps")            else "N/A"
        d2e  = f"{stock['debt_to_equity']:.0f}%" if stock.get("debt_to_equity") else "N/A"
        mcap = _fmt(stock.get("market_cap"))
        rev  = _fmt(stock.get("revenue"))
        oi   = _fmt(stock.get("operating_income"))
        w52h = f"{stock['week52_high']:,.0f}원" if stock.get("week52_high") else "N/A"
        w52l = f"{stock['week52_low']:,.0f}원"  if stock.get("week52_low")  else "N/A"
        summary = (stock.get("summary") or "")[:250]  # 600→250 으로 압축

        system = (
            f"한국 주식 블로거(10년 경력). 개인투자자용 분석 글. "
            "친근한 문체(거든요/더라고요). HTML만 출력(```없이)."
        )

        user = f"""{name}({code}) 주식 분석 블로그 글 작성.

종목: {name} | 현재가: {price:,.0f}원({chg:+.2f}%) | 52주 고/저: {w52h}/{w52l}
시가총액: {mcap} | PER: {per} | PBR: {pbr} | ROE: {roe} | EPS: {eps} | 부채비율: {d2e}
매출: {rev} | 영업이익: {oi} | 섹터: {stock.get('sector','')} | 업종: {stock.get('industry','')}
회사개요: {summary}

구조 (HTML, 1200~1800자):
1. 도입 <p> — 오늘 네이버페이 인기 종목 소개
2. <h2>{name} 회사 소개</h2>
3. <h2>재무 분석</h2> — 지표 해석 + <table>로 핵심 지표 정리
4. <h2>사업 분석</h2> — 경쟁력·트렌드·리스크
5. <h2>차트 분석</h2> — 반드시 포함: <figure style="margin:20px 0;text-align:center;"><img src="CHART_IMAGE" alt="{name} 차트" style="max-width:100%;border-radius:8px;" /></figure>
6. <h2>투자 포인트</h2> — 긍정 3가지·리스크 2가지 ul>li"""

        body = self._call(system, user, max_tokens=3000)  # 4500→3000

        # 차트 분석 결과를 </figure> 뒤에 삽입
        body = body.replace("</figure>", f"</figure>\n{chart_analysis}", 1)
        return body

    # ── 공개 메서드 ──────────────────────────────────────────────
    def generate_article(self, stock: dict) -> dict:
        name = stock["name"]
        code = stock["code"]

        print(f"  [1/2] 차트 분석 (Haiku Vision)...")
        chart_analysis = self._analyze_chart(stock["chart_b64"], stock)

        print(f"  [2/2] 본문 작성 (Sonnet)...")
        body = self._write_body(stock, chart_analysis)

        full_content = DISCLAIMER + "\n" + body + "\n" + RELATED_FOOTER

        from datetime import datetime
        today    = datetime.now().strftime("%m월 %d일")
        chg      = stock.get("change_pct", 0)
        chg_word = "급등" if chg >= 3 else ("상승" if chg >= 0 else "하락")
        title    = f"{today} {name} 주가 {chg_word} | 재무·차트 분석 총정리"

        tags = [
            name, f"{name} 주가", f"{name} 주식 분석",
            "네이버페이 증권", "오늘 인기 종목",
            "주식 분석", "재무분석", "차트분석",
            stock.get("sector", "주식투자"), "개인투자자",
        ]

        print(f"  완료 | 제목: {title}")
        return {
            "title":      title,
            "content":    full_content,
            "tags":       [t for t in tags if t][:10],
            "chart_file": stock.get("chart_file", ""),
            "stock_name": name,
            "stock_code": code,
        }
