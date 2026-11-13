"""Coverage (man/zone, Cover 0/1/2/3/4/6) i ścieżki z danych FTN w nflverse (participation + pbp)."""
import json
from pathlib import Path
import nflreadpy as nfl
import polars as pl

MAIN = ["COVER_0", "COVER_1", "COVER_2", "2_MAN", "COVER_3", "COVER_4", "COVER_6"]


def build_coverage(out: Path):
    parts, seasons = [], []
    for s in (2023, 2024, 2025, 2026):
        try:
            p = nfl.load_participation([s])
            if p.height:
                parts.append(p)
                seasons.append(s)
        except Exception as e:
            print("participation", s, "niedostępne:", e)
    if not parts:
        raise RuntimeError("brak danych participation")
    part = pl.concat(parts, how="diagonal_relaxed")
    for c in ("defense_man_zone_type", "defense_coverage_type", "route"):
        if c not in part.columns:
            part = part.with_columns(pl.lit(None, dtype=pl.Utf8).alias(c))
    part = (part.select(["nflverse_game_id", "play_id", "defense_man_zone_type", "defense_coverage_type", "route"])
                .with_columns(pl.col("play_id").cast(pl.Int64)))
    cols = ["game_id", "play_id", "season", "defteam", "passer_player_id", "receiver_player_id", "pass_attempt",
            "complete_pass", "yards_gained", "pass_touchdown", "interception", "epa", "qb_dropback"]
    pbp = (nfl.load_pbp(seasons).select(cols).filter(pl.col("qb_dropback") == 1)
              .with_columns(pl.col("play_id").cast(pl.Int64)))
    j = pbp.join(part, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="inner")
    print("coverage: dopasowane dropbacki:", j.height, "sezony:", seasons)

    dct = pl.col("defense_coverage_type")
    mzt = pl.col("defense_man_zone_type").str.to_uppercase()
    j = j.with_columns(
        [pl.col(c).fill_null(0) for c in ("pass_attempt", "complete_pass", "pass_touchdown", "interception")]
    ).with_columns(
        pl.when(dct.is_in(MAIN)).then(dct).when(dct.is_not_null()).then(pl.lit("OTHER")).alias("cov"),
        pl.when(mzt.str.contains("ZONE")).then(pl.lit("ZONE")).when(mzt.str.contains("MAN")).then(pl.lit("MAN")).alias("mz"),
        pl.when(pl.col("complete_pass") == 1).then(pl.col("yards_gained")).otherwise(0).alias("yds"),
    )
    long = pl.concat([j.filter(pl.col("cov").is_not_null()).with_columns(pl.col("cov").alias("split")),
                      j.filter(pl.col("mz").is_not_null()).with_columns(pl.col("mz").alias("split"))])
    tg = j.filter(pl.col("receiver_player_id").is_not_null(), pl.col("pass_attempt") == 1)
    tgl = long.filter(pl.col("receiver_player_id").is_not_null(), pl.col("pass_attempt") == 1)
    last = max(seasons)  # profil obrony: najnowszy sezon z danymi
    (out / "coverage" / "players").mkdir(parents=True, exist_ok=True)

    # --- obrony: użycie coverage (% dropbacków) i ranking przeciw ścieżkom ---
    teams = {}
    for col in ("cov", "mz"):
        g = (j.filter(pl.col("season") == last, pl.col(col).is_not_null()).group_by(["defteam", col]).len()
              .with_columns((pl.col("len") / pl.col("len").sum().over("defteam") * 100).round(1).alias("pct")))
        for r in g.to_dicts():
            teams.setdefault(r["defteam"], {"usage": {}, "routes": {}})["usage"][r[col]] = r["pct"]
    dr = (tg.filter(pl.col("route").is_not_null(), pl.col("season") == last).group_by(["defteam", "route"])
            .agg(pl.len().alias("targets"), (pl.col("yds").sum() / pl.len()).round(1).alias("ypt"),
                 pl.col("epa").mean().round(2).alias("epa"))
            .with_columns(pl.col("epa").rank("ordinal").over("route").alias("rank")))  # 1 = najlepsza obrona
    for r in dr.to_dicts():
        teams.setdefault(r["defteam"], {"usage": {}, "routes": {}})["routes"][r["route"]] = {
            k: r[k] for k in ("targets", "ypt", "epa", "rank")}
    (out / "coverage" / "defense.json").write_text(json.dumps(
        {"meta": {"seasons": seasons, "def_season": last}, "teams": teams}))

    # --- zawodnicy: ścieżki przy targetach, statystyki vs coverage (odbiorcy) i QB ---
    P = lambda pid: players_out.setdefault(pid, {"routes": {}, "cov": {}, "pass": {}})
    players_out = {}
    pr = (tg.filter(pl.col("route").is_not_null()).group_by(["receiver_player_id", "route"]).len()
            .rename({"len": "targets"})
            .with_columns((pl.col("targets") / pl.col("targets").sum().over("receiver_player_id") * 100).round(1).alias("share")))
    for r in pr.to_dicts():
        P(r["receiver_player_id"])["routes"][r["route"]] = {"targets": r["targets"], "share": r["share"]}
    rc = tgl.group_by(["receiver_player_id", "split"]).agg(
        pl.len().alias("targets"), pl.col("complete_pass").sum().alias("rec"), pl.col("yds").sum().alias("yds"),
        pl.col("pass_touchdown").sum().alias("td"), pl.col("epa").mean().round(2).alias("epa"))
    for r in rc.to_dicts():
        P(r["receiver_player_id"])["cov"][r["split"]] = {k: r[k] for k in ("targets", "rec", "yds", "td", "epa")}
    qb = long.filter(pl.col("passer_player_id").is_not_null()).group_by(["passer_player_id", "split"]).agg(
        pl.len().alias("dropbacks"), pl.col("pass_attempt").sum().alias("att"), pl.col("complete_pass").sum().alias("cmp"),
        pl.col("yds").sum().alias("yds"), pl.col("pass_touchdown").sum().alias("td"),
        pl.col("interception").sum().alias("int"), pl.col("epa").mean().round(2).alias("epa"))
    for r in qb.to_dicts():
        P(r["passer_player_id"])["pass"][r["split"]] = {k: r[k] for k in ("dropbacks", "att", "cmp", "yds", "td", "int", "epa")}
    for pid, d in players_out.items():
        (out / "coverage" / "players" / f"{pid}.json").write_text(json.dumps(d))
    print("coverage: gotowe,", len(teams), "obron,", len(players_out), "zawodników")