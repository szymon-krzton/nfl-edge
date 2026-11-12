"""Podgląd surowych odpowiedzi ESPN. Użycie: python ingest/debug_espn.py WSH 2026 Croskey"""
import json
import sys
from espn import get, SITE, CORE

ab = sys.argv[1] if len(sys.argv) > 1 else "WSH"
year = sys.argv[2] if len(sys.argv) > 2 else "2026"
who = sys.argv[3].lower() if len(sys.argv) > 3 else ""
teams = get(f"{SITE}/teams")["sports"][0]["leagues"][0]["teams"]
tid = next(t["team"]["id"] for t in teams if t["team"]["abbreviation"] == ab)
print("team id:", tid)
dc = get(f"{CORE}/seasons/{year}/teams/{tid}/depthcharts") or {}
for item in dc.get("items", []):
    print("GRUPA:", item.get("name"))
    for key, blk in (item.get("positions") or {}).items():
        print("  ", key, [(e.get("rank"), e.get("slot"), (e.get("athlete") or {}).get("$ref", "")[-45:])
                          for e in blk.get("athletes", [])])
inj = get(f"{SITE}/injuries") or {}
print("klucze odpowiedzi injuries:", list(inj.keys()))
for tm in inj.get("injuries", []):
    if str(tm.get("id")) == str(tid):
        print("KONTUZJE DRUŻYNY:", json.dumps(tm, ensure_ascii=False)[:3500])
    for i in tm.get("injuries", []):
        if who and who in json.dumps(i, ensure_ascii=False).lower():
            print("TRAFIENIE dla", who, "->", tm.get("displayName"), json.dumps(i, ensure_ascii=False)[:1500])