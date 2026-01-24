"""
누락된 회차의 number_features_by_round 데이터를 채우는 보정 스크립트
"""
import os
from supabase import create_client

# ============================================================
# 상수 정의
# ============================================================
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
DIAGONALS = {1, 9, 17, 25, 33, 41, 7, 13, 19, 31, 37, 43}

# ============================================================
# 계산 함수들
# ============================================================

def get_hot_cold_status(number, recent_draws, period=10):
    """핫/콜드 상태 계산"""
    count = sum(1 for draw in recent_draws[:period] if number in draw['numbers'])
    if count >= 3:
        return 'hot'
    elif count >= 1:
        return 'neutral'
    else:
        return 'cold'

def get_appearance_count(number, recent_draws, period):
    """최근 N회 출현 횟수"""
    return sum(1 for draw in recent_draws[:period] if number in draw['numbers'])

def get_missing_count(number, all_draws, current_round):
    """미출현 회차 수"""
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
    """N회전 당첨 여부"""
    target_round = current_round - n_back
    for draw in all_draws:
        if draw['round'] == target_round:
            return number in draw['numbers']
    return False

def is_twin_number(number):
    """쌍둥이 번호 여부"""
    last_digit = number % 10
    twins = [i for i in range(1, 46) if i % 10 == last_digit]
    return len(twins) > 1

# ============================================================
# 메인 함수
# ============================================================

def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ 오류: Supabase 환경변수(URL/KEY)가 없습니다.")
        return

    supabase = create_client(url, key)

    # 1. 모든 lotto_draws 가져오기
    print("📊 lotto_draws 데이터 로딩 중...")
    res = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
    all_draws = res.data
    max_draw_round = all_draws[0]['round'] if all_draws else 0
    print(f"   lotto_draws 최대 회차: {max_draw_round}")

    # 2. number_features_by_round의 최대 회차 확인
    print("📊 number_features_by_round 데이터 확인 중...")
    res2 = supabase.table("number_features_by_round").select("round").order("round", desc=True).limit(1).execute()
    max_features_round = res2.data[0]['round'] if res2.data else 0
    print(f"   number_features_by_round 최대 회차: {max_features_round}")

    # 3. 누락된 회차 계산
    missing_rounds = list(range(max_features_round + 1, max_draw_round + 1))
    
    if not missing_rounds:
        print("✅ 누락된 회차가 없습니다!")
        return
    
    print(f"\n⚠️ 누락된 회차: {missing_rounds}")
    print(f"📈 {len(missing_rounds)}개 회차의 번호 특성 계산 시작...\n")

    # 4. 누락된 회차에 대해 특성 계산
    for target_round in missing_rounds:
        print(f"🔄 {target_round}회차 처리 중...")
        
        # 해당 회차의 당첨번호 찾기
        target_draw = None
        for draw in all_draws:
            if draw['round'] == target_round:
                target_draw = draw
                break
        
        if not target_draw:
            print(f"   ⚠️ {target_round}회차 당첨번호를 찾을 수 없습니다.")
            continue
        
        winning_numbers = target_draw['numbers']
        bonus_number = target_draw['bonus']
        
        # 이전 회차 번호 찾기
        prev_draw = None
        for draw in all_draws:
            if draw['round'] == target_round - 1:
                prev_draw = draw
                break
        prev_numbers = prev_draw['numbers'] if prev_draw else []
        
        # 현재 회차 기준으로 이전 데이터만 필터링
        draws_before = sorted([d for d in all_draws if d['round'] < target_round], 
                             key=lambda x: x['round'], reverse=True)
        
        # 1~45번 각 번호에 대해 특성 계산
        features_to_insert = []
        
        for number in range(1, 46):
            # 이웃수 계산
            neighbor_set = set()
            if prev_numbers:
                for n in prev_numbers:
                    if n - 1 >= 1:
                        neighbor_set.add(n - 1)
                    if n + 1 <= 45:
                        neighbor_set.add(n + 1)
                # 전회차 번호 자체는 제외
                for n in prev_numbers:
                    neighbor_set.discard(n)
            
            feature = {
                "round": target_round,
                "number": number,
                "hot_cold": get_hot_cold_status(number, draws_before, 10),
                "appearance_count_5": get_appearance_count(number, draws_before, 5),
                "appearance_count_10": get_appearance_count(number, draws_before, 10),
                "appearance_count_15": get_appearance_count(number, draws_before, 15),
                "appearance_count_20": get_appearance_count(number, draws_before, 20),
                "is_neighbor": number in neighbor_set,
                "is_consecutive": False,
                "is_twin": is_twin_number(number),
                "missing_count": get_missing_count(number, draws_before, target_round),
                "last_appearance_round": get_last_appearance_round(number, draws_before, target_round),
                "is_carryover": number in prev_numbers if prev_numbers else False,
                "is_winning": number in winning_numbers,
                "is_bonus": number == bonus_number,
            }
            
            # 회귀 분석
            for n in [2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100, 150, 200]:
                feature[f"regression_{n}"] = check_regression(number, draws_before, target_round, n)
            
            features_to_insert.append(feature)
        
        # 배치 삽입
        try:
            supabase.table("number_features_by_round").insert(features_to_insert).execute()
            print(f"   ✅ {target_round}회차 번호 특성 (45개) 저장 완료!")
        except Exception as e:
            print(f"   ❌ {target_round}회차 특성 저장 실패: {e}")

    print("\n🎉 보정 작업 완료!")


if __name__ == "__main__":
    main()
