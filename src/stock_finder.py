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
    {"name": "삼성전자",      "code": "005930"},
    {"name": "SK하이닉스",    "code": "000660"},
    {"name": "LG에너지솔루션","code": "373220"},
    {"name": "현대차",        "code": "005380"},
    {"name": "NAVER",        "code": "035420"},
    {"name": "카카오",        "code": "035720"},
    {"name": "삼성바이오로직스","code": "207940"},
    {"name": "KB금융",        "code": "105560"},
    {"name": "POSCO홀딩스",   "code": "005490"},
    {"name": "셀트리온",      "code": "068270"},
]


# ── 네이버 금융 인기 종목 스크래핑 ───────────────────────────
def _scrape_hot_stocks(n: int = 10) -> list:
    url = "https://finance.naver.com/sise/lastsearch2.naver"
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
                stocks.append({"name": name, "code": code})
            if len(stocks) >= n:
                break

        print(f"  네이버 인기 종목 {len(stocks)}개 수집: {[s['name'] for s in stocks[:5]]}")
        return stocks
    except Exception as e:
        print(f"  네이버 스크래핑 오류: {e}")
        return []


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
        2, 1, figsize=(11, 7),
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
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
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
        오늘 네이버페이 인기 종목 → yfinance 데이터 + 차트 반환.
        이미 분석한 종목 중복 방지를 위해 logs 를 참조.
        """
        candidates = _scrape_hot_stocks(10)
        if not candidates:
            print("  스크래핑 실패 → fallback 목록 사용")
            candidates = FALLBACK_STOCKS.copy()
            random.shuffle(candidates)

        # 최근 발행 종목 중복 방지
        recent = self._recent_codes(3)

        ordered = [c for c in candidates if c["code"] not in recent] + \
                  [c for c in candidates if c["code"] in recent]

        for candidate in ordered[:6]:
            name, code = candidate["name"], candidate["code"]
            print(f"  '{name}({code})' 데이터 수집 중...")
            data = _fetch_yfinance(code, name)
            if not data:
                print(f"    yfinance 데이터 없음, 다음 종목으로")
                continue

            print(f"  [OK] {name} 선택 | 현재가 {data['price']:,.0f}원 ({data['change_pct']:+.2f}%)")
            print("  차트 생성 중...")
            png_bytes, b64, chart_path = _generate_chart(data)
            data["chart_bytes"] = png_bytes
            data["chart_b64"]   = b64
            data["chart_file"]  = chart_path
            print(f"  [OK] 차트 저장: {chart_path}")
            return data

        raise RuntimeError("주식 데이터 수집 실패 (모든 후보 불가)")

    def _recent_codes(self, n: int) -> set:
        import json
        codes = set()
        log_dir = "logs"
        if not os.path.isdir(log_dir):
            return codes
        for fname in sorted(os.listdir(log_dir), reverse=True)[:2]:
            try:
                with open(os.path.join(log_dir, fname), encoding="utf-8") as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        c = entry.get("stock_code")
                        if c:
                            codes.add(c)
                        if len(codes) >= n:
                            return codes
            except Exception:
                pass
        return codes
