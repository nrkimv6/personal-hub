# 모니터링할 URL 목록과 각기 다른 프로파일 경로 설정
urls = [
    # {"url": "https://booking.naver.com/booking/13/bizes/1184162/items/5992713?startDate=2024-07-06",
    #  "tag": "어퓨_0706"},
    # {"url": "https://booking.naver.com/booking/13/bizes/1184162/items/5992713?startDate=2024-07-07", "tag": "어퓨_0707"},
    # {"url": "https://booking.naver.com/booking/13/bizes/1184162/items/5992713?startDate=2024-07-13", "tag": "어퓨_0713"},
    # {"url": "https://booking.naver.com/booking/13/bizes/1184162/items/5992713?startDate=2024-07-14", "tag": "어퓨_0714"},
    # {"url": "https://booking.naver.com/booking/13/bizes/1184162/items/5992713?startDate=2024-07-12", "tag": "어퓨_0712"},
    # {
    #     "url": "https://booking.naver.com/booking/6/bizes/1176343/items/5950967?startDateTime=2024-07-06T20%3A00%3A00%2B09%3A00",
    #     "tag": "달달_0706"},
    # {
    #     "url": "https://booking.naver.com/booking/6/bizes/1176343/items/5950967?startDateTime=2024-07-07T20%3A00%3A00%2B09%3A00",
    #     "tag": "달달_0707"
    # },
    # {
    #     "url": "https://booking.naver.com/booking/6/bizes/1176343/items/5950967?startDateTime=2024-07-13T20%3A00%3A00%2B09%3A00",
    #     "tag": "달달_0713"
    # },
    # {
    #     "url": "https://booking.naver.com/booking/6/bizes/1176343/items/5950967?startDateTime=2024-07-14T20%3A00%3A00%2B09%3A00",
    #     "tag": "달달_0714"
    # }, {
    #     "url": "https://booking.naver.com/booking/12/bizes/1185810/items/5992021?startDateTime=2024-07-13T20%3A00%3A00%2B09%3A00",
    #     "tag": "시크릿데이_0713"
    # },
    # {
    #     "url": "https://booking.naver.com/booking/12/bizes/1185810/items/5992021?startDateTime=2024-07-14T20%3A00%3A00%2B09%3A00",
    #     "tag": "시크릿데이_0714"
    # },
    # {
    #     "url": "https://booking.naver.com/booking/13/bizes/1222026/items/6134915?area=pll&startDate=2024-09-14T20%3A00%3A00%2B09%3A00",
    #     # "url": "https://m.booking.naver.com/booking/13/bizes/1222026/items/6134915?area=pll&startDate=2024-09-14&theme=place",
    #     "tag": "퓨_0914"
    # },
    # {
    #         "url": "https://booking.naver.com/booking/12/bizes/1227982/items/6151703?startDateTime=2024-10-04T20%3A00%3A00%2B09%3A00",
    #         "tag": "강진_1004"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/12/bizes/142806/items/4569360?startDateTime=2024-07-07T20%3A00%3A00%2B09%3A00",
    #         "tag": "전통주갤러리_0707"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/12/bizes/142806/items/4569360?startDateTime=2024-07-13T20%3A00%3A00%2B09%3A00",
    #         "tag": "전통주갤러리_0713"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/12/bizes/142806/items/4569360?startDateTime=2024-07-14T20%3A00%3A00%2B09%3A00",
    #         "tag": "전통주갤러리_0714"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/12/bizes/1232927/items/6170380?startDate=2024-09-27T20%3A00%3A00%2B09%3A00",
    #         "tag": "무등창고"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/12/bizes/1228808/items/6155041?startDate=2024-09-27T20%3A00%3A00%2B09%3A00",
    #         "tag": "아이소이 장수진"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/13/bizes/1237664/items/6186982??startDate=2024-09-27T20%3A00%3A00%2B09%3A00",
    #         "tag": "아이오페 레티놀"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/12/bizes/1204324/items/6198978?startDateTime=2024-10-13T20%3A00%3A00%2B09%3A00",
    #         "tag": "펍지_치맥1013"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/5/bizes/1240483/items/6202961?startDateTime=2024-10-09T20%3A00%3A00%2B09%3A00",
    #         "tag": "미미달_1009"
    #     },
    # {
    #         "url": "https://booking.naver.com/booking/5/bizes/1240483/items/6202961?startDateTime=2024-10-13T20%3A00%3A00%2B09%3A00",
    #         "tag": "미미달_1013"
    #     }
    # {
    #         "url": "https://booking.naver.com/booking/6/bizes/1239631/items/6194317?startDateTime=2024-10-12T20%3A00%3A00%2B09%3A00",
    #         "tag": "롯데리아_1_1012"
    #     },{
    #         "url": "https://booking.naver.com/booking/6/bizes/1239631/items/6194341?startDateTime=2024-10-12T20%3A00%3A00%2B09%3A00",
    #         "tag": "롯데리아_2_1012"
    #     },
    # {
        #     "url": "https://booking.naver.com/booking/6/bizes/1239631/items/6194317?startDateTime=2024-10-19T20%3A00%3A00%2B09%3A00",
        #     "tag": "롯데리아_1_1019"
        # },{
        #     "url": "https://booking.naver.com/booking/6/bizes/1239631/items/6194341?startDateTime=2024-10-19T20%3A00%3A00%2B09%3A00",
        #     "tag": "롯데리아_2_1019"
        # },{
        #     "url": "https://booking.naver.com/booking/12/bizes/1243139/items/6207807?startDateTime=2024-10-19T20%3A00%3A00%2B09%3A00",
        #     "tag": "에이지투웨니스_1019"
        # },
        # {
        #     "url": "https://booking.naver.com/booking/12/bizes/1272478/items/6312190?startDateTime=2024-11-30T20%3A00%3A00%2B09%3A00",
        #     "tag": "에이지투웨니스_1019"
        # },
    #  {
    #     "url": "https://booking.naver.com/booking//12/bizes/1249231",
    #     "tag": "토리든",
    #     "validate": 1
    # },
    #  {
    #     "url": "https://booking.naver.com/booking/12/bizes/1276629/items/6332309?from=myp&startDateTime=2024-12-18T00%3A00%3A00%2B09%3A00",
    #     "tag": "티르티르_1218",
    #     "validate": 1
    # },F
    #  {
    #     "url": "https://booking.naver.com/booking/12/bizes/1344902/items/6513108?area=ple&lang=ko&startDateTime=2025-03-01T00%3A00%3A00%2B09%3A00&tab=book&theme=place",
    #     "tag": "나르카_0301"
    # },
    #  {
    #     "url": "https://booking.naver.com/booking/12/bizes/1344902/items/6513108?area=ple&lang=ko&startDateTime=2025-03-02T00%3A00%3A00%2B09%3A00&tab=book&theme=place",
    #     "tag": "나르카_0302"
    # },
     {
        "url": "https://m.booking.naver.com/booking/12/bizes/1366759/items/6589834?startDateTime=2025-04-05T00%3A00%3A00%2B09%3A00",
        "tag": "컴온스타일_0405"
    },
     {
        "url": "https://m.booking.naver.com/booking/12/bizes/1366759/items/6589834?startDateTime=2025-04-06T00%3A00%3A00%2B09%3A00",
        "tag": "컴온스타일_0406"
    },
     {
        "url": "https://booking.naver.com/booking/12/bizes/1249231/items/6620152?startDateTime=2025-04-17T00%3A00%3A00%2B09%3A00",
        "tag": "나전칠기_0417"
    },
     {
        "url": "https://booking.naver.com/booking/12/bizes/1249231/items/6620152?startDateTime=2025-04-24T00%3A00%3A00%2B09%3A00",
        "tag": "나전칠기_0424"
    },
     {
        "url": "https://booking.naver.com/booking/12/bizes/1249231/items/6633589?startDateTime=2025-04-12T00%3A00%3A00%2B09%3A00",
        "tag": "요가_0412"
    },
    # https://booking.naver.com/booking/12/bizes/1243139/items/6207807?bookingId=769366787&endDateTime=2024-10-19T05:30:00Z&options=&prices=7591773&startDateTime=2024-10-19T05:30:00Z
    # https://booking.naver.com/booking/6/bizes/1239631/items/6194317
    # https://booking.naver.com/booking/6/bizes/1239631/items/6194341
    # https://m.booking.naver.com/booking/5/bizes/1240483/items/6202961?theme=place&area=ple/
    # https://map.naver.com/p/entry/place/1392624239?c=15.00,0,0,0,dh
]
