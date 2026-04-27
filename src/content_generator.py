"""
주식 분석 블로그 콘텐츠 생성 모듈

비용 구조:
  재무 테이블  → Python 직접 생성 (토큰 0)
  차트 분석    → Haiku Vision (메인 섹션, 토큰 확장)
  회사·투자    → Haiku 텍스트 (초단축)
  Sonnet 호출  → 없음
예상 비용: ~$0.008/회 (~11원), 월 30회 ~330원
"""

import os
import re
import anthropic


DISCLAIMER = (
    '<div style="background:#fff3cd;border-left:4px solid #ffc107;'
    'padding:12px 16px;margin:18px 0;border-radius:6px;font-size:13px;">'
    "<strong>투자 유의사항</strong> — 본 글은 참고 정보이며 매수·매도 권유가 아닙니다. "
    "투자 결정은 본인 책임이며 원금 손실 가능성이 있습니다.</div>"
)

RELATED_FOOTER = (
    '<hr style="border:none;border-top:1px solid #e0e0e0;margin:28px 0;">'
    '<div style="background:#f0f4ff;border:1px solid #c5d0f0;padding:18px;'
    'margin:18px 0;border-radius:8px;">'
    "<h3 style='margin-top:0;font-size:15px;color:#2c3e50;'>함께 보면 좋은 정보</h3>"
    '<ul style="margin:0;padding-left:20px;line-height:2.2;">'
    '<li><a href="https://winone-life.com" target="_blank" rel="noopener">'
    "생활 속 금융·절세 꿀팁 — winone-life.com</a></li>"
    '<li><a href="https://winone-worekr.com" target="_blank" rel="noopener">'
    "직장인 재테크·노무 정보 — winone-worekr.com</a></li>"
    "</ul></div>"
)


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


def _eval_per(per) -> str:
    if per is None: return ""
    if per < 10:    return "저평가 구간"
    if per < 20:    return "적정 수준"
    if per < 30:    return "다소 높음"
    return "고평가 주의"

def _eval_pbr(pbr) -> str:
    if pbr is None: return ""
    if pbr < 1.0:   return "자산 대비 저평가"
    if pbr < 2.0:   return "적정"
    return "프리미엄"

def _eval_roe(roe) -> str:
    if roe is None: return ""
    pct = roe * 100
    if pct >= 20:   return "우수"
    if pct >= 10:   return "양호"
    return "낮음"

def _eval_d2e(d2e) -> str:
    if d2e is None: return ""
    if d2e < 100:   return "안정"
    if d2e < 200:   return "보통"
    return "부채 주의"


class ContentGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model  = "claude-haiku-4-5-20251001"   # 모든 호출 Haiku

    def _call(self, system: str, user: str, max_tokens: int,
              chart_b64: str = None) -> str:
        import time
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
                    model=self.model, max_tokens=max_tokens,
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

    # ── [Python] 재무 지표 테이블 — 토큰 0 ─────────────────────
    def _build_finance_table(self, stock: dict) -> str:
        s = stock
        rows = [
            ("현재가",   f"{s.get('price',0):,.0f}원",          f"{s.get('change_pct',0):+.2f}%"),
            ("시가총액", _fmt(s.get("market_cap")),              ""),
            ("PER",      f"{s['per']:.1f}배"  if s.get("per")  else "N/A", _eval_per(s.get("per"))),
            ("PBR",      f"{s['pbr']:.2f}배"  if s.get("pbr")  else "N/A", _eval_pbr(s.get("pbr"))),
            ("ROE",      f"{s['roe']*100:.1f}%" if s.get("roe") else "N/A", _eval_roe(s.get("roe"))),
            ("EPS",      f"{s['eps']:,.0f}원" if s.get("eps")  else "N/A", ""),
            ("부채비율", f"{s['debt_to_equity']:.0f}%" if s.get("debt_to_equity") else "N/A",
                         _eval_d2e(s.get("debt_to_equity"))),
            ("매출액",   _fmt(s.get("revenue")),                ""),
            ("영업이익", _fmt(s.get("operating_income")),       ""),
            ("52주 고가",f"{s['week52_high']:,.0f}원" if s.get("week52_high") else "N/A", ""),
            ("52주 저가",f"{s['week52_low']:,.0f}원"  if s.get("week52_low")  else "N/A", ""),
        ]

        th = "padding:9px 12px;border:1px solid #dde;text-align:"
        html = (
            '<table style="width:100%;border-collapse:collapse;margin:14px 0;font-size:14px;">'
            '<thead><tr style="background:#f0f4ff;">'
            f'<th style="{th}left;">지표</th>'
            f'<th style="{th}right;">수치</th>'
            f'<th style="{th}center;">평가</th>'
            "</tr></thead><tbody>"
        )
        for i, (label, value, note) in enumerate(rows):
            bg = "#fff" if i % 2 == 0 else "#f9f9ff"
            note_html = f'<span style="color:#1a73e8;font-size:12px;">{note}</span>' if note else ""
            html += (
                f'<tr style="background:{bg};">'
                f'<td style="{th}left;">{label}</td>'
                f'<td style="{th}right;font-weight:bold;">{value}</td>'
                f'<td style="{th}center;">{note_html}</td>'
                "</tr>"
            )
        html += "</tbody></table>"
        return html

    # ── [Haiku Vision] 차트 분석 — 메인 섹션 ───────────────────
    def _analyze_chart(self, chart_b64: str, stock: dict) -> str:
        name  = stock["name"]
        price = stock.get("price", 0)
        chg   = stock.get("change_pct", 0)
        w52h  = f"{stock['week52_high']:,.0f}" if stock.get("week52_high") else "N/A"
        w52l  = f"{stock['week52_low']:,.0f}"  if stock.get("week52_low")  else "N/A"

        system = "주식 기술적 분석가. HTML만 출력(```없이). 허용 태그: p strong ul li span."

        user = (
            f"{name} 3개월 주가 차트.\n"
            f"현재가 {price:,.0f}원({chg:+.2f}%), 52주 고/저 {w52h}/{w52l}원.\n"
            "차트: 종가선(파랑) MA5(노랑) MA20(빨강) 52주선(점선) 거래량 바.\n\n"
            "아래 5항목을 각각 <p>로 구체적으로 분석 (수치 포함):\n"
            "1. <strong>추세 분석</strong> — 단기(1개월)·중기(3개월) 추세 방향, "
            "이동평균 정배열/역배열 여부\n"
            "2. <strong>지지·저항선</strong> — 주요 가격대, 현재가 위치, "
            "돌파 시 목표가/이탈 시 하락폭\n"
            "3. <strong>거래량 분석</strong> — 최근 거래량 증감, 가격·거래량 다이버전스 여부\n"
            "4. <strong>기술적 신호</strong> — 골든/데드크로스, 과매수·과매도 구간 여부\n"
            "5. <strong>단기 전망</strong> — 1~2주 시나리오 (상승/횡보/하락) 및 "
            "주목할 가격대"
        )

        return self._call(system, user, max_tokens=1200, chart_b64=chart_b64)

    # ── [Haiku] 회사 소개 + 투자 포인트 ─────────────────────────
    def _write_summary(self, stock: dict) -> str:
        name    = stock["name"]
        sector  = stock.get("sector", "")
        summary = (stock.get("summary") or "")[:150]

        user = (
            f"{name}({sector}) 주식 블로그 글.\n"
            f"회사개요: {summary}\n\n"
            "HTML로 작성:\n"
            f"1. <p> — {name} 핵심 사업 소개 (2문장)\n"
            "2. <h2>투자 포인트</h2>\n"
            "   <ul><li>긍정 포인트 3개 (한 줄씩)</li></ul>\n"
            "   <ul><li>주의 리스크 2개 (한 줄씩)</li></ul>"
        )

        return self._call("주식 블로거. HTML만 출력(```없이).", user, max_tokens=400)

    # ── 전체 글 조립 ─────────────────────────────────────────────
    def generate_article(self, stock: dict) -> dict:
        name = stock["name"]
        code = stock["code"]
        chg  = stock.get("change_pct", 0)

        print(f"  [1/2] 차트 분석 (Haiku Vision)...")
        chart_html = self._analyze_chart(stock["chart_b64"], stock)

        print(f"  [2/2] 회사 요약 (Haiku)...")
        summary_html = self._write_summary(stock)

        # 재무 테이블은 Python으로 직접 생성 (토큰 0)
        finance_table = self._build_finance_table(stock)

        # 차트 이미지 figure 태그
        chart_figure = (
            f'<figure style="margin:20px 0;text-align:center;">'
            f'<img src="CHART_IMAGE" alt="{name} 주가 차트" '
            f'style="max-width:100%;border-radius:8px;border:1px solid #dde;" />'
            f'</figure>'
        )

        today    = __import__("datetime").datetime.now().strftime("%m월 %d일")
        chg_word = "급등" if chg >= 3 else ("상승" if chg >= 0 else "하락")
        title    = f"{today} {name} 주가 {chg_word} | 차트·재무 분석"

        body = f"""<p>오늘 네이버페이 증권에서 가장 많이 조회된 종목은 <strong>{name}</strong>입니다.
현재가 <strong>{stock.get('price', 0):,.0f}원</strong> ({chg:+.2f}%)로 거래되고 있습니다.</p>

{summary_html}

<h2>재무 지표 요약</h2>
{finance_table}

<h2>차트 분석</h2>
{chart_figure}
{chart_html}
"""

        full_content = DISCLAIMER + "\n" + body + "\n" + RELATED_FOOTER

        tags = [
            name, f"{name} 주가", f"{name} 차트분석",
            "네이버페이 증권", "오늘 인기 종목",
            "주식 차트", "재무분석", "개인투자자",
            stock.get("sector", "주식"), "주식 분석",
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
