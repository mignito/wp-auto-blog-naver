# 네이버 블로그 자동 포스팅 - 설정 가이드

## ⚠️ 중요 사항
- 네이버 블로그는 **공식 포스팅 API가 없습니다**
- Selenium(크롬 자동화)으로 동작합니다
- 과도한 자동화 시 계정 제재 위험 → **하루 1~2회 이내** 사용 권장
- **임시저장(draft)** 으로 시작 → 검토 후 직접 발행 권장

---

## 1. 필수 설치

```bash
cd "c:\Users\migni\OneDrive\바탕 화면\워드프레스\wp-auto-naver"
pip install -r requirements.txt
```

> Chrome 브라우저가 설치되어 있어야 합니다.
> ChromeDriver는 `undetected-chromedriver`가 자동 설치합니다.

---

## 2. .env 파일 설정

`.env.example`을 `.env`로 복사 후 수정:

```
ANTHROPIC_API_KEY=sk-ant-xxxx       ← Claude AI 키
NAVER_BLOG_ID=your_blog_id          ← 네이버 블로그 ID
NAVER_USERNAME=your_naver_id        ← 네이버 로그인 ID
NAVER_PASSWORD=your_password        ← 네이버 비밀번호

NAVER_CLIENT_ID=xxxx                ← 네이버 Open API (선택)
NAVER_CLIENT_SECRET=xxxx

PEXELS_API_KEY=xxxx                 ← 이미지 API (선택)

POST_STATUS=draft                   ← draft=임시저장 / publish=발행
HEADLESS=false                      ← 처음엔 반드시 false
```

---

## 3. 첫 로그인 (쿠키 저장)

**처음 한 번만** 직접 로그인해서 쿠키를 저장해야 합니다.

```bash
# HEADLESS=false 상태에서 실행
python main.py --login
```

1. 크롬이 열리며 네이버 로그인 페이지로 이동
2. **직접 로그인** (2단계 인증 포함)
3. 콘솔에서 Enter 입력
4. 쿠키가 `cookies/naver_cookies.json`에 저장됨

> 쿠키는 약 30일간 유효. 만료 시 다시 `--login` 실행.

---

## 4. 실행 방법

```bash
# 기본 실행 (트렌드 키워드 자동 탐색)
python main.py

# 미리보기만 (발행 안 함)
python main.py --dry

# 키워드 직접 지정
python main.py --keyword "ISA 계좌 절세 방법" --category 금융

# 로그인 테스트
python main.py --login
```

---

## 5. 설정 값 설명

| 항목 | 설명 |
|------|------|
| `POST_STATUS=draft` | 임시저장 (안전, 권장) |
| `POST_STATUS=publish` | 즉시 발행 |
| `HEADLESS=false` | 크롬 창 보이며 실행 (디버깅용) |
| `HEADLESS=true` | 백그라운드 실행 (쿠키 저장 후 사용) |

---

## 6. 네이버 Open API 발급 (선택사항)

트렌드 키워드 탐색 정확도를 높이려면:

1. https://developers.naver.com 접속
2. 애플리케이션 등록
3. "검색트렌드(DataLab)" API 체크
4. Client ID / Secret을 `.env`에 입력

---

## 7. 문제 해결

| 증상 | 해결 |
|------|------|
| 로그인 실패 | `HEADLESS=false` 후 `--login` 재실행 |
| 에디터 인식 못 함 | `HEADLESS=false`로 직접 확인 |
| 쿠키 만료 | `python main.py --login` 재실행 |
| ChromeDriver 오류 | Chrome 브라우저 최신 버전 업데이트 |
| 캡차/2차 인증 | 수동 로그인 후 쿠키 저장 |

---

## 8. 권장 사용 패턴

```
월~금 하루 1회:
  1. python main.py --dry   (미리보기 확인)
  2. python main.py          (임시저장 발행)
  3. 네이버 블로그에서 검토 후 직접 발행 클릭
```
