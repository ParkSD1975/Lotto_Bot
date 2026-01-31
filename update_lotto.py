import os
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re

def get_hot_cold_status(count, period):
    if period == 10:
        return 'hot' if count >= 3 else ('cold' if count == 0 else 'warm')
    return 'warm'

def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase = create_client(url, key)

    # 1. 최신 당첨 회차 확인 및 크롤링
    res_draws = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
    max_draw = res_draws.data[0]['round'] if res_draws.data else 0
    target_round = max_draw + 1

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    try:
        resp = requests.get(f"https://search.daum.net/search?w=tot&q={target_round}회+로또", headers=headers)
        soup = BeautifulSoup(resp.text, 'html.parser')
        box = soup.select_one('#lottoColl')
        if box and f"{target_round}회" in box.text:
            date_text = box.select_one('.date').text
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            balls = [int(b.text) for b in box.select('.ball') if b.text.strip().isdigit()]
            
            # lotto_draws 저장
            supabase.table("lotto_draws").insert({
                "round": target_round, "date": f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}",
                "numbers": balls[:6], "bonus": balls[6]
            }).execute()
            print(f"✅ {target_round}회 당첨번호 저장 완료")
            max_draw = target_round
    except: print("신규 회차 없음")

    # 2. 누락된 분석 테이블 업데이트 (number_round_stats, regression_details)
    res_stats = supabase.table("number_round_stats").select("round").order("round", desc=True).limit(1).execute()
    max_stat = res_stats.data[0]['round'] if res_stats.data else 0

    if max_draw > max_stat:
        missing = list(range(max_stat + 1, max_draw + 1))
        all_draws = supabase.table("lotto_draws").select("*").order("round", desc=True).limit(350).execute().data
        draws_map = {d['round']: d for d in all_draws}

        for r in missing:
            print(f"📊 {r}회차 상세 분석 데이터 생성 중...")
            curr = draws_map[r]
            curr_nums = set(curr['numbers'])
            
            stats_batch = []
            reg_batch = []

            # (A) number_round_stats 계산
            for n in range(1, 46):
                prev_draws = [d for d in all_draws if d['round'] < r]
                gap = 0
                for pd in prev_draws:
                    if n in pd['numbers']: break
                    gap += 1
                
                f10 = sum(1 for d in prev_draws[:10] if n in d['numbers'])
                reg_hit = 0
                for dist in range(2, 201):
                    src_r = r - dist
                    if src_r in draws_map and n in draws_map[src_r]['numbers']: reg_hit += 1

                stats_batch.append({
                    "round": r, "number": n, "gap": gap, "freq_10": f10,
                    "hot_cold_10": get_hot_cold_status(f10, 10),
                    "regression_hit_count": reg_hit, "is_winner": n in curr_nums
                })

            # (B) regression_details 계산 (2~200회귀)
            for dist in range(2, 201):
                src_r = r - dist
                if src_r in draws_map:
                    src_nums = draws_map[src_r]['numbers']
                    matches = list(curr_nums.intersection(set(src_nums)))
                    reg_batch.append({
                        "target_round": r, "regression_distance": dist,
                        "source_round": src_r, "source_numbers": src_nums,
                        "matching_numbers": matches, "match_count": len(matches)
                    })

            supabase.table("number_round_stats").insert(stats_batch).execute()
            supabase.table("regression_details").insert(reg_batch).execute()
            print(f"✅ {r}회차 분석 테이블(Stats/Regression) 동기화 완료")

if __name__ == "__main__":
    main()
