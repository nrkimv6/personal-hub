import requests

url = "https://gifticonapp40.gifticon.com/app45/sns/kakao/gifticon.do?ged=oaakGcTZIfigY0WYCarqUSKStcPTug-ZvWpVseESfK4"
resp = requests.get(url)
print(resp.text[:2000])

