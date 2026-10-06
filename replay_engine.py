# -*- coding: utf-8 -*-
"""Rebuilds the battle logs of a recorded match from its seed, so the logs themselves never have to be stored.

Every game of the tournament is a pure function of (engine version, tournament settings, the two trainers, Seed_Base): the engine seeds its
random generator from `Seed_Base + game number` and nothing else is random. matches{suffix}.csv keeps each match's Seed_Base, the engine
file that played the dataset is kept in tournament_data/engine_snapshots/<version_id>/ (with the move database and HGSS trainer file it used),
and replay_data/ holds the few MB of Platinum / HGSS game data the engine reads (trainer teams, species, items). Re-playing a match with those
gives back the exact log the tournament wrote - checked against the original logs for hundreds of thousands of games, and against Python 3.10
and 3.13.

    python replay_engine.py _noitems "Champion Cynthia" "Rival Survival Area Torterra"       # prints the score and checks it against matches*.csv

    import replay_engine
    info = replay_engine.dataset_info("_noitems")            # None when this dataset can't be re-played (no replay_info / snapshot)
    res = replay_engine.rebuild_match("_noitems", "Champion Cynthia", "Rival Survival Area Torterra", seed_base)
    res["score"], res["logs"][3]                            # logs: {game number: text}

replay_info{suffix}.json (next to the CSVs) names the engine version of a dataset: {"version_id": ..., "settings": {...}}. The engine source is run
with its absolute data paths pointed at this deployment's copies; the version fingerprint (engine, move DB, trainer / species / item data) is
recomputed on load and must equal the recorded version_id - if the bundled data ever differed, the replay refuses to run instead of drifting."""
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import types
import uuid
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE_DIR = os.path.join(HERE, "replay_data")
DATA_DIR = os.path.join(HERE, "tournament_data")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "engine_snapshots")


class ReplayError(RuntimeError):
    pass


def settings_from_suffix(suffix):
    """Tournament settings encoded in a dataset suffix (_50_ level cap, _hgss / _combined game, _noitems), as the orchestrator wrote them."""
    toks = [t for t in suffix.split("_") if t]
    return {"level": next((int(t) for t in toks if t.isdigit()), None),
            "game": "hgss" if "hgss" in toks else "combined" if "combined" in toks else "platinum",
            "items": "noitems" not in toks}


def dataset_info(suffix):
    """The replay_info for a dataset, or None if it cannot be re-played here (no info file, or its engine snapshot is not shipped)."""
    path = os.path.join(DATA_DIR, f"replay_info{suffix}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    vid = info.get("version_id")
    if not vid or not os.path.isfile(os.path.join(SNAPSHOT_DIR, vid, "pokemon_ai_tournament.py")) or not os.path.isdir(BUNDLE_DIR):
        return None
    return info


def _constants(version_dir):
    plat, hgss = os.path.join(BUNDLE_DIR, "platinum"), os.path.join(BUNDLE_DIR, "hgss")
    return {
        "TRAINER_DATA_DIR": os.path.join(plat, "res", "trainers", "data"),
        "MOVES_DB_FILE": os.path.join(version_dir, "moves_db.json"),
        "SPECIES_DATA_DIR": os.path.join(plat, "res", "pokemon"),
        "HGSS_TRAINER_DATA_FILE": os.path.join(version_dir, "trainers.json"),
        "PLATINUM_REPO_DIR": plat,
        "HGSS_REPO_DIR": hgss,
        "ITEM_DATA_DIR": os.path.join(plat, "res", "items", "data"),
    }


def _portable_tree_fingerprint(root, pattern):
    """The engine's own _tree_fingerprint, made independent of the operating system. The engine sorts the FULL paths, so whether
    'porygon/data.json' sorts before 'porygon2/data.json' depends on the path separator (a slash sorts before '2', a backslash after it); the stamped versions were hashed on
    Windows. Sorting as if every separator were a backslash gives the stamped value on any OS (the live Linux app computed a different
    species fingerprint, and so a different version_id, with the engine's own function)."""
    h = hashlib.sha256()
    for path in sorted(glob.glob(os.path.join(root, pattern)), key=lambda p: p.replace("/", "\\")):
        h.update(os.path.relpath(path, root).replace("\\", "/").encode("utf-8"))
        h.update(_sha256_file(path).encode("ascii"))
    return h.hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_engine(suffix, info):
    vdir = os.path.join(SNAPSHOT_DIR, info["version_id"])
    src_path = os.path.join(vdir, "pokemon_ai_tournament.py")
    with open(src_path, "r", encoding="utf-8", newline="") as fh:
        src = fh.read()
    for name, path in _constants(vdir).items():                      # the engine hard-codes where its data lives; point those at this checkout
        pat = re.compile(rf"^{name}[ \t]*=[^\r\n]*", re.M)
        if len(pat.findall(src)) != 1:
            raise ReplayError(f"engine {info['version_id']}: cannot find the single `{name} = ...` line to redirect")
        src = pat.sub(lambda m, n=name, p=path: f"{n} = {p!r}", src)
    mod = types.ModuleType(f"replay_engine_{info['version_id']}_{uuid.uuid4().hex[:6]}")
    mod.__file__ = src_path                                           # engine_version_info hashes this file, i.e. the snapshot as stored
    sys.modules[mod.__name__] = mod
    try:
        exec(compile(src, src_path, "exec"), mod.__dict__)
        mod._tree_fingerprint = _portable_tree_fingerprint
        st = settings_from_suffix(suffix)
        mod.SET_LEVEL = st["level"]
        mod.MOVESET_LEVEL_SOURCE = "original"
        mod.TOURNAMENT_BATTLE_MODE = "normal"
        mod.TRAINER_ITEMS_ENABLED = st["items"]
        if st["game"] == "platinum":
            mod.TRAINERS_DB, mod.DISPLAY_NAMES = mod.load_trainers_from_repo()
        elif st["game"] == "hgss":
            mod.TRAINERS_DB, mod.DISPLAY_NAMES = mod.load_hgss_trainers_from_repo()
        elif hasattr(mod, "load_combined_roster"):
            mod.TRAINERS_DB, mod.DISPLAY_NAMES = mod.load_combined_roster()
        else:
            raise ReplayError(f"engine {info['version_id']} predates the Combined roster fix - its Combined logs cannot be told apart by name")
        mod.install_duo_trainers()
        got = mod.engine_version_info()
        if got["version_id"] != info["version_id"]:
            differs = [k for k in ("engine_sha256", "moves_db_sha256", "hgss_trainers_sha256", "platinum_trainers_fingerprint", "species_fingerprint",
                                   "items_fingerprint") if got.get(k) != info.get(k)]
            raise ReplayError(f"data mismatch: this checkout hashes to engine version {got['version_id']}, the dataset was played by "
                              f"{info['version_id']} (differs in: {', '.join(differs) or 'nothing recorded'})")
        for k, v in (info.get("settings") or {}).items():
            if got["settings"].get(k) != v:
                raise ReplayError(f"setting {k} differs: dataset {v!r}, replay {got['settings'].get(k)!r}")
    except Exception:
        sys.modules.pop(mod.__name__, None)
        raise
    by_name = {}
    for key, name in mod.DISPLAY_NAMES.items():
        by_name.setdefault(name, key)
    return mod, by_name


_ENGINES = OrderedDict()          # suffix -> (engine module, name -> key); a loaded engine holds its whole roster, so only a couple are kept
_MAX_ENGINES = 2
_LOCK = threading.RLock()         # an engine's output folder name is a module global: one replay at a time


def _engine(suffix, info):
    entry = _ENGINES.get(suffix)
    if entry is not None:
        _ENGINES.move_to_end(suffix)
        return entry
    entry = _load_engine(suffix, info)
    _ENGINES[suffix] = entry
    while len(_ENGINES) > _MAX_ENGINES:
        _, (old, _names) = _ENGINES.popitem(last=False)
        sys.modules.pop(old.__name__, None)
    return entry


def warm(suffix):
    """Loads the engine for a dataset ahead of the first replay (a few seconds). Returns False if the dataset cannot be re-played."""
    info = dataset_info(suffix)
    if info is None:
        return False
    with _LOCK:
        _engine(suffix, info)
    return True


def rebuild_match(suffix, name_a, name_b, seed_base):
    """Plays the match again. `name_a` / `name_b` are the matches CSV's Trainer_A / Trainer_B display names (the order the engine played them in).
    Returns {"score": [wins A, wins B], "turns": total turns, "games": n, "winner": display name, "logs": {game number: log text}}."""
    info = dataset_info(suffix)
    if info is None:
        raise ReplayError(f"dataset {suffix!r} has no replay_info / engine snapshot")
    with _LOCK:
        eng, by_name = _engine(suffix, info)
        for n in (name_a, name_b):
            if n not in by_name:
                raise ReplayError(f"{n!r} is not in the {suffix!r} roster")
        tmp = "_replay_" + uuid.uuid4().hex[:8]                       # the engine writes every game's log file; it is deleted again right away
        eng.OUTPUT_SUFFIX = tmp
        try:
            winner, wins_a, wins_b, games, turns, _results, stats = eng.run_match(by_name[name_a], by_name[name_b], int(seed_base))
            logs = {i + 1: "\n".join(s["log_lines"]) for i, s in enumerate(stats)}
        finally:
            shutil.rmtree("tournament_results" + tmp, ignore_errors=True)
        return {"score": [wins_a, wins_b], "turns": turns, "games": games, "winner": eng.DISPLAY_NAMES.get(winner, winner), "logs": logs,
                "engine_version": info["version_id"]}


def _main():
    import csv
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    suffix, a, b = sys.argv[1:]
    path = os.path.join(DATA_DIR, f"matches{suffix}.csv")
    row = None
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if {r["Trainer_A"], r["Trainer_B"]} == {a, b}:
                row = r
                break
    if row is None:
        sys.exit(f"no match between {a!r} and {b!r} in {path}")
    res = rebuild_match(suffix, row["Trainer_A"], row["Trainer_B"], row["Seed_Base"])
    ok = res["score"] == [int(row["Score_A"]), int(row["Score_B"])] and res["turns"] == int(row["Total_Turns"])
    print(f"{row['Trainer_A']} vs {row['Trainer_B']}: {res['score'][0]}-{res['score'][1]}, {res['turns']} turns, engine {res['engine_version']} -> "
          f"{'matches the recorded result' if ok else 'DOES NOT MATCH the recorded result'}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    _main()
