"""
Google 검색 CSS 선택자 및 상수 정의
"""

# CSS 선택자
SELECTORS = {
    "search_area": "#rso",
    "titles": "#rso h3",
    "result_block": "[jscontroller]",
    "cite": "cite",
    "snippet": "[data-sncf]",
    "next_button": "#pnnext",
    "prev_button": "#pnprev",
    "captcha": "div#recaptcha, iframe[title*='reCAPTCHA']",
}

# 날짜 필터 매핑 (사용자 친화적 값 -> Google tbs 파라미터)
DATE_FILTERS = {
    "1h": "qdr:h",   # 최근 1시간
    "24h": "qdr:d",  # 최근 24시간
    "1w": "qdr:w",   # 최근 1주일
    "1m": "qdr:m",   # 최근 1개월
    "1y": "qdr:y",   # 최근 1년
}

# 날짜 필터 레이블 (UI 표시용)
DATE_FILTER_LABELS = {
    "1h": "최근 1시간",
    "24h": "최근 24시간",
    "1w": "최근 1주일",
    "1m": "최근 1개월",
    "1y": "최근 1년",
}

# 언어 옵션 (Google lr 파라미터)
LANGUAGE_OPTIONS = {
    "lang_ko": "한국어",
    "lang_en": "영어",
    "lang_ja": "일본어",
    "lang_zh-CN": "중국어 간체",
}

# 국가 옵션 (Google cr 파라미터)
COUNTRY_OPTIONS = {
    "countryKR": "한국",
    "countryUS": "미국",
    "countryJP": "일본",
    "countryCN": "중국",
}

# 페이지당 결과 수 옵션 (Google num 파라미터)
NUM_OPTIONS = {
    10: "10개",
    20: "20개",
    50: "50개",
}

# 추가 검색 파라미터 허용 키 목록
ALLOWED_SEARCH_PARAMS = {"lr", "cr", "as_sitesearch", "num"}

# 검색 결과 파싱용 JavaScript 코드
SCRAPE_RESULTS_JS = """
() => {
    const data = [];
    const h3Elements = document.querySelectorAll('#rso h3');

    h3Elements.forEach((h3, index) => {
        try {
            const link = h3.closest('a');
            if (!link) return;

            const result = {
                rank: index + 1,
                title: h3.innerText.trim(),
                url: link.href,
                display_url: '',
                snippet: '',
                publish_date: null
            };

            const resultBlock = h3.closest('[jscontroller]');

            if (resultBlock) {
                const cite = resultBlock.querySelector('cite');
                if (cite) {
                    result.display_url = cite.innerText.trim();
                }

                const snippetDiv = resultBlock.querySelector('[data-sncf]');
                if (snippetDiv) {
                    result.snippet = snippetDiv.innerText.trim();
                }

                // 날짜 추출
                const allSpans = resultBlock.querySelectorAll('span');
                for (const span of allSpans) {
                    const text = span.innerText;
                    if (text && (text.match(/\\d{4}\\.\\s*\\d{1,2}\\.\\s*\\d{1,2}/) ||
                                text.match(/\\d+\\s*(시간|일|주|개월|년)\\s*전/))) {
                        result.publish_date = text.trim();
                        break;
                    }
                }
            }

            data.push(result);
        } catch (error) {
            console.log(`Error at index ${index}:`, error.message);
        }
    });

    return data;
}
"""
