import os
import requests
from bs4 import BeautifulSoup
from supabase import create_client
import re
from datetime import datetime

# ============================================================
# [헬퍼 함수] 로직 보완
# ============================================================
def get_hot_cold_status_basic(count, period):
    if period == 10:
        return 'hot' if count >= 3 else ('cold' if count == 0 else 'warm')
    return 'warm'

# ============================================================
# [핵심] 로또 데이터 가져오기 (보완된 버전)
# ============================================================
def fetch_lotto_data(target_round):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.dhlottery.co.kr/'
    }
    today_str = datetime.now().strftime('%Y-%m-%d') # 기본값으로 오늘 날짜 준비

    # 1단계: 동행복권 공식 JSON API
    try:
        url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={target_round}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and 'application/json' in resp.headers.get('Content-Type', ''):
            data = resp.json()
            if data.get("returnValue") == "success":
                print(f"✅ [OFFICIAL API] {target_round}회 데이터 확보 성공")
                return {
                    "round": target_round,
                    "date": data.get("drwNoDate", today_str),
                    "numbers": [data[f"drwtNo{i}"] for i in range(1, 7)],
                    "bonus": data.get("bnusNo")
                }
    except Exception as e:
        print(f"⚠️ API 시도 실패 (넘어감): {e}")

    # 2단계: Naver 검색 결과 (간소화 페이지 우회용)
    try:
        url = f"https://search.naver.com/search.naver?query={target_round}회+로또"
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        container = soup.select_one('.lotto_win_number')
        if container:
            balls = [int(b.text) for b in container.select('.ball')]
            date_text = soup.select_one('.sub_title').text if soup.select_one('.sub_title') else ""
            date_match = re.search(r'(\d{4})[./\-](\d{2})[./\-](\d{2})', date_text)
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else today_str
            
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
                # Daum에서 날짜 파싱 실패 대비 오늘 날짜 사용
                return {"round": target_round, "date": today_str, "numbers": balls[:6], "bonus": balls[6]}
    except Exception as e:
        print(f"⚠️ Daum 시도 실패: {e}")

    return None

def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key: return

    supabase = create_client(url, key)

    # 최신 회차 확인
    res = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
    max_db = res.data[0]['round'] if res.data else 0
    target = max_db + 1

    print(f"🔍 업데이트 대상: {target}회")
    new_data = fetch_lotto_data(target)

    if new_data:
        # DB 저장 시 date 값이 비어있지 않은지 한 번 더 체크
        if not new_data.get("date"):
            new_data["date"] = datetime.now().strftime('%Y-%m-%d')

        supabase.table("lotto_draws").upsert(new_data).execute()
        print(f"💾 {target}회 DB 저장 완료")
        max_db = target
    else:
        print("⏳ 로또 데이터를 찾을 수 없습니다.")

    # 분석 데이터 업데이트
    all_draws_res = supabase.table("lotto_draws").select("*").order("round", desc=True).limit(400).execute()
    all_draws = all_draws_res.data
    draws_map = {d['round']: d for d in all_draws}

    res_stats = supabase.table("number_round_stats").select("round").order("round", desc=True).limit(1).execute()
    max_stat = res_stats.data[0]['round'] if res_stats.data else 0

    if max_db > max_stat:
        for r in range(max_stat + 1, max_db + 1):
            curr = draws_map.get(r)
            if not curr: continue
            
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
            print(f"📊 {r}회차 분석 완료")

    print("🎉 모든 업데이트 작업이 완료되었습니다!")

if __name__ == "__main__":
    main()
