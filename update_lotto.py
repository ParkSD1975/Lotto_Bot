import os
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
from datetime import datetime

# 환경변수 로드
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("❌ 오류: Supabase 환경변수가 없습니다.")
    exit(1)

supabase = create_client(url, key)

def main():
    # 1. 마지막 회차 조회
    try:
        res = supabase.table("lotto_draws").select("round").order("round", desc=True).limit(1).execute()
        max_round = res.data[0]['round'] if res.data else 0
    except:
        max_round = 0

    print(f"📊 DB 마지막 회차: {max_round}회")

    # 2. 다음 3회차 조회
    for i in range(1, 4):
        target = max_round + i
        print(f"🔍 {target}회차 검색 중...")

        try:
            # 다음(Daum) 검색
            resp = requests.get(f"https://search.daum.net/search?w=tot&q={target}회+로또")
            soup = BeautifulSoup(resp.text, 'html.parser')

            box = soup.select_one('#lottoColl')
            if not box:
                print("   📌 결과 없음")
                break

            balls = [int(b.text) for b in box.select('.ball_lotto')]
            date_text = box.select_one('.date').text

            # 날짜 변환
            import re
            d = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
            date_str = f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else datetime.now().strftime("%Y-%m-%d")

            data = {"round": target, "date": date_str, "numbers": balls[:6], "bonus": balls[6]}

            supabase.table("lotto_draws").insert(data).execute()
            print(f"   ✅ {target}회차 저장 완료!")
            time.sleep(1)

        except Exception:
            print("   ⚠️ 아직 추첨 전이거나 에러")
            break

if __name__ == "__main__":
    main()
