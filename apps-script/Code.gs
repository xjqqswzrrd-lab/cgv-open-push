const CGV_CO_CD = 'A420';
const CGV_SITE_DATES_API = 'https://cgv.co.kr/api/v1/booking/searchSiteScnscYmdListBySite';
const CGV_IMAX_EXISTS_API = 'https://cgv.co.kr/api/v1/booking/searchSscnsSchdExistList';
const CGV_BOOKING_URL = 'https://cgv.co.kr/cnm/movieBook/cinema';
const TARGETS = {
  '광교 IMAX': '0257',
  '용산아이파크몰 IMAX': '0013',
};

/**
 * 최초 1회 실행: 트리거를 만들고 기준 날짜를 저장합니다.
 * Telegram 설정 후 이 함수를 실행하면 기존 날짜에는 알림을 보내지 않습니다.
 */
function setup() {
  deleteTriggers_('checkNow');
  ScriptApp.newTrigger('checkNow').timeBased().everyMinutes(5).create();
  initializeBaseline();
  Logger.log('설정 완료: 5분 간격 감시 트리거와 기준 날짜를 생성했습니다.');
}

/** 현재 상태를 기준값으로 저장하고 알림은 보내지 않습니다. */
function initializeBaseline() {
  const state = {};
  Object.keys(TARGETS).forEach(function(label) {
    const siteNo = TARGETS[label];
    state[siteNo] = fetchImaxDates_(siteNo);
    Logger.log('%s 기준값: %s', label, state[siteNo].join(', ') || '없음');
  });
  PropertiesService.getScriptProperties().setProperty('CGV_STATE', JSON.stringify(state));
}

/** 트리거가 5분마다 실행하는 함수입니다. */
function checkNow() {
  const properties = PropertiesService.getScriptProperties();
  const previousState = JSON.parse(properties.getProperty('CGV_STATE') || '{}');
  const nextState = {};
  const messages = [];

  Object.keys(TARGETS).forEach(function(label) {
    const siteNo = TARGETS[label];
    try {
      const currentDates = fetchImaxDates_(siteNo);
      nextState[siteNo] = currentDates;
      if (!Object.prototype.hasOwnProperty.call(previousState, siteNo)) {
        continue;
      }
      const previous = previousState[siteNo] || [];
      const added = currentDates.filter(function(date) {
        return previous.indexOf(date) === -1;
      });
      if (added.length > 0) {
        messages.push(
          '[CGV IMAX 예매 오픈]\n' + label + '\n새 날짜: ' +
          added.map(formatDate_).join(', ') + '\n' + CGV_BOOKING_URL
        );
      }
    } catch (error) {
      console.error(label + ' 조회 실패: ' + error);
    }
  });

  properties.setProperty('CGV_STATE', JSON.stringify(nextState));
  messages.forEach(sendTelegram_);
}

function fetchImaxDates_(siteNo) {
  const datePayload = fetchJson_(CGV_SITE_DATES_API, {
    coCd: CGV_CO_CD,
    siteNo: siteNo,
  });
  const candidates = (datePayload.data || []).map(function(item) {
    return String(item.scnYmd);
  });
  const uniqueCandidates = candidates.filter(function(date, index) {
    return candidates.indexOf(date) === index;
  }).sort();

  return uniqueCandidates.filter(function(scnYmd) {
    const existsPayload = fetchJson_(CGV_IMAX_EXISTS_API, {
      coCd: CGV_CO_CD,
      siteNo: siteNo,
      scnYmd: scnYmd,
    });
    return (existsPayload.data || []).some(function(item) {
      return item.comCdvalNm === '아이맥스' && Number(item.schdCnt || 0) > 0;
    });
  });
}

function fetchJson_(baseUrl, params) {
  const query = Object.keys(params).map(function(key) {
    return encodeURIComponent(key) + '=' + encodeURIComponent(params[key]);
  }).join('&');
  const response = UrlFetchApp.fetch(baseUrl + '?' + query, {
    method: 'get',
    muteHttpExceptions: true,
    headers: {
      Accept: 'application/json',
      'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
      Referer: 'https://cgv.co.kr/cnm/movieBook/cinema',
      'User-Agent': 'Mozilla/5.0 (compatible; CGV-IMAX-Alert/1.0)',
    },
  });
  const status = response.getResponseCode();
  const text = response.getContentText();
  if (status < 200 || status >= 300) {
    throw new Error('CGV HTTP ' + status + ': ' + text.slice(0, 300));
  }
  const payload = JSON.parse(text);
  if (String(payload.statusCode) !== '0') {
    throw new Error(payload.statusMessage || 'CGV API 오류');
  }
  return payload;
}

function sendTelegram_(text) {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('TELEGRAM_BOT_TOKEN');
  const chatId = properties.getProperty('TELEGRAM_CHAT_ID');
  if (!token || !chatId) {
    throw new Error('Script Properties에 TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 설정하세요.');
  }
  const response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    payload: JSON.stringify({
      chat_id: chatId,
      text: text,
      disable_web_page_preview: false,
    }),
  });
  const payload = JSON.parse(response.getContentText());
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300 || !payload.ok) {
    throw new Error('Telegram 오류: ' + response.getContentText().slice(0, 300));
  }
}

function formatDate_(value) {
  if (!/^\d{8}$/.test(value)) return value;
  return value.slice(0, 4) + '년 ' + value.slice(4, 6) + '월 ' + value.slice(6, 8) + '일';
}

function deleteTriggers_(functionName) {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (!functionName || trigger.getHandlerFunction() === functionName) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}
