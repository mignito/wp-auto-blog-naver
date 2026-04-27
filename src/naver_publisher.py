"""
네이버 블로그 자동 포스팅 모듈
- undetected-chromedriver로 봇 감지 우회
- 쿠키 기반 세션 유지 (재로그인 최소화)
- 스마트에디터 ONE(SE ONE) JavaScript 인젝션
"""

import os
import json
import time
import random
import tempfile
import requests
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains


COOKIE_FILE = "cookies/naver_cookies.json"
WRITE_URL   = "https://blog.naver.com/{blog_id}/postwrite"
CHECK_URL   = "https://blog.naver.com/{blog_id}"


class NaverPublisher:
    def __init__(self):
        self.blog_id     = os.getenv("NAVER_BLOG_ID", "")
        self.username    = os.getenv("NAVER_USERNAME", "")
        self.password    = os.getenv("NAVER_PASSWORD", "")
        self.post_status = os.getenv("POST_STATUS", "draft")     # draft | publish
        self.category    = os.getenv("POST_CATEGORY", "")
        self.headless    = os.getenv("HEADLESS", "false").lower() == "true"
        self.driver      = None

    # ── Chrome 드라이버 ─────────────────────────────────────────
    def _setup_driver(self):
        options = uc.ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1280,900")
        options.add_argument("--lang=ko-KR")
        # detect installed Chrome version to download matching ChromeDriver
        import subprocess, re as _re
        ver = None
        for reg_path in [
            r"HKCU\SOFTWARE\Google\Chrome\BLBeacon",
            r"HKLM\SOFTWARE\Google\Chrome\BLBeacon",
            r"HKLM\SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon",
        ]:
            try:
                out = subprocess.check_output(
                    ["reg", "query", reg_path, "/v", "version"],
                    stderr=subprocess.DEVNULL
                ).decode(errors="ignore")
                m = _re.search(r"(\d+)\.\d+\.\d+\.\d+", out)
                if m:
                    ver = int(m.group(1))
                    break
            except Exception:
                pass
        print(f"  Chrome 버전 감지: {ver}")
        kwargs = {"options": options}
        if ver:
            kwargs["version_main"] = ver
        self.driver = uc.Chrome(**kwargs)
        self.driver.implicitly_wait(5)

    def _quit(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None

    # ── 쿠키 저장/로드 ──────────────────────────────────────────
    def _save_cookies(self):
        Path("cookies").mkdir(exist_ok=True)
        cookies = self.driver.get_cookies()
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        print(f"  쿠키 저장 완료: {COOKIE_FILE} ({len(cookies)}개)")

    def _load_cookies(self) -> bool:
        if not Path(COOKIE_FILE).exists():
            return False
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            self.driver.get("https://www.naver.com")
            time.sleep(2)
            for cookie in cookies:
                cookie.pop("sameSite", None)
                try:
                    self.driver.add_cookie(cookie)
                except Exception:
                    pass
            self.driver.refresh()
            time.sleep(2)
            return True
        except Exception as e:
            print(f"  쿠키 로드 오류: {e}")
            return False

    def _is_logged_in(self) -> bool:
        """로그인 상태 확인 (네이버 메인에서 로그인 여부 체크)"""
        try:
            self.driver.get("https://www.naver.com")
            time.sleep(2)
            # 로그인 시 .MyView-module__link_login 가 없어야 함
            # 또는 .gnb_name (아이디 표시) 요소가 있으면 로그인 상태
            elements = self.driver.find_elements(By.CSS_SELECTOR, ".gnb_name, .MyView-module__link_id__KvCqN")
            if elements:
                print(f"  로그인 상태 확인: {elements[0].text}")
                return True
            # 로그인 버튼이 있으면 로그아웃 상태
            login_btns = self.driver.find_elements(By.CSS_SELECTOR, ".link_login, [class*='login']")
            for btn in login_btns:
                if "로그인" in btn.text:
                    return False
            return False
        except Exception as e:
            print(f"  로그인 상태 확인 오류: {e}")
            return False

    # ── 로그인 ──────────────────────────────────────────────────
    def _manual_login_wait(self) -> bool:
        """자동 로그인 시도 → 실패 시 수동 대기 (non-headless)"""
        print("  자동 로그인 시도 중...")
        if self._auto_login():
            return True

        # 자동 로그인 실패 + headless이면 포기
        if self.headless:
            print("  헤드리스 모드에서 자동 로그인 실패.")
            return False

        # non-headless: 90초 폴링 방식 수동 로그인 대기 (input() 없음)
        print("\n" + "="*55)
        print("  [수동 로그인 필요] 브라우저 창에서 네이버에 로그인하세요.")
        print("  120초 안에 로그인하면 자동으로 계속 진행됩니다.")
        print("="*55)
        self.driver.get("https://nid.naver.com/nidlogin.login")
        deadline = time.time() + 120
        while time.time() < deadline:
            remaining = int(deadline - time.time())
            print(f"\r  로그인 대기 중... {remaining}초 남음", end="", flush=True)
            time.sleep(3)
            if self._is_logged_in():
                print()
                self._save_cookies()
                print("  로그인 성공, 쿠키 저장 완료")
                return True
        print("\n  120초 초과 - 로그인 실패")
        return False

    def _auto_login(self) -> bool:
        """자동 ID/PW 입력 로그인 (봇 감지 주의)"""
        if not self.username or not self.password:
            print("  NAVER_USERNAME, NAVER_PASSWORD 환경변수가 없습니다.")
            return False
        try:
            self.driver.get("https://nid.naver.com/nidlogin.login")
            time.sleep(2)

            id_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "id"))
            )
            # 사람처럼 천천히 타이핑
            for char in self.username:
                id_field.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))

            time.sleep(random.uniform(0.3, 0.7))

            pw_field = self.driver.find_element(By.ID, "pw")
            for char in self.password:
                pw_field.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))

            time.sleep(random.uniform(0.5, 1.0))
            pw_field.send_keys(Keys.RETURN)
            time.sleep(5)

            if self._is_logged_in():
                self._save_cookies()
                return True
            else:
                print("  자동 로그인 실패. 캡차 또는 2단계 인증이 필요할 수 있습니다.")
                print("  HEADLESS=false 로 설정하고 다시 실행해서 수동 로그인하세요.")
                return False
        except Exception as e:
            print(f"  자동 로그인 오류: {e}")
            return False

    def login(self) -> bool:
        """쿠키 로그인 시도 → 실패 시 수동/자동 로그인"""
        print("  쿠키로 로그인 시도 중...")
        if self._load_cookies() and self._is_logged_in():
            print("  쿠키 로그인 성공")
            return True

        print("  쿠키 로그인 실패. 새로 로그인합니다...")
        return self._manual_login_wait()

    # ── SE ONE 에디터 콘텐츠 주입 ──────────────────────────────
    def _wait_for_editor(self, timeout=30) -> bool:
        """SE ONE 에디터가 로드될 때까지 대기"""
        end = time.time() + timeout
        while time.time() < end:
            # 에디터 iframe 또는 contenteditable 확인
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                cls = iframe.get_attribute("class") or ""
                if "se" in src.lower() or "se" in cls.lower() or "editor" in cls.lower():
                    return True
            # 메인 문서에 contenteditable이 있는 경우
            edits = self.driver.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
            if edits:
                return True
            time.sleep(1)
        return False

    def _inject_title(self, title: str):
        """제목 입력 (메인 문서 내)"""
        selectors = [
            "textarea.se-title-text",
            "textarea[placeholder*='제목']",
            ".se-title-text",
            "input[placeholder*='제목']",
        ]
        for sel in selectors:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                el = els[0]
                el.click()
                time.sleep(0.3)
                el.send_keys(Keys.CONTROL + "a")
                el.send_keys(Keys.DELETE)
                time.sleep(0.2)
                for char in title:
                    el.send_keys(char)
                    time.sleep(random.uniform(0.01, 0.04))
                print(f"  제목 입력 완료: {title[:40]}...")
                return True
        print("  [경고] 제목 입력 필드를 찾지 못했습니다.")
        return False

    def _inject_body_in_iframe(self, iframe, html: str) -> bool:
        """iframe 내부 SE ONE 에디터에 HTML 주입"""
        try:
            self.driver.switch_to.frame(iframe)
            time.sleep(1)

            # contenteditable 요소 찾기
            candidates = self.driver.find_elements(
                By.CSS_SELECTOR, ".se-content, [contenteditable='true']"
            )
            if not candidates:
                self.driver.switch_to.default_content()
                return False

            editor = candidates[0]
            self.driver.execute_script("arguments[0].focus();", editor)
            time.sleep(0.5)

            # 기존 내용 전체 선택 후 삭제
            self.driver.execute_script(
                "document.execCommand('selectAll', false, null);"
            )
            time.sleep(0.2)

            # HTML 삽입
            result = self.driver.execute_script(
                "return document.execCommand('insertHTML', false, arguments[0]);",
                html
            )
            time.sleep(0.5)

            if not result:
                # execCommand 실패 시 innerHTML 직접 주입
                self.driver.execute_script("""
                    arguments[0].innerHTML = arguments[1];
                    arguments[0].dispatchEvent(new InputEvent('input', {bubbles: true}));
                """, editor, html)

            # 변경 사항 확인
            content_len = self.driver.execute_script(
                "return arguments[0].innerText.length;", editor
            )
            self.driver.switch_to.default_content()
            print(f"  본문 주입 완료 (약 {content_len}자)")
            return content_len > 50

        except Exception as e:
            print(f"  iframe 본문 주입 오류: {e}")
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            return False

    def _inject_body(self, html: str) -> bool:
        """SE ONE 에디터에 본문 HTML 주입 (iframe 순회)"""
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        print(f"  iframe {len(iframes)}개 발견, SE ONE 에디터 탐색 중...")

        for i, iframe in enumerate(iframes):
            src = iframe.get_attribute("src") or ""
            cls = iframe.get_attribute("class") or ""
            if "se" in src.lower() or "se" in cls.lower() or "editor" in cls.lower() or not src:
                print(f"  iframe[{i}] 시도 중 (class={cls[:40]})")
                if self._inject_body_in_iframe(iframe, html):
                    return True
                # 이전 상태로 복귀 후 다음 iframe 시도
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")

        # 메인 문서 내 contenteditable 시도 (iframe 아닌 경우)
        editors = self.driver.find_elements(
            By.CSS_SELECTOR, ".se-content[contenteditable='true'], [contenteditable='true']"
        )
        if editors:
            editor = editors[0]
            self.driver.execute_script("arguments[0].focus();", editor)
            time.sleep(0.3)
            self.driver.execute_script(
                "document.execCommand('selectAll', false, null);"
            )
            self.driver.execute_script(
                "document.execCommand('insertHTML', false, arguments[0]);",
                html
            )
            print("  메인 문서 에디터에 본문 주입 완료")
            return True

        print("  [경고] SE ONE 에디터를 찾지 못했습니다.")
        return False

    def _inject_tags(self, tags: list):
        """태그 입력"""
        if not tags:
            return
        selectors = [
            "input[placeholder*='태그']",
            ".tag-input input",
            "#SE-tagInput",
            ".HashTag input",
        ]
        tag_input = None
        for sel in selectors:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                tag_input = els[0]
                break

        if not tag_input:
            print("  태그 입력 필드를 찾지 못했습니다 (건너뜀)")
            return

        for tag in tags[:10]:
            try:
                tag_input.click()
                time.sleep(0.3)
                tag_input.send_keys(tag)
                time.sleep(0.3)
                tag_input.send_keys(Keys.RETURN)
                time.sleep(0.3)
                print(f"  태그 추가: #{tag}")
            except Exception as e:
                print(f"  태그 '{tag}' 추가 실패: {e}")

    def _click_publish_or_draft(self) -> str:
        """
        발행 또는 임시저장 버튼 클릭 후 게시글 URL 반환
        POST_STATUS=publish  → 발행
        POST_STATUS=draft    → 임시저장
        """
        is_publish = self.post_status == "publish"
        action_text = "발행" if is_publish else "임시저장"

        # 발행/임시저장 버튼 탐색
        btn_selectors = [
            f"button[class*='publish']",
            f"button[class*='Publish']",
            "button[class*='save']",
            "button[class*='Save']",
            f"//button[contains(text(),'{action_text}')]",
        ]

        btn = None
        for sel in btn_selectors:
            try:
                if sel.startswith("//"):
                    els = self.driver.find_elements(By.XPATH, sel)
                else:
                    els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    # 텍스트로 재필터링
                    for el in els:
                        if action_text in el.text or not el.text:
                            btn = el
                            break
                    if btn:
                        break
            except Exception:
                pass

        # 텍스트 전체 탐색 (fallback)
        if not btn:
            all_btns = self.driver.find_elements(By.TAG_NAME, "button")
            for b in all_btns:
                if action_text in (b.text or ""):
                    btn = b
                    break

        if not btn:
            print(f"  [경고] '{action_text}' 버튼을 찾지 못했습니다.")
            # 현재 URL 반환 (부분 성공)
            return self.driver.current_url

        btn.click()
        time.sleep(3)

        # 발행 확인 팝업이 뜨는 경우 처리
        try:
            confirm_btns = self.driver.find_elements(
                By.XPATH, "//button[contains(text(),'확인') or contains(text(),'발행')]"
            )
            if confirm_btns:
                confirm_btns[-1].click()
                time.sleep(3)
        except Exception:
            pass

        post_url = self.driver.current_url
        print(f"  게시글 URL: {post_url}")
        return post_url

    # ── 이미지 업로드 (선택) ────────────────────────────────────
    def _upload_image_to_naver(self, image_url: str) -> str:
        """
        Pexels 등 외부 이미지를 임시 다운로드 후 네이버에 업로드.
        성공하면 네이버 CDN URL 반환, 실패하면 원본 URL 반환.
        """
        if not image_url:
            return ""
        try:
            resp = requests.get(image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return image_url

            suffix = ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            # 사진 추가 버튼 클릭
            photo_btns = self.driver.find_elements(
                By.XPATH,
                "//button[contains(@class,'photo') or contains(text(),'사진')]"
            )
            if not photo_btns:
                return image_url

            photo_btns[0].click()
            time.sleep(2)

            # 파일 선택 input
            file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if file_inputs:
                file_inputs[0].send_keys(tmp_path)
                time.sleep(4)

            import os as _os
            _os.unlink(tmp_path)
            return ""  # 업로드 후 URL은 별도 추출 필요 (구현 복잡)
        except Exception as e:
            print(f"  이미지 업로드 오류 (외부 URL 사용): {e}")
            return image_url

    # ── 메인 발행 ───────────────────────────────────────────────
    def publish(self, article: dict, stock: dict) -> str:
        """
        네이버 블로그에 주식 분석 글 발행.
        chart_b64 를 data URL로 임베드해서 별도 업로드 불필요.
        반환값: 게시글 URL (실패 시 빈 문자열)
        """
        if not self.blog_id:
            print("  NAVER_BLOG_ID 환경변수가 없습니다.")
            return ""

        self._setup_driver()
        try:
            if not self.login():
                print("  로그인 실패. 종료합니다.")
                return ""

            write_url = WRITE_URL.format(blog_id=self.blog_id)
            print(f"  글쓰기 페이지 이동: {write_url}")
            self.driver.get(write_url)
            time.sleep(4)

            if not self._wait_for_editor(timeout=30):
                print("  [경고] 에디터 로딩 타임아웃. 계속 시도합니다...")

            time.sleep(2)

            # 제목 입력
            self._inject_title(article["title"])
            time.sleep(1)

            # 차트 이미지를 base64 data URL로 임베드
            import re
            content_html = article["content"]
            chart_b64 = stock.get("chart_b64", "")
            if chart_b64:
                data_url = f"data:image/png;base64,{chart_b64}"
                content_html = content_html.replace("CHART_IMAGE", data_url)
                print("  차트 이미지 base64 임베드 완료")
            else:
                # 차트 없으면 figure 태그 제거
                content_html = re.sub(
                    r'<figure[^>]*>.*?</figure>', '', content_html, flags=re.DOTALL
                )

            # 본문 입력
            self._inject_body(content_html)
            time.sleep(1)

            # 태그 입력
            tags = article.get("tags", [])
            if tags:
                self._inject_tags(tags)
                time.sleep(1)

            # 발행 또는 임시저장
            post_url = self._click_publish_or_draft()
            return post_url

        except Exception as e:
            import traceback
            print(f"  발행 중 오류: {e}")
            traceback.print_exc()
            return ""
        finally:
            self._quit()

    def test_login(self) -> bool:
        """로그인 테스트만 실행"""
        self._setup_driver()
        try:
            result = self.login()
            if result:
                print("  로그인 테스트 성공")
            else:
                print("  로그인 테스트 실패")
            return result
        finally:
            self._quit()
