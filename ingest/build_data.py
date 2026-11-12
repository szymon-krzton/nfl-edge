"""Pobiera dane nflverse i zapisuje JSON-y dla frontendu (web/public/data)."""
import json
from pathlib import Path
import nflreadpy as nfl
import polars as pl

SEASONS = [2025, 2026]
POS = ["QB", "RB", "WR", "TE"]
STAT = ["completions", "attempts", "passing_yards", "passing_tds", "carries",
        "rushing_yards", "targets", "receptions", "receiving_yards", "receiving_tds"]
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
base = ["season", "week", "team", "opponent_team", "position", "player_display_name"]

players = (df.group_by("player_id")
             .agg(pl.col("player_display_name").last().alias("name"),
                  pl.col("position").last().alias("pos"),
                  pl.col("team").last().alias("team"), pl.len().alias("games"))
             .filter(pl.col("games") >= 6).sort("name"))
(OUT / "players.json").write_text(json.dumps(players.to_dicts()))

keep = set(players["player_id"].to_list())
parts = df.filter(pl.col("player_id").is_in(keep)).sort(["season", "week"]).partition_by("player_id", as_dict=True)
for key, g in parts.items():
    pid = key[0] if isinstance(key, tuple) else key
    (OUT / "logs" / f"{pid}.json").write_text(json.dumps(g.select(base + stats).to_dicts()))

cur = df.filter(pl.col("season") == df["season"].max())
for team in cur["opponent_team"].unique().to_list():
    sub = cur.filter(pl.col("opponent_team") == team)
    weeks = sorted(sub["week"].unique().to_list())[-8:]
    sub = sub.filter(pl.col("week").is_in(weeks))
    allowed = (sub.group_by(["week", "position"]).agg([pl.col(c).sum() for c in stats])
                  .group_by("position").agg([pl.col(c).mean().round(1) for c in stats]))
    recent = sub.filter((pl.col("attempts") >= 10) | (pl.col("carries") >= 5) | (pl.col("targets") >= 3))
    (OUT / "defense" / f"{team}.json").write_text(json.dumps({
        "allowed": {r["position"]: {c: r[c] for c in stats} for r in allowed.to_dicts()},
        "recent": recent.sort(["week"], descending=True).select(base + stats).to_dicts()}))
print("gotowe:", len(keep), "zawodników")
