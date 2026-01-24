import os
import time
import requests
import json
from supabase import create_client

def main():
    # 1. 환경변수 확인
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ 오류: Supabase 환경변수(URL/KEY)가 없습니다.")
        return

    supabase = create_client(url, key)

    # 2. DB에서 마지막 회차 가져오기
    try:
        res = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
        max_round = res.data[0]['round'] if res.data else 0
    except:
        max_round = 0
    
    print(f"📊 현재 DB 마지막 회차: {max_round}회")

    # 3. 다음 회차 조회 (동행복권 공식 API 사용)
    for i in range(1, 6):
        target = max_round + i
        print(f"🔍 {target}회차 요청 중 (공식 API)...")
        
        try:
            # 동행복권 공식 주소
            api_url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={target}"
            resp = requests.get(api_url)
            data = resp.json()
            
            # 결과 확인 (success가 아니면 아직 추첨 전)
            if data.get("returnValue") != "success":
                print(f"   📌 {target}회차는 아직 결과가 없습니다.")
                break

            # 데이터 정리
            numbers = [
                data["drwtNo1"], data["drwtNo2"], data["drwtNo3"],
                data["drwtNo4"], data["drwtNo5"], data["drwtNo6"]
            ]
            
            insert_data = {
                "round": target,
                "date": data["drwNoDate"],
                "numbers": numbers,
                "bonus": data["bnusNo"]
            }
            
            # 4. 저장
            supabase.table("lotto_draws").insert(insert_data).execute()
            print(f"   ✅ {target}회차 ({data['drwNoDate']}) 저장 완료!")
            time.sleep(1)
            
        except Exception as e:
            print(f"   ⚠️ 에러 발생: {e}")
            break

if __name__ == "__main__":
    main()
