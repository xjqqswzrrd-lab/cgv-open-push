# Google Apps Script 버전

Windows PC 없이 Google 서버에서 광교와 용산아이파크몰 IMAX의 신규 예매 날짜를 확인하고 Telegram으로 알립니다.

## 1. Apps Script 프로젝트 만들기

1. [script.google.com](https://script.google.com/)에서 새 프로젝트를 만듭니다.
2. 기본 `Code.gs` 내용을 삭제하고 이 디렉터리의 `Code.gs`를 붙여 넣습니다.
3. 저장합니다.

## 2. Telegram 값 저장하기

Apps Script 편집기에서 왼쪽의 **프로젝트 설정**을 열고 **스크립트 속성**에 다음 두 값을 추가합니다.

| 속성 | 값 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather에서 발급한 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 알림을 받을 개인 채팅 또는 그룹 ID |

토큰은 코드에 직접 넣거나 GitHub에 저장하지 않습니다.

## 3. 최초 실행

함수 목록에서 `setup`을 선택하고 실행합니다. 처음 실행할 때 Google 권한 승인 화면이 나타나면 본인 계정으로 승인합니다. `setup`은 5분 간격 트리거를 만들고, 당시 보이는 IMAX 날짜를 기준값으로 저장합니다. 따라서 최초 실행 시 기존 날짜에 대한 알림은 보내지 않습니다.

이후 `checkNow`가 5분마다 실행되며, 이전 기준값에 없던 IMAX 날짜가 발견될 때만 Telegram으로 알립니다. 상태는 `PropertiesService`에 저장됩니다.

## 4. 수동 테스트

Telegram 속성을 저장한 뒤 함수 목록에서 `checkNow`를 직접 실행할 수 있습니다. 단, `setup`을 먼저 실행해야 최초 기준값이 저장됩니다. 새 날짜가 없으면 메시지가 전송되지 않는 것이 정상입니다.

## 5. 트리거 확인·중지

왼쪽의 시계 아이콘인 **트리거** 메뉴에서 `checkNow` 트리거를 확인할 수 있습니다. 중지하려면 해당 트리거를 삭제하면 됩니다.

## 주의사항

CGV API가 Google 서버의 자동화 요청을 차단하는 경우 Apps Script 실행 기록에 HTTP 오류가 남을 수 있습니다. 이 경우 현재 Python 코드를 Cloud Run Jobs로 배포하는 방식으로 전환하는 것이 적합합니다.
