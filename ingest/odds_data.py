"""Kursy i linie Superbet (PL) z OddsPapi -> odds.json (bieżące linie) i odds_history.json (ruch linii).

Darmowy plan OddsPapi nie daje historical-odds dla meczów nadchodzących i trwających (tylko dla zakończonych), dlatego:
  - bieżące linie wszystkich meczów NFL pobieramy jednym zapytaniem odds-by-tournaments (awaryjnie, z ODDS_FALLBACK=1, pojedynczo: odds),
  - ruch linii budujemy z własnych pomiarów: przy każdym uruchomieniu dopisujemy pomiar, gdy linia lub kurs się zmieniły
    (etykieta w aplikacji: „od pierwszego pomiaru”),
  - po zakończeniu meczu uzupełniamy pełną historię od otwarcia do zamknięcia z darmowego historical-odds (hist[...]["full"] = True).
Katalog rynków jest zapisywany w ingest/odds_catalog.json (odświeżany co 7 dni), mapa id zawodników w ingest/odds_players.json.
Zużycie limitu: ok. 2 zapytania na uruchomienie (mecze + kursy), plus katalog co tydzień i kursy meczu z nieznanymi zawodnikami.
Uruchamiaj PO build_data.py. Klucz: zmienna ODDSPAPI_KEY. Lokalnie ODDS_CACHE=1 oszczędza limit przy poprawkach."""
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
SLUGS = (BOOK, "superbet")
MAX_CALLS = int(os.environ.get("ODDS_MAX_CALLS", "40"))
DATA = Path(__file__).resolve().parents[1] / "web" / "public" / "data"
MAPFILE = Path(__file__).resolve().parent / "odds_players.json"
CATFILE = Path(__file__).resolve().parent / "odds_catalog.json"
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
    opcjonalnym lokalnym cache (ODDS_CACHE=1, ważny 6 godzin). Błędy zgłasza jako RuntimeError z kodem i opisem z API."""
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
        if not r.ok:
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
    """Nazwisko bez akcentów i znaków specjalnych, małymi literami, bez przyrostków (Jr, Sr, II...), do dopasowania nazw z kursów do zawodników."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def flip(name):  # "Maye, Drake" -> "Drake Maye"
    """Zamienia zapis 'Nazwisko, Imię' na 'Imię Nazwisko'."""
    a, _, b = (name or "").partition(",")
    return f"{b.strip()} {a.strip()}".strip() if b else name


def find(ids, name):
    """Znajduje player_id po nazwisku wśród zawodników drużyn meczu: najpierw dokładne dopasowanie, potem po nazwisku i trzech
    pierwszych literach imienia (Cameron/Cam). Zwraca None, gdy wynik jest niejednoznaczny."""
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
    """Skrót drużyny po nazwie z pola fixture (po słowie-pseudonimie drużyny, np. 'patriots'); None, gdy nie rozpoznano."""
    n = str(name or "").lower()
    return next((a for a, k in NICK.items() if k in n), None)


def best_line(lines, a="Over", b="Under"):
    """Z linii {h: {strona: kurs}} wybiera tę o najbardziej wyrównanych kursach (główną): (h, kurs_a, kurs_b) albo None."""
    c = [(abs(v[a] - v[b]), h, v) for h, v in lines.items() if a in v and b in v]
    if not c:
        return None
    _, h, v = min(c, key=lambda x: x[0])
    return h, v[a], v[b]


def push(lst, row):
    """Dopisuje pomiar [czas, ...wartości] tylko wtedy, gdy wartości różnią się od ostatniego pomiaru."""
    if not lst or lst[-1][1:] != row[1:]:
        lst.append(row)


def timeline(lines, a, b):
    """lines: {linia: {strona: [wpisy]}} z historical-odds -> ([[czas, linia, cena_a, cena_b], ...], czy_rynek_aktywny_teraz).
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
    """Przebieg jednej ceny (np. anytime TD): lista zmian [czas, cena] z aktywnych wpisów i informacja, czy ostatni wpis jest aktywny."""
    rows = []
    for e in sorted(entries, key=lambda e: e["createdAt"]):
        if e["active"] and (not rows or rows[-1][1] != e["price"]):
            rows.append([e["createdAt"], e["price"]])
    last = max(entries, key=lambda e: e["createdAt"]) if entries else None
    return rows, bool(last and last["active"])


def read(path, default):
    """Wczytuje JSON z pliku albo zwraca wartość domyślną, gdy pliku nie ma."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_catalog():
    """Katalog rynków OddsPapi z pliku w repo (odświeżany co 7 dni, żeby oszczędzać limit zapytań)."""
    c = read(CATFILE, None)
    if c and time.time() - c["fetched"] < 7 * 86400:
        return c["markets"]
    markets = call("markets", sportId=14)
    CATFILE.write_text(json.dumps({"fetched": time.time(), "markets": markets}, ensure_ascii=False), encoding="utf-8")
    return markets


# --- wejście: zawodnicy i terminarz z build_data.py oraz mapa id OddsPapi -> nazwiska ---
players = read(DATA / "players.json", [])
games = read(DATA / "schedule.json", [])
by_team = {}
for p in players:
    by_team.setdefault(p["team"], {})[norm(p["name"])] = p["player_id"]
for team, d in read(DATA / "depth.json", {}).items():
    for lst in d.values():
        for x in lst:
            by_team.setdefault(team, {}).setdefault(norm(x["name"]), x["player_id"])
pmap = read(MAPFILE, {})  # id OddsPapi -> "Imię Nazwisko"
hist = read(DATA / "odds_history.json", {})
old_games = read(DATA / "odds.json", {}).get("games", {})
for gid, H in hist.items():  # migracja wpisów ze starszego formatu (bez fixtureId, drużyn i flagi full)
    parts = gid.split("_")
    H.setdefault("away", parts[2] if len(parts) == 4 else None)
    H.setdefault("home", parts[3] if len(parts) == 4 else None)
    H.setdefault("p1", None)
    H.setdefault("p2", None)
    H.setdefault("full", False)
    if not H.get("fixtureId") and gid in old_games:
        H["fixtureId"] = old_games[gid].get("fixtureId")
fid2gid = {h["fixtureId"]: gid for gid, h in hist.items() if h.get("fixtureId")}
all_games = read(DATA / "schedule_all.json", [])  # pełny terminarz sezonu (także rozegrane mecze) - do przypisania zakończonych fixture

# --- lista meczów (od 3 dni wstecz do +8 dni) i katalog rynków ---
today = dt.date.today()
fixtures = call("fixtures", sportId=14, tournamentId=31, **{"from": str(today - dt.timedelta(days=3)), "to": str(today + dt.timedelta(days=8))})
utc = dt.datetime.now(dt.timezone.utc)
fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M")
now_s, started_s, finished_s = fmt(utc), fmt(utc - dt.timedelta(hours=14)), fmt(utc - dt.timedelta(hours=5))
upcoming = sorted((f for f in fixtures if f["startTime"] > started_s), key=lambda f: f["startTime"])
print("mecze do pobrania:", len(upcoming), "| znanych zawodników w mapie:", len(pmap))
catalog = load_catalog()
mname = {m["marketId"]: m["marketName"] for m in catalog}
hand = {m["marketId"]: m.get("handicap") for m in catalog}
oname = {(m["marketId"], o["outcomeId"]): o["outcomeName"] for m in catalog for o in m.get("outcomes", [])}


def collect_now(book):
    """Bieżące ceny bukmachera -> propsy {(nazwisko, statystyka): {linia: {strona: kurs}}} i rynki meczowe {rynek: {linia: {strona: kurs}}}
    (tylko aktywne ceny); zwraca też id zawodników, których nazwisk jeszcze nie znamy. Uczy mapę pmap z pola playerName, jeśli jest."""
    props, gm, unknown = {}, {}, set()
    for mid, m in book.get("markets", {}).items():
        name, h = mname.get(int(mid), ""), hand.get(int(mid))
        for oid, o in m["outcomes"].items():
            side = oname.get((int(mid), int(oid)), "")
            for pid, pr in o["players"].items():
                if not pr.get("active") or pr.get("price") is None:
                    continue
                if pid == "0":
                    if name in GAME:
                        gm.setdefault(GAME[name], {}).setdefault(h, {})[side] = pr["price"]
                elif name in PROPS:
                    if pr.get("playerName") and pid not in pmap:
                        pmap[pid] = flip(pr["playerName"])
                    if pid in pmap:
                        props.setdefault((pmap[pid], PROPS[name]), {}).setdefault(h, {})[side] = pr["price"]
                    else:
                        unknown.add(pid)
    return props, gm, unknown


def collect(book):
    """Jak collect_now, ale dla odpowiedzi historical-odds: zamiast cen są listy wpisów z czasem (createdAt, price, active)."""
    props, gm = {}, {}
    for mid, m in book["markets"].items():
        name, h = mname.get(int(mid), ""), hand.get(int(mid))
        for oid, o in m["outcomes"].items():
            side = oname.get((int(mid), int(oid)), "")
            for pid, ents in o["players"].items():
                if pid == "0":
                    if name in GAME:
                        gm.setdefault(GAME[name], {}).setdefault(h, {})[side] = ents
                elif name in PROPS and pid in pmap:
                    props.setdefault((pmap[pid], PROPS[name]), {}).setdefault(h, {})[side] = ents
    return props, gm


def fetch_boards(fxs):
    """Bieżące kursy Superbet: jedno zapytanie odds-by-tournaments dla wszystkich meczów NFL; w razie błędu (i tylko z ODDS_FALLBACK=1) kursy każdego meczu osobno (odds)."""
    try:
        resp = call("odds-by-tournaments", tournamentIds=31, bookmakers=BOOK)
        return {f["fixtureId"]: f.get("bookmakerOdds") or {} for f in resp}
    except RuntimeError as e:
        print("odds-by-tournaments niedostępne:", e)
    if not os.environ.get("ODDS_FALLBACK"):  # pobieranie pojedyncze kosztuje po 1 zapytaniu na mecz - tylko świadomie
        print("pomijam pobieranie kursów (ustaw ODDS_FALLBACK=1, aby pobrać je pojedynczo: ok. 1 zapytanie na mecz)")
        return {}
    boards = {}
    for fx in fxs:
        try:
            boards[fx["fixtureId"]] = call("odds", fixtureId=fx["fixtureId"]).get("bookmakerOdds") or {}
        except RuntimeError as e:
            print("pomijam mecz", fx.get("participant1Name"), "-", fx.get("participant2Name"), ":", e)
            if "REQUEST_LIMIT_EXCEEDED" in str(e) or "zapytań na uruchomienie" in str(e):
                break
    return boards


def match_game(fx, names):
    """Mecz z terminarza dla fixture: najpierw po zapisanym wcześniej fixtureId, potem po drużynach z nazw uczestników, na końcu po liczbie wspólnych nazwisk zawodników. None, gdy nie ma dopasowania."""
    gid = fid2gid.get(fx["fixtureId"])
    if gid:
        h = hist[gid]
        return {"game_id": gid, "away_team": h["away"], "home_team": h["home"]}
    p1, p2 = team_of(fx.get("participant1Name")), team_of(fx.get("participant2Name"))
    for g in games:  # najpewniejsze: obie drużyny z nazw uczestników zgadzają się z meczem z terminarza
        if p1 and p2 and {p1, p2} == {g["away_team"], g["home_team"]}:
            return g
    scored = [(len(names & (by_team.get(g["away_team"], {}).keys() | by_team.get(g["home_team"], {}).keys())), g) for g in games]
    overlap, g = max(scored, key=lambda x: x[0]) if scored else (0, None)
    return g if overlap >= 3 else None


# --- bieżące linie: odds.json i pomiary do odds_history.json ---
out = {"updated": utc.isoformat(timespec="minutes"), "bookmaker": BOOK, "players": {}, "games": {}}
unmatched, stamp = [], out["updated"]
boards = fetch_boards(upcoming)
for fx in upcoming:
    b = boards.get(fx["fixtureId"], {})
    book = next((b[s] for s in SLUGS if s in b), None)
    if not book:
        if fx["startTime"] > now_s or fx["fixtureId"] not in fid2gid:  # linii jeszcze nie ma albo nie zdążyliśmy ich zapisać przed meczem
            print("brak Superbet na meczu", fx.get("participant1Name"), "-", fx.get("participant2Name"), fx["startTime"])
            continue
        book = {}  # mecz rozpoczęty: rynki wstrzymane, pokażemy ostatnią znaną linię z historii pomiarów
    props, gm, unknown = collect_now(book)
    if unknown and fx["startTime"] > now_s:  # nieznani zawodnicy: jedno zapytanie o kursy meczu zwraca ich nazwiska
        try:
            b2 = call("odds", fixtureId=fx["fixtureId"]).get("bookmakerOdds") or {}
            collect_now(next((b2[s] for s in SLUGS if s in b2), {}))
            props, gm, unknown = collect_now(book)
        except RuntimeError as e:
            print("nie udało się pobrać nazwisk zawodników:", e)
    g = match_game(fx, {norm(n) for n, _ in props})
    if not g:
        print("nie dopasowano meczu do terminarza:", fx.get("participant1Name"), "-", fx.get("participant2Name"), fx["startTime"])
        continue
    gid = g["game_id"]
    ids = {**by_team.get(g["away_team"], {}), **by_team.get(g["home_team"], {})}
    p1, p2 = team_of(fx.get("participant1Name")), team_of(fx.get("participant2Name"))
    H = hist.setdefault(gid, {"fixtureId": fx["fixtureId"], "startTime": fx["startTime"], "away": g["away_team"], "home": g["home_team"],
                              "p1": p1, "p2": p2, "full": False, "players": {}, "game": {}})
    p1, p2 = H.get("p1") or p1, H.get("p2") or p2
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
                push(H["players"].setdefault(pid, {}).setdefault("td", []), [stamp, yes])
                n_ok += 1
        else:
            bl = best_line(lines)
            if bl:
                out["players"].setdefault(pid, {})[stat] = {"line": bl[0], "over": bl[1], "under": bl[2]}
                push(H["players"].setdefault(pid, {}).setdefault(stat, []), [stamp, bl[0], bl[1], bl[2]])
                n_ok += 1
    gl = {"fixtureId": fx["fixtureId"], "startTime": fx["startTime"]}
    tl = best_line(gm.get("total", {}))
    if tl:
        gl["total"] = {"line": tl[0], "over": tl[1], "under": tl[2]}
        push(H["game"].setdefault("total", []), [stamp, tl[0], tl[1], tl[2]])
    if {p1, p2} == {g["away_team"], g["home_team"]}:
        hc = best_line(gm.get("handicap", {}), "1", "2")
        if hc:
            gl["spread"] = {p1: {"line": hc[0], "price": hc[1]}, p2: {"line": -hc[0], "price": hc[2]}}
            push(H["game"].setdefault("spread", {}).setdefault(p1, []), [stamp, hc[0], hc[1]])
            push(H["game"].setdefault("spread", {}).setdefault(p2, []), [stamp, -hc[0], hc[2]])
        w = next((v for v in gm.get("winner", {}).values() if "1" in v and "2" in v), None)
        if w:
            gl["moneyline"] = {p1: w["1"], p2: w["2"]}
            push(H["game"].setdefault("moneyline", {}).setdefault(p1, []), [stamp, w["1"]])
            push(H["game"].setdefault("moneyline", {}).setdefault(p2, []), [stamp, w["2"]])
    elif gm.get("handicap") or gm.get("winner"):
        print("nie rozpoznano drużyn z pól fixture - pomijam spread i moneyline. Klucze:", list(fx))
    out["games"][gid] = gl
    print(f'{g["away_team"]} @ {g["home_team"]}: propsy z linią: {n_ok}, total: {gl.get("total")}')

# --- mecze rozpoczęte: rynki wstrzymane, więc pokazujemy ostatnią znaną linię (zamykającą) z historii pomiarów ---
for gid, gl in out["games"].items():
    H, closed = hist[gid], []
    if H["startTime"] > now_s:
        continue
    for pid, stats in H["players"].items():
        for stat, rows in stats.items():
            if stat not in out["players"].get(pid, {}) and rows:
                r = rows[-1]
                out["players"].setdefault(pid, {})[stat] = ({"yes": r[1], "closed": True} if stat == "td" else
                                                            {"line": r[1], "over": r[2], "under": r[3], "closed": True})
    if "total" not in gl and H["game"].get("total"):
        r = H["game"]["total"][-1]
        gl["total"] = {"line": r[1], "over": r[2], "under": r[3]}
        closed.append("total")
    for key in ("spread", "moneyline"):
        if key not in gl and H["game"].get(key):
            vals = {t: v[-1] for t, v in H["game"][key].items()}
            gl[key] = {t: ({"line": r[1], "price": r[2]} if key == "spread" else r[1]) for t, r in vals.items()}
            closed.append(key)
    if closed:
        gl["closed"] = closed

# --- zapis wyników (przed uzupełnianiem historii, żeby ewentualny błąd nie zniszczył bieżących linii) ---
cutoff = fmt(utc - dt.timedelta(days=21))


def save():
    """Zapisuje mapę zawodników, historię (bez meczów starszych niż 21 dni) i odds.json (tylko gdy są bieżące mecze)."""
    MAPFILE.write_text(json.dumps(pmap, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    keep = {k: v for k, v in hist.items() if v["startTime"] >= cutoff}
    (DATA / "odds_history.json").write_text(json.dumps(keep, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    if out["games"]:
        (DATA / "odds.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


save()


def game_for(fx):
    """Mecz z pełnego terminarza dla zakończonego fixture: obie drużyny z nazw uczestników i data (+/- 1 dzień, bo mecze nocne są następnego dnia UTC)."""
    p1, p2 = team_of(fx.get("participant1Name")), team_of(fx.get("participant2Name"))
    d0 = dt.date.fromisoformat(fx["startTime"][:10])
    for g in all_games:
        if p1 and p2 and {p1, p2} == {g["away_team"], g["home_team"]} and abs((dt.date.fromisoformat(g["gameday"]) - d0).days) <= 1:
            return g, p1, p2
    return None, p1, p2


# --- zakończone mecze: przypisanie do terminarza i pełna historia od otwarcia do zamknięcia z darmowego historical-odds ---
for fx in fixtures:
    if fx["startTime"] > finished_s:
        continue
    g, p1, p2 = game_for(fx)
    if not g:
        continue
    H = hist.setdefault(g["game_id"], {"fixtureId": fx["fixtureId"], "startTime": fx["startTime"], "away": g["away_team"],
                                       "home": g["home_team"], "p1": p1, "p2": p2, "full": False, "players": {}, "game": {}})
    if not H.get("fixtureId"):
        H["fixtureId"] = fx["fixtureId"]
    H["p1"], H["p2"] = H.get("p1") or p1, H.get("p2") or p2
done = 0
for gid, H in sorted(hist.items(), key=lambda kv: kv[1]["startTime"], reverse=True):
    if H.get("full") or not H.get("fixtureId") or not H.get("away") or H["startTime"] > finished_s or done >= 8:
        continue
    try:
        book = (call("historical-odds", fixtureId=H["fixtureId"], bookmakers=BOOK).get("bookmakers") or {}).get(BOOK)
        if not book:
            continue
        props, gm = collect(book)
        ids = {**by_team.get(H["away"], {}), **by_team.get(H["home"], {})}
        hp, gh = {}, {}
        for (pname, stat), lines in props.items():
            pid = find(ids, pname)
            if not pid:
                continue
            if stat == "td":
                ents = next((v.get("Yes") or v.get("1+") for v in lines.values() if v.get("Yes") or v.get("1+")), None)
                rows, _ = timeline_one(ents) if ents else ([], False)
            else:
                rows, _ = timeline(lines, "Over", "Under")
            if rows:
                hp.setdefault(pid, {})[stat] = rows
        tot, _ = timeline(gm.get("total", {}), "Over", "Under")
        if tot:
            gh["total"] = tot
        p1, p2 = H.get("p1"), H.get("p2")
        if {p1, p2} == {H["away"], H["home"]}:
            hc, _ = timeline(gm.get("handicap", {}), "1", "2")
            if hc:
                gh["spread"] = {p1: [[t, h, a] for t, h, a, b in hc], p2: [[t, -h, b] for t, h, a, b in hc]}
            ml, _ = timeline(gm.get("winner", {}), "1", "2")
            if ml:
                gh["moneyline"] = {p1: [[t, a] for t, h, a, b in ml], p2: [[t, b] for t, h, a, b in ml]}
        H["players"], H["game"], H["full"] = hp, gh, True
        done += 1
        print(f"uzupełniono pełną historię meczu {gid}: {len(hp)} zawodników")
    except RuntimeError as e:
        print("historia meczu", gid, "niedostępna:", e)
        if "REQUEST_LIMIT_EXCEEDED" in str(e) or "zapytań na uruchomienie" in str(e):
            break
    except Exception as e:  # błąd w jednym meczu nie przerywa reszty
        print("błąd przetwarzania historii meczu", gid, ":", repr(e))

# --- końcowy zapis i podsumowanie ---
save()
if not out["games"]:
    print("Nie pobrano żadnych bieżących kursów - zostawiam poprzedni odds.json.")
    sys.exit(1)
print(f"zapisano: {len(out['games'])} meczów, {len(out['players'])} zawodników, historia: {len(hist)} meczów; zapytań użytych: {calls}")
if unmatched:
    print("niedopasowani zawodnicy (", len(unmatched), "):", sorted(set(unmatched))[:25])

# --- ranking value: przelicza value.json po każdym odświeżeniu kursów ---
try:
    from value_data import build_value
    build_value(DATA)
except Exception as e:
    print("ranking value pominięty:", e)