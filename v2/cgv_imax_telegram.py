import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from google.cloud import storage
except ImportError:
    storage = None

BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/movie"
MOVIE_NAME = "오디세이"
TARGETS = {"광교": "광교", "용산아이파크몰": "용산아이파크몰"}
SEOUL = ZoneInfo("Asia/Seoul")
STATE_PATH = Path(os.getenv("STATE_PATH", "state.json"))
STATE_BACKEND = os.getenv("STATE_BACKEND", "local").lower()
GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
GCS_BLOB = os.getenv("GCS_BLOB", "cgv-imax/state.json").strip()
RUN_ONCE = os.getenv("RUN_ONCE", "0") == "1"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cgv-ui-monitor")


def load_state() -> dict:
    if STATE_BACKEND == "gcs":
        if storage is None or not GCS_BUCKET:
            raise RuntimeError("GCS 상태 저장 설정이 없습니다.")
        blob = storage.Client().bucket(GCS_BUCKET).blob(GCS_BLOB)
        try:
            value = json.loads(blob.download_as_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception as exc:
            if "404" in str(exc) or "Not Found" in str(exc):
                return {}
            raise
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
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


def pretty_date(value: str) -> str:
    return datetime.strptime(value, "%Y%m%d").strftime("%Y년 %m월 %d일")


def normalize_state(raw: dict) -> dict:
    if isinstance(raw.get("locations"), dict):
        return raw
    return {"locations": {}}


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
    if not response.json().get("ok"):
        raise RuntimeError(response.json().get("description", "Telegram API 오류"))


def visible(locator) -> bool:
    try:
        return locator.is_visible()
    except Exception:
        return False


def select_movie(page) -> None:
    card = page.locator("button").filter(has=page.locator(f'img[alt*="{MOVIE_NAME}"]')).first
    card.wait_for(state="visible", timeout=60000)
    card.click()
    page.wait_for_timeout(1500)
    log.info("영화 선택 완료: %s", MOVIE_NAME)


def open_theater_picker(page) -> None:
    # CGV의 + 컨트롤은 접근성 텍스트가 없고, 고유 editBtn 클래스와 음성용 문구를 가진다.
    plus = page.locator("button[class*='cnms01510_editBtn']").last
    plus.wait_for(state="visible", timeout=30000)
    plus.click()
    page.locator("input#search1").wait_for(state="visible", timeout=30000)


def choose_theater(page, name: str) -> None:
    open_theater_picker(page)
    search = page.locator("input#search1")
    search.fill(name)
    page.wait_for_timeout(700)

    result = page.get_by_role("button", name=name, exact=True)
    if result.count() == 0:
        raise RuntimeError(f"극장 검색 결과 없음: {name}")
    result.last.click()
    page.wait_for_timeout(800)

    # 어떤 UI 변형에서는 결과 선택 뒤 하단 확인 버튼을 한 번 더 눌러야 한다.
    confirm = page.get_by_role("button", name="극장선택", exact=True)
    if confirm.count() and visible(confirm.last):
        confirm.last.click()
        page.wait_for_timeout(1000)

    if visible(page.locator("input#search1")):
        raise RuntimeError(f"극장 선택 모달이 닫히지 않음: {name}")
    if page.get_by_text(name, exact=True).count() == 0:
        raise RuntimeError(f"선택된 극장명이 화면에 없음: {name}")
    log.info("극장 선택 완료: %s", name)


def parse_date_text(raw: str, previous: date | None) -> date | None:
    raw = " ".join(raw.split())
    full = re.search(r"(20\d{2})\s*[./년-]\s*(\d{1,2})\s*[./월-]\s*(\d{1,2})", raw)
    if full:
        try:
            return date(int(full.group(1)), int(full.group(2)), int(full.group(3)))
        except ValueError:
            return None
    day_match = re.search(r"(?:^|\s)(\d{1,2})(?:\s|$)", raw)
    if not day_match:
        return None
    today = datetime.now(SEOUL).date()
    day = int(day_match.group(1))
    year, month = today.year, today.month
    candidate = date(year, month, day)
    if candidate < today - timedelta(days=3):
        candidate = date(year + 1, 1, day) if month == 12 else date(year, month + 1, day)
    if previous and candidate < previous:
        candidate = date(previous.year + 1, 1, day) if previous.month == 12 else date(previous.year, previous.month + 1, day)
    return candidate


def read_rightmost_visible_date(page) -> tuple[str, list[str]]:
    # dayScroll_black은 고정 헤더용 복제 영역이므로 제외한다.
    container = page.locator("div[class*='dayScroll_container']:not([class*='dayScroll_black'])").first
    container.wait_for(state="visible", timeout=60000)

    script = """
    container => {
      const cr = container.getBoundingClientRect();
      return [...container.querySelectorAll("button")].map((b, i) => {
        const r = b.getBoundingClientRect();
        const s = getComputedStyle(b);
        const shown = r.width > 0 && r.height > 0 && s.display !== 'none' &&
          s.visibility !== 'hidden' && Number(s.opacity || 1) > 0 &&
          r.right > cr.left && r.left < cr.right && r.bottom > cr.top && r.top < cr.bottom;
        return {i, text: b.innerText.trim(), date: b.getAttribute('data-date'), aria: b.getAttribute('aria-label'), right: r.right, shown};
      }).filter(x => x.shown);
    }
    """
    first = container.evaluate(script)
    page.wait_for_timeout(500)
    second = container.evaluate(script)
    if not second or [(x["text"], round(x["right"])) for x in first] != [(x["text"], round(x["right"])) for x in second]:
        page.wait_for_timeout(800)
        second = container.evaluate(script)
    if not second:
        raise RuntimeError("현재 화면에 표시된 날짜 버튼이 없습니다.")

    parsed = []
    previous = None
    for item in second:
        value = item.get("date") or item.get("aria") or item.get("text", "")
        parsed_date = parse_date_text(value, previous)
        if parsed_date:
            parsed.append((float(item["right"]), parsed_date))
            previous = parsed_date
    if not parsed:
        raise RuntimeError(f"날짜 버튼 해석 실패: {second}")
    parsed.sort(key=lambda x: x[0])
    labels = [d.strftime("%Y%m%d") for _, d in parsed]
    return labels[-1], labels


def collect_ui_dates() -> dict[str, dict[str, list[str] | str]]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
            extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"},
            viewport={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        try:
            page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            select_movie(page)  # 실행당 한 번만 선택한다.
            results = {}
            for name in TARGETS:
                choose_theater(page, name)
                last, dates = read_rightmost_visible_date(page)
                results[name] = {"last_visible_date": last, "visible_dates": dates}
                log.info("%s 실제 UI 오른쪽 끝 날짜: %s", name, pretty_date(last))
            return results
        except PlaywrightTimeoutError as exc:
            title = page.title()
            body = page.locator("body").inner_text(timeout=5000)[:500].replace("\n", " ")
            raise RuntimeError(f"CGV UI 대기 시간 초과: title={title!r}, body={body!r}") from exc
        finally:
            context.close()
            browser.close()


def process(results: dict, state: dict) -> list[str]:
    locations = state.setdefault("locations", {})
    alerts = []
    for name, current in results.items():
        old = locations.get(name, {}).get("last_visible_date")
        new = current["last_visible_date"]
        if old and new > old:
            added = [d for d in current["visible_dates"] if d > old]
            alerts.append(f"[CGV 예매 날짜 오픈]\n{name} {MOVIE_NAME}\n새 공개 날짜: {', '.join(pretty_date(d) for d in added)}\n{BOOKING_URL}")
            log.info("%s 신규 UI 날짜: %s", name, ", ".join(pretty_date(d) for d in added))
        elif old:
            log.info("%s 날짜 변경 없음: %s", name, pretty_date(new))
        else:
            log.info("%s UI 기준값 저장: %s", name, pretty_date(new))
        locations[name] = current
    return alerts


def main() -> None:
    log.info("광교·용산 CGV UI 날짜 알리미 시작: run_once=%s", RUN_ONCE)
    state = normalize_state(load_state())
    try:
        results = collect_ui_dates()
    except Exception:
        log.exception("UI 감지 실패: 기존 기준값을 유지합니다.")
        return
    alerts = process(results, state)
    save_state(state)
    for alert in alerts:
        send_telegram(alert)


if __name__ == "__main__":
    main()
