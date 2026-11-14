"""Kursy i pełna historia linii Superbet (PL) z OddsPapi (historical-odds).

Zapisuje: web/public/data/odds.json (bieżące linie), web/public/data/odds_history.json (ruch linii od otwarcia rynku)
oraz ingest/odds_players.json (mapa identyfikatorów zawodników OddsPapi -> nazwiska; commitujemy ją).
Uruchamiaj PO build_data.py. Klucz: zmienna ODDSPAPI_KEY. Lokalnie ODDS_CACHE=1 oszczędza limit zapytań.
Zużycie: ok. 2 + liczba meczów kolejki zapytań; dodatkowo po jednym zapytaniu o kursy dla meczów z nieznanymi zawodnikami.
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
BOOK = "superbet.pl"
MAX_CALLS = int(os.environ.get("ODDS_MAX_CALLS", "40"))
DATA = Path(__file__).resolve().parents[1] / "web" / "public" / "data"
MAPFILE = Path(__file__).resolve().parent / "odds_players.json"
CACHE = Path(__file__).resolve().parent / ".odds_cache"
PROPS = {
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


def timeline(lines, a, b):
    """lines: {linia: {strona: [wpisy]}} -> ([[czas, linia, cena_a, cena_b], ...], czy_rynek_aktywny_teraz).
    W każdej chwili wybieramy aktywną linię o najbardziej wyrównanych kursach (główną)."""
    ev = {(h, s): sorted(v.get(s, []), key=lambda e: e["createdAt"]) for h, v in lines.items() for s in (a, b)}
    times = sorted({e["createdAt"] for lst in ev.values() for e in lst})
    idx, cur, rows, live = {k: 0 for k in ev}, {}, [], False
    for t in times:
        for k, lst in ev.items():
            while idx[k] < len(lst) and lst[idx[k]]["createdAt"] <= t:
                cur[k] = lst[idx[k]]
                idx[k] += 1
        cands = [(abs(cur[(h, a)]["price"] - cur[(h, b)]["price"]), h) for h in lines
                 if (h, a) in cur and (h, b) in cur and cur[(h, a)]["active"] and cur[(h, b)]["active"]]
        live = bool(cands)
        if cands:
            _, h = min(cands, key=lambda c: c[0])
            row = [t, h, cur[(h, a)]["price"], cur[(h, b)]["price"]]
            if not rows or rows[-1][1:] != row[1:]:
                rows.append(row)
    return rows, live


def timeline_one(entries):
    rows = []
    for e in sorted(entries, key=lambda e: e["createdAt"]):
        if e["active"] and (not rows or rows[-1][1] != e["price"]):
            rows.append([e["createdAt"], e["price"]])
    last = max(entries, key=lambda e: e["createdAt"]) if entries else None
    return rows, bool(last and last["active"])


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
pmap = json.loads(MAPFILE.read_text(encoding="utf-8")) if MAPFILE.exists() else {}  # id OddsPapi -> "Imię Nazwisko"

today = dt.date.today()
fixtures = call("fixtures", sportId=14, tournamentId=31, **{"from": str(today), "to": str(today + dt.timedelta(days=8))})
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
upcoming = sorted((f for f in fixtures if f["startTime"] > now), key=lambda f: f["startTime"])
print("mecze do pobrania:", len(upcoming), "| znanych zawodników w mapie:", len(pmap))
catalog = call("markets", sportId=14)
mname = {m["marketId"]: m["marketName"] for m in catalog}
hand = {m["marketId"]: m.get("handicap") for m in catalog}
oname = {(m["marketId"], o["outcomeId"]): o["outcomeName"] for m in catalog for o in m.get("outcomes", [])}


def collect(book):
    props, gm, unknown = {}, {}, set()
    for mid, m in book["markets"].items():
        name, h = mname.get(int(mid), ""), hand.get(int(mid))
        for oid, o in m["outcomes"].items():
            side = oname.get((int(mid), int(oid)), "")
            for pid, ents in o["players"].items():
                if pid == "0":
                    if name in GAME:
                        gm.setdefault(GAME[name], {}).setdefault(h, {})[side] = ents
                elif name in PROPS:
                    if pid in pmap:
                        props.setdefault((pmap[pid], PROPS[name]), {}).setdefault(h, {})[side] = ents
                    else:
                        unknown.add(pid)
    return props, gm, unknown


HFILE = DATA / "odds_history.json"
hist = json.loads(HFILE.read_text(encoding="utf-8")) if HFILE.exists() else {}
out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "bookmaker": BOOK, "players": {}, "games": {}}
unmatched = []
for fx in upcoming:
    try:
        resp = call("historical-odds", fixtureId=fx["fixtureId"], bookmakers=BOOK)
        book = (resp.get("bookmakers") or {}).get(BOOK)
        if not book:
            print("brak Superbet na meczu", fx["fixtureId"], fx["startTime"])
            continue
        props, gm, unknown = collect(book)
        if unknown:  # nieznane id zawodników: jedno zapytanie o kursy daje ich nazwiska
            board = (call("odds", fixtureId=fx["fixtureId"]).get("bookmakerOdds") or {}).get(BOOK) or {}
            for m in board.get("markets", {}).values():
                for o in m["outcomes"].values():
                    for pid, price in o["players"].items():
                        if pid != "0" and price.get("playerName"):
                            pmap[pid] = flip(price["playerName"])
            props, gm, unknown = collect(book)
    except Exception as e:
        print("przerywam pobieranie:", e)
        break
    names = {norm(n) for n, _ in props}
    scored = [(len(names & (by_team.get(g["away_team"], {}).keys() | by_team.get(g["home_team"], {}).keys())), g) for g in games]
    overlap, g = max(scored, key=lambda x: x[0])
    if overlap < 3:
        print("nie dopasowano meczu do terminarza:", fx["fixtureId"], fx["startTime"], "(wspólnych nazwisk:", overlap, ")")
        continue
    gid = g["game_id"]
    ids = {**by_team.get(g["away_team"], {}), **by_team.get(g["home_team"], {})}
    hp, n_ok = {}, 0
    for (pname, stat), lines in props.items():
        pid = find(ids, pname)
        if not pid:
            unmatched.append(pname)
            continue
        if stat == "td":
            ents = next((v.get("Yes") or v.get("1+") for v in lines.values() if v.get("Yes") or v.get("1+")), None)
            rows, live = timeline_one(ents) if ents else ([], False)
            if rows:
                hp.setdefault(pid, {})["td"] = rows
                if live:
                    out["players"].setdefault(pid, {})["td"] = {"yes": rows[-1][1]}
                    n_ok += 1
        else:
            rows, live = timeline(lines, "Over", "Under")
            if rows:
                hp.setdefault(pid, {})[stat] = rows
                if live:
                    out["players"].setdefault(pid, {})[stat] = {"line": rows[-1][1], "over": rows[-1][2], "under": rows[-1][3]}
                    n_ok += 1
    gl, gh = {"fixtureId": fx["fixtureId"], "startTime": fx["startTime"]}, {}
    tot, live = timeline(gm.get("total", {}), "Over", "Under")
    if tot:
        gh["total"] = tot
        if live:
            gl["total"] = {"line": tot[-1][1], "over": tot[-1][2], "under": tot[-1][3]}
    p1, p2 = team_of(fx.get("participant1Name")), team_of(fx.get("participant2Name"))
    if {p1, p2} == {g["away_team"], g["home_team"]}:
        hc, live = timeline(gm.get("handicap", {}), "1", "2")
        if hc:
            gh["spread"] = {p1: [[t, h, a] for t, h, a, b in hc], p2: [[t, -h, b] for t, h, a, b in hc]}
            if live:
                gl["spread"] = {p1: {"line": hc[-1][1], "price": hc[-1][2]}, p2: {"line": -hc[-1][1], "price": hc[-1][3]}}
        ml, live = timeline(gm.get("winner", {}), "1", "2")
        if ml:
            gh["moneyline"] = {p1: [[t, a] for t, h, a, b in ml], p2: [[t, b] for t, h, a, b in ml]}
            if live:
                gl["moneyline"] = {p1: ml[-1][2], p2: ml[-1][3]}
    else:
        print("nie rozpoznano drużyn z pól fixture - pomijam spread i moneyline. Klucze:", list(fx))
    out["games"][gid] = gl
    hist[gid] = {"startTime": fx["startTime"], "players": hp, "game": gh}
    print(f'{g["away_team"]} @ {g["home_team"]}: propsy z aktywną linią: {n_ok}, zmian linii total: {len(gh.get("total", []))}')

MAPFILE.write_text(json.dumps(pmap, ensure_ascii=False, sort_keys=True), encoding="utf-8")
if not out["games"]:
    sys.exit("Nie pobrano żadnych kursów - zostawiam poprzedni odds.json.")
(DATA / "odds.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=21)).strftime("%Y-%m-%dT%H:%M")
hist = {k: v for k, v in hist.items() if v["startTime"] >= cutoff}  # starsze mecze usuwamy
HFILE.write_text(json.dumps(hist, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
print(f"zapisano: {len(out['games'])} meczów, {len(out['players'])} zawodników, historia: {len(hist)} meczów; zapytań użytych: {calls}")
if unmatched:
    print("niedopasowani zawodnicy (", len(unmatched), "):", sorted(set(unmatched))[:25])
print("próbka:", json.dumps(next(iter(out["games"].values())), ensure_ascii=False)[:400])