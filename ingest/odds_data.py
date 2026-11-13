"""Kursy i linie Superbet (PL) z OddsPapi -> web/public/data/odds.json.

Uruchamiaj PO build_data.py (korzysta z players.json i schedule.json).
Klucz: zmienna środowiskowa ODDSPAPI_KEY (lokalnie) albo sekret ODDSPAPI_KEY (GitHub Actions).
Darmowy limit to ok. 250 zapytań miesięcznie; jedno uruchomienie zużywa ok. 2 + liczba meczów kolejki.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
import requests

KEY = os.environ.get("ODDSPAPI_KEY")
if not KEY:
    sys.exit("Ustaw zmienną środowiskową ODDSPAPI_KEY.")
BASE = "https://api.oddspapi.io/v4"
SLUGS = ("superbet.pl", "superbet")  # pierwszy dostępny i niewstrzymany
MAX_CALLS = int(os.environ.get("ODDS_MAX_CALLS", "25"))
DATA = Path(__file__).resolve().parents[1] / "web" / "public" / "data"
PROPS = {  # nazwa rynku w OddsPapi -> klucz statystyki w aplikacji
    "Over Under Player Receiving Yards (incl. overtime)": "receiving_yards",
    "Over Under Player Receptions (incl. overtime)": "receptions",
    "Over Under Player Rush Yards (incl. overtime)": "rushing_yards",
    "Over Under Player Rush Attempts (incl. overtime)": "carries",
    "Over Under Player Pass Yards (incl. overtime)": "passing_yards",
    "Over Under Player TD Passes (incl. overtime)": "passing_tds",
    "Over Under Player Pass Completions (incl. overtime)": "completions",
    "Over Under Player Pass Attempts (incl. overtime)": "attempts",
    "Over Under Player Interceptions (incl. overtime)": "passing_interceptions",
    "Player To Score TD (incl. overtime)": "td",
}
GAME = {"Total (incl. overtime)": "total", "Handicap (incl. overtime)": "handicap", "Winner (incl. overtime)": "winner"}
NICK = {"ARI": "cardinals", "ATL": "falcons", "BAL": "ravens", "BUF": "bills", "CAR": "panthers", "CHI": "bears",
        "CIN": "bengals", "CLE": "browns", "DAL": "cowboys", "DEN": "broncos", "DET": "lions", "GB": "packers",
        "HOU": "texans", "IND": "colts", "JAX": "jaguars", "KC": "chiefs", "LV": "raiders", "LAC": "chargers",
        "LA": "rams", "MIA": "dolphins", "MIN": "vikings", "NE": "patriots", "NO": "saints", "NYG": "giants",
        "NYJ": "jets", "PHI": "eagles", "PIT": "steelers", "SF": "49ers", "SEA": "seahawks", "TB": "buccaneers",
        "TEN": "titans", "WAS": "commanders"}
CACHE = Path(__file__).resolve().parent / ".odds_cache"  # włącz: ODDS_CACHE=1 (pliki ważne 6 h, nie commituj)
calls = 0


def call(path, **params):
    global calls
    params["apiKey"] = KEY
    cfile = None
    if os.environ.get("ODDS_CACHE"):
        CACHE.mkdir(exist_ok=True)
        h = hashlib.sha1((path + json.dumps({k: str(v) for k, v in params.items() if k != "apiKey"}, sort_keys=True)).encode()).hexdigest()
        cfile = CACHE / f"{h}.json"
        if cfile.exists() and time.time() - cfile.stat().st_mtime < 6 * 3600:
            return json.loads(cfile.read_text(encoding="utf-8"))
    for _ in range(4):
        if calls >= MAX_CALLS:
            raise RuntimeError(f"limit {MAX_CALLS} zapytań na uruchomienie")
        calls += 1
        r = requests.get(f"{BASE}/{path}", params=params, timeout=300)
        if r.status_code == 429:
            time.sleep(r.json().get("error", {}).get("retryMs", 2000) / 1000 + 0.3)
            continue
        r.raise_for_status()
        data = r.json()
        if cfile:
            cfile.write_text(json.dumps(data), encoding="utf-8")
        return data
    raise RuntimeError("limit zapytań (429)")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def flip(name):  # "Maye, Drake" -> "Drake Maye"
    a, _, b = (name or "").partition(",")
    return f"{b.strip()} {a.strip()}".strip() if b else name


def best_line(lines):  # linia o kursach najbliższych sobie (główna)
    c = [(abs(v["Over"] - v["Under"]), h, v) for h, v in lines.items() if "Over" in v and "Under" in v]
    if not c:
        return None
    _, h, v = min(c, key=lambda x: x[0])
    return {"line": h, "over": v["Over"], "under": v["Under"]}


players = json.loads((DATA / "players.json").read_text(encoding="utf-8"))
games = json.loads((DATA / "schedule.json").read_text(encoding="utf-8"))
if not games:
    sys.exit("Brak meczów w schedule.json - uruchom najpierw build_data.py.")
by_team = {}
for p in players:
    by_team.setdefault(p["team"], {})[norm(p["name"])] = p["player_id"]

dfile = DATA / "depth.json"
if dfile.exists():
    for team, d in json.loads(dfile.read_text(encoding="utf-8")).items():
        for lst in d.values():
            for x in lst:
                by_team.setdefault(team, {}).setdefault(norm(x["name"]), x["player_id"])


def find(ids, name):
    n = norm(name)
    if not n:
        return None
    if n in ids:
        return ids[n]
    t = n.split()
    if len(t) < 2:
        return None
    c = set()
    for key, pid in ids.items():
        k = key.split()
        if len(k) > 1 and k[-1] == t[-1] and (k[0].startswith(t[0][:3]) or t[0].startswith(k[0][:3])):
            c.add(pid)
    return c.pop() if len(c) == 1 else None


def team_of(name):
    n = str(name or "").lower()
    return next((a for a, k in NICK.items() if k in n), None)


today = dt.date.today()
fixtures = call("fixtures", sportId=14, tournamentId=31,
                **{"from": str(today), "to": str(today + dt.timedelta(days=8))})
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
upcoming = sorted((f for f in fixtures if f["startTime"] > now), key=lambda f: f["startTime"])
print("mecze do pobrania:", len(upcoming))
catalog = call("markets", sportId=14)
mname = {m["marketId"]: m["marketName"] for m in catalog}
hand = {m["marketId"]: m.get("handicap") for m in catalog}
oname = {(m["marketId"], o["outcomeId"]): o["outcomeName"] for m in catalog for o in m.get("outcomes", [])}

out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "bookmaker": None, "players": {}, "games": {}}
unmatched = []
for fx in upcoming:
    try:
        board = call("odds", fixtureId=fx["fixtureId"]).get("bookmakerOdds") or {}
    except Exception as e:
        print("przerywam pobieranie:", e)
        break
    slug = next((s for s in SLUGS if s in board and not board[s].get("suspended")), None)
    if not slug:
        print("brak Superbet na meczu", fx["fixtureId"], fx["startTime"])
        continue
    props, game = {}, {}
    for mid, market in board[slug]["markets"].items():
        name, h = mname.get(int(mid), ""), hand.get(int(mid))
        for oid, outcome in market["outcomes"].items():
            side = oname.get((int(mid), int(oid)), "")
            for pid, price in outcome["players"].items():
                if not price.get("active") or price.get("price") is None:
                    continue
                if pid == "0":
                    if name in GAME:
                        game.setdefault(GAME[name], {}).setdefault(h, {})[side] = price["price"]
                elif name in PROPS:
                    props.setdefault((flip(price.get("playerName", "")), PROPS[name]), {}).setdefault(h, {})[side] = price["price"]
    names = {norm(n) for n, _ in props}
    scored = [(len(names & (by_team.get(g["away_team"], {}).keys() | by_team.get(g["home_team"], {}).keys())), g) for g in games]
    overlap, g = max(scored, key=lambda x: x[0])
    if overlap < 3:
        print("nie dopasowano meczu do terminarza:", fx["fixtureId"], fx["startTime"], "(wspólnych nazwisk:", overlap, ")")
        continue
    ids = {**by_team.get(g["away_team"], {}), **by_team.get(g["home_team"], {})}
    n_ok = 0
    for (pname, stat), lines in props.items():
        pid = find(ids, pname)
        if not pid:
            unmatched.append(pname)
            continue
        if stat == "td":
            yes = next((v.get("Yes") or v.get("1+") for v in lines.values() if v.get("Yes") or v.get("1+")), None)
            if yes:
                out["players"].setdefault(pid, {})["td"] = {"yes": yes}
                n_ok += 1
        else:
            b = best_line(lines)
            if b:
                out["players"].setdefault(pid, {})[stat] = b
                n_ok += 1
    gl = {"fixtureId": fx["fixtureId"], "startTime": fx["startTime"], "total": best_line(game.get("total", {}))}
    p1, p2 = team_of(fx.get("participant1Name")), team_of(fx.get("participant2Name"))
    if {p1, p2} == {g["away_team"], g["home_team"]}:
        c = [(abs(v["1"] - v["2"]), h, v) for h, v in game.get("handicap", {}).items() if "1" in v and "2" in v and h is not None]
        if c:
            _, h, v = min(c, key=lambda x: x[0])
            gl["spread"] = {p1: {"line": h, "price": v["1"]}, p2: {"line": -h, "price": v["2"]}}
        w = next((v for v in game.get("winner", {}).values() if "1" in v and "2" in v), None)
        if w:
            gl["moneyline"] = {p1: w["1"], p2: w["2"]}
    else:
        print("nie rozpoznano drużyn z pól fixture - pomijam spread i moneyline. Klucze:", list(fx))
    out["games"][g["game_id"]] = gl
    out["bookmaker"] = slug
    print(f'{g["away_team"]} @ {g["home_team"]}: {slug}, dopasowane propsy: {n_ok}, total: {gl["total"]}')

if not out["games"]:
    sys.exit("Nie pobrano żadnych kursów - zostawiam poprzedni odds.json.")
(DATA / "odds.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print(f"zapisano odds.json: {len(out['games'])} meczów, {len(out['players'])} zawodników; zapytań użytych: {calls}")
if unmatched:
    print("niedopasowani zawodnicy (", len(unmatched), "):", sorted(set(unmatched))[:25])
print("próbka:", json.dumps(next(iter(out["games"].values())), ensure_ascii=False)[:500])