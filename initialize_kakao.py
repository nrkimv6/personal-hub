import requests

client_id = '1d5f0b2a49c46c4a2f85f56a2b694879'
redirect_uri = 'https://jarada.life'
def get_access_token(client_id, redirect_uri, code):
    url = "https://kauth.kakao.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(url, headers=headers, data=payload)
    if response.status_code == 200:
        return response.json()['access_token']
    else:
        # print(json.dumps(response, ensure_ascii=False, indent=3))
        print(vars(response))
        return None
# https://jarada.life/?code=RUUrAd6G6wFO4q-xEozxMBettScBaHIKjdPe4YavMqWtXGzi31SMBgAAAAQKKiUPAAABkDnCNAhtZc76WqiBKA
# https://kauth.kakao.com/oauth/authorize?client_id=1d5f0b2a49c46c4a2f85f56a2b694879&redirect_uri=https://jarada.life&response_type=code

# #https://kauth.kakao.com/oauth/authorize?client_id=1d5f0b2a49c46c4a2f85f56a2b694879&redirect_uri=https://jarada.life&response_type=code&scope=talk_message


# Replace with your actual data
def generate_access_token():
    # return 'kEp5FMsCVJ7wBG5Hffwfswu0oaRVJkSDAAAAAQo9dRsAAAGQOdjXmPoXDHwO3UaB'
    # return '1ylb2m_paLNSEjCc6g2jSunXyIbpkindAAAAAQopyNkAAAGQOfE-O_oXDHwO3UaB'
    # https://jarada.life/?code=Yo-ShM_dLMHWnRuLXcdQEvYoNNe-7b_rYtWYGHT4AX7Vw5D4ohW-AQAAAAQKKiWRAAABkH4XN4nHP8VuE1ZNOQ
    return 'yx_nqpyMAMHMQl5x2G5wmEnmPCmd5dcmAAAAAQo8JJoAAAGQfhjX6_oXDHwO3UaB' #2024-07-04

    # code = 'QPxh4xiJX52kRBGzX0OnNjJmhzQHgb_dfJO6zmFyNKsYIs99NPhd7AAAAAQKPXWbAAABkDnw_6_o6jj-qNQmaA'
    code = 'Yo-ShM_dLMHWnRuLXcdQEvYoNNe-7b_rYtWYGHT4AX7Vw5D4ohW-AQAAAAQKKiWRAAABkH4XN4nHP8VuE1ZNOQ'

    access_token = get_access_token(client_id, redirect_uri, code)
    if access_token:
        print("Access token received:", access_token)
    else:
        print("Failed to get access token")
    return access_token

