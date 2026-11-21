"""Kursy i pełna historia linii Superbet (PL) z OddsPapi (historical-odds).

Zapisuje: web/public/data/odds.json (bieżące linie), web/public/data/odds_history.json (ruch linii od otwarcia rynku)
oraz ingest/odds_players.json (mapa identyfikatorów zawodników OddsPapi -> nazwiska; commitujemy ją).
Uruchamiaj PO build_data.py. Klucz: zmienna ODDSPAPI_KEY. Lokalnie ODDS_CACHE=1 oszczędza limit zapytań.
Zużycie limitu: 2 zapytania (mecze i katalog rynków) + po jednym zapytaniu o kursy dla meczów z nieznanymi zawodnikami; historical-odds jest darmowe
i nie wlicza się do limitu, ale ma osobny limit częstotliwości (min. 5 s między zapytaniami).
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
last_hist = 0.0  # moment ostatniego zapytania historical-odds (API wymaga min. 5 s przerwy między takimi zapytaniami)


def call(path, **params):
    """Zapytanie do OddsPapi z ponawianiem przy 429, licznikiem użytych zapytań (limit na uruchomienie) i
    opcjonalnym lokalnym cache (ODDS_CACHE=1, ważny 6 godzin).
    """
    global calls, last_hist
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
        if path == "historical-odds":  # osobny limit częstotliwości: min. 5 sekund między zapytaniami
            time.sleep(max(0.0, 5.2 - (time.time() - last_hist)))
        r = requests.get(f"{BASE}/{path}", params=params, timeout=300)
        if path == "historical-odds":
            last_hist = time.time()
        if r.status_code == 429:
            err = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
            if err.get("code") == "REQUEST_LIMIT_EXCEEDED":  # miesięczny limit wyczerpany - ponawianie nie pomoże
                raise RuntimeError(f"429 REQUEST_LIMIT_EXCEEDED {err.get('details', '')}")
            time.sleep(err.get("retryMs", 2000) / 1000 + 0.3)
            continue
        if not r.ok:  # pełny opis błędu z odpowiedzi API (kod i szczegóły), a nie sam kod HTTP
            try:
                err = r.json().get("error", {})
            except Exception:
                err = {}
            raise RuntimeError(f"{r.status_code} {err.get('code', '')} {err.get('details') or err.get('message') or r.text[:200]} [{path}]")
        data = r.json()
        if cfile:
            cfile.write_text(json.dumps(data), encoding="utf-8")
        return data
    raise RuntimeError("limit zapytań (429)")


def norm(s):
    """Nazwisko bez akcentów i znaków specjalnych, małymi literami, bez przyrostków (Jr, Sr, II...), do dopasowania
    nazw z kursów do zawodników.
    """
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def flip(name):  # "Maye, Drake" -> "Drake Maye"
    """Zamienia zapis 'Nazwisko, Imię' na 'Imię Nazwisko'."""
    a, _, b = (name or "").partition(",")
    return f"{b.strip()} {a.strip()}".strip() if b else name


def find(ids, name):
    """Znajduje player_id po nazwisku wśród zawodników drużyn meczu: najpierw dokładne dopasowanie, potem po
    nazwisku i trzech pierwszych literach imienia (Cameron/Cam). Zwraca None, gdy wynik jest niejednoznaczny.
    """
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
    """Skrót drużyny po nazwie z pola fixture (po słowie-pseudonimie drużyny, np. 'patriots'); None, gdy nie
    rozpoznano.
    """
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
    """Przebieg jednej ceny (np. anytime TD): lista zmian [czas, cena] z aktywnych wpisów i informacja, czy ostatni
    wpis jest aktywny.
    """
    rows = []
    for e in sorted(entries, key=lambda e: e["createdAt"]):
        if e["active"] and (not rows or rows[-1][1] != e["price"]):
            rows.append([e["createdAt"], e["price"]])
    last = max(entries, key=lambda e: e["createdAt"]) if entries else None
    return rows, bool(last and last["active"])


# --- wejście: zawodnicy i terminarz z build_data.py oraz mapa id OddsPapi -> nazwiska ---
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

# --- lista meczów (od wczoraj do +8 dni) i katalog rynków OddsPapi ---
today = dt.date.today()
fixtures = call("fixtures", sportId=14, tournamentId=31, **{"from": str(today - dt.timedelta(days=1)), "to": str(today + dt.timedelta(days=8))})
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
started = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M")  # mecze rozpoczęte do 14 h temu też (linia zamykająca)
upcoming = sorted((f for f in fixtures if f["startTime"] > started), key=lambda f: f["startTime"])
print("mecze do pobrania:", len(upcoming), "| znanych zawodników w mapie:", len(pmap))
catalog = call("markets", sportId=14)
mname = {m["marketId"]: m["marketName"] for m in catalog}
hand = {m["marketId"]: m.get("handicap") for m in catalog}
oname = {(m["marketId"], o["outcomeId"]): o["outcomeName"] for m in catalog for o in m.get("outcomes", [])}


def collect(book):
    """Rozdziela rynki bukmachera na propsy zawodników {(nazwisko, statystyka): {linia: {strona: wpisy}}} i rynki
    meczowe (total, handicap, zwycięzca); zwraca też identyfikatory zawodników, których nazwisk jeszcze nie
    znamy.
    """
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


# --- pętla po meczach: historia z API -> bieżące linie (odds.json) i pełny ruch linii (odds_history.json) ---
HFILE = DATA / "odds_history.json"
hist = json.loads(HFILE.read_text(encoding="utf-8")) if HFILE.exists() else {}
out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "bookmaker": BOOK, "players": {}, "games": {}}
unmatched = []
for fx in upcoming:
    try:
        resp = call("historical-odds", fixtureId=fx["fixtureId"], bookmakers=BOOK)
        book = (resp.get("bookmakers") or {}).get(BOOK)
        if not book:
            print("brak Superbet na meczu", fx.get("participant1Name"), "-", fx.get("participant2Name"), fx["startTime"])
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
    except RuntimeError as e:  # błąd jednego meczu nie zatrzymuje pozostałych (poza wyczerpanym limitem)
        print("pomijam mecz", fx.get("participant1Name"), "-", fx.get("participant2Name"), fx["startTime"], ":", e)
        if "REQUEST_LIMIT_EXCEEDED" in str(e) or "zapytań na uruchomienie" in str(e):
            break
        continue
    names = {norm(n) for n, _ in props}
    scored = [(len(names & (by_team.get(g["away_team"], {}).keys() | by_team.get(g["home_team"], {}).keys())), g) for g in games]
    overlap, g = max(scored, key=lambda x: x[0])
    if overlap < 3:
        print("nie dopasowano meczu do terminarza:", fx.get("participant1Name"), "-", fx.get("participant2Name"), fx["startTime"], "(wspólnych nazwisk:", overlap, ")")
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
                out["players"].setdefault(pid, {})["td"] = {"yes": rows[-1][1], **({} if live else {"closed": True})}
                n_ok += 1
        else:
            rows, live = timeline(lines, "Over", "Under")
            if rows:
                hp.setdefault(pid, {})[stat] = rows
                out["players"].setdefault(pid, {})[stat] = {"line": rows[-1][1], "over": rows[-1][2], "under": rows[-1][3],
                                                            **({} if live else {"closed": True})}
                n_ok += 1
    gl, gh, closed = {"fixtureId": fx["fixtureId"], "startTime": fx["startTime"]}, {}, []
    tot, live = timeline(gm.get("total", {}), "Over", "Under")
    if tot:
        gh["total"] = tot
        gl["total"] = {"line": tot[-1][1], "over": tot[-1][2], "under": tot[-1][3]}
        if not live:
            closed.append("total")
    p1, p2 = team_of(fx.get("participant1Name")), team_of(fx.get("participant2Name"))
    if {p1, p2} == {g["away_team"], g["home_team"]}:
        hc, live = timeline(gm.get("handicap", {}), "1", "2")
        if hc:
            gh["spread"] = {p1: [[t, h, a] for t, h, a, b in hc], p2: [[t, -h, b] for t, h, a, b in hc]}
            gl["spread"] = {p1: {"line": hc[-1][1], "price": hc[-1][2]}, p2: {"line": -hc[-1][1], "price": hc[-1][3]}}
            if not live:
                closed.append("spread")
        ml, live = timeline(gm.get("winner", {}), "1", "2")
        if ml:
            gh["moneyline"] = {p1: [[t, a] for t, h, a, b in ml], p2: [[t, b] for t, h, a, b in ml]}
            gl["moneyline"] = {p1: ml[-1][2], p2: ml[-1][3]}
            if not live:
                closed.append("moneyline")
    else:
        print("nie rozpoznano drużyn z pól fixture - pomijam spread i moneyline. Klucze:", list(fx))
    if closed:
        gl["closed"] = closed
    out["games"][gid] = gl
    hist[gid] = {"startTime": fx["startTime"], "players": hp, "game": gh}
    print(f'{g["away_team"]} @ {g["home_team"]}: rynków w historii: {len(book["markets"])}, propsy z linią: {n_ok}, zmian linii total: {len(gh.get("total", []))}')

# --- zapis wyników i podsumowanie ---
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

# --- ranking value: przelicza value.json po każdym odświeżeniu kursów ---
try:
    from value_data import build_value
    build_value(DATA)
except Exception as e:
    print("ranking value pominięty:", e)