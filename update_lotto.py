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

def calculate_ac(numbers):
    """AC값 (산술적 복잡도) 계산"""
    if not numbers or len(numbers) != 6: return 0
    diffs = set()
    sorted_nums = sorted(numbers)
    for i in range(len(sorted_nums)):
        for j in range(i + 1, len(sorted_nums)):
            diffs.add(abs(sorted_nums[i] - sorted_nums[j]))
    return len(diffs) - (len(numbers) - 1)

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

    for i in range(1, 6): # 최대 5회차까지 신규 검색
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

            # 날짜 파싱
            date_element = box.select_one('.date')
            date_text = date_element.text if date_element else ""
            date_match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else ""

            # 번호 파싱
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
            
            # [테이블 1] lotto_draws 저장
            supabase.table("lotto_draws").insert(draw_data).execute()
            print(f"   ✅ {target}회차 원천 데이터 저장 완료")
            
            new_rounds_data.append(draw_data)
            time.sleep(1)
            
        except Exception as e:
            print(f"   ⚠️ 크롤링 에러: {e}")
            break

    # 4. 분석 데이터 생성 (모든 테이블 업데이트)
    if new_rounds_data:
        print(f"\n📈 {len(new_rounds_data)}개 신규 회차 분석 및 테이블 동기화 중...")
        
        # 전체 과거 데이터 로드 (최신순 정렬)
        res_all = supabase.table("lotto_draws").select("*").order("round", desc=True).limit(350).execute()
        past_draws_cache = res_all.data 
        draws_map = {d['round']: d for d in past_draws_cache}

        for new_draw in new_rounds_data:
            current_round = new_draw['round']
            current_numbers = set(new_draw['numbers'])
            draws_before = [d for d in past_draws_cache if d['round'] < current_round]
            
            # 이전 회차 정보 (이월수, 이웃수 계산용)
            prev_draw = draws_map.get(current_round - 1)
            prev_numbers = set(prev_draw['numbers']) if prev_draw else set()

            # --- [A] number_round_stats (신규 테이블) ---
            # --- [B] number_features_by_round (구형 테이블 - hot_cold.html용) ---
            stats_rows = []
            legacy_features_rows = []

            for num in range(1, 46):
                # 공통 통계 계산
                gap = 0
                for d in draws_before:
                    if num in d['numbers']: break
                    gap += 1
                
                freq_5 = sum(1 for d in draws_before[:5] if num in d['numbers'])
                freq_10 = sum(1 for d in draws_before[:10] if num in d['numbers'])
                freq_15 = sum(1 for d in draws_before[:15] if num in d['numbers'])
                freq_20 = sum(1 for d in draws_before[:20] if num in d['numbers'])

                # 회귀 일치 수
                reg_hit_count = 0
                for dist in range(2, 201):
                    src_round = current_round - dist
                    if src_round in draws_map and num in draws_map[src_round]['numbers']:
                        reg_hit_count += 1

                # [A] 데이터 구성
                def get_hc_new(cnt, period):
                    # 신규 로직 기준 (심플)
                    if period == 10: return 'hot' if cnt >= 3 else ('cold' if cnt == 0 else 'warm')
                    return 'warm' # 나머지는 DB에서 계산 안 함 (용량 절약)

                stats_rows.append({
                    "round": current_round,
                    "number": num,
                    "gap": gap,
                    "freq_5": freq_5,
                    "freq_10": freq_10,
                    "freq_15": freq_15,
                    "freq_20": freq_20,
                    "hot_cold_5": get_hot_cold_status_legacy(freq_5, 5),   # 구형 로직 활용
                    "hot_cold_10": get_hot_cold_status_legacy(freq_10, 10),
                    "hot_cold_15": get_hot_cold_status_legacy(freq_15, 15),
                    "hot_cold_20": get_hot_cold_status_legacy(freq_20, 20),
                    "regression_hit_count": reg_hit_count,
                    "is_winner": num in current_numbers
                })

                # [B] 데이터 구성 (hot_cold.html 호환)
                # 이웃수 판별
                is_neighbor = (num - 1 in prev_numbers) or (num + 1 in prev_numbers)
                
                # 쌍둥이 판별 (끝수 같은 번호가 2개 이상) - 간단히 로직 구현
                is_twin = False # (상세 로직은 복잡하여 생략하거나 필요시 추가)

                # 구형 회귀 컬럼들 (regression_2 ... regression_200)
                legacy_reg_data = {}
                for dist in [2, 3, 4, 5, 10, 20, 30, 40, 50, 100, 200]:
                     src_r = current_round - dist
                     legacy_reg_data[f"regression_{dist}"] = (src_r in draws_map and num in draws_map[src_r]['numbers'])

                legacy_features_rows.append({
                    "round": current_round,
                    "number": num,
                    "hot_cold": get_hot_cold_status_legacy(freq_10, 10), # 기본
