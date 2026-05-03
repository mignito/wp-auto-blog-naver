"""
네이버 블로그 주식 분석 자동 포스팅

사용법:
  python main.py                    # 네이버페이 인기 종목 → 분석 → 발행
  python main.py --login            # 로그인 + 쿠키 저장
  python main.py --export-cookies   # GitHub Secret용 base64 쿠키 출력
  python main.py --dry              # 발행 없이 HTML 미리보기만
  python main.py --stock 005930     # 종목코드 직접 지정 (삼성전자=005930)
"""

import os
import sys
import json
import argparse
from datetime import datetime
from dotenv import load_dotenv

# 한글/특수문자 콘솔 출력 보장 (cp949 인코딩 오류 방지)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from stock_finder      import StockFinder
from content_generator import ContentGenerator
from naver_publisher   import NaverPublisher


def check_env():
    missing = [v for v in ["ANTHROPIC_API_KEY", "NAVER_BLOG_ID"] if not os.getenv(v)]
    if missing:
        print(f"오류: 환경변수 누락 → {', '.join(missing)}")
        sys.exit(1)


def export_cookies_b64():
    import base64
    cookie_file = "cookies/naver_cookies.json"
    if not os.path.exists(cookie_file):
        print("쿠키 파일 없음. 먼저 실행: python main.py --login")
        sys.exit(1)
    with open(cookie_file, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    print("\n" + "="*60)
    print("  GitHub Secret → NAVER_COOKIES_B64 에 아래 값 붙여넣기")
    print("="*60)
    print(b64)
    print("="*60 + "\n")


def save_log(article: dict, post_url: str):
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/{datetime.now().strftime('%Y-%m')}_posts.jsonl"
    entry = {
        "date":       datetime.now().isoformat(),
        "stock_name": article.get("stock_name", ""),
        "stock_code": article.get("stock_code", ""),
        "title":      article["title"],
        "post_url":   post_url,
        "tags":       article.get("tags", []),
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  로그 저장: {log_file}")


def main():
    parser = argparse.ArgumentParser(description="네이버 블로그 주식 분석 자동 포스팅")
    parser.add_argument("--login",          action="store_true")
    parser.add_argument("--export-cookies", action="store_true")
    parser.add_argument("--dry",            action="store_true", help="발행 없이 미리보기")
    parser.add_argument("--stock",          type=str,            help="종목코드 직접 지정 (예: 005930)")
    args = parser.parse_args()

    if args.export_cookies:
        export_cookies_b64()
        return

    print("=" * 55)
    print(f"네이버 주식 분석 포스팅: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    check_env()

    # ── 로그인 테스트 ────────────────────────────────────────
    if args.login:
        print("\n[로그인 모드]")
        NaverPublisher().test_login()
        return

    # ── Step 1: 종목 선택 + 데이터 수집 ─────────────────────
    print("\n[Step 1] 종목 선택 및 데이터 수집")
    finder = StockFinder()

    if args.stock:
        # 직접 지정 종목
        from stock_finder import _fetch_yfinance, _generate_chart
        import base64
        print(f"  직접 지정 종목: {args.stock}")
        stock = _fetch_yfinance(args.stock, args.stock)
        if not stock:
            print("  데이터 수집 실패")
            sys.exit(1)
        _, b64, chart_path = _generate_chart(stock)
        stock["chart_b64"]  = b64
        stock["chart_file"] = chart_path
    else:
        stock = finder.get_hot_stock()

    # ── Step 2: 콘텐츠 생성 ──────────────────────────────────
    print(f"\n[Step 2] {stock['name']} 분석 콘텐츠 생성")
    gen     = ContentGenerator()
    article = gen.generate_article(stock)

    # ── --dry 미리보기 ────────────────────────────────────────
    if args.dry:
        print("\n[미리보기 모드 - 발행 안 함]")
        # 차트 base64 → data URL 로 치환
        content = article["content"]
        if stock.get("chart_b64"):
            data_url = f"data:image/png;base64,{stock['chart_b64']}"
            content  = content.replace("CHART_IMAGE", data_url)

        preview = f"preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        with open(preview, "w", encoding="utf-8") as f:
            f.write(f"""<!DOCTYPE html><html lang="ko"><head>
<meta charset="UTF-8"><title>{article['title']}</title>
<style>
  body{{font-family:'Malgun Gothic',sans-serif;max-width:860px;margin:0 auto;padding:24px;line-height:1.9;color:#333}}
  h2{{color:#1a1a2e;margin-top:32px;border-bottom:2px solid #e0e0e0;padding-bottom:6px}}
  h3{{color:#2c3e50}} table{{width:100%;border-collapse:collapse;margin:15px 0}}
  th,td{{border:1px solid #ddd;padding:10px;text-align:left}} th{{background:#f5f5f5}}
  img{{max-width:100%;border-radius:8px}} ul{{padding-left:24px}} li{{margin-bottom:6px}}
  .meta{{background:#e8f4fd;padding:14px;border-radius:6px;margin-bottom:20px;font-size:13px}}
</style></head><body>
<div class="meta">
  <strong>제목:</strong> {article['title']}<br>
  <strong>종목:</strong> {stock['name']} ({stock['code']})<br>
  <strong>태그:</strong> {', '.join(article['tags'])}
</div>
{content}
</body></html>""")
        print(f"  미리보기 저장: {preview}  (크롬으로 열어 확인)")
        return

    # ── Step 3: 네이버 발행 ───────────────────────────────────
    print("\n[Step 3] 네이버 블로그 발행")
    publisher = NaverPublisher()
    post_url  = publisher.publish(article, stock)

    save_log(article, post_url)

    print("\n" + "=" * 55)
    status = "발행" if os.getenv("POST_STATUS") == "publish" else "임시저장"
    print(f"완료! {status} → {post_url or '확인 필요'}")
    print("=" * 55)


if __name__ == "__main__":
    main()
