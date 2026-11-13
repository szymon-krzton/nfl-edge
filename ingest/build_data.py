"""Pobiera dane nflverse i zapisuje JSON-y dla frontendu (web/public/data)."""
import json
from pathlib import Path
import nflreadpy as nfl
import polars as pl

SEASONS = [2023, 2024, 2025, 2026]
POS = ["QB", "RB", "WR", "TE"]
TOP = {"QB": 3, "RB": 6, "WR": 9, "TE": 5}  # ilu zawodników na pozycję w depth chart
STAT = ["completions", "attempts", "passing_yards", "passing_tds", "carries",
        "rushing_yards", "targets", "receptions", "receiving_yards", "receiving_tds", "rushing_tds", "passing_interceptions"]
OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "data"
(OUT / "logs").mkdir(parents=True, exist_ok=True)
(OUT / "defense").mkdir(parents=True, exist_ok=True)

frames = []
for s in SEASONS:
    try:
        frames.append(nfl.load_player_stats([s]))
    except Exception as e:  # sezon bez danych
        print("pomijam", s, e)
df = pl.concat(frames, how="diagonal_relaxed")
stats = [c for c in STAT if c in df.columns]
df = (df.filter(pl.col("position").is_in(POS), pl.col("season_type") == "REG")
        .with_columns([pl.col(c).fill_null(0) for c in stats]))
# daty meczów (kolumna "date") z terminarza, dołączane po (sezon, tydzień, drużyna)
_sch = nfl.load_schedules(SEASONS).filter(pl.col("game_type") == "REG").with_columns(pl.col("gameday").cast(pl.Utf8))
gdates = (pl.concat([_sch.select(["season", "week", pl.col("home_team").alias("team"), "gameday"]),
                     _sch.select(["season", "week", pl.col("away_team").alias("team"), "gameday"])])
            .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
df = (df.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
        .join(gdates, on=["season", "week", "team"], how="left").rename({"gameday": "date"}))
print("mecze bez daty:", df.filter(pl.col("date").is_null()).height)
base = ["season", "week", "team", "opponent_team", "position", "player_display_name", "date"]

players = (df.group_by("player_id")
             .agg(pl.col("player_display_name").last().alias("name"),
                  pl.col("position").last().alias("pos"),
                  pl.col("team").last().alias("team"), pl.len().alias("games"))
             .filter(pl.col("games") >= 1).sort("name"))
(OUT / "players.json").write_text(json.dumps(players.to_dicts()))

keep = set(players["player_id"].to_list())
parts = df.filter(pl.col("player_id").is_in(keep)).sort(["season", "week"]).partition_by("player_id", as_dict=True)
for key, g in parts.items():
    pid = key[0] if isinstance(key, tuple) else key
    (OUT / "logs" / f"{pid}.json").write_text(json.dumps(g.select(base + stats).to_dicts()))

cur = df.filter(pl.col("season") == df["season"].max())

# --- historyczna pozycja w depth chartcie: ostatni zapis z nflverse sprzed daty meczu ---
hist_rank = None
try:
    TFIX = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI",
            "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
    cs = int(df["season"].max())
    dch = (nfl.load_depth_charts([cs]).filter(pl.col("position").is_in(POS), pl.col("gsis_id").is_not_null())
             .with_columns(pl.col("team").replace(TFIX), pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64),
                           pl.col("dt").cast(pl.Utf8).alias("dts")))
    sc = nfl.load_schedules([cs]).filter(pl.col("game_type") == "REG").with_columns(pl.col("gameday").cast(pl.Utf8))
    gd = (pl.concat([sc.select(["season", "week", pl.col("home_team").alias("team"), "gameday"]),
                     sc.select(["season", "week", pl.col("away_team").alias("team"), "gameday"])])
            .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    k = ["season", "week", "team"]
    dch = (dch.join(gd, on=k, how="inner").filter(pl.col("dts").str.slice(0, 10) <= pl.col("gameday"))
              .filter(pl.col("dts") == pl.col("dts").max().over(k))
              .sort(["pos_rank", "pos_slot"])
              .unique(subset=k + ["position", "gsis_id"], keep="first", maintain_order=True)
              .with_columns((pl.int_range(pl.len()).over(k + ["position"]) + 1).alias("depth_rank")))
    hist_rank = dch.select(k + ["position", pl.col("gsis_id").alias("player_id"), "depth_rank"])
    print("historyczny depth chart:", hist_rank.height, "rekordów")
except Exception as e:
    print("brak historycznego depth chartu (użyję obecnego):", e)
for team in cur["opponent_team"].unique().to_list():
    sub = cur.filter(pl.col("opponent_team") == team)
    weeks = sorted(sub["week"].unique().to_list())[-8:]
    sub = sub.filter(pl.col("week").is_in(weeks))
    allowed = (sub.group_by(["week", "position"]).agg([pl.col(c).sum() for c in stats])
                  .group_by("position").agg([pl.col(c).mean().round(1) for c in stats]))
    recent = sub.filter((pl.col("attempts") >= 10) | (pl.col("carries") >= 5) | (pl.col("targets") >= 3))
    if hist_rank is not None:
        recent = recent.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)).join(
            hist_rank, on=["season", "week", "team", "position", "player_id"], how="left")
    (OUT / "defense" / f"{team}.json").write_text(json.dumps({
        "allowed": {r["position"]: {c: r[c] for c in stats} for r in allowed.to_dicts()},
        "recent": recent.sort(["week"], descending=True).select(["player_id"] + base + stats + (["depth_rank"] if "depth_rank" in recent.columns else [])).to_dicts()}))

# --- terminarz: najbliższa kolejka ---
season = int(df["season"].max())
sch = (nfl.load_schedules(SEASONS).filter(pl.col("game_type") == "REG")
          .with_columns(pl.col("gameday").cast(pl.Utf8)))
todo = sch.filter(pl.col("home_score").is_null())
games = []
if todo.height:
    s = todo["season"].min()
    w = todo.filter(pl.col("season") == s)["week"].min()
    games = (todo.filter((pl.col("season") == s) & (pl.col("week") == w))
                 .select(["game_id", "season", "week", "gameday", "away_team", "home_team"]).to_dicts())
(OUT / "schedule.json").write_text(json.dumps(games))

# --- statusy: raport kontuzji (OUT / D / Q) i lista rezerwowa kontuzjowanych (IR) ---
LAB = {"out": "OUT", "doubtful": "D", "questionable": "Q"}
status = {}  # gsis_id -> {"status", "injury"}
try:
    inj = nfl.load_injuries([season]).filter(pl.col("season_type") == "REG")
    weeks = inj["week"].unique().to_list()
    wk = games[0]["week"] if games and games[0]["week"] in weeks else inj["week"].max()
    for r in inj.filter(pl.col("week") == wk).to_dicts():
        st = LAB.get(str(r.get("report_status") or "").strip().lower())
        if st and r.get("gsis_id"):
            status[r["gsis_id"]] = {"status": st, "injury": r.get("report_primary_injury") or ""}
    print("raport kontuzji: tydzień", wk, "-", len(status), "zawodników ze statusem")
except Exception as e:
    print("brak raportu kontuzji:", e)
try:
    ros = nfl.load_rosters_weekly([season])
    ros = ros.filter(pl.col("week") == ros["week"].max())
    print("statusy w rosterze (sprawdź, który oznacza IR):", ros["status"].unique().to_list())
    for r in ros.filter(pl.col("status") == "RES").to_dicts():
        status[r["gsis_id"]] = {"status": "IR", "injury": ""}
except Exception as e:
    print("brak rosterów tygodniowych:", e)

# --- ESPN (nieoficjalne API): depth chart i statusy; nadpisują dane nflverse ---
depth_raw = {}
try:
    from espn import fetch_espn
    depth_raw, esp_status = fetch_espn(season, players, TOP)
    status.update(esp_status)
    print("ESPN: depth chart dla", len(depth_raw), "drużyn,", len(esp_status), "statusów")
except Exception as e:
    print("ESPN niedostępny, zostają dane nflverse:", e)

def entry(pid, name, **kw):
    st = status.get(pid, {})
    return {"player_id": pid, "name": name, "status": st.get("status", ""), "injury": st.get("injury", ""), **kw}

# --- depth chart: oficjalny z nflverse, a gdy niedostępny - ranking według użycia z 4 meczów ---
depth = {t: {p: [entry(i, n) for i, n in l] for p, l in d.items()} for t, d in depth_raw.items()}
try:
    if depth:
        raise RuntimeError('ESPN już dostarczył depth chart')
    dc = nfl.load_depth_charts([season]).filter(pl.col("position").is_in(POS))
    dc = dc.filter(pl.col("dt") == pl.col("dt").max().over("team")).sort(["pos_rank", "pos_slot"])
    for team in dc["team"].unique().to_list():
        t = dc.filter(pl.col("team") == team)
        depth[team] = {p: [entry(r["gsis_id"], r["player_name"]) for r in
                           t.filter(pl.col("position") == p).unique(subset=["gsis_id"], keep="first", maintain_order=True)
                            .head(n).to_dicts()] for p, n in TOP.items()}
    print("depth chart: oficjalny,", len(depth), "drużyn")
except Exception as e:
    print("oficjalny depth chart niedostępny:", e)
if not depth:
    usage = (pl.when(pl.col("position") == "QB").then(pl.col("attempts"))
               .when(pl.col("position") == "RB").then(pl.col("carries") + pl.col("targets"))
               .otherwise(pl.col("targets")))
    for team in cur["team"].unique().to_list():
        t = cur.filter(pl.col("team") == team)
        t = t.filter(pl.col("week") > t["week"].max() - 4).with_columns(usage.alias("usage"))
        u = t.group_by("player_id").agg(pl.col("player_display_name").last().alias("name"),
                                        pl.col("position").last().alias("pos"),
                                        pl.col("usage").mean().round(1).alias("usage"))
        depth[team] = {p: [entry(r["player_id"], r["name"], usage=r["usage"]) for r in
                           u.filter(pl.col("pos") == p).sort("usage", descending=True).head(n).to_dicts()]
                       for p, n in TOP.items()}
    print("depth chart: zastępczy (użycie z ostatnich 4 meczów)")
# --- zawodnicy na IR nie są w depth chartach: dopisujemy ich na koniec listy pozycji ---
rows = {r["player_id"]: r for r in players.to_dicts()}
added = []
for pid, st in status.items():
    r = rows.get(pid)
    lst = depth.get(r["team"], {}).get(r["pos"]) if r else None
    if st["status"] == "IR" and lst is not None and all(x["player_id"] != pid for x in lst):
        lst.append(entry(pid, r["name"]))
        added.append(f'{r["team"]}: {r["name"]}')
print("IR dopisani z nflverse:", added)
(OUT / "depth.json").write_text(json.dumps(depth))
print("gotowe:", len(keep), "zawodników,", len(games), "meczów w najbliższej kolejce")

# --- usage: targety i carries w kolejnych meczach drużyn (bieżący sezon) ---
usage_out = {}
for team in cur["team"].unique().to_list():
    t = cur.filter(pl.col("team") == team)
    rows = {}
    for r in t.select(["player_id", "player_display_name", "position", "week", "targets", "carries"]).to_dicts():
        d = rows.setdefault(r["player_id"], {"player_id": r["player_id"], "name": r["player_display_name"],
                                             "pos": r["position"], "g": {}})
        d["g"][r["week"]] = [int(r["targets"] or 0), int(r["carries"] or 0)]
    usage_out[team] = {"weeks": sorted(t["week"].unique().to_list()),
                       "dates": {int(w): d for w, d in zip(t["week"].to_list(), t["date"].to_list())},
                       "players": [p for p in rows.values() if any(v[0] or v[1] for v in p["g"].values())]}
(OUT / "usage.json").write_text(json.dumps(usage_out))
print("usage:", len(usage_out), "drużyn")

# --- coverage i ścieżki (FTN / nflverse); opcjonalne, nie blokuje reszty danych ---
try:
    from coverage_data import build_coverage
    build_coverage(OUT)
except Exception as e:
    print("dane o coverage pominięte:", e)