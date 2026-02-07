import os
import re
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client

# ============================================================
# [설정] 헬퍼 함수 정의
# ============================================================

def get_hot_cold_status_basic(count, period):
    """기본 통계용 핫/콜드"""
    if period == 10:
        return 'hot' if count >= 3 else ('cold' if count == 0 else 'warm')
    return 'warm'

def get_hot_cold_status_detail(number, recent_draws, period=10):
    """상세 특성용 핫/콜드"""
    count = sum(1 for draw in recent_draws[:period] if number in draw['numbers'])
    if count >= 3: return 'hot'
    elif count >= 1: return 'neutral'
    else: return 'cold'

def get_appearance_count(number, recent_draws, period):
    """최근 N회 출현 횟수"""
    return sum(1 for draw in recent_draws[:period] if number in draw['numbers'])

def get_missing_count(number, all_draws, current_round):
    """현재 기준 미출현 기간"""
    for draw in all_draws:
        if draw['round'] < current_round and number in draw['numbers']:
            return current_round - draw['round'] - 1
    return current_round - 1

def get_last_appearance_round(number, all_draws, current_round):
    """마지막 출현 회차"""
    for draw in all_draws:
        if draw['round'] < current_round and number in draw['numbers']:
            return draw['round']
    return None

def check_regression(number, all_draws, current_round, n_back):
    """N회전 회귀 적중 여부"""
    target_round = current_round - n_back
    for draw in all_draws:
        if draw['round'] == target_round:
            return number in draw['numbers']
    return False

def is_twin_number(number):
    """쌍둥이수 여부 (예: 11, 22, 33, 44)"""
    return number > 10 and (number % 10 == number // 10)

# ============================================================
# [핵심] 크롤링 함수 (Daum -> 동행복권 순차 시도)
# ============================================================
def fetch_lotto_data(target_round):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # 1. Daum 검색 시도
    try:
        url = f"https://search.daum.net/search?w=tot&q={target_round}회+로또"
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        box = soup.select_one('#lottoColl')
        
        if box and f"{target_round}회" in box.text:
            date_text = box.select_one('.date').text
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            balls = [int(b.text) for b in box.select('.ball') if b.text.strip().isdigit()]
            
            if len(balls) >= 7:
                print(f"✅ [Daum]에서 {target_round}회차 데이터 발견!")
                return {
                    "round": target_round,
                    "date": f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}",
                    "numbers": balls[:6],
                    "bonus": balls[6]
                }
    except Exception as e:
        print(f"⚠️ Daum 크롤링 실패: {e}")

    # 2. 동행복권 공식 홈페이지 시도 (Fallback)
    print("🔄 동행복권 공식 홈페이지에서 데이터 조회 시도...")
    try:
        url = "https://dhlottery.co.kr/gameResult.do?method=byWin"
        params = {'drwNo': target_round}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.encoding = 'euc-kr' # 동행복권은 EUC-KR 인코딩 사용
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        win_result = soup.select_one('.win_result')
        
        if win_result:
            # 회차 확인
            title = win_result.select_one('h4 strong')
            if title and str(target_round) in title.text:
                # 날짜 파싱
                date_text = win_result.select_one('.desc').text
                date_match = re.search(r'(\d{4})년 (\d{1,2})월 (\d{1,2})일', date_text)
                date_str = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
                
                # 번호 파싱
                balls = [int(span.text) for span in win_result.select('.ball_645')]
                
                if len(balls) >= 7:
                    print(f"✅ [동행복권]에서 {target_round}회차 데이터 발견!")
                    return {
                        "round": target_round,
                        "date": date_str,
                        "numbers": balls[:6],
                        "bonus": balls[6]
                    }
    except Exception as e:
        print(f"⚠️ 동행복권 크롤링 실패: {e}")

    return None

# ============================================================
# [메인] 실행 로직
# ============================================================

def main():
    # 환경변수 로드
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("❌ Supabase 환경변수(SUPABASE_URL, SUPABASE_KEY)가 없습니다.")
        return

    supabase = create_client(url, key)

    # --------------------------------------------------------
    # [Step 1] 최신 회차 확인 및 크롤링
    # --------------------------------------------------------
    print("🔍 DB에서 최신 회차 확인 중...")
    res_draws = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
    max_draw_db = res_draws.data[0]['round'] if res_draws.data else 0
    target_round = max_draw_db + 1
    
    print(f"🎯 목표 회차: {target_round}회")

    new_data = fetch_lotto_data(target_round)

    if new_data:
        # 데이터 저장 (Upsert)
        supabase.table("lotto_draws").upsert(new_data, on_conflict='round').execute()
        print(f"💾 {target_round}회차 당첨번호 DB 저장 완료")
        max_draw_db = target_round # DB 최신값 갱신
    else:
        print(f"⏳ {target_round}회차 정보를 아직 찾을 수 없습니다. (추첨 전이거나 사이트 반영 지연)")
        # 데이터가 없어도 기존에 누락된 분석 데이터가 있을 수 있으므로 계속 진행

    # --------------------------------------------------------
    # [Step 2] 전체 데이터 로드 (5000회분)
    # --------------------------------------------------------
    print("📊 분석을 위해 전체 로또 데이터 로딩 중...")
    all_draws_res = supabase.table("lotto_draws").select("*").order("round", desc=True).range(0, 5000).execute()
    all_draws = all_draws_res.data
    
    if not all_draws:
        print("❌ 분석할 데이터가 없습니다.")
        return
        
    draws_map = {d['round']: d for d in all_draws}

    # --------------------------------------------------------
    # [Step 3] 기본 통계 (number_round_stats / regression_details)
    # --------------------------------------------------------
    res_stats = supabase.table("number_round_stats").select("round").order("round", desc=True).limit(1).execute()
    max_stat = res_stats.data[0]['round'] if res_stats.data else 0

    if max_draw_db > max_stat:
        missing_stats = list(range(max_stat + 1, max_draw_db + 1))
        print(f"🛠️ 기본 통계 업데이트 필요: {missing_stats}")
        
        for r in missing_stats:
            curr = draws_map.get(r)
            if not curr: continue
            
            print(f"   Processed Round {r} (Basic Stats)...")
            curr_nums = set(curr['numbers'])
            stats_batch = []
            reg_batch = []

            # 과거 데이터 필터링
            prev_draws = [d for d in all_draws if d['round'] < r]
            
            # (A) number_round_stats
            for n in range(1, 46):
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
                    "hot_cold_10": get_hot_cold_status_basic(f10, 10),
                    "regression_hit_count": reg_hit, "is_winner": n in curr_nums
                })

            # (B) regression_details
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

            # 배치 저장
            if stats_batch: supabase.table("number_round_stats").insert(stats_batch).execute()
            if reg_batch: supabase.table("regression_details").insert(reg_batch).execute()

    # --------------------------------------------------------
    # [Step 4] 상세 특성 (number_features_by_round)
    # --------------------------------------------------------
    res_feat = supabase.table("number_features_by_round").select("round").order("round", desc=True).limit(1).execute()
    max_feat = res_feat.data[0]['round'] if res_feat.data else 0

    if max_draw_db > max_feat:
        missing_feats = list(range(max_feat + 1, max_draw_db + 1))
        print(f"🧬 상세 특성 업데이트 필요: {missing_feats}")

        for target_round in missing_feats:
            print(f"   Processed Round {target_round} (Features)...")
            
            target_draw = draws_map.get(target_round)
            prev_draw = draws_map.get(target_round - 1)
            
            if not target_draw: continue

            winning_numbers = target_draw['numbers']
            bonus_number = target_draw['bonus']
            prev_numbers = prev_draw['numbers'] if prev_draw else []
            
            draws_before = [d for d in all_draws if d['round'] < target_round]

            features_to_insert = []
            
            for number in range(1, 46):
                # 이웃수 로직
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
                    "is_consecutive": False, 
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
                except Exception as e:
                    print(f"   ❌ 저장 실패: {e}")

    print("\n🎉 모든 업데이트 작업이 성공적으로 완료되었습니다!")

if __name__ == "__main__":
    main()
