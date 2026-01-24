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

    # 3. 사람인 척 위장하기 (헤더 추가)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.dhlottery.co.kr/',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    }

    # 4. 다음 회차 조회
    for i in range(1, 6):
        target = max_round + i
        print(f"🔍 {target}회차 요청 중 (공식 API)...")
        
        try:
            # 헤더를 같이 보냅니다 (headers=headers)
            api_url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={target}"
            resp = requests.get(api_url, headers=headers, timeout=10)
            
            # 응답이 JSON인지 확인
            try:
                data = resp.json()
            except ValueError:
                print("   🚨 서버에서 차단당했거나 잘못된 응답입니다. (HTML 반환됨)")
                break
            
            # 결과 확인
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
            
            # 5. 저장
            supabase.table("lotto_draws").insert(insert_data).execute()
            print(f"   ✅ {target}회차 ({data['drwNoDate']}) 저장 완료!")
            time.sleep(2) # 2초 휴식 (너무 빠르면 또 차단당함)
            
        except Exception as e:
            print(f"   ⚠️ 에러 발생: {e}")
            break

if __name__ == "__main__":
    main()
