"""Dane bieżącego sezonu z play-by-play (aktualizowane na bieżąco): strefy targetów (głębokość x strona boiska)
oraz częstotliwość blitzów (FTN charting, publikowany do 48 h po meczu).

Strefa = głębokość podania (air yards) x strona boiska (pass_location). To przybliżenie ścieżek, a nie ich nazwy.
Ranking obrony: 1 = najlepsza (najniższe EPA na target), liczony dla obron z min. 5 targetami w strefie."""
import json
from pathlib import Path
import nflreadpy as nfl
import polars as pl


def build_inseason(out: Path, season: int):
    cols = ["week", "game_id", "play_id", "season_type", "defteam", "qb_dropback", "pass_attempt", "air_yards",
            "pass_location", "receiver_player_id", "complete_pass", "yards_gained", "pass_touchdown", "epa"]
    pbp = nfl.load_pbp([season]).select(cols).filter(pl.col("season_type") == "REG")
    through = int(pbp["week"].max())
    ay = pl.col("air_yards")
    t = (pbp.filter(pl.col("pass_attempt") == 1, pl.col("receiver_player_id").is_not_null(), ay.is_not_null(),
                    pl.col("pass_location").is_not_null())
            .with_columns(pl.col("complete_pass").fill_null(0), pl.col("pass_touchdown").fill_null(0))
            .with_columns(pl.when(ay < 0).then(pl.lit("behind")).when(ay < 10).then(pl.lit("short"))
                            .when(ay < 20).then(pl.lit("mid")).otherwise(pl.lit("deep")).alias("d"),
                          pl.when(pl.col("complete_pass") == 1).then(pl.col("yards_gained")).otherwise(0).alias("yds"))
            .with_columns(pl.concat_str([pl.col("d"), pl.col("pass_location")], separator=":").alias("zone")))
    (out / "inseason" / "players").mkdir(parents=True, exist_ok=True)

    teams = {}
    dz = (t.group_by(["defteam", "zone"])
            .agg(pl.len().alias("targets"), (pl.col("yds").sum() / pl.len()).round(1).alias("ypt"),
                 pl.col("epa").mean().round(2).alias("epa"))
            .filter(pl.col("targets") >= 5)
            .with_columns(pl.col("epa").rank("ordinal").over("zone").alias("rank")))
    for r in dz.to_dicts():
        teams.setdefault(r["defteam"], {"zones": {}})["zones"][r["zone"]] = {k: r[k] for k in ("targets", "ypt", "epa", "rank")}

    try:  # blitz: FTN charting (publikowany do 48 h po meczu)
        ftn = (nfl.load_ftn_charting([season]).select(["nflverse_game_id", "nflverse_play_id", "n_blitzers"])
                 .with_columns(pl.col("nflverse_play_id").cast(pl.Int64)))
        jb = (pbp.filter(pl.col("qb_dropback") == 1).with_columns(pl.col("play_id").cast(pl.Int64))
                 .join(ftn, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "nflverse_play_id"])
                 .filter(pl.col("n_blitzers").is_not_null()))
        bl = (jb.group_by("defteam").agg(pl.len().alias("n"), ((pl.col("n_blitzers") > 0).mean() * 100).round(1).alias("pct"))
                .with_columns(pl.col("pct").rank("ordinal", descending=True).alias("rank")))
        for r in bl.to_dicts():
            teams.setdefault(r["defteam"], {"zones": {}})["blitz"] = {"pct": r["pct"], "rank": r["rank"], "n": r["n"]}
    except Exception as e:
        print("blitz (FTN charting) pominięty:", e)

    (out / "inseason" / "defense.json").write_text(json.dumps({"meta": {"season": season, "through_week": through}, "teams": teams}))
    pz = (t.group_by(["receiver_player_id", "zone"])
            .agg(pl.len().alias("targets"), pl.col("complete_pass").sum().alias("rec"), pl.col("yds").sum().alias("yds"),
                 pl.col("pass_touchdown").sum().alias("td"), pl.col("epa").mean().round(2).alias("epa")))
    P = {}
    for r in pz.to_dicts():
        P.setdefault(r["receiver_player_id"], {"zones": {}})["zones"][r["zone"]] = {k: r[k] for k in ("targets", "rec", "yds", "td", "epa")}
    for pid, d in P.items():
        (out / "inseason" / "players" / f"{pid}.json").write_text(json.dumps(d))
    print(f"bieżący sezon {season} (do tygodnia {through}): {len(teams)} obron, {len(P)} zawodników")