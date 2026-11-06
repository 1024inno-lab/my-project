# 투자 데스크 (invest-desk)

주식·채권·IRP 보유 현황을 한 화면에서 관리하는 개인용 서비스입니다.
- 실시간 시세를 반영합니다 (한국투자증권 Open API).
- 매일 아침 AI 에이전트가 **종합 포트폴리오 전략**과 **보유 주식 대응 전략**을 만들어 메일로 보냅니다.
- 판단의 근거가 되는 요인별 가중치는 매일 복기 결과로 **백엔드에서 자동 조정**됩니다. 화면에는 나오지 않습니다.

```
[브라우저] ──로그인(Cognito)──▶ CloudFront + S3 (웹페이지)
     │
     └─ API 호출(JWT) ──▶ API Gateway ──▶ Lambda(api) ──▶ DynamoDB
                                              │           ├─ KIS Open API (시세·검색·일봉·수급)
                                              │           └─ 공공데이터포털 (채권 발행정보)
EventBridge Scheduler (서울 시간)
  ├─ 평일 07:00 ▶ Lambda(review)       전일 판단 vs 실제 결과 복기 → 요인 가중치 조정
  └─ 평일 07:30 ▶ Lambda(daily_agent)  요인 채점 → Claude API(웹 검색) → 전략 저장 → SES 메일
```

| 폴더 | 내용 |
|---|---|
| `frontend/` | 웹페이지 (빌드 없는 순수 HTML/JS) — 대시보드, 주식 대응 전략, 보유 종목 추가·수정 |
| `backend/src/` | Lambda 코드 — `api.py`, `daily_agent.py`, `review.py`, `common/` |
| `backend/tests/` | 단위 테스트 (판단 모델·가중치 학습·평균단가·채권 이자일 등) |
| `template.yaml` | AWS 인프라 전체 (SAM) |
| `infra/bootstrap.yaml` | GitHub → AWS 배포 권한 (최초 1회) |
| `.github/workflows/` | `ci.yml` (PR 테스트), `deploy.yml` (main 푸시 시 자동 배포) |

---

## 처음 한 번만 하는 셋업

### 1단계. AWS 계정 만들기 (약 15분)

1. https://aws.amazon.com 에서 **AWS 계정 생성**
   - 이메일, 카드 등록, 전화 인증을 거칩니다.
   - 지원 플랜은 *기본(무료)* 을 선택합니다.
2. 로그인 후 오른쪽 위 계정명 → **보안 자격 증명** → **MFA 할당**
   - 휴대폰 OTP 앱(Google Authenticator 등)을 등록합니다.
3. 오른쪽 위 리전을 **아시아 태평양(서울) ap-northeast-2** 로 바꿉니다.
4. **결제 및 비용 관리 → 예산 → 예산 생성 → 월별 비용 예산**
   - 금액 예시: 월 $20
   - 알림 메일을 받을 주소를 입력합니다.

> 루트 계정은 이 셋업과 결제 관리에만 씁니다. 배포는 GitHub Actions가 전용 역할로 하므로 액세스 키를 만들 필요가 없습니다.

### 2단계. 배포 권한 만들기 (약 5분)

1. AWS 콘솔 → **CloudFormation** → **스택 생성 → 새 리소스 사용(표준)**
2. **템플릿 파일 업로드**에서 이 저장소의 `infra/bootstrap.yaml`을 선택합니다.
3. 아래처럼 입력합니다.
   - 스택 이름: `invest-desk-bootstrap`
   - `GitHubOwner`: `1024inno-lab` (기본값으로 채워져 있음)
   - `GitHubRepo`: `my-project` (기본값으로 채워져 있음)
   - `AppStackName`: `invest-desk` (그대로)
   - `CreateOidcProvider`: `true` (그대로)
4. 마지막 화면에서 "IAM 리소스를 생성할 수 있음을 승인"에 체크하고 **제출**합니다.
5. 완료되면 **출력** 탭의 `DeployRoleArn` 값을 복사합니다.

### 3단계. GitHub 저장소 설정 (약 2분)

저장소 → **Settings → Secrets and variables → Actions → Variables** 탭 → **New repository variable**

| 이름 | 값 |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | 2단계에서 복사한 ARN |
| `OWNER_EMAIL` | 로그인 및 전략 메일을 받을 이메일 |
| `CLAUDE_MODEL` | (선택) 기본값 `claude-sonnet-5-5` 외 모델을 쓸 때만 |

배포는 자동으로 일어나지 않습니다. 작업을 마쳤을 때 **Actions → Deploy → Run workflow** 로 직접 실행하며, 10~15분 정도 걸립니다(CloudFront 생성 시간 포함).

### 4단계. 배포 직후 할 일

1. **메일 2통 확인**
   - **Amazon SES 확인 메일**: 링크를 눌러야 데일리 전략 메일이 발송됩니다.
   - **임시 비밀번호 메일 (Cognito)**: 첫 로그인 때 새 비밀번호를 설정합니다.
2. **API 키 입력** — 둘 중 편한 방법
   - **GitHub에서 (권장)**: 저장소 Settings → Secrets and variables → Actions → *Repository secrets*에 아래 이름 그대로 추가한 뒤 Deploy를 실행하면 배포 중에 AWS로 자동 입력됩니다(넣은 키만 갱신).
   - **AWS 콘솔에서**: 시드니 리전 **Secrets Manager** → `AppSecret...` → **보안 암호 값 검색 → 편집**에서 `CHANGE_ME`를 실제 값으로 바꿉니다.

| 키 | 발급처 |
|---|---|
| `KIS_APP_KEY`, `KIS_APP_SECRET` | 한국투자증권 계좌 개설 → [KIS Developers](https://apiportal.koreainvestment.com) → Open API 신청 (실전투자) |
| `ANTHROPIC_API_KEY` | [Claude Console](https://console.anthropic.com) → API Keys |
| `DATA_GO_KR_KEY` | [공공데이터포털](https://www.data.go.kr)에서 "금융위원회_채권기본정보" 활용신청 → 일반 인증키(Encoding) |

3. **접속**
   - Actions 실행 결과 요약에 나온 접속 주소(`https://xxxx.cloudfront.net`)로 들어가 로그인합니다.
   - **보유 종목 추가**에서 주식·채권·IRP를 등록합니다.
4. **(선택) 전략을 바로 받아 보기**
   - Lambda 콘솔에서 `invest-desk-DailyAgentFunction...` 함수를 엽니다.
   - **테스트** 탭에서 이벤트 `{"force": true}`로 실행합니다.

---

## 평소 개발 흐름 (형상관리)

```bash
git clone https://github.com/1024inno-lab/my-project.git && cd my-project
git switch -c feature/화면-수정        # 작업 브랜치
# ... 수정 ...
cd backend && pytest -q && cd ..       # 테스트
git commit -am "대시보드 IRP 표 정렬 수정"
git push -u origin feature/화면-수정   # → PR 생성 시 CI 자동 실행
# main에 머지해도 배포는 되지 않음 → 작업이 끝나면 Actions → Deploy → Run workflow
```

권장 설정: 저장소 **Settings → Branches → Add rule** (`main`)
- *Require a pull request before merging*
- *Require status checks to pass* (CI의 `test` 선택)

### 로컬에서 화면만 확인

```bash
cp frontend/config.example.js frontend/config.js   # demo: true 로 바꾸면 샘플 데이터
cd frontend && python3 -m http.server 8765         # http://localhost:8765
```

실제 API를 붙여 보려면 `config.js`에 배포 출력값(ApiUrl, CognitoDomain, UserPoolClientId)을 넣으세요. `localhost:8765`는 로그인 콜백에 미리 등록되어 있습니다.

---

## 동작 방식 요약

**시세**
- 주식과 IRP 안의 상장 ETF는 KIS REST 시세를 씁니다.
- 장중에는 10초, 장외에는 60초마다 갱신합니다.
- 환율은 하루 1회 기준환율(frankfurter.app)을 씁니다.

**채권**
- ISIN으로 금융위원회 채권기본정보를 조회해 표면금리, 이자지급주기, 발행일, 만기일을 자동으로 채웁니다.
- 다음 이자일은 발행일과 지급 주기로 계산합니다.
- 평가금액은 직접 갱신합니다. 해외채권은 발행 정보를 직접 입력합니다.

**IRP**
- 상장 ETF는 실시간으로 반영됩니다.
- 펀드·TDF는 기준가를 직접 갱신합니다.
- 예금은 금리와 만기로 이자를 자동 계산합니다.
- 납입 기록과 위험자산 비중(한도 70%)을 함께 관리합니다.

**데일리 전략 (07:30)**
1. 정량 요인 계산: 수급(외국인·기관), 차트(20일선·5일선·거래량), 과거 유사 사례
2. Claude가 웹 검색으로 정성 요인을 -2~+2로 채점합니다: 미국장 결과, 리포트, 뉴스·공시, 거시, 이벤트
3. 종합점수 = Σ(점수 × 가중치) ÷ 2. +25 이상은 매수, -25 이하는 비중축소, 그 사이는 관망입니다. 판단은 코드가 결정하고, Claude는 근거와 대응 가격만 작성합니다.
4. 결과를 저장하고 메일로 보냅니다. 화면에는 결과만 나오고, 점수와 가중치는 DB(`JUDGMENT`, `MODEL`)에만 남습니다.

**복기와 가중치 조정 (07:00)**
- 전일 판단과 실제 등락을 비교합니다. 국내 종목은 당일 종가, 미국 종목은 그날 밤 미국장 종가 기준입니다.
- 최근 20거래일 요인별 적중률로 가중치를 천천히 조정합니다.
  - 새 가중치 = 기존 80% + 목표 20%
  - 하루 조정 폭 ±2%p, 가중치 범위 3~30%
  - 표본이 10건 미만인 요인은 조정을 보류합니다.
- KODEX 200이 -3% 이하로 급락한 날은 조정을 쉽니다.

### 비용 감 (개인 1명 기준, 월)
- **AWS**: 대부분 프리 티어 또는 수백~수천 원 수준입니다. Lambda, API Gateway, DynamoDB, S3, CloudFront, Secrets Manager($0.4)가 포함됩니다.
- **Claude API**: 평일 하루 2회 호출에 웹 검색을 포함해 보유 종목 수에 비례합니다. Console에서 사용량 한도를 걸어 두는 것을 권장합니다.

### 알아 두실 점
- 이 서비스의 전략은 자동 생성된 참고 자료입니다. 투자 판단과 책임은 본인에게 있습니다.
- **KIS API**
  - 실전투자 앱키 기준입니다. 토큰은 DynamoDB에 캐시해 하루 1회만 발급합니다.
  - KIS가 TR ID나 응답 필드를 바꾸면 `backend/src/common/kis.py`만 고치면 됩니다.
- **채권 API**: 응답 필드명이 명세와 다를 수 있습니다. 후보 키를 여러 개 두었으니 첫 조회가 비어 있으면 `common/market.py`의 `BOND_FIELDS`를 확인해 주세요.
- **공공데이터 라이선스**: 공공누리 제2유형(상업적 이용 금지)입니다. 개인용으로는 문제없지만 상업 서비스로 확장하려면 예탁결제원과 별도 계약이 필요합니다.

---

## 일시 중지 · 재개 · 완전 삭제

**현재 상태: 일시 중지.** 평일 07:00 복기와 07:30 전략 자동 실행이 꺼져 있습니다. 사이트, 로그인, 보유 종목 데이터, 실시간 시세 조회는 그대로 쓸 수 있습니다.

| 하고 싶은 것 | 방법 |
|---|---|
| 자동 실행 다시 켜기 | 저장소 Settings → Secrets and variables → Actions → **Variables**에 `AGENT_SCHEDULE` = `ENABLED` 추가 → 배포 |
| 다시 일시 중지 | `AGENT_SCHEDULE` 변수를 삭제하거나 `DISABLED`로 바꾼 뒤 → 배포 |
| 비용 0으로 완전 삭제 | 아래 순서 (데이터·키 보관함도 지워지며 되돌릴 수 없음) |

**완전 삭제 순서** (AWS 콘솔, 시드니 리전)
1. S3: 스택이 만든 사이트 버킷(`invest-desk-sitebucket-…`)을 열고 **비우기**를 실행합니다. 비어 있지 않으면 스택 삭제가 실패합니다.
2. CloudFormation: `invest-desk` 스택을 **삭제**합니다. CloudFront 삭제 때문에 15분 이상 걸릴 수 있습니다.
3. 삭제 보호를 걸어 둔 두 리소스는 따로 지웁니다.
   - DynamoDB 테이블(`invest-desk-Table-…`): 보유 종목 데이터
   - Secrets Manager `AppSecret-…`: 월 $0.40가 청구되는 항목입니다. 삭제 대기 기간을 7일로 정하면 됩니다.
4. (선택) `aws-sam-cli-managed-default` 스택과 버킷, `invest-desk-bootstrap` 스택도 삭제할 수 있습니다. 배포 권한 스택은 비용이 없습니다.

코드는 GitHub에 그대로 남아 있습니다. 나중에 다시 배포하면 새로 만들어지며, 보유 종목은 다시 입력해야 합니다.
