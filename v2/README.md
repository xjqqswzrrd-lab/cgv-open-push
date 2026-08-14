# 광교·용산 IMAX Telegram 알리미

기존 `cgv-open-push`의 Discord 알림과 별도로, 광교와 용산아이파크몰 IMAX에서 **새로운 예매 날짜가 추가될 때만** Telegram 알림을 보내는 v2 프로그램입니다.

## 감시 대상

| 지점 | CGV siteNo |
|---|---:|
| 광교 IMAX | 0257 |
| 용산아이파크몰 IMAX | 0013 |

## 동작 원리

프로그램은 CGV 공식 예매 화면이 사용하는 공개 API에서 지점별 예매 가능 날짜를 가져온 뒤, 날짜별 IMAX 상영 회차 존재 여부를 확인합니다. 첫 실행 때 현재 날짜 목록을 `state.json`에 기준값으로 저장하고 알림은 보내지 않습니다. 다음 조회부터 기준값에 없던 날짜가 보이면 Telegram으로 알림을 보냅니다.

## 실행

```powershell
cd v2
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN = "텔레그램_봇_토큰"
$env:TELEGRAM_CHAT_ID = "텔레그램_채팅_ID"
$env:POLL_SECONDS = "300"
python .\cgv_imax_telegram.py
```

`TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`는 코드나 GitHub에 저장하지 마세요. `state.json`을 삭제하면 현재 날짜를 새 기준으로 다시 저장합니다.

## 참고

이 프로그램은 예매 날짜 알림만 수행하며 좌석 선택, 결제, 자동 예매는 수행하지 않습니다. CGV API 또는 웹 화면이 변경되면 수집 모듈을 수정해야 할 수 있습니다.

## Cloud Run 전환 버전

Apps Script에서 CGV HTTP 403이 발생하면 Google Apps Script 대신 `Dockerfile`과 `requirements-cloud-run.txt`를 사용해 Cloud Run Jobs로 배포합니다. 이 버전은 `RUN_ONCE=1`로 한 번 확인하고 종료하며, Cloud Scheduler가 5분마다 다시 실행합니다.

Cloud Run에서는 컨테이너 파일시스템이 실행 사이에 보장되지 않으므로 상태를 Google Cloud Storage에 저장합니다. 먼저 같은 Google Cloud 프로젝트에 버킷을 만들고 Cloud Run 실행 서비스 계정에 해당 버킷의 객체 읽기·쓰기 권한을 부여합니다.

필수 환경변수는 다음과 같습니다.

```text
RUN_ONCE=1
STATE_BACKEND=gcs
GCS_BUCKET=생성한-GCS-버킷명
GCS_BLOB=cgv-imax/state.json
TELEGRAM_BOT_TOKEN=새로_발급한_토큰
TELEGRAM_CHAT_ID=7029690322
```

배포 흐름은 다음과 같습니다.

```bash
gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT_ID/cgv/cgv-imax:v1 .
gcloud run jobs create cgv-imax-alert \
  --image REGION-docker.pkg.dev/PROJECT_ID/cgv/cgv-imax:v1 \
  --region REGION \
  --set-env-vars RUN_ONCE=1,STATE_BACKEND=gcs,GCS_BUCKET=버킷명,GCS_BLOB=cgv-imax/state.json \
  --set-secrets TELEGRAM_BOT_TOKEN=telegram-bot-token:latest \
  --set-env-vars TELEGRAM_CHAT_ID=7029690322

gcloud scheduler jobs create http cgv-imax-every-5-min \
  --location REGION \
  --schedule="*/5 * * * *" \
  --time-zone="Asia/Seoul" \
  --uri="https://run.googleapis.com/v2/projects/PROJECT_ID/locations/REGION/jobs/cgv-imax-alert:run" \
  --http-method=POST \
  --oauth-service-account-email=SERVICE_ACCOUNT_EMAIL
```

실제 배포 전에는 새 Telegram 토큰을 Secret Manager에 저장하고, 토큰을 GitHub나 문서에 직접 기록하지 않습니다. Cloud Run Job 서비스 계정에는 GCS 버킷 객체 읽기·쓰기 권한과 Secret Manager 비밀값 접근 권한이 필요합니다.

Cloud Run Job이 CGV API에서도 403을 받는다면 CGV가 클라우드 데이터센터 요청을 차단하는 것이므로, 단순한 헤더 변경으로 해결되지 않을 수 있습니다. 그 경우에는 브라우저 자동화가 가능한 별도 실행 환경이 필요합니다.
