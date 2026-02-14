import os
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re
from datetime import datetime

# ============================================================
# [헬퍼 함수] 분석용 로직
# ============================================================
def get_hot_cold_status(count, period):
    if period == 10:
        return 'hot' if count >= 3 else ('cold' if count == 0 else 'warm')
    return 'warm'

def is_twin_number(number):
    return number > 10 and (number % 10 == number // 10)

def get_missing_count(number, all_draws, current_round):
    for draw in all_draws:
        if draw['round'] < current_round and number in draw['numbers']:
            return current_round - draw['round'] - 1
    return current_round - 1

def get_last_appearance_round(number, all_draws, current_round):
    for draw in all_draws:
        if draw['round'] < current_round and number in draw['numbers']:
            return draw['round']
    return None

# ============================================================
# [핵심] 로또 데이터 가져오기 (3중 백업)
# ============================================================
def fetch_lotto_data(target_round):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.dhlottery.co.kr/'
    }
    today_str = datetime.now().strftime('%Y-%m-%d')

    # 1. API 
    try:
        url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={target_round}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and 'application/json' in resp.headers.get('Content-Type', ''):
            data = resp.json()
            if data.get(\"returnValue\") == \"success\":
                return {
                    \"round\": target_round,
                    \"date\": data.get(\"drwNoDate\", today_str),
                    \"numbers\": [data[f\"drwtNo{i}\"] for i in range(1, 7)],
                    \"bonus\": data.get(\"bnusNo\")
                }
    except: pass

    # 2. Naver
    try:
        url = f\"https://search.naver.com/search.naver?query={target_round}회+로또\"
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        container = soup.select_one('.lotto_win_number')
        if container:
            balls = [int(b.text) for b in container.select('.ball')]
            date_text = soup.select_one('.sub_title').text if soup.select_one('.sub_title') else \"\"
            date_match = re.search(r'(\\d{4})[./\\-](\\d{2})[./\\-](\\d{2})', date_text)
            date_str = f\"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}\" if date_match else today_str
            if len(balls) >= 7:
                return {\"round\": target_round, \"date\": date_str, \"numbers\": balls[:6], \"bonus\": balls[6]}
    except: pass

    # 3. Daum
    try:
        url = f\"https://search.daum.net/search?w=tot&q={target_round}회+로또\"
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        box = soup.select_one('#lottoColl')
        if box:
            balls = [int(b.text) for b in box.select('.ball') if b.text.strip().isdigit()]
            if len(balls) >= 7:
                return {\"round\": target_round, \"date\": today_str, \"numbers\": balls[:6], \"bonus\": balls[6]}
    except: pass
    return None

def main():
    url = os.environ.get(\"SUPABASE_URL\")
    key = os.environ.get(\"SUPABASE_KEY\")
    if not url or not key: return
    supabase = create_client(url, key)

    # 1. 최신 회차 동기화
    res = supabase.table(\"lotto_draws\").select(\"round\").order(\"round\", desc=True).limit(1).execute()
    max_db = res.data[0]['round'] if res.data else 0
    target = max_db + 1
    
    print(f\"🔍 목표 회차: {target}회\")
    new_data = fetch_lotto_data(target)
    if new_data:
        supabase.table(\"lotto_draws\").upsert(new_data).execute()
        print(f\"✅ {target}회 당첨번호 저장 완료\")
        max_db = target

    # 2. 분석용 데이터 벌크 로드 (과거 데이터 매핑)
    all_draws = supabase.table(\"lotto_draws\").select(\"*\").order(\"round\", desc=True).limit(500).execute().data
    draws_map = {d['round']: d for d in all_draws}

    # 3. 테이블별 업데이트 루프 (Stats, Regression, Features)
    tables = [
        {\"name\": \"number_round_stats\", \"pk\": \"round\"},
        {\"name\": \"regression_details\", \"pk\": \"target_round\"},
        {\"name\": \"number_features_by_round\", \"pk\": \"round\"}
    ]

    for table in tables:
        res_t = supabase.table(table['name']).select(table['pk']).order(table['pk'], desc=True).limit(1).execute()
        max_t = res_t.data[0][table['pk']] if res_t.data else 0
        
        if max_db > max_t:
            for r in range(max_t + 1, max_db + 1):
                curr = draws_map.get(r)
                if not curr: continue
                
                curr_nums = set(curr['numbers'])
                prev_draws = [d for d in all_draws if d['round'] < r]
                prev_1 = draws_map.get(r-1)
                
                if table['name'] == \"number_round_stats\":
                    batch = []
                    for n in range(1, 46):
                        gap = 0
                        for pd in prev_draws:
                            if n in pd['numbers']: break
                            gap += 1
                        f10 = sum(1 for d in prev_draws[:10] if n in d['numbers'])
                        reg_hit = sum(1 for d in range(2, 201) if (r-d) in draws_map and n in draws_map[r-d]['numbers'])
                        batch.append({\"round\": r, \"number\": n, \"gap\": gap, \"freq_10\": f10, \"hot_cold_10\": get_hot_cold_status(f10, 10), \"regression_hit_count\": reg_hit, \"is_winner\": n in curr_nums})
                    supabase.table(\"number_round_stats\").insert(batch).execute()

                elif table['name'] == \"regression_details\":
                    reg_batch = []
                    for dist in range(2, 201):
                        src_r = r - dist
                        if src_r in draws_map:
                            src_nums = draws_map[src_r]['numbers']
                            matches = list(curr_nums.intersection(set(src_nums)))
                            reg_batch.append({\"target_round\": r, \"regression_distance\": dist, \"source_round\": src_r, \"source_numbers\": src_nums, \"matching_numbers\": matches, \"match_count\": len(matches)})
                    supabase.table(\"regression_details\").insert(reg_batch).execute()

                elif table['name'] == \"number_features_by_round\":
                    feat_batch = []
                    neighbor_set = set()
                    if prev_1:
                        for n in prev_1['numbers']:
                            if n-1>=1: neighbor_set.add(n-1)
                            if n+1<=45: neighbor_set.add(n+1)
                        for n in prev_1['numbers']: neighbor_set.discard(n)
                    
                    for n in range(1, 46):
                        f = {\"round\": r, \"number\": n, \"hot_cold\": get_hot_cold_status(sum(1 for d in prev_draws[:10] if n in d['numbers']), 10),
                             \"appearance_count_5\": sum(1 for d in prev_draws[:5] if n in d['numbers']),
                             \"appearance_count_10\": sum(1 for d in prev_draws[:10] if n in d['numbers']),
                             \"is_neighbor\": n in neighbor_set, \"is_twin\": is_twin_number(n),
                             \"missing_count\": get_missing_count(n, prev_draws, r), \"is_carryover\": n in (set(prev_1['numbers']) if prev_1 else set()),
                             \"is_winning\": n in curr_nums, \"is_bonus\": n == curr['bonus']}
                        for dist in [2, 3, 4, 5, 10, 20, 50, 100]: # 주요 회귀선만 우선 추가 (성능상)
                            f[f\"regression_{dist}\"] = (r-dist) in draws_map and n in draws_map[r-dist]['numbers']
                        feat_batch.append(f)
                    supabase.table(\"number_features_by_round\").insert(feat_batch).execute()
                
                print(f\"📊 {table['name']} - {r}회 업데이트 완료\")

    print(\"🎉 모든 분석 동기화가 완료되었습니다!\")

if __name__ == \"__main__\":
    main()
