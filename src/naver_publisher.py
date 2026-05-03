"""
네이버 블로그 자동 포스팅 모듈
- undetected-chromedriver로 봇 감지 우회
- 쿠키 기반 세션 유지 (재로그인 최소화)
- 스마트에디터 ONE(SE ONE) 클립보드 paste 방식 콘텐츠 주입
"""

import os
import json
import time
import random
from pathlib import Path

import platform
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

IS_WINDOWS = platform.system() == "Windows"


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
        """NID_AUT / NID_SES 쿠키 존재 여부로 로그인 확인"""
        try:
            cookies = self.driver.get_cookies()
            for c in cookies:
                if c.get("name") in ("NID_AUT", "NID_SES") and c.get("value"):
                    print(f"  로그인 쿠키 확인 ({c['name']})")
                    return True
            return False
        except Exception as e:
            print(f"  로그인 상태 확인 오류: {e}")
            return False

    # ── 로그인 ──────────────────────────────────────────────────
    def _manual_login_wait(self) -> bool:
        """비헤드리스: 수동 로그인 / 헤드리스: 자동 로그인"""
        if self.headless:
            print("  자동 로그인 시도 중...")
            if self._auto_login():
                return True
            print("  헤드리스 자동 로그인 실패.")
            return False

        # non-headless: 수동 로그인 (봇 감지 방지를 위해 자동 입력 안 함)
        print("\n" + "="*55)
        print("  [브라우저 로그인 필요]")
        print("  지금 열리는 Chrome 창에서 네이버에 로그인하세요.")
        print("  로그인 완료되면 자동으로 감지합니다.")
        print("="*55)
        self.driver.get("https://nid.naver.com/nidlogin.login")
        self.driver.maximize_window()

        deadline = time.time() + 180
        while time.time() < deadline:
            remaining = int(deadline - time.time())
            print(f"\r  로그인 대기 중... {remaining}초 남음  ", end="", flush=True)
            time.sleep(2)
            try:
                cur = self.driver.current_url
                if "nid.naver.com" not in cur and "naver.com" in cur:
                    cookies = self.driver.get_cookies()
                    if any(c.get("name") in ("NID_AUT", "NID_SES") for c in cookies):
                        print("\n  로그인 감지!")
                        self._save_cookies()
                        print("  쿠키 저장 완료")
                        return True
            except Exception:
                pass
        print("\n  3분 초과 - 로그인 실패")
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

    # ── SE ONE 에디터 로딩 대기 ──────────────────────────────────
    def _wait_for_editor(self, timeout=30) -> bool:
        """SE ONE 에디터가 로드될 때까지 대기"""
        end = time.time() + timeout
        while time.time() < end:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                cls = iframe.get_attribute("class") or ""
                if "se" in src.lower() or "se" in cls.lower() or "editor" in cls.lower():
                    return True
            edits = self.driver.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
            if edits:
                return True
            time.sleep(1)
        return False

    # ── SE ONE 제목 입력 ─────────────────────────────────────────
    def _inject_title(self, title: str):
        """SE ONE 제목 입력 — panels 닫기 → scroll top → ActionChains click+send_keys"""
        title = title.replace('\xa0', ' ').replace('​', '').strip()

        try:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)
        except Exception:
            pass

        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.4)

        try:
            el = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "div.se-title-text"))
            )
        except Exception:
            print("  [경고] 제목 div 못 찾음")
            return False

        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.3)

        def _actual():
            return (self.driver.execute_script(
                "var e=document.querySelector('div.se-title-text'); return e?e.innerText:'';"
            ) or "").replace('\xa0', ' ').strip()

        # Strategy A: ActionChains click → Ctrl+A → send_keys (to active element)
        try:
            ActionChains(self.driver).move_to_element(el).click().perform()
            time.sleep(0.4)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
            time.sleep(0.2)
            ActionChains(self.driver).send_keys(title).perform()
            time.sleep(0.5)
            if title[:6] in _actual():
                print(f"  제목 입력 완료 (ActionChains): {title[:50]}")
                return True
        except Exception as e:
            print(f"  제목 ActionChains 실패: {e}")

        # Strategy B: JS execCommand fallback
        try:
            ActionChains(self.driver).move_to_element(el).click().perform()
            time.sleep(0.3)
            self.driver.execute_script("""
                var el = document.querySelector('div.se-title-text');
                if (!el) return;
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                document.execCommand('insertText', false, arguments[0]);
            """, title)
            time.sleep(0.4)
            if title[:6] in _actual():
                print(f"  제목 입력 완료 (execCommand): {title[:50]}")
                return True
        except Exception as e:
            print(f"  제목 execCommand 실패: {e}")

        print(f"  [경고] 제목 입력 실패 (현재값: '{_actual()[:30]}')")
        return False

    # ── SE ONE 본문 주입 (clipboard paste) ──────────────────────
    def _inject_body_via_paste(self, html: str, append: bool = False) -> bool:
        """임시 탭 HTML 복사 → SE ONE 본문 클릭 → Ctrl+V 붙여넣기
        append=True 이면 Ctrl+A 생략 (차트 등 기존 내용 보존)"""
        import tempfile, os as _os, re as _re
        tmp_path = None
        orig_handle = self.driver.current_window_handle
        try:
            # base64 이미지 제거
            html_small = _re.sub(r'src="data:image/[^"]{100,}"', 'src=""', html)

            # 1. 임시 HTML 파일 생성 + 새 탭에서 열기
            tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8')
            tmp.write(f"<html><body>{html_small}</body></html>")
            tmp.close()
            tmp_path = tmp.name.replace('\\', '/')

            self.driver.switch_to.new_window('tab')
            self.driver.get(f'file:///{tmp_path}')
            time.sleep(2)

            # 2. Ctrl+A → Ctrl+C
            body = self.driver.find_element(By.TAG_NAME, 'body')
            body.click()
            time.sleep(0.3)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
            time.sleep(0.4)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('c').key_up(Keys.CONTROL).perform()
            time.sleep(0.4)

            # 3. 탭 닫기 후 에디터 복귀
            self.driver.get('about:blank')
            time.sleep(0.3)
            self.driver.close()
            self.driver.switch_to.window(orig_handle)
            time.sleep(1)
            print("  클립보드 복사 완료, 에디터 복귀")

            if append:
                # append 모드: 차트 등 기존 내용 보존 — 클릭 없이 현재 커서 위치에 Ctrl+V
                # (publish()에서 이미 Ctrl+End로 커서를 최하단에 위치시킴)
                print("  append 모드: 현재 커서 위치에 직접 붙여넣기")
            else:
                # 빈 에디터 모드: SE ONE 본문 영역 클릭 후 Ctrl+A → Ctrl+V
                clicked = False
                selectors = [
                    '.se-placeholder',                    # SE ONE 빈 에디터 placeholder
                    '.se-text-paragraph',                  # SE ONE 텍스트 단락
                    '.se-section-content',                 # SE ONE 섹션 내용
                    '[contenteditable][data-placeholder]', # data-placeholder 있는 contenteditable
                    '.se-component',                       # SE ONE 컴포넌트
                ]
                for sel in selectors:
                    target = self.driver.execute_script(f"""
                        var el = document.querySelector('{sel}');
                        if (!el) return null;
                        var r = el.getBoundingClientRect();
                        if (r.width > 5 && r.height > 0 && r.top >= 0 && r.top < window.innerHeight)
                            return el;
                        return null;
                    """)
                    if target:
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
                            time.sleep(0.2)
                            ActionChains(self.driver).move_to_element(target).click().perform()
                            time.sleep(0.3)
                            active_cls = self.driver.execute_script("return document.activeElement.className;") or ""
                            if 'title' not in active_cls.lower():
                                print(f"  본문 클릭 완료 (selector='{sel}', active='{active_cls[:40]}')")
                                clicked = True
                                break
                            else:
                                print(f"  selector='{sel}' → title에 포커스됨, 다음 시도")
                        except Exception as _e:
                            print(f"  selector='{sel}' 클릭 실패: {str(_e)[:60]}")

                if not clicked:
                    print("  [경고] SE ONE 본문 셀렉터 실패, 좌표 클릭 시도")
                    try:
                        title_el = self.driver.find_element(By.CSS_SELECTOR, "div.se-title-text")
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'start'});", title_el)
                        time.sleep(0.3)
                        ActionChains(self.driver).move_to_element_with_offset(title_el, 0, 150).click().perform()
                        time.sleep(0.3)
                        print("  좌표 클릭 완료 (title+150px)")
                    except Exception as _e2:
                        print(f"  좌표 클릭 실패: {_e2}")

                ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                time.sleep(0.3)

            # 5. Ctrl+V 붙여넣기
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
            time.sleep(3)

            self.driver.save_screenshot("debug_after_paste.png")

            # 붙여넣기 결과 확인 — SE ONE placeholder 숨김 여부 + 컴포넌트 수로 판단
            result = self.driver.execute_script("""
                var ph = document.querySelector('.se-placeholder');
                if (ph) {
                    var s = window.getComputedStyle(ph);
                    if (s.display === 'none' || s.visibility === 'hidden' || ph.offsetHeight === 0)
                        return {ok: true, reason: 'placeholder hidden'};
                } else {
                    return {ok: true, reason: 'no placeholder'};
                }
                var comps = document.querySelectorAll('.se-component');
                if (comps.length > 3) return {ok: true, reason: 'components=' + comps.length};
                var body = document.querySelector('.se-body');
                if (body) {
                    var len = (body.innerText || '').trim().length;
                    if (len > 100) return {ok: true, reason: 'text=' + len};
                }
                return {ok: false, reason: 'placeholder visible, components=' + comps.length};
            """)
            ok = result.get('ok', False) if result else False
            reason = result.get('reason', '?') if result else '?'
            print(f"  붙여넣기 결과: {'성공' if ok else '실패'} ({reason})")
            return ok

        except Exception as e:
            print(f"  paste 주입 오류: {e}")
            try:
                if self.driver.current_window_handle != orig_handle:
                    self.driver.get('about:blank')
                    time.sleep(0.3)
                    self.driver.close()
                    self.driver.switch_to.window(orig_handle)
            except Exception:
                pass
            return False
        finally:
            if tmp_path and _os.path.exists(tmp_path):
                try:
                    _os.unlink(tmp_path)
                except Exception:
                    pass

    def _inject_body_via_js_html(self, html: str) -> bool:
        """SE ONE 본문에 innerHTML 직접 주입 (paste 실패 시 fallback)"""
        try:
            result = self.driver.execute_script("""
                var editor = document.querySelector('.se-content[contenteditable]')
                           || document.querySelector('.se-content[contenteditable="true"]');
                if (!editor) {
                    var all = Array.from(document.querySelectorAll('[contenteditable]'));
                    for (var e of all) {
                        if (e.getAttribute('contenteditable') === 'false') continue;
                        var cls = e.className || '';
                        if (cls.includes('title') || cls.includes('Title')) continue;
                        editor = e; break;
                    }
                }
                if (!editor) return 'not found';
                editor.focus();
                editor.innerHTML = arguments[0];
                editor.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:''}));
                editor.dispatchEvent(new Event('change', {bubbles:true}));
                var txt = (editor.innerText || '').trim();
                return 'ok:cls=' + (editor.className||'(empty)') + ':len=' + txt.length + ':tag=' + editor.tagName;
            """, html)
            print(f"  본문 innerHTML 주입: {result}")
            if result and result.startswith('ok'):
                time.sleep(1)
                self.driver.save_screenshot("debug_body_injected.png")
                return True
            return False
        except Exception as e:
            print(f"  본문 innerHTML 오류: {e}")
            return False

    # ── 태그 입력 ────────────────────────────────────────────────
    def _inject_tags(self, tags: list):
        """태그 입력 — 페이지 하단 스크롤 후 태그 input/contenteditable 탐색"""
        if not tags:
            return

        # 페이지 하단으로 스크롤하여 태그 입력 필드 노출
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        tag_input = self.driver.execute_script("""
            // 1순위: SE ONE 태그 전용 input
            var selectors = [
                'input.se-tag-input',
                'input[class*="tag"]',
                'div[class*="tag"] input',
                '.se-tag-field input',
                '.tag-input input',
            ];
            for (var sel of selectors) {
                var el = document.querySelector(sel);
                if (el) return el;
            }
            // 2순위: placeholder에 '태그' 포함하는 모든 input
            var inputs = Array.from(document.querySelectorAll('input'));
            for (var inp of inputs) {
                var ph = (inp.getAttribute('placeholder') || '').toLowerCase();
                var cls = (inp.className || '').toLowerCase();
                var nm  = (inp.getAttribute('name') || '').toLowerCase();
                if (ph.includes('태그') || ph.includes('tag') ||
                    cls.includes('tag') || nm.includes('tag')) {
                    return inp;
                }
            }
            // 3순위: contenteditable 태그 영역 (SE ONE div 기반 태그)
            var ces = Array.from(document.querySelectorAll('[contenteditable]'));
            for (var ce of ces) {
                var cls2 = (ce.className || '').toLowerCase();
                var ph2  = (ce.getAttribute('data-placeholder') || '').toLowerCase();
                if (cls2.includes('tag') || ph2.includes('태그') || ph2.includes('tag')) {
                    return ce;
                }
            }
            return null;
        """)

        if not tag_input:
            # 4순위: '태그' 텍스트 근처의 input/contenteditable
            tag_input = self.driver.execute_script("""
                var all = Array.from(document.querySelectorAll('label, span, p, div, h4'));
                for (var el of all) {
                    var txt = (el.textContent || '').trim();
                    if (txt === '태그' || txt === '태그 입력') {
                        var parent = el.closest('div, section, li, form');
                        if (parent) {
                            var inp = parent.querySelector('input, [contenteditable="true"]');
                            if (inp) return inp;
                        }
                    }
                }
                return null;
            """)

        if not tag_input:
            # 디버그: 화면의 모든 input 출력
            debug = self.driver.execute_script("""
                return Array.from(document.querySelectorAll('input')).map(function(i){
                    return (i.className||'') + '|' + (i.getAttribute('placeholder')||'') + '|' + (i.name||'');
                });
            """)
            print(f"  [태그 디버그] input 목록: {debug[:5]}")
            print("  태그 입력 필드를 찾지 못했습니다 (건너뜀)")
            return

        tag_type = self.driver.execute_script("return arguments[0].tagName;", tag_input)
        print(f"  태그 입력 필드 발견: <{tag_type}>")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tag_input)
        time.sleep(0.5)

        for tag in tags[:10]:
            try:
                ActionChains(self.driver).move_to_element(tag_input).click().perform()
                time.sleep(0.3)
                ActionChains(self.driver).send_keys(tag).perform()
                time.sleep(0.3)
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                time.sleep(0.4)
                print(f"  태그 추가: #{tag}")
            except Exception as e:
                print(f"  태그 '{tag}' 추가 실패: {e}")

    # ── 발행 / 임시저장 ──────────────────────────────────────────
    def _click_publish_or_draft(self) -> str:
        """발행 또는 임시저장"""
        is_publish = self.post_status == "publish"

        if not is_publish:
            if IS_WINDOWS and not self.headless:
                print("  임시저장 중 (Win32 Ctrl+S)...")
                import subprocess as _sp2
                win2 = self.driver.get_window_position()
                chrome_ui_h2 = self.driver.execute_script("return window.outerHeight - window.innerHeight;")
                sx2 = win2['x'] + 640
                sy2 = win2['y'] + chrome_ui_h2 + 320
                ps_save = f"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class U32Save {{
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, IntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
}}
'@
$chrome = Get-Process -Name "chrome" -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
if ($chrome) {{
    [U32Save]::ShowWindow($chrome.MainWindowHandle, 9)
    [U32Save]::SetForegroundWindow($chrome.MainWindowHandle)
    Start-Sleep -Milliseconds 400
}}
[U32Save]::SetCursorPos({sx2}, {sy2})
Start-Sleep -Milliseconds 150
[U32Save]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 80
[U32Save]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 400
[U32Save]::keybd_event(0x11, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 60
[U32Save]::keybd_event(0x53, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 60
[U32Save]::keybd_event(0x53, 0, 2, [IntPtr]::Zero)
Start-Sleep -Milliseconds 60
[U32Save]::keybd_event(0x11, 0, 2, [IntPtr]::Zero)
"""
                _sp2.run(['powershell', '-NonInteractive', '-Command', ps_save], capture_output=True, timeout=20)
            else:
                print("  임시저장 중 (Selenium Ctrl+S)...")
                self.driver.execute_script("""
                    var ed = document.querySelector('.se-content[contenteditable]')
                             || document.querySelector('[contenteditable="true"]');
                    if (ed) { ed.focus(); }
                """)
                time.sleep(0.3)
                ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('s').key_up(Keys.CONTROL).perform()

            time.sleep(5)
            self.driver.save_screenshot("debug_after_save.png")
            post_url = self.driver.current_url
            print(f"  임시저장 완료: {post_url}")
            return post_url

        # 발행: "글 올리기" 또는 "발행" 버튼 탐색
        publish_texts = ["글 올리기", "발행", "Publish", "공개발행"]
        btn = None

        all_btns = self.driver.find_elements(By.TAG_NAME, "button")
        print(f"  [발행] 버튼 {len(all_btns)}개 탐색 중...")
        for b in all_btns:
            txt = (b.text or "").strip()
            if any(t in txt for t in publish_texts):
                btn = b
                print(f"  발행 버튼 발견: '{txt}'")
                break

        if not btn:
            print("  [경고] 발행 버튼을 찾지 못해 Ctrl+Enter 시도...")
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys(Keys.RETURN).key_up(Keys.CONTROL).perform()
            time.sleep(3)
            return self.driver.current_url

        btn.click()
        time.sleep(3)  # 발행 설정 패널 애니메이션 대기

        # 발행 설정 패널의 "✔ 발행" 확인 버튼 클릭
        confirmed = False
        try:
            all_publish = self.driver.find_elements(By.TAG_NAME, "button")
            publish_btns = [b for b in all_publish if '발행' in (b.text or '')]
            print(f"  '발행' 텍스트 포함 버튼: {len(publish_btns)}개 → {[b.text.strip()[:15] for b in publish_btns]}")
            if len(publish_btns) >= 2:
                confirm_btn = publish_btns[-1]
                print(f"  발행 확인 클릭: '{confirm_btn.text.strip()}'")
                self.driver.execute_script("arguments[0].click();", confirm_btn)
                confirmed = True
                time.sleep(5)
            elif len(publish_btns) == 1:
                time.sleep(2)
                all_publish2 = self.driver.find_elements(By.TAG_NAME, "button")
                publish_btns2 = [b for b in all_publish2 if '발행' in (b.text or '')]
                print(f"  재탐색: {len(publish_btns2)}개")
                if len(publish_btns2) >= 2:
                    self.driver.execute_script("arguments[0].click();", publish_btns2[-1])
                    confirmed = True
                    time.sleep(5)
        except Exception as e:
            print(f"  발행 확인 버튼 오류: {e}")

        if not confirmed:
            print("  [경고] 발행 확인 버튼 못 찾음, 현재 URL 반환")

        # 발행 후 URL 변경 대기 (postwrite → 실제 게시글 URL)
        try:
            WebDriverWait(self.driver, 15).until(
                lambda d: "postwrite" not in d.current_url
            )
        except Exception:
            pass

        post_url = self.driver.current_url
        print(f"  게시글 URL: {post_url}")
        return post_url

    # ── SE ONE 차트 이미지 업로드 ────────────────────────────────
    def _insert_chart_image(self, chart_path: str) -> bool:
        """SE ONE 이미지 버튼으로 차트 PNG 업로드 삽입"""
        if not chart_path or not os.path.exists(chart_path):
            return False
        abs_path = str(Path(chart_path).resolve())
        try:
            img_btn = self.driver.execute_script("""
                var btns = Array.from(document.querySelectorAll('button'));
                for (var b of btns) {
                    var lbl = (b.getAttribute('aria-label') || b.getAttribute('title') || '').toLowerCase();
                    var cls = (b.className || '').toLowerCase();
                    if (lbl.includes('사진') || lbl.includes('이미지') ||
                        cls.includes('photo') || cls.includes('se-image')) {
                        var r = b.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return b;
                    }
                }
                return null;
            """)
            if not img_btn:
                print("  이미지 업로드 버튼 못 찾음 (건너뜀)")
                return False

            self.driver.execute_script("arguments[0].click();", img_btn)
            time.sleep(2)
            self.driver.save_screenshot("debug_image_modal.png")

            file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if not file_inputs:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                print("  파일 input 없음 (건너뜀)")
                return False

            file_inputs[0].send_keys(abs_path)
            time.sleep(6)

            confirm_btn = self.driver.execute_script("""
                var btns = Array.from(document.querySelectorAll('button'));
                for (var b of btns) {
                    var txt = b.textContent.trim();
                    if (txt === '확인' || txt === '완료' || txt === '삽입' || txt === '업로드') {
                        var r = b.getBoundingClientRect();
                        if (r.width > 0) return b;
                    }
                }
                return null;
            """)
            if confirm_btn:
                self.driver.execute_script("arguments[0].click();", confirm_btn)
                time.sleep(3)

            self.driver.save_screenshot("debug_after_image.png")
            print(f"  차트 이미지 업로드 완료: {os.path.basename(chart_path)}")
            return True
        except Exception as e:
            print(f"  차트 이미지 업로드 오류: {e}")
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            return False

    # ── 메인 발행 ───────────────────────────────────────────────
    def publish(self, article: dict, stock: dict) -> str:
        """
        네이버 블로그에 주식 분석 글 발행.
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
            time.sleep(6)

            if not self._wait_for_editor(timeout=40):
                print("  [경고] 에디터 로딩 타임아웃. 계속 시도합니다...")

            time.sleep(3)

            # CHART_IMAGE placeholder 제거 (SE ONE이 data: URL을 차단하므로 업로드 방식 사용)
            import re as _re
            content_html = article["content"]
            content_html = _re.sub(
                r'<p[^>]*>\s*<img[^>]*src="CHART_IMAGE"[^>]*/>\s*</p>\s*'
                r'<p[^>]*>[^<]*차트[^<]*</p>',
                '', content_html
            )
            content_html = content_html.replace('src="CHART_IMAGE"', 'src=""')

            # 1. 임시저장 팝업 닫기 ('취소' JS 클릭)
            dismissed = self.driver.execute_script("""
                var btns = Array.from(document.querySelectorAll('button'));
                for (var b of btns) {
                    if (b.textContent.trim() === '취소') { b.click(); return true; }
                }
                return false;
            """)
            if dismissed:
                print("  임시저장 팝업 닫음 (취소 JS 클릭)")
                time.sleep(2.5)

            # 2. 도움말 패널 닫기 (overlay 제거)
            help_closed = self.driver.execute_script("""
                var btns = Array.from(document.querySelectorAll('button'));
                for (var b of btns) {
                    var rect = b.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) continue;
                    var lbl = b.getAttribute('aria-label') || '';
                    var txt = b.textContent.trim();
                    if ((lbl === '닫기' || txt === '닫기') && rect.width <= 30) {
                        b.click();
                        return true;
                    }
                }
                return false;
            """)
            if help_closed:
                print("  도움말 패널 닫음")
                time.sleep(1.5)

            self.driver.save_screenshot("debug_editor.png")
            time.sleep(1)

            # 3. 제목 입력 — 에디터가 깨끗한 상태에서 먼저 입력
            self._inject_title(article["title"])
            time.sleep(0.5)

            # 4. 차트 이미지 먼저 업로드 (빈 body = SE ONE이 첫 번째 블록으로 삽입)
            chart_file = stock.get("chart_file", "")
            if chart_file:
                # 본문 placeholder 클릭으로 SE ONE body 포커스 확보
                try:
                    ph = self.driver.execute_script("""
                        var el = document.querySelector('.se-placeholder');
                        if (el) { var r = el.getBoundingClientRect(); if (r.top >= 0 && r.top < window.innerHeight) return el; }
                        return document.querySelector('.se-section-content');
                    """)
                    if ph:
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", ph)
                        time.sleep(0.2)
                        ActionChains(self.driver).move_to_element(ph).click().perform()
                        time.sleep(0.3)
                        print("  body 포커스 확보 완료 (차트 업로드 준비)")
                except Exception as _fe:
                    print(f"  body 포커스 실패 (무시): {_fe}")

                self._insert_chart_image(chart_file)
                time.sleep(1.5)

                # 차트 삽입 후 문서 끝으로 커서 이동 (본문은 차트 다음에 붙임)
                try:
                    ActionChains(self.driver).key_down(Keys.CONTROL).send_keys(Keys.END).key_up(Keys.CONTROL).perform()
                    time.sleep(0.3)
                    print("  차트 삽입 완료, 커서 최하단으로 이동")
                except Exception:
                    pass

            # 5. 본문 주입 — 차트 이미 있으면 append=True (Ctrl+A 생략, 차트 보존)
            body_ok = self._inject_body_via_paste(content_html, append=bool(chart_file))
            if not body_ok:
                print("  paste 실패, innerHTML fallback 시도")
                self._inject_body_via_js_html(content_html)
            time.sleep(2)

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
