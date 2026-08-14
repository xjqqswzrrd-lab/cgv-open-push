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
