"""Dane do rankingu value: propsy Superbet (odds.json) połączone z historią wyników zawodników (logs/<id>.json).

Wynik: web/public/data/value.json - dla każdego propsu z aktywną linią: zawodnik, mecz, statystyka, linia, kursy, linia otwarcia
oraz ostatnie 20 wartości statystyki zawodnika (v) i liczba tych z bieżącego sezonu (cs). Trafność, szansę i przewagę liczy
frontend, dzięki czemu okno (L5/L10/L20/sezon) i minimalną próbkę można zmieniać bez ponownego budowania danych.
Uruchamiany na końcu build_data.py i odds_data.py (każdy z nich zmienia jedno z wejść).

Dodatkowo prowadzi automatyczny dziennik modelu (value_log.json): przed meczem zapisuje typy z dodatnim EV (model v1: trafność L10 wygładzona
priorem z kursu), po rozpoczęciu meczu je zamraża, a po meczu rozlicza z logów zawodników i liczy CLV z historii linii. Dzięki temu można
mierzyć kalibrację i zwrot modelu bez ręcznego wpisywania czegokolwiek."""
import datetime as dt
import json
from pathlib import Path

K = 6  # siła priora: tyle fikcyjnych meczów o trafności równej szansie z kursu (jak KPRIOR w aplikacji)

STATS = {"receiving_yards", "receptions", "rushing_yards", "carries", "passing_yards", "passing_tds", "completions", "attempts",
         "passing_interceptions", "td"}
KEEP = 20


def val(row, stat):
    """Wartość statystyki w jednym meczu (td = TD z biegu + TD z odbioru)."""
    if stat == "td":
        return (row.get("rushing_tds") or 0) + (row.get("receiving_tds") or 0)
    return row.get(stat) or 0


def read(path, default):
    """Wczytuje JSON z pliku albo zwraca wartość domyślną, gdy pliku nie ma."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def build_value(out: Path):
    """Buduje value.json z aktywnych linii Superbet i logów zawodników; pomija rynki zamknięte i zawodników bez meczu w terminarzu."""
    odds = read(out / "odds.json", {})
    players = {p["player_id"]: p for p in read(out / "players.json", [])}
    games = read(out / "schedule.json", [])
    hist = read(out / "odds_history.json", {})
    by_team = {}
    for g in games:  # terminarz jest posortowany po dacie: bierzemy najbliższy mecz drużyny
        for side in ("away_team", "home_team"):
            by_team.setdefault(g[side], g)
    props = []
    for pid, stats in odds.get("players", {}).items():
        p = players.get(pid)
        g = by_team.get(p["team"]) if p else None
        rows = read(out / "logs" / f"{pid}.json", [])
        if not g or not rows:
            continue
        opp = g["home_team"] if p["team"] == g["away_team"] else g["away_team"]
        for stat, o in stats.items():
            if stat not in STATS or o.get("closed"):
                continue
            last = rows[-KEEP:]
            first = (hist.get(g["game_id"], {}).get("players", {}).get(pid, {}).get(stat) or [[None, None]])[0]
            props.append({"id": pid, "name": p["name"], "team": p["team"], "opp": opp, "gid": g["game_id"], "pos": p["pos"], "stat": stat,
                          "line": o.get("line"), "over": o.get("over"), "under": o.get("under"), "yes": o.get("yes"),
                          "l0": first[1] if len(first) > 1 and o.get("line") is not None else None,
                          "v": [val(r, stat) for r in last], "cs": sum(1 for r in last if r["season"] == g["season"])})
    meta = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "n": len(props)}
    (out / "value.json").write_text(json.dumps({"meta": meta, "props": props}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"value: {len(props)} propsów z historią")
    update_log(out, props)


def evaluate(pr, win=10, min_n=5):
    """Ocena propsu modelem v1 (jak valueOf w aplikacji): trafność historyczna z ostatnich `win` meczów wygładzona priorem z kursu.
    Zwraca stronę (Over/Under/Yes) o większym EV razem z kursem, szansą z kursu (imp), szacowaną szansą (pe) i EV w procentach; None przy małej próbce."""
    vals = pr["v"][-win:]
    n = len(vals)
    if n < min_n:
        return None
    if pr.get("yes") is not None:
        imp, h = 1 / pr["yes"], sum(1 for x in vals if x > 0)
        pe = (h + K * imp) / (n + K)
        return {"side": "Yes", "odds": pr["yes"], "imp": imp, "pe": pe, "ev": (pe * pr["yes"] - 1) * 100, "n": n, "h": h}
    a, b = 1 / pr["over"], 1 / pr["under"]
    io, iu = a / (a + b), b / (a + b)
    ho, hu = sum(1 for x in vals if x > pr["line"]), sum(1 for x in vals if x < pr["line"])
    po, pu = (ho + K * io) / (n + K), (hu + K * iu) / (n + K)
    o = {"side": "Over", "odds": pr["over"], "imp": io, "pe": po, "ev": (po * pr["over"] - 1) * 100, "n": n, "h": ho}
    u = {"side": "Under", "odds": pr["under"], "imp": iu, "pe": pu, "ev": (pu * pr["under"] - 1) * 100, "n": n, "h": hu}
    return o if o["ev"] >= u["ev"] else u


def settle(p, rows):
    """Wynik typu z logu zawodnika (wiersz sezon/tydzień z gid): W/L/P, wartość statystyki i zysk w jednostkach; None, gdy meczu jeszcze nie ma w logu."""
    season, week = (int(x) for x in p["gid"].split("_")[:2])
    row = next((r for r in rows if r["season"] == season and r["week"] == week), None)
    if row is None:
        return None
    x, line = val(row, p["stat"]), p.get("line")
    if p["side"] == "Yes":
        res = "W" if x > 0 else "L"
    elif p["side"] == "Over":
        res = "W" if x > line else "L" if x < line else "P"
    else:
        res = "W" if x < line else "L" if x > line else "P"
    return {"res": res, "val": x, "profit": round(p["odds"] - 1, 3) if res == "W" else -1 if res == "L" else 0}


def closing(p, hist):
    """Linia zamykająca typu (ostatni zapisany pomiar) i CLV w procentach: kurs typu kontra uczciwy kurs zamykający tej samej linii
    (bez marży; dla anytime TD kurs zamykający wprost). CLV jest None, gdy linia się zmieniła albo nie ma pomiarów."""
    rows = hist.get(p["gid"], {}).get("players", {}).get(p["id"], {}).get(p["stat"])
    if not rows:
        return None
    r = rows[-1]
    if p["side"] == "Yes":
        return {"odds": r[1], "clv": round((p["odds"] / r[1] - 1) * 100, 1)}
    if r[1] != p["line"]:
        return {"line": r[1], "clv": None}
    a, b = 1 / r[2], 1 / r[3]
    pc = (a if p["side"] == "Over" else b) / (a + b)
    return {"line": r[1], "clv": round((p["odds"] * pc - 1) * 100, 1)}


def update_log(out: Path, props, now=None):
    """Aktualizuje value_log.json: (1) przed meczem zapisuje/odświeża typy z dodatnim EV, a te, które przestały go mieć, usuwa;
    (2) po rozpoczęciu meczu wpisy są zamrożone; (3) zamrożone wpisy rozlicza z logów zawodników i liczy CLV z historii linii."""
    now = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
    games = read(out / "odds.json", {}).get("games", {})
    hist = read(out / "odds_history.json", {})
    picks = {p["k"]: p for p in read(out / "value_log.json", {}).get("picks", [])}
    live = set()
    for pr in props:
        start = games.get(pr["gid"], {}).get("startTime")
        e = evaluate(pr)
        if not start or start <= now or not e or e["ev"] <= 0:
            continue
        k = f'{pr["gid"]}|{pr["id"]}|{pr["stat"]}'
        live.add(k)
        picks[k] = {"k": k, "gid": pr["gid"], "id": pr["id"], "name": pr["name"], "pos": pr["pos"], "team": pr["team"], "opp": pr["opp"], "stat": pr["stat"],
                    "side": e["side"], "line": pr["line"], "odds": e["odds"], "imp": round(e["imp"], 4), "pe": round(e["pe"], 4),
                    "ev": round(e["ev"], 1), "n": e["n"], "start": start, "ts": now, "res": None}
    for k in [k for k, p in picks.items() if p["start"] > now and k not in live]:
        del picks[k]  # przed meczem typ przestał spełniać warunek
    for p in picks.values():
        if p["start"] > now:
            continue
        if not p.get("res"):
            s = settle(p, read(out / "logs" / f'{p["id"]}.json', []))
            if s:
                p.update(s)
        if p.get("res") and "clv" not in p:
            c = closing(p, hist)
            if c:
                p["cl"], p["clv"] = c, c["clv"]
    (out / "value_log.json").write_text(json.dumps({"model": "v1: trafność L10 + prior z kursu", "updated": now,
                                                    "picks": sorted(picks.values(), key=lambda p: p["start"], reverse=True)},
                                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"value_log: {len(picks)} typów, rozliczonych: {sum(1 for p in picks.values() if p.get('res'))}")