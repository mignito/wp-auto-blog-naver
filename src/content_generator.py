"""
주식 분석 블로그 콘텐츠 생성 모듈

비용 구조 (Haiku 4.5):
  재무 테이블  → Python 직접 생성 (토큰 0)
  차트 분석    → Haiku Vision, max_tokens=900
  투자 리포트  → Haiku 텍스트, max_tokens=1200
  제목 생성    → Haiku 텍스트, max_tokens=60
예상 비용: ~$0.008/회 (~11원), 2시간마다(월360회) ~$2.9 (~4,100원)
"""

import os
import re
import requests
import xml.etree.ElementTree as ET
import anthropic
from datetime import datetime


DISCLAIMER = (
    '<div style="background:#fff3cd;border-left:4px solid #ffc107;'
    'padding:12px 16px;margin:18px 0;border-radius:6px;font-size:13px;">'
    "<strong>투자 유의사항</strong> — 본 글은 참고 정보이며 매수·매도 권유가 아닙니다. "
    "투자 결정은 본인 책임이며 원금 손실 가능성이 있습니다.</div>"
)

# ── 관련 글 RSS 크롤링 ──────────────────────────────────────────
_RELATED_SITES = [
    ("winone-life.com",   "https://winone-life.com/feed/"),
    ("winone-worker.com", "https://winone-worker.com/feed/"),
]

_RELATED_FALLBACK = [
    {"title": "관리비 줄이는 방법 아파트 3가지 꿀팁 2026년 최신",
     "url": "https://winone-life.com/%ea%b4%80%eb%a6%ac%eb%b9%84-%ec%a4%84%ec%9d%b4%eb%8a%94-%eb%b0%a9%eb%b2%95-%ec%95%84%ed%8c%8c%ed%8a%b8/%ea%b8%b0%ed%83%80%ec%a0%95%eb%b3%b4/",
     "site": "winone-life.com"},
    {"title": "2026년 IRP 세액공제 한도 8가지 핵심 정리",
     "url": "https://winone-life.com/irp-%ec%84%b8%ec%95%a1%ea%b3%b5%ec%a0%9c-%ed%95%9c%eb%8f%84-2/%ea%b8%b0%ed%83%80%ec%a0%95%eb%b3%b4/",
     "site": "winone-life.com"},
    {"title": "소상공인 대출 신청 6가지 방법 완벽 정리",
     "url": "https://winone-worker.com/%ec%86%8c%ec%83%81%ea%b3%b5%ec%9d%b8-%eb%8c%80%ec%b6%9c-%ec%8b%a0%ec%b2%ad%eb%b0%a9%eb%b2%95-2/",
     "site": "winone-worker.com"},
    {"title": "상속세 절세 방법 2026 완벽 정리 | 꼭 알아야 할 핵심 정보",
     "url": "https://winone-worker.com/%ec%83%81%ec%86%8d%ec%84%b8-%ec%a0%88%ec%84%b8-%eb%b0%a9%eb%b2%95-2026/",
     "site": "winone-worker.com"},
]


def _fetch_related_posts() -> list:
    """RSS 피드에서 최신 글 2개씩 크롤링. 실패 시 fallback 반환."""
    posts = []
    for site_name, feed_url in _RELATED_SITES:
        try:
            resp = requests.get(
                feed_url, timeout=8,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:2]
            for item in items:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if title and link:
                    posts.append({"title": title, "url": link, "site": site_name})
        except Exception as e:
            print(f"  관련 글 크롤링 실패 ({site_name}): {e}")

    return posts if len(posts) >= 2 else _RELATED_FALLBACK


def _build_related_footer(posts: list) -> str:
    items_html = "\n".join(
        f'<li style="margin-bottom:10px;">'
        f'<a href="{p["url"]}" target="_blank" rel="noopener" '
        f'style="color:#1a5276;text-decoration:none;font-weight:500;">'
        f'📌 {p["title"]}</a>'
        f'<span style="font-size:12px;color:#999;margin-left:8px;">— {p["site"]}</span>'
        f"</li>"
        for p in posts
    )
    return (
        '<div style="border-top:1px solid #e0e0e0;margin:36px 0 0;padding-top:4px;"></div>'
        '<div style="background:#f8f9fa;border:1px solid #dee2e6;padding:20px 24px;'
        'margin:16px 0 8px;border-radius:8px;">'
        "<h3 style='margin-top:0;margin-bottom:12px;font-size:15px;color:#2c3e50;'>"
        "📚 함께 보면 좋은 정보</h3>"
        f'<ul style="margin:0;padding-left:20px;line-height:1.8;">'
        f'{items_html}'
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
    # Haiku 4.5 단가 (USD/1M tokens)
    _PRICE_IN  = 0.80
    _PRICE_OUT = 2.40

    def __init__(self):
        self.client    = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model     = "claude-haiku-4-5-20251001"
        self._total_in  = 0
        self._total_out = 0

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
                i = msg.usage.input_tokens
                o = msg.usage.output_tokens
                self._total_in  += i
                self._total_out += o
                cost = (i * self._PRICE_IN + o * self._PRICE_OUT) / 1_000_000
                print(f"    토큰: in={i} out={o} (${cost:.5f})")
                return self._clean(msg.content[0].text)
            except Exception as e:
                if "529" in str(e) or "overloaded" in str(e).lower():
                    wait = 30 * (attempt + 1)
                    print(f"  Claude 과부하. {wait}초 대기...")
                    time.sleep(wait)
                else:
                    raise

    def log_cost_summary(self):
        total = (self._total_in * self._PRICE_IN + self._total_out * self._PRICE_OUT) / 1_000_000
        print(f"  [API 비용] 총 in={self._total_in} out={self._total_out} → ${total:.5f} (≈{total*1400:.0f}원)")

    def _clean(self, text: str) -> str:
        text = re.sub(r"^```html\s*|^```\s*|\s*```$|```html|```", "", text.strip())
        text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<html[^>]*>|</html>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<head>.*?</head>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<body[^>]*>|</body>', '', text, flags=re.IGNORECASE)
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

    # ── [Haiku] 단기전망 요약 기반 제목 생성 ───────────────────
    def _generate_title(self, stock: dict, chart_analysis: str = "") -> str:
        name = stock["name"]
        chg  = stock.get("change_pct", 0)

        # 차트 분석에서 핵심 텍스트 추출
        context = ""
        if chart_analysis:
            plain = re.sub(r'<[^>]+>', ' ', chart_analysis)
            context = re.sub(r'\s+', ' ', plain).strip()[:500]

        user = (
            f"종목명: {name}, 오늘 등락률: {chg:+.2f}%\n"
            f"차트·투자 분석: {context}\n\n"
            "위 분석 내용을 바탕으로 이 종목의 단기 전망을 한 문구로 요약하라.\n\n"
            "출력 형식: {종목명} {단기전망 핵심내용}\n"
            "조건:\n"
            f"- 반드시 '{name}'으로 시작\n"
            "- 핵심 이유·키워드 포함 (예: 원자재 급락에 따른 기술적 조정, 실적 개선 기대에 단기 상승여지)\n"
            "- 전체 20자 내외\n"
            "- 문장 부호·따옴표·날짜·번호 포함 금지\n"
            "문구만 한 줄 출력."
        )
        raw = (self._call("주식 투자 애널리스트.", user, max_tokens=60) or "").strip()

        # 종목명으로 시작하지 않으면 앞에 붙이기
        if raw and not raw.startswith(name):
            raw = f"{name} {raw}"

        # fallback
        if not raw or len(raw) < len(name) + 3:
            raw = f"{name} {'단기 상승 흐름 지속 전망' if chg >= 0 else '단기 조정 가능성 주시'}"

        date_str = datetime.now().strftime("%y%m%d")
        return f"{raw}({date_str})"

    # ── [Haiku Vision] 차트 기술적 분석 ────────────────────────
    def _analyze_chart(self, chart_b64: str, stock: dict) -> str:
        name  = stock["name"]
        price = stock.get("price", 0)
        chg   = stock.get("change_pct", 0)
        w52h  = f"{stock['week52_high']:,.0f}" if stock.get("week52_high") else "N/A"
        w52l  = f"{stock['week52_low']:,.0f}"  if stock.get("week52_low")  else "N/A"

        system = (
            "주식 기술적 분석가. HTML만 출력(``` 없이). 허용 태그: h3 p strong ul li. "
            "문체: 반말 단문(했음·보임·예상됨·상승 중·돌파 시). '했습니다/됩니다' 금지. "
            "완성 우선: 앞 항목이 길어지면 줄이고 5번 항목까지 반드시 완성할 것."
        )
        user = (
            f"{name} 3개월 차트. 현재가 {price:,.0f}원({chg:+.2f}%), "
            f"52주 고/저 {w52h}/{w52l}원.\n"
            "차트: 종가선(파랑) MA5(노랑) MA20(빨강) 52주선(점선) 거래량 바.\n\n"
            "5항목을 <h3>소제목</h3><p>본문(1~2문장, 수치포함)</p><p></p> 형식으로 작성.\n"
            "각 항목 사이 빈 단락 <p></p> 삽입. 각 항목 본문은 1~2문장으로 간결하게.\n"
            "1. <h3>📈 추세 분석</h3> 단기·중기 방향, 이평 정/역배열\n"
            "2. <h3>🔍 지지·저항선</h3> 주요 가격대, 돌파/이탈 시나리오\n"
            "3. <h3>📊 거래량 분석</h3> 증감 추이, 가격-거래량 다이버전스\n"
            "4. <h3>⚡ 기술적 신호</h3> 골든/데드크로스, 과매수·과매도\n"
            "5. <h3>🎯 단기 전망(1~2주)</h3> 시나리오별 조건, 핵심 가격대"
        )
        return self._call(system, user, max_tokens=900, chart_b64=chart_b64)

    # ── [Haiku] 한경컨센서스 스타일 투자 리포트 ──────────────────
    def _write_summary(self, stock: dict, chart_analysis: str = "") -> str:
        name    = stock["name"]
        sector  = stock.get("sector", "")
        summary = (stock.get("summary") or "")[:200]
        price   = stock.get("price", 0)
        chg     = stock.get("change_pct", 0)
        per     = f"{stock['per']:.1f}배"  if stock.get("per")  else "N/A"
        pbr     = f"{stock['pbr']:.2f}배"  if stock.get("pbr")  else "N/A"
        roe     = f"{stock['roe']*100:.1f}%" if stock.get("roe") else "N/A"
        rev     = _fmt(stock.get("revenue"))
        oi      = _fmt(stock.get("operating_income"))
        w52h    = f"{stock['week52_high']:,.0f}" if stock.get("week52_high") else "N/A"
        w52l    = f"{stock['week52_low']:,.0f}"  if stock.get("week52_low")  else "N/A"

        # 차트 분석 텍스트에서 핵심 신호만 추출 (최대 500자)
        chart_context = ""
        if chart_analysis:
            plain = re.sub(r'<[^>]+>', ' ', chart_analysis)
            plain = re.sub(r'\s+', ' ', plain).strip()[:500]
            chart_context = f"\n\n[차트 기술 분석 요약]: {plain}"

        td = "padding:10px 14px;border:1px solid #dde;font-size:14px;"
        user = (
            f"종목:{name}({sector}), {price:,.0f}원({chg:+.2f}%)\n"
            f"PER:{per} PBR:{pbr} ROE:{roe} 52주고:{w52h} 52주저:{w52l}\n"
            f"매출:{rev} 영업이익:{oi}\n"
            f"기업개요:{summary}"
            + chart_context
            + "\n\n"
            "한국 증권사 투자 리포트 형식으로 HTML 작성. 아래 구조를 그대로 따를 것.\n"
            "허용 태그: h2 h3 p strong em ul li table tr td th div span.\n"
            "각 항목은 1~2문장으로 간결하게. 수치 반드시 포함. 마지막 결론까지 완성할 것.\n\n"

            "<h2>🏢 기업 개요</h2>\n"
            "<p>핵심 사업·경쟁력 1~2문장.</p>\n\n"

            "<h2>📰 시장 동향 및 핵심 이슈</h2>\n"
            f"<p><strong>오늘 주가 동향</strong>: {chg:+.2f}% 배경·원인 1문장.</p>\n"
            "<p></p>\n"
            f"<p><strong>섹터 트렌드</strong>: {sector} 업종 흐름·{name} 영향 1문장.</p>\n"
            "<p></p>\n"
            "<p><strong>주목 이슈</strong>: 실적·수주·정책 등 수치 포함 1문장.</p>\n"
            "<p></p>\n"
            "<p><strong>단기 전망</strong>: 1~4주 방향성·주요 변수 1문장.</p>\n"
            "<p></p>\n\n"

            "<h2>✅ 투자 포인트 (Bull vs Bear)</h2>\n"
            "수치(%, 원, 배) 포함. 표 금지, 문단으로.\n\n"

            "<h3 style='color:#1a7431;'>💚 강점 (Bull)</h3>\n"
            "<p><strong>① 실적·성장성</strong>: 매출·영업이익 YoY 수치 포함 1문장.</p>\n"
            "<p><strong>② 밸류에이션</strong>: PER·PBR 업종 평균 대비 1문장.</p>\n"
            "<p><strong>③ 기술적 지지</strong>: 이평선·지지선 매수 근거 1문장.</p>\n\n"

            "<h3 style='color:#b71c1c;'>🔴 리스크 (Bear)</h3>\n"
            "<p><strong>① 거시 환경</strong>: 금리·환율·경쟁 수치 포함 1문장.</p>\n"
            "<p><strong>② 실적 변동성</strong>: 하락 시나리오 1문장.</p>\n"
            "<p><strong>③ 기술적 하방</strong>: 손절 기준가·하락 목표가 1문장.</p>\n\n"

            "<h2>💼 투자 의견 및 전망</h2>\n"
            "<p><strong>밸류에이션</strong>: PER·PBR 평가 1문장.</p>\n"
            "<p></p>\n"
            "<p><strong>단기 전망</strong>: 1~4주 방향성·모니터링 가격대 1문장.</p>\n"
            "<p></p>\n"
            "<p><strong>결론</strong>: 투자 결론 1문장.</p>\n\n"

            "HTML만 출력. ``` 코드블록 없이."
        )
        return self._call(
            "국내 증권사 애널리스트. 한경컨센서스 스타일 투자 리포트 HTML만 출력. "
            "문체: 반말 단문(했음·예상됨·보임·상승 중). '했습니다/됩니다/입니다' 금지. "
            "완성 우선: 앞 섹션이 길어지면 요약하고 마지막 섹션(결론)까지 반드시 완성할 것.",
            user, max_tokens=1200
        )

    # ── 전체 글 조립 ─────────────────────────────────────────────
    def generate_article(self, stock: dict) -> dict:
        name  = stock["name"]
        code  = stock["code"]
        price = stock.get("price", 0)
        chg   = stock.get("change_pct", 0)

        print(f"  [1/4] 차트 기술 분석 (Haiku Vision)...")
        chart_html = self._analyze_chart(stock["chart_b64"], stock)

        print(f"  [2/4] 투자 리포트 작성 (Haiku, 차트 분석 반영)...")
        summary_html = self._write_summary(stock, chart_analysis=chart_html)

        print(f"  [3/4] 제목 생성 (단기전망 요약)...")
        title = self._generate_title(stock, chart_analysis=chart_html)

        print(f"  [4/4] 관련 글 크롤링 및 글 조립...")
        related_posts   = _fetch_related_posts()
        related_footer  = _build_related_footer(related_posts)

        finance_table = self._build_finance_table(stock)

        # 투자의견 박스 (등락률 기반 rough estimate)
        if chg >= 1.0:
            opinion, ocolor = "BUY", "#155724"
            target_price = int(price * 1.20 / 100) * 100
        elif chg <= -2.0:
            opinion, ocolor = "REDUCE", "#721c24"
            target_price = int(price * 0.90 / 100) * 100
        else:
            opinion, ocolor = "HOLD", "#7a5100"
            target_price = int(price * 1.08 / 100) * 100
        upside = ((target_price / price) - 1) * 100 if price else 0

        opinion_box = (
            f'<div style="background:#f8f9fa;border-left:5px solid {ocolor};'
            f'padding:14px 20px;border-radius:6px;margin:20px 0;">'
            f'<table style="width:100%;border:none;"><tr>'
            f'<td style="width:80px;font-size:22px;font-weight:900;color:{ocolor};">{opinion}</td>'
            f'<td style="text-align:center;font-size:13px;">목표주가<br>'
            f'<strong style="font-size:16px;">{target_price:,.0f}원</strong></td>'
            f'<td style="text-align:center;font-size:13px;">현재가<br>'
            f'<strong style="font-size:16px;">{price:,.0f}원</strong></td>'
            f'<td style="text-align:center;font-size:13px;">상승여력<br>'
            f'<strong style="font-size:16px;color:{ocolor};">{upside:+.1f}%</strong></td>'
            f'</tr></table></div>'
        )

        chart_figure = (
            f'<p style="text-align:center;">'
            f'<img src="CHART_IMAGE" alt="{name} 3개월 주가 차트" '
            f'style="max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.15);" />'
            f'</p>'
            f'<p style="text-align:center;font-size:12px;color:#888;margin-top:4px;">'
            f'▲ {name} 최근 3개월 주가 차트 (MA5·MA20·거래량)</p>'
        )

        HR = '<div style="border-top:2px solid #eee;margin:24px 0;height:1px;overflow:hidden;"></div>'

        body = (
            chart_figure                           # 차트 이미지 최상단
            + f"\n{HR}\n"
            + opinion_box
            + f"\n{HR}\n"
            + summary_html
            + f"\n{HR}\n"
            + f'<h2>📋 핵심 재무 지표</h2>\n'
            + finance_table
            + f"\n{HR}\n"
            + f'<h2>📈 주가 차트 기술적 분석 (3개월)</h2>\n'
            + chart_html
        )

        full_content = DISCLAIMER + "\n" + body + "\n" + related_footer

        sector = stock.get("sector", "주식")
        tags = [
            name, f"{name} 주가", f"{name} 주가 전망", f"{name} 차트",
            f"{name} 매수", f"{name} 매도", f"{name} 분석",
            code, f"{sector} 주식", f"{sector} 대장주",
            "오늘의 주식", "주식 추천", "주식 분석", "주식 차트",
            "개인투자자", "재무분석", "기술적분석", "국내주식",
            "투자리포트", "주식투자",
        ]

        print(f"  완료 | 제목: {title}")
        return {
            "title":      title,
            "content":    full_content,
            "tags":       [t for t in tags if t][:20],
            "chart_file": stock.get("chart_file", ""),
            "stock_name": name,
            "stock_code": code,
        }
