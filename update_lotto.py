import os
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re

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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # 4. 다음(Daum) 검색으로 데이터 가져오기
    for i in range(1, 6):
        target = max_round + i
        print(f"🔍 {target}회차 검색 중 (Daum)...")
        
        try:
            # 다음 검색 URL
            search_url = f"https://search.daum.net/search?w=tot&q={target}회+로또"
            resp = requests.get(search_url, headers=headers)
            soup = BeautifulSoup(resp.text, 'html.parser')

            # 로또 정보 박스 찾기
            box = soup.select_one('#lottoColl')
            
            # 박스가 없으면 아직 추첨 전
            if not box:
                print(f"   📌 {target}회차 검색 결과가 없습니다.")
                break
            
            # 텍스트 검증 (검색 결과가 엉뚱한 거면 스킵)
            text_content = box.text
            if f"{target}회" not in text_content:
                print(f"   ⚠️ 검색 결과가 정확하지 않아 건너뜁니다.")
                break

            # 날짜 추출 (2026.01.24 형태 찾기)
            date_element = box.select_one('.date')
            date_text = date_element.text if date_element else ""
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            
            if date_match:
                date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            else:
                print("   ⚠️ 날짜를 찾을 수 없습니다.")
                break

            # 당첨 번호 추출 (숫자만 있는 .ball 요소만 필터링)
            all_balls = box.select('.ball')
            balls = [b for b in all_balls if b.text.strip().isdigit()]
            
            if len(balls) < 7:
                print(f"   ⚠️ 공 번호를 모두 찾지 못했습니다. (찾은 개수: {len(balls)})")
                break
                
            numbers = [int(b.text) for b in balls[:6]]
            bonus = int(balls[6].text)

            insert_data = {
                "round": target,
                "date": date_str,
                "numbers": numbers,
                "bonus": bonus
            }
            
            # 5. 저장
            supabase.table("lotto_draws").insert(insert_data).execute()
            print(f"   ✅ {target}회차 ({date_str}) 저장 완료!")
            print(f"      번호: {numbers} + 보너스: {bonus}")
            time.sleep(1)
            
        except Exception as e:
            print(f"   ⚠️ 에러 발생: {e}")
            break

if __name__ == "__main__":
    main()
