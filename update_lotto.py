import os
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re
from datetime import datetime
import time

# ============================================================
# [헬퍼 함수] 분석용 로직
# ============================================================
def get_hot_cold_status(count, period):
    if period == 5: # 5회차 기준
        if count >= 2: return 'hot'
        if count == 0: return 'cold'
    elif period == 10: # 10회차 기준
        if count >= 3: return 'hot'
        if count == 0: return 'cold' 
    elif period == 15: # 15회차 기준
        if count >= 4: return 'hot'
        if count <= 1: return 'cold'
    elif period == 20: # 20회차 기준
        if count >= 5: return 'hot'
        if count <= 1: return 'cold'
    return 'warm' # 그 외

def is_twin_number(number):
    return number > 10 and (number % 10 == number // 10)

def get_missing_count(number, all_draws, current_round):
    for draw in all_draws:
        if draw['round'] < current_round and number in draw['numbers']:
            return current_round - draw['round'] - 1
    return current_round - 1 # 한번도 안나왔으면 현재회차-1 (1회차부터 미출현)

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
        'Referer': 'https://www.dhlottery.co.kr/',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest'
    }
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"🔍 {target_round}회차 데이터 조회 시도...")

    # 1. API (세션 활용 + AJAX 헤더 → JSON 응답 유도)
    try:
        session = requests.Session()
        session.headers.update(headers)
        # 세션 쿠키 취득 (리다이렉트 방지)
        session.get('https://www.dhlottery.co.kr/', timeout=15)
        url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={target_round}"
        resp = session.get(url, timeout=30)
        ct = resp.headers.get('Content-Type', '')
        if resp.status_code == 200 and 'application/json' in ct:
            data = resp.json()
            if data.get("returnValue") == "success":
                print("   ✅ [API] 데이터 확보 성공")
                return {
                    "round": target_round,
                    "date": data.get("drwNoDate", today_str),
                    "numbers": [data[f"drwtNo{i}"] for i in range(1, 7)],
                    "bonus": data.get("bnusNo")
                }
            elif data.get("returnValue") == "fail":
                # 추첨 전이거나 데이터 미공개 → Naver/Daum 폴백 시도
                print(f"   ⚠️ [API] returnValue=fail → 크롤링 폴백 시도")
        else:
            print(f"   ⚠️ [API] JSON 아님 (Content-Type: {ct[:60]}) → 크롤링 폴백 시도")
    except Exception as e:
        print(f"   ⚠️ [API] 실패: {e}")

    # 2. Naver
    try:
        naver_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        url = f"https://search.naver.com/search.naver?query={target_round}회+로또"
        resp = requests.get(url, headers=naver_headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        container = soup.select_one('.lotto_win_number')
        # 중요: 실제 화면에 표기된 회차가 target_round와 일치하는지 검증
        round_text_el = soup.select_one('a._lotto-btn-current > em')
        if not container:
            print(f"   ⚠️ [Naver] .lotto_win_number 셀렉터 없음 (HTML 구조 변경 가능성)")
        elif not round_text_el:
            print(f"   ⚠️ [Naver] a._lotto-btn-current>em 셀렉터 없음 (HTML 구조 변경 가능성)")
        elif str(target_round) not in round_text_el.text:
            print(f"   ⚠️ [Naver] 회차 불일치: 검색결과='{round_text_el.text.strip()}', 요청={target_round}")
        else:
            balls = [int(b.text) for b in container.select('.ball')]
            date_text = soup.select_one('.sub_title').text if soup.select_one('.sub_title') else ""
            date_match = re.search(r'(\d{4})[./\-](\d{2})[./\-](\d{2})', date_text)
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else today_str
            if len(balls) >= 7:
                print("   ✅ [Naver] 데이터 확보 성공")
                return {"round": target_round, "date": date_str, "numbers": balls[:6], "bonus": balls[6]}
            else:
                print(f"   ⚠️ [Naver] 볼 개수 부족: {len(balls)}개")
    except Exception as e:
        print(f"   ⚠️ [Naver] 실패: {e}")

    # 3. Daum
    try:
        daum_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        url = f"https://search.daum.net/search?w=tot&q={target_round}회+로또"
        resp = requests.get(url, headers=daum_headers, timeout=20)
        soup = BeautifulSoup(resp.text, 'html.parser')
        box = soup.select_one('#lottoColl')
        # 중요: 실제 검색 결과의 회차가 맞는지 검증
        tit_tot = soup.select_one('.tit_tot')
        if not box:
            print(f"   ⚠️ [Daum] #lottoColl 셀렉터 없음 (HTML 구조 변경 가능성)")
        elif not tit_tot:
            print(f"   ⚠️ [Daum] .tit_tot 셀렉터 없음 (HTML 구조 변경 가능성)")
        elif str(target_round) not in tit_tot.text:
            print(f"   ⚠️ [Daum] 회차 불일치: 검색결과='{tit_tot.text.strip()[:30]}', 요청={target_round}")
        else:
            balls = [int(b.text) for b in box.select('.ball') if b.text.strip().isdigit()]
            if len(balls) >= 7:
                print("   ✅ [Daum] 데이터 확보 성공")
                return {"round": target_round, "date": today_str, "numbers": balls[:6], "bonus": balls[6]}
            else:
                print(f"   ⚠️ [Daum] 볼 개수 부족: {len(balls)}개")
    except Exception as e:
        print(f"   ⚠️ [Daum] 실패: {e}")
        
    print(f"   ❌ {target_round}회차 정보 없음")
    return None

def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("❌ Supabase 환경변수 누락")
        return
    supabase = create_client(url, key)

    # ── 재시도 설정 ──
    # 토요일 스케줄 실행 시에만 재시도 (추첨 직후 데이터 미공개 대기용)
    # push/workflow_dispatch 실행 시에는 1회만 시도 (이미 공개된 데이터 수집용)
    event_name = os.environ.get("GITHUB_EVENT_NAME", "push")
    if event_name == "schedule":
        MAX_RETRIES = 6       # 최대 6회 재시도 (토요일 추첨 직후)
        RETRY_INTERVAL = 600  # 10분(600초) 간격
        print(f"⏰ [스케줄 실행] 재시도 모드: 최대 {MAX_RETRIES}회, {RETRY_INTERVAL//60}분 간격")
    else:
        MAX_RETRIES = 1       # 1회만 시도 (push/수동 실행)
        RETRY_INTERVAL = 0
        print(f"🔧 [{event_name} 실행] 단일 시도 모드 (재시도 없음)")

    # 1. 최신 회차 동기화
    res = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
    max_db = res.data[0]['round'] if res.data else 0
    target = max_db + 1

    # 3회차 여유분 체크 (혹시 밀렸을 경우)
    for i in range(3):
        curr_target = target + i
        print(f"\n===== [ {curr_target}회차 작업 시작 ] =====")

        # 첫 번째 신규 회차(i==0)만 재시도 로직 적용
        # 이후 회차(i>0)는 과거 누락 보충이므로 1회만 시도
        retries = MAX_RETRIES if i == 0 else 1
        new_data = None

        for attempt in range(retries):
            new_data = fetch_lotto_data(curr_target)
            if new_data:
                break
            if attempt < retries - 1:
                print(f"   ⏳ [{attempt + 1}/{retries}] {curr_target}회차 데이터 미공개."
                      f" {RETRY_INTERVAL // 60}분 후 재시도... "
                      f"({datetime.now().strftime('%H:%M:%S')})")
                time.sleep(RETRY_INTERVAL)
            else:
                if i == 0:
                    print(f"   ❌ {MAX_RETRIES}회 재시도 후에도 {curr_target}회차 데이터 없음."
                          f" 다음 실행 시 처리됩니다.")
                else:
                    print(f"   🏁 {curr_target}회차 데이터 없음. 이후 회차 없음.")

        if new_data:
            try:
                supabase.table("lotto_draws").upsert(new_data).execute()
                print(f"   💾 lotto_draws {curr_target}회차 저장 완료")
                max_db = curr_target  # 업데이트 성공 시 기준점 이동
            except Exception as e:
                print(f"   ℹ️ 저장 스킵: {e}")
        else:
            if i > 0:
                print("   🏁 더 이상 새로운 회차가 없습니다.")
            break

    # 2. 분석용 데이터 벌크 로드 (과거 500회분 - 분석에 필요)
    print("\n🔄 분석용 과거 데이터 로드 중...")
    all_draws_res = supabase.table("lotto_draws").select("*").order("round", desc=True).limit(500).execute()
    all_draws = all_draws_res.data if all_draws_res.data else []
    draws_map = {d['round']: d for d in all_draws}
    print(f"   ✅ {len(all_draws)}개 회차 데이터 메모리 로드 완료")

    # 3. 테이블별 업데이트 루프 (Stats, Regression, Features)
    # 각 테이블별로 어디까지 업데이트 되었는지 확인하고, max_db까지 채워넣음
    tables = [
        {"name": "number_round_stats", "pk": "round"},
        {"name": "regression_details", "pk": "target_round"},
        {"name": "number_features_by_round", "pk": "round"}
    ]

    for table in tables:
        print(f"\n📊 [{table['name']}] 동기화 점검...")
        res_t = supabase.table(table['name']).select(table['pk']).order(table['pk'], desc=True).limit(1).execute()
        max_t = res_t.data[0][table['pk']] if res_t.data else 0
        
        if max_db > max_t:
            print(f"   👉 {max_t + 1}회 ~ {max_db}회 데이터 생성 필요")
            
            for r in range(max_t + 1, max_db + 1):
                curr = draws_map.get(r)
                if not curr: 
                    print(f"   ⚠️ {r}회차 원본 데이터(lotto_draws)가 메모리에 없음. 건너뜀.")
                    continue
                
                curr_nums = set(curr['numbers'])
                # r회차 이전 데이터들
                prev_draws = [d for d in all_draws if d['round'] < r]
                prev_1 = draws_map.get(r-1)
                
                # A. number_round_stats
                if table['name'] == "number_round_stats":
                    batch = []
                    for n in range(1, 46):
                        gap = 0
                        for pd in prev_draws:
                            if n in pd['numbers']: break
                            gap += 1
                        
                        # 기간별 빈도
                        f5 = sum(1 for d in prev_draws[:5] if n in d['numbers'])
                        f10 = sum(1 for d in prev_draws[:10] if n in d['numbers'])
                        f15 = sum(1 for d in prev_draws[:15] if n in d['numbers'])
                        f20 = sum(1 for d in prev_draws[:20] if n in d['numbers'])

                        # 회귀 적중 (2~200)
                        reg_hit = 0
                        for dist in range(2, 201):
                            if (r-dist) in draws_map and n in draws_map[r-dist]['numbers']:
                                reg_hit += 1
                        
                        batch.append({
                            "round": r, 
                            "number": n, 
                            "gap": gap, 
                            "freq_5": f5,
                            "freq_10": f10,
                            "freq_15": f15,
                            "freq_20": f20,
                            "hot_cold_5": get_hot_cold_status(f5, 5),
                            "hot_cold_10": get_hot_cold_status(f10, 10),
                            "hot_cold_15": get_hot_cold_status(f15, 15),
                            "hot_cold_20": get_hot_cold_status(f20, 20),
                            "regression_hit_count": reg_hit, 
                            "is_winner": n in curr_nums
                        })
                    supabase.table("number_round_stats").insert(batch).execute()

                # B. regression_details
                elif table['name'] == "regression_details":
                    reg_batch = []
                    for dist in range(2, 201):
                        src_r = r - dist
                        if src_r in draws_map:
                            src_nums = draws_map[src_r]['numbers']
                            matches = list(curr_nums.intersection(set(src_nums)))
                            reg_batch.append({
                                "target_round": r, 
                                "regression_distance": dist, 
                                "source_round": src_r, 
                                "source_numbers": src_nums, 
                                "matching_numbers": matches, 
                                "match_count": len(matches)
                            })
                    # 200개 row insert 가 꽤 크므로 나눠서 넣거나 그냥 넣음 (Supabase는 보통 수백개 OK)
                    if reg_batch:
                        supabase.table("regression_details").insert(reg_batch).execute()

                # C. number_features_by_round
                elif table['name'] == "number_features_by_round":
                    feat_batch = []
                    neighbor_set = set()
                    if prev_1:
                        for n in prev_1['numbers']:
                            if n-1>=1: neighbor_set.add(n-1)
                            if n+1<=45: neighbor_set.add(n+1)
                        # 당첨번호 본인은 제외? 보통 이웃수는 본인 제외 양옆. (JS로직 따름)
                        for n in prev_1['numbers']: 
                             if n in neighbor_set: neighbor_set.discard(n)
                    
                    for n in range(1, 46):
                        f = {
                            "round": r, 
                            "number": n, 
                            "hot_cold": get_hot_cold_status(sum(1 for d in prev_draws[:10] if n in d['numbers']), 10),
                            "appearance_count_5": sum(1 for d in prev_draws[:5] if n in d['numbers']),
                            "appearance_count_10": sum(1 for d in prev_draws[:10] if n in d['numbers']),
                            "is_neighbor": n in neighbor_set, 
                            "is_twin": is_twin_number(n),
                            "missing_count": get_missing_count(n, prev_draws, r), 
                            "is_carryover": n in (set(prev_1['numbers']) if prev_1 else set()),
                            "is_winning": n in curr_nums, 
                            "is_bonus": n == curr['bonus']
                        }
                        # 주요 회귀선 여부
                        for dist in [2, 3, 4, 5, 10, 20, 50, 100]: 
                            f[f"regression_{dist}"] = (r-dist) in draws_map and n in draws_map[r-dist]['numbers']
                        
                        feat_batch.append(f)
                    supabase.table("number_features_by_round").insert(feat_batch).execute()
                
                print(f"      ✅ {r}회차 데이터 생성 완료")
        else:
            print("   ✨ 최신 상태입니다.")

    print("\n🎉 모든 분석 동기화가 완료되었습니다!")

if __name__ == "__main__":
    main()