"""비활성화 상품 GraphQL 응답 테스트"""
import asyncio
import sys
sys.path.insert(0, 'D:/work/project/tools/monitor-page')

from app.services.naver_graphql_client import get_naver_graphql_client
import json

async def test():
    client = get_naver_graphql_client()

    # 비활성화 상품
    business_id = '1269828'
    biz_item_id = '6308953'

    print(f'Testing item status: {business_id}/{biz_item_id}')
    print('='*60)

    # 1. 상품 목록 조회 (상태 확인)
    items = await client.fetch_biz_items(business_id)
    print(f'\nTotal items: {len(items)}')

    target_item = None
    for item in items:
        if str(item.biz_item_id) == biz_item_id:
            target_item = item
            break

    if target_item:
        print(f'\nTarget item found:')
        print(f'  name: {target_item.name}')
        print(f'  biz_item_id: {target_item.biz_item_id}')
        print(f'  is_display: {target_item.is_display}')
        print(f'  is_reservation_available: {target_item.is_reservation_available}')
        # 모든 속성 출력
        print(f'\nAll attributes:')
        for attr in dir(target_item):
            if not attr.startswith('_'):
                print(f'  {attr}: {getattr(target_item, attr)}')
    else:
        print(f'Item {biz_item_id} NOT FOUND in items list!')

    await client.close()

if __name__ == '__main__':
    asyncio.run(test())
