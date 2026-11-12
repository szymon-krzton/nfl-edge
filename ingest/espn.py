"""Depth charty i statusy kontuzji z nieoficjalnego API ESPN (może się zmienić bez uprzedzenia)."""
import re
import time
import unicodedata
import requests
import nflreadpy as nfl

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
FIX = {"WSH": "WAS", "LAR": "LA"}  # skróty ESPN -> skróty nflverse
POS = ("QB", "RB", "WR", "TE")
KEY = re.compile(r"(qb|rb|wr|te)(\d*)")  # ESPN: "wr", ale też "wr1", "wr2", "wr3"
STATUS = {"out": "OUT", "injured reserve": "IR", "questionable": "Q", "doubtful": "D",
          "day-to-day": "DTD", "suspension": "SUSP"}
S = requests.Session()
S.headers["User-Agent"] = "nfl-edge/0.1"


def get(url):
    for i in range(3):
        try:
            r = S.get(url, timeout=15)
            r.raise_for_status()
            time.sleep(0.2)
            return r.json()
        except Exception:
            time.sleep(1 + i)
    return None


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def id_maps(players):
    by_espn = {}
    try:
        for r in nfl.load_ff_playerids().select(["espn_id", "gsis_id"]).drop_nulls().to_dicts():
            by_espn[str(r["espn_id"]).split(".")[0]] = r["gsis_id"]
    except Exception as e:
        print("brak mapy ID ESPN->nflverse, dopasowuję po nazwisku:", e)
    by_name = {(norm(r["name"]), r["team"]): r["player_id"] for r in players.to_dicts()}
    return by_espn, by_name


def pos_of(a):
    p = a.get("position")
    return (p.get("abbreviation") if isinstance(p, dict) else p) or ""


def athlete_id(a):
    """ID zawodnika z linku do jego karty lub z nazwy zdjęcia (id wpisu w raporcie to id kontuzji, a nie zawodnika)."""
    hrefs = [l.get("href", "") for l in (a.get("links") or []) if isinstance(l, dict)]
    h = a.get("headshot")
    hrefs.append(h.get("href", "") if isinstance(h, dict) else str(h or ""))
    for href in hrefs:
        m = re.search(r"/id/(\d+)", href) or re.search(r"/(\d+)\.\w+$", href)
        if m:
            return m.group(1)
    return str(a.get("id") or "")


def fetch_espn(year, players, top):
    """Zwraca (depth, status): depth = {team: {pos: [(player_id, name)]}}, status = {player_id: {...}}."""
    by_espn, by_name = id_maps(players)
    gid = lambda eid, name, team: by_espn.get(str(eid)) or by_name.get((norm(name), team)) or f"espn_{eid}"
    d = get(f"{SITE}/teams") or {}
    teams = {str(t["team"]["id"]): FIX.get(t["team"]["abbreviation"], t["team"]["abbreviation"])
             for t in d["sports"][0]["leagues"][0]["teams"]}
    names, rpos, depth, listed = {}, {}, {}, {}
    for tid, ab in teams.items():
        for g in (get(f"{SITE}/teams/{tid}/roster") or {}).get("athletes", []):
            for a in (g.get("items") or [g]):
                if a.get("id"):
                    names[str(a["id"])] = a.get("displayName") or a.get("fullName") or ""
                    rpos[str(a["id"])] = pos_of(a)
        cand = {p: [] for p in POS}
        items = (get(f"{CORE}/seasons/{year}/teams/{tid}/depthcharts") or {}).get("items", [])
        for gi, item in enumerate(items):
            positions = item.get("positions")
            if not isinstance(positions, dict):
                continue
            for key, blk in positions.items():
                m = KEY.fullmatch(key.lower())
                if not m:
                    continue
                pos, num = m.group(1).upper(), int(m.group(2) or 1)
                for e in blk.get("athletes", []):
                    a = e.get("athlete") or {}
                    mm = re.search(r"/athletes/(\d+)", a.get("$ref", ""))
                    eid = str(a.get("id") or (mm.group(1) if mm else ""))
                    if eid:
                        cand[pos].append((e.get("rank", 99), num, gi, e.get("slot", 99), eid))
        if any(cand.values()):
            lists = {}
            for p in POS:
                seen = []
                for c in sorted(cand[p]):
                    if c[-1] not in seen:
                        seen.append(c[-1])
                lists[p] = seen[:top[p]]
            depth[ab] = {p: [(gid(eid, names.get(eid, ""), ab), names.get(eid) or eid) for eid in l]
                         for p, l in lists.items()}
            listed[ab] = {eid for l in lists.values() for eid in l}
    status = {}
    for tm in (get(f"{SITE}/injuries") or {}).get("injuries", []):
        ab = teams.get(str(tm.get("id")), "")
        for i in tm.get("injuries", []):
            a = i.get("athlete") or {}
            eid = athlete_id(a)
            low = str(i.get("status") or "").strip().lower()
            if not (eid and low) or low == "active":  # ESPN dopisuje też wpisy "Active" zdrowych graczy
                continue
            label = STATUS.get(low, low.upper()[:6])
            text = (i.get("details") or {}).get("type") or (i.get("type") or {}).get("description") or ""
            name = names.get(eid) or a.get("displayName") or eid
            pid = gid(eid, name, ab)
            status[pid] = {"status": label, "injury": text}
            pos = rpos.get(eid) or pos_of(a)
            # depth chart ESPN zawiera tylko aktywnych - zawodników z IR dopisujemy na koniec listy pozycji
            if label == "IR" and ab in depth and pos in POS and eid not in listed[ab]:
                depth[ab][pos].append((pid, name))
                listed[ab].add(eid)
    return depth, status