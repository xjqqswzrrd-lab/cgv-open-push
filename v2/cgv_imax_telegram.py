import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

CGV_CO_CD = "A420"
CGV_SITE_DATES_API = "https://cgv.co.kr/api/v1/booking/searchSiteScnscYmdListBySite"
CGV_IMAX_EXISTS_API = "https://cgv.co.kr/api/v1/booking/searchSscnsSchdExistList"
CGV_BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/cinema"
TARGETS = {
    "광교 IMAX": "0257",
    "용산아이파크몰 IMAX": "0013",
}
POLL_SECONDS = max(60, int(os.getenv("POLL_SECONDS", "300")))
STATE_PATH = Path(os.getenv("STATE_PATH", "state.json"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("cgv-imax-telegram")

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://cgv.co.kr/cnm/movieBook/cinema",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
}


def load_state() -> dict[str, list[str]]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("상태 파일을 읽을 수 없어 새로 시작합니다: %s", exc)
        return {}


def save_state(state: dict[str, list[str]]) -> None:
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_PATH)


def get_json(session: requests.Session, url: str, params: dict[str, str]) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=20)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    if data.get("statusCode") not in (0, "0"):
        raise RuntimeError(data.get("statusMessage", "CGV API 오류"))
    return data


def fetch_imax_dates(session: requests.Session, site_no: str) -> list[str]:
    date_data = get_json(session, CGV_SITE_DATES_API, {"coCd": CGV_CO_CD, "siteNo": site_no})
    candidates = sorted({
        str(item["scnYmd"])
        for item in (date_data.get("data") or [])
        if item.get("scnYmd")
    })
    result: list[str] = []
    for scn_ymd in candidates:
        exists_data = get_json(
            session,
            CGV_IMAX_EXISTS_API,
            {"coCd": CGV_CO_CD, "siteNo": site_no, "scnYmd": scn_ymd},
        )
        if any(
            item.get("comCdvalNm") == "아이맥스"
            and int(item.get("schdCnt", 0) or 0) > 0
            for item in (exists_data.get("data") or [])
        ):
            result.append(scn_ymd)
    return result


def pretty_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y년 %m월 %d일")
    except ValueError:
        return value


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram 환경변수가 없어 알림을 건너뜁니다.")
        return
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram API 오류"))


def check_once(session: requests.Session, state: dict[str, list[str]], initialize: bool) -> tuple[dict[str, list[str]], list[str]]:
    next_state = dict(state)
    messages: list[str] = []
    for label, site_no in TARGETS.items():
        try:
            current = fetch_imax_dates(session, site_no)
            previous = set(state.get(site_no, []))
            if initialize or site_no not in state:
                next_state[site_no] = current
                log.info("%s 기준값 저장: %s", label, ", ".join(map(pretty_date, current)) or "없음")
                continue
            added = sorted(set(current) - previous)
            next_state[site_no] = current
            if added:
                dates = ", ".join(map(pretty_date, added))
                messages.append(
                    f"[CGV IMAX 예매 오픈]\n{label}\n새 날짜: {dates}\n{CGV_BOOKING_URL}"
                )
                log.info("%s 신규 날짜 감지: %s", label, dates)
            else:
                log.info("%s 변경 없음", label)
        except Exception:
            log.exception("%s 조회 실패", label)
    return next_state, messages


def main() -> None:
    log.info("광교·용산 IMAX 알리미 시작: %ss 주기", POLL_SECONDS)
    session = requests.Session()
    session.headers.update(HEADERS)
    state = load_state()
    state, _ = check_once(session, state, initialize=not bool(state))
    save_state(state)
    while True:
        time.sleep(POLL_SECONDS)
        state, messages = check_once(session, state, initialize=False)
        save_state(state)
        for message in messages:
            try:
                send_telegram(message)
            except Exception:
                log.exception("Telegram 전송 실패")


if __name__ == "__main__":
    main()
