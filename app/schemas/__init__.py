"""
스키마 모듈
"""
from app.schemas.account import (
    AccountBase,
    AccountCreate,
    AccountUpdate,
    Account,
    AccountWithItems,
    AccountLoginStatus,
)
from app.schemas.business import (
    BusinessBase,
    BusinessCreate,
    BusinessUpdate,
    Business,
    BusinessWithItems,
)
from app.schemas.biz_item import (
    BizItemBase,
    BizItemCreate,
    BizItemUpdate,
    BizItem,
    BizItemWithSchedules,
)
from app.schemas.monitor_schedule import (
    MonitorScheduleBase,
    MonitorScheduleCreate,
    MonitorScheduleUpdate,
    MonitorSchedule,
    ScheduleWithContext,
    BulkScheduleCreate,
)
from app.schemas.proxy import (
    ProxyStatus,
    ProxyProtocol,
    ProxyCheckHistoryBase,
    ProxyCheckHistoryCreate,
    ProxyCheckHistoryResponse,
    ProxyBase,
    ProxyCreate,
    ProxyUpdate,
    ProxyResponse,
    ProxyDetailResponse,
    ProxyCollectionRunBase,
    ProxyCollectionRunCreate,
    ProxyCollectionRunUpdate,
    ProxyCollectionRunResponse,
    ProxyStatsResponse,
    ProxyListParams,
    ProxyListResponse,
    ProxyImportResult,
)
from app.schemas.universal_crawl import (
    CrawledPageBase,
    CrawledPageCreate,
    CrawledPageResponse,
    CrawledPageList,
    UniversalCrawlRequestCreate,
    UniversalCrawlRequestUpdate,
    UniversalCrawlRequestResponse,
    UniversalCrawlRequestList,
    CrawlUrlRequest,
    CrawlUrlResponse,
)

__all__ = [
    # account
    "AccountBase",
    "AccountCreate",
    "AccountUpdate",
    "Account",
    "AccountWithItems",
    "AccountLoginStatus",
    # business
    "BusinessBase",
    "BusinessCreate",
    "BusinessUpdate",
    "Business",
    "BusinessWithItems",
    # biz_item
    "BizItemBase",
    "BizItemCreate",
    "BizItemUpdate",
    "BizItem",
    "BizItemWithSchedules",
    # monitor_schedule
    "MonitorScheduleBase",
    "MonitorScheduleCreate",
    "MonitorScheduleUpdate",
    "MonitorSchedule",
    "ScheduleWithContext",
    "BulkScheduleCreate",
    # proxy
    "ProxyStatus",
    "ProxyProtocol",
    "ProxyCheckHistoryBase",
    "ProxyCheckHistoryCreate",
    "ProxyCheckHistoryResponse",
    "ProxyBase",
    "ProxyCreate",
    "ProxyUpdate",
    "ProxyResponse",
    "ProxyDetailResponse",
    "ProxyCollectionRunBase",
    "ProxyCollectionRunCreate",
    "ProxyCollectionRunUpdate",
    "ProxyCollectionRunResponse",
    "ProxyStatsResponse",
    "ProxyListParams",
    "ProxyListResponse",
    "ProxyImportResult",
    # universal_crawl
    "CrawledPageBase",
    "CrawledPageCreate",
    "CrawledPageResponse",
    "CrawledPageList",
    "UniversalCrawlRequestCreate",
    "UniversalCrawlRequestUpdate",
    "UniversalCrawlRequestResponse",
    "UniversalCrawlRequestList",
    "CrawlUrlRequest",
    "CrawlUrlResponse",
]
