import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from google.cloud import storage
except ImportError:
    storage = None

TARGETS = {"광교": "0257", "용산아이파크몰": "0013"}
BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/cinema"
SEOUL = ZoneInfo("Asia/Seoul")
STATE_PATH = Path(os.getenv("STATE_PATH", "state.json"))
STATE_BACKEND = os.getenv("STATE_BACKEND", "local").lower()
GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_BLOB = os.getenv("GCS_BLOB", "cgv-imax/state.json").strip()
RUN_ONCE = os.getenv("RUN_ONCE", "0") == "1"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cgv-dom-monitor")


def load_state() -> dict[str, list[str]]:
    if STATE_BACKEND == "gcs":
        if storage is None or not GCS_BUCKET:
            raise RuntimeError("GCS 상태 저장 설정이 없습니다.")
        blob = storage.Client().bucket(GCS_BUCKET).blob(GCS_BLOB)
        try:
            return json.loads(blob.download_as_text(encoding="utf-8"))
        except Exception as exc:
            if "404" in str(exc) or "Not Found" in str(exc):
                return {}
            raise
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict[str, list[str]]) -> None:
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    if STATE_BACKEND == "gcs":
        if storage is None or not GCS_BUCKET:
            raise RuntimeError("GCS 상태 저장 설정이 없습니다.")
        storage.Client().bucket(GCS_BUCKET).blob(GCS_BLOB).upload_from_string(
            payload, content_type="application/json; charset=utf-8"
        )
        return
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(STATE_PATH)


def display_date(value: str) -> str:
    return datetime.strptime(value, "%Y%m%d").strftime("%Y년 %m월 %d일")


def extract_visible_dates(buttons: list[dict]) -> list[str]:
    """날짜 버튼 DOM 순서에서 disabled 버튼을 제외해 실제 활성 날짜만 반환한다."""
    today = datetime.now(SEOUL).date()
    visible: list[str] = []
    for index, button in enumerate(buttons):
        number = str(button.get("number", "")).strip()
        if not number.isdigit() or button.get("disabled"):
            continue
        candidate = today + timedelta(days=index)
        if candidate.day != int(number):
            log.warning("DOM 날짜와 추정 날짜가 다릅니다: DOM=%s 추정=%s", number, candidate)
            continue
        visible.append(candidate.strftime("%Y%m%d"))
    return visible


def fetch_visible_dates(page, label: str, site_no: str) -> list[str]:
    url = f"{BOOKING_URL}?siteNm={quote(label)}&siteNo={site_no}"
    log.info("%s 화면 확인: %s", label, url)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    selector = "button[class*='dayScroll_scrollItem']"
    try:
        page.wait_for_selector(selector, state="attached", timeout=30000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"{label} 날짜 버튼을 찾지 못했습니다.") from exc
    page.wait_for_timeout(1200)
    buttons = page.locator(selector).evaluate_all(
        """els => els.map(el => ({
            number: (el.querySelector('[class*="dayScroll_number"]')?.textContent || '').trim(),
            disabled: el.disabled === true || el.className.includes('dayScroll_disabled')
        }))"""
    )
    dates = extract_visible_dates(buttons)
    if not dates:
        raise RuntimeError(f"{label} 활성 날짜를 찾지 못했습니다: {buttons}")
    log.info("%s 실제 화면 날짜: %s", label, ", ".join(display_date(d) for d in dates))
    return dates


def send_telegram(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram 설정이 없어 전송하지 않습니다.")
        return
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": False},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram API 오류"))


def run_once(state: dict[str, list[str]]) -> tuple[dict[str, list[str]], list[str]]:
    new_state = dict(state)
    alerts: list[str] = []
    initialize = not bool(state)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(locale="ko-KR", timezone_id="Asia/Seoul")
        try:
            for label, site_no in TARGETS.items():
                try:
                    current = fetch_visible_dates(page, label, site_no)
                    previous = set(state.get(site_no, []))
                    added = [] if initialize or site_no not in state else sorted(set(current) - previous)
                    new_state[site_no] = current
                    if initialize or site_no not in state:
                        log.info("%s 기준값 저장", label)
                    elif added:
                        dates = ", ".join(display_date(d) for d in added)
                        alerts.append(f"[CGV 예매 날짜 오픈]\n{label}\n새 공개 날짜: {dates}\n{BOOKING_URL}")
                        log.info("%s 신규 날짜: %s", label, dates)
                    else:
                        log.info("%s 날짜 변경 없음", label)
                except Exception:
                    log.exception("%s 확인 실패", label)
        finally:
            browser.close()
    return new_state, alerts


def main() -> None:
    log.info("광교·용산 CGV 화면 날짜 알리미 시작: run_once=%s", RUN_ONCE)
    state, alerts = run_once(load_state())
    save_state(state)
    for alert in alerts:
        try:
            send_telegram(alert)
        except Exception:
            log.exception("Telegram 알림 전송 실패")


if __name__ == "__main__":
    main()
