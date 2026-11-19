"""Red zone i linia bramkowa z play-by-play bieżącego sezonu: udział zawodników w targetach/biegach i TD
oraz skuteczność obron (TD na akcję). Strefy: do 20 jardów od pola punktowego, do 10 i do 5.
Wynik: web/public/data/redzone.json (liczby tygodniowe, okna L3/L5 liczy frontend)."""
import json
from pathlib import Path
import nflreadpy as nfl
import polars as pl


def build_redzone(out: Path, season: int):
    """Z akcji w red zone (do 20 jardów, bez klęknięć, spike'ów i prób na 2 punkty) liczy tygodniowe targety, biegi
    i TD zawodników (strefy do 20/10/5 jardów), sumy drużyn oraz skuteczność obron (akcje i TD z rankingiem).
    Zapisuje redzone.json; okna L3/L5 liczy frontend.
    """
    cols = ["week", "season_type", "posteam", "defteam", "yardline_100", "pass_attempt", "rush_attempt", "receiver_player_id",
            "rusher_player_id", "pass_touchdown", "rush_touchdown", "qb_kneel", "qb_spike", "two_point_attempt"]
    pbp = nfl.load_pbp([season]).select(cols).filter(pl.col("season_type") == "REG")
    pbp = (pbp.with_columns([pl.col(c).fill_null(0) for c in ("pass_attempt", "rush_attempt", "pass_touchdown", "rush_touchdown",
                                                              "qb_kneel", "qb_spike", "two_point_attempt")])
              .filter(pl.col("yardline_100").is_not_null(), pl.col("yardline_100") <= 20,
                      (pl.col("pass_attempt") == 1) | (pl.col("rush_attempt") == 1),
                      pl.col("qb_kneel") != 1, pl.col("qb_spike") != 1, pl.col("two_point_attempt") != 1))
    through = int(pbp["week"].max())
    yl = pl.col("yardline_100")
    num = lambda c: pl.col(c).cast(pl.Int64)
    tg = pbp.filter(pl.col("pass_attempt") == 1, pl.col("receiver_player_id").is_not_null())
    ca = pbp.filter(pl.col("rush_attempt") == 1, pl.col("rusher_player_id").is_not_null())

    def counts(df, keys, td):
        """Grupuje akcje po kluczach i liczy: wszystkie w red zone (n20), do 10 (n10) i do 5 jardów (n5) oraz
        przyłożenia z kolumny td.
        """
        return df.group_by(keys).agg(pl.len().alias("n20"), (yl <= 10).sum().alias("n10"), (yl <= 5).sum().alias("n5"),
                                     num(td).sum().alias("td"))

    players, teams = {}, {}
    for r in counts(tg, ["posteam", "week", "receiver_player_id"], "pass_touchdown").to_dicts():
        g = players.setdefault(r["receiver_player_id"], {"t": r["posteam"], "g": {}})
        g["t"] = r["posteam"]
        a = g["g"].setdefault(r["week"], [0] * 8)
        a[0], a[2], a[4], a[6] = r["n20"], r["n10"], r["n5"], r["td"]
    for r in counts(ca, ["posteam", "week", "rusher_player_id"], "rush_touchdown").to_dicts():
        g = players.setdefault(r["rusher_player_id"], {"t": r["posteam"], "g": {}})
        g["t"] = r["posteam"]
        a = g["g"].setdefault(r["week"], [0] * 8)
        a[1], a[3], a[5], a[7] = r["n20"], r["n10"], r["n5"], r["td"]
    for kind, df, off in (("t", tg, 0), ("c", ca, 1)):
        for r in counts(df, ["posteam", "week"], "pass_touchdown").to_dicts():
            a = teams.setdefault(r["posteam"], {"g": {}})["g"].setdefault(r["week"], [0] * 6)
            a[off], a[off + 2], a[off + 4] = r["n20"], r["n10"], r["n5"]

    def dstats(df, min_plays):
        """Statystyki obron w red zone: liczba podań i biegów, TD oraz rankingi (ogółem, przeciw podaniom, przeciw
        biegom; 1 = najmniej TD na akcję) dla obron z minimalną liczbą akcji.
        """
        d = (df.group_by("defteam").agg((pl.col("pass_attempt") == 1).sum().alias("pa"), (pl.col("rush_attempt") == 1).sum().alias("ra"),
                                        num("pass_touchdown").sum().alias("ptd"), num("rush_touchdown").sum().alias("rtd"))
               .with_columns((pl.col("pa") + pl.col("ra")).alias("n"), ((pl.col("ptd") + pl.col("rtd")) / (pl.col("pa") + pl.col("ra"))).alias("rate"),
                             (pl.col("ptd") / pl.col("pa")).alias("prate"), (pl.col("rtd") / pl.col("ra")).alias("rrate")))
        d = d.filter(pl.col("n") >= min_plays).with_columns(
            pl.col("rate").rank("ordinal").alias("rank_all"), pl.col("prate").rank("ordinal").alias("rank_p"),
            pl.col("rrate").rank("ordinal").alias("rank_r"))
        return {r["defteam"]: {k: r[k] for k in ("pa", "ra", "ptd", "rtd", "rank_all", "rank_p", "rank_r")} for r in d.to_dicts()}

    d20, d5 = dstats(pbp, 15), dstats(pbp.filter(yl <= 5), 8)
    defense = {t: {"z20": d20.get(t), "z5": d5.get(t)} for t in set(d20) | set(d5)}
    (out / "redzone.json").write_text(json.dumps({"meta": {"season": season, "through_week": through}, "teams": teams,
                                                   "players": players, "defense": defense}, separators=(",", ":")))
    print(f"red zone {season} (do tygodnia {through}): {len(players)} zawodników, {len(defense)} obron")