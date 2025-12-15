"""HTTP 302 테스트 스크립트"""
import aiohttp
import asyncio

async def test():
    url = 'https://m.booking.naver.com/booking/13/bizes/1269828/items/6308953'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://m.booking.naver.com/',
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            print(f'Status: {resp.status}')
            print(f'Location: {resp.headers.get("Location", "N/A")}')
            print(f'Content-Type: {resp.headers.get("Content-Type", "N/A")}')

            # 페이지 내용 확인
            content = await resp.text()
            print(f'\nContent length: {len(content)} bytes')

            # 비활성화 관련 키워드 검색
            keywords = ['redirect', 'error', '비활성', '운영중지', '예약불가', 'closed', 'disabled']
            for kw in keywords:
                if kw.lower() in content.lower():
                    print(f'Found keyword: {kw}')

            # 처음 500자 출력
            print(f'\nFirst 500 chars:\n{content[:500]}')

if __name__ == '__main__':
    asyncio.run(test())
