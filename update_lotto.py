import os
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re

# ============================================================
# 설정 및 상수
# ============================================================
def get_hot_cold_status_legacy(count, period):
    if period == 5:
        return 'hot' if count >= 2 else ('neutral' if count >= 1 else 'cold')
    elif period == 10:
        return 'hot' if count >= 3 else ('neutral' if count >= 1 else 'cold')
    elif period == 15:
        return 'hot' if count >= 4 else ('neutral' if count >= 2 else 'cold')
    else: # 20
        return 'hot' if count >= 5 else ('neutral' if count >= 2 else 'cold')

def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("❌ 오류: Supabase 환경변수가 없습니다.")
        return
    supabase = create_client(url, key)

    # 1. DB 상태 확인
    res_draws = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
    max_draw = res_draws.data[0]['round'] if res_draws.data else 0
    
    # 2. 신규 회차 크롤링 (Daum)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    target_round = max_draw + 1
    print(f"🔍 {target_round}회차 크롤링 시도...")
    
    try:
        search_url = f"https://search.daum.net/search?w=tot&q={target_round}회+로또"
        resp = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(resp.text, 'html.parser')
        box = soup.select_one('#lottoColl')
        
        if box and f"{target_round}회" in box.text:
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', box.select_one('.date').text)
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            balls = [int(b.text) for b in box.select('.ball') if b.text.strip().isdigit()]
            
            draw_data = {"round": target_round, "date": date_str, "numbers": balls[:6], "bonus": balls[6]}
            supabase.table("lotto_draws").insert(draw_data).execute()
            print(f"✅ {target_round}회차 당첨번호 저장 완료")
            max_draw = target_round
    except Exception as e:
        print(f"ℹ️ 신규 회차 없음 또는 에러: {e}")

    # 3. 누락된 분석 데이터(1209회 포함) 생성 로직
    res_feats = supabase.table("number_features_by_round").select("round").order("round", desc=True).limit(1).execute()
    max_feat = res_feats.data[0]['round'] if res_feats.data else 0
    
    if max_draw > max_feat:
        missing_rounds = list(range(max_feat + 1, max_draw + 1))
        print(f"⚠️ 분석 누락 발견: {missing_rounds}회차 계산 시작...")
        
        # 분석을 위한 과거 데이터 로드
        all_past = supabase.table("lotto_draws").select("*").order("round", desc=True).limit(300).execute().data
        
        for r in missing_rounds:
            curr_draw = next(d for d in all_past if d['round'] == r)
            curr_nums = set(curr_draw['numbers'])
            prev_draw = next((d for d in all_past if d['round'] == r - 1), None)
            prev_nums = set(prev_draw['numbers']) if prev_draw else set()
            
            features = []
            for n in range(1, 46):
                before = [d for d in all_past if d['round'] < r]
                f10 = sum(1 for d in before[:10] if n in d['numbers'])
                
                row = {
                    "round": r, "number": n, "is_winning": n in curr_nums,
                    "hot_cold": get_hot_cold_status_legacy(f10, 10),
                    "is_carryover": n in prev_nums,
                    "appearance_count_10": f10,
                    "is_bonus": n == curr_draw['bonus']
                }
                # 회귀 컬럼 자동 생성
                for d_dist in [2, 3, 4, 5, 10, 20, 30, 40, 50, 100, 200]:
                    src = next((pd for pd in all_past if pd['round'] == r - d_dist), None)
                    row[f"regression_{d_dist}"] = (n in src['numbers']) if src else False
                features.append(row)
            
            supabase.table("number_features_by_round").insert(features).execute()
            print(f"✅ {r}회차 분석 데이터(45개 번호) 동기화 완료")

if __name__ == "__main__":
    main()
