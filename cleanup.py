import os
from supabase import create_client

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
c = create_client(url, key)

tables_round = ["number_round_stats", "number_features_by_round", "lotto_features", "lotto_draws"]
for t in tables_round:
    try:
        c.table(t).delete().gte("round", 1213).execute()
        print(f"Deleted from {t}")
    except Exception as e:
        print(f"Failed {t}: {e}")

try:
    c.table("regression_details").delete().gte("target_round", 1213).execute()
    print("Deleted from regression_details")
except Exception as e:
    print(f"Failed regression_details: {e}")
