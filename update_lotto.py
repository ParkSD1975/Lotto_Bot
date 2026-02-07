import os
import re
import requests
from bs4 import BeautifulSoup
from supabase import create_client

# ============================================================
# 1. 설정 및 헬퍼 함수
# ============================================================

def get_hot_cold_status_basic(count, period):
    """number_round_stats용 간단 상태"""
    if period == 10:
        return 'hot' if count >= 3 else ('cold' if count == 0 else 'warm')
    return 'warm'

def get_hot_cold_status_detail(number, recent_draws, period=10):
    """number_features_by_round용 상세 상태"""
    count = sum(1 for draw in recent_draws[:period] if number in draw['numbers'])
    if count >= 3: return 'hot'
    elif count >= 1: return 'neutral'
    else: return 'cold'

def get_appearance_count(number, recent_draws, period):
    return sum(1 for draw in recent_draws[:period] if number in draw['numbers'])

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

def check_regression(number, all_draws, current_round, n_back):
    target_round = current_round - n_back
    for draw in all_draws:
        if draw['round'] == target_round:
            return number in draw['numbers']
    return False

def is_twin_number(number):
    last_digit = number % 10
    twins = [i for i in range(1, 46) if i % 10 == last_digit]
    return len(twins) > 1

# ============================================================
# 2. 메인 로직
# ============================================================

def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("❌ Supabase 환경변수 누락")
        return

    supabase = create_client(url, key)

    # --------------------------------------------------------
    # [Step 1] 최신 회차 크롤링 및 lotto_draws 업데이트
    # --------------------------------------------------------
    res_draws = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
    max_draw_db = res_draws.data[0]['round'] if res_draws.data else 0
    target_round = max_draw_db + 1

    print(f"🔍 {target_round}회차 데이터 확인 중...")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = requests.get(f"https://search.daum.net/search?w=tot&q={target_round}회+로또", headers=headers)
        soup = BeautifulSoup(resp.text, 'html.parser')
        box = soup.select_one('#lottoColl')
        
        if box and f"{target_round}회" in box.text:
            date_text = box.select_one('.date').text
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            balls = [int(b.text) for b in box.select('.ball') if b.text.strip().isdigit()]
            
            if len(balls) >= 7:
                supabase.table("lotto_draws").insert({
                    "round": target_round, 
                    "date": f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}",
                    "numbers": balls[:6], 
                    "bonus": balls[6]
                }).execute()
                print(f"✅ {target_round}회 당첨번호 저장 완료")
                max_draw_db = target_round # DB 최신값 갱신
            else:
                print("⚠️ 번호 파싱 실패")
        else:
            print("⏳ 신규 회차 정보 없음 (아직 추첨 전이거나 업데이트 안됨)")
    except Exception as e: 
        print(f"⚠️ 크롤링 에러: {e}")

    # --------------------------------------------------------
    # [Step 2] 전체 데이터 로드 (분석용) - 5000개로 제한 늘림
    # --------------------------------------------------------
    all_draws_res = supabase.table("lotto_draws").select("*").order("round", desc=True).range(0, 5000).execute()
    all_draws = all_draws_res.data
    draws_map = {d['round']: d for d in all_draws}

    if not all_draws:
        print("❌ 데이터 없음")
        return

    # --------------------------------------------------------
    # [Step 3] 기본 통계 (number_round_stats, regression_details) 업데이트
    # --------------------------------------------------------
    res_stats = supabase.table("number_round_stats").select("round").order("round", desc=True).limit(1).execute()
    max_stat = res_stats.data[0]['round'] if res_stats.data else 0

    if max_draw_db > max_stat:
        missing_stats = list(range(max_stat + 1, max_draw_db + 1))
        for r in missing_stats:
            print(f"📊 {r}회차 기본 통계 생성 중...")
            curr = draws_map.get(r)
            if not curr: continue

            curr_nums = set(curr['numbers'])
            stats_batch = []
            reg_batch = []

            # A. number_round_stats
            prev_draws = [d for d in all_draws if d['round'] < r] # 해당 회차 이전 데이터만
            
            for n in range(1, 46):
                gap = 0
                for pd in prev_draws:
                    if n in pd['numbers']: break
                    gap += 1
                
                f10 = sum(1 for d in prev_draws[:10] if n in d['numbers'])
                
                # 회귀 히트수 (2~200)
                reg_hit = 0
                for dist in range(2, 201):
                    src_r = r - dist
                    if src_r in draws_map and n in draws_map[src_r]['numbers']: reg_hit += 1

                stats_batch.append({
                    "round": r, "number": n, "gap": gap, "freq_10": f10,
                    "hot_cold_10": get_hot_cold_status_basic(f10, 10),
                    "regression_hit_count": reg_hit, "is_winner": n in curr_nums
                })

            # B. regression_details
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

            if stats_batch: supabase.table("number_round_stats").insert(stats_batch).execute()
            if reg_batch: supabase.table("regression_details").insert(reg_batch).execute()

    # --------------------------------------------------------
    # [Step 4] 상세 특성 (number_features_by_round) 업데이트
    # --------------------------------------------------------
    res_features = supabase.table("number_features_by_round").select("round").order("round", desc=True).limit(1).execute()
    max_feat = res_features.data[0]['round'] if res_features.data else 0

    if max_draw_db > max_feat:
        missing_feats = list(range(max_feat + 1, max_draw_db + 1))
        print(f"📈 {len(missing_feats)}개 회차의 상세 특성(Features) 계산 시작...")

        for target_round in missing_feats:
            print(f"🔄 {target_round}회차 상세 특성 처리 중...")
            
            target_draw = draws_map.get(target_round)
            prev_draw = draws_map.get(target_round - 1)
            
            if not target_draw: continue

            winning_numbers = target_draw['numbers']
            bonus_number = target_draw['bonus']
            prev_numbers = prev_draw['numbers'] if prev_draw else []
            
            # 현재 회차보다 과거 데이터만 필터링
            draws_before = [d for d in all_draws if d['round'] < target_round]

            features_to_insert = []
            
            for number in range(1, 46):
                # 이웃수 계산
                neighbor_set = set()
                if prev_numbers:
                    for n in prev_numbers:
                        if n - 1 >= 1: neighbor_set.add(n - 1)
                        if n + 1 <= 45: neighbor_set.add(n + 1)
                    for n in prev_numbers: neighbor_set.discard(n)
                
                feature = {
                    "round": target_round,
                    "number": number,
                    "hot_cold": get_hot_cold_status_detail(number, draws_before, 10),
                    "appearance_count_5": get_appearance_count(number, draws_before, 5),
                    "appearance_count_10": get_appearance_count(number, draws_before, 10),
                    "appearance_count_15": get_appearance_count(number, draws_before, 15),
                    "appearance_count_20": get_appearance_count(number, draws_before, 20),
                    "is_neighbor": number in neighbor_set,
                    "is_consecutive": False, # 로직 필요 시 추가
                    "is_twin": is_twin_number(number),
                    "missing_count": get_missing_count(number, draws_before, target_round),
                    "last_appearance_round": get_last_appearance_round(number, draws_before, target_round),
                    "is_carryover": number in prev_numbers,
                    "is_winning": number in winning_numbers,
                    "is_bonus": number == bonus_number,
                }

                # 회귀 분석 (특성용)
                for n in [2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100, 150, 200]:
                    feature[f"regression_{n}"] = check_regression(number, draws_before, target_round, n)
                
                features_to_insert.append(feature)

            if features_to_insert:
                try:
                    supabase.table("number_features_by_round").insert(features_to_insert).execute()
                    print(f"   ✅ {target_round}회차 상세 특성 저장 완료")
                except Exception as e:
                    print(f"   ❌ 저장 실패: {e}")

    print("\n🎉 모든 업데이트 작업 완료!")

if __name__ == "__main__":
    main()
