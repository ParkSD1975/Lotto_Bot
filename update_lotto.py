import os
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re
import time

# ============================================================
# [헬퍼 함수] 분석용 로직
# ============================================================
def calculate_ac(numbers):
    if not numbers or len(numbers) < 6: return 0
    diffs = set()
    for i in range(len(numbers)):
        for j in range(i + 1, len(numbers)):
            diffs.add(abs(numbers[i] - numbers[j]))
    return len(diffs) - (len(numbers) - 1)

def get_hot_cold_status_basic(count, period):
    if period == 10:
        return 'hot' if count >= 3 else ('cold' if count == 0 else 'warm')
    return 'warm'

def is_twin_number(number):
    return number > 10 and (number % 10 == number // 10)

# ============================================================
# [핵심] 로또 데이터 가져오기 (3중 백업)
# ============================================================
def fetch_lotto_data(target_round):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.dhlottery.co.kr/'
    }

    # 1단계: 동행복권 공식 JSON API (가장 정확하고 안정적)
    try:
        url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={target_round}"
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("returnValue") == "success":
            print(f"✅ [OFFICIAL API] {target_round}회 데이터 확보 성공")
            return {
                "round": target_round,
                "date": data.get("drwNoDate"),
                "numbers": [data[f"drwtNo{i}"] for i in range(1, 7)],
                "bonus": data.get("bnusNo")
            }
    except Exception as e:
        print(f"⚠️ API 시도 실패: {e}")

    # 2단계: Naver 검색 결과 (간소화 페이지 영향 없음)
    try:
        url = f"https://search.naver.com/search.naver?query={target_round}회+로또"
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        container = soup.select_one('.lotto_win_number')
        if container:
            balls = [int(b.text) for b in container.select('.ball')]
            date_text = soup.select_one('.sub_title').text if soup.select_one('.sub_title') else ""
            date_match = re.search(r'(\d{4})[./\-](\d{2})[./\-](\d{2})', date_text)
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else ""
            
            if len(balls) >= 7:
                print(f"✅ [NAVER] {target_round}회 데이터 확보")
                return {"round": target_round, "date": date_str, "numbers": balls[:6], "bonus": balls[6]}
    except Exception as e:
        print(f"⚠️ Naver 시도 실패: {e}")

    # 3단계: Daum 검색 결과
    try:
        url = f"https://search.daum.net/search?w=tot&q={target_round}회+로또"
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        box = soup.select_one('#lottoColl')
        if box:
            balls = [int(b.text) for b in box.select('.ball') if b.text.strip().isdigit()]
            if len(balls) >= 7:
                print(f"✅ [DAUM] {target_round}회 데이터 확보")
                return {"round": target_round, "date": "", "numbers": balls[:6], "bonus": balls[6]}
    except Exception as e:
        print(f"⚠️ Daum 시도 실패: {e}")

    return None

# ============================================================
# 메인 실행 로직
# ============================================================
def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("❌ 환경변수 설정 오류")
        return

    supabase = create_client(url, key)

    # 1. 최신 회차 확인
    res = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
    max_db = res.data[0]['round'] if res.data else 0
    target = max_db + 1

    print(f"🔍 업데이트 대상: {target}회")
    new_data = fetch_lotto_data(target)

    if new_data:
        supabase.table("lotto_draws").upsert(new_data).execute()
        print(f"💾 {target}회 DB 저장 완료")
        max_db = target
    else:
        print("⏳ 아직 데이터가 생성되지 않았거나 모든 경로가 차단되었습니다.")

    # 2. 분석 테이블 업데이트
    # (효율적인 분석을 위해 최근 300회분만 로드)
    all_draws = supabase.table("lotto_draws").select("*").order("round", desc=True).limit(300).execute().data
    draws_map = {d['round']: d for d in all_draws}

    # number_round_stats 동기화
    res_stats = supabase.table("number_round_stats").select("round").order("round", desc=True).limit(1).execute()
    max_stat = res_stats.data[0]['round'] if res_stats.data else 0

    if max_db > max_stat:
        for r in range(max_stat + 1, max_db + 1):
            curr = draws_map.get(r)
            if not curr: continue
            
            print(f"📊 {r}회차 통계 계산 중...")
            curr_nums = set(curr['numbers'])
            prev_draws = [d for d in all_draws if d['round'] < r]
            
            stats_batch = []
            for n in range(1, 46):
                gap = 0
                for pd in prev_draws:
                    if n in pd['numbers']: break
                    gap += 1
                f10 = sum(1 for d in prev_draws[:10] if n in d['numbers'])
                
                stats_batch.append({
                    "round": r, "number": n, "gap": gap, "freq_10": f10,
                    "hot_cold_10": get_hot_cold_status_basic(f10, 10),
                    "is_winner": n in curr_nums
                })
            supabase.table("number_round_stats").insert(stats_batch).execute()

    print("🎉 모든 작업 완료!")

if __name__ == "__main__":
    main()
