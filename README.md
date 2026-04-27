완료했습니다. wp-auto-blog-naver에 모두 올라갔습니다.

내일 다른 컴퓨터에서 할 때 순서:


git clone https://github.com/mignito/wp-auto-blog-naver.git
cd wp-auto-blog-naver
pip install -r requirements.txt
.env 파일은 git에 없으니 직접 만들어야 합니다 (.gitignore에 포함):


ANTHROPIC_API_KEY=sk-ant-...
NAVER_BLOG_ID=winone89
NAVER_USERNAME=winone89
NAVER_PASSWORD=dltmdgks89@
NAVER_CLIENT_ID=bjQt1oSwQTQUqw_VeRmQ
NAVER_CLIENT_SECRET=k1_7_ye0yQ
PEXELS_API_KEY=RQhL0edrvb5naDGmm3fdJHA8kH1Kk3BedyEIsBx8hXugYR4tJ6x1Nrni
POST_STATUS=draft
POST_CATEGORY=금융
HEADLESS=false
그다음 python main.py 실행 → Chrome 창에서 네이버 로그인 → 쿠키 저장 → 포스팅 자동 완료.
