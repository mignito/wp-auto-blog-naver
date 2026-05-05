"""
네이버페이 증권 인기 종목 탐색 + 주식 데이터 수집 + 차트 생성
"""

import os
import io
import base64
import random
import time
import requests
from bs4 import BeautifulSoup

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

import yfinance as yf


# ── 한글 폰트 설정 ────────────────────────────────────────────
def _setup_font():
    candidates = ["Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"]
    available  = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False

_setup_font()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 스크래핑 실패 시 fallback 종목 목록
FALLBACK_STOCKS = [
    {"name": "삼성전자",       "code": "005930"},
    {"name": "SK하이닉스",     "code": "000660"},
    {"name": "LG에너지솔루션", "code": "373220"},
    {"name": "현대차",         "code": "005380"},
    {"name": "NAVER",          "code": "035420"},
    {"name": "카카오",         "code": "035720"},
    {"name": "삼성바이오로직스","code": "207940"},
    {"name": "KB금융",         "code": "105560"},
    {"name": "POSCO홀딩스",    "code": "005490"},
    {"name": "셀트리온",       "code": "068270"},
    {"name": "기아",           "code": "000270"},
    {"name": "삼성SDI",        "code": "006400"},
    {"name": "LG화학",         "code": "051910"},
    {"name": "SK이노베이션",   "code": "096770"},
    {"name": "현대모비스",     "code": "012330"},
    {"name": "삼성물산",       "code": "028260"},
    {"name": "LG전자",         "code": "066570"},
    {"name": "신한지주",       "code": "055550"},
    {"name": "하나금융지주",   "code": "086790"},
    {"name": "우리금융지주",   "code": "316140"},
    {"name": "카카오뱅크",     "code": "323410"},
    {"name": "크래프톤",       "code": "259960"},
    {"name": "엔씨소프트",     "code": "036570"},
    {"name": "넷마블",         "code": "251270"},
    {"name": "두산에너빌리티", "code": "034020"},
    {"name": "한국전력",       "code": "015760"},
    {"name": "CJ제일제당",     "code": "097950"},
    {"name": "아모레퍼시픽",   "code": "090430"},
    {"name": "LG생활건강",     "code": "051900"},
    {"name": "S-Oil",          "code": "010950"},
    {"name": "삼성생명",       "code": "032830"},
    {"name": "한국항공우주",   "code": "047810"},
]


# ── 네이버 금융 종목 스크래핑 공통 함수 ──────────────────────
# ETN/ETF/파생상품 필터 키워드 (yfinance 없고 블로그 주제로 부적합)
_SKIP_KEYWORDS = (
    'ETN', 'ETF', 'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO',
    '인버스', '레버리지', '선물', '스팩', 'SPAC', '리츠', 'REIT',
    'USD', 'WTI', 'VIX', '2X', '2배', 'N2 ',
)


def _is_valid_stock(name: str, code: str) -> bool:
    """파생상품/ETF/ETN 종목 제외"""
    up = name.upper()
    return not any(kw.upper() in up for kw in _SKIP_KEYWORDS)


def _scrape_naver_table(url: str, label: str, n: int = 10) -> list:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")
        stocks = []
        table = soup.find("table", class_="type_2")
        if not table:
            return []
        for tr in table.find_all("tr"):
            a = tr.find("a", href=lambda h: h and "code=" in h)
            if not a:
                continue
            code = a["href"].split("code=")[-1].strip()
            name = a.text.strip()
            if code and name and len(code) == 6 and code.isdigit():
                if _is_valid_stock(name, code):
                    stocks.append({"name": name, "code": code})
            if len(stocks) >= n:
                break
        print(f"  {label} {len(stocks)}개 수집: {[s['name'] for s in stocks[:5]]}")
        return stocks
    except Exception as e:
        print(f"  {label} 스크래핑 오류: {e}")
        return []


def _scrape_hot_stocks(n: int = 10) -> list:
    return _scrape_naver_table(
        "https://finance.naver.com/sise/lastsearch2.naver", "인기검색 종목", n
    )


def _scrape_rise_stocks(n: int = 10) -> list:
    return _scrape_naver_table(
        "https://finance.naver.com/sise/sise_rise.naver", "급상승 종목", n
    )


def _scrape_fall_stocks(n: int = 10) -> list:
    return _scrape_naver_table(
        "https://finance.naver.com/sise/sise_fall.naver", "급하락 종목", n
    )


def _scrape_volume_stocks(n: int = 10) -> list:
    return _scrape_naver_table(
        "https://finance.naver.com/sise/sise_quant.naver", "거래량 급증 종목", n
    )


# ── yfinance 데이터 수집 ──────────────────────────────────────
def _fetch_yfinance(code: str, name: str) -> dict | None:
    for suffix in [".KS", ".KQ"]:
        try:
            ticker = yf.Ticker(f"{code}{suffix}")
            info   = ticker.info
            price  = info.get("currentPrice") or info.get("regularMarketPrice")
            if not price:
                continue

            hist = ticker.history(period="3mo", interval="1d")
            if hist.empty or len(hist) < 10:
                continue

            return {
                "name":           name,
                "code":           code,
                "ticker":         f"{code}{suffix}",
                "price":          price,
                "change_pct":     round(info.get("regularMarketChangePercent", 0), 2),
                "market_cap":     info.get("marketCap", 0),
                "per":            info.get("trailingPE"),
                "pbr":            info.get("priceToBook"),
                "eps":            info.get("trailingEps"),
                "roe":            info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "revenue":        info.get("totalRevenue"),
                "operating_income": info.get("operatingIncome"),
                "sector":         info.get("sector", ""),
                "industry":       info.get("industry", ""),
                "summary":        info.get("longBusinessSummary", ""),
                "employees":      info.get("fullTimeEmployees"),
                "week52_high":    info.get("fiftyTwoWeekHigh"),
                "week52_low":     info.get("fiftyTwoWeekLow"),
                "avg_volume":     info.get("averageVolume"),
                "hist":           hist,
            }
        except Exception:
            pass
        time.sleep(0.3)
    return None


# ── 차트 생성 ────────────────────────────────────────────────
def _generate_chart(stock: dict) -> tuple:
    """
    주가 + 거래량 차트 PNG 생성.
    Returns: (png_bytes, base64_str, local_filepath)
    """
    hist = stock["hist"]
    name = stock["name"]
    code = stock["code"]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 5),
        gridspec_kw={"height_ratios": [3, 1]},
        facecolor="#0d1117"
    )
    ax1.set_facecolor("#0d1117")
    ax2.set_facecolor("#0d1117")

    # 이동평균선
    ma5  = hist["Close"].rolling(5).mean()
    ma20 = hist["Close"].rolling(20).mean()

    ax1.plot(hist.index, hist["Close"], color="#58a6ff", linewidth=1.8, label="종가",  zorder=3)
    ax1.plot(hist.index, ma5,           color="#f0c010", linewidth=1.0, label="MA5",   alpha=0.85)
    ax1.plot(hist.index, ma20,          color="#ff7b72", linewidth=1.0, label="MA20",  alpha=0.85)
    ax1.fill_between(hist.index, hist["Close"], hist["Close"].min() * 0.98,
                     alpha=0.07, color="#58a6ff")

    # 52주 고저선
    if stock.get("week52_high"):
        ax1.axhline(stock["week52_high"], color="#ff7b72", linestyle="--",
                    alpha=0.4, linewidth=0.9, label=f'52주 고가 {stock["week52_high"]:,.0f}')
    if stock.get("week52_low"):
        ax1.axhline(stock["week52_low"],  color="#3fb950", linestyle="--",
                    alpha=0.4, linewidth=0.9, label=f'52주 저가 {stock["week52_low"]:,.0f}')

    ax1.set_title(f"{name} ({code})  |  3개월 주가 차트",
                  color="#e6edf3", fontsize=13, pad=12, fontweight="bold")
    ax1.set_ylabel("주가 (원)", color="#8b949e", fontsize=10)
    ax1.tick_params(colors="#8b949e", labelsize=9)
    for sp in ax1.spines.values():
        sp.set_color("#30363d")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax1.grid(True, alpha=0.15, color="#30363d")
    ax1.legend(loc="upper left", facecolor="#161b22", labelcolor="#8b949e",
               fontsize=8, framealpha=0.8)

    # 거래량 (상승=초록 / 하락=빨강)
    colors = ["#3fb950" if c >= o else "#f85149"
              for c, o in zip(hist["Close"], hist["Open"])]
    ax2.bar(hist.index, hist["Volume"], color=colors, alpha=0.75, width=0.8)
    ax2.set_ylabel("거래량", color="#8b949e", fontsize=9)
    ax2.tick_params(colors="#8b949e", labelsize=8)
    for sp in ax2.spines.values():
        sp.set_color("#30363d")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda x, _: f"{int(x/1e4):,}만" if x >= 1e4 else f"{int(x):,}"
    ))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax2.grid(True, alpha=0.15, color="#30363d")

    plt.tight_layout(pad=1.5)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=72, bbox_inches="tight",
                facecolor="#0d1117")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    b64 = base64.b64encode(png_bytes).decode()

    # 로컬 저장
    os.makedirs("charts", exist_ok=True)
    chart_path = f"charts/{code}_chart.png"
    with open(chart_path, "wb") as f:
        f.write(png_bytes)

    return png_bytes, b64, chart_path


# ── 메인 클래스 ──────────────────────────────────────────────
class StockFinder:
    def get_hot_stock(self) -> dict:
        """
        종목 선택 우선순위 (최근 10개 중복 제외):
          1순위: 급상승 종목 (모멘텀)
          2순위: 거래량 급증 종목 (시장 관심)
          3순위: 인기 종목
          4순위: 급하락 종목 (반등 기대)
          5순위: 전체 중복 시 → 급하락 종목에서 강제 선택 (다양성 확보)
        """
        # 블로그 RSS + 로컬 이력 기반 중복 체크 함수 초기화
        self._recent_codes(10)
        is_recent = getattr(self, "_is_recent_fn", lambda code, name: False)

        rise   = _scrape_rise_stocks(10)
        volume = _scrape_volume_stocks(10)
        hot    = _scrape_hot_stocks(10)
        fall   = _scrape_fall_stocks(10)

        # 우선순위 순서로 중복 제거 후 단일 리스트 구성
        seen, priority_list = set(), []
        for stock in rise + volume + hot + fall:
            if stock["code"] not in seen:
                seen.add(stock["code"])
                priority_list.append(stock)

        if not priority_list:
            print("  스크래핑 전체 실패 → fallback 목록 사용")
            priority_list = FALLBACK_STOCKS.copy()
            random.shuffle(priority_list)

        non_recent = [c for c in priority_list if not is_recent(c["code"], c["name"])]
        skipped    = [c["name"] for c in priority_list if is_recent(c["code"], c["name"])]
        if skipped:
            print(f"  최근 10개 이내 중복 건너뜀: {skipped}")
        print(f"  선택 가능 후보: {len(non_recent)}개")

        # Phase 1: 최근 미포함 종목 우선순위 순서대로 시도
        for candidate in non_recent:
            name, code = candidate["name"], candidate["code"]
            print(f"  '{name}({code})' 데이터 수집 중...")
            data = _fetch_yfinance(code, name)
            if not data:
                print(f"    yfinance 데이터 없음, 다음으로")
                continue
            print(f"  [OK] {name} 선택 | {data['price']:,.0f}원 ({data['change_pct']:+.2f}%)")
            return self._attach_chart(data)

        # Phase 2: 모두 최근 이내 → 급하락 종목에서 강제 선택 (다양성 우선)
        print("  [경고] 모든 후보가 최근 10개 이내 → 급하락 종목 강제 선택")
        for candidate in fall:
            name, code = candidate["name"], candidate["code"]
            if not is_recent(code, name):
                data = _fetch_yfinance(code, name)
                if data:
                    print(f"  [강제선택-하락주] {name} ({data['change_pct']:+.2f}%)")
                    return self._attach_chart(data)

        # Phase 3: 최후 수단 — recent 필터 완전 해제
        print("  [최후수단] recent 필터 해제 후 재시도")
        for candidate in priority_list[:5]:
            name, code = candidate["name"], candidate["code"]
            data = _fetch_yfinance(code, name)
            if data:
                return self._attach_chart(data)

        raise RuntimeError("주식 데이터 수집 실패 (모든 후보 불가)")

    def _attach_chart(self, data: dict) -> dict:
        print("  차트 생성 중...")
        png_bytes, b64, chart_path = _generate_chart(data)
        data["chart_bytes"] = png_bytes
        data["chart_b64"]   = b64
        data["chart_file"]  = chart_path
        print(f"  [OK] 차트 저장: {chart_path}")
        return data

    def _recent_codes(self, n: int) -> set:
        """
        중복 방지: 블로그 RSS + 로컬 이력 두 곳에서 최근 n개 종목명 확인.

        우선순위:
          1. 네이버 블로그 RSS (실제 발행 기준, 가장 신뢰)
          2. data/recent_stocks.json (git 영속, RSS 실패 시 fallback)
        """
        blog_id = os.getenv("NAVER_BLOG_ID", "")
        names_from_blog: set = set()

        # ── 블로그 RSS에서 최근 제목 수집 ─────────────────────────
        if blog_id:
            try:
                import xml.etree.ElementTree as ET
                rss_url = f"https://rss.blog.naver.com/{blog_id}.xml"
                resp = requests.get(rss_url, timeout=8, headers=HEADERS)
                root = ET.fromstring(resp.content)
                titles = [item.findtext("title", "") for item in root.findall(".//item")][:n]
                for title in titles:
                    names_from_blog.add(title)
                print(f"  블로그 RSS 최근 {len(titles)}개 제목 수집 완료")
            except Exception as e:
                print(f"  블로그 RSS 수집 실패 (fallback 사용): {e}")

        # ── 로컬 이력에서 종목 코드 수집 ─────────────────────────
        import json
        local_codes: set = set()
        local_names: set = set()
        path = "data/recent_stocks.json"
        try:
            with open(path, encoding="utf-8") as f:
                records = json.load(f)
            local_codes = {r["code"] for r in records[-n:]}
            local_names = {r["name"] for r in records[-n:]}
        except Exception:
            pass

        # ── 후보 종목이 최근 발행됐는지 확인하는 함수 ────────────
        # 블로그 제목에 종목명이 포함되면 중복으로 판단
        def is_recent(stock_code: str, stock_name: str) -> bool:
            if stock_code in local_codes:
                return True
            if stock_name in local_names:
                return True
            for title in names_from_blog:
                if stock_name in title:
                    return True
            return False

        # StockFinder 인스턴스에 저장 (get_hot_stock에서 활용)
        self._is_recent_fn = is_recent
        return local_codes  # 호환성 유지용 반환값 (실제 체크는 _is_recent_fn 사용)
