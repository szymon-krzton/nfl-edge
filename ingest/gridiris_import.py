"""Import eksportów "Every play" z gridiris.com (CSV) do plików JSON, z których korzysta reszta pipeline'u.

Użycie (można podać wiele plików naraz, także ze znakami wieloznacznymi):
    python ingest/gridiris_import.py ~/Downloads/gridiris-*.csv
    python ingest/gridiris_import.py plik1.csv plik2.csv --out ingest/gridiris

Dla każdego meczu powstaje ingest/gridiris/<sezon>_<tydzień>_<wyjazd>_<dom>.json (identyfikator zgodny z nflverse,
np. 2026_10_LAC_BAL). Ponowny import tego samego meczu nadpisuje plik, więc można bezpiecznie wrzucać nowe eksporty.
Plik CSV nie jest zwykłą tabelą: to raport złożony z bloków "N. The play" (pary klucz,wartość) i "N. Routes" (tabela
wszystkich zawodników na ścieżkach z ustawieniem, ścieżką, separacją i krywającym obrońcą)."""
import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path

TEAM_FIX = {"LAR": "LA", "AZ": "ARI", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "JAC": "JAX", "WSH": "WAS", "LVR": "LV"}


def team(t):
    """Normalizuje skrót drużyny do postaci używanej przez nflverse (np. BLT -> BAL, AZ -> ARI)."""
    t = (t or "").strip().upper()
    return TEAM_FIX.get(t, t)


def num(s):
    """Pierwsza liczba z tekstu (ze znakiem), albo None."""
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def split_blocks(rows):
    """Dzieli wiersze CSV na bloki oddzielone pustymi wierszami."""
    blocks, cur = [], []
    for r in rows:
        if not r or all(c.strip() == "" for c in r):
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(r)
    if cur:
        blocks.append(cur)
    return blocks


def parse_header(title):
    """Nagłówek pliku: 'LAC at BAL · Week 10, 2026 · Every play · Final · LAC 23, BAL 20 · 159 plays...'."""
    parts = [p.strip() for p in title.split("·")]
    m = re.match(r"^(\w+) at (\w+)$", parts[0])
    w = re.search(r"Week (\d+), (\d{4})", title)
    if not (m and w):
        raise ValueError(f"nie rozpoznano nagłówka: {title[:80]}")
    away, home = team(m.group(1)), team(m.group(2))
    sc = re.search(r"(\w+) (\d+), (\w+) (\d+)", " · ".join(parts[3:]))
    score = {team(sc.group(1)): int(sc.group(2)), team(sc.group(3)): int(sc.group(4))} if sc else {}
    status = parts[3] if len(parts) > 3 else ""
    season, week = int(w.group(2)), int(w.group(1))
    return {"game_id": f"{season}_{week:02d}_{away}_{home}", "season": season, "week": week, "away": away, "home": home,
            "status": status, "score": score}


def parse_when(s, offense):
    """'Q1 14:53 · 1st & 10 at BAL 23' -> kwarta, zegar, down, yardy do zdobycia, yardline_100 (odległość od pola punktowego)."""
    out = {}
    m = re.match(r"Q(\d|OT)\s+(\d+:\d+)", s)
    if m:
        out["q"], out["clock"] = (5 if m.group(1) == "OT" else int(m.group(1))), m.group(2)
    m = re.search(r"(\d)(?:st|nd|rd|th) & (\d+|Goal)", s)
    if m:
        out["down"], out["dist"] = int(m.group(1)), (None if m.group(2) == "Goal" else int(m.group(2)))
        out["goal"] = m.group(2) == "Goal"
    m = re.search(r"(?:at )?([A-Z]{2,3}) (\d+)\s*$", s)
    if m:
        side, yd = team(m.group(1)), int(m.group(2))
        out["yl100"] = 100 - yd if side == offense else yd
    elif re.search(r"at 50\s*$", s):
        out["yl100"] = 50
    return out


def parse_play(block, offense_default=""):
    """Blok 'N. The play' -> słownik z polami akcji (formacja, obrona, krycie, wynik, pomiary)."""
    d = {r[0]: r[1] for r in block[1:] if len(r) > 1}
    off = team(d.get("Offense", offense_default))
    p = {"n": int(re.match(r"(\d+)\.", block[0][0]).group(1)), "off": off, "text": d.get("Play", "")}
    p.update(parse_when(d.get("When", ""), off))
    if "Formation" in d:
        f = [x.strip() for x in d["Formation"].split("·")]
        p["form"] = d["Formation"]
        p["pers"] = next((x.split()[0] for x in f if x.endswith("personnel")), None)
        p["snap"] = next((x for x in f if x in ("gun", "under center", "pistol")), None)
    if "Motion" in d:
        p["motion"] = d["Motion"]
    if "Defense" in d:
        f = [x.strip() for x in d["Defense"].split("·")]
        p["dpkg"] = f[0]
        p["front"] = f[1] if len(f) > 1 else None
        box = next((num(x) for x in f if "in the box" in x), None)
        p["box"] = int(box) if box is not None else None
        p["shell"] = f[-1] if len(f) > 3 else None
    if "Coverage (est.)" in d:
        f = [x.strip() for x in d["Coverage (est.)"].split("·")]
        p["cov"] = f[0]
        man = re.search(r"(\d+)% of", d["Coverage (est.)"])
        rush = re.search(r"(\d+) estimated rushers", d["Coverage (est.)"])
        p["man_pct"] = int(man.group(1)) if man else None
        p["rushers"] = int(rush.group(1)) if rush else None
    if "Result" in d:
        p["result"] = d["Result"]
    if "Ball out" in d:
        f = d["Ball out"]
        p["ttt"] = num(f)
        drop = re.search(r"([-+]?\d+(?:\.\d+)?)-yd drop", f)
        p["drop"] = float(drop.group(1)) if drop else None
        p["pocket"] = "outside the pocket" not in f
    if "Air yards" in d:
        p["air"] = num(d["Air yards"])
        mph = re.search(r"([\d.]+) mph", d["Air yards"])
        p["throw_mph"] = float(mph.group(1)) if mph else None
    if "After the catch" in d:
        p["yac"] = num(d["After the catch"])
        c = re.search(r"([\d.]+) after contact", d["After the catch"])
        p["yac_contact"] = float(c.group(1)) if c else None
    if "Carrier" in d:
        m = re.match(r"#(\d+)\s+(.*)", d["Carrier"])
        p["carrier"] = {"no": int(m.group(1)), "name": m.group(2)} if m else {"name": d["Carrier"]}
    if "Gain" in d:
        g = re.findall(r"[-+]?\d+(?:\.\d+)?", d["Gain"])
        p["gain"] = float(g[0]) if g else None
        p["gain_before"], p["gain_after"] = (float(g[1]), float(g[2])) if len(g) >= 3 else (None, None)
    if "Top speed" in d:
        p["top_mph"] = num(d["Top speed"])
    t = p["text"]
    y = re.search(r"for (-?\d+) yards?", t)
    p["yds"] = int(y.group(1)) if y else (0 if ("no gain" in t.lower() or "incomplete" in t.lower()) else None)
    p["td"] = "TOUCHDOWN" in t
    p["int"] = "INTERCEPTED" in t
    p["sack"] = "sacked" in t
    return p


def parse_routes(block):
    """Blok 'N. Routes' -> lista zawodników na ścieżkach (ustawienie, ścieżka, głębokość, separacja, krywający)."""
    head = block[1]
    out = []
    for r in block[2:]:
        d = dict(zip(head, r + [""] * (len(head) - len(r))))
        align = d.get("Lined up", "")
        kind, _, side = align.partition(" ")
        cov = re.match(r"#(\d+)\s+(.*)", d.get("Covered by", ""))
        out.append({"no": int(d["No."]) if d.get("No.", "").isdigit() else None, "name": d.get("Player"), "pos": d.get("Pos"),
                    "align": kind.lower(), "side": side.lower(), "route": d.get("Route"),
                    "depth": num(d.get("Depth")), "open": num(d.get("Open at throw")),
                    "def_no": int(cov.group(1)) if cov else None, "def_name": cov.group(2) if cov else None,
                    "target": d.get("Target", "").strip().lower() == "yes"})
    return out


def parse_file(path):
    """Wczytuje jeden eksport CSV i zwraca słownik meczu (metadane + lista akcji ze ścieżkami)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    blocks = split_blocks(rows)
    game = parse_header(blocks[0][0][0])
    game["exported"] = blocks[0][1][0] if len(blocks[0]) > 1 else None
    game["source"] = "gridiris"
    routes = {}
    for b in blocks[1:]:
        m = re.match(r"^(\d+)\. Routes$", b[0][0])
        if m:
            routes[int(m.group(1))] = parse_routes(b)
    plays = []
    for b in blocks[1:]:
        if re.match(r"^\d+\. The play$", b[0][0]):
            p = parse_play(b)
            if p["n"] in routes:
                p["routes"] = routes[p["n"]]
            plays.append(p)
    game["plays"] = plays
    return game


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", help="pliki CSV z gridiris.com (można użyć znaków wieloznacznych)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "gridiris"), help="katalog wyjściowy")
    a = ap.parse_args()
    paths = sorted({p for f in a.files for p in (glob.glob(f) or [f])})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for p in paths:
        try:
            g = parse_file(p)
        except Exception as e:  # jeden zły plik nie przerywa reszty
            print(f"BŁĄD {Path(p).name}: {e}")
            continue
        (out / f"{g['game_id']}.json").write_text(json.dumps(g, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        n_pass = sum(1 for x in g["plays"] if "routes" in x)
        warn = "" if g["status"] == "Final" else f"  UWAGA: status „{g['status']}” - dane mogą być niepełne"
        print(f"{g['game_id']}: {len(g['plays'])} akcji, {n_pass} podań ze ścieżkami{warn}")
        ok += 1
    print(f"zaimportowano {ok} z {len(paths)} plików do {out}")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()