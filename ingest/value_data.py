"""Dane do rankingu value: propsy Superbet (odds.json) połączone z historią wyników zawodników (logs/<id>.json).

Wynik: web/public/data/value.json - dla każdego propsu z aktywną linią: zawodnik, mecz, statystyka, linia, kursy, linia otwarcia
oraz ostatnie 20 wartości statystyki zawodnika (v) i liczba tych z bieżącego sezonu (cs). Trafność, szansę i przewagę liczy
frontend, dzięki czemu okno (L5/L10/L20/sezon) i minimalną próbkę można zmieniać bez ponownego budowania danych.
Uruchamiany na końcu build_data.py i odds_data.py (każdy z nich zmienia jedno z wejść)."""
import datetime as dt
import json
from pathlib import Path

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