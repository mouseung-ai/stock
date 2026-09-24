# 금리판 — 금리·환율·섹터 모니터 (아이폰용)

미국 10년·국고채 10년을 중심으로 환율, 미장·국장 섹터(기술·반도체·은행·모기지/리츠), 뉴스, 전망을 한 화면에서 보는 개인용 웹앱입니다.
서버 없이 **GitHub Actions(무료)**가 매시간 데이터를 모아 분석하고, **GitHub Pages**가 화면을 띄웁니다. 아이폰에서는 Safari로 열어 홈 화면에 추가하면 앱처럼 씁니다.

```
GitHub Actions (매시간, 하루 2번은 뉴스·전망까지)
  └ src/main.py → FRED·ECOS·Yahoo 수집 → 상관·베타·분해 계산 → 뉴스 수집 → Claude 요약·전망 → 채점
      └ docs/data.json 저장(커밋)
GitHub Pages (docs/) → 아이폰 Safari → 홈 화면 앱
텔레그램 봇 → 급변·디커플링 알림
```

## 설치 (약 20분)

**1. 저장소 만들기**
- GitHub에서 새 저장소를 **Public**으로 만듭니다(무료 Pages는 공개 저장소만 가능. 올라가는 건 시세·뉴스 제목뿐이고 API 키는 비공개 Secrets에 들어갑니다).
- 이 폴더 전체를 올립니다. 웹 업로드는 `.github` 같은 숨김 폴더가 빠질 수 있으니, 올린 뒤 `.github/workflows/update.yml`이 있는지 꼭 확인하세요. 없으면 `Add file → Create new file`에서 경로를 그대로 입력하고 내용을 붙여 넣으면 됩니다.

**2. API 키 (Settings → Secrets and variables → Actions → New repository secret)**

| 이름 | 필요 여부 | 발급 |
|---|---|---|
| `ECOS_API_KEY` | 한국 금리에 필요 | ecos.bok.or.kr 가입 → 인증키 신청(무료) |
| `ANTHROPIC_API_KEY` | 뉴스 요약·전망에 필요 | console.anthropic.com (사용량 과금) |
| `TELEGRAM_BOT_TOKEN` | 알림용(선택) | 텔레그램 @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | 알림용(선택) | 봇에게 아무 메시지 보낸 뒤 `https://api.telegram.org/bot<토큰>/getUpdates`에서 `chat.id` 확인 |

키가 없는 기능은 꺼진 채로 나머지는 동작합니다. 미국 금리(FRED)와 Yahoo 시세는 키가 필요 없습니다.

**3. Pages 켜기**: Settings → Pages → Source: `Deploy from a branch` → Branch `main`, 폴더 `/docs` → Save

**4. 첫 실행**: Actions 탭 → `update` → `Run workflow`(뉴스·전망 체크) → 2~3분 뒤 초록색이면 성공

**5. 아이폰**: Safari로 `https://<아이디>.github.io/<저장소이름>/` 열기 → 공유 버튼 → **홈 화면에 추가**

## 갱신 주기
- 시세·분석: 한국장(09~15시), 미국장(22~05시) 매시간
- 뉴스·전망: 매일 08:00, 16:40 (평일)
- GitHub 예약 실행은 몇 분~수십 분 늦을 수 있습니다. 급할 땐 Actions에서 수동 실행하세요.

## 설정 바꾸기 — `config.yaml` 하나만
- 종목/ETF 추가·교체, 섹터 구성, 커플링 후보, 상관 윈도우(20/120일), 베타 윈도우, 알림 기준, 뉴스 검색어, 일정
- **처음 한 번 꼭 확인할 것**: 한국 종목 코드(`xxxxxx.KS`)와 ECOS 항목 코드(국고채 3년 `010200000`, 10년 `010210000`, 기준금리 `0101000`). 첫 실행 후 앱 상단 "수집 경고"에 뜨는 항목이 있으면 그 코드를 고치면 됩니다.
- 일정(FOMC, 금통위 등)은 무료 자동 수집원이 마땅치 않아 직접 적습니다. 들어 있는 날짜는 예시이니 공식 일정으로 확인하세요.

## 분석 방식 (화면에 나오는 숫자의 뜻)
- **상관**: 금리는 일간 bp 변화, 가격은 일간 로그수익률끼리 계산합니다. 수준끼리 계산하면 추세만 같아도 높게 나오는 허위상관이 생깁니다.
- **커플링/디커플링**: "이전 5개월"(최근 1개월과 겹치지 않는 구간)과 "최근 1개월" 상관을 비교합니다.
  - 역전: 부호가 바뀜
  - 약화: 최근 상관이 평소의 절반 미만
  - 새로 동조: 평소엔 무관했는데 최근 강하게 같이 움직임
- **시차 보정**: 한국 지표는 전날 밤 미국 종가와 짝지어 계산합니다(한국장은 전날 미국장에 반응).
- **금리 베타**: 최근 60거래일 회귀로 "미국 10년 +10bp일 때 이 종목 몇 %". 설명력(R²)이 낮으면 금리보다 다른 요인이 크다는 뜻입니다.
- **10년물 분해**: 명목 = 실질금리(TIPS) + 기대인플레. 어떤 쪽이 금리를 움직였는지에 따라 섹터 영향이 다릅니다.
- **전망 채점**: 모든 전망을 `docs/state/forecast_log.json`에 저장하고, 기간이 끝나면 보합 범위(금리 1주 ±5bp/1달 ±10bp, 환율 ±0.5%/±1%, 주식 ±1%/±3%)로 판정해 적중률을 냅니다.

## 한계 (알고 쓰세요)
- Yahoo 시세는 지연되고, `yfinance`는 비공식 라이브러리라 가끔 막히거나 값이 빠집니다.
- FRED 미국 금리는 하루 늦습니다. 당일 미국 10년은 `^TNX`로 덧붙입니다.
- 국고채는 ECOS 일별 값뿐이라 장중 움직임은 보이지 않습니다.
- 1개월(20거래일) 상관은 표본이 작아 흔들립니다. 디커플링 알림이 하루 뜨고 사라지면 노이즈일 가능성이 큽니다.
- 전망은 참고용입니다. 적중률이 50% 근처에 머물면 방향보다 근거·무효화 조건을 보세요.

## 로컬에서 돌려보기
```bash
pip install -r requirements.txt
export ECOS_API_KEY=...  ANTHROPIC_API_KEY=...
python src/main.py --full
python -m http.server -d docs 8000     # http://localhost:8000
python scripts/make_demo.py && python scripts/build_demo_html.py   # 가짜 데이터로 화면만 확인
```
