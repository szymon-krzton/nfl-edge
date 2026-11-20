"""Agregacja zaimportowanych meczów Gridiris (ingest/gridiris/*.json) do plików dla aplikacji.

Wejście:  ingest/gridiris/<sezon>_<tydzień>_<wyjazd>_<dom>.json (tworzy je gridiris_import.py).
Wyjście:  web/public/data/gridiris/defenders.json        - obrońcy: kogo kryją, wyniki i separacja (CB kontra WR)
          web/public/data/gridiris/defense.json            - obrony: użycie krycia (est.), oddane jardy wg alignment i ścieżek + rankingi
          web/public/data/gridiris/players/<gsis_id>.json  - zawodnicy: alignment, ścieżki, wyniki wg krycia, udział w trasach, obrońcy (cb)
Liczone jest tylko najnowszy sezon z zaimportowanych plików (od początku sezonu do ostatniego zaimportowanego meczu).
Skróty: n = snapy w podaniach, r = ścieżki (bez bloków), t = targety, rec = przyjęcia, yds = jardy, td = przyłożenia,
so = suma separacji na targetach, no = liczba pomiarów separacji."""
import json
import re
import unicodedata
from pathlib import Path

MAN = {"Cover 0", "Cover 1", "2-Man"}
ZONE = {"Cover 2", "Cover 3", "Cover 4", "Cover 6"}
MIN_ROUTES = 15  # minimalna liczba ścieżek, by obrona dostała ranking w danej komórce
MIN_TEAMS = 8  # minimalna liczba obron z próbką, by w ogóle liczyć ranking


def norm(s):
    """Nazwisko bez akcentów, znaków specjalnych i przyrostków (Jr, Sr, II...), małymi literami."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def split_name(name):
    """'J.Lane' -> ('j', 'lane'); 'A.St. Brown' -> ('a', 'st brown')."""
    m = re.match(r"^\s*([A-Za-z])\.?\s*(.*)$", name or "")
    return (m.group(1).lower(), norm(m.group(2))) if m else ("", norm(name))


def load_roster(season):
    """Składy tygodniowe nflverse: (drużyna, tydzień, numer) -> (gsis_id, pełne nazwisko, pozycja). Przy braku danych zwraca pusty słownik."""
    try:
        import nflreadpy as nfl
        r = nfl.load_rosters_weekly([season]).select(["team", "week", "jersey_number", "gsis_id", "full_name", "position"]).drop_nulls()
        return {(x["team"], int(x["week"]), int(x["jersey_number"])): (x["gsis_id"], x["full_name"], x["position"]) for x in r.to_dicts()}
    except Exception as e:
        print("gridiris: brak składów tygodniowych, dopasowuję po nazwiskach:", e)
        return {}


class IdMap:
    """Zamienia skrócone nazwisko i numer koszulki z Gridiris na gsis_id z nflverse."""

    def __init__(self, roster, players):
        self.roster, self.cache = roster, {}
        self.by_team = {}
        for p in players:
            self.by_team.setdefault(p["team"], []).append((norm(p["name"]), p["name"][:1].lower(), p["player_id"]))

    def get(self, team, week, no, name):
        """Najpierw skład tygodniowy (drużyna + tydzień + numer), potem unikalne nazwisko w drużynie. None, gdy się nie da."""
        key = (team, week, no, name)
        if key in self.cache:
            return self.cache[key]
        ini, last = split_name(name)
        res = None
        hit = self.roster.get((team, week, no))
        if hit and norm(hit[1]).endswith(last) and hit[1][:1].lower() == ini:
            res = hit[0]
        if res is None:
            c = {pid for full, i, pid in self.by_team.get(team, []) if i == ini and full.endswith(last)}
            res = c.pop() if len(c) == 1 else None
        self.cache[key] = res
        return res

    def info(self, team, week, no, name):
        """(player_id, pełne nazwisko, pozycja) obrońcy ze składu tygodniowego; (None, None, None), gdy nie da się dopasować."""
        hit = self.roster.get((team, week, no))
        ini, last = split_name(name)
        if hit and norm(hit[1]).endswith(last) and hit[1][:1].lower() == ini:
            return hit[0], hit[1], (hit[2] if len(hit) > 2 else None)
        return None, None, None


def cell():
    """Pusta komórka statystyk (so/no: separacja na targetach, sa/na: separacja na wszystkich trasach)."""
    return {"n": 0, "r": 0, "t": 0, "rec": 0, "yds": 0, "td": 0, "so": 0.0, "no": 0, "sa": 0.0, "na": 0}


def bump(d, key, is_route, target, rec, yds, td, openv):
    """Dopisuje jedno wystąpienie zawodnika (snap w podaniu) do komórki d[key]."""
    c = d.setdefault(key, cell())
    c["n"] += 1
    if is_route:
        c["r"] += 1
        if openv is not None:
            c["sa"] += openv
            c["na"] += 1
    if target:
        c["t"] += 1
        c["rec"] += rec
        c["yds"] += yds
        c["td"] += td
        if openv is not None:
            c["so"] += openv
            c["no"] += 1


def rank_cells(teams, field):
    """Ranking obron (1 = najlepsza, najmniej jardów na ścieżkę) w każdym kluczu pola `field`; znormalizowany do skali 32 drużyn."""
    keys = {k for t in teams.values() for k in t[field]}
    for k in keys:
        vals = [(t[field][k]["yds"] / t[field][k]["r"], name) for name, t in teams.items()
                if k in t[field] and t[field][k]["r"] >= MIN_ROUTES]
        vals.sort()
        n = len(vals)
        if n < MIN_TEAMS:  # za mało obron z próbką - ranking byłby mylący
            continue
        for i, (_, name) in enumerate(vals):
            teams[name][field][k]["rn"] = n
            teams[name][field][k]["rank"] = round(i / (n - 1) * 31) + 1 if n > 1 else 16


def aggregate(games, idmap):
    """Główna agregacja: zwraca (dane_obron, dane_zawodników, dane_obrońców) dla listy meczów jednego sezonu."""
    players, teams, gtp, defenders = {}, {}, {}, {}
    for g in games:
        for p in g["plays"]:
            if "routes" not in p:
                continue
            off = p["off"]
            dfn = g["home"] if off == g["away"] else g["away"]
            cov = p.get("cov")
            groups = [cov] if cov else []
            if cov in MAN:
                groups.append("MAN")
            elif cov in ZONE:
                groups.append("ZONE")
            gtp[(g["game_id"], off)] = gtp.get((g["game_id"], off), 0) + 1
            D = teams.setdefault(dfn, {"pp": 0, "cov": {}, "ncov": 0, "al": {}, "rt": {}})
            D["pp"] += 1
            if cov:
                D["ncov"] += 1
                for k in groups:
                    D["cov"][k] = D["cov"].get(k, 0) + 1
            for r in p["routes"]:
                is_route = r["route"] != "Block"
                tgt = bool(r["target"])
                rec = 1 if tgt and p.get("result") == "Complete" else 0
                yds = (p.get("yds") or 0) if rec else 0
                td = 1 if rec and p.get("td") else 0
                did = dname = dpos = None
                if is_route and r["def_no"] is not None:  # kto kryje odbiorcę w momencie rzutu
                    did, dname, dpos = idmap.info(dfn, g["week"], r["def_no"], r["def_name"])
                    if did is None:
                        ini, last = split_name(r["def_name"])
                        did, dname = f"{dfn}:{ini}.{last}", r["def_name"]
                    DD = defenders.setdefault(did, {"team": dfn, "name": dname, "pos": dpos, "games": set(), "al": {}})
                    DD["games"].add(g["game_id"])
                    bump(DD["al"], r["align"], is_route, tgt, rec, yds, td, r["open"])
                pid = idmap.get(off, g["week"], r["no"], r["name"])
                if tgt or is_route:
                    bump(D["al"], r["align"], is_route, tgt, rec, yds, td, r["open"])
                    if is_route:
                        bump(D["rt"], r["route"], is_route, tgt, rec, yds, td, r["open"])
                if not pid:
                    continue
                P = players.setdefault(pid, {"team": off, "pos": r["pos"], "name": r["name"], "games": set(), "al": {}, "side": {},
                                             "rt": {}, "cv": {}, "snaps": 0, "routes": 0, "cb": {}, "cbm": {}})
                P["games"].add(g["game_id"])
                P["snaps"] += 1
                P["routes"] += is_route
                bump(P["al"], r["align"], is_route, tgt, rec, yds, td, r["open"])
                bump(P["side"], r["side"], is_route, tgt, rec, yds, td, r["open"])
                if did is not None:  # obrońcy, którzy kryli tego odbiorcę
                    bump(P["cb"], did, is_route, tgt, rec, yds, td, r["open"])
                    P["cbm"][did] = {"name": dname, "team": dfn, "pos": dpos}
                if is_route:
                    bump(P["rt"], r["route"], is_route, tgt, rec, yds, td, r["open"])
                    for k in groups:
                        bump(P["cv"], k, is_route, tgt, rec, yds, td, r["open"])
    rank_cells(teams, "al")
    rank_cells(teams, "rt")
    for P in players.values():
        P["tp"] = sum(v for (gid, tm), v in gtp.items() if tm == P["team"] and gid in P["games"])  # podania drużyny w jego meczach
        P["games"] = len(P["games"])
        P["cb"] = sorted(({"id": d, **P["cbm"][d], "r": c["r"], "t": c["t"], "rec": c["rec"], "yds": c["yds"], "td": c["td"],
                           "sa": round(c["sa"], 1), "na": c["na"]} for d, c in P["cb"].items()), key=lambda x: -x["r"])[:8]
        del P["cbm"]
    return teams, players, defenders


def build_gridiris(out: Path, in_dir: Path = None, players_json: Path = None):
    """Czyta wszystkie zaimportowane mecze najnowszego sezonu i zapisuje pliki dla aplikacji w <out>/gridiris/."""
    in_dir = in_dir or Path(__file__).resolve().parent / "gridiris"
    files = sorted(in_dir.glob("*.json"))
    if not files:
        raise RuntimeError(f"brak zaimportowanych meczów w {in_dir}")
    games = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    season = max(g["season"] for g in games)
    games = [g for g in games if g["season"] == season]
    pj = players_json or out / "players.json"
    players = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else []
    teams, pls, dfs = aggregate(games, IdMap(load_roster(season), players))
    gdir = out / "gridiris"
    (gdir / "players").mkdir(parents=True, exist_ok=True)
    for old in (gdir / "players").glob("*.json"):  # dane zawodników liczone od zera przy każdym budowaniu
        old.unlink()
    weeks = sorted({g["week"] for g in games})
    meta = {"season": season, "games": len(games), "weeks": weeks, "through_week": weeks[-1]}
    defense = {}
    for t, D in teams.items():
        n = D["ncov"]
        usage = {k: round(v / n * 100, 1) for k, v in D["cov"].items()} if n else {}
        defense[t] = {"pp": D["pp"], "ncov": n, "usage": usage, "al": D["al"], "rt": D["rt"]}
    (gdir / "defense.json").write_text(json.dumps({"meta": meta, "teams": defense}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for pid, P in pls.items():
        (gdir / "players" / f"{pid}.json").write_text(json.dumps(P, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    names = {p["player_id"]: p["name"] for p in players}
    tm = {}  # lista zawodników drużyny z ustawieniami (do strony meczu: obrona vs alignment)
    for pid, P in pls.items():
        if P["snaps"] < 5:
            continue
        tm.setdefault(P["team"], []).append({"id": pid, "name": names.get(pid) or P["name"], "pos": P["pos"], "g": P["games"], "n": P["snaps"],
                                             "r": P["routes"], "tp": P["tp"], "t": sum(c["t"] for c in P["al"].values()),
                                             "sa": round(sum(c["sa"] for c in P["al"].values()), 1), "na": sum(c["na"] for c in P["al"].values()),
                                             "al": {k: {"n": c["n"], "t": c["t"]} for k, c in P["al"].items()}})
    for t in tm:
        tm[t].sort(key=lambda x: -x["r"])
    (gdir / "teams.json").write_text(json.dumps(tm, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dout = {}  # obrońcy: kogo kryli i ile separacji zostawiali (do strony meczu: CB kontra WR)
    for did, DD in dfs.items():
        tot = cell()
        for c in DD["al"].values():
            for k in ("r", "t", "rec", "yds", "td", "sa", "na"):
                tot[k] += c[k]
        if tot["r"] < 5:
            continue
        dout.setdefault(DD["team"], []).append({
            "id": did, "name": DD["name"], "pos": DD["pos"], "g": len(DD["games"]), "r": tot["r"], "t": tot["t"], "rec": tot["rec"],
            "yds": tot["yds"], "td": tot["td"], "sa": round(tot["sa"], 1), "na": tot["na"],
            "al": {k: {"r": c["r"], "t": c["t"], "rec": c["rec"], "yds": c["yds"], "sa": round(c["sa"], 1), "na": c["na"]}
                   for k, c in DD["al"].items()}})
    pool = sorted(((x["sa"] / x["na"], x) for lst in dout.values() for x in lst if x["r"] >= MIN_ROUTES and x["na"]), key=lambda t: t[0])
    if len(pool) >= 20:  # percentyl separacji wśród obrońców: wyższy = zostawia więcej miejsca (słabszy obrońca)
        for i, (_, x) in enumerate(pool):
            x["sp"] = round(i / (len(pool) - 1) * 100)
    for t in dout:
        dout[t].sort(key=lambda x: -x["r"])
    (gdir / "defenders.json").write_text(json.dumps(dout, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"gridiris {season}: {len(games)} meczów (tygodnie {weeks}), {len(defense)} obron, {len(pls)} zawodników")
    return meta