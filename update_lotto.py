import os
import time
import requests
import json
from supabase import create_client, Client

# 환경변수 로드
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("❌ 오류: Supabase 환경변수가 없습니다.")
    exit(1)

supabase = create_client(url, key)

def main():
    # 1. DB에서 가장 마지막 회차 조회
    try:
        res = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
        max_round = res.data[0]['round'] if res.data else 0
    except:
        max_round = 0
    
    print(f"📊 현재 DB 마지막 회차: {max_round}회")

    # 2. 다음 회차 조회 (동행복권 공식 API 사용)
    # 한 번에 5회차까지 넉넉하게 체크
    for i in range(1, 5):
        target = max_round + i
        print(f"🔍 {target}회차 데이터 요청 중 (동행복권)...")
        
        try:
            # 공식 API 주소 (화면 해석 필요 없이 데이터만 줌)
            api_url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={target}"
            resp = requests.get(api_url)
            data = resp.json()
            
            # 성공 여부 확인 (returnValue가 'success'여야 함)
            if data.get('returnValue') != 'success':
                print(f"   📌 {target}회차는 아직 추첨 전입니다.")
                break
            
            # 데이터 추출
            numbers = [
                data['drwtNo1'], data['drwtNo2'], data['drwtNo3'],
                data['drwtNo4'], data['drwtNo5'], data['drwtNo6']
            ]
            bonus = data['bnusNo']
            date_str = data['drwNoDate'] # 형식: 2026-01-24

            insert_data = {
                "round": target,
                "date": date_str,
                "numbers
