import streamlit as st
import pandas as pd
import os
import zipfile
import re
import plotly.express as px
import numpy as np
import html
import base64
import struct
import glob
from PIL import Image
import io
import difflib
import json
from collections import Counter

# Read-only, best-effort import of the tournament engine itself - ONLY for its exact stat-calculation/ability/nature
# resolution (Trainer Database's "Actual Stats" section - see get_actual_mon further down). This is the one piece
# this dashboard can't safely reimplement on its own: a trainer's real nature/ability/IVs aren't just defaults,
# they're derived by a accurate NPC "personality value" algorithm (see assign_trainer_personalities in
# pokemon_ai_tournament.py) that depends on internal trainer-ID/species-ID/class-index tables this file has no
# business duplicating - getting that wrong would show a confidently-wrong ability/nature, worse than not showing
# one at all. This NEVER modifies pokemon_ai_tournament.py or writes anything - pure read access to its already-
# built roster, safe to run alongside a tournament that's currently writing its own OUTPUT_SUFFIX-scoped files in a
# separate process. Importing it does trigger ITS OWN module-level Platinum roster load (a few seconds, once, at
# this server's startup - the same cost every other script in this project that touches it already pays), and if
# the file isn't even present (a deployment that only ships app.py + tournament_data/ + sprites/, not the multi-GB
# decompiled source tree), this degrades to `eng = None` and every feature that needs it just quietly doesn't show.

try:
    import pokemon_ai_tournament as eng
except Exception:
    eng = None

# Battle logs are not stored for a dataset that carries a replay_info{suffix}.json: replay_engine.py plays any of its matches again from the
# match's recorded Seed_Base with the exact engine version that played the dataset (a few MB of bundled game data, see its docstring) and
# gives back the identical log. Datasets without that file still read their logs from tournament_results{suffix}_partN.zip.
try:
    import replay_engine
except Exception:
    replay_engine = None


def safe_filename(name):
    """MUST match pokemon_ai_tournament.py's own safe_filename() exactly: it's what the tournament script actually names a
    battle log file after (safe_filename(trainer_a_display_name) + "_vs_" + safe_filename(trainer_b_display_name) +
    "_game{n}.txt"), collapsing any run of non-alphanumeric characters to a single underscore and trimming the ends. A plain
    `.replace(" ", "_")` (this page's previous approach) leaves periods, parentheses and ampersands untouched, so it silently
    failed to find any log for a trainer whose display name has one - "Rival Silver Feraligatr (Goldenrod)", "Leader Lt. Surge
    Rematch", "Bug Catcher Jack & Lass Briana" and, in HGSS/Combined datasets, roughly 1 in 7 trainers overall.

    Reverses the "(DD)" -> "(Dragon's Den)" readability expansion this page applies to df['Display_Name'] (see that
    assignment's own comment) before collapsing - the actual log filenames were generated from the RAW "(DD)" form,
    since that expansion is a display-only affordance added long after those tournaments ran. Without this, every
    Leader Clair & Champion Lance (Dragon's Den) log (Combined and HGSS alike) would silently fail to be found."""
    name = name.replace("(Dragon's Den)", "(DD)")
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")

# Set browser tab title and layout
st.set_page_config(page_title="Gen 4 AI Tournament Battle Logs", layout="wide")

# --- SIDEBAR: DATASET SELECTION ---
st.sidebar.header("Dataset")

# Every export from one tournament run (standings*.csv, tournament_results*/, analytics_*.csv, ...) shares one suffix baked in
# from that run's own settings - see OUTPUT_SUFFIX in pokemon_ai_tournament.py (level, forced battle format, game, generic-only,
# items). The controls below are faceted: each one only lists the values that actually occur among the runs still matching
# every choice made so far, so picking Game then narrows what Level Cap/Format/etc. can be, and a dimension with only one
# possible value (e.g. this repo ships just one Battle Format) is shown as a plain caption instead of a single-choice dropdown.
# This also means a fresh checkout with only a subset of runs generated never crashes or offers a dead-end combination - it
# just has fewer controls. Once every dimension is pinned down, exactly one run's suffix remains and is reused VERBATIM for
# every file this page reads, so a run's CSV, its battle logs and its analytics can never mismatch (the previous version
# rebuilt the suffix from each toggle by hand, which drifted out of sync the moment a new setting - like Items Disabled - was
# added on the generator side, and that's exactly why the Battle Log Viewer stopped finding any logs).
GAME_LABELS = {"platinum": "Pokémon Platinum", "hgss": "HeartGold / SoulSilver", "combined": "Combined (Platinum + HGSS)"}
LEVEL_LABELS = {"normal": "Normal (story levels)", "50": "Level Cap 50", "100": "Level Cap 100"}
LEVEL_HELP = ("'Normal' battles each trainer at their real in-game level, so the roster spans a Youngster's level 5 team up to " 
              "a level 70+ postgame Champion. 'Level Cap 50/100' reruns the whole tournament with every Pokémon's level forced "
              "to that number instead, so a trainer's ranking reflects team-building and AI skill alone, without an early-game "
              "trainer being penalized just for being fought at a low story level.")
FORMAT_LABELS = {"normal": "Normal (mixed, as in-game)", "doubles": "Forced Doubles", "singles": "Forced Singles"}
FORMAT_HELP = ("'Normal' follows each matchup's own in-game format - a genuine mix of 1-on-1 and 2-on-2 fights. The forced "
               "options replay every matchup as pure singles or pure doubles instead, even trainers who don't normally fight "
               "that way.")
GENERIC_HELP = ("Leaves out Gym Leaders, the Elite Four, Champions, Rivals, Battleground trainers, Red, Frontier Brains, "
                "other story characters and every evil-team member (Commanders, Grunts, Executives, bosses) - a roster of "
                "ordinary NPC trainers only.")
ITEMS_HELP = ("Whether trainers were allowed to use their held Full Restores, Potions, Full Heals and X items during battle, "
              "same as the real games (Disabled removes that AI behavior for a cleaner head-to-head comparison).")


# All tournament-output files (standings/analytics/matches CSVs, tournament_results folders and zips, moves_db.json)
# are looked up through dp() below, joined onto this one directory - empty by default (files sit right next to
# app.py, this project's own layout), but a deployment that keeps everything in its own subfolder for tidiness (e.g.
# "tournament_data") only needs to change this single constant, not every path in the file.
DATA_DIR = "tournament_data"


def dp(*parts):
    """Joins DATA_DIR onto a tournament-data filename/dirname - see DATA_DIR's own comment."""
    return os.path.join(DATA_DIR, *parts)


@st.cache_data
def discover_datasets():
    """One dict per standings*.csv on disk: its exact OUTPUT_SUFFIX (e.g. "_50_hgss_noitems" - substitute it into
    "tournament_results{suffix}"/"analytics_species{suffix}.csv"/etc. for that SAME run's data) plus the individual settings
    that produced it, parsed back out of the suffix. "extra" catches any token this page doesn't otherwise recognize, so a
    future setting shows up as its own filter rather than silently vanishing or colliding with another run."""
    rows = []
    for full_path in sorted(glob.glob(dp("standings*.csv")), key=lambda p: -os.path.getmtime(p)):
        path = os.path.basename(full_path)
        suf = path[len("standings"):-4]
        remaining = suf
        game = "combined" if "_combined" in remaining else ("hgss" if "_hgss" in remaining else "platinum")
        level = "100" if "_100" in remaining else ("50" if "_50" in remaining else "normal")
        fmt = "doubles" if "_doubles" in remaining else ("singles" if "_singles" in remaining else "normal")
        generic = ("_generic" in remaining) or ("_noboss" in remaining)
        items = "_noitems" not in remaining
        for token in ("_100", "_50", "_doubles", "_singles", "_combined", "_hgss", "_generic", "_noboss", "_noitems"):
            remaining = remaining.replace(token, "", 1)
        rows.append({"suffix": suf, "game": game, "level": level, "format": fmt, "generic": generic, "items": items,
                     "extra": remaining.strip("_")})
    return rows


def pick(label, options_map, pool, field, help_text=None, hide_if_none=False):
    """Narrows `pool` to a single value of `field`: a dropdown when the remaining runs disagree on it, a plain caption when
    they don't (nothing to choose), sorted to match options_map's own declaration order. `hide_if_none` skips even that
    caption when the single remaining value is empty/falsy - for "Other setting" (see its own call site), whose caption
    would otherwise read "Other setting: **(none)**" on literally every dataset that exists today, forever, since nothing
    has ever produced a real value there; it still appears (as a caption, or a dropdown if more than one) the moment a
    future dataset's suffix actually carries something in that slot."""
    present = sorted({row[field] for row in pool}, key=lambda v: list(options_map).index(v) if v in options_map else 999)
    if len(present) == 1:
        value = present[0]
        if not (hide_if_none and not value):
            st.sidebar.caption(f"{label}: **{options_map.get(value, value or '(none)')}**")
    else:
        shown = st.sidebar.selectbox(label, [options_map.get(v, v) for v in present], help=help_text)
        value = next(v for v in present if options_map.get(v, v) == shown)
    return [row for row in pool if row[field] == value], value


datasets = discover_datasets()
if not datasets:
    st.error("No `standings*.csv` files found in this folder. Run a tournament first "
             "(see `python pokemon_ai_tournament.py`) before opening this dashboard.")
    st.stop()

pool, game = pick("Game", GAME_LABELS, datasets, "game")
pool, _level = pick("Level Cap", LEVEL_LABELS, pool, "level", LEVEL_HELP)
pool, _fmt = pick("Battle Format", FORMAT_LABELS, pool, "format", FORMAT_HELP)
generic_present = sorted({row["generic"] for row in pool})
if len(generic_present) == 2:
    generic_only = st.sidebar.checkbox("Generic NPCs Only", value=False, help=GENERIC_HELP)
    pool = [row for row in pool if row["generic"] == generic_only]
elif generic_present[0]:
    st.sidebar.caption("Generic NPCs Only: **On** (the only data available for this combination)")
items_present = sorted({row["items"] for row in pool})
if len(items_present) == 2:
    items_enabled = st.sidebar.radio("Trainer Items", ["Enabled", "Disabled"], index=1, help=ITEMS_HELP) == "Enabled"
    pool = [row for row in pool if row["items"] == items_enabled]
else:
    st.sidebar.caption(f"Trainer Items: **{'Enabled' if items_present[0] else 'Disabled'}**")
pool, _extra = pick("Other setting", {}, pool, "extra", hide_if_none=True)  # a token no other filter recognizes - see pick()'s own docstring

suffix = pool[0]["suffix"]                  # exactly one run should remain; pool[0] is a defensive fallback if several tie
game_title = {"hgss": "HGSS", "combined": "Combined", "platinum": "Pokémon Platinum"}[game]

csv_file = dp(f"standings{suffix}.csv")
results_dir = dp(f"tournament_results{suffix}")
REPLAY_INFO = replay_engine.dataset_info(suffix) if replay_engine else None     # None -> this dataset's logs live in zip parts

st.sidebar.caption(f"`standings{suffix}.csv`")
st.title(f"{game_title} AI Tournament: Database")

# --- LOAD DATA & CACHE ZIP CONTENTS ---
@st.cache_data
def load_data(csv_path):
    if not os.path.exists(csv_path):
        return None
    return pd.read_csv(csv_path)

df = load_data(csv_file)

if df is None:
    st.error(f"Could not find `{csv_file}`. Tournament has not been run yet.")
    st.stop()

# "(DD)" is HGSS's own shorthand for Dragon's Den (Leader Clair's rematch venue, and the Rival fight that leads into
# it) baked into these trainers' Display_Name at generation time - spelled out here, once, for every reader of df
# (dropdowns, trainer cards, Tier List, Leaderboard...) rather than at each individual render site. Display-only:
# Trainer_Key (which the rest of the app keys everything off of) is untouched.
df['Display_Name'] = df['Display_Name'].str.replace(r'\(DD\)$', "(Dragon's Den)", regex=True)

trainer_dict = dict(zip(df['Display_Name'], df['Trainer_Key']))
key_to_name = dict(zip(df['Trainer_Key'], df['Display_Name']))    # the reverse - Trainer_Key is guaranteed unique per row, Display_Name isn't

# --- SPECIES -> TRAINERS INDEX (drives the Tier List tab's "click a species, see who uses it" flow) ---
if "selected_trainer_key" not in st.session_state:
    st.session_state.selected_trainer_key = None
if "selected_species_lookup" not in st.session_state:
    st.session_state.selected_species_lookup = None
if "analytics_mode_pending_jump" not in st.session_state:
    # One-shot: holds a species name that Move Analytics wants the Analytics tab to jump to (switch its mode to
    # "Species Data" and preselect this species), same pattern/reason as trainerdb_pending_jump below.
    st.session_state.analytics_mode_pending_jump = None
if "move_analytics_pending_jump" not in st.session_state:
    # One-shot: holds a move name that Species Data's "Moves Executed" donut (or a Mimic click) wants the Analytics
    # tab to jump to (switch its mode to "Move Analytics" and preselect this move).
    st.session_state.move_analytics_pending_jump = None
if "trainerdb_pending_jump" not in st.session_state:
    # One-shot flag: only an external click (Tier List "trainers using X", etc.) should force the Trainer Database
    # tab's selectbox to jump to `selected_trainer_key`. Without this, the tab re-forced that value on EVERY rerun
    # (including the one caused by the user picking a different name in that same dropdown by hand), which silently
    # snapped the dropdown right back and made manual switching look broken.
    st.session_state.trainerdb_pending_jump = False


def parse_team_species_set(team_str):
    """This one trainer's own real species (ALL-CAPS), parsed straight out of their Team_and_Movesets - the same
    per-mon parsing as build_species_trainer_index, just for one team instead of indexing every trainer's. This is
    the authoritative source for "what does this trainer actually field": some existing analytics_individuals.csv
    datasets have stray extra (Trainer_Key, Species) rows for species that trainer never fielded at all (a species
    it merely fought as an opponent, misattributed - a pre-existing data issue, not something this dashboard can
    regenerate short of a full re-simulation), so any per-trainer species list drawn from that CSV should be
    intersected with this set rather than trusted on its own. See its use in the Trainer Database tab."""
    if not isinstance(team_str, str) or team_str in ('-', ''):
        return set()
    result = set()
    for mon_data in team_str.split(' | '):
        base_mon_name = re.sub(r'\[.*?\]', '', mon_data.split(' Lv')[0].strip()).strip()
        mon_name = (base_mon_name.split('@')[0] if '@' in base_mon_name else base_mon_name).strip().upper()
        if mon_name:
            result.add(mon_name)
    return result


def build_species_trainer_index(dataframe):
    """species (ALL-CAPS, matching analytics_species.csv's own spelling) -> the Trainer_Keys of every trainer who fields it,
    parsed straight out of Team_and_Movesets. Built fresh per dataset (a few thousand string splits - trivial), not cached,
    so switching datasets in the sidebar can never show a stale trainer list for a species."""
    index = {}
    for _, r in dataframe.iterrows():
        team_str = r.get('Team_and_Movesets', '')
        if not isinstance(team_str, str) or team_str in ('-', ''):
            continue
        seen_on_this_team = set()
        for mon_data in team_str.split(' | '):
            base_mon_name = re.sub(r'\[.*?\]', '', mon_data.split(' Lv')[0].strip()).strip()
            mon_name = (base_mon_name.split('@')[0] if '@' in base_mon_name else base_mon_name).strip().upper()
            if mon_name and mon_name not in seen_on_this_team:
                seen_on_this_team.add(mon_name)
                index.setdefault(mon_name, []).append(r['Trainer_Key'])
    return index


SPECIES_TRAINER_INDEX = build_species_trainer_index(df)


def get_trainer_species_moveset(trainer_key, species_upper):
    """One specific trainer's own moves for a species, exactly as it appears in THEIR Team_and_Movesets (matching
    species_upper, ALL-CAPS - SPECIES_TRAINER_INDEX's own spelling). Different trainers can run the same species with
    different movesets, so this is not the same as a species' Global_Move_Usage. Returns None if that trainer isn't
    fielding this species at all (a stale index after a dataset switch, in practice)."""
    match = df[df['Trainer_Key'] == trainer_key]
    if match.empty:
        return None
    team_str = match.iloc[0].get('Team_and_Movesets', '')
    if not isinstance(team_str, str) or team_str in ('-', ''):
        return None
    for mon_data in team_str.split(' | '):
        base_mon_name = re.sub(r'\[.*?\]', '', mon_data.split(' Lv')[0].strip()).strip()
        mon_name = (base_mon_name.split('@')[0] if '@' in base_mon_name else base_mon_name).strip()
        if mon_name.upper() != species_upper:
            continue
        if ': ' not in mon_data:
            return []
        return [m.strip() for m in mon_data.split(': ')[1].split('/') if m.strip() and m.strip() != "None"]
    return None


def moveset_chips_html(moves):
    """Small type-colored move chips, one row - the same visual language as a trainer card's own movesets, just
    compact enough to sit next to a trainer's name in a "trainers using this species" list."""
    if not moves:
        return ""
    chips = []
    for mv in moves:
        search_key = mv.lower().replace(" ", "").replace("-", "")
        m_type = MOVE_DICT.get(search_key, 'Normal')
        bg_color = TYPE_COLORS.get(m_type, '#A8A77A')
        chips.append(
            f"<span style='background:{bg_color}; color:#fff; text-shadow:1px 1px 1px rgba(0,0,0,0.7); "
            f"font-size:10px; font-weight:bold; border-radius:3px; padding:2px 6px; margin-right:3px; "
            f"white-space:nowrap; display:inline-block; margin-top:2px;'>{mv}</span>"
        )
    return "".join(chips)


def cap_for_donut(df, count_col='Count', name_col='Move', top_n=15, other_label='Other'):
    """Caps a (name, count) dataframe to its top `top_n` rows by count, folding everything past that into one
    `other_label` row - the same "Top 15" treatment the All Tournament Data view's own move chart already applies
    with a plain .head(15). A well-traveled species' full move history can run to hundreds of rows; without this, its
    donut chart turns into an unreadable ring of sub-0.01% slices with a legend that overflows the page. Returns the
    input unchanged (not even sorted) if it's already at or under top_n, so a short list renders exactly as before."""
    if len(df) <= top_n:
        return df
    sorted_df = df.sort_values(count_col, ascending=False)
    capped = sorted_df.head(top_n)
    other_count = sorted_df.iloc[top_n:][count_col].sum()
    return pd.concat([capped, pd.DataFrame([{name_col: other_label, count_col: other_count}])], ignore_index=True)


# --- SPECIES TIER / ROLE / KDA (analytics_species.csv - see pokemon_ai_tournament.py's ASSIST TRACKING / KDA sections) ---
# Loaded once here (not just inside the Analytics tab) so the Tier List tab and every trainer card's Team Composition line
# can use it too. A dataset produced before assist tracking existed simply won't have these columns - SPECIES_ROLE/
# SPECIES_TIER then stay empty and every place that reads them degrades gracefully (no badge/line rendered) rather than
# erroring, so an older dataset still opens fine.
_species_analytics_path = dp(f"analytics_species{suffix}.csv")
if not os.path.exists(_species_analytics_path) and os.path.exists(dp(f"analytics_species{suffix}_2.csv")):
    _species_analytics_path = dp(f"analytics_species{suffix}_2.csv")
df_species_global = load_data(_species_analytics_path)
SPECIES_ROLE = dict(zip(df_species_global['Species'], df_species_global['Role'])) \
    if df_species_global is not None and 'Role' in df_species_global.columns else {}
SPECIES_TIER = dict(zip(df_species_global['Species'], df_species_global['Tier'])) \
    if df_species_global is not None and 'Tier' in df_species_global.columns else {}

TIER_ORDER = ["S+", "S", "S-", "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "E+", "E", "E-", "F+", "F", "F-"]
TIER_COLORS = {
    "S+": "#FFD700", "S": "#FFD700", "S-": "#FFD700",
    "A+": "#FF7F50", "A": "#FF7F50", "A-": "#FF7F50",
    "B+": "#4DA6FF", "B": "#4DA6FF", "B-": "#4DA6FF",
    "C+": "#7AC74C", "C": "#7AC74C", "C-": "#7AC74C",
    "D+": "#A6B91A", "D": "#A6B91A", "D-": "#A6B91A",
    "E+": "#B7B7CE", "E": "#B7B7CE", "E-": "#B7B7CE",
    "F+": "#999999", "F": "#999999", "F-": "#999999",
}
ALL_ROLE_NAMES = ["Attacker", "Disrupter", "Hazards", "Weather", "Support", "Passer", "Tank", "Fodder", "All-Rounder"]
# The engine's own "Defender" role (see compute_combat_role in pokemon_ai_tournament.py) means "no offense/support role,
# but long-lived" - which reads very differently for a species propping up the S tiers versus one nobody could kill only
# because nobody wanted to. This page splits it in two for display ONLY (the analytics CSV itself still says "Defender"):
# "Tank" for a Tier of D- or better, "Fodder" for E+ or worse - the same D-/E+ line the underlying Tier list already draws.
TANK_FODDER_CUTOFF = TIER_ORDER.index("D-")


def tier_rank(tier):
    """0 (S+) .. len(TIER_ORDER)-1 (F-); an unknown/missing tier sorts as worse than F-."""
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)


# A dataset generated before a role was renamed in the engine still has the OLD name baked into its Role column (a re-run is what
# would actually change it) - normalized here, at the earliest point every consumer (badges, the Role filter, the Role Distribution
# pie chart) reads Role through, so an older dataset displays and filters exactly like a fresh one instead of needing its own re-run
# just to read right. "Cleric" -> "Support": see compute_combat_role in pokemon_ai_tournament.py.
OLD_ROLE_NAME_ALIASES = {"Cleric": "Support"}


def role_components(role_str):
    """"Attacker / Disrupter" -> ["Attacker", "Disrupter"] (compute_combat_role's own " / " join, see pokemon_ai_tournament.py), with
    OLD_ROLE_NAME_ALIASES applied to each part."""
    if not isinstance(role_str, str) or not role_str:
        return []
    return [OLD_ROLE_NAME_ALIASES.get(r.strip(), r.strip()) for r in role_str.split(" / ") if r.strip()]


def display_role_parts(role_str, tier):
    """role_components(), with "Defender" renamed to "Tank" or "Fodder" for display using THIS species' own Tier - see
    ALL_ROLE_NAMES's comment. Every other role name passes through unchanged."""
    parts = role_components(role_str)
    if "Defender" not in parts:
        return parts
    label = "Tank" if tier_rank(tier) <= TANK_FODDER_CUTOFF else "Fodder"
    return [label if p == "Defender" else p for p in parts]


def display_role_text(role_str, tier):
    return " / ".join(display_role_parts(role_str, tier))


def mon_role_text(species_display_name):
    """The (Tank/Fodder-renamed) Role text for one Pokemon as it appears in a team string (e.g. "Garchomp") - looked up in
    SPECIES_ROLE/SPECIES_TIER, both keyed by the ALL-CAPS spelling analytics_species.csv itself uses."""
    key = species_display_name.strip().upper()
    return display_role_text(SPECIES_ROLE.get(key), SPECIES_TIER.get(key))


def role_badge_html(role_str, tier=None):
    parts = display_role_parts(role_str, tier)
    if not parts:
        return ""
    # Explicit text color, not just a background - this chip is often the only thing between the text and whatever
    # the page's theme happens to be (dark chip + inherited-black text in light mode is unreadable).
    return "".join(
        f"<span style='background:#333; color:#eee; border-radius:4px; padding:1px 7px; font-size:11px; margin-right:4px; white-space:nowrap;'>"
        f"{p}</span>" for p in parts
    )


def tier_badge_html(tier):
    if not tier or str(tier) in ("nan", "-", ""):
        return ""
    color = TIER_COLORS.get(tier, "#888")
    return f"<span style='background:{color}; color:#111; font-weight:bold; border-radius:4px; padding:2px 9px; font-size:13px;'>{tier}</span>"


# Display-only rename for one Assist_Breakdown category - the CSV column itself still says "Cleric" (a dataset re-run is what would
# actually rename it), same reasoning as ALL_ROLE_NAMES's Tank/Fodder split for the engine's own "Defender" role.
ASSIST_CATEGORY_DISPLAY_NAMES = {"Cleric": "Support"}


def parse_assist_breakdown(s):
    """"Damage: 426, Status: 12, Hazard: 0, Weather: 656, Cleric: 0, Screen: 3, Pass: 1" -> {"Damage": 426, ..., "Support": 0, ...}
    (Assist_Breakdown column, with ASSIST_CATEGORY_DISPLAY_NAMES applied)."""
    if not isinstance(s, str):
        return {}
    return {ASSIST_CATEGORY_DISPLAY_NAMES.get(k.strip(), k.strip()): int(v) for k, v in re.findall(r'([A-Za-z]+):\s*(\d+)', s)}


@st.cache_data
def get_available_logs(target_dir):
    available_files = set()
    if os.path.exists(target_dir):
        available_files.update(os.listdir(target_dir))

    # Walk part numbers until one is missing, rather than a fixed count - a hardcoded range(1, 21) silently stopped
    # indexing any dataset with more than 20 parts (all 3 Combined combos have 33-36, since Combined's ~1,380-trainer
    # roster produces far more matchups/logs per combo than Platinum or HGSS alone), so any log living in part 21+
    # was invisible here even though the zip itself was right there on disk.
    i = 1
    while os.path.exists(f"{target_dir}_part{i}.zip"):
        try:
            with zipfile.ZipFile(f"{target_dir}_part{i}.zip", 'r') as z:
                available_files.update([os.path.basename(f) for f in z.namelist()])
        except zipfile.BadZipFile:
            pass
        i += 1

    return available_files

available_logs = set() if REPLAY_INFO else get_available_logs(results_dir)


def raw_trainer_name(display_name):
    """matches*.csv spells Dragon's Den trainers "(DD)"; df['Display_Name'] shows "(Dragon's Den)" (see its own comment)."""
    return display_name.replace("(Dragon's Den)", "(DD)")


@st.cache_data
def load_replay_matches(suffix):
    """matches{suffix}.csv - one row per match with the Seed_Base the engine played it from."""
    cols = ["Trainer_A", "Trainer_B", "Score_A", "Score_B", "Total_Turns", "Seed_Base"]
    return pd.read_csv(dp(f"matches{suffix}.csv"), usecols=cols, dtype={"Trainer_A": "category", "Trainer_B": "category"})


@st.cache_data(max_entries=32, show_spinner=False)
def replay_games_vs(suffix, raw_name):
    """{opponent: games played in that match} for every match this trainer is in (a match is 2 to 7 games)."""
    m = load_replay_matches(suffix)
    a, b = m[m["Trainer_A"] == raw_name], m[m["Trainer_B"] == raw_name]
    out = {str(o): int(g) for o, g in zip(a["Trainer_B"], a["Score_A"] + a["Score_B"])}
    out.update({str(o): int(g) for o, g in zip(b["Trainer_A"], b["Score_A"] + b["Score_B"])})
    return out


@st.cache_data(max_entries=64, show_spinner=False)
def replay_match_row(suffix, raw_a, raw_b):
    m = load_replay_matches(suffix)
    r = m[((m["Trainer_A"] == raw_a) & (m["Trainer_B"] == raw_b)) | ((m["Trainer_A"] == raw_b) & (m["Trainer_B"] == raw_a))]
    if r.empty:
        return None
    row = r.iloc[0]
    return {"Trainer_A": str(row["Trainer_A"]), "Trainer_B": str(row["Trainer_B"]), "Score_A": int(row["Score_A"]), "Score_B": int(row["Score_B"]),
            "Total_Turns": int(row["Total_Turns"]), "Seed_Base": int(row["Seed_Base"])}


@st.cache_data(max_entries=200, show_spinner=False)
def rebuild_match_logs(suffix, raw_a, raw_b, seed_base):
    return replay_engine.rebuild_match(suffix, raw_a, raw_b, seed_base)

# --- SIDEBAR: ADVANCED SYNERGY FILTERS ---
st.sidebar.markdown("---")
st.sidebar.header("Advanced Filters")

search_mon = st.sidebar.text_input("Filter by Pokémon", placeholder="e.g. Garchomp").strip()
search_move = st.sidebar.text_input("Filter by Move", placeholder="e.g. Earthquake").strip()
search_item = st.sidebar.text_input("Filter by Item", placeholder="e.g. Lum Berry").strip()
search_ability = st.sidebar.text_input("Filter by Ability", placeholder="e.g. Intimidate").strip()

st.sidebar.markdown("**Apply filters to:**")
apply_to = st.sidebar.radio("Apply filters to:", ["Trainer 1", "Trainer 2", "Both Trainers"], label_visibility="collapsed")

st.sidebar.markdown("---")
min_games_filter = st.sidebar.slider("Minimum Games Played in Match:", min_value=2, max_value=7, value=2)

st.sidebar.header("Display Settings")
expand_log = st.sidebar.checkbox("Show full log (Disable scrolling)", value=False)

# --- FILTER APPLICATION ---
def apply_filters(df_to_filter):
    f_df = df_to_filter.copy()
    if search_mon: f_df = f_df[f_df['Team_and_Movesets'].str.contains(search_mon, case=False, na=False)]
    if search_move: f_df = f_df[f_df['Team_and_Movesets'].str.contains(search_move, case=False, na=False)]
    if search_item: f_df = f_df[f_df['Team_and_Movesets'].str.contains(search_item, case=False, na=False)]
    if search_ability: f_df = f_df[f_df['Team_and_Movesets'].str.contains(search_ability, case=False, na=False)]
    return f_df

t1_df = apply_filters(df) if apply_to in ["Trainer 1", "Both Trainers"] else df.copy()
t2_df = apply_filters(df) if apply_to in ["Trainer 2", "Both Trainers"] else df.copy()

t1_names = sorted(t1_df['Display_Name'].dropna().unique().tolist())
t2_names = sorted(t2_df['Display_Name'].dropna().unique().tolist())

# --- APP TABS ---
tab_logs, tab_leaderboard, tab_analytics, tab_tierlist, tab_trainerdb, tab_curve = st.tabs([
    "Battle Log Viewer",
    "Leaderboard",
    "Analytics",
    "Tier List",
    "Trainer Database",
    "Difficulty Curve",
])

# ==========================================
# ASSET DIRECTORIES & CACHED IMAGE HELPERS
# ==========================================
# Deployment layout: only res/pokemon/*/data.json is shipped here (2.6MB, powers Species Data's Base Stats/
# Abilities), not the full decompiled source tree.
REPO_ASSETS_DIR = ""
HGSS_ASSETS_DIR = "sprites/hgss"
# Trainer CLASS sprite folders specifically (one subfolder per class, each holding front.png etc) - this deployment
# supplies just this piece as its own flat folder, mirroring res/trainers/classes' own structure, without needing
# the whole res/ tree alongside it.
TRAINER_SPRITE_DIR = "sprites/platinum"
# Species icons specifically (one subfolder per species, each holding just icon.png - not the rest of res/pokemon/)
# - split out from REPO_ASSETS_DIR the same way TRAINER_SPRITE_DIR is, so this deployment can supply just this piece.
POKEMON_ICON_DIR = "sprites/pokemon_icon"
# Held-item icons - same split-out-flat-folder approach as POKEMON_ICON_DIR/TRAINER_SPRITE_DIR.
ITEM_ICON_DIR = "sprites/items"

@st.cache_data
def get_valid_trainer_folders(classes_dir):
    if os.path.exists(classes_dir):
        return [f for f in os.listdir(classes_dir) if os.path.isdir(os.path.join(classes_dir, f))]
    return []

@st.cache_data
def get_hgss_sprites(base_dir):
    if os.path.exists(base_dir):
        return [f for f in os.listdir(base_dir) if f.lower().endswith('.png')]
    return []

@st.cache_data
def get_sprite_html(path, fallback_text, is_trainer=False, is_item=False, size=75):
    path = str(path) if path else ""
    if not os.path.exists(path):
        if is_item: return ""
        return f"<span style='color: #888; font-size: 11px; padding: 5px;'>{fallback_text}</span>"
    
    try:
        img = Image.open(path).convert("RGBA")
        data = np.array(img)
        
        bg_color = data[0, 0]
        if bg_color[3] == 255:
            mask = (data[:, :, 0] == bg_color[0]) & \
                   (data[:, :, 1] == bg_color[1]) & \
                   (data[:, :, 2] == bg_color[2])
            data[:, :, 3][mask] = 0
            img = Image.fromarray(data)

        w, h = img.size
        
        if is_item:
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            b64 = base64.b64encode(buffered.getvalue()).decode()
            return f"<img src='data:image/png;base64,{b64}' title='{fallback_text}' style='image-rendering: pixelated; width: 24px; vertical-align: middle;'>"
        elif is_trainer:
            if h > w:
                img = img.crop((0, 0, w, w))
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            b64 = base64.b64encode(buffered.getvalue()).decode()
            return f"<img src='data:image/png;base64,{b64}' title='{fallback_text}' style='image-rendering: pixelated; width: {size}px; object-fit: contain;'>"
        else:
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            b64 = base64.b64encode(buffered.getvalue()).decode()
            frames = max(1, h // w)
            anim_name = f"anim_{w}_{h}_{frames}_{base64.b64encode(fallback_text.encode()).decode()[:5]}"
            duration = frames * 0.4
            css = f"<style>@keyframes {anim_name} {{ 100% {{ background-position: 0 -{h}px; }} }}</style>"
            return f"{css}<div style='width: {w}px; height: {w}px; background-image: url(data:image/png;base64,{b64}); animation: {anim_name} {duration}s steps({frames}) infinite; image-rendering: pixelated; display: inline-block; vertical-align: middle;' title='{fallback_text}'></div>"
            
    except Exception as e:
        return f"<span style='color: #888; font-size: 11px;'>{fallback_text}</span>"


@st.cache_data
def get_species_static_info(species_display_name):
    """Base stats, possible abilities and type straight from this species' own res/pokemon/<name>/data.json - the
    same static game-data folder the icon lookups already use (see safe_mon's fallback-to-first-word convention
    elsewhere in this file), not anything the tournament measured. None if that file isn't there (a deployment
    without REPO_ASSETS_DIR synced, most likely) - callers treat that as "no static info to show", same
    graceful-degradation pattern as a missing sprite."""
    safe_mon = species_display_name.lower().replace(' ', '_').replace('.', '').replace('-', '_').replace("'", "")
    data_path = os.path.join(REPO_ASSETS_DIR, 'res', 'pokemon', safe_mon, 'data.json')
    if not os.path.exists(data_path) and '_' in safe_mon:
        data_path = os.path.join(REPO_ASSETS_DIR, 'res', 'pokemon', safe_mon.split('_')[0], 'data.json')
    if not os.path.exists(data_path):
        return None
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    abilities = [a.replace('ABILITY_', '').replace('_', ' ').title()
                 for a in (data.get('abilities') or []) if a and a != 'ABILITY_NONE']
    types = [t.replace('TYPE_', '').title() for t in (data.get('types') or []) if t and t != 'TYPE_NONE']
    return {"base_stats": data.get('base_stats') or {}, "abilities": abilities, "types": types}


@st.cache_data
def load_actual_mon_data():
    """Precomputed nature/ability/IVs for every Platinum and HGSS trainer's party (trainer_key -> [{"species",
    "ability", "nature", "ivs"}, ...], see export_actual_mon_data.py) - level-independent, since the personality
    hash that derives these is seeded from each trainer file's own canonical level, never a tournament's SET_LEVEL
    override, so one export covers every level-cap dataset. {} if actual_mon_data.json isn't shipped."""
    path = dp("actual_mon_data.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_roster_for_game(game_mode):
    """The precomputed party data for one of "platinum" / "hgss" / "combined" - same key namespace as that exact
    dataset's own Trainer_Key column (Combined prefixes every HGSS-origin key with "hgss_", matching
    pokemon_ai_tournament.py's own combining logic). {} if actual_mon_data.json isn't shipped."""
    data = load_actual_mon_data()
    if game_mode == "platinum":
        return data.get("platinum", {})
    if game_mode == "hgss":
        return data.get("hgss", {})
    combined = dict(data.get("platinum", {}))
    for key, party in data.get("hgss", {}).items():
        combined[f"hgss_{key}"] = party
    return combined


# Standard Gen 3+ stat formula and nature table - unlike nature/ability/IVs themselves (which need the retail
# trainer-ID/species-ID "personality value" hash - see export_actual_mon_data.py, which precomputes those once
# locally against the decompiled source and ships the result as actual_mon_data.json), turning base stats + IVs +
# nature into an actual stat VALUE at a given level needs no secret tables, so it's safe to compute right here.
NATURE_STAT_TABLE = {
    "LONELY": ("atk", "def"), "BRAVE": ("atk", "spe"), "ADAMANT": ("atk", "spa"), "NAUGHTY": ("atk", "spd"),
    "BOLD": ("def", "atk"), "RELAXED": ("def", "spe"), "IMPISH": ("def", "spa"), "LAX": ("def", "spd"),
    "TIMID": ("spe", "atk"), "HASTY": ("spe", "def"), "JOLLY": ("spe", "spa"), "NAIVE": ("spe", "spd"),
    "MODEST": ("spa", "atk"), "MILD": ("spa", "def"), "QUIET": ("spa", "spe"), "RASH": ("spa", "spd"),
    "CALM": ("spd", "atk"), "GENTLE": ("spd", "def"), "SASSY": ("spd", "spe"), "CAREFUL": ("spd", "spa"),
}


def nature_stat_multiplier(nature_name, stat):
    if not nature_name:
        return 1.0
    up, down = NATURE_STAT_TABLE.get(nature_name.replace("NATURE_", "").upper(), (None, None))
    if stat == up:
        return 1.1
    if stat == down:
        return 0.9
    return 1.0


def calc_actual_stat(base, iv, level, is_hp=False, nature_mult=1.0):
    core = (2 * base + iv) * level // 100
    return core + level + 10 if is_hp else int((core + 5) * nature_mult)


def get_mon_level_from_team_str(team_str, species_upper):
    """This species' own level, exactly as tournament-generated for the CURRENTLY selected dataset - Team_and_Movesets
    is always authoritative for level (ivs/nature come from actual_mon_data.json instead, since those don't vary by
    level-cap), same per-mon parsing convention as get_trainer_species_moveset."""
    if not isinstance(team_str, str):
        return None
    for mon_data in team_str.split(' | '):
        base_mon_name = re.sub(r'\[.*?\]', '', mon_data.split(' Lv')[0].strip()).strip()
        mon_name = (base_mon_name.split('@')[0] if '@' in base_mon_name else base_mon_name).strip()
        if mon_name.upper() != species_upper:
            continue
        m = re.search(r'Lv\s*(\d+)', mon_data)
        return int(m.group(1)) if m else None
    return None


def get_actual_mon(trainer_key, species_display_name, game_mode, team_str):
    """This species' resolved ability/nature/IVs (from actual_mon_data.json) plus its real calculated stats at the
    level it's actually fielded at in `team_str` (that dataset row's own Team_and_Movesets). None if
    actual_mon_data.json isn't shipped, the trainer isn't in it (a duo not covered by DUO_TRAINER_MEMBERS, or a
    trainer_key naming mismatch), or this species isn't actually on that trainer's team."""
    roster = load_roster_for_game(game_mode)
    if not roster:
        return None
    party = roster.get(trainer_key)
    if party is None:
        # A duo's merged key never exists as its own roster entry - its combined party is the concatenation of its
        # two individual members' own entries instead (see DUO_TRAINER_MEMBERS, defined further down this file but
        # already in scope by the time this is ever called). An HGSS member of a Combined-context duo needs the
        # "hgss_" prefix this roster's own combining step gave it; a Platinum or HGSS-only-dataset member doesn't,
        # so both spellings are tried.
        party = []
        for member_key in DUO_TRAINER_MEMBERS.get(trainer_key, ()):
            party.extend(roster.get(member_key) or roster.get(f"hgss_{member_key}") or [])
    species_key = species_display_name.strip().upper().replace(" ", "_").replace("'", "").replace(".", "")
    mon = next((m for m in party if (m.get("species") or "").replace("SPECIES_", "") == species_key), None)
    if mon is None:
        return None
    level = get_mon_level_from_team_str(team_str, species_key.replace("_", " "))
    static_info = get_species_static_info(species_display_name)
    base_stats = (static_info or {}).get("base_stats") or {}
    if level is None or not base_stats:
        return None
    nature = mon.get("nature")
    ivs = mon.get("ivs") or {}
    return {
        "level": level,
        "max_hp": calc_actual_stat(base_stats.get("hp", 0), ivs.get("hp", 31), level, is_hp=True),
        "atk": calc_actual_stat(base_stats.get("attack", 0), ivs.get("atk", 31), level,
                                 nature_mult=nature_stat_multiplier(nature, "atk")),
        "def": calc_actual_stat(base_stats.get("defense", 0), ivs.get("def", 31), level,
                                 nature_mult=nature_stat_multiplier(nature, "def")),
        "spa": calc_actual_stat(base_stats.get("special_attack", 0), ivs.get("spa", 31), level,
                                 nature_mult=nature_stat_multiplier(nature, "spa")),
        "spd": calc_actual_stat(base_stats.get("special_defense", 0), ivs.get("spd", 31), level,
                                 nature_mult=nature_stat_multiplier(nature, "spd")),
        "speed": calc_actual_stat(base_stats.get("speed", 0), ivs.get("spe", 31), level,
                                   nature_mult=nature_stat_multiplier(nature, "spe")),
        "ability": mon.get("ability"),
        "nature": nature,
    }


# Dynamic JSON parsing for Move Typing
MOVE_DICT = {}
# Static per-move reference data (type/class/power/accuracy/pp/description/secondary-effect chance) for the Move
# Analytics mode - this is all fixed game data from moves_db.json, not anything the tournament measured, since the
# analytics CSVs only ever tracked misses/crits/secondary-effect procs aggregated per Pokemon (across ALL of its
# moves), never broken out per individual move.
MOVE_INFO = {}
TYPE_COLORS = {
    'Normal': '#A8A77A', 'Fire': '#EE8130', 'Water': '#6390F0',
    'Electric': '#F7D02C', 'Grass': '#7AC74C', 'Ice': '#96D9D6',
    'Fighting': '#C22E28', 'Poison': '#A33EA1', 'Ground': '#E2BF65',
    'Flying': '#A98FF3', 'Psychic': '#F95587', 'Bug': '#A6B91A',
    'Rock': '#B6A136', 'Ghost': '#735797', 'Dragon': '#6F35FC',
    'Dark': '#705848', 'Steel': '#B7B7CE', 'Mystery': '#68A090'
}

if os.path.exists(dp('moves_db.json')):
    with open(dp('moves_db.json'), 'r', encoding='utf-8') as f:
        moves_data = json.load(f)
        for k, v in moves_data.items():
            raw_name = v.get("name", "")
            clean_name = raw_name.replace("MOVE_", "").replace("_", "").lower()
            raw_type = v.get("type", "TYPE_NORMAL")
            clean_type = raw_type.replace("TYPE_", "").capitalize()
            MOVE_DICT[clean_name] = clean_type
            if clean_name and raw_name != "MOVE_NONE":
                effect = v.get("effect", {}) or {}
                MOVE_INFO[clean_name] = {
                    "type": clean_type,
                    "class": v.get("class", "").replace("CLASS_", "").title(),
                    "power": v.get("power", 0),
                    "accuracy": v.get("accuracy", 0),
                    "pp": v.get("pp", 0),
                    "effect_type": effect.get("type", "BATTLE_EFFECT_HIT"),
                    "effect_chance": effect.get("chance", 0),
                    "description": "".join(v.get("description", [])).replace("\n", " ").strip(),
                }

# ==========================================
# UNIVERSAL TRAINER CARD BUILDER
# ==========================================
# Two trainers fight side by side as one merged combatant for three fights (see DUO_TRAINER_PAIRS in
# pokemon_ai_tournament.py's install_duo_trainers/apply_duo_roster): the merged trainer's own Trainer_Key is
# "{member_a_key}_and_{member_b_key}" (both members' keys carrying the same "hgss_" prefix when the dataset is Combined,
# since that prefix is applied to each member before joining, not once to the whole key). Listed here so their card can
# show both trainers' own sprites instead of just the first member's.
DUO_TRAINER_MEMBERS = {
    "commander_jupiter_spear_pillar_and_commander_mars_spear_pillar": ["commander_jupiter_spear_pillar", "commander_mars_spear_pillar"],
    "bug_catcher_jack_and_lass_briana": ["bug_catcher_jack", "lass_briana"],
    "leader_clair_clair_dd_and_champion_lance_dd": ["leader_clair_clair_dd", "champion_lance_dd"],
    "hgss_leader_clair_clair_dd_and_hgss_champion_lance_dd": ["leader_clair_clair_dd", "champion_lance_dd"],
}


def resolve_trainer_sprite_path(t_key_raw, t_class_raw, display_name, game_title, valid_pt_folders, hgss_files):
    """The sprite file for one trainer key/class (a duo's card calls this once per member, so it takes those three fields
    explicitly rather than pulling them from a standings.csv row - a duo's two members never get their own row there, since
    they play as a single merged combatant)."""
    t_key_raw = str(t_key_raw).lower()
    # Order matters: the Class column comes through as a space-separated string (e.g. "Trainerclass Pokefan M" - HGSS classes
    # without their own prettified name fall back to this raw "Trainerclass X" form; Platinum classes usually don't have the
    # prefix at all, e.g. "Ace Trainer Male"), so replacing "trainerclass_" (underscored) BEFORE turning spaces into
    # underscores never matches anything - it has to run after, or "trainerclass_" stays stuck on the front forever.
    t_class_raw = str(t_class_raw or "").lower().replace(' ', '_').replace('trainerclass_', '')
    clean_key = re.sub(r'_(rematch.*|postgame.*|game\d+.*|battleground.*)$', '', t_key_raw)

    trainer_path = None

    def resolve_platinum_path():
        """Platinum sprite-folder lookup, factored out so it can also serve as the HGSS branch's own failsafe below -
        some HGSS trainer classes (Bug Catcher, Swimmer, Ace Trainer, ...) never got their own sprite captured into
        HGSS_ASSETS_DIR, but the class itself usually has a Platinum sprite that's a fine stand-in rather than
        leaving the card with no trainer art at all."""
        target_folder = None
        special_map = {
            'champion_cynthia': 'champion_cynthia', 'leader_volkner_fight_area': 'leader_volkner', 'galactic_boss_cyrus_distortion_world': 'galactic_boss', 'galactic_boss_cyrus_celestic_town_ruins': 'galactic_boss', 'commander_mars_stark_mountain': 'commander_mars', 'commander_mars_spear_pillar': 'commander_mars', 'commander_saturn_galactic_hq': 'commander_saturn', 'commander_jupiter_stark_mountain': 'commander_jupiter'
        }
        if t_key_raw in special_map:
            target_folder = special_map[t_key_raw]
        if not target_folder:
            for length in range(len(clean_key.split('_')), 0, -1):
                cand = "_".join(clean_key.split('_')[:length])
                if cand in valid_pt_folders:
                    target_folder = cand
                    break
        if not target_folder:
            if t_class_raw in valid_pt_folders:
                target_folder = t_class_raw
            else:
                # Platinum's own gender-split folders are always the full word ("pokefan_male"/"pokefan_female", NEVER
                # "_m"/"_f" - see `ls res/trainers/classes`) - a class name that already ends in a short "_m"/"_f" marker
                # (HGSS's "Trainerclass Pokefan M" becomes t_class_raw "pokefan_m") needs that swapped for the full word,
                # not another suffix piled on top of it. A class with no marker at all (HGSS's female Pokefan is simply
                # "Pokefan", no letter - t_class_raw "pokefan") instead tries adding one.
                if t_class_raw.endswith('_m') or t_class_raw.endswith('_f'):
                    candidates = [t_class_raw[:-2] + ('_male' if t_class_raw.endswith('_m') else '_female')]
                else:
                    candidates = [t_class_raw + suf for suf in ('_male', '_female', '_m', '_f', 'm', 'f')]
                for cand in candidates:
                    if cand in valid_pt_folders:
                        target_folder = cand
                        break
        if not target_folder:
            matches = difflib.get_close_matches(clean_key, valid_pt_folders, n=1, cutoff=0.6)
            if matches: target_folder = matches[0]
        return os.path.join(TRAINER_SPRITE_DIR, target_folder, 'front.png') if target_folder else None

    if game_title == "HGSS" or t_key_raw.startswith("hgss_"):     # a Combined dataset mixes both games' keys row by row
        def clean_hgss_filename(filename):
            """Strips the file-naming boilerplate down to just the class name, folded to plain lowercase ASCII. Two things a
            trainer class's own name never has, but this asset dump's filenames sometimes do: a couple of sprites are DP-era
            art reused as-is ("Spr_DP_Pokéfan_M.png", not "Spr_HGSS_..."), and "Poké" (Pokéfan, Poké Maniac) carries an accent
            - both are normalized away here so the comparisons below can actually match them."""
            cleaned = re.sub(r'(?i)^(imgi_?\d*_*)*(spr_)?(hgss|dp)_', '', filename)
            return cleaned.replace('.png', '').replace('_', '').lower().replace('é', 'e')

        special_hgss_map = {
            'red': 'red', 'lance': 'lance', 'rival_': 'silver', 'bruno': 'bruno', 'karen': 'karen', 'will': 'will', 'koga': 'koga', 'falkner': 'falkner', 'bugsy': 'bugsy', 'whitney': 'whitney', 'morty': 'morty', 'chuck': 'chuck', 'jasmine': 'jasmine', 'pryce': 'pryce', 'clair': 'clair', 'brock': 'brock', 'misty': 'misty', 'surge': 'ltsurge', 'erika': 'erika', 'janine': 'janine', 'sabrina': 'sabrina', 'blaine': 'blaine', 'blue': 'blue', 'ethan': 'ethan', 'lyra': 'lyra'
        }

        display_lower = str(display_name or '').lower()
        gender_suffix = ""
        if re.search(r'\b(m|male)\b', display_lower): gender_suffix = "m"
        elif re.search(r'\b(f|female)\b', display_lower): gender_suffix = "f"

        t_class_flat = t_class_raw.replace('_', '')

        # Whole-token match, not substring: a raw `key in clean_key` matched "red" against the middle of "alfred" and
        # "jared" (both trainer_keys - "gentleman_alfred", "psychic_jared" - happen to contain that substring), handing
        # them Pokemon Trainer Red's sprite. clean_key's own underscore segments are its real name components, so a
        # special-map key only counts as a match when it IS one of those segments outright - "rival_" (trailing
        # underscore, matching every "rival_silver_<location>" variant) still works the same either way, since 'rival'
        # is always one of those segments too.
        clean_key_tokens = clean_key.split('_')
        for key, val in special_hgss_map.items():
            if not trainer_path and (key.rstrip('_') in clean_key_tokens):
                for f in hgss_files:
                    if val == clean_hgss_filename(f):
                        trainer_path = os.path.join(HGSS_ASSETS_DIR, f)
                        break

        if not trainer_path:
            for f in hgss_files:
                if t_class_flat == clean_hgss_filename(f):
                    trainer_path = os.path.join(HGSS_ASSETS_DIR, f)
                    break

        if not trainer_path and gender_suffix:
            for f in hgss_files:
                if t_class_flat + gender_suffix == clean_hgss_filename(f):
                    trainer_path = os.path.join(HGSS_ASSETS_DIR, f)
                    break

        parts = [p for p in clean_key.split('_') if len(p) > 2 or p in ['li', 'pi']]
        if not trainer_path:
            for p in parts:
                if trainer_path: break
                for f in hgss_files:
                    if p == clean_hgss_filename(f):
                        trainer_path = os.path.join(HGSS_ASSETS_DIR, f)
                        break

        if not trainer_path:
            search_terms = sorted([t_class_flat] + parts, key=len, reverse=True)
            for term in search_terms:
                if trainer_path: break
                if not term: continue
                for f in hgss_files:
                    if term in clean_hgss_filename(f):
                        trainer_path = os.path.join(HGSS_ASSETS_DIR, f)
                        break

        if not trainer_path:
            # Failsafe: every HGSS-specific match above failed (a real gap in HGSS_ASSETS_DIR's own sprite set, not a
            # bug - not every trainer class in this repo's HGSS asset dump got captured) - fall back to that same
            # class/key's Platinum sprite rather than showing nothing.
            trainer_path = resolve_platinum_path()
    else:
        trainer_path = resolve_platinum_path() or ""

    return trainer_path


def build_trainer_card(row, game_title, valid_pt_folders, hgss_files, rank_idx=None):
    t_key_raw = str(row.get('Trainer_Key', '')).lower()
    t_class_raw = str(row.get('Class', '')).lower().replace(' ', '_').replace('trainerclass_', '')
    display_name = str(row.get('Display_Name', ''))

    duo_members = DUO_TRAINER_MEMBERS.get(t_key_raw)
    if duo_members:
        # Neither member has its own standings.csv row (they play as this one merged combatant), so their class and exact
        # display name aren't available here - only their trainer keys are, which resolve_trainer_sprite_path can already
        # work from alone for these three pairs (member_names is a rough split of the merged display name, e.g. "Commander
        # Jupiter" / "Mars (Spear Pillar)" - good enough for its low-priority gender-suffix fallback).
        #
        # In a Combined dataset, game_title is "Combined", not "HGSS" - but resolve_trainer_sprite_path's HGSS/Platinum
        # branch only checks game_title=="HGSS" OR the passed-in key starting with "hgss_", and these individual member
        # keys never carry that prefix (only the merged duo key does, e.g. "hgss_leader_clair_clair_dd_and_..."). Without
        # this, an HGSS-origin duo's members silently fell into the Platinum branch and got difflib's closest-string
        # fuzzy match instead - "leader_clair_clair_dd" ~ "leader_roark", "champion_lance_dd" ~ "champion_cynthia" (the
        # only Platinum leader/champion folders that loosely resemble them) - real trainers, just the wrong ones.
        member_game_title = "HGSS" if t_key_raw.startswith("hgss_") else game_title
        member_names = display_name.split(" & ", 1) if " & " in display_name else ["", ""]
        sprite_paths = [
            resolve_trainer_sprite_path(member_key, "", member_names[i] if i < len(member_names) else "", member_game_title, valid_pt_folders, hgss_files)
            for i, member_key in enumerate(duo_members)
        ]
        trainer_sprite = "".join(get_sprite_html(p, "Sprite Missing", is_trainer=True, size=50) for p in sprite_paths)
        sprite_slot_width = 130
    else:
        trainer_path = resolve_trainer_sprite_path(t_key_raw, t_class_raw, display_name, game_title, valid_pt_folders, hgss_files)
        trainer_sprite = get_sprite_html(trainer_path, "Sprite Missing", is_trainer=True)
        sprite_slot_width = 80

    mon_cards_html = ""
    team_str = str(row.get('Team_and_Movesets', '-'))
    if team_str != "-":
        for mon_data in team_str.split(" | "):
            base_mon_name = mon_data.split(" Lv")[0].strip()
            base_mon_name = re.sub(r'\[.*?\]', '', base_mon_name).strip()
            
            item_name = None
            if '@' in base_mon_name:
                parts = base_mon_name.split('@', 1)
                mon_name = parts[0].strip()
                item_name = parts[1].strip()
            else:
                mon_name = base_mon_name

            if not mon_name: continue
                
            lvl_match = re.search(r'Lv\s*(\d+)', mon_data)
            lvl = lvl_match.group(1) if lvl_match else "??"
            # Only datasets regenerated after format_team_and_movesets started baking ability in (see
            # pokemon_ai_tournament.py) have it here - an older Team_and_Movesets just won't match, and the line
            # below is skipped entirely, same graceful-degradation pattern as the Tier/Role/KDA columns.
            ability_match = re.search(r'Lv\s*\d+\s*\(([^)]+)\)', mon_data)
            ability_text = ability_match.group(1) if ability_match else None

            safe_mon = mon_name.lower().replace(' ', '_').replace('.', '').replace('-', '_').replace("'", "")
            mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon, 'icon.png')
            
            if not os.path.exists(mon_path) and '_' in safe_mon:
                safe_mon_fallback = safe_mon.split('_')[0]
                mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon_fallback, 'icon.png')
                
            mon_icon = get_sprite_html(mon_path, mon_name, is_trainer=False)
            
            item_html = ""
            if item_name:
                safe_item = item_name.strip().lower().replace(" ", "_").replace(".", "").replace("'", "")
                item_path = os.path.join(ITEM_ICON_DIR, f"{safe_item}.png")
                item_html = get_sprite_html(item_path, item_name, is_item=True)

            moves_html = ""
            if ": " in mon_data:
                moves = mon_data.split(": ")[1].split("/")
                for m in moves:
                    clean_m = m.strip()
                    if clean_m and clean_m != "None":
                        search_key = clean_m.lower().replace(" ", "").replace("-", "")
                        m_type = MOVE_DICT.get(search_key, 'Normal')
                        bg_color = TYPE_COLORS.get(m_type, '#A8A77A')
                        
                        moves_html += f"<div style='background: {bg_color}; font-size: 10px; font-weight: bold; text-align: center; border-radius: 3px; padding: 2px 4px; color: white; text-shadow: 1px 1px 1px rgba(0,0,0,0.7); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' title='{clean_m}'>{clean_m}</div>"
            
            mon_role = mon_role_text(mon_name)
            role_line = f"<span style='font-size: 9px; color: #7AC74C;'>{mon_role}</span>" if mon_role else ""
            # Mirrors role_line's spot under the name on the left - same size, under the item/level on the right
            # instead, so the header row stays a clean two-column layout (name+role / item+level+ability) rather
            # than competing for space with the move grid below.
            ability_line = f"<div style='font-size: 9px; color: #4da6ff;'>{ability_text}</div>" if ability_text else ""

            mon_cards_html += (
                f"<div style='background: #2a2a2a; border-radius: 6px; padding: 6px;'>"
                f"<div style='display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;'>"
                f"<div style='display: flex; align-items: center; gap: 4px;'>{mon_icon} "
                f"<div style='display: flex; flex-direction: column; line-height: 1.2;'>"
                f"<span style='font-size: 13px; font-weight: bold; color: #fff;'>{mon_name}</span>{role_line}</div></div>"
                f"<div style='display: flex; flex-direction: column; align-items: flex-end; line-height: 1.2;'>"
                f"<div style='display: flex; align-items: center; gap: 4px;'>{item_html} <span style='font-size: 11px; color: #aaa; font-weight: bold;'>Lv.{lvl}</span></div>"
                f"{ability_line}"
                f"</div>"
                f"</div>"
                f"<div style='display: grid; grid-template-columns: 1fr 1fr; gap: 3px;'>{moves_html}</div>"
                f"</div>"
            )
    
    m_wins = str(row.get('Match_Wins', '0'))
    m_losses = str(row.get('Match_Losses', '0'))
    g_wins = str(row.get('Game_Wins', '0'))
    g_losses = str(row.get('Game_Losses', '0'))
    
    record = f"{m_wins} - {m_losses}"
    game_wl = f"{g_wins} - {g_losses}"
    
    notable_win = str(row.get('Greatest_Win', '-'))
    notable_loss = str(row.get('Worst_Loss', '-'))

    # Longest_Match_Vs (standings.csv) is this trainer's own single longest match BY GAME COUNT (a 7-game Tiebreak
    # match beats a 2-0 sweep) - "Opponent Name (N games)", or the literal string "None" if they never played one
    # longer than their shortest possible match. Older datasets predate this column entirely, hence the graceful
    # degradation to "" (no line rendered) rather than printing "nan"/"None".
    longest_match_raw = str(row.get('Longest_Match_Vs', '')).strip()
    longest_match_html = (
        f"<div style='color: #4da6ff;'>Longest Match: <span style='color: #ccc;'>{longest_match_raw}</span></div>"
        if longest_match_raw and longest_match_raw not in ('nan', 'None', '-') else ""
    )

    tier = str(row.get('Tier', 'Unranked'))
    if tier == "nan" or tier == "-": tier = "Unranked"

    try:
        w, l = int(float(m_wins)), int(float(m_losses))
        ratio = f"{(w / (w + l) * 100):.1f}%" if (w+l) > 0 else "0%"
    except:
        ratio = "N/A"

    elo_str = str(row.get('Elo', '0'))
    try:
        elo_fmt = f"{float(elo_str):.1f}"
    except:
        elo_fmt = "N/A"
    
    rank_html = f"<div style='font-size: 12px; color: #888; font-weight: bold; text-transform: uppercase;'>Rank #{rank_idx}</div>" if rank_idx else ""

    card = (
        f"<div style='background: #1e1e1e; border: 1px solid #444; border-radius: 8px; padding: 15px; width: 450px; color: #eee; box-shadow: 2px 2px 8px rgba(0,0,0,0.3); margin-bottom: 20px;'>"
        f"<div style='display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 10px; margin-bottom: 12px;'>"
        f"<div style='flex-grow: 1;'>"
        f"{rank_html}"
        f"<h3 style='margin: 5px 0; color: #ff7f50; font-size: 18px;'>{str(row.get('Display_Name', 'Unknown'))}</h3>"
        f"<div style='font-size: 14px; margin-top: 5px;'><span style='background: #333; padding: 2px 6px; border-radius: 4px; color: #fff; font-weight: bold;'>{tier}</span> &nbsp;Elo: {elo_fmt}</div>"
        f"<div style='font-size: 13px; color: #aaa; margin-top: 5px;'><strong>Match W/L:</strong> {record} ({ratio}) &nbsp;|&nbsp; <strong>Game W/L:</strong> {game_wl}</div>"
        f"<div style='font-size: 11px; color: #888; margin-top: 6px; background: #222; padding: 6px; border-radius: 4px;'>"
        f"<div style='color: #7AC74C; margin-bottom: 2px;'>Best Win: <span style='color: #ccc;'>{notable_win}</span></div>"
        f"<div style='color: #ff6b6b;'>Worst Loss: <span style='color: #ccc;'>{notable_loss}</span></div>"
        f"{longest_match_html}"
        f"</div>"
        f"</div>"
        f"<div style='width: {sprite_slot_width}px; text-align: right; display: flex; align-items: center; justify-content: center; gap: 4px; margin-right: 15px;'>{trainer_sprite}</div>"
        f"</div>"
        f"<div style='display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px;'>{mon_cards_html}</div>"
        f"</div>"
    )
    return card

# ==========================================
# TAB 1: BATTLE LOG VIEWER
# ==========================================
with tab_logs:
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        t1_name = st.selectbox("Select Trainer 1", t1_names if t1_names else ["No trainers match filters"])

    t2_options = t2_names
    if min_games_filter > 2 and t1_name != "No trainers match filters":
        t1_key = trainer_dict[t1_name]
        t1_display_safe = safe_filename(t1_name)
        
        valid_t2s = []
        if REPLAY_INFO:
            games_vs = replay_games_vs(suffix, raw_trainer_name(t1_name))
            valid_t2s = [t2 for t2 in t2_names if t2 != t1_name and games_vs.get(raw_trainer_name(t2), 0) >= min_games_filter]
        else:
            for t2 in t2_names:
                if t2 == t1_name: continue
                t2_key = trainer_dict[t2]
                t2_display_safe = safe_filename(t2)

                possible_filenames = [
                    f"{t1_display_safe}_vs_{t2_display_safe}_game{min_games_filter}.txt",
                    f"{t2_display_safe}_vs_{t1_display_safe}_game{min_games_filter}.txt",
                    f"{t1_key}_vs_{t2_key}_game{min_games_filter}.txt",
                    f"{t2_key}_vs_{t1_key}_game{min_games_filter}.txt"
                ]

                if any(f in available_logs for f in possible_filenames):
                    valid_t2s.append(t2)

        t2_options = valid_t2s

    with col2:
        default_idx = 1 if len(t2_options) > 1 and t2_options[0] == t1_name else 0
        t2_name = st.selectbox("Select Trainer 2", t2_options if t2_options else ["No matching opponents found"], index=default_idx)

    invalid_placeholders = ["No trainers match filters", "No matching opponents found"]

    # Only offer the games that actually have a log between THESE two trainers, instead of a blind 1-7 (a match is at
    # most a 7-game Tiebreak, but almost every match ends well before that, e.g. a 2-0 sweep only ever has Game 1/2).
    available_game_nums = []
    if t1_name and t2_name and t1_name not in invalid_placeholders and t2_name not in invalid_placeholders and t1_name != t2_name:
        t1_key_probe = trainer_dict[t1_name]
        t2_key_probe = trainer_dict[t2_name]
        t1_disp_safe_probe = safe_filename(t1_name)
        t2_disp_safe_probe = safe_filename(t2_name)
        if REPLAY_INFO:
            available_game_nums = list(range(1, replay_games_vs(suffix, raw_trainer_name(t1_name)).get(raw_trainer_name(t2_name), 0) + 1))
        for i in ([] if REPLAY_INFO else range(1, 8)):
            gs = f"game{i}"
            probe_filenames = [
                f"{t1_disp_safe_probe}_vs_{t2_disp_safe_probe}_{gs}.txt",
                f"{t2_disp_safe_probe}_vs_{t1_disp_safe_probe}_{gs}.txt",
                f"{t1_key_probe}_vs_{t2_key_probe}_{gs}.txt",
                f"{t2_key_probe}_vs_{t1_key_probe}_{gs}.txt",
            ]
            if any(f in available_logs for f in probe_filenames):
                available_game_nums.append(i)

    with col3:
        game_opts = [f"Game {i}" for i in available_game_nums] if available_game_nums else ["Game 1"]
        game_num = st.selectbox("Select Game", game_opts)

    if t1_name and t2_name and t1_name not in invalid_placeholders and t2_name not in invalid_placeholders:
        if t1_name == t2_name:
            st.warning("Please select two different trainers.")
        else:
            t1_key = trainer_dict[t1_name]
            t2_key = trainer_dict[t2_name]
            
            t1_display_safe = safe_filename(t1_name)
            t2_display_safe = safe_filename(t2_name)
            game_suffix = game_num.replace(" ", "").lower()
            
            possible_filenames = [
                f"{t1_display_safe}_vs_{t2_display_safe}_{game_suffix}.txt",
                f"{t2_display_safe}_vs_{t1_display_safe}_{game_suffix}.txt",
                f"{t1_key}_vs_{t2_key}_{game_suffix}.txt",
                f"{t2_key}_vs_{t1_key}_{game_suffix}.txt"
            ]
            
            target_filename = next((f for f in possible_filenames if f in available_logs), None)
            log_content = None
            rebuilt_note = None
            replay_failed = False

            if REPLAY_INFO:
                match_row = replay_match_row(suffix, raw_trainer_name(t1_name), raw_trainer_name(t2_name))
                if match_row is not None:
                    game_n = int(game_num.split()[-1])
                    try:
                        with st.spinner("Rebuilding this battle from its seed..."):
                            rebuilt = rebuild_match_logs(suffix, match_row["Trainer_A"], match_row["Trainer_B"], match_row["Seed_Base"])
                        log_content = rebuilt["logs"].get(game_n)
                        if rebuilt["score"] != [match_row["Score_A"], match_row["Score_B"]] or rebuilt["turns"] != match_row["Total_Turns"]:
                            st.warning("The rebuilt match does not reproduce this match's recorded result - treat this log with caution.")
                        rebuilt_note = (f"Rebuilt from the match seed {match_row['Seed_Base']} with engine version {REPLAY_INFO['version_id']} "
                                        f"- the same battle the tournament played, no stored log.")
                    except Exception as replay_err:
                        replay_failed = True
                        st.error(f"Could not rebuild this battle ({type(replay_err).__name__}: {replay_err}).")
            elif target_filename:
                raw_path = os.path.join(results_dir, target_filename)
                if os.path.exists(raw_path):
                    with open(raw_path, 'r', encoding='utf-8') as f:
                        log_content = f.read()
                else:
                    # Same "walk until missing" fix as get_available_logs() above - see its own comment.
                    i = 1
                    while os.path.exists(f"{results_dir}_part{i}.zip"):
                        zip_path = f"{results_dir}_part{i}.zip"
                        with zipfile.ZipFile(zip_path, 'r') as z:
                            zip_files = z.namelist()
                            path_with_dir = f"{results_dir}/{target_filename}"
                            actual_zip_path = path_with_dir if path_with_dir in zip_files else (target_filename if target_filename in zip_files else None)

                            if actual_zip_path:
                                with z.open(actual_zip_path) as f:
                                    log_content = f.read().decode('utf-8')
                                break
                        if log_content:
                            break
                        i += 1

            if log_content:
                safe_text = html.escape(log_content, quote=False)
                safe_text = re.sub(r'^[ ]{2,4}', '&nbsp;&nbsp;&nbsp;&nbsp;', safe_text, flags=re.MULTILINE)
                safe_text = re.sub(r'(X\s+.*?\s+fainted!)', r'<span style="color: #ff6b6b; font-weight: bold; background: rgba(255, 107, 107, 0.15); padding: 1px 6px; border-radius: 4px;">\1</span>', safe_text)
                safe_text = re.sub(r'([A-Za-z0-9\-\']+\'s\s+[A-Za-z\s]+\s+lowered\s+[A-Za-z0-9\-\'\s]+!|[A-Za-z0-9\-\']+\'s\s+(?:ATK|DEF|SPD|SPATK|SPDEF)\s+fell.*?!|[A-Za-z0-9\-\']+\'s\s+Intimidate.*?!|Critical hit!|Super effective!)', r'<span style="color: #4da6ff; font-weight: bold; background: rgba(77, 166, 255, 0.15); padding: 1px 6px; border-radius: 4px;">\1</span>', safe_text)
                safe_text = re.sub(r'([A-Za-z0-9\-\']+\s+(?:restored health|ate its|hung on using its)\s+.*?!|\bHP was restored\.)', r'<span style="color: #ffd700; font-weight: bold; background: rgba(255, 215, 0, 0.15); padding: 1px 6px; border-radius: 4px;">\1</span>', safe_text)
                safe_text = re.sub(r'(\bThe weather became.*?!|\bThe sunlight faded.*?!|.*?\bwas afflicted with.*?!|.*?\bwoke up!|.*?\bis fast asleep\.)', r'<span style="color: #ce93d8; font-weight: bold; background: rgba(206, 147, 216, 0.15); padding: 1px 6px; border-radius: 4px;">\1</span>', safe_text)

                if expand_log:
                    st.markdown(f"<div style=\"font-family: 'Courier New', monospace; white-space: pre-wrap; line-height: 1.5;\">{safe_text}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style=\"height: 520px; overflow-y: auto; background-color: #1e1e1e; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; white-space: pre-wrap; line-height: 1.5; color: #d4d4d4; border: 1px solid #333;\">{safe_text}</div>", unsafe_allow_html=True)
                
                st.caption(rebuilt_note or f"Loaded log: `{target_filename}`")
            elif not replay_failed:             # (a failed rebuild already showed its own error above)
                if game_num == "Game 3" and min_games_filter < 3:
                    st.info("No Game 3 log found. This match likely ended in a 2-0 sweep!")
                else:
                    st.error(f"Could not find a battle log for **{t1_name}** vs **{t2_name}**.")

# ==========================================
# TAB 2: ANALYTICS DASHBOARD
# ==========================================
with tab_analytics:
    st.header("Tournament Analytics")

    indiv_path = dp(f"analytics_individuals{suffix}.csv")
    if not os.path.exists(indiv_path) and os.path.exists(dp("analytics_individuals.csv")):
        indiv_path = dp("analytics_individuals.csv")

    tourn_path = dp(f"analytics_tournament{suffix}.csv")

    df_species = df_species_global      # loaded once near the top of the page - see SPECIES_ROLE/SPECIES_TIER
    df_indiv = load_data(indiv_path)
    df_tourn = load_data(tourn_path)
    
    rng_tooltip = "A calculated metric of RNG fortune. Positive numbers indicate 'Good Luck' (more Critical Hits/Secondary Effects, fewer Misses than average). Negative numbers indicate 'Bad Luck'."
    
    def parse_moves(m_str):
        if pd.isna(m_str) or m_str == "-": return pd.DataFrame(columns=['Move', 'Count'])
        matches = re.findall(r'([A-Za-z0-9\s-]+):\s*(\d+)', m_str)
        return pd.DataFrame({'Move': [m[0].strip() for m in matches], 'Count': [int(m[1]) for m in matches]})
        
    if df_species is not None and df_indiv is not None:
        species_list = sorted(df_species['Species'].dropna().unique().tolist())

        # Same key-vs-index precedence issue as the Trainer Database tab: a Move Analytics species click has to force
        # BOTH the mode radio and the species selectbox's session_state directly, before either widget is created.
        if st.session_state.analytics_mode_pending_jump:
            jump_species = st.session_state.analytics_mode_pending_jump
            st.session_state["analytics_mode_radio"] = "Species Data"
            if jump_species in species_list:
                st.session_state["analytics_species_select"] = jump_species
            st.session_state.analytics_mode_pending_jump = None

        # Same for a move jump (a click on the Species Data donut, or on a Mimic-used move) - the actual selectbox
        # value is only set once the Move Analytics branch below has computed its own valid move list.
        if st.session_state.get("move_analytics_pending_jump"):
            st.session_state["analytics_mode_radio"] = "Move Analytics"

        view_mode_analytics = st.radio("Analytics Mode:", ["All Tournament Data", "Species Data", "Move Analytics"],
                                        horizontal=True, key="analytics_mode_radio")
        st.markdown("---")
        
        valid_pt_folders = get_valid_trainer_folders(TRAINER_SPRITE_DIR)
        hgss_files = get_hgss_sprites(HGSS_ASSETS_DIR)
            
        if view_mode_analytics == "All Tournament Data":
            st.write("Data reflects the macro performance metrics aggregated across all simulated matches.")
            
            # Moves executed frequency
            move_counter = {}
            for moves_str in df_species['Global_Move_Usage'].dropna():
                matches = re.findall(r'([A-Za-z0-9\s-]+):\s*(\d+)', moves_str)
                for move, count in matches:
                    move = move.strip()
                    move_counter[move] = move_counter.get(move, 0) + int(count)
            m_df_global = pd.DataFrame(list(move_counter.items()), columns=['Move', 'Execution Count']).sort_values('Execution Count', ascending=False).head(15)

            col_pie, col_bar = st.columns(2)
            with col_pie:
                if not m_df_global.empty:
                    m_df_global['Type'] = m_df_global['Move'].apply(lambda x: MOVE_DICT.get(x.lower().replace(" ", "").replace("-", ""), 'Normal'))
                    m_df_global['Color'] = m_df_global['Type'].apply(lambda x: TYPE_COLORS.get(x, '#A8A77A'))
                    color_map = {row['Move']: row['Color'] for i, row in m_df_global.iterrows()}
                    
                    fig_pie = px.pie(m_df_global, values='Execution Count', names='Move', title="Top 15 Most Executed Moves", hole=0.3, color='Move', color_discrete_map=color_map)
                    fig_pie.update_traces(textinfo='value+label')
                    st.plotly_chart(fig_pie, use_container_width=True)
                    
            with col_bar:
                top_killers = df_species.sort_values(by='Total_KOs', ascending=False).head(15)
                fig_bar = px.bar(top_killers, x='Total_KOs', y='Species', title="Top 15 Deadliest Pokémon (By Total KOs)", orientation='h')
                fig_bar.update_layout(yaxis={'categoryorder':'total ascending'})
                fig_bar.update_traces(marker_color='#ff7f50')
                st.plotly_chart(fig_bar, use_container_width=True)

            # --- Tournament-wide aggregates (analytics_tournament.csv - one row, computed once after the whole run) ---
            if df_tourn is not None:
                st.subheader("Advanced Combat Metrics")
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    if 'Deadliest_Moves' in df_tourn.columns:
                        dm_df = parse_moves(df_tourn['Deadliest_Moves'].iloc[0]).head(10)
                        fig_dm = px.bar(dm_df, x='Count', y='Move', title="Deadliest Moves (Most KOs)", orientation='h')
                        fig_dm.update_layout(yaxis={'categoryorder':'total ascending'})
                        st.plotly_chart(fig_dm, use_container_width=True)
                with col_m2:
                    if 'Item_Activation_Counts' in df_tourn.columns:
                        item_df = parse_moves(df_tourn['Item_Activation_Counts'].iloc[0]).head(10)
                        fig_items = px.bar(item_df, x='Count', y='Move', title="Most Frequently Triggered Items", orientation='h')
                        fig_items.update_layout(yaxis={'categoryorder':'total ascending'})
                        fig_items.update_traces(marker_color='#4da6ff')
                        st.plotly_chart(fig_items, use_container_width=True)

                if 'Average_Game_Length_Turns' in df_tourn.columns:
                    len_col1, len_col2 = st.columns(2)
                    len_col1.metric("Average Game Length", f"{df_tourn['Average_Game_Length_Turns'].iloc[0]:.1f} turns")
                    len_col2.metric("Average Match Length", f"{df_tourn['Average_Match_Length_Turns'].iloc[0]:.1f} turns",
                                     help="Summed across every game of a Tiebreak match (2-7 games), not one game's own length.")

            # --- TOURNAMENT RECORDS: the rest of what analytics_species.csv / analytics_individuals.csv track but had no
            # aggregate view anywhere yet - Luck_Score and Switch_In_Casualties both already exist per-species, just never
            # ranked against the rest of the field before. (Lead_Win_Rate is still shown per-trainer-mon, in the Trainer
            # Database tab's "Matchup Context" expander - just not ranked here anymore.) ---
            st.subheader("Tournament Records")
            rec_col1, rec_col2 = st.columns(2)
            with rec_col1:
                luck_ranked = df_species[['Species', 'Luck_Score']].dropna().sort_values('Luck_Score', ascending=False)
                if not luck_ranked.empty:
                    fig_luck = px.bar(luck_ranked.head(8), x='Luck_Score', y='Species', orientation='h', title="Luckiest Species")
                    fig_luck.update_layout(yaxis={'categoryorder': 'total ascending'})
                    fig_luck.update_traces(marker_color='#7AC74C')
                    st.plotly_chart(fig_luck, use_container_width=True)
            with rec_col2:
                if not luck_ranked.empty:
                    fig_unluck = px.bar(luck_ranked.tail(8), x='Luck_Score', y='Species', orientation='h', title="Unluckiest Species")
                    fig_unluck.update_layout(yaxis={'categoryorder': 'total descending'})
                    fig_unluck.update_traces(marker_color='#ff6b6b')
                    st.plotly_chart(fig_unluck, use_container_width=True)

            st.subheader("Complete Species Data")
            species_cols = (['Species'] + (['Tier', 'Role'] if 'Tier' in df_species.columns else [])
                             + ['Total_KOs', 'Total_Deaths', 'Global_KDR']
                             + (['Total_Assists', 'KDA'] if 'KDA' in df_species.columns else [])
                             + ['Global_Average_Lifespan_Turns', 'Luck_Score']
                             + (['Assist_Breakdown'] if 'Assist_Breakdown' in df_species.columns else []))
            display_species = df_species[species_cols].copy()
            sort_col = 'KDA' if 'KDA' in display_species.columns else 'Total_KOs'
            st.dataframe(display_species.sort_values(by=sort_col, ascending=False), use_container_width=True)

            st.subheader("Complete Individual Data")
            indiv_cols = (['Trainer_Key', 'Species', 'KOs', 'Deaths', 'KDR']
                          + (['Total_Assists', 'KDA'] if 'KDA' in df_indiv.columns else [])
                          + ['AI_Switching_Frequency', 'Luck_Score']
                          + (['Assist_Breakdown'] if 'Assist_Breakdown' in df_indiv.columns else []))
            display_indiv = df_indiv[indiv_cols].copy()
            sort_col_i = 'KDA' if 'KDA' in display_indiv.columns else 'KOs'
            st.dataframe(display_indiv.sort_values(by=sort_col_i, ascending=False), use_container_width=True)

        elif view_mode_analytics == "Species Data":
            st.write("Analyzes how a specific Pokémon species performed universally across all trainers who used it.")

            selected_species = st.selectbox("Select Pokémon Species", species_list, key="analytics_species_select")
            
            if selected_species:
                s_data = df_species[df_species['Species'] == selected_species].iloc[0]
                
                safe_mon = selected_species.lower().replace(' ', '_').replace('.', '').replace('-', '_').replace("'", "")
                mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon, 'icon.png')
                if not os.path.exists(mon_path) and '_' in safe_mon:
                    mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon.split('_')[0], 'icon.png')
                mon_icon = get_sprite_html(mon_path, selected_species.title(), is_trainer=False)
                
                badges = f"{tier_badge_html(s_data.get('Tier'))} {role_badge_html(s_data.get('Role'), s_data.get('Tier'))}" if 'Tier' in df_species.columns else ""
                st.markdown(f"<h3 style='display:flex; align-items:center; gap:10px;'>{mon_icon} {selected_species.title()} Global Stats {badges}</h3>", unsafe_allow_html=True)

                static_info = get_species_static_info(selected_species)
                if static_info and static_info["base_stats"]:
                    bs_col, ab_col = st.columns([2, 1])
                    with bs_col:
                        st.caption("Base Stats")
                        stat_order = [("hp", "HP"), ("attack", "Attack"), ("defense", "Defense"),
                                      ("special_attack", "Sp. Atk"), ("special_defense", "Sp. Def"), ("speed", "Speed")]
                        bs_df = pd.DataFrame([{"Stat": label, "Value": static_info["base_stats"].get(key, 0)}
                                               for key, label in stat_order])
                        fig_bs = px.bar(bs_df, x="Value", y="Stat", orientation="h", text="Value", range_x=[0, 255])
                        fig_bs.update_layout(yaxis={"categoryorder": "array", "categoryarray": [l for _, l in stat_order][::-1]},
                                              height=230, showlegend=False, margin=dict(l=0, r=10, t=10, b=0))
                        fig_bs.update_traces(marker_color="#4da6ff", textposition="outside")
                        st.plotly_chart(fig_bs, use_container_width=True)
                    with ab_col:
                        st.caption("Type")
                        if static_info["types"]:
                            st.markdown("".join(
                                f"<span style='background:{TYPE_COLORS.get(t, '#A8A77A')}; color:#111; font-weight:bold; "
                                f"border-radius:4px; padding:2px 9px; font-size:12px; margin-right:4px;'>{t}</span>"
                                for t in static_info["types"]), unsafe_allow_html=True)
                        st.caption("Possible Abilities")
                        st.write(", ".join(static_info["abilities"]) if static_info["abilities"] else "Unknown")
                    st.markdown("---")

                has_kda = 'KDA' in s_data.index
                cols = st.columns(6 if has_kda else 5)
                cols[0].metric("Global KDR", f"{s_data.get('Global_KDR', 0):.2f}",
                                help="Total_KOs / max(1, Total_Deaths) across every trainer who fielded this species.")
                if has_kda:
                    cols[1].metric("KDA", f"{s_data.get('KDA', 0):.2f}", help="(Kills + Assists) / max(1, Deaths) - see the Tier List tab for how species are ranked by this.")
                    rest = cols[2:]
                else:
                    rest = cols[1:]
                rest[0].metric("Avg Lifespan (Turns)", f"{s_data.get('Global_Average_Lifespan_Turns', 0):.2f}",
                                help="Average number of turns this species stayed on the field per game it appeared in, counting from the turn it switched/sent in to the turn it fainted (or the game ended).")
                rest[1].metric("Total KOs", s_data.get('Total_KOs', 0),
                                help="Total knockouts this species landed across every trainer that used it, in every game of this dataset.")
                rest[2].metric("RNG / Luck Score", f"{s_data.get('Luck_Score', 0):.2f}", help=rng_tooltip)
                rest[3].metric("Games Appeared In", s_data.get('Games_Seen', 0),
                                help="How many individual games (not matches) this species was sent out in at least once, across every trainer that used it.")

                if 'Assist_Breakdown' in s_data.index:
                    breakdown = parse_assist_breakdown(s_data.get('Assist_Breakdown'))
                    if breakdown and s_data.get('Total_Assists', 0):
                        ab_df = pd.DataFrame(list(breakdown.items()), columns=['Category', 'Count'])
                        fig_ab = px.bar(ab_df, x='Count', y='Category', orientation='h',
                                        title=f"What {selected_species.title()}'s {int(s_data.get('Total_Assists', 0))} assists were for")
                        fig_ab.update_layout(yaxis={'categoryorder': 'total ascending'})
                        fig_ab.update_traces(marker_color='#7AC74C')
                        st.plotly_chart(fig_ab, use_container_width=True)

                with st.expander("View Detailed RNG & Luck Metrics"):
                    st.write(f"**Critical Hits Landed:** {s_data.get('Critical_Hits', 0)}")
                    st.write(f"**Secondary Effects Triggered:** {s_data.get('Secondary_Effect_Procs', 0)}")
                    st.write(f"**Moves Missed:** {s_data.get('Missed_Attacks', 0)}")

                with st.expander("Matchup Analysis"):
                    best_matchups = s_data.get('Most_KOs_Against', 'Data not yet generated.')
                    worst_matchups = s_data.get('Killed_Most_By', 'Data not yet generated.')
                    st.write(f"**Top Targets (Most KOs Against):** {best_matchups}")
                    st.write(f"**Greatest Threats (Killed Most By):** {worst_matchups}")

                m_df = parse_moves(s_data.get('Global_Move_Usage', ''))
                if not m_df.empty:
                    DONUT_TOP_N = 15
                    donut_df = cap_for_donut(m_df, top_n=DONUT_TOP_N).copy()
                    donut_df['Type'] = donut_df['Move'].apply(
                        lambda x: 'Other' if x == 'Other' else MOVE_DICT.get(x.lower().replace(" ", "").replace("-", ""), 'Normal'))
                    donut_df['Color'] = donut_df['Type'].apply(lambda x: '#555555' if x == 'Other' else TYPE_COLORS.get(x, '#A8A77A'))

                    color_map = {row['Move']: row['Color'] for i, row in donut_df.iterrows()}
                    fig = px.pie(donut_df, values='Count', names='Move', title=f"Moves Executed by {selected_species.title()}", hole=0.3, color='Move', color_discrete_map=color_map)
                    # Plotly pie/donut traces aren't one of the trace types Streamlit's own on_select click/selection
                    # wiring supports (bar/scatter/histogram/box are - confirmed empirically: plain clicks AND box-drags
                    # over a pie here never populate a selection), so the donut itself can't be made clickable. A row of
                    # small buttons directly below it - one per slice, same color swatch - gives the same "click a move to
                    # open its data page" outcome the donut can't provide on its own.
                    st.plotly_chart(fig, use_container_width=True)
                    if len(m_df) > DONUT_TOP_N:
                        st.caption(f"Showing the top {DONUT_TOP_N} of {len(m_df)} moves ever executed by "
                                   f"{selected_species.title()} - the rest are grouped into \"Other\" so the chart "
                                   "stays readable. Every move is still listed (and clickable) in the filterable grid below.")

                    # Mimic permanently copies a move from an opponent mid-battle - it isn't part of this species' own
                    # moveset, so keeping it in the chart above would credit e.g. Budew with "using" whatever move its
                    # Mimic slot last happened to copy. Mimic_Move_Usage only exists in datasets run after that split
                    # was added (see mimic_move_usage / mimic_active in pokemon_ai_tournament.py) - older datasets just
                    # don't show this section, same graceful-degradation pattern as the Tier/Role/KDA columns.
                    # Placed HERE, directly under the donut, rather than after the (potentially 100+ button, one per
                    # move ever used) grid below - a heavily-played species can have a long tail of tiny-percentage
                    # moves that pushes anything placed after that grid many screens down.
                    if 'Mimic_Move_Usage' in df_species.columns:
                        mimic_df = parse_moves(s_data.get('Mimic_Move_Usage', ''))
                        if not mimic_df.empty:
                            st.subheader("Moves Used via Mimic")
                            st.caption(f"{selected_species.title()} knows Mimic, so these were temporarily copied from an "
                                       "opponent mid-battle rather than being part of its own moveset - kept separate "
                                       "from the chart above so it isn't cluttered with whatever it happened to copy. "
                                       "Note that the chart above still reflects the ORIGINAL tournament's full sample - "
                                       "moves it mimicked before this tracking existed are still baked into it and "
                                       "can't be retroactively removed without re-simulating that whole tournament.")
                            st.dataframe(mimic_df.sort_values('Count', ascending=False), use_container_width=True, hide_index=True)
                            st.markdown("---")

                    full_move_df = m_df.sort_values('Count', ascending=False).reset_index(drop=True)

                    def _render_move_grid(df_to_show):
                        move_btn_cols = st.columns(4)
                        for mv_idx, mv_row in df_to_show.iterrows():
                            with move_btn_cols[mv_idx % 4]:
                                if st.button(f"{mv_row['Move']} ({int(mv_row['Count'])})",
                                             key=f"sdmovebtn_{selected_species}_{mv_row['Move']}", use_container_width=True):
                                    st.session_state.move_analytics_pending_jump = mv_row['Move']
                                    st.rerun()

                    # Past this many, the grid (and the filter box that comes with it) moves into a collapsed
                    # expander - closed by default, so a well-traveled species' 100+ move buttons don't bury
                    # "Trainers Using X" (and everything else on the page) many screens down; open it back up with
                    # one click when actually browsing the full list. Keyed per-species so the filter text starts
                    # fresh rather than carrying over a query that no longer matches after switching species.
                    GRID_EXPAND_THRESHOLD = 12
                    if len(full_move_df) > GRID_EXPAND_THRESHOLD:
                        with st.expander(f"Show all {len(full_move_df)} moves executed by {selected_species.title()}"):
                            st.caption("Click a move below to open it in Move Analytics.")
                            grid_search = st.text_input("Filter moves", key=f"sdmove_search_{selected_species}",
                                                         placeholder="e.g. Earthquake")
                            grid_df = (full_move_df[full_move_df['Move'].str.contains(grid_search, case=False, na=False)]
                                       if grid_search else full_move_df).reset_index(drop=True)
                            if grid_search and grid_df.empty:
                                st.info(f"No move matches \"{grid_search}\".")
                            _render_move_grid(grid_df)
                    else:
                        st.caption("Click a move below to open it in Move Analytics.")
                        _render_move_grid(full_move_df)

                st.markdown("---")
                st.subheader(f"Trainers Using {selected_species.title()}")
                sd_trainer_keys = SPECIES_TRAINER_INDEX.get(selected_species.upper(), [])
                if not sd_trainer_keys:
                    st.info("No trainers in this dataset field this species.")
                else:
                    st.caption(f"{len(sd_trainer_keys)} trainer(s). Click one to open their Trainer Database profile - "
                               f"their own moveset for {selected_species.title()} is shown below their name, since "
                               "different trainers can run it differently.")
                    sd_trb_cols = st.columns(3)
                    for idx, k in enumerate(sd_trainer_keys):
                        t_row_sd = df[df['Trainer_Key'] == k]
                        t_row_sd = t_row_sd.iloc[0] if not t_row_sd.empty else None
                        t_class_sd = str(t_row_sd.get('Class', '')).lower().replace(' ', '_').replace('trainerclass_', '') if t_row_sd is not None else ""
                        t_display_sd = t_row_sd.get('Display_Name', key_to_name.get(k, k)) if t_row_sd is not None else key_to_name.get(k, k)
                        t_sprite_path_sd = resolve_trainer_sprite_path(k, t_class_sd, t_display_sd, game_title, valid_pt_folders, hgss_files)
                        t_sprite_sd = get_sprite_html(t_sprite_path_sd, "Sprite Missing", is_trainer=True, size=50)
                        moves_sd = get_trainer_species_moveset(k, selected_species.upper())
                        with sd_trb_cols[idx % 3]:
                            st.markdown(f"<div style='text-align:center;'>{t_sprite_sd}</div>", unsafe_allow_html=True)
                            if st.button(key_to_name.get(k, k), key=f"sdtrb_{selected_species}_{k}", use_container_width=True):
                                st.session_state.selected_trainer_key = k
                                st.session_state.trainerdb_pending_jump = True
                                st.rerun()
                            st.markdown(
                                f"<div style='text-align:center; margin-top:-4px; background:#222; border-radius:4px; padding:5px;'>"
                                f"{moveset_chips_html(moves_sd)}</div>",
                                unsafe_allow_html=True,
                            )
                    if st.session_state.selected_trainer_key in sd_trainer_keys:
                        st.success(f"Selected **{key_to_name.get(st.session_state.selected_trainer_key)}** - "
                                   "open the Trainer Database tab to view their full profile.")

        elif view_mode_analytics == "Move Analytics":
            st.write("Pick any move to see its game data and every Pokémon that actually used it in this tournament.")
            st.caption("Misses/crits/secondary-effect procs are only tracked in aggregate per Pokémon (across ALL of its "
                       "moves), never narrowed down to one specific move - see a Pokémon's own RNG metrics under Species "
                       "Data for those.")

            # Union of every move that shows up in ANY species' actual usage log (not the full ~460-move game list - a
            # move nothing in this dataset ever used has nothing to analyze).
            move_usage_by_species = {}   # Species -> {Move: Count}
            move_totals = Counter()
            for _, srow in df_species.iterrows():
                m_df_this = parse_moves(srow.get('Global_Move_Usage', ''))
                if m_df_this.empty:
                    continue
                move_usage_by_species[srow['Species']] = dict(zip(m_df_this['Move'], m_df_this['Count']))
                for mv, cnt in zip(m_df_this['Move'], m_df_this['Count']):
                    move_totals[mv] += int(cnt)

            all_moves = sorted(move_totals.keys())
            if not all_moves:
                st.info("No move-usage data in this dataset.")
            else:
                def _move_type(mv_name):
                    return MOVE_INFO.get(mv_name.lower().replace(" ", "").replace("-", ""), {}).get('type', 'Normal')

                def _move_class(mv_name):
                    return MOVE_INFO.get(mv_name.lower().replace(" ", "").replace("-", ""), {}).get('class', '?')

                fcol1, fcol2 = st.columns(2)
                with fcol1:
                    type_filter = st.selectbox("Filter by Type", ["All"] + sorted(TYPE_COLORS.keys()), key="move_analytics_type_filter")
                with fcol2:
                    class_filter = st.selectbox("Filter by Class", ["All", "Physical", "Special", "Status"], key="move_analytics_class_filter")

                filtered_moves = all_moves
                if type_filter != "All":
                    filtered_moves = [mv for mv in filtered_moves if _move_type(mv) == type_filter]
                if class_filter != "All":
                    filtered_moves = [mv for mv in filtered_moves if _move_class(mv) == class_filter]

                # A move click (Species Data's donut, or a Mimic-used-moves entry) forces this selectbox's own
                # session_state directly, same one-shot pattern as analytics_mode_pending_jump above - but only once
                # the filtered list above is known, since the jump target might not survive the current Type/Class filter.
                if st.session_state.get("move_analytics_pending_jump"):
                    jump_move = st.session_state.move_analytics_pending_jump
                    if jump_move in filtered_moves:
                        st.session_state["move_analytics_select"] = jump_move
                    st.session_state.move_analytics_pending_jump = None

                if not filtered_moves:
                    st.info("No moves match this filter.")
                    selected_move = None
                else:
                    if st.session_state.get("move_analytics_select") not in filtered_moves:
                        st.session_state["move_analytics_select"] = filtered_moves[0]
                    selected_move = st.selectbox("Select Move", filtered_moves, key="move_analytics_select")

                if selected_move:
                    move_key = selected_move.lower().replace(" ", "").replace("-", "")
                    info = MOVE_INFO.get(move_key, {})

                    type_badge = (f"<span style='background:{TYPE_COLORS.get(info.get('type', 'Normal'), '#A8A77A')}; "
                                  f"color:#111; font-weight:bold; border-radius:4px; padding:2px 9px; font-size:13px;'>"
                                  f"{info.get('type', '?')}</span>")
                    st.markdown(f"<h3 style='display:flex; align-items:center; gap:10px;'>{selected_move} {type_badge}</h3>",
                                unsafe_allow_html=True)
                    if info.get('description'):
                        st.caption(info['description'])

                    mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
                    mcol1.metric("Class", info.get('class', '?'))
                    mcol2.metric("Power", info.get('power', 0) or "-")
                    acc_val = info.get('accuracy', 0)
                    mcol3.metric("Accuracy", f"{acc_val}%" if acc_val else "Always Hits")
                    mcol4.metric("PP", info.get('pp', 0) or "-")
                    effect_chance = info.get('effect_chance', 0)
                    mcol5.metric("Secondary Effect", f"{effect_chance}% chance" if effect_chance else "None",
                                 help=f"Effect type: {info.get('effect_type', '?')}")

                    total_uses = move_totals.get(selected_move, 0)
                    rank = sorted(move_totals.values(), reverse=True).index(total_uses) + 1
                    tcol1, tcol2 = st.columns(2)
                    tcol1.metric("Total Times Executed", total_uses, help=f"Rank #{rank} of {len(all_moves)} moves actually used in this tournament.")
                    if df_tourn is not None and 'Deadliest_Moves' in df_tourn.columns:
                        deadliest_df = parse_moves(df_tourn['Deadliest_Moves'].iloc[0])
                        ko_row = deadliest_df[deadliest_df['Move'] == selected_move]
                        if not ko_row.empty:
                            tcol2.metric("Total KOs With This Move", int(ko_row.iloc[0]['Count']))

                    st.markdown("---")
                    st.subheader(f"Pokémon that use {selected_move}")
                    st.caption("Click one to load it into Species Data.")

                    users = [(sp, counts[selected_move]) for sp, counts in move_usage_by_species.items() if selected_move in counts]
                    users.sort(key=lambda x: -x[1])

                    if not users:
                        st.info("No Pokémon in this dataset used this move.")
                    else:
                        cols_per_row_mv = 6
                        row_cols_mv = None
                        for i, (sp, cnt) in enumerate(users):
                            if i % cols_per_row_mv == 0:
                                row_cols_mv = st.columns(cols_per_row_mv)
                            safe_mon_mv = sp.lower().replace(' ', '_').replace('.', '').replace('-', '_').replace("'", "")
                            mon_path_mv = os.path.join(POKEMON_ICON_DIR, safe_mon_mv, 'icon.png')
                            if not os.path.exists(mon_path_mv) and '_' in safe_mon_mv:
                                mon_path_mv = os.path.join(POKEMON_ICON_DIR, safe_mon_mv.split('_')[0], 'icon.png')
                            icon_mv = get_sprite_html(mon_path_mv, sp.title(), is_trainer=False)
                            with row_cols_mv[i % cols_per_row_mv]:
                                st.markdown(f"<div style='text-align:center;'>{icon_mv}</div>", unsafe_allow_html=True)
                                if st.button(sp.title(), key=f"movebtn_{selected_move}_{sp}", use_container_width=True):
                                    st.session_state.analytics_mode_pending_jump = sp
                                    st.rerun()
                                st.markdown(
                                    f"<div style='text-align:center; margin-top:-8px; background:#222; border-radius:4px; padding:3px 2px;'>"
                                    f"<span style='font-size:9px; color:#ccc;'>{cnt}x used</span></div>",
                                    unsafe_allow_html=True,
                                )

    else:
        st.write("Data reflects the **Team-Building Data** (the frequency of Pokémon and moves actively equipped in trainer rosters).")
        
        all_mons, all_moves = [], []
        for team in t1_df['Team_and_Movesets'].dropna():
            for mon_data in team.split(" | "):
                mon_name = mon_data.split(" Lv")[0].strip()
                mon_name = re.sub(r'\[.*?\]', '', mon_name).strip()
                if mon_name: all_mons.append(mon_name)
                
                if ": " in mon_data:
                    moves = mon_data.split(": ")[1].split("/")
                    for m in moves:
                        clean_move = m.strip()
                        if clean_move and clean_move != "None":
                            all_moves.append(clean_move)
                            
        col_pie, col_bar = st.columns(2)
        
        with col_pie:
            if all_mons:
                mon_counts = pd.Series(all_mons).value_counts().head(15).reset_index()
                mon_counts.columns = ['Pokémon', 'Equip Count']
                fig_pie = px.pie(mon_counts, values='Equip Count', names='Pokémon', title="Top 15 Most Equipped Pokémon", hole=0.3)
                fig_pie.update_traces(textinfo='value+label')
                st.plotly_chart(fig_pie, use_container_width=True)
                
        with col_bar:
            if all_moves:
                move_counts = pd.Series(all_moves).value_counts().head(15).reset_index()
                move_counts.columns = ['Move', 'Equip Count']
                fig_bar = px.bar(move_counts, x='Equip Count', y='Move', title="Top 15 Most Equipped Moves", orientation='h')
                fig_bar.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_bar, use_container_width=True)

# ==========================================
# TAB 3: SPECIES TIER LIST
# ==========================================
with tab_tierlist:
    st.header("Species Tier List")
    st.write("Every species ranked by KDA - (Kills + Assists) / max(1, Deaths) - into the same 5% percentile tiers the "
             "trainer Leaderboard uses, so a support Pokémon that racks up assists without KOs isn't buried under sweepers. "
             "Click a species to see every trainer who fields it; click one of those trainers to open their full profile "
             "in the Trainer Database tab.")

    if df_species_global is None:
        st.info("No species analytics file for this dataset.")
    elif 'Tier' not in df_species_global.columns:
        st.info("This dataset predates assist tracking, so its species have no Tier/Role yet - re-run the tournament with "
                 "a current build of `pokemon_ai_tournament.py` to populate this tab.")
    else:
        valid_pt_folders = get_valid_trainer_folders(TRAINER_SPRITE_DIR)
        hgss_files = get_hgss_sprites(HGSS_ASSETS_DIR)

        col_role, col_search = st.columns([1, 1])
        with col_role:
            role_filter = st.selectbox("Filter by Role", ["All"] + ALL_ROLE_NAMES,
                                        help="A species can carry more than one role (e.g. \"Attacker / Disrupter\"); filtering by one still shows it.\n\n"
                                             "**Attacker** - top quarter of the field by share of its KOs+Assists that were KOs.\n\n"
                                             "**Disrupter / Hazards / Weather** - top quarter of the species that get a meaningful amount of that "
                                             "category's assists (status conditions, entry hazards, or weather), ranked by how much of the species' total "
                                             "assists fall in that category.\n\n"
                                             "**Support** - like Disrupter/Hazards/Weather, but for helping a teammate: healing/curing it (Wish, Heal Bell, ...), "
                                             "Reflect/Light Screen reducing a hit a teammate went on to avenge by beating that very attacker, and stat "
                                             "debuffs or Tailwind that set up a KO - a lowered Defense/Sp. Def when a matching physical/special hit lands the "
                                             "KO, a lowered Attack/Sp. Atk that made the foe fall short of a KO it would otherwise have scored, or a lowered "
                                             "Speed / Tailwind that let a teammate move first and land the KO.\n\n"
                                             "**Passer** - Baton Passed a real buff (a stat boost, Substitute, Aqua Ring, ...) onto a teammate that then "
                                             "scored a KO while still carrying it.\n\n"
                                             "**Tank** / **Fodder** - no role above; qualifies by top-quarter average lifespan instead. Tank if the species' "
                                             "own tier is D- or better, Fodder if E+ or lower.\n\n"
                                             "**All-Rounder** - none of the above; a jack-of-all-trades or below-average-everything species.")
        with col_search:
            tier_search = st.text_input("Search Species", placeholder="e.g. Garchomp").strip()

        # --- "Trainers using <species>" - filled in once a species button below is clicked (a rerun-then-render pattern:
        # the click sets session_state and reruns, and this block - which runs every rerun - then reads that state.
        # Placed here, above the tier grid, so the result appears without having to scroll past the whole tier list. ---
        if st.session_state.selected_species_lookup:
            sp_sel = st.session_state.selected_species_lookup
            st.markdown("---")
            head_col, clear_col = st.columns([5, 1])
            head_col.subheader(f"Trainers using {sp_sel.title()}")
            if clear_col.button("Clear", key="clear_species_lookup"):
                st.session_state.selected_species_lookup = None
                st.session_state.selected_trainer_key = None
                st.rerun()
            trainer_keys_for_species = SPECIES_TRAINER_INDEX.get(sp_sel.upper(), [])
            if not trainer_keys_for_species:
                st.info("No trainers in this dataset field this species.")
            else:
                st.caption(f"{len(trainer_keys_for_species)} trainer(s). Their own moveset for {sp_sel.title()} is shown "
                           "below their name, since different trainers can run it differently.")
                trb_cols = st.columns(3)
                for idx, k in enumerate(trainer_keys_for_species):
                    t_row_tl = df[df['Trainer_Key'] == k]
                    t_row_tl = t_row_tl.iloc[0] if not t_row_tl.empty else None
                    t_class_tl = str(t_row_tl.get('Class', '')).lower().replace(' ', '_').replace('trainerclass_', '') if t_row_tl is not None else ""
                    t_display_tl = t_row_tl.get('Display_Name', key_to_name.get(k, k)) if t_row_tl is not None else key_to_name.get(k, k)
                    t_sprite_path_tl = resolve_trainer_sprite_path(k, t_class_tl, t_display_tl, game_title, valid_pt_folders, hgss_files)
                    t_sprite_tl = get_sprite_html(t_sprite_path_tl, "Sprite Missing", is_trainer=True, size=50)
                    moves_tl = get_trainer_species_moveset(k, sp_sel.upper())
                    with trb_cols[idx % 3]:
                        st.markdown(f"<div style='text-align:center;'>{t_sprite_tl}</div>", unsafe_allow_html=True)
                        if st.button(key_to_name.get(k, k), key=f"tiertrb_{sp_sel}_{k}", use_container_width=True):
                            st.session_state.selected_trainer_key = k
                            st.session_state.trainerdb_pending_jump = True
                            st.rerun()
                        st.markdown(
                            f"<div style='text-align:center; margin-top:-4px; background:#222; border-radius:4px; padding:5px;'>"
                            f"{moveset_chips_html(moves_tl)}</div>",
                            unsafe_allow_html=True,
                        )
                if st.session_state.selected_trainer_key in trainer_keys_for_species:
                    st.success(f"Selected **{key_to_name.get(st.session_state.selected_trainer_key)}** - "
                               "open the Trainer Database tab to view their full profile.")
            st.markdown("---")

        role_counts_chart = Counter()
        for _, r in df_species_global[['Role', 'Tier']].dropna(subset=['Role']).iterrows():
            for part in display_role_parts(r['Role'], r.get('Tier')):
                role_counts_chart[part] += 1
        if role_counts_chart:
            rc_df = pd.DataFrame(list(role_counts_chart.items()), columns=['Role', 'Count'])
            fig_roles = px.pie(rc_df, values='Count', names='Role', title="Role Distribution Across This Tournament", hole=0.3)
            st.plotly_chart(fig_roles, use_container_width=True)

        def _row_has_role(r, wanted):
            """role_filter match for one df_species_global row: Tank/Fodder need the row's OWN Tier to disambiguate from
            the shared underlying "Defender" role; every other role is a plain membership test."""
            if wanted in ("Tank", "Fodder"):
                return wanted in display_role_parts(r['Role'], r.get('Tier'))
            return wanted in role_components(r['Role'])

        tdf = df_species_global.copy()
        if role_filter != "All":
            tdf = tdf[tdf.apply(lambda r: _row_has_role(r, role_filter), axis=1)]
        if tier_search:
            tdf = tdf[tdf['Species'].str.contains(tier_search, case=False, na=False)]

        if tdf.empty:
            st.warning("No species match this filter.")

        # A plain, borderless look for every species "button" below - visually just an icon + name + role, not an obvious
        # button - while keeping them real st.button widgets underneath so clicking one still works.
        st.markdown(
            "<style>div[data-testid='stVerticalBlock'] div.stButton > button {"
            "background: none; border: none; padding: 2px 0; color: #eee; font-size: 12px; font-weight: 600;"
            "box-shadow: none; text-align: center;"
            "}"
            "div[data-testid='stVerticalBlock'] div.stButton > button:hover {color: #7AC74C; background: none;}"
            "div[data-testid='stVerticalBlock'] div.stButton > button:focus:not(:active) {color: #7AC74C;}"
            "</style>",
            unsafe_allow_html=True,
        )
        st.markdown("---")
        for tier in TIER_ORDER:
            tier_rows = tdf[tdf['Tier'] == tier]
            if tier_rows.empty:
                continue
            color = TIER_COLORS.get(tier, "#888")
            st.markdown(
                f"<div style='display:flex; align-items:center; gap:10px; margin-top:16px;'>"
                f"<div style='background:{color}; color:#111; font-weight:bold; border-radius:6px; padding:4px 16px; "
                f"font-size:16px; min-width:36px; text-align:center;'>{tier}</div>"
                f"<div style='background:#222; color:#ccc; border-radius:4px; padding:2px 8px; font-size:12px;'>{len(tier_rows)} species</div></div>",
                unsafe_allow_html=True,
            )
            sorted_rows = list(tier_rows.sort_values('KDA', ascending=False).iterrows())
            # 6, not 8 - a longer species name (Porygon Z, Mime Jr, Nidoran F/M, ...) wraps ugly across several
            # lines in an 8-wide grid; 6 matches the width Move Analytics' own icon+button card grid already uses.
            cols_per_row = 6
            row_cols = None
            for i, (_, srow) in enumerate(sorted_rows):
                if i % cols_per_row == 0:
                    row_cols = st.columns(cols_per_row)
                sp = srow['Species']
                safe_mon = sp.lower().replace(' ', '_').replace('.', '').replace('-', '_').replace("'", "")
                mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon, 'icon.png')
                if not os.path.exists(mon_path) and '_' in safe_mon:
                    mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon.split('_')[0], 'icon.png')
                icon = get_sprite_html(mon_path, sp.title(), is_trainer=False)
                role_text = display_role_text(srow.get('Role'), srow.get('Tier'))
                with row_cols[i % cols_per_row]:
                    with st.container(border=True):
                        st.markdown(f"<div style='text-align:center;'>{icon}</div>", unsafe_allow_html=True)
                        if st.button(sp.title(), key=f"tierbtn_{tier}_{sp}", use_container_width=True):
                            st.session_state.selected_species_lookup = sp
                            st.session_state.selected_trainer_key = None
                            st.rerun()
                        st.markdown(
                            f"<div style='text-align:center; margin-top:-8px;'>"
                            f"<span style='font-size:9px; color:#7AC74C;'>{role_text}</span><br>"
                            f"<span style='font-size:9px; color:#ccc;'>KDA {srow.get('KDA', 0):.2f}</span></div>",
                            unsafe_allow_html=True,
                        )

# ==========================================
# TAB 4: TRAINER DATABASE
# ==========================================
with tab_trainerdb:
    st.header("Trainer Database")
    st.write("Full profile for one trainer: their team, Tier/Role badges, and how each of their Pokémon actually performed. "
             "Reached directly from the Tier List tab (click a species, then a trainer), or pick one below.")

    all_trainer_names = sorted(df['Display_Name'].dropna().unique().tolist())
    # A selectbox that already has a `key` ignores a changed `index=` on later reruns (Streamlit keeps whatever the key's own
    # session_state entry holds) - the only way to actually move the visible selection when it's set programmatically (from
    # a Tier List click, not a user typing in this dropdown) is to write that key's session_state entry directly, before the
    # widget is created, exactly like a real click on it would. This must only happen on the ONE rerun right after such a
    # click (trainerdb_pending_jump) - forcing it on every rerun would also fire on the rerun caused by the user picking a
    # different name in THIS SAME dropdown by hand, snapping their pick right back and making manual switching a no-op.
    if st.session_state.trainerdb_pending_jump:
        default_name = key_to_name.get(st.session_state.selected_trainer_key) if st.session_state.selected_trainer_key else None
        if default_name in all_trainer_names:
            st.session_state["trainerdb_select"] = default_name
        st.session_state.trainerdb_pending_jump = False
    selected_trainer_name = st.selectbox("Select Trainer", all_trainer_names, key="trainerdb_select")

    if selected_trainer_name:
        t_key = trainer_dict.get(selected_trainer_name)
        st.session_state.selected_trainer_key = t_key      # keep the two tabs in sync if the dropdown is changed by hand

        valid_pt_folders = get_valid_trainer_folders(TRAINER_SPRITE_DIR)
        hgss_files = get_hgss_sprites(HGSS_ASSETS_DIR)
        t_row = df[df['Trainer_Key'] == t_key].iloc[0]
        card_html = build_trainer_card(t_row, game_title, valid_pt_folders, hgss_files)
        st.markdown(card_html, unsafe_allow_html=True)

        indiv_path_db = dp(f"analytics_individuals{suffix}.csv")
        if not os.path.exists(indiv_path_db) and os.path.exists(dp("analytics_individuals.csv")):
            indiv_path_db = dp("analytics_individuals.csv")
        df_indiv_db = load_data(indiv_path_db)

        if df_indiv_db is None:
            st.warning("No individual-execution analytics file for this dataset.")
        else:
            indiv_subset = df_indiv_db[df_indiv_db['Trainer_Key'] == t_key]
            if indiv_subset.empty:
                st.warning("No battle execution data found for this trainer.")
            else:
                # Intersect with this trainer's REAL team (from their own Team_and_Movesets, always authoritative) -
                # some existing datasets' analytics_individuals.csv has stray rows for a species this trainer never
                # fielded at all (see parse_team_species_set), which would otherwise show up here as a phantom
                # option that simply renders no data when picked.
                real_team = parse_team_species_set(t_row.get('Team_and_Movesets', ''))
                poke_list = sorted(sp for sp in indiv_subset['Species'].dropna().unique().tolist() if sp in real_team)
                # Same key-vs-index precedence issue as the trainer selectbox above: reset the remembered Pokemon choice
                # back to this trainer's own first Pokemon whenever the TRAINER just changed, so switching from one
                # trainer to another can't leave a species selected that isn't even on the new trainer's team.
                if st.session_state.get("trainerdb_poke_trainer") != t_key:
                    st.session_state["trainerdb_poke_trainer"] = t_key
                    if poke_list:
                        st.session_state["trainerdb_poke_select"] = poke_list[0]
                selected_poke = st.selectbox("Select Pokémon on Team", poke_list, key="trainerdb_poke_select")

                if selected_poke:
                    i_data = indiv_subset[indiv_subset['Species'] == selected_poke].iloc[0]

                    safe_mon = selected_poke.lower().replace(' ', '_').replace('.', '').replace('-', '_').replace("'", "")
                    mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon, 'icon.png')
                    if not os.path.exists(mon_path) and '_' in safe_mon:
                        mon_path = os.path.join(POKEMON_ICON_DIR, safe_mon.split('_')[0], 'icon.png')
                    mon_icon = get_sprite_html(mon_path, selected_poke.title(), is_trainer=False)

                    st.markdown(f"<h3 style='display:flex; align-items:center; gap:10px;'>{mon_icon} {selected_poke.title()}'s Execution Data</h3>", unsafe_allow_html=True)

                    actual_mon = get_actual_mon(t_key, selected_poke, game, t_row.get('Team_and_Movesets', ''))
                    static_info_db = get_species_static_info(selected_poke)
                    if actual_mon or (static_info_db and static_info_db["base_stats"]):
                        stat_col_db, meta_col_db = st.columns([2, 1])
                        with stat_col_db:
                            st.caption(f"Stats - Base vs. Actual at Lv.{actual_mon['level']}" if actual_mon else "Base Stats")
                            stat_order_db = [("hp", "HP", "max_hp"), ("attack", "Attack", "atk"), ("defense", "Defense", "def"),
                                              ("special_attack", "Sp. Atk", "spa"), ("special_defense", "Sp. Def", "spd"),
                                              ("speed", "Speed", "speed")]
                            base_stats_db = (static_info_db or {}).get("base_stats", {})
                            rows_db = []
                            for base_key, label, actual_key in stat_order_db:
                                rows_db.append({"Stat": label, "Series": "Base", "Value": base_stats_db.get(base_key, 0)})
                                if actual_mon:
                                    rows_db.append({"Stat": label, "Series": f"Actual (Lv.{actual_mon.get('level', '?')})",
                                                     "Value": actual_mon.get(actual_key, 0)})
                            fig_stat_db = px.bar(pd.DataFrame(rows_db), x="Value", y="Stat", color="Series",
                                                  orientation="h", barmode="group", text="Value")
                            fig_stat_db.update_layout(
                                yaxis={"categoryorder": "array", "categoryarray": [l for _, l, _ in stat_order_db][::-1]},
                                height=260, margin=dict(l=0, r=10, t=10, b=0),
                                legend=dict(title="", orientation="h", yanchor="bottom", y=1.02))
                            fig_stat_db.update_traces(textposition="outside")
                            st.plotly_chart(fig_stat_db, use_container_width=True)
                        with meta_col_db:
                            if actual_mon:
                                st.metric("Ability", (actual_mon.get("ability") or "?").replace("_", " ").title())
                                nature_db = actual_mon.get("nature")
                                st.metric("Nature", nature_db.replace("NATURE_", "").replace("_", " ").title() if nature_db else "Neutral")
                            elif static_info_db and static_info_db["abilities"]:
                                st.caption("Possible Abilities")
                                st.write(", ".join(static_info_db["abilities"]))
                                st.caption("This trainer's own IVs/ability/nature aren't available here (needs the "
                                           "decompiled trainer-data source locally) - showing base stats only.")
                        st.markdown("---")

                    rng_tooltip_db = "A calculated metric of RNG fortune. Positive numbers indicate 'Good Luck' (more Critical Hits/Secondary Effects, fewer Misses than average). Negative numbers indicate 'Bad Luck'."
                    has_kda_i = 'KDA' in i_data.index
                    cols_i = st.columns(6 if has_kda_i else 5)
                    cols_i[0].metric("Individual KDR", f"{i_data.get('KDR', 0):.2f}")
                    if has_kda_i:
                        cols_i[1].metric("KDA", f"{i_data.get('KDA', 0):.2f}")
                        rest_i = cols_i[2:]
                    else:
                        rest_i = cols_i[1:]
                    rest_i[0].metric("Avg Lifespan", f"{i_data.get('Average_Lifespan_Turns', 0):.2f}")
                    rest_i[1].metric("AI Switch-Outs", i_data.get('AI_Switching_Frequency', 0))
                    rest_i[2].metric("RNG / Luck", f"{i_data.get('Luck_Score', 0):.2f}", help=rng_tooltip_db)
                    rest_i[3].metric("Total KOs", i_data.get('KOs', 0))

                    if 'Assist_Breakdown' in i_data.index:
                        breakdown_i = parse_assist_breakdown(i_data.get('Assist_Breakdown'))
                        if breakdown_i and i_data.get('Total_Assists', 0):
                            abi_df = pd.DataFrame(list(breakdown_i.items()), columns=['Category', 'Count'])
                            fig_abi = px.bar(abi_df, x='Count', y='Category', orientation='h',
                                              title=f"What this {selected_poke.title()}'s {int(i_data.get('Total_Assists', 0))} assists were for")
                            fig_abi.update_layout(yaxis={'categoryorder': 'total ascending'})
                            fig_abi.update_traces(marker_color='#7AC74C')
                            st.plotly_chart(fig_abi, use_container_width=True)

                    with st.expander("View Detailed RNG & Luck Metrics"):
                        st.write(f"**Critical Hits Landed:** {i_data.get('Critical_Hits', 0)}")
                        st.write(f"**Secondary Effects Triggered:** {i_data.get('Secondary_Effect_Procs', 0)}")
                        st.write(f"**Moves Missed:** {i_data.get('Missed_Attacks', 0)}")

                    with st.expander("Matchup Context"):
                        st.write(f"**Top Targets (Most KOs Against):** {i_data.get('Most_KOs_Against', 'Data not yet generated.')}")
                        st.write(f"**Greatest Threats (Killed Most By):** {i_data.get('Killed_Most_By', 'Data not yet generated.')}")
                        st.write(f"**Match Sweeps (3+ KOs):** {i_data.get('Sweep_Count', 'Data not yet generated.')}")
                        st.write(f"**Lead Win Rate:** {i_data.get('Lead_Win_Rate', 'Data not yet generated.')}")

                    m_df = parse_moves(i_data.get('Move_Preference', ''))
                    if not m_df.empty:
                        m_df['Type'] = m_df['Move'].apply(lambda x: MOVE_DICT.get(x.lower().replace(" ", "").replace("-", ""), 'Normal'))
                        m_df['Color'] = m_df['Type'].apply(lambda x: TYPE_COLORS.get(x, '#A8A77A'))
                        color_map = {row['Move']: row['Color'] for i, row in m_df.iterrows()}
                        fig = px.pie(m_df, values='Count', names='Move', title="AI Move Selection Preference", hole=0.3, color='Move', color_discrete_map=color_map)
                        st.plotly_chart(fig, use_container_width=True)

# ==========================================
# TAB 5: DIFFICULTY CURVE
# ==========================================
with tab_curve:
    st.header("The Difficulty Curve")
    st.write("Progression on the X-axis is always based on the original storyline levels. The blue line is the actual "
             "curve - the average Elo at each level, smoothed - with every individual trainer plotted as a dot around it.")
    
    curve_search = st.text_input("Highlight Trainer in Graph:", placeholder="e.g. Cynthia, Bug Catcher, Flint...").strip()
    
    def extract_level(team_str):
        if not isinstance(team_str, str): return 0
        levels = re.findall(r'Lv(\d+)', team_str)
        return max(int(l) for l in levels) if levels else 0

    # The x-axis is each trainer's ORIGINAL story level, which a forced-level run's own Team_and_Movesets can't give (every
    # mon there really is level 50/100) - strip just the level token and re-fetch that same game/generic/items combo's
    # normal-level standings for the real numbers, falling back to this dataset's own (possibly forced) levels if that
    # variant was never run.
    normal_suffix = suffix.replace("_50", "").replace("_100", "")
    normal_csv = dp(f"standings{normal_suffix}.csv")
    df_normal = load_data(normal_csv)

    plot_df = t1_df.copy()
    
    if df_normal is not None:
        df_normal['Original_Max_Level'] = df_normal['Team_and_Movesets'].apply(extract_level)
        level_map = dict(zip(df_normal['Trainer_Key'], df_normal['Original_Max_Level']))
        plot_df['Max_Level'] = plot_df['Trainer_Key'].map(level_map)
    else:
        plot_df['Max_Level'] = plot_df['Team_and_Movesets'].apply(extract_level)
        
    plot_df = plot_df[plot_df['Max_Level'] > 0]
    
    if not plot_df.empty:
        np.random.seed(42)
        plot_df['Level_Jittered'] = plot_df['Max_Level'] + np.random.uniform(-0.35, 0.35, size=len(plot_df))
        plot_df['Hover_Team'] = plot_df['Team_and_Movesets'].str.replace(' | ', '<br>', regex=False)

        plot_df['Bracket_Name'] = "Lvl " + (plot_df['Max_Level'] // 10 * 10).astype(str) + "s"
        peak_indices = plot_df.dropna(subset=['Elo']).groupby('Bracket_Name')['Elo'].idxmax()
        plot_df['Is_Peak'] = False
        plot_df.loc[peak_indices, 'Is_Peak'] = True

        if curve_search:
            mask = plot_df['Display_Name'].str.contains(curve_search, case=False, na=False)
            plot_df['Highlight'] = np.where(mask, 'Searched Trainer', np.where(plot_df['Is_Peak'], 'Highest Elo', 'Normal'))
        else:
            plot_df['Highlight'] = np.where(plot_df['Is_Peak'], 'Highest Elo', 'Normal')

        fig_scatter = px.scatter(
            plot_df, x='Level_Jittered', y='Elo', hover_name='Display_Name',
            color='Highlight',
            color_discrete_map={'Searched Trainer': '#39ff14', 'Highest Elo': '#ffd700', 'Normal': '#ff7f50'},
            category_orders={'Highlight': ['Normal', 'Highest Elo', 'Searched Trainer']},
            hover_data={'Level_Jittered': False, 'Max_Level': True, 'Bracket_Name': False, 'Elo': ':.1f', 'Hover_Team': True, 'Highlight': False, 'Is_Peak': False},
            template='plotly_dark'
        )

        fig_scatter.for_each_trace(lambda t: t.update(
            marker=dict(
                size=16 if 'Searched' in t.name else (14 if 'Highest Elo' in t.name else 7),
                opacity=1.0 if t.name != 'Normal' else (0.15 if curve_search else 0.7),
                line=dict(width=2 if t.name != 'Normal' else 0.5, color='white'),
                symbol='star' if 'Highest Elo' in t.name else 'circle'
            )
        ))

        # The actual "curve": average Elo at each level, lightly smoothed with a centered rolling mean so a level with
        # only a couple of trainers doesn't zigzag the line - drawn UNDER the scatter dots (added first) so individual
        # trainers still stand out on top of it.
        curve_line_df = plot_df.dropna(subset=['Elo']).groupby('Max_Level')['Elo'].mean().reset_index().sort_values('Max_Level')
        curve_line_df['Smoothed_Elo'] = curve_line_df['Elo'].rolling(window=5, center=True, min_periods=1).mean()
        fig_scatter.add_scatter(
            x=curve_line_df['Max_Level'], y=curve_line_df['Smoothed_Elo'], mode='lines', name='Difficulty Curve (Avg Elo)',
            line=dict(color='#4da6ff', width=3), hoverinfo='skip',
        )
        fig_scatter.data = (fig_scatter.data[-1],) + fig_scatter.data[:-1]

        fig_scatter.update_layout(
            xaxis_title="Max Team Level (Original Progression)", yaxis_title="Trainer Elo Rating",
            height=600, hoverlabel=dict(bgcolor="#222", font_size=12),
            legend=dict(title="", yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0.5)")
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
    else:
        st.info("Not enough data to plot the curve with the current filters.")


# ==========================================
# TAB 6: LEADERBOARD & VISUALIZED CARDS
# ==========================================
with tab_leaderboard:
    st.header("Tournament Standings")
    
    col_view, col_tier, col_search = st.columns([1, 1, 1])
    with col_view:
        view_mode = st.radio("View Mode", ["Visualized Cards", "Classic Table"], horizontal=True)
    with col_tier:
        tier_filter = st.selectbox("Tier Filter", ["All", "S+", "S", "S-", "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "E+", "E", "E-", "F+", "F", "F-"])
    with col_search:
        trainer_search = st.text_input("Search Trainer", placeholder="e.g. Cynthia, Ace Trainer...").strip()
    
    leaderboard_df = t1_df.copy()
    
    if 'Elo' in leaderboard_df.columns:
        leaderboard_df = leaderboard_df.sort_values(by='Elo', ascending=False).reset_index(drop=True)
        
    leaderboard_df.index = np.arange(1, len(leaderboard_df) + 1)
    leaderboard_df.index.name = "Rank"
    leaderboard_df['True_Rank'] = leaderboard_df.index
    
    if tier_filter != "All":
        leaderboard_df = leaderboard_df[leaderboard_df['Tier'] == tier_filter]
        
    if trainer_search:
        leaderboard_df = leaderboard_df[leaderboard_df['Display_Name'].str.contains(trainer_search, case=False, na=False)]
    
    if view_mode == "Classic Table":
        # True_Rank itself is left out here - the dataframe's own index (labeled "Rank" above) already shows the exact
        # same number as its leftmost column, and Streamlit renders that index automatically, so keeping it as a
        # second, identical data column just duplicated it. The Visualized Cards branch below still reads
        # row['True_Rank'] directly (a plain .iterrows() row has no easy access to its own index label there).
        desired_cols = ['Display_Name', 'Match_Wins', 'Match_Losses', 'Game_Wins', 'Game_Losses', 'Elo', 'Tier', 'Class', 'Greatest_Win', 'Worst_Loss', 'Team_and_Movesets']
        available_cols = [col for col in desired_cols if col in leaderboard_df.columns]
        st.dataframe(
            leaderboard_df[available_cols],
            use_container_width=True,
            column_config={"Team_and_Movesets": st.column_config.TextColumn("Team & Movesets", width="large")}
        )
        
    else:
        cards_per_page = 50
        total_trainers = len(leaderboard_df)
        total_pages = max(1, (total_trainers + cards_per_page - 1) // cards_per_page)
        
        if total_trainers == 0:
            st.warning("No trainers found matching your filters.")
        else:
            st.write(f"Found **{total_trainers}** trainers matching your filters.")
            
            if total_pages > 1:
                col_space1, col_slider, col_space2 = st.columns([1, 2, 1])
                with col_slider:
                    current_page = st.slider("Page (Shows 50 trainers per page)", min_value=1, max_value=total_pages, value=1)
            else:
                current_page = 1
                
            start_idx = (current_page - 1) * cards_per_page
            end_idx = start_idx + cards_per_page
            
            valid_pt_folders = get_valid_trainer_folders(TRAINER_SPRITE_DIR)
            hgss_files = get_hgss_sprites(HGSS_ASSETS_DIR)
            
            html_cards = "<div style='display: flex; flex-wrap: wrap; gap: 20px; padding: 10px 0;'>"
            
            for _, row in leaderboard_df.iloc[start_idx:end_idx].iterrows():
                actual_rank = row['True_Rank']
                card = build_trainer_card(row, game_title, valid_pt_folders, hgss_files, rank_idx=actual_rank)
                html_cards += card
                
            html_cards += "</div>"
            st.markdown(html_cards, unsafe_allow_html=True)