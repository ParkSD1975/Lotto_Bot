import os
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re

# ============================================================
# 상수 정의
# ============================================================
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
DIAGONALS = {1, 9, 17, 25, 33, 41, 7, 13, 19, 31, 37, 43}  # 로또 용지 대각선

# ============================================================
# 계산 함수들 (Edge Function에서 변환)
# ============================================================

def calculate_ac(numbers):
    """AC값 (산술적 복잡도) 계산"""
    if not numbers or len(numbers) != 6:
        return 0
    diffs = set()
    sorted_nums = sorted(numbers)
    for i in range(len(sorted_nums)):
        for j in range(i + 1, len(sorted_nums)):
            diffs.add(abs(sorted_nums[i] - sorted_nums[j]))
    return len(diffs) - (len(numbers) - 1)

def calculate_consecutive(numbers):
    """연번 개수 계산"""
    if not numbers:
        return 0
    count = 0
    sorted_nums = sorted(numbers)
    for i in range(len(sorted_nums) - 1):
        if sorted_nums[i + 1] - sorted_nums[i] == 1:
            count += 1
    return count

def get_prime_count(numbers):
    """소수 개수"""
    return len([n for n in numbers if n in PRIMES])

def get_diagonal_count(numbers):
    """대각선 번호 개수"""
    return len([n for n in numbers if n in DIAGONALS])

def get_multiples_of_3(numbers):
    """3의 배수 개수"""
    return len([n for n in numbers if n % 3 == 0])

def get_color_pattern(numbers):
    """색상 분포 (10단위): 1-10, 11-20, 21-30, 31-40, 41-45"""
    counts = [0, 0, 0, 0, 0]
    for n in numbers:
        if n <= 10:
            counts[0] += 1
        elif n <= 20:
            counts[1] += 1
        elif n <= 30:
            counts[2] += 1
        elif n <= 40:
            counts[3] += 1
        else:
            counts[4] += 1
    return ':'.join(map(str, counts))

def get_zone3_pattern(numbers):
    """3분할 패턴: 1-15, 16-30, 31-45"""
    counts = [0, 0, 0]
    for n in numbers:
        if n <= 15:
            counts[0] += 1
        elif n <= 30:
            counts[1] += 1
        else:
            counts[2] += 1
    return ':'.join(map(str, counts))

def get_quadrant_pattern(numbers):
    """4분면 패턴 (로또 용지 기준): 1-11, 12-23, 24-34, 35-45"""
    counts = [0, 0, 0, 0]
    for n in numbers:
        if n <= 11:
            counts[0] += 1
        elif n <= 23:
            counts[1] += 1
        elif n <= 34:
            counts[2] += 1
        else:
            counts[3] += 1
    return ':'.join(map(str, counts))

def calculate_neighbors(current_numbers, prev_numbers):
    """이웃수 계산 (전회차 번호의 ±1)"""
    if not prev_numbers:
        return 0
    neighbors = set()
    for n in prev_numbers:
        if n - 1 >= 1:
            neighbors.add(n - 1)
        if n + 1 <= 45:
            neighbors.add(n + 1)
    # 전회차 번호 자체는 이웃수에서 제외 (그건 이월수임)
    for n in prev_numbers:
        neighbors.discard(n)
    return len([n for n in current_numbers if n in neighbors])

def get_hot_cold_status(number, recent_draws, period=10):
    """핫/콜드 상태 계산"""
    count = sum(1 for draw in recent_draws[:period] if number in draw['numbers'])
    
    # 기준: period=10일 때 3회 이상=hot, 1-2회=neutral, 0회=cold
    if period == 5:
        if count >= 2:
            return 'hot'
        elif count >= 1:
            return 'neutral'
        else:
            return 'cold'
    elif period == 10:
        if count >= 3:
            return 'hot'
        elif count >= 1:
            return 'neutral'
        else:
            return 'cold'
    elif period == 15:
        if count >= 4:
            return 'hot'
        elif count >= 2:
            return 'neutral'
        else:
            return 'cold'
    else:  # period == 20
        if count >= 5:
            return 'hot'
        elif count >= 2:
            return 'neutral'
        else:
            return 'cold'

def get_appearance_count(number, recent_draws, period):
    """최근 N회 출현 횟수"""
    return sum(1 for draw in recent_draws[:period] if number in draw['numbers'])

def get_missing_count(number, all_draws, current_round):
    """미출현 회차 수 (마지막 출현 이후)"""
    for i, draw in enumerate(all_draws):
        if draw['round'] < current_round and number in draw['numbers']:
            return current_round - draw['round'] - 1
    return current_round - 1  # 한번도 안나왔으면

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
    """쌍둥이 번호 여부 (끝자리가 같은 쌍이 있는 번호)"""
    # 끝자리가 같은 번호들: 1-11-21-31-41, 2-12-22-32-42, ...
    last_digit = number % 10
    twins = [i for i in range(1, 46) if i % 10 == last_digit]
    return len(twins) > 1

# ============================================================
# 메인 함수
# ============================================================

def main():
    # 1. 환경변수 확인
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ 오류: Supabase 환경변수(URL/KEY)가 없습니다.")
        return

    supabase = create_client(url, key)

    # 2. DB에서 기존 데이터 가져오기
    try:
        res = supabase.table("lotto_draws").select("*").order("round", desc=True).execute()
        all_draws = res.data
        max_round = all_draws[0]['round'] if all_draws else 0
    except:
        all_draws = []
        max_round = 0
    
    print(f"📊 현재 DB 마지막 회차: {max_round}회")

    # 3. 사람인 척 위장하기 (헤더 추가)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # 4. 새로운 회차 데이터 가져오기
    new_rounds = []
    for i in range(1, 6):
        target = max_round + i
        print(f"🔍 {target}회차 검색 중 (Daum)...")
        
        try:
            search_url = f"https://search.daum.net/search?w=tot&q={target}회+로또"
            resp = requests.get(search_url, headers=headers)
            soup = BeautifulSoup(resp.text, 'html.parser')

            box = soup.select_one('#lottoColl')
            if not box:
                print(f"   📌 {target}회차 검색 결과가 없습니다.")
                break
            
            text_content = box.text
            if f"{target}회" not in text_content:
                print(f"   ⚠️ 검색 결과가 정확하지 않아 건너뜁니다.")
                break

            date_element = box.select_one('.date')
            date_text = date_element.text if date_element else ""
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            
            if date_match:
                date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            else:
                print("   ⚠️ 날짜를 찾을 수 없습니다.")
                break

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
            
            # lotto_draws 테이블에 저장
            supabase.table("lotto_draws").insert(insert_data).execute()
            print(f"   ✅ {target}회차 ({date_str}) 저장 완료!")
            print(f"      번호: {numbers} + 보너스: {bonus}")
            
            new_rounds.append(insert_data)
            all_draws.insert(0, insert_data)  # 메모리에도 추가
            time.sleep(1)
            
        except Exception as e:
            print(f"   ⚠️ 에러 발생: {e}")
            break

    # 5. 새로운 회차에 대해 number_features_by_round 업데이트
    if new_rounds:
        print(f"\n📈 {len(new_rounds)}개 회차의 번호 특성 계산 중...")
        
        for new_draw in new_rounds:
            target_round = new_draw['round']
            winning_numbers = new_draw['numbers']
            bonus_number = new_draw['bonus']
            
            # 이전 회차 데이터 찾기
            prev_draw = None
            for draw in all_draws:
                if draw['round'] == target_round - 1:
                    prev_draw = draw
                    break
            prev_numbers = prev_draw['numbers'] if prev_draw else []
            
            # 1~45번 각 번호에 대해 특성 계산
            features_to_insert = []
            
            for number in range(1, 46):
                # 출현 횟수 계산 (현재 회차 기준으로 이전 데이터만 사용)
                draws_before = [d for d in all_draws if d['round'] < target_round]
                
                feature = {
                    "round": target_round,
                    "number": number,
                    "hot_cold": get_hot_cold_status(number, draws_before, 10),
                    "appearance_count_5": get_appearance_count(number, draws_before, 5),
                    "appearance_count_10": get_appearance_count(number, draws_before, 10),
                    "appearance_count_15": get_appearance_count(number, draws_before, 15),
                    "appearance_count_20": get_appearance_count(number, draws_before, 20),
                    "is_neighbor": number in [n-1 for n in prev_numbers if n > 1] + [n+1 for n in prev_numbers if n < 45] if prev_numbers else False,
                    "is_consecutive": False,  # 개별 번호 기준으론 계산 불가, 당첨번호 기준으로 나중에 업데이트
                    "is_twin": is_twin_number(number),
                    "missing_count": get_missing_count(number, draws_before, target_round),
                    "last_appearance_round": get_last_appearance_round(number, draws_before, target_round),
                    "is_carryover": number in prev_numbers if prev_numbers else False,
                    "is_winning": number in winning_numbers,
                    "is_bonus": number == bonus_number,
                }
                
                # 회귀 분석 (N회전 당첨 여부)
                for n in [2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100, 150, 200]:
                    feature[f"regression_{n}"] = check_regression(number, draws_before, target_round, n)
                
                features_to_insert.append(feature)
            
            # 배치 삽입
            try:
                supabase.table("number_features_by_round").insert(features_to_insert).execute()
                print(f"   ✅ {target_round}회차 번호 특성 (45개) 저장 완료!")
            except Exception as e:
                print(f"   ⚠️ {target_round}회차 특성 저장 실패: {e}")

    print("\n🎉 모든 작업 완료!")


if __name__ == "__main__":
    main()
