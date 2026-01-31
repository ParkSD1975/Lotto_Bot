import os
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re

# ============================================================
# 설정 및 상수
# ============================================================
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}

def get_hot_cold_status_legacy(count, period):
    """기존 hot_cold.html 호환용 상태 판별"""
    if period == 5:
        if count >= 2: return 'hot'
        elif count >= 1: return 'neutral'
        else: return 'cold'
    elif period == 10:
        if count >= 3: return 'hot'
        elif count >= 1: return 'neutral'
        else: return 'cold'
    elif period == 15:
        if count >= 4: return 'hot'
        elif count >= 2: return 'neutral'
        else: return 'cold'
    else: # 20
        if count >= 5: return 'hot'
        elif count >= 2: return 'neutral'
        else: return 'cold'

def main():
    # 1. 환경변수 확인
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ 오류: Supabase 환경변수(URL/KEY)가 없습니다.")
        return

    supabase = create_client(url, key)

    # 2. DB에서 최신 회차 확인
    try:
        res = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
        max_round = res.data[0]['round'] if res.data else 0
    except Exception as e:
        print(f"⚠️ DB 연결/조회 오류: {e}")
        max_round = 0
    
    print(f"📊 현재 DB 마지막 회차: {max_round}회")

    # 3. 새로운 회차 크롤링 (Daum 검색)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    new_rounds_data = []

    for i in range(1, 6):
        target = max_round + i
        print(f"🔍 {target}회차 검색 중 (Daum)...")
        
        try:
            search_url = f"https://search.daum.net/search?w=tot&q={target}회+로또"
            resp = requests.get(search_url, headers=headers)
            soup = BeautifulSoup(resp.text, 'html.parser')

            box = soup.select_one('#lottoColl')
            if not box or f"{target}회" not in box.text:
                print(f"   📌 {target}회차 정보가 아직 없습니다.")
                break

            # 날짜 및 번호 파싱
            date_element = box.select_one('.date')
            date_text = date_element.text if date_element else ""
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else ""

            all_balls = box.select('.ball')
            balls = [b for b in all_balls if b.text.strip().isdigit()]
            
            if len(balls) < 7:
                print("   ⚠️ 공 번호 파싱 실패")
                break
                
            numbers = [int(b.text) for b in balls[:6]]
            bonus = int(balls[6].text)

            draw_data = {
                "round": target,
                "date": date_str,
                "numbers": numbers,
                "bonus": bonus
            }
            
            supabase.table("lotto_draws").insert(draw_data).execute()
            print(f"   ✅ {target}회차 원천 데이터 저장 완료")
            
            new_rounds_data.append(draw_data)
            time.sleep(1)
            
        except Exception as e:
            print(f"   ⚠️ 크롤링 에러: {e}")
            break

    # 4. 분석 데이터 생성 (number_features_by_round 업데이트)
    if new_rounds_data:
        print(f"\n📈 {len(new_rounds_data)}개 신규 회차 분석 중...")
        res_all = supabase.table("lotto_draws").select("*").order("round", desc=True).limit(300).execute()
        past_draws = res_all.data 

        for new_draw in new_rounds_data:
            curr_round = new_draw['round']
            curr_nums = set(new_draw['numbers'])
            prev_draw = next((d for d in past_draws if d['round'] == curr_round - 1), None)
            prev_nums = set(prev_draw['numbers']) if prev_draw else set()

            features_rows = []
            for num in range(1, 46):
                draws_before = [d for d in past_draws if d['round'] < curr_round]
                
                freq_5 = sum(1 for d in draws_before[:5] if num in d['numbers'])
                freq_10 = sum(1 for d in draws_before[:10] if num in d['numbers'])
                freq_15 = sum(1 for d in draws_before[:15] if num in d['numbers'])
                freq_20 = sum(1 for d in draws_before[:20] if num in d['numbers'])

                row = {
                    "round": curr_round,
                    "number": num,
                    "hot_cold": get_hot_cold_status_legacy(freq_10, 10),
                    "appearance_count_5": freq_5,
                    "appearance_count_10": freq_10,
                    "appearance_count_15": freq_15,
                    "appearance_count_20": freq_20,
                    "is_carryover": num in prev_nums,
                    "is_winning": num in curr_nums,
                    "is_bonus": num == new_draw['bonus']
                }
                # 회귀 컬럼 추가 (필요한 경우)
                for dist in [2, 3, 4, 5, 10, 20, 30, 40, 50, 100, 200]:
                    target_r = curr_round - dist
                    src_d = next((d for d in past_draws if d['round'] == target_r), None)
                    row[f"regression_{dist}"] = (num in src_d['numbers']) if src_d else False
                
                features_rows.append(row)

            supabase.table("number_features_by_round").insert(features_rows).execute()
            print(f"   ✅ {curr_round}회차 분석 데이터 저장 완료")

if __name__ == "__main__":
    main()
