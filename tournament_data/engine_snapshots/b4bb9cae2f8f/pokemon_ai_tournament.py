"""
Pokemon Platinum - Authentic Trainer AI Battle Tournament Simulator
=====================================================================

This is a port of the Generation 4 trainer AI from the pokeplatinum decompilation
(src/battle/trainer_ai/script.s and trainer_ai.c): every move starts at 100,
each active AI flag's script adds or subtracts, and the highest score wins
(ties broken randomly). The real AI is a small bytecode VM; each flag is a
script, and this file re-implements those scripts as Python functions.

STATUS OF THE PORT (checked against the real scripts)
------------------------------------------------------
All ELEVEN flag scripts (Basic, Expert, EvalAttack, SetupFirstTurn, Risky,
PrioritizeExtremes, Weather, Harrassment, CheckHP, BatonPass, TagStrategy) were
verified by executing the literal script.s bytecode in a small interpreter and
diffing the score AND the exact sequence of random rolls against the Python on
random battle states (see test_package/diff_*_vs_script.py; each harness was
mutation-tested). Every roll follows the real 8-bit form (`IfRandomLessThan N`
== `rng.randint(0, 255) < N`), and retail bugs and quirks are reproduced rather
than fixed.
- BASIC: the entry section (type immunity, absorption abilities, Soundproof,
  OHKO) and the whole effect section (~100 handlers, dispatched on the move's
  REAL BATTLE_EFFECT_* tag) - see _basic_entry_checks and BASIC_HANDLERS.
- EXPERT: all 136 reachable handlers, dispatched on the real effect tag via
  EXPERT_DISPATCH - see EXPERT_HANDLERS / EXPERT_PARTY_HANDLERS.
- EVALUATE_ATTACK, SETUP_FIRST_TURN, RISKY, PRIORITIZE_EXTREMES, WEATHER,
  HARASSMENT, CHECK_HP, BATON_PASS and TAG_STRATEGY (doubles) flags.
- Voluntary switching and send-in selection: a LITERAL port of trainer_ai.c's
  TrainerAI_ShouldSwitch + AI_* helpers and battle_lib.c's BattleAI_PostKOSwitchIn
  (should_voluntarily_switch[_double], select_switch_in_target, _AISwitch). It is
  unit-tested with a scripted u16 RandNext that pins every draw (the C is not
  bytecode, so there is no interpreter to diff against).
- Trainer item use (ai_should_use_item / apply_ai_item): a literal
  port of TrainerAI_ShouldUseItem for Full Restore, potions, status cures and
  X items / Guard Spec, including its retail quirks (unit-tested). In doubles only
  the first slot owns the trainer's items (a one-trainer double never loads a
  second trainer for slot 2 - see AI_ITEM_POOL_SLOT).
- PP tracking per move slot with the Struggle fallback, Perish Song's
  countdown, and the rest of the Gen 4 battle engine.

KNOWN DIFFERENCES FROM THE REAL GAME
-------------------------------------
- The AI's knowledge of the opponent is modelled (ai_load_ability / ai_check_ability): an ability counts as known only
  after it was shown in a battle message (Intimidate, weather setters, Pressure, absorb/immunity abilities on a real hit, Static /
  Flame Body / Poison Point / Rough Skin, Shed Skin, Natural Cure, healing abilities, Transform), otherwise the AI guesses one
  of the species' two abilities with a coin flip (Load) or answers HAVE / NOT_HAVE / UNKNOWN (Check); trapping abilities are
  always known and everything is forgotten on switch-in. The held item is known after Leftovers/Black Sludge/berry-cure/White
  Herb/Trick messages (ai_reveal_item). Only ability triggers this engine actually implements can reveal; abilities it does not
  simulate (Trace, Skill Swap, Sturdy, Synchronize messages...) are never announced.
- Damage is a literal integer port of BattleSystem_CalcMoveDamage / CalcCriticalMulti / CalcDamageVariance / ApplyTypeChart
  (calc_move_damage, crit_stage_multiplier, apply_type_chart_damage): base damage -> crit -> Life Orb -> variance 85-100 -> STAB
  -> chart rows in table order -> Filter / Expert Belt / Tinted Lens, with the real ability and held-item terms (Huge/Pure
  Power, Guts, Technician, Iron Fist, Thick Fat, Sniper, Choice items, type boosters, ...). The AI's damage-comparison opcodes
  use the same chain with crit x1 and variance 100 (TrainerAI_CalcDamage), ignoring accuracy. Reckless has no effect, as in the
  decomp (only the AI table mentions it).
- The real AddToMoveScore clamps a running score at 0 after every add; this file sums per flag. It only
  matters if a total fell below zero, which needs a 100-point penalty and never happens in practice.
- Accuracy follows BattleControllerPlayer_CheckMoveHitAccuracy (_accuracy_check_misses): the real
  HitRateByStage table, integer modifiers (Compound Eyes, Hustle, Sand Veil, Tangled Feet, Bright Powder,
  Wide/Zoom Lens, Gravity...) and a 1-100 roll. Status moves now roll accuracy too (Hypnosis used to
  always hit), raw accuracy 0 never rolls, and the AI's damage estimate ignores accuracy (it used to
  return 0 for every move under ~84%).
- Switching follows BattleSystem_InitBattleMon / UpdateAfterSwitch: a mon entering the field has its stat stages and volatile
  state reset (reset_on_switch_in); Baton Pass keeps the real set. About 40 status moves that used to do nothing now have their
  real effect (_ENGINE_STATUS_EFFECTS, keyed on the real BATTLE_EFFECT_*): Foresight, Miracle Eye, Mean Look, Mud/Water Sport,
  Magnet Rise, Worry Seed, Psych Up, Role Play, Skill Swap, Refresh, Recycle, Gastro Acid, Power Trick, Heart/Power/Guard Swap,
  Teeter Dance, Psycho Shift, Disable, Spite, Destiny Bond, Follow Me, Heal Bell, Aromatherapy, Healing Wish, Lunar Dance,
  Conversion, Conversion 2, Camouflage, Nature Power (both read BATTLE_TERRAIN, default TERRAIN_BUILDING), Heal Block, Me First,
  Teleport (always fails), and Metronome / Mirror Move / Assist (called-move swap). Still without an engine effect: Magic Coat,
  Defog and Sketch (no trainer knows them).
- Turn order is BattleSystem_SortMonActionOrder + CompareBattlerSpeed (move priority, then the literal speed compare; ties are a
  coin flip). Battle abilities now modelled: Trace, Download, Intimidate's blockers, Synchronize, Effect Spore, Color Change,
  Aftermath, Liquid Ooze, Skill Link, Anger Point, Suction Cups, Damp, Steadfast, Inner Focus, Keen Eye, White Smoke, Magma Armor,
  Gluttony, Unburden, Cloud Nine / Air Lock (weather_now), Plus / Minus / Flower Gift by side, Lightning Rod / Storm Drain
  redirection in doubles, Rivalry. Future Sight / Doom Desire (damage fixed at use, no type chart) and Wish are keyed
  per slot; Counter / Mirror Coat / Metal Burst use the last attacker of the matching class.
- Doubles: a slot that switches or uses an item now spends its action (it used to
  switch and then also attack), and the doubles hit path now covers what singles does (multi-hit,
  charge turns, Bide, recharge, Explosion, Roar/U-turn, berries...). Multi/tag battles with two distinct trainers do not
  exist here, so there is only ever one item pool per side.
- Doubles use choose_move_and_target_double (TrainerAI_MainDoubles): every move is scored against
  every target including the ally, so the partner-target script paths are live. The
  engine now also resolves every move range (spread, random-opponent, ally, field) -
  before, e.g. Rock Slide/Twister/Counter fell into the "self" branch - and models
  Helping Hand (x1.5 power for the ally's move that turn).
- Speed comparisons (_ai_effective_speed) follow BattleSystem_CompareBattlerSpeed; only Quick Claw / Custap Berry are not modelled. A
  fainted partner's data is treated as absent in the AI's reads (the real AI still reads it).
- Trainer Pokemon get the game's own personality: nature, gender (so Captivate, Attract, Cute Charm and Rivalry work), ability slot and
  IVs (iv_scale * 31 / 255) are derived exactly as TrainerData_BuildParty does (see NPC TRAINER PERSONALITY), from the trainer's ID, the
  class index and gender, the species and its ORIGINAL level - a set-level run keeps each mon's original nature and gender. Platinum is
  exact; HGSS uses the same procedure with its own class and species tables and its gender / ability overrides. Data files that carry
  no trainer ID in this checkout (the "_postgame" files, the Survival Area rivals) are paired by name (see
  PLATINUM_TRAINER_FILE_ALIASES).
- Post-KO switch-in stage 2 uses this file's damage estimator (wrapped to u8
  once, where the real code wraps twice).

TOURNAMENT ANALYTICS: ASSISTS, KDA, SPECIES TIERS AND ROLES
-------------------------------------------------------------
Both battle engines credit team play (see the ASSIST TRACKING section): every mon remembers who helped bring it down - "damage",
"status", "hazard", "weather", "cleric", "screen" and "pass" contributions, only ever from the other side - and when it faints the mon
that struck the final blow gets the KO while every OTHER contributing species gets one assist carrying its categories (a passive faint -
poison, weather, hazards - has no killer, so all of them do). The events travel in game_stats["assist_events"] into the analytics CSVs:
Total_Assists, KDA = (KOs + Assists) / max(1, Deaths) and an Assist_Breakdown in both, and in analytics_species.csv also a Tier (the
trainers' 5% percentile table, applied to species KDA) and a Role (Attacker / Disrupter / Hazards / Weather / Support / Passer, otherwise
Defender or All-Rounder, each relative to the field - compute_combat_role). ASSIST_WINDOW_TURNS can limit contributions to the last N turns (default: the whole
battle).

MOVE / SPECIES DATA (v2 - driven by your real data files)
-----------------------------------------------------------
Your moves_db.json entries carry the game's own effect classification:
    "effect": {"type": "BATTLE_EFFECT_XXX", "chance": N}
plus a "flags" list (MOVE_FLAG_MAKES_CONTACT, MOVE_FLAG_CAN_PROTECT, ...).
Rather than guessing move effects from the move's name, this version
derives move metadata directly from that effect.type/chance/flags data
via derive_effect_meta() - so it reflects your actual data file, not an
approximation of it. A small MOVE_NAME_OVERRIDES table exists only for
the handful of combo effects (e.g. Bulk Up's dual Atk+Def boost) that
the generic effect.type parser can't fully expand on its own.

Species data now loads directly from your res/pokemon dump: base_stats
keys are hp/attack/defense/speed/special_attack/special_defense, types
is a list (possibly the SAME type twice for a mono-type Pokemon - that
is deduped), and abilities is a 2-slot list (slot 0 used unless the
trainer's party entry specifies otherwise). Species files are matched
by their pokedex_data.en.name (giving a canonical "SPECIES_XXX" key),
falling back to the filename if that's absent. A small built-in
SPECIES_DB remains as a last-resort fallback for anything not found on
disk, so the sim never hard-crashes on an unrecognized species.
"""

import json
import csv
import random
import itertools
import os
import re
import copy
import time
import glob
import hashlib
from collections import defaultdict, Counter

# ============================================================
# PATHS
# ============================================================
TRAINER_DATA_DIR = r"Z:\PlatinumAI\pokeplatinum-main\pokeplatinum-main\res\trainers\data"
MOVES_DB_FILE = "moves_db.json"
# Per-species base-stat/type/ability data, one json per species (matches
# the res/pokemon dump format you shared - base_stats/types/abilities/
# pokedex_data). If this directory doesn't exist, we silently fall back
# to the built-in SPECIES_DB below.
SPECIES_DATA_DIR = "pokeplatinum-main/pokeplatinum-main/res/pokemon"
# HeartGold/SoulSilver's entire trainer roster lives in one JSON file
# (unlike Platinum's one-file-per-trainer layout) - see
# load_hgss_trainers_from_repo for the format differences this loader
# has to bridge. HGSS's own species data isn't separately available, so
# species lookups (base stats/types/abilities/learnsets) reuse
# SPECIES_DATA_DIR above - both games share the same Gen4 Pokemon roster,
# so this is expected to already be correct without needing HGSS-specific
# species files.
HGSS_TRAINER_DATA_FILE = r"Z:\PlatinumAI\pokeheartgold-master\pokeheartgold-master\files\poketool\trainer\trainers.json"
# The two decomp checkouts themselves: a trainer's party entry only carries species/level/IV scale, and the game derives gender, nature
# and ability slot from constants and tables that live outside the trainer files (trainer ID, trainer-class index and gender, species
# ID and gender ratio) - see the NPC TRAINER PERSONALITY section. When a directory is missing those mons simply get no nature/gender.
PLATINUM_REPO_DIR = r"Z:\PlatinumAI\pokeplatinum-main\pokeplatinum-main"
HGSS_REPO_DIR = r"Z:\PlatinumAI\pokeheartgold-master\pokeheartgold-master"
# False: skip the derivation entirely (mons get no nature, GENDERLESS, and the ability-slot override alone picks the ability).
TRAINER_PERSONALITY_ENABLED = True
# Per-item data, one json per item (holdEffect/effectParam, flingEffect/
# flingPower, pluckEffect, naturalGiftPower/naturalGiftType, berryData).
ITEM_DATA_DIR = r"Z:\PlatinumAI\pokeplatinum-main\pokeplatinum-main\res\items\data"
# Failsafe: if a single game somehow runs this many turns without either
# side fainting (e.g. two Pokemon that can never dent each other, or a
# data issue that slips past the loader's other safety nets), it's cut
# off and the trainer with more Pokemon remaining is awarded the win
# (ties broken in trainer_a's favor) rather than hanging the tournament.
MAX_BATTLE_TURNS = 350
# Weather set by an ABILITY (Drought/Drizzle/Sand Stream/Snow Warning) is
# permanent in Gen4 - it lasts until something else replaces it, unlike
# the 5-turn weather from moves like Rain Dance/Sandstorm/Sunny Day/Hail.
# There's no real "infinite" turn counter to use, so this is just a
# duration comfortably longer than any single battle can run (see
# MAX_BATTLE_TURNS above) - the weather-turns countdown will never
# actually reach it, which has the same practical effect as permanent.
PERMANENT_WEATHER_TURNS = MAX_BATTLE_TURNS + 1
# Gen4 Mimic: fails to copy these regardless of what the target just used
# (Shadow moves are Colosseum/XD-exclusive and don't exist in Platinum's
# own move pool, so they're not listed here) - checked alongside "already
# knows this move" and "target is semi-invulnerable" at the point of use.
MIMIC_EXCLUDED_MOVES = {"MOVE_SKETCH", "MOVE_STRUGGLE", "MOVE_METRONOME", "MOVE_CHATTER"}
# Gen4's Sleep Talk cannot call itself or these "unselectable" moves -
# Assist/Metronome/Mirror Move because they'd need to pick ANOTHER move
# themselves, Mimic/Sketch because they permanently alter the user's own
# moveset, Focus Punch because it needs to charge while the user is
# conscious, and Bide because it needs multiple turns of the user
# actually being awake to accumulate damage.
SLEEP_TALK_EXCLUDED_MOVES = {"MOVE_SLEEP_TALK", "MOVE_ASSIST", "MOVE_BIDE", "MOVE_FOCUS_PUNCH",
                             "MOVE_METRONOME", "MOVE_MIMIC", "MOVE_MIRROR_MOVE", "MOVE_SKETCH"}

# Set-level tournament mode: None means every Pokemon battles at its own
# in-game level (the default/original behavior). 50 or 100 overrides
# EVERY Pokemon's battling level uniformly, for an "everyone at level 50"
# or "everyone at level 100" tournament instead. Set interactively by
# prompt_for_set_level() at __main__ time - importing this module
# programmatically leaves this at None (unaffected) unless explicitly
# changed. See _build_party_mon for where this is actually applied.
SET_LEVEL = None
# Only consulted when SET_LEVEL is not None: for a trainer whose "moves"
# is null/missing (the game derives its moveset from level-up), this
# decides whether that moveset is computed at the Pokemon's own ORIGINAL
# level (e.g. Roman's level-26 Lickitung keeps its level-26 moves even
# though it now battles as if level 50) or at SET_LEVEL itself (that
# Lickitung instead gets whatever moves it would know by level 50/100).
# "original" or "set". Set by prompt_for_moveset_level_source().
MOVESET_LEVEL_SOURCE = "original"
# Appended to every output filename/directory (tournament_results,
# standings.csv, etc.) so a set-level run's output never overwrites a
# normal run's, e.g. "_50" or "_100". Empty string when SET_LEVEL is None.
# Also picks up "_singles"/"_doubles" when TOURNAMENT_BATTLE_MODE forces
# one format for the whole tournament (both suffixes combine, e.g.
# "_50_doubles") - see prompt_for_battle_mode and its __main__ wiring.
OUTPUT_SUFFIX = ""
# "normal" (default): each matchup's format follows determine_battle_format
# below - a genuine mix of singles and doubles results in the SAME
# tournament_results folder, matching the real game's own per-trainer
# double_battle flag. "singles" or "doubles" forces every single matchup
# in the tournament to that format regardless of what any individual
# trainer's own data says (except that a trainer with only one Pokemon
# can never physically field two, so it still battles 1-on-1 even under
# forced "doubles" mode - see determine_battle_format). Set by
# prompt_for_battle_mode() at __main__ time.
TOURNAMENT_BATTLE_MODE = "normal"
# True (default, matches the real games): trainers use the items in their data (Full Restore, potions, Full Heal, X items...)
# whenever TrainerAI_ShouldUseItem says to. False: nobody uses items. The trainer data itself is never modified - the switch is
# applied where a battle builds its item state (new_ai_item_state), so it works for every roster and can be flipped at any
# time. Set by prompt_for_trainer_items() at __main__ time; adds "_noitems" to OUTPUT_SUFFIX when off.
TRAINER_ITEMS_ENABLED = True


def determine_battle_format(trainer_a_party, trainer_b_party, tournament_mode, trainer_a_double_flag, trainer_b_double_flag):
    """Decides whether one specific matchup is fought as singles (1v1) or
    doubles (2v2). Both sides always send out the SAME number of Pokemon -
    there is no 2v1: if either trainer only has one Pokemon total, that
    Pokemon could never have a partner to begin with, so the fight is
    forced down to singles regardless of the tournament mode or either
    trainer's own double_battle flag. Otherwise: tournament_mode "singles"
    or "doubles" forces every matchup to that format; "normal" (the
    default) uses the real game's own rule - a fight is doubles if EITHER
    trainer's data marks it as a double battle."""
    if len(trainer_a_party) <= 1 or len(trainer_b_party) <= 1:
        return "singles"
    if tournament_mode in ("singles", "doubles"):
        return tournament_mode
    return "doubles" if (trainer_a_double_flag or trainer_b_double_flag) else "singles"


# ============================================================
# GEN 4 TYPE CHART (18 types, full matrix, only non-1.0 listed)
# ============================================================
ALL_TYPES = [
    "TYPE_NORMAL", "TYPE_FIGHTING", "TYPE_FLYING", "TYPE_POISON", "TYPE_GROUND",
    "TYPE_ROCK", "TYPE_BUG", "TYPE_GHOST", "TYPE_STEEL", "TYPE_FIRE",
    "TYPE_WATER", "TYPE_GRASS", "TYPE_ELECTRIC", "TYPE_PSYCHIC", "TYPE_ICE",
    "TYPE_DRAGON", "TYPE_DARK",
]

# attacker -> {defender_type: multiplier}; anything absent is 1.0
TYPE_CHART = {
    "TYPE_NORMAL":    {"TYPE_ROCK": 0.5, "TYPE_STEEL": 0.5, "TYPE_GHOST": 0.0},
    "TYPE_FIGHTING":  {"TYPE_NORMAL": 2.0, "TYPE_ROCK": 2.0, "TYPE_STEEL": 2.0, "TYPE_ICE": 2.0, "TYPE_DARK": 2.0,
                        "TYPE_FLYING": 0.5, "TYPE_POISON": 0.5, "TYPE_BUG": 0.5, "TYPE_PSYCHIC": 0.5, "TYPE_GHOST": 0.0},
    "TYPE_FLYING":    {"TYPE_FIGHTING": 2.0, "TYPE_BUG": 2.0, "TYPE_GRASS": 2.0,
                        "TYPE_ROCK": 0.5, "TYPE_STEEL": 0.5, "TYPE_ELECTRIC": 0.5},
    "TYPE_POISON":    {"TYPE_GRASS": 2.0, "TYPE_POISON": 0.5, "TYPE_GROUND": 0.5, "TYPE_ROCK": 0.5, "TYPE_GHOST": 0.5, "TYPE_STEEL": 0.0},
    "TYPE_GROUND":    {"TYPE_POISON": 2.0, "TYPE_ROCK": 2.0, "TYPE_STEEL": 2.0, "TYPE_FIRE": 2.0, "TYPE_ELECTRIC": 2.0,
                        "TYPE_GRASS": 0.5, "TYPE_BUG": 0.5, "TYPE_FLYING": 0.0},
    "TYPE_ROCK":      {"TYPE_FLYING": 2.0, "TYPE_BUG": 2.0, "TYPE_FIRE": 2.0, "TYPE_ICE": 2.0,
                        "TYPE_FIGHTING": 0.5, "TYPE_GROUND": 0.5, "TYPE_STEEL": 0.5},
    "TYPE_BUG":       {"TYPE_GRASS": 2.0, "TYPE_PSYCHIC": 2.0, "TYPE_DARK": 2.0,
                        "TYPE_FIGHTING": 0.5, "TYPE_FLYING": 0.5, "TYPE_POISON": 0.5, "TYPE_GHOST": 0.5, "TYPE_STEEL": 0.5, "TYPE_FIRE": 0.5},
    "TYPE_GHOST":     {"TYPE_GHOST": 2.0, "TYPE_PSYCHIC": 2.0, "TYPE_DARK": 0.5, "TYPE_STEEL": 0.5, "TYPE_NORMAL": 0.0},
    "TYPE_STEEL":     {"TYPE_ROCK": 2.0, "TYPE_ICE": 2.0,
                        "TYPE_STEEL": 0.5, "TYPE_FIRE": 0.5, "TYPE_WATER": 0.5, "TYPE_ELECTRIC": 0.5},
    "TYPE_FIRE":      {"TYPE_GRASS": 2.0, "TYPE_ICE": 2.0, "TYPE_BUG": 2.0, "TYPE_STEEL": 2.0,
                        "TYPE_FIRE": 0.5, "TYPE_WATER": 0.5, "TYPE_ROCK": 0.5, "TYPE_DRAGON": 0.5},
    "TYPE_WATER":     {"TYPE_FIRE": 2.0, "TYPE_GROUND": 2.0, "TYPE_ROCK": 2.0,
                        "TYPE_WATER": 0.5, "TYPE_GRASS": 0.5, "TYPE_DRAGON": 0.5},
    "TYPE_GRASS":     {"TYPE_WATER": 2.0, "TYPE_GROUND": 2.0, "TYPE_ROCK": 2.0,
                        "TYPE_FIRE": 0.5, "TYPE_GRASS": 0.5, "TYPE_POISON": 0.5, "TYPE_FLYING": 0.5, "TYPE_BUG": 0.5, "TYPE_DRAGON": 0.5, "TYPE_STEEL": 0.5},
    "TYPE_ELECTRIC":  {"TYPE_WATER": 2.0, "TYPE_FLYING": 2.0,
                        "TYPE_GRASS": 0.5, "TYPE_ELECTRIC": 0.5, "TYPE_DRAGON": 0.5, "TYPE_GROUND": 0.0},
    "TYPE_PSYCHIC":   {"TYPE_FIGHTING": 2.0, "TYPE_POISON": 2.0, "TYPE_PSYCHIC": 0.5, "TYPE_STEEL": 0.5, "TYPE_DARK": 0.0},
    "TYPE_ICE":       {"TYPE_GRASS": 2.0, "TYPE_GROUND": 2.0, "TYPE_FLYING": 2.0, "TYPE_DRAGON": 2.0,
                        "TYPE_FIRE": 0.5, "TYPE_WATER": 0.5, "TYPE_ICE": 0.5, "TYPE_STEEL": 0.5},
    "TYPE_DRAGON":    {"TYPE_DRAGON": 2.0, "TYPE_STEEL": 0.5},
    "TYPE_DARK":      {"TYPE_GHOST": 2.0, "TYPE_PSYCHIC": 2.0, "TYPE_FIGHTING": 0.5, "TYPE_DARK": 0.5, "TYPE_STEEL": 0.5},
}


def type_effectiveness_raw(attack_type, defender_types):
    """Pure type-chart multiplier, ignoring abilities."""
    mult = 1.0
    chart = TYPE_CHART.get(attack_type, {})
    for def_type in defender_types:
        mult *= chart.get(def_type, 1.0)
    return mult


# ============================================================
# NATURES
# ============================================================
# nature name -> (stat_boosted, stat_lowered); neutral natures map to (None, None)
NATURE_TABLE = {
    "HARDY": (None, None), "DOCILE": (None, None), "SERIOUS": (None, None),
    "BASHFUL": (None, None), "QUIRKY": (None, None),
    "LONELY": ("atk", "def"), "BRAVE": ("atk", "spe"), "ADAMANT": ("atk", "spa"), "NAUGHTY": ("atk", "spd"),
    "BOLD": ("def", "atk"), "RELAXED": ("def", "spe"), "IMPISH": ("def", "spa"), "LAX": ("def", "spd"),
    "TIMID": ("spe", "atk"), "HASTY": ("spe", "def"), "JOLLY": ("spe", "spa"), "NAIVE": ("spe", "spd"),
    "MODEST": ("spa", "atk"), "MILD": ("spa", "def"), "QUIET": ("spa", "spe"), "RASH": ("spa", "spd"),
    "CALM": ("spd", "atk"), "GENTLE": ("spd", "def"), "SASSY": ("spd", "spe"), "CAREFUL": ("spd", "spa"),
}


def nature_multiplier(nature_name, stat):
    if not nature_name:
        return 1.0
    key = nature_name.replace("NATURE_", "").upper()
    up, down = NATURE_TABLE.get(key, (None, None))
    if stat == up:
        return 1.1
    if stat == down:
        return 0.9
    return 1.0


# ============================================================
# SPECIES DATA (base stats + types)
# ============================================================
# Built-in fallback table. Covers the default Cynthia / Elite Four roster
# used by run_tournament() below. Format: (type1, type2_or_None,
# {hp, atk, def, spa, spd, spe}, default_ability_if_none_given)
SPECIES_DB = {
    "SPECIES_GARCHOMP":  ("TYPE_DRAGON", "TYPE_GROUND", {"hp": 108, "atk": 130, "def": 95, "spa": 80, "spd": 85, "spe": 102}, "SAND_VEIL"),
    "SPECIES_SPIRITOMB": ("TYPE_GHOST", "TYPE_DARK", {"hp": 50, "atk": 92, "def": 108, "spa": 92, "spd": 108, "spe": 35}, "PRESSURE"),
    "SPECIES_ROSERADE":  ("TYPE_GRASS", "TYPE_POISON", {"hp": 60, "atk": 70, "def": 65, "spa": 125, "spd": 105, "spe": 90}, "NATURAL_CURE"),
    "SPECIES_TOGEKISS":  ("TYPE_NORMAL", "TYPE_FLYING", {"hp": 85, "atk": 50, "def": 95, "spa": 120, "spd": 115, "spe": 80}, "SERENE_GRACE"),
    "SPECIES_LUCARIO":   ("TYPE_FIGHTING", "TYPE_STEEL", {"hp": 70, "atk": 110, "def": 70, "spa": 115, "spd": 70, "spe": 90}, "INNER_FOCUS"),
    "SPECIES_MILOTIC":   ("TYPE_WATER", None, {"hp": 95, "atk": 60, "def": 79, "spa": 100, "spd": 125, "spe": 81}, "MARVEL_SCALE"),

    "SPECIES_DUSTOX":    ("TYPE_BUG", "TYPE_POISON", {"hp": 60, "atk": 50, "def": 70, "spa": 50, "spd": 90, "spe": 65}, "SHIELD_DUST"),
    "SPECIES_BEAUTIFLY": ("TYPE_BUG", "TYPE_FLYING", {"hp": 60, "atk": 70, "def": 50, "spa": 90, "spd": 50, "spe": 65}, "SWARM"),
    "SPECIES_VESPIQUEN": ("TYPE_BUG", "TYPE_FLYING", {"hp": 70, "atk": 80, "def": 102, "spa": 80, "spd": 102, "spe": 40}, "PRESSURE"),
    "SPECIES_YANMEGA":   ("TYPE_BUG", "TYPE_FLYING", {"hp": 86, "atk": 76, "def": 86, "spa": 116, "spd": 56, "spe": 95}, "SPEED_BOOST"),
    "SPECIES_DRAPION":   ("TYPE_POISON", "TYPE_DARK", {"hp": 70, "atk": 90, "def": 110, "spa": 60, "spd": 75, "spe": 95}, "BATTLE_ARMOR"),
    "SPECIES_HERACROSS": ("TYPE_BUG", "TYPE_FIGHTING", {"hp": 80, "atk": 125, "def": 75, "spa": 40, "spd": 95, "spe": 85}, "SWARM"),

    "SPECIES_WHISCASH":  ("TYPE_WATER", "TYPE_GROUND", {"hp": 110, "atk": 78, "def": 73, "spa": 76, "spd": 71, "spe": 60}, "OBLIVIOUS"),
    "SPECIES_QUAGSIRE":  ("TYPE_WATER", "TYPE_GROUND", {"hp": 95, "atk": 85, "def": 85, "spa": 65, "spd": 65, "spe": 35}, "DAMP"),
    "SPECIES_SUDOWOODO": ("TYPE_ROCK", None, {"hp": 70, "atk": 100, "def": 115, "spa": 30, "spd": 65, "spe": 30}, "STURDY"),
    "SPECIES_GOLEM":     ("TYPE_ROCK", "TYPE_GROUND", {"hp": 80, "atk": 120, "def": 130, "spa": 55, "spd": 65, "spe": 45}, "STURDY"),
    "SPECIES_HIPPOWDON": ("TYPE_GROUND", None, {"hp": 108, "atk": 112, "def": 118, "spa": 68, "spd": 72, "spe": 47}, "SAND_STREAM"),

    "SPECIES_RAPIDASH":  ("TYPE_FIRE", None, {"hp": 65, "atk": 100, "def": 70, "spa": 80, "spd": 80, "spe": 105}, "FLASH_FIRE"),
    "SPECIES_STEELIX":   ("TYPE_STEEL", "TYPE_GROUND", {"hp": 75, "atk": 85, "def": 200, "spa": 55, "spd": 65, "spe": 30}, "ROCK_HEAD"),
    "SPECIES_DRIFBLIM":  ("TYPE_GHOST", "TYPE_FLYING", {"hp": 150, "atk": 80, "def": 44, "spa": 90, "spd": 54, "spe": 80}, "UNBURDEN"),
    "SPECIES_LOPUNNY":   ("TYPE_NORMAL", None, {"hp": 65, "atk": 76, "def": 84, "spa": 54, "spd": 96, "spe": 105}, "CUTE_CHARM"),
    "SPECIES_INFERNAPE": ("TYPE_FIRE", "TYPE_FIGHTING", {"hp": 76, "atk": 104, "def": 71, "spa": 104, "spd": 71, "spe": 108}, "BLAZE"),
    "SPECIES_MAGMORTAR": ("TYPE_FIRE", None, {"hp": 75, "atk": 95, "def": 67, "spa": 125, "spd": 95, "spe": 83}, "FLAME_BODY"),

    "SPECIES_MR_MIME":   ("TYPE_PSYCHIC", None, {"hp": 40, "atk": 45, "def": 65, "spa": 100, "spd": 120, "spe": 90}, "SOUNDPROOF"),
    "SPECIES_GIRAFARIG": ("TYPE_NORMAL", "TYPE_PSYCHIC", {"hp": 70, "atk": 80, "def": 65, "spa": 90, "spd": 65, "spe": 85}, "INNER_FOCUS"),
    "SPECIES_MEDICHAM":  ("TYPE_FIGHTING", "TYPE_PSYCHIC", {"hp": 60, "atk": 60, "def": 75, "spa": 60, "spd": 75, "spe": 80}, "PURE_POWER"),
    "SPECIES_ALAKAZAM":  ("TYPE_PSYCHIC", None, {"hp": 55, "atk": 50, "def": 45, "spa": 135, "spd": 95, "spe": 120}, "SYNCHRONIZE"),
    "SPECIES_BRONZONG":  ("TYPE_STEEL", "TYPE_PSYCHIC", {"hp": 67, "atk": 89, "def": 116, "spa": 79, "spd": 116, "spe": 33}, "LEVITATE"),
    "SPECIES_GALLADE":   ("TYPE_PSYCHIC", "TYPE_FIGHTING", {"hp": 68, "atk": 125, "def": 65, "spa": 65, "spd": 115, "spe": 80}, "STEADFAST"),
}


def _species_key_from_data(data, fallback_filename):
    """Prefer the game's own English species name (pokedex_data.en.name),
    e.g. 'GARCHOMP' -> 'SPECIES_GARCHOMP', since that reliably matches the
    SPECIES_xxx identifiers used in trainer party jsons. Falls back to the
    filename (uppercased) if pokedex_data is missing for some reason.

    A couple of special characters need explicit handling rather than the
    generic non-alphanumeric-to-underscore rule below, because the game's
    own identifiers don't treat them as separators:
      - Apostrophes are dropped entirely, not turned into "_"
        (Farfetch'd -> SPECIES_FARFETCHD, not SPECIES_FARFETCH_D).
      - The Nidoran gender symbols map to an explicit _F/_M suffix
        (Nidoran-F -> SPECIES_NIDORAN_F, Nidoran-M -> SPECIES_NIDORAN_M),
        since otherwise both genders would collapse to the same key and
        one would silently overwrite the other in SPECIES_DB."""
    name = None
    try:
        name = data.get("pokedex_data", {}).get("en", {}).get("name")
    except AttributeError:
        name = None
    if not name:
        name = os.path.splitext(fallback_filename)[0]
    name = name.upper()
    name = name.replace("\u2640", "_F").replace("\u2642", "_M")  # ♀ / ♂
    name = name.replace("'", "").replace("\u2019", "")  # ' and '
    key = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return f"SPECIES_{key}"


def _walk_species_files(root):
    """Yields (filename, filepath) for every species json under root,
    whether it's flat (res/pokemon/<name>.json) or nested
    (res/pokemon/<name>/data.json or similar)."""
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".json"):
                yield fn, os.path.join(dirpath, fn)


# species key -> numeric gender ratio (the personality low byte must be BELOW it for a female; 0 = always male, 254 = always female,
# 255 = genderless), read from each species file's "gender_ratio" constant.
GENDER_RATIO_VALUES = {"GENDER_RATIO_MALE_ONLY": 0, "GENDER_RATIO_FEMALE_12_5": 31, "GENDER_RATIO_FEMALE_25": 63,
                       "GENDER_RATIO_FEMALE_50": 127, "GENDER_RATIO_FEMALE_75": 191, "GENDER_RATIO_FEMALE_87_5": 223,
                       "GENDER_RATIO_FEMALE_ONLY": 254, "GENDER_RATIO_NO_GENDER": 255}
SPECIES_GENDER_RATIO = {}


def load_species_from_repo():
    """Loads your res/pokemon dump: base_stats{hp,attack,defense,speed,
    special_attack,special_defense}, types (a list; the SAME type listed
    twice for a mono-type Pokemon), abilities (2-slot list, may include
    'ABILITY_NONE'). Returns a dict merged on top of SPECIES_DB (repo data
    always wins). Silently returns {} if the directory isn't found."""
    extra = {}
    if not os.path.isdir(SPECIES_DATA_DIR):
        return extra
    for filename, filepath in _walk_species_files(SPECIES_DATA_DIR):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "base_stats" not in data:
                continue  # not a species data.json (could be a moves/anim file nested nearby)

            species_key = _species_key_from_data(data, filename)
            bs = data["base_stats"]
            stats = {
                "hp": bs.get("hp", 50),
                "atk": bs.get("attack", bs.get("atk", 50)),
                "def": bs.get("defense", bs.get("def", 50)),
                "spa": bs.get("special_attack", bs.get("spatk", bs.get("spa", 50))),
                "spd": bs.get("special_defense", bs.get("spdef", bs.get("spd", 50))),
                "spe": bs.get("speed", bs.get("spe", 50)),
            }

            types_list = data.get("types") or []
            type1 = types_list[0] if len(types_list) > 0 else "TYPE_NORMAL"
            type2 = types_list[1] if len(types_list) > 1 else None
            if type2 == type1:
                type2 = None  # mono-type Pokemon list the same type twice in this dump

            abilities = [a for a in (data.get("abilities") or []) if a and a != "ABILITY_NONE"]
            ability = abilities[0].replace("ABILITY_", "") if abilities else None

            # By-level learnset, needed for trainer party entries with
            # "moves": null - the game derives their moveset automatically
            # from what the species would know at that level (see
            # moves_from_learnset below). Stored sorted ascending by level.
            raw_learnset = ((data.get("learnset") or {}).get("by_level")) or []
            learnset = sorted(
                ((lvl, mv) for lvl, mv in raw_learnset if mv and mv != "MOVE_NONE"),
                key=lambda pair: pair[0],
            )

            extra[species_key] = (type1, type2, stats, ability, abilities, learnset)
            ratio = data.get("gender_ratio")
            ratio = GENDER_RATIO_VALUES.get(ratio, ratio if isinstance(ratio, int) else None)
            if ratio is not None:
                SPECIES_GENDER_RATIO[species_key] = ratio
        except Exception as e:
            print(f"WARNING: could not parse species file {filename}: {e}")
    return extra


SPECIES_DB.update(load_species_from_repo())


def load_items_from_repo():
    """Loads every item json in ITEM_DATA_DIR into a dict keyed by
    'ITEM_X' (derived from the file's own gbaID, e.g.
    'GBA_ITEM_SITRUS_BERRY' -> 'ITEM_SITRUS_BERRY' - this matches the
    convention trainer party data already uses for held items, like
    'ITEM_LEFTOVERS' or 'ITEM_LIGHT_CLAY'). Many Gen4-introduced items
    (most type-resist berries, Black Sludge, etc.) have no GBA-era
    counterpart and all share the literal placeholder "GBA_ITEM_NONE" -
    using that directly as the key would collide every such item into
    one shared "ITEM_NONE" entry, silently overwriting all but the last
    one loaded. Whenever the gbaID isn't a real, unique identifier (missing,
    or exactly "GBA_ITEM_NONE"), the key is derived from the filename
    itself instead (e.g. "wacan_berry.json" -> "ITEM_WACAN_BERRY"), which
    is always unique per file. Silently returns an empty dict if the
    directory doesn't exist, matching SPECIES_DB's own graceful-fallback
    behavior.

    is_berry is true whenever the item has real berryData OR sits in the
    berries field pocket - either is a reliable signal independent of
    holdEffect, since a berry's own hold effect can be any of several
    different values (HP_PCT_RESTORE, stat-boost-at-low-HP, status cure,
    etc.) rather than one single tag."""
    items_db = {}
    if not os.path.isdir(ITEM_DATA_DIR):
        return items_db
    for filename in os.listdir(ITEM_DATA_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(ITEM_DATA_DIR, filename), encoding="utf-8") as f:
                raw = json.load(f)
            gba_id = raw.get("gbaID", "")
            if gba_id and gba_id != "GBA_ITEM_NONE" and gba_id.startswith("GBA_ITEM_"):
                key = gba_id.replace("GBA_ITEM_", "ITEM_")
            else:
                key = "ITEM_" + os.path.splitext(filename)[0].upper()
            items_db[key] = {
                "name": raw.get("name", key),
                "hold_effect": raw.get("holdEffect") or "HOLD_EFFECT_NONE",
                "effect_param": raw.get("effectParam", 0) or 0,
                "fling_effect": raw.get("flingEffect") or "FLING_EFFECT_NONE",
                "fling_power": raw.get("flingPower", 0) or 0,
                "use_params": raw.get("itemUseParams") or {},
                "pluck_effect": raw.get("pluckEffect") or "PLUCK_EFFECT_NONE",
                "natural_gift_power": raw.get("naturalGiftPower", 0) or 0,
                "natural_gift_type": raw.get("naturalGiftType"),
                "is_berry": bool(raw.get("berryData")) or raw.get("fieldPocket") == "POCKET_BERRIES",
            }
        except Exception as e:
            print(f"WARNING: could not parse item file {filename}: {e}")
    return items_db


ITEMS_DB = load_items_from_repo()


def get_item_info(item_name):
    """Returns the item dict for item_name (see load_items_from_repo for
    its shape), or a harmless all-defaults dict if the item is unknown
    or item_name is None/empty - callers never need to check for a
    missing entry separately from an item with no notable effects."""
    if not item_name:
        return {"name": None, "hold_effect": "HOLD_EFFECT_NONE", "effect_param": 0,
                "fling_effect": "FLING_EFFECT_NONE", "fling_power": 0, "pluck_effect": "PLUCK_EFFECT_NONE",
                "natural_gift_power": 0, "natural_gift_type": None, "is_berry": False}
    return ITEMS_DB.get(item_name, {"name": item_name, "hold_effect": "HOLD_EFFECT_NONE", "effect_param": 0,
                                     "fling_effect": "FLING_EFFECT_NONE", "fling_power": 0,
                                     "pluck_effect": "PLUCK_EFFECT_NONE", "natural_gift_power": 0,
                                     "natural_gift_type": None, "is_berry": False})


def item_effects_active(mon):
    """False while mon is under Embargo (5 turns, cleared on switch-out -
    see the taunt_turns-style decrement and the switch-out reset lists),
    meaning its held item's effects are negated for as long as this
    returns False. Every held-item-effect site (Leftovers/Black Sludge
    healing, berries, White Herb, Light Ball, type-resist berries,
    Heat Rock/Light Clay's duration extension) should gate on this."""
    return mon.get("embargo_turns", 0) <= 0


def get_species_info(species_name):
    """Returns (type1, type2_or_None, base_stats_dict, default_ability,
    abilities_list, learnset_by_level). abilities_list is the ordered
    (non-NONE) ability slots, used when a trainer's party entry specifies
    an ability slot index instead of naming the ability directly.
    learnset_by_level is a list of (level, move_name) tuples sorted
    ascending, used to fill in a moveset when a party entry has no
    explicit moves (see moves_from_learnset)."""
    if species_name in SPECIES_DB:
        entry = SPECIES_DB[species_name]
        if len(entry) == 4:  # built-in fallback table entries lack a full abilities/learnset
            type1, type2, stats, default_ability = entry
            abilities = [default_ability] if default_ability else []
            return (type1, type2, stats, default_ability, abilities, [])
        if len(entry) == 5:  # older cached shape without a learnset
            return entry + ([],)
        return entry
    # Unknown species: fall back to plain Normal-type with mediocre stats
    # rather than crashing - but flag it loudly so it's easy to notice
    # and add real data under SPECIES_DATA_DIR.
    print(f"WARNING: no base-stat data for '{species_name}', using generic fallback (check SPECIES_DATA_DIR path/schema).")
    return ("TYPE_NORMAL", None, {"hp": 70, "atk": 70, "def": 70, "spa": 70, "spd": 70, "spe": 70}, None, [], [])


def calc_stat(base, iv, ev, level, is_hp=False, nature_mult=1.0):
    core = (2 * base + iv + ev // 4) * level // 100
    if is_hp:
        if base == 1:  # Shedinja-style 1 HP mons; not relevant here but safe
            return 1
        return core + level + 10
    return int((core + 5) * nature_mult)


# ============================================================
# MOVE EFFECTS: derived directly from moves_db.json's own
# "effect": {"type": "BATTLE_EFFECT_XXX", "chance": N} and "flags" list
# ============================================================
# Effect types matching these substrings represent non-standard damage
# (flat/variable/HP-based/etc.) that the real AI's damage-comparison
# routines always exclude and score by dedicated logic instead (see the
# source document's preamble list). We detect this from the effect TYPE
# string itself rather than hardcoding move names, so it stays correct
# even for moves we don't otherwise special-case.
NON_STANDARD_DAMAGE_MARKERS = (
    "RECHARGE_AFTER", "CHARGE_TURN", "SKIP_CHARGE_TURN", "DECREASE_POWER_WITH_LESS_USER_HP",
    "POWER_BASED_ON_LOW_SPEED", "INCREASE_POWER_WITH_WEIGHT", "RECOIL_HALF", "LEVEL_DAMAGE_FLAT",
    "HALVE_HP", "_DAMAGE_FLAT", "RANDOM_DAMAGE", "POWER_BASED_ON_FRIENDSHIP",
    "POWER_BASED_ON_LOW_FRIENDSHIP", "HIT_LAST_WHIFF_IF_HIT", "HIT_FIRST_IF_TARGET_ATTACKING",
    "RANDOM_POWER_BASED_ON_IVS", "NATURAL_GIFT", "JUDGEMENT", "PSYWAVE", "HIGHER_POWER_WHEN_LOW_PP",
    "INCREASE_POWER_WITH_MORE_HP", "BIDE", "COUNTER", "MIRROR_COAT", "METAL_BURST", "SPIT_UP",
    "INCREASE_POWER_WITH_MORE_STAT_UP", "RANDOM_POWER_MAYBE_HEAL", "SET_HP_EQUAL_TO_USER",
)

# Sound-based moves: your moves_db.json flags don't include a dedicated
# "sound" flag, so Soundproof is gated on this name list instead (this is
# the complete Gen4 sound-move list).
SOUND_MOVES = {
    "MOVE_GROWL", "MOVE_ROAR", "MOVE_SING", "MOVE_SUPERSONIC", "MOVE_SCREECH", "MOVE_SNORE",
    "MOVE_UPROAR", "MOVE_METAL_SOUND", "MOVE_GRASS_WHISTLE", "MOVE_HYPER_VOICE", "MOVE_BUG_BUZZ",
    "MOVE_CHATTER", "MOVE_HEAL_BELL", "MOVE_PERISH_SONG", "MOVE_SPARK", "MOVE_ECHOED_VOICE",
}

# Explicit overrides for combo effects the generic parser below can't
# fully expand from a single BATTLE_EFFECT_XXX token alone (two stats
# boosted/lowered at once, or a self-penalty bundled with damage).
MOVE_NAME_OVERRIDES = {
    "MOVE_BULK_UP": {"stat_changes": [("self", "atk", 1), ("self", "def", 1)], "setup": True},
    "MOVE_CALM_MIND": {"stat_changes": [("self", "spa", 1), ("self", "spd", 1)], "setup": True},
    "MOVE_DRAGON_DANCE": {"stat_changes": [("self", "atk", 1), ("self", "spe", 1)], "setup": True},
    "MOVE_COSMIC_POWER": {"stat_changes": [("self", "def", 1), ("self", "spd", 1)], "setup": True},
    "MOVE_DEFEND_ORDER": {"stat_changes": [("self", "def", 1), ("self", "spd", 1)], "setup": True},
    "MOVE_TICKLE": {"stat_changes": [("target", "atk", -1), ("target", "def", -1)]},
    "MOVE_SUPERPOWER": {"stat_changes": [("self", "atk", -1), ("self", "def", -1)], "risky": True},
    # Belt-and-suspenders overrides for the two moves explicitly named as
    # examples of the self/target secondary-stat-change bug (see the
    # STAT_CHANGE handling in run_battle) - guarantees correct behavior
    # regardless of the exact raw effect.type token in moves_db.json.
    "MOVE_CHARGE_BEAM": {"secondary": {"chance": 0.70, "effect": "STAT_CHANGE", "stat": "spa", "stages": 1, "target": "self"}},
    "MOVE_SHADOW_BALL": {"secondary": {"chance": 0.20, "effect": "STAT_CHANGE", "stat": "spd", "stages": -1, "target": "target"}},
    "MOVE_ENDEAVOR": {"effect": "ENDEAVOR", "nonstandard_damage": True, "power": 0},

    # --- Recharge moves: must skip the following turn entirely ---
    "MOVE_HYPER_BEAM": {"recharge": True}, "MOVE_GIGA_IMPACT": {"recharge": True},
    "MOVE_BLAST_BURN": {"recharge": True}, "MOVE_HYDRO_CANNON": {"recharge": True},
    "MOVE_FRENZY_PLANT": {"recharge": True}, "MOVE_ROCK_WRECKER": {"recharge": True},
    "MOVE_ROAR_OF_TIME": {"recharge": True},

    # --- Locked rampage moves: forced to repeat for 2-3 turns, then confused ---
    "MOVE_OUTRAGE": {"rampage": True}, "MOVE_PETAL_DANCE": {"rampage": True}, "MOVE_THRASH": {"rampage": True},

    # --- Pivoting moves: switch out after resolving (Baton Pass carries stat stages/Substitute along) ---
    "MOVE_U_TURN": {"pivot": True}, "MOVE_BATON_PASS": {"pivot": True, "baton_pass": True, "power": 0,
                                                          "class": "CLASS_STATUS", "always_hit": True},
    "MOVE_VOLT_SWITCH": {"pivot": True}, "MOVE_FLIP_TURN": {"pivot": True}, "MOVE_PARTING_SHOT": {"pivot": True},

    # --- Crash-on-miss moves: lose 1/2 max HP if they miss or are Protected against ---
    "MOVE_HI_JUMP_KICK": {"crash": True}, "MOVE_JUMP_KICK": {"crash": True},

    # --- Status-boosted attack: power doubles if the user is burned/paralyzed/poisoned ---
    "MOVE_FACADE": {"double_power_when_statused": True},

    # --- Taunt: disables CLASS_STATUS move selection for a few turns ---
    "MOVE_TAUNT": {"effect": "TAUNT", "always_hit": True},
    "MOVE_TORMENT": {"effect": "TORMENT", "always_hit": True},
    "MOVE_EMBARGO": {"effect": "EMBARGO"},
    "MOVE_GRUDGE": {"effect": "GRUDGE"},
    "MOVE_SNATCH": {"effect": "SNATCH"},
    "MOVE_TRICK": {"effect": "TRICK"},
    "MOVE_ENCORE": {"effect": "ENCORE", "always_hit": True},
    "MOVE_FLING": {"effect": "FLING"}, "MOVE_PLUCK": {"effect": "PLUCK"},
    "MOVE_NATURAL_GIFT": {"effect": "NATURAL_GIFT"},
    "MOVE_FUTURE_SIGHT": {"effect": "FUTURE_SIGHT", "always_hit": True},
    "MOVE_TRANSFORM": {"effect": "TRANSFORM", "always_hit": True, "can_be_protected": False},
    "MOVE_DOOM_DESIRE": {"effect": "FUTURE_SIGHT", "always_hit": True},
    "MOVE_WISH": {"effect": "WISH", "always_hit": True},

    # --- Rollout/Ice Ball: locked in for up to 5 turns, doubling power each hit; Defense Curl doubles it further ---
    "MOVE_ROLLOUT": {"rollout": True}, "MOVE_ICE_BALL": {"rollout": True},
    "MOVE_DEFENSE_CURL": {"effect": "DEFENSE_CURL", "stat_changes": [("self", "def", 1)], "setup": True},

    # --- Magnitude: random power via the real Gen4 probability table ---
    "MOVE_MAGNITUDE": {"magnitude": True, "nonstandard_damage": True},

    # --- Sucker Punch: fails outright unless the target is about to use a damaging move ---
    "MOVE_SUCKER_PUNCH": {"sucker_punch": True, "risky": True},

    # --- Fake Out: guaranteed flinch, but only works on the user's very first turn on the field ---
    "MOVE_FAKE_OUT": {"fake_out": True, "secondary": {"chance": 1.0, "effect": "FLINCH"}},

    # --- Two-turn semi-invulnerable moves ---
    "MOVE_FLY": {"charge_move": "FLY"}, "MOVE_DIG": {"charge_move": "DIG"},
    "MOVE_SOLAR_BEAM": {"solar_charge": True},
    "MOVE_DIVE": {"charge_move": "DIVE"}, "MOVE_BOUNCE": {"charge_move": "BOUNCE"},

    # --- Explosion/Self-Destruct: halve the target's Defense during damage calc, and faint the user ---
    "MOVE_EXPLOSION": {"halve_defense": True, "self_destruct": True, "risky": True},
    "MOVE_SELFDESTRUCT": {"halve_defense": True, "self_destruct": True, "risky": True},

    # --- Weather Ball: power doubles and type changes to match the active weather ---
    "MOVE_WEATHER_BALL": {"weather_ball": True, "nonstandard_damage": True},

    # --- Payback/Avalanche/Revenge: double power under the right turn-order/damage-taken condition ---
    "MOVE_PAYBACK": {"payback": True, "nonstandard_damage": True},
    "MOVE_AVALANCHE": {"avalanche_revenge": True, "nonstandard_damage": True},
    "MOVE_REVENGE": {"avalanche_revenge": True, "nonstandard_damage": True},
    "MOVE_ASSURANCE": {"target_revenge": True, "nonstandard_damage": True},

    # --- Brine: doubles in power if the target is below half HP ---
    "MOVE_BRINE": {"brine": True, "nonstandard_damage": True},

    # --- Weather-bypassing accuracy ---
    "MOVE_THUNDER": {"weather_accuracy": True}, "MOVE_BLIZZARD": {"weather_accuracy": True},

    # --- Swagger/Flatter: boost a stat AND confuse the target (previously only boosted) ---
    "MOVE_SWAGGER": {"stat_changes": [("target", "atk", 2)], "also_confuses": True, "risky": True},
    "MOVE_FLATTER": {"stat_changes": [("target", "spa", 1)], "also_confuses": True},

    # --- Binding moves: trap + residual damage for 2-5 turns ---
    "MOVE_WRAP": {"binding": True}, "MOVE_FIRE_SPIN": {"binding": True}, "MOVE_SAND_TOMB": {"binding": True},
    "MOVE_BIND": {"binding": True}, "MOVE_CLAMP": {"binding": True}, "MOVE_WHIRLPOOL": {"binding": True},
    "MOVE_CLOSE_COMBAT": {"stat_changes": [("self", "def", -1), ("self", "spd", -1)]},
    "MOVE_HAMMER_ARM": {"stat_changes": [("self", "spe", -1)]},
    "MOVE_OVERHEAT": {"stat_changes": [("self", "spa", -2)]},
    "MOVE_DRACO_METEOR": {"stat_changes": [("self", "spa", -2)]},
    "MOVE_LEAF_STORM": {"stat_changes": [("self", "spa", -2)]},
    "MOVE_PSYCHO_BOOST": {"stat_changes": [("self", "spa", -2)]},
    "MOVE_CAPTIVATE": {"effect": "CAPTIVATE"},
    "MOVE_MEMENTO": {"effect": "MEMENTO", "risky": True},
    "MOVE_BELLY_DRUM": {"stat_changes": [("self", "atk", 12)], "risky": True},
    "MOVE_ACUPRESSURE": {"stat_changes": [("self", "random", 2)], "risky": True},
    "MOVE_DESTINY_BOND": {"risky": True}, "MOVE_COUNTER": {"risky": True, "effect": "COUNTER"},
    "MOVE_MIRROR_COAT": {"risky": True, "effect": "MIRROR_COAT"},
    "MOVE_METAL_BURST": {"risky": True, "effect": "METAL_BURST"}, "MOVE_PRESENT": {"risky": True}, "MOVE_METRONOME": {"risky": True},
    "MOVE_PSYWAVE": {"risky": True}, "MOVE_ANCIENT_POWER": {"risky": True}, "MOVE_SILVER_WIND": {"risky": True},
    "MOVE_OMINOUS_WIND": {"risky": True}, "MOVE_ME_FIRST": {"risky": True},
    "MOVE_ATTRACT": {"risky": True}, "MOVE_GUILLOTINE": {"risky": True}, "MOVE_HORN_DRILL": {"risky": True},
    "MOVE_FISSURE": {"risky": True}, "MOVE_SHEER_COLD": {"risky": True},
    "MOVE_LEECH_SEED": {"setup": True}, "MOVE_SUBSTITUTE": {"setup": True},
    "MOVE_RAIN_DANCE": {"setup": True}, "MOVE_SUNNY_DAY": {"setup": True},
    "MOVE_REFLECT": {"setup": True}, "MOVE_LIGHT_SCREEN": {"setup": True}, "MOVE_TAILWIND": {"setup": True},
    # Stockpile/Swallow/Spit Up: a self-contained combo not expressible via
    # the generic effect.type/stat_changes parser, since Swallow/Spit Up's
    # power/healing depend on a per-Pokemon counter that Stockpile builds
    # up (see the "stockpile" field added in _build_party_mon and the
    # STOCKPILE/SWALLOW/SPIT_UP handling in apply_move_effect). Stockpile's
    # own Def/SpDef boost and its "fails at 3 stacks" cap are both handled
    # entirely inside that STOCKPILE branch rather than via stat_changes,
    # so the boost doesn't apply on the failing 4th use.
    "MOVE_STOCKPILE": {"effect": "STOCKPILE", "setup": True},
    "MOVE_SWALLOW": {"effect": "SWALLOW"},
    "MOVE_SPIT_UP": {"effect": "SPIT_UP", "nonstandard_damage": True},
    # Multi-hit moves: a random count (see roll_multihit_count - the Gen1-4
    # distribution is 2 or 3 hits at 3/8 each, 4 or 5 hits at 1/8 each) for
    # most of them, but a handful always hit exactly twice.
    "MOVE_COMET_PUNCH": {"multihit": True}, "MOVE_FURY_ATTACK": {"multihit": True},
    "MOVE_PIN_MISSILE": {"multihit": True}, "MOVE_SPIKE_CANNON": {"multihit": True},
    "MOVE_BARRAGE": {"multihit": True}, "MOVE_FURY_SWIPES": {"multihit": True},
    "MOVE_ARM_THRUST": {"multihit": True}, "MOVE_BULLET_SEED": {"multihit": True},
    "MOVE_ICICLE_SPEAR": {"multihit": True}, "MOVE_ROCK_BLAST": {"multihit": True},
    "MOVE_DOUBLE_KICK": {"multihit_fixed": 2}, "MOVE_BONEMERANG": {"multihit_fixed": 2},
    "MOVE_TWINEEDLE": {"multihit_fixed": 2},
    # Curse: behavior branches on the USER's own type at the moment it's
    # used (Ghost vs everything else), which the generic per-move parser
    # can't express - see the CURSE branch in apply_move_effect.
    "MOVE_CURSE": {"effect": "CURSE"},
    # Whirlwind/Roar: forces the TARGET to switch to a random other party
    # member - handled directly in run_battle (it needs the target's full
    # party/index, which apply_move_effect doesn't have access to), not
    # via apply_move_effect. Gen4 accuracy is listed as "-" (never miss).
    "MOVE_WHIRLWIND": {"effect": "FORCE_SWITCH", "always_hit": True},
    "MOVE_ROAR": {"effect": "FORCE_SWITCH", "always_hit": True},
    "MOVE_YAWN": {"effect": "YAWN"},
    "MOVE_IMPRISON": {"effect": "IMPRISON", "always_hit": True},
    "MOVE_PUNISHMENT": {"punishment": True, "nonstandard_damage": True},
    # Fixed-damage moves: bypass the entire stat-based formula (no STAB,
    # no weather, no crit, no attacker/defender stat stages) - but type
    # IMMUNITY (and abilities like Wonder Guard) still block them
    # entirely, same as any other move. See the fixed_damage handling in
    # compute_damage. power:1 is just a non-zero placeholder so the
    # normal "power<=0 -> no damage" short-circuit doesn't fire first.
    "MOVE_DRAGON_RAGE": {"fixed_damage": 40, "nonstandard_damage": True, "power": 1},
    "MOVE_SONIC_BOOM": {"fixed_damage": 20, "nonstandard_damage": True, "power": 1},
    "MOVE_NIGHT_SHADE": {"fixed_damage_by_level": True, "nonstandard_damage": True, "power": 1},
    "MOVE_SEISMIC_TOSS": {"fixed_damage_by_level": True, "nonstandard_damage": True, "power": 1},
    # Reversal/Flail: power scales up as the USER's own HP drops - see
    # compute_low_hp_power for the real Gen3/4 lookup table.
    "MOVE_REVERSAL": {"low_hp_power": True, "nonstandard_damage": True},
    "MOVE_FLAIL": {"low_hp_power": True, "nonstandard_damage": True},
    # Eruption/Water Spout: power scales UP with the user's current HP
    # (the opposite direction from Reversal/Flail above) - a direct
    # linear formula, not a lookup table, so this gets its own flag.
    "MOVE_ERUPTION": {"hp_scaling_power": True, "nonstandard_damage": True},
    "MOVE_WRING_OUT": {"target_hp_scaling_power": True, "nonstandard_damage": True},
    "MOVE_WATER_SPOUT": {"hp_scaling_power": True, "nonstandard_damage": True},
    # Bide: a stateful 2-turn charge-then-release move, handled with its
    # own dedicated block in run_battle rather than through the normal
    # damage pipeline - see the "bide" handling there and in choose_move.
    "MOVE_BIDE": {"bide": True, "always_hit": True},
    "MOVE_MIMIC": {"mimic": True, "always_hit": True},
    "MOVE_COPYCAT": {"copycat": True},
    "MOVE_SLEEP_TALK": {"effect": "SLEEP_TALK", "always_hit": True},
    "MOVE_PAIN_SPLIT": {"effect": "PAIN_SPLIT", "always_hit": True, "typeless": True},
    # Hidden Power: type AND power are both derived from the user's IVs,
    # fixed for its whole life - see compute_hidden_power.
    "MOVE_HIDDEN_POWER": {"hidden_power": True, "nonstandard_damage": True},
}

# Names that carry a high critical-hit ratio (folded in below alongside
# whatever the effect.type parser detects, since a couple of these are
# combined types like HIGH_CRITICAL_BURN_HIT/HIGH_CRITICAL_POISON_HIT).
# Type-resist berries (Occa/Passho/Wacan/Rindo/etc.) all share this one
# naming convention for their hold effect - each halves damage from a
# SUPER EFFECTIVE hit of its one matching type, is consumed on use, and
# only that one specific type triggers it (a merely neutral or not-very-
# effective hit of the same type does nothing). Gen4 has one berry per
# type except Fairy (introduced later), all following this same pattern,
# so this generalizes automatically to any of them.
TYPE_RESIST_BERRY_TYPES = {
    f"HOLD_EFFECT_WEAKEN_SE_{t}": f"TYPE_{t}" for t in (
        "NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BUG", "GHOST", "STEEL",
        "FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC", "ICE", "DRAGON", "DARK",
    )
}
_STAT_ALIASES = {"ATK": "atk", "ATTACK": "atk", "DEF": "def", "DEFENSE": "def",
                 "SP_ATK": "spa", "SP_DEF": "spd", "SPEED": "spe", "ACCURACY": "acc",
                 "ACC": "acc", "EVA": "eva", "EVASION": "eva"}

_RECOIL_FRACTIONS = {"QUARTER": 0.25, "THIRD": 1 / 3, "HALF": 0.5}

_STATUS_TOKEN_MAP = {
    "BURN": "BURN", "FREEZE": "FREEZE", "PARALYZE": "PARALYZE", "POISON": "POISON",
    "BADLY_POISON": "TOXIC", "CONFUSE": "CONFUSE", "FLINCH": "FLINCH",
}


def _is_non_standard_damage(effect_type):
    return any(marker in effect_type for marker in NON_STANDARD_DAMAGE_MARKERS)


def derive_effect_meta(move_name, category, raw_effect):
    """Translates moves_db.json's own effect.type/chance into the internal
    metadata shape the AI scorer and battle engine use (effect / stat_changes
    / secondary / drain / recoil / ohko / protect / substitute / high_crit).
    This is deliberately pattern-based (not a giant literal per-move table)
    so it stays correct across the full ~467-move set from a manageable
    amount of code. See MOVE_NAME_OVERRIDES above for the handful of combo
    moves this can't fully expand on its own."""
    etype = (raw_effect or {}).get("type", "") or ""
    if etype.startswith("BATTLE_EFFECT_"):
        etype = etype[len("BATTLE_EFFECT_"):]
    chance_pct = (raw_effect or {}).get("chance", 0) or 0
    chance = chance_pct / 100.0
    meta = {}

    # --- dedicated status moves (100% on hit; the move's own accuracy already gates it) ---
    m = re.match(r"^STATUS_(SLEEP|CONFUSE|BURN|PARALYZE|POISON|BADLY_POISON|LEECH_SEED|NIGHTMARE)$", etype)
    if m:
        tag = m.group(1)
        mapped = {"BADLY_POISON": "TOXIC"}.get(tag, tag)
        meta["effect"] = mapped
        return meta
    if etype in ("SLEEP_NEXT_TURN", "YAWN"):
        # Yawn: doesn't put the target to sleep immediately - it starts a
        # 2-turn countdown (see the "yawn_turn" field and its handling in
        # apply_move_effect/process_status_end_turn) - genuinely different
        # from an instant-sleep move, so it gets its own tag rather than
        # reusing "SLEEP" with a flag nothing downstream ever consumed.
        return {"effect": "YAWN"}
    if etype == "INFATUATE":
        return {"effect": "ATTRACT", "risky": True}
    if etype in ("PERISH_SONG", "ALL_FAINT_3_TURNS"):
        return {"effect": "PERISH_SONG"}
    if etype == "RAISE_ALL_STATS_HIT":
        # Ancient Power/Silver Wind/Ominous Wind: ONE chance roll raises
        # all 5 stats together by 1 stage each - not 5 independent rolls,
        # so this needs its own dedicated effect tag rather than
        # reusing the single-stat STAT_CHANGE secondary mechanism.
        return {"secondary": {"chance": chance, "effect": "RAISE_ALL_STATS"}}
    if etype == "RESET_STAT_CHANGES":
        return {"effect": "HAZE"}
    if etype == "CRIT_UP_2":
        return {"effect": "FOCUS_ENERGY"}
    if etype == "SP_DEF_UP_DOUBLE_ELECTRIC_POWER":
        return {"stat_changes": [("self", "spd", 1)], "setup": True, "charges_electric": True}
    if etype == "FAIL_IF_NOT_USED_ALL_OTHER_MOVES":
        return {"effect": "LAST_RESORT"}
    if etype in ("BYPASS_ACCURACY", "PRIORITY_NEG_1_BYPASS_ACCURACY"):
        # Swift/Aerial Ace/Magical Leaf/Shock Wave/Aura Sphere/Vital
        # Throw: these carry accuracy=0 in the raw data (since the real
        # game never rolls an accuracy check for them at all), which
        # without this tag would fall back to a default 100 via
        # move.get("accuracy", 100) or 100 and be treated as an ordinary
        # evasion-affected 100%-accuracy move rather than one that
        # truly never misses. Vital Throw's -1 priority itself still
        # comes from the raw move data as usual; this only adds the
        # always-hit half of its effect.
        return {"always_hit": True}
    if etype == "EVA_UP_2_MINIMIZE":
        # The trailing _MINIMIZE suffix means this doesn't match the
        # generic "<STAT>_UP(_2)?" pattern below - Minimize's own
        # increased-damage-from-certain-moves interaction (Stomp, Body
        # Slam, etc.) isn't modeled, just the evasion boost itself.
        return {"stat_changes": [("self", "eva", 2)], "setup": True}

    # --- secondary status/flinch on a damaging move: "<STATUS>_HIT" ---
    m = re.match(r"^(BURN|FREEZE|PARALYZE|POISON|BADLY_POISON|CONFUSE|FLINCH)_HIT$", etype)
    if m:
        tag = _STATUS_TOKEN_MAP[m.group(1)] if m.group(1) != "BADLY_POISON" else "TOXIC"
        return {"secondary": {"chance": chance, "effect": tag}}

    # --- fang moves: flinch OR a status, one shared chance roll each ---
    m = re.match(r"^FLINCH_(BURN|FREEZE|PARALYZE)_HIT$", etype)
    if m:
        return {"secondaries": [{"chance": chance, "effect": "FLINCH"},
                                 {"chance": chance, "effect": _STATUS_TOKEN_MAP[m.group(1)]}]}

    # --- high-crit moves, optionally bundled with a status chance ---
    if etype == "HIGH_CRITICAL":
        return {"high_crit": True, "risky": True}
    m = re.match(r"^HIGH_CRITICAL_(BURN|POISON)_HIT$", etype)
    if m:
        return {"high_crit": True, "risky": True, "secondary": {"chance": chance, "effect": _STATUS_TOKEN_MAP[m.group(1)]}}

    # --- secondary stat change on a damaging move: "RAISE/LOWER_<STAT>(_2)?_HIT" ---
    m = re.match(r"^(RAISE|LOWER)_([A-Z_]+?)(_2)?_HIT$", etype)
    if m and m.group(2) in _STAT_ALIASES:
        direction, stat_tok, two = m.groups()
        stages = (2 if two else 1) * (1 if direction == "RAISE" else -1)
        stat_target = "self" if direction == "RAISE" else "target"
        return {"secondary": {"chance": chance, "effect": "STAT_CHANGE", "stat": _STAT_ALIASES[stat_tok],
                               "stages": stages, "target": stat_target}}

    # --- pure self stat-boosting status moves: "<STAT>_UP(_2)?" ---
    m = re.match(r"^([A-Z_]+?)_UP(_2)?$", etype)
    if m and m.group(1) in _STAT_ALIASES:
        stages = 2 if m.group(2) else 1
        return {"stat_changes": [("self", _STAT_ALIASES[m.group(1)], stages)], "setup": True}

    # --- pure target stat-dropping status moves: "<STAT>_DOWN(_2)?" ---
    m = re.match(r"^([A-Z_]+?)_DOWN(_2)?$", etype)
    if m and m.group(1) in _STAT_ALIASES:
        stages = -(2 if m.group(2) else 1)
        return {"stat_changes": [("target", _STAT_ALIASES[m.group(1)], stages)]}

    # --- recoil ---
    m = re.match(r"^RECOIL_(QUARTER|THIRD|HALF)$", etype)
    if m:
        return {"recoil": _RECOIL_FRACTIONS[m.group(1)]}
    m = re.match(r"^RECOIL_(BURN|PARALYZE)_HIT$", etype)
    if m:
        return {"recoil": 1 / 3, "secondary": {"chance": chance, "effect": _STATUS_TOKEN_MAP[m.group(1)]}}

    # --- drain ---
    if etype == "RECOVER_HALF_DAMAGE_DEALT":
        return {"drain": 0.5}

    # --- OHKO ---
    if etype == "ONE_HIT_KO":
        return {"ohko": True, "risky": True}

    # --- protect / substitute / endure ---
    if etype == "PROTECT":
        return {"protect": True}
    if etype == "SET_SUBSTITUTE":
        return {"substitute": True, "setup": True}
    if etype == "SURVIVE_WITH_1_HP":
        return {"effect": "ENDURE"}

    # --- weather ---
    m = re.match(r"^WEATHER_(RAIN|SUN|HAIL|SANDSTORM)$", etype)
    if m:
        return {"effect": f"WEATHER_{m.group(1)}", "setup": True}

    # --- field effects / screens / hazards ---
    field_map = {
        "SET_REFLECT": {"effect": "REFLECT", "setup": True},
        "SET_LIGHT_SCREEN": {"effect": "LIGHT_SCREEN", "setup": True},
        "PREVENT_STATUS": {"effect": "SAFEGUARD"},
        "PREVENT_STAT_REDUCTION": {"effect": "MIST"},
        "DOUBLE_SPEED_3_TURNS": {"effect": "TAILWIND", "setup": True},
        "TRICK_ROOM": {"effect": "TRICK_ROOM"},
        "GRAVITY": {"effect": "GRAVITY"},
        "PREVENT_CRITS": {"effect": "LUCKY_CHANT"},
        "SET_SPIKES": {"effect": "SPIKES"},
        "STEALTH_ROCK": {"effect": "STEALTH_ROCK"},
        "TOXIC_SPIKES": {"effect": "TOXIC_SPIKES"},
        "RESTORE_HP_EVERY_TURN": {"effect": "AQUA_RING"},
        "GROUND_TRAP_USER_CONTINUOUS_HEAL": {"effect": "INGRAIN", "setup": True},
        "STATUS_LEECH_SEED": {"effect": "LEECH_SEED", "setup": True},
    }
    if etype in field_map:
        return field_map[etype]

    # --- recovery ---
    if etype == "RESTORE_HALF_HP":
        return {"effect": "RECOVER", "heal_fraction": 0.5}
    if etype == "HEAL_HALF_MORE_IN_SUN":
        return {"effect": "RECOVER", "heal_fraction": 0.5, "sun_boosted": True}
    if etype == "HEAL_HALF_REMOVE_FLYING_TYPE":
        return {"effect": "RECOVER", "heal_fraction": 0.5}
    if etype == "REST":
        return {"effect": "REST"}

    # --- non-standard damage (flat/variable/HP-based/charge-turn/etc.) ---
    if _is_non_standard_damage(etype):
        return {"nonstandard_damage": True}

    # --- plain damage, or an unrecognized status move: no special metadata ---
    return {}


def get_move_effect_meta(move_name, category, raw_effect):
    meta = derive_effect_meta(move_name, category, raw_effect)
    if move_name in MOVE_NAME_OVERRIDES:
        meta = {**meta, **MOVE_NAME_OVERRIDES[move_name]}
    if move_name in SOUND_MOVES:
        meta["sound"] = True
    return meta


# ============================================================
# STRUGGLE (Gen4-accurate hardcoded data)
# ============================================================
# Struggle isn't a real entry in moves_db.json and behaves unlike any
# other move in Gen4, so it's hardcoded here rather than run through the
# generic effect-derivation pipeline above:
#   - typeless: ignores the type chart entirely (a flat 1x neutral hit),
#     which is how it's able to hit Ghost-types despite being nominally
#     Normal-type.
#   - always_hit: bypasses the accuracy check completely (short of the
#     target being in a semi-invulnerable turn like Dig/Fly, which this
#     sim doesn't model, so in practice it simply never misses here).
#   - no_technician: its 50 base power is NOT boosted by Technician,
#     unlike every other <=60 power move.
#   - struggle_recoil: recoil is a flat 1/4 of the USER's max HP
#     (rounded down, minimum 1) rather than a fraction of damage dealt.
#     subscript_struggle checks no ability, so neither Rock Head nor Magic
#     Guard prevents it, and as a MOVE_SIDE_EFFECT_ON_HIT it also fires
#     when a Substitute takes the hit (see _struggle_recoil).
# It also has no PP pool of its own - it's used automatically whenever a
# Pokemon has no other move left with PP (see choose_move()).
STRUGGLE_MOVE_DATA = {
    "name": "MOVE_STRUGGLE",
    "type": "TYPE_NORMAL",
    "power": 50,
    "class": "CLASS_PHYSICAL",
    "accuracy": 100,
    "priority": 0,
    "pp": 1,
    "makes_contact": True,
    "can_be_protected": True,
    "typeless": True,
    "always_hit": True,
    "no_technician": True,
    "struggle_recoil": True,
}


# ============================================================
# LOAD DATABASES
# ============================================================
with open(MOVES_DB_FILE, "r", encoding="utf-8") as f:
    MOVES_DB = json.load(f)

_MOVES_BY_NAME = {m.get("name"): m for m in MOVES_DB.values() if isinstance(m, dict) and m.get("name")}
_MOVE_META_CACHE = {}


def get_move_data_by_name(move_name):
    """Merges raw moves_db.json fields (power/type/accuracy/priority/flags)
    with metadata derived from its own effect.type/chance via
    derive_effect_meta(). Cached per move name since it's pure/static.
    MOVE_STRUGGLE is special-cased to STRUGGLE_MOVE_DATA above instead of
    going through moves_db.json at all."""
    if move_name == "MOVE_STRUGGLE":
        return dict(STRUGGLE_MOVE_DATA)

    cached = _MOVE_META_CACHE.get(move_name)
    if cached is not None:
        return cached

    raw = _MOVES_BY_NAME.get(move_name)
    if raw is None:
        raw = {"name": move_name, "type": "TYPE_NORMAL", "power": 40, "class": "CLASS_PHYSICAL"}
        print(f"WARNING: move '{move_name}' not found in moves_db.json; treating as generic 40-power Normal move.")
    category = raw.get("class") or raw.get("category") or ("CLASS_STATUS" if raw.get("power", 0) == 0 else "CLASS_PHYSICAL")
    flags = raw.get("flags") or []
    merged = {
        "name": move_name,
        "type": raw.get("type", "TYPE_NORMAL"),
        "power": raw.get("power", raw.get("basePower", 0)) or 0,
        "class": category,
        "accuracy": raw.get("accuracy", raw.get("acc", 100)) or 100,
        # BattleControllerPlayer_CheckMoveHitAccuracy: a raw accuracy of 0 means the move never rolls an accuracy check
        # (self/field/side moves, Swift, Trump Card, ...), not "100% but evasion-affected".
        "no_accuracy_check": not raw.get("accuracy", raw.get("acc", 100)),
        "priority": raw.get("priority", 0) or 0,
        "pp": raw.get("pp", 15),
        "makes_contact": "MOVE_FLAG_MAKES_CONTACT" in flags,
        "can_be_protected": "MOVE_FLAG_CAN_PROTECT" in flags,
        # Targeting range - only meaningful in double battles (see
        # choose_target/run_battle_double); singles has exactly one
        # possible opponent so this is never consulted there.
        "range": raw.get("range") or "RANGE_SINGLE_TARGET",
    }
    merged.update(get_move_effect_meta(move_name, category, raw.get("effect")))
    _MOVE_META_CACHE[move_name] = merged
    return merged


# Spit Up's power scales with the user's CURRENT stockpile count (100/200/
# 300 power for 1/2/3 stacks, guaranteed to fail with 0 stacked) - a
# genuinely dynamic, per-use value that get_move_data_by_name's static,
# name-keyed cache can't represent on its own. Anywhere a move's data is
# needed together with a specific attacker (AI scoring, the switch
# heuristic, and actually using the move) should go through this wrapper
# instead of calling get_move_data_by_name directly, so Spit Up is
# perceived and resolved consistently everywhere.
SPIT_UP_POWER_BY_STACKS = {1: 100, 2: 200, 3: 300}


MAGNITUDE_TABLE = [(4, 10), (5, 30), (6, 50), (7, 70), (8, 90), (9, 110), (10, 150)]
MAGNITUDE_PROBS = [0.05, 0.10, 0.20, 0.30, 0.20, 0.10, 0.05]  # real Gen4 probability table


def roll_magnitude(rng):
    """Returns (magnitude_number, power) using the real Gen4 distribution."""
    roll = rng.random()
    cumulative = 0.0
    for (mag, power), prob in zip(MAGNITUDE_TABLE, MAGNITUDE_PROBS):
        cumulative += prob
        if roll < cumulative:
            return mag, power
    return MAGNITUDE_TABLE[-1]  # float-precision fallback


def compute_low_hp_power(hp, max_hp):
    """Reversal/Flail: the lower the user's remaining HP fraction, the
    higher the power - the real Gen3/4 lookup table, keyed by HP
    expressed in 48ths (floor(hp*48/max_hp))."""
    ratio = (hp * 48) // max(1, max_hp)
    if ratio <= 1:
        return 200
    if ratio <= 4:
        return 150
    if ratio <= 9:
        return 100
    if ratio <= 16:
        return 80
    if ratio <= 32:
        return 40
    return 20


# Hidden Power's 16 possible types, in the exact order the type-index
# formula below maps onto (Normal is never a possible result).
HIDDEN_POWER_TYPES = [
    "TYPE_FIGHTING", "TYPE_FLYING", "TYPE_POISON", "TYPE_GROUND", "TYPE_ROCK", "TYPE_BUG",
    "TYPE_GHOST", "TYPE_STEEL", "TYPE_FIRE", "TYPE_WATER", "TYPE_GRASS", "TYPE_ELECTRIC",
    "TYPE_PSYCHIC", "TYPE_ICE", "TYPE_DRAGON", "TYPE_DARK",
]


def compute_hidden_power(ivs):
    """Gen3/4 Hidden Power: both type and power are derived from the
    Pokemon's own IVs (fixed for its whole life, unlike everything else
    in this file that's computed per-battle-state). Note the bit order
    is HP/Atk/Def/SPEED/SpA/SpD, not the more usual HP/Atk/Def/SpA/SpD/
    Speed - that's a real, well-documented quirk of the original formula,
    not a typo here."""
    hp, atk, defn = ivs.get("hp", 31), ivs.get("atk", 31), ivs.get("def", 31)
    spa, spd, spe = ivs.get("spa", 31), ivs.get("spd", 31), ivs.get("spe", 31)

    type_bits = (hp % 2) + 2 * (atk % 2) + 4 * (defn % 2) + 8 * (spe % 2) + 16 * (spa % 2) + 32 * (spd % 2)
    type_index = (type_bits * 15) // 63
    hp_type = HIDDEN_POWER_TYPES[type_index]

    power_bits = ((hp // 2) % 2) + 2 * ((atk // 2) % 2) + 4 * ((defn // 2) % 2) + \
        8 * ((spe // 2) % 2) + 16 * ((spa // 2) % 2) + 32 * ((spd // 2) % 2)
    power = 30 + (power_bits * 40) // 63

    return hp_type, power


def get_effective_move_data(move_name, attacker, defender=None, bstate=None, rng=None, moved_second=False):
    """Wraps get_move_data_by_name to inject state-dependent overrides that
    a static, cached move dict can't capture: Spit Up's stockpile-scaled
    power, Magnitude's random power (a fixed expected value when rng isn't
    given, e.g. for AI scoring - a real roll only happens where rng is
    passed, i.e. actual execution), Weather Ball's weather-dependent
    type/power, Payback's moved-second doubling, Avalanche/Revenge's
    took-damage-this-turn doubling, Brine's low-HP-target doubling,
    Facade's own-status doubling, Rollout/Ice Ball's escalating power,
    Punishment's power scaling with the TARGET's positive stat stages,
    Reversal/Flail's power scaling with the USER's own missing HP, and
    Hidden Power's IV-derived type/power.
    Anywhere a move's data is needed together with a specific attacker
    should go through this wrapper instead of calling
    get_move_data_by_name directly."""
    mv = get_move_data_by_name(move_name)

    if move_name == "MOVE_SPIT_UP":
        mv = dict(mv)
        mv["power"] = SPIT_UP_POWER_BY_STACKS.get(attacker.get("stockpile", 0), 0)
        return mv

    if mv.get("magnitude"):
        mv = dict(mv)
        if rng is not None:
            mag, power = roll_magnitude(rng)
            mv["power"] = power
            mv["_magnitude_display"] = mag
        else:
            mv["power"] = 71  # expected value (sum of power*probability) for AI scoring
        return mv

    if mv.get("weather_ball") and bstate is not None:
        mv = dict(mv)
        weather = weather_now(bstate)
        weather_type = {"RAIN": "TYPE_WATER", "SUN": "TYPE_FIRE", "HAIL": "TYPE_ICE"}.get(weather)
        if weather_type:
            mv["type"] = weather_type
            mv["power"] = 100
        elif weather == "SANDSTORM":
            mv["power"] = 100  # power still doubles; type stays Normal in a sandstorm
        else:
            mv["power"] = 50
        return mv

    if mv.get("payback"):
        base = mv.get("power", 50)
        if moved_second:
            mv = dict(mv)
            mv["power"] = base * 2
        return mv

    if attacker.get("charged") and mv.get("type") == "TYPE_ELECTRIC" and mv.get("class") != "CLASS_STATUS" and not mv.get("charges_electric"):
        # Charge's own use is excluded above (charges_electric) so using
        # Charge again doesn't "double" its own (zero) power - only a
        # genuine Electric-type damaging move benefits. The charge is
        # actually CONSUMED elsewhere (see the post-move cleanup next to
        # White Herb's own check), not here, since this function can
        # also be called for AI-scoring predictions that must never
        # have the side effect of spending the charge early.
        mv = dict(mv)
        mv["power"] = mv.get("power", 0) * 2

    if mv.get("avalanche_revenge"):
        base = mv.get("power", 60)
        if attacker.get("_damage_taken_this_turn", 0) > 0:
            mv = dict(mv)
            mv["power"] = base * 2
        return mv

    if mv.get("target_revenge") and defender is not None:
        # Assurance: doubles power if the TARGET (not the user) has
        # already taken any damage this turn - direct attacks, recoil,
        # crash damage, or hurting itself in confusion all count (see
        # _damage_taken_this_turn's various set points). Life Orb isn't
        # modeled in this simulator, so it can't yet contribute to this
        # check specifically, though every other listed source can.
        base = mv.get("power", 50)
        if defender.get("_damage_taken_this_turn", 0) > 0:
            mv = dict(mv)
            mv["power"] = base * 2
        return mv

    if mv.get("brine") and defender is not None:
        base = mv.get("power", 65)
        if defender.get("hp", 1) <= defender.get("max_hp", 1) // 2:
            mv = dict(mv)
            mv["power"] = base * 2
        return mv

    if mv.get("double_power_when_statused"):
        if attacker.get("status", "NONE") in ("BURN", "PARALYSIS", "POISON", "TOXIC"):
            mv = dict(mv)
            mv["power"] = mv.get("power", 70) * 2
        return mv

    if mv.get("rollout"):
        base = mv.get("power", 30)
        uses_so_far = attacker.get("rollout_turns", 0)  # 0 on the first use of a new lock
        multiplier = 2 ** min(uses_so_far, 4)
        if attacker.get("defense_curled"):
            multiplier *= 2
        mv = dict(mv)
        mv["power"] = base * multiplier
        return mv

    if mv.get("punishment") and defender is not None:
        # 60 base, +20 per positive stat stage the TARGET has (ALL seven
        # stages count - Atk/Def/SpA/SpD/Spe/Accuracy/Evasion - not just
        # the "main" five), capped at 7 stages counted (200 power total).
        # Lowered stages never subtract anything.
        positive_stages = sum(
            max(0, defender.get(f"{s}_stage", 0)) for s in ("atk", "def", "spa", "spd", "spe", "acc", "eva")
        )
        mv = dict(mv)
        mv["power"] = 60 + 20 * min(positive_stages, 7)
        return mv

    if mv.get("low_hp_power"):
        mv = dict(mv)
        mv["power"] = compute_low_hp_power(attacker["hp"], attacker["max_hp"])
        return mv

    if mv.get("hp_scaling_power"):
        # Eruption/Water Spout: power = base_power * current_hp/max_hp,
        # floored but never below 1 even at very low HP.
        mv = dict(mv)
        base_power = mv.get("power", 150) or 150
        mv["power"] = max(1, (base_power * attacker["hp"]) // max(1, attacker["max_hp"]))
        return mv

    if mv.get("target_hp_scaling_power") and defender is not None:
        # Wring Out: power = 1 + 120 * (target's current HP / target's
        # max HP) - ranges from 1 (target nearly fainted) up to 121
        # (target at full HP). Scales off the DEFENDER's HP, the
        # opposite of Eruption/Water Spout above.
        mv = dict(mv)
        mv["power"] = 1 + (120 * defender["hp"]) // max(1, defender.get("max_hp", defender["hp"]))
        return mv

    if mv.get("hidden_power"):
        hp_type, power = compute_hidden_power(attacker.get("ivs", {}))
        mv = dict(mv)
        mv["type"] = hp_type
        mv["power"] = power
        return mv

    return mv



# ============================================================
# ABILITY HELPERS
# ============================================================
DESIRABLE_ABILITIES = {  # used by the Expert-flag Role Play/Skill Swap routine
    "SPEED_BOOST", "BATTLE_ARMOR", "SAND_VEIL", "STATIC", "FLASH_FIRE", "WONDER_GUARD",
    "EFFECT_SPORE", "SWIFT_SWIM", "HUGE_POWER", "RAIN_DISH", "CUTE_CHARM", "SHED_SKIN",
    "MARVEL_SCALE", "PURE_POWER", "CHLOROPHYLL", "SHIELD_DUST", "ADAPTABILITY", "MAGIC_GUARD",
    "MOLD_BREAKER", "SUPER_LUCK", "UNAWARE", "TINTED_LENS", "FILTER", "SOLID_ROCK", "RECKLESS",
}


def ability_of(mon):
    if mon.get("ability_suppressed"):               # Gastro Acid: MOVE_EFFECT_ABILITY_SUPPRESSED
        return "NONE"
    return (mon.get("ability") or "NONE").upper()


def has_ability(mon, name):
    return ability_of(mon) == name.upper()


def is_immune_by_ability(move_type, defender, attacker):
    """Type-immunity abilities (Basic-flag Step 1 checks)."""
    if has_ability(attacker, "MOLD_BREAKER"):
        return False
    dab = ability_of(defender)
    if move_type == "TYPE_ELECTRIC" and dab in ("VOLT_ABSORB", "MOTOR_DRIVE"):
        return True
    if move_type == "TYPE_WATER" and dab in ("WATER_ABSORB", "DRY_SKIN"):
        return True
    if move_type == "TYPE_FIRE" and dab == "FLASH_FIRE":
        return True
    if move_type == "TYPE_GROUND" and dab == "LEVITATE":
        return True
    return False


def get_type_effectiveness(attack_type, attacker, defender, typeless=False, gravity=False):
    """Full effectiveness including ability interactions. Returns a
    multiplier; 0.0 means immune. typeless=True is for Struggle: Gen4
    Struggle ignores the type chart entirely (always a neutral 1x hit,
    which is how it's able to hit Ghost-types despite nominally being a
    Normal-type move) and ignores type-based immunity abilities AND Wonder
    Guard: BattleSystem_ApplyTypeChart / CalcEffectiveness return on
    MOVE_STRUGGLE before their Wonder Guard, Filter and Solid Rock checks.
    gravity=True (Gravity is in effect) removes Flying-type's innate
    immunity to Ground-type moves AND ignores Levitate for Ground moves
    specifically, per Gen4 Gravity mechanics - it doesn't touch any of a
    Pokemon's OTHER type matchups (a Flying/Rock-type still takes Rock's
    own extra Ground weakness normally; a pure Flying-type just takes a
    neutral 1x hit once its immunity is removed)."""
    if typeless:
        return 1.0
    else:
        ground_gravity_bypass = gravity and attack_type == "TYPE_GROUND"
        if not ground_gravity_bypass and is_immune_by_ability(attack_type, defender, attacker):
            return 0.0
        if attack_type == "TYPE_GROUND" and defender.get("magnet_rise_turns", 0) > 0 and not defender.get("ingrain") \
                and _held_effect(defender)[0] != "HOLD_EFFECT_SPEED_DOWN_GROUNDED":
            return 0.0                                  # MOVE_STATUS_MAGNET_RISE
        defender_types = [t for t in [defender.get("type1"), defender.get("type2")] if t]
        if ground_gravity_bypass:
            defender_types = [t for t in defender_types if t != "TYPE_FLYING"]
        # Foresight / Odor Sleuth (identified) and Scrappy remove the Ghost type's immunity to Normal and Fighting; Miracle Eye
        # removes the Dark type's immunity to Psychic. apply_type_chart_damage already honours these, but this check runs first
        # and used to return 0 before the chart was ever consulted.
        if attack_type in ("TYPE_NORMAL", "TYPE_FIGHTING") and (has_ability(attacker, "SCRAPPY") or defender.get("foresight")):
            defender_types = [t for t in defender_types if t != "TYPE_GHOST"]
        if attack_type == "TYPE_PSYCHIC" and defender.get("miracle_eye"):
            defender_types = [t for t in defender_types if t != "TYPE_DARK"]
        mult = type_effectiveness_raw(attack_type, defender_types)
        if mult == 0.0:
            return 0.0
    dab = ability_of(defender)
    aab = ability_of(attacker)
    if dab == "WONDER_GUARD" and mult <= 1.0 and aab != "MOLD_BREAKER":
        return 0.0
    if dab in ("SOLID_ROCK", "FILTER") and mult > 1.0 and aab != "MOLD_BREAKER":
        mult *= 0.75
    return mult


def get_stat_multiplier(stage):
    stage = max(-6, min(6, stage))
    return (2.0 + stage) / 2.0 if stage >= 0 else 2.0 / (2.0 - stage)


STATUS_IMMUNITY_ABILITIES = {
    "SLEEP": {"INSOMNIA", "VITAL_SPIRIT"},
    "POISON": {"IMMUNITY"},
    "TOXIC": {"IMMUNITY"},
    "PARALYZE": {"LIMBER"},
    "BURN": {"WATER_VEIL"},
    "CONFUSE": {"OWN_TEMPO"},
    "ATTRACT": {"OBLIVIOUS"},
    "FREEZE": {"MAGMA_ARMOR"},
}


# subscript_paralyze / _burn / _poison / _badly_poison / _fall_asleep check Leaf Guard in harsh sunlight; _freeze does not
_LEAF_GUARD_STATUSES = ("SLEEP", "POISON", "TOXIC", "PARALYZE", "BURN")


def status_blocked_by_ability(status, mon, weather=None):
    """The infliction scripts' ability gates. Magic Guard is NOT one of them (it only stops the residual damage / the full-paralysis roll)."""
    if weather == "SUN" and status in _LEAF_GUARD_STATUSES and has_ability(mon, "LEAF_GUARD"):
        return True
    return ability_of(mon) in STATUS_IMMUNITY_ABILITIES.get(status, set())


def status_blocked_by_type(status, mon):
    """The infliction scripts' type gates: Poison / Steel vs poison, Fire vs burn, Ice vs freezing. There is NO Electric immunity to
    paralysis in Platinum (subscript_paralyze checks only Limber, Leaf Guard, Safeguard, Shield Dust and Substitute)."""
    types = {mon.get("type1"), mon.get("type2")}
    if status in ("POISON", "TOXIC"):
        return bool(types & {"TYPE_POISON", "TYPE_STEEL"})
    if status == "BURN":
        return "TYPE_FIRE" in types
    if status == "FREEZE":
        return "TYPE_ICE" in types
    return False


def can_be_attracted(source, victim):
    """Whether victim could become attracted to source - the same
    checks Attract's own effect applies (already attracted, Oblivious,
    matching genders, or either genderless all block it), reused here
    for Cute Charm's own contact-triggered Attract infliction."""
    return not victim.get("attracted") and not has_ability(victim, "OBLIVIOUS") \
        and victim.get("gender") != source.get("gender") \
        and "GENDERLESS" not in (source.get("gender"), victim.get("gender"))


def can_inflict_status(status, attacker, defender, weather=None):
    if defender.get("status", "NONE") != "NONE":
        return False
    if status == "FREEZE" and weather == "SUN":
        return False                                    # subscript_freeze: nothing freezes in harsh sunlight
    if defender.get("safeguard", 0) > 0 and attacker is not defender:
        return False
    if status_blocked_by_type(status, defender):
        return False
    if status_blocked_by_ability(status, defender, weather) and not has_ability(attacker, "MOLD_BREAKER"):
        return False
    return True


# ============================================================
# TRAINER LOADER
# ============================================================
def format_class_title(class_str):
    """'CLASS_ACE_TRAINER' / 'TRAINER_CLASS_ACE_TRAINER' -> 'Ace Trainer'.
    Still used for the standings exports' separate "Class" column (see
    _standings_rows) - just no longer used to build the DISPLAY name,
    see format_display_from_key below."""
    if not class_str:
        return ""
    s = class_str
    for prefix in ("TRAINER_CLASS_", "CLASS_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return " ".join(w.capitalize() for w in s.split("_") if w)


# Rival Barry's team is always the COUNTER-PICK to whatever starter the
# player chose (Grass < Fire < Water < Grass), not the starter named in
# the trainer file itself - a file whose key mentions "piplup" represents
# the player having picked Piplup, so Barry is actually using Turtwig
# (final form Torterra). Used both by format_display_from_key (to show
# Barry's own team correctly rather than literally repeating the
# player's choice) and by find_starter_triangle_trainers further down.
STARTER_COUNTER_PICK = {"TURTWIG": "CHIMCHAR", "CHIMCHAR": "PIPLUP", "PIPLUP": "TURTWIG"}
STARTER_FINAL_EVO = {"TURTWIG": "Torterra", "CHIMCHAR": "Infernape", "PIPLUP": "Empoleon"}


def format_display_from_key(base_key):
    """Turns a filename-derived base_key into a readable display name by
    replacing underscores with spaces and capitalizing each word, e.g.
    'galactic_grunt_floaroma_meadow_1' -> 'Galactic Grunt Floaroma Meadow 1'.
    Used instead of the trainer JSON's own "name"/"class" fields: for
    generic trainers (Grunt, Youngster, Ace Trainer, ...) those fields are
    often an identical placeholder shared by dozens of distinct trainer
    files, which collapsed every one of them down to the same display
    name in match logs, standings, and exports. The filename itself is
    always unique (that's the whole reason it's used as the trainer key),
    so deriving the display name from it guarantees every trainer prints
    distinctly.

    Rival Barry's trainer files are named after the PLAYER's starter (see
    STARTER_COUNTER_PICK) - a key like 'rival_1_chimchar' means "the
    player chose Chimchar", so Barry's own team is actually built around
    the counter-pick (Piplup), not Chimchar itself. Displaying the fight
    under the player's Pokemon rather than Barry's own would be
    confusing, so the starter word is swapped for the fully-evolved form
    of what Barry is ACTUALLY carrying (e.g. Empoleon)."""
    words = base_key.replace("_", " ").split()
    if "rival" in base_key.lower():
        for starter in STARTER_COUNTER_PICK:
            if any(w.lower() == starter.lower() for w in words):
                barry_final_evo = STARTER_FINAL_EVO[STARTER_COUNTER_PICK[starter]]
                words = [barry_final_evo if w.lower() == starter.lower() else w for w in words]
                break
    return " ".join(w.capitalize() for w in words)


REMATCH_FILENAME_RE = re.compile(r"^(?P<base>.+?)_rematch(?:_(?P<num>\d+))?$", re.IGNORECASE)


def parse_trainer_filename(key):
    """key is the filename without extension, e.g. 'ace_trainer_dennis' or
    'ace_trainer_dennis_rematch_1'. Returns (base_key, tier) where tier=0
    for the base encounter, 1/2/3/... for '..._rematch_1' / '_rematch_2'
    / etc, and 1 for a bare '..._rematch' with no number (a trainer with
    exactly one rematch)."""
    m = REMATCH_FILENAME_RE.match(key)
    if m:
        return m.group("base"), (int(m.group("num")) if m.group("num") else 1)
    return key, 0


# ============================================================
# NPC TRAINER PERSONALITY (gender / nature / ability slot / IVs)
# ============================================================
# A trainer's party entry only says species, level and an IV scale (HGSS adds gender / ability overrides). When the party is created the
# game builds a personality value for every mon and everything else follows from it: TrainerData_BuildParty in pokeplatinum's
# trainer_data.c (and CreateNPCTrainerParty in pokeheartgold's, which has the same shape):
#     seed        = ivScale + level + species ID + trainer ID              (level = the mon's ORIGINAL level, not a set level)
#     personality = LCRNG_Next() repeated trainerClass-index times from that seed (the seed itself if the index is 0)
#     personality = (personality << 8) + genderMod                          (genderMod 0x78 for a female class, else 0x88)
#     IVs         = ivScale * 31 / 255 for all six stats
# gender = species gender ratio vs the personality's low byte, nature = personality % 25, ability = the second slot when the
# personality is odd and the species has one (the gender byte is even, so in Platinum that is always the first ability).
# HGSS also lets a party entry override gender and ability: TrMon_OverridePidGender rewrites the gender byte in place, and because that
# variable lives across the party loop an override keeps applying to the mons after it (reproduced on purpose).
MAX_IV_SCALE = 255
NATURE_ORDER = ("HARDY", "LONELY", "BRAVE", "ADAMANT", "NAUGHTY", "BOLD", "DOCILE", "RELAXED", "IMPISH", "LAX", "TIMID", "HASTY",
                "SERIOUS", "JOLLY", "NAIVE", "MODEST", "MILD", "QUIET", "BASHFUL", "RASH", "CALM", "GENTLE", "SASSY", "CAREFUL", "QUIRKY")
_U32 = 0xFFFFFFFF
_LCRNG_MULTIPLIER, _LCRNG_INCREMENT = 1103515245, 24691
HGSS_GENDER_OVERRIDE_VALUES = {"TRPOKE_GENDER_OVERRIDE_OFF": 0, "TRPOKE_GENDER_OVERRIDE_MALE": 1, "TRPOKE_GENDER_OVERRIDE_FEMALE": 2}
HGSS_ABILITY_OVERRIDE_VALUES = {"TRPOKE_ABILITY_OVERRIDE_OFF": 0, "TRPOKE_ABILITY_OVERRIDE_FIRST": 1, "TRPOKE_ABILITY_OVERRIDE_SECOND": 2}
# The generated trainer-ID list in this checkout has no entry for a few data files: the "_postgame" files sit under the plain trainer's
# constant, and the Survival Area rival files carry no 1_/2_ number. The mapping below is the best pairing (base fight -> 1_, rematch
# -> 2_); a file that fits none of these gets trainer ID 0.
PLATINUM_TRAINER_FILE_ALIASES = {
    "rival_survival_area_piplup": "TRAINER_RIVAL_SURVIVAL_AREA_1_PIPLUP", "rival_survival_area_turtwig": "TRAINER_RIVAL_SURVIVAL_AREA_1_TURTWIG",
    "rival_survival_area_chimchar": "TRAINER_RIVAL_SURVIVAL_AREA_1_CHIMCHAR",
    "rival_survival_area_piplup_rematch": "TRAINER_RIVAL_SURVIVAL_AREA_2_PIPLUP",
    "rival_survival_area_turtwig_rematch": "TRAINER_RIVAL_SURVIVAL_AREA_2_TURTWIG",
    "rival_survival_area_chimchar_rematch": "TRAINER_RIVAL_SURVIVAL_AREA_2_CHIMCHAR",
}
_PERSONALITY_TABLES = {}


def npc_personality(iv_scale, level, species_id, trainer_id, class_index, gender_mod):
    """The personality value TrainerData_BuildParty / CreateNPCTrainerParty computes (all u32 arithmetic)."""
    state = rnd = (iv_scale + level + species_id + trainer_id) & _U32
    for _ in range(class_index):
        state = (state * _LCRNG_MULTIPLIER + _LCRNG_INCREMENT) & _U32
        rnd = state >> 16
    return ((rnd << 8) + gender_mod) & _U32


def personality_nature(personality):
    return "NATURE_" + NATURE_ORDER[personality % 25]


def personality_gender(ratio, personality):
    """SpeciesData_GetGenderOf: "MALE" / "FEMALE" / "GENDERLESS" for a species gender ratio (0 male only, 254 female only, 255 none)."""
    if ratio == 0:
        return "MALE"
    if ratio == 254:
        return "FEMALE"
    if ratio == 255:
        return "GENDERLESS"
    return "FEMALE" if ratio > (personality & 0xFF) else "MALE"


def hgss_override_gender_byte(gender_byte, ratio, gender_override, ability_override):
    """TrMon_OverridePidGender: the gender byte a mon with a gender / ability override uses (and every later mon of the party keeps)."""
    g = HGSS_GENDER_OVERRIDE_VALUES.get(gender_override, 0)
    a = HGSS_ABILITY_OVERRIDE_VALUES.get(ability_override, 0)
    if g or a:
        if g:
            gender_byte = ((ratio or 0) + 2 if g == 1 else (ratio or 0) - 2) & _U32
        if a == 1:
            gender_byte &= ~1 & _U32
        elif a == 2:
            gender_byte |= 1
    return gender_byte


def _read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_personality_tables(game, repo_dir=None):
    """The decomp tables the derivation needs, or None if the checkout (or one of its files) is not there: trainer ID by constant,
    trainer-class index and gender, species ID. `game` is "platinum" or "hgss"."""
    try:
        if game == "platinum":
            repo = repo_dir or PLATINUM_REPO_DIR
            trainers = _read_lines(os.path.join(repo, "generated", "trainers.txt"))
            classes = _read_lines(os.path.join(repo, "generated", "trainer_classes.txt"))
            species = _read_lines(os.path.join(repo, "generated", "species.txt"))
            genders = _read_text(os.path.join(repo, "include", "data", "trainer_class_genders.h"))
            return {"game": game, "trainer_ids": {n: i for i, n in enumerate(trainers)},
                    "class_index": {n: i for i, n in enumerate(classes)},
                    "class_female": set(re.findall(r"\[(TRAINER_CLASS_\w+)\]\s*=\s*GENDER_FEMALE", genders)),
                    "species_id": {n: i for i, n in enumerate(species)}, "unmapped": []}
        if game == "hgss":
            repo = repo_dir or HGSS_REPO_DIR
            classes = _read_text(os.path.join(repo, "include", "constants", "trainer_class.h"))
            species = _read_text(os.path.join(repo, "include", "constants", "species.h"))
            genders = _read_text(os.path.join(repo, "src", "trainer_data.c"))
            return {"game": game,
                    "class_index": {n: int(v) for n, v in re.findall(r"#define\s+(TRAINERCLASS_\w+)\s+(\d+)\b", classes)},
                    "class_female": {n for g, n in re.findall(r"(TRAINER_MALE|TRAINER_FEMALE)\s*,\s*//\s*(TRAINERCLASS_\w+)", genders)
                                     if g == "TRAINER_FEMALE"},
                    "species_id": {n: int(v) for n, v in re.findall(r"#define\s+(SPECIES_\w+)\s+(\d+)\b", species)}}
    except OSError:
        return None
    raise ValueError(f"unknown game {game!r}")


def get_personality_tables(game):
    """load_personality_tables, cached, and None (with one warning) when disabled or the decomp files are missing."""
    if not TRAINER_PERSONALITY_ENABLED:
        return None
    if game not in _PERSONALITY_TABLES:
        tables = load_personality_tables(game)
        if tables is None:
            print(f"WARNING: {game} decomp data for trainer personalities not found - its trainers' Pokemon get no nature and no gender "
                  f"(check PLATINUM_REPO_DIR / HGSS_REPO_DIR).")
        _PERSONALITY_TABLES[game] = tables
    return _PERSONALITY_TABLES[game]


def platinum_trainer_id(tables, key):
    """Trainer ID of a Platinum trainer file (its position in the generated trainer list); 0 when the file has no constant."""
    ids = tables["trainer_ids"]
    candidates = ["TRAINER_" + key.upper(), PLATINUM_TRAINER_FILE_ALIASES.get(key)]
    if key.endswith("_postgame"):
        candidates.append("TRAINER_" + key[:-len("_postgame")].upper())
    for candidate in candidates:
        if candidate in ids:
            return ids[candidate]
    if key not in tables["unmapped"]:
        tables["unmapped"].append(key)
    return 0


def assign_trainer_personalities(party, tables, trainer_id, class_name):
    """Derives personality, nature, gender and ability slot for each raw party dict (species, level, iv_scale, HGSS overrides) and stores
    them on it, without overriding anything the entry already names. Returns False when the class is unknown."""
    class_index = tables["class_index"].get(class_name)
    if class_index is None:
        return False
    gender_byte = 120 if class_name in tables["class_female"] else 136            # 0x78 / 0x88
    hgss = tables["game"] == "hgss"
    for mon in party:
        species = mon.get("species")
        species_id = tables["species_id"].get(species)
        if species_id is None:
            continue
        ratio = SPECIES_GENDER_RATIO.get(species)
        if hgss:
            gender_byte = hgss_override_gender_byte(gender_byte, ratio, mon.get("genderOverride"), mon.get("abilityOverride"))
        personality = npc_personality(mon.get("iv_scale") or 0, mon.get("level", 50), species_id, trainer_id, class_index, gender_byte)
        mon["personality"] = personality
        if not mon.get("nature"):
            mon["nature"] = personality_nature(personality)
        if ratio is not None and not mon.get("gender"):
            mon["gender"] = personality_gender(ratio, personality)
        if not any(k in mon for k in ("ability", "abilityNum", "ability_num")):
            mon["abilityNum"] = personality & 1
    return True


def personalise_platinum_party(party, key, class_name):
    """Enriches the raw party dicts of Platinum trainer file `key` in place; False if the derivation is unavailable."""
    tables = get_personality_tables("platinum")
    return bool(tables) and assign_trainer_personalities(party, tables, platinum_trainer_id(tables, key), class_name)


def personalise_hgss_party(party, trainer_index, class_name):
    """Same for an HGSS trainer (its ID is its position in trainers.json)."""
    tables = get_personality_tables("hgss")
    return bool(tables) and assign_trainer_personalities(party, tables, trainer_index, class_name)


def resolve_ivs(mon):
    """IVs can show up under a few different keys depending on the trainer
    file's schema:
      - "ivs" / "iv" as a per-stat dict -> used directly (default 31 for
        any stat not present).
      - "ivs" / "iv" as a single flat value -> applied to all stats. Some
        decomp formats encode this on a 0-255 'IV quality' knob rather
        than a real 0-31 IV; detected by range (>31) and converted via
        iv = round(raw * 31 / 255).
      - "iv_scale" (Platinum's field; HGSS calls it "difficulty") is the real
        0-255 scale: every stat gets iv_scale * 31 / 255 (integer division, as
        in TrainerData_BuildParty), e.g. 250 -> 30, 50 -> 6, 0 -> 0.
      - None of the above -> defaults to 31 (perfect IVs) for every stat."""
    stat_keys = ("hp", "atk", "def", "spa", "spd", "spe")
    raw_iv = mon.get("iv", mon.get("ivs"))
    if isinstance(raw_iv, dict):
        return {k: raw_iv.get(k, 31) for k in stat_keys}
    if raw_iv is not None:
        val = raw_iv
        if val > 31:
            val = round(val * 31 / 255)
        return {k: val for k in stat_keys}
    iv_scale = mon.get("iv_scale")
    if iv_scale is not None:
        val = int(iv_scale) * 31 // MAX_IV_SCALE
        return {k: val for k in stat_keys}
    return {k: 31 for k in stat_keys}


def resolve_evs(raw_ev):
    stat_keys = ("hp", "atk", "def", "spa", "spd", "spe")
    if isinstance(raw_ev, dict):
        return {k: raw_ev.get(k, 0) for k in stat_keys}
    val = 0 if raw_ev is None else raw_ev
    return {k: val for k in stat_keys}


def moves_from_learnset(learnset_by_level, level, max_slots=4):
    """Mirrors the in-game behavior for a trainer party entry with no
    explicit moveset: the Pokemon knows whatever it would have learned by
    level-up at its current level, keeping only the most recent 4 distinct
    moves (a move learned later bumps the oldest one out of the lineup,
    same as it would for a Pokemon you raised yourself). learnset_by_level
    is the (level, move_name) list from the species data, sorted ascending."""
    ordered = []
    for lvl, move in learnset_by_level:
        if lvl > level:
            break
        if move in ordered:
            continue
        ordered.append(move)
    return ordered[-max_slots:]


def resolve_ability(mon, default_ability, abilities_list):
    """A party entry may name its ability directly ('ability': 'ABILITY_X'),
    or select a species ability slot by index ('abilityNum': 0 or 1)."""
    ability_raw = mon.get("ability")
    if ability_raw:
        return ability_raw.replace("ABILITY_", "").upper()
    slot = mon.get("abilityNum", mon.get("ability_num"))
    if slot is not None and abilities_list:
        idx = min(int(slot), len(abilities_list) - 1)
        return abilities_list[idx].replace("ABILITY_", "").upper()
    return (default_ability or "NONE").upper()


def _build_party_mon(mon):
    species = mon.get("species")
    type1, type2, base_stats, default_ability, abilities_list, learnset = get_species_info(species)

    raw_moves = mon.get("moves") or []
    clean_moves = [m for m in raw_moves if m and m != "MOVE_NONE"]

    original_level = mon.get("level", 50)
    # SET_LEVEL (set-level tournament mode) overrides every Pokemon's
    # actual battling level uniformly - see the constant's own comment.
    level = SET_LEVEL if SET_LEVEL is not None else original_level
    nature = mon.get("nature")

    if not clean_moves:
        # "moves": null (or empty) means the game derives the moveset from
        # the species' own level-up learnset - a party entry with no moves
        # at all here would never be able to act (this was the cause of
        # battles stalling out at the turn cap with nothing happening).
        # Which level that moveset is computed AT is independently
        # configurable from the battling level itself - see
        # MOVESET_LEVEL_SOURCE's own comment for why these two are kept
        # separate (a set-level run can still keep everyone's original,
        # in-game-appropriate moveset instead of scaling it up too).
        moveset_level = level if (SET_LEVEL is not None and MOVESET_LEVEL_SOURCE == "set") else original_level
        clean_moves = moves_from_learnset(learnset, moveset_level)
        if not clean_moves:
            # No learnset data available either (species missing from
            # SPECIES_DATA_DIR, or it genuinely has no level-up moves by
            # this level) - leave it moveless. choose_move()'s PP check
            # (an empty moveset has nothing with PP > 0) will correctly
            # fall back to Struggle every turn rather than soft-locking.
            print(f"WARNING: '{species}' (level {moveset_level}) has no explicit moves and no usable "
                  f"learnset data - it will only ever be able to use Struggle. Check its "
                  f"species file's learnset.by_level if this looks wrong.")
            clean_moves = []

    ivs = resolve_ivs(mon)
    evs = resolve_evs(mon.get("ev", mon.get("evs")))

    max_hp = calc_stat(base_stats["hp"], ivs["hp"], evs["hp"], level, is_hp=True)
    stats = {
        "atk": calc_stat(base_stats["atk"], ivs["atk"], evs["atk"], level, nature_mult=nature_multiplier(nature, "atk")),
        "def": calc_stat(base_stats["def"], ivs["def"], evs["def"], level, nature_mult=nature_multiplier(nature, "def")),
        "spa": calc_stat(base_stats["spa"], ivs["spa"], evs["spa"], level, nature_mult=nature_multiplier(nature, "spa")),
        "spd": calc_stat(base_stats["spd"], ivs["spd"], evs["spd"], level, nature_mult=nature_multiplier(nature, "spd")),
        "spe": calc_stat(base_stats["spe"], ivs["spe"], evs["spe"], level, nature_mult=nature_multiplier(nature, "spe")),
    }
    ability = resolve_ability(mon, default_ability, abilities_list)

    # PP pool: one entry per known move, seeded from moves_db.json's own
    # "pp" field (via get_move_data_by_name, which is already loaded by
    # the time trainers are built). MOVE_STRUGGLE deliberately has no
    # entry here - it isn't a "known" move, it's the automatic fallback
    # choose_move() reaches for once every entry below hits 0.
    move_pp = {name: get_move_data_by_name(name).get("pp", 15) for name in clean_moves}

    return {
        "species": species,
        "species_display": species.replace("SPECIES_", "").replace("_", " "),
        "level": level,
        "ivs": ivs,
        "hp": max_hp,
        "max_hp": max_hp,
        "atk": stats["atk"], "def": stats["def"], "spa": stats["spa"], "spd": stats["spd"], "speed": stats["spe"],
        "type1": type1, "type2": type2, "types": [t for t in (type1, type2) if t],
        "ability": ability,
        "species_abilities": tuple(a.replace("ABILITY_", "").upper() for a in list(abilities_list or [])[:2]),
        "ai_known_ability": None,          # what the OPPONENT's AI has seen of this mon's ability (see ai_load_ability)
        "item": mon.get("item", None),
        "gender": mon.get("gender", "GENDERLESS"),
        "contributors": {}, "supporters": {},        # assist tracking (see note_contribution)
        "debuff_source": {},                          # {"atk"/"def"/"spa"/"spd"/"spe": (side, species, turn, magnitude)}
        "nature": nature,
        "personality": mon.get("personality"),
        "moves": clean_moves,
        "move_pp": move_pp,
        "status": "NONE",
        "perish_song": 0,
        "stockpile": 0,
        "cursed": False,
        "yawn_turn": 0,
        "nightmare": False,
        "imprison_moves": None,
        "bide_turns": 0, "bide_damage": 0,
        "_fainted_already_logged": False,
        "prev_turn_hit_type": None, "this_turn_hit_type": None, "move_hit": None, "move_hit_slot": None,
        "last_move_used": None, "mimic_active_move": None,
        "must_recharge": False,
        "rampage_move": None, "rampage_turns": 0,
        "taunt_turns": 0, "tormented": False, "encore_turns": 0, "encore_move": None,
        "rollout_move": None, "rollout_turns": 0, "defense_curled": False,
        "acted_since_switch_in": False,
        "vanished": None,  # "FLY"/"DIG"/"DIVE"/"BOUNCE" while charging on turn 1 of a two-turn move
        "atk_stage": 0, "def_stage": 0, "spa_stage": 0, "spd_stage": 0, "spe_stage": 0,
        "acc_stage": 0, "eva_stage": 0,
        "confused": False, "confuse_turns": 0,
        "flinched": False, "protect_used_last": False, "protect_chain": 0,
        "substitute_hp": 0, "leech_seeded": False, "toxic_turns": 0,
        "aqua_ring": False, "ingrain": False,
        "first_turn": True,
    }


def load_trainers_from_repo():
    """Returns (trainers_db, display_names), both keyed by a unique,
    filename-derived key (NOT the trainer's in-game "name" field, since
    Platinum's rematch trainers reuse the same display name across
    multiple separate files - keying on "name" would silently collide
    and drop rematches).

    Rematch tiers are read directly from the filename convention:
    'ace_trainer_dennis.json' (base fight) plus 'ace_trainer_dennis_rematch_1.json',
    '..._rematch_2.json', etc (or a bare '..._rematch.json' for a trainer
    with only one rematch). Display naming: the base fight gets no
    suffix; if a trainer has exactly one rematch file it's shown as
    "... Rematch" (no number); with two or more rematch files they're
    numbered "... Rematch 1", "... Rematch 2", etc, in filename order."""
    trainers_db = {}
    display_names = {}
    if not os.path.exists(TRAINER_DATA_DIR):
        print(f"WARNING: Trainer directory not found at {TRAINER_DATA_DIR}.")
        return trainers_db, display_names

    raw_entries = []  # (key, base_key, tier, parsed_data)
    filenames = sorted(f for f in os.listdir(TRAINER_DATA_DIR) if f.endswith(".json"))
    for filename in filenames:
        filepath = os.path.join(TRAINER_DATA_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error parsing {filename}: {e}")
            continue
        key = os.path.splitext(filename)[0]
        base_key, tier = parse_trainer_filename(key)
        raw_entries.append((key, base_key, tier, data))

    groups = defaultdict(list)
    for key, base_key, tier, data in raw_entries:
        groups[base_key].append((tier, key, data))

    skipped = []
    for base_key, entries in groups.items():
        entries.sort(key=lambda e: e[0])  # tier 0 (base fight) first, then 1, 2, ...
        n = len(entries)
        for i, (tier, key, data) in enumerate(entries):
            if i == 0:
                suffix = ""
            elif n == 2:
                suffix = " Rematch"
            else:
                suffix = f" Rematch {i}"
            display_base_name = format_display_from_key(base_key)
            display = f"{display_base_name}{suffix}".strip()

            try:
                party_raw = [dict(mon) for mon in (data.get("party") or []) if mon]
                personalise_platinum_party(party_raw, key, data.get("class"))
                party = [_build_party_mon(mon) for mon in party_raw]
                if not party:
                    # A trainer with an empty/null party (or one where every
                    # mon failed to build) can't ever be sent into battle -
                    # run_battle would crash trying to index party[0]. Skip
                    # it from the tournament rather than let one bad file
                    # take down an hours-long run; this is usually a stub/
                    # unused trainer slot in the game's own data rather than
                    # something to fix in this script.
                    raise ValueError("empty party (no valid Pokemon parsed)")
                raw_flags = data.get("ai_flags") or []
                ai_flags = [flag.replace("AI_FLAG_", "TRAINER_AI_") for flag in raw_flags if flag]
                trainers_db[key] = {
                    "class": data.get("class"),
                    "base_name": display_base_name,
                    "ai_flags": ai_flags if ai_flags else ["TRAINER_AI_BASIC"],
                    "items": [i for i in (data.get("items") or []) if i and i != "ITEM_NONE"],
                    "party": party,
                    "double_battle": bool(data.get("double_battle", False)),
                }
                display_names[key] = display
            except Exception as e:
                skipped.append((key, display, str(e)))

    if skipped:
        print(f"WARNING: skipped {len(skipped)} trainer(s) that couldn't be loaded into the tournament:")
        for key, display, reason in skipped:
            print(f"  - {display} ({key}): {reason}")

    return trainers_db, display_names


# ============================================================
# HEARTGOLD/SOULSILVER TRAINER LOADING
# ============================================================
# HGSS's entire trainer roster lives in one JSON file
# ({"trainers": [...]}), not one file per trainer, and its per-trainer
# shape differs from Platinum's in several confirmed ways: ai_flags is
# an integer BITMASK rather than a list of named AI_FLAG_ strings;
# abilityOverride is an explicit string enum
# (TRPOKE_ABILITY_OVERRIDE_OFF/_SECOND) rather than an ability-slot
# integer; a Pokemon's "moves" key is OMITTED ENTIRELY (not an explicit
# null) when it should use its level-up learnset; "double" is 0 for a
# single battle and 2 (not 1) for a double battle; and rematches have no
# explicit tag or unique file name at all - the same trainer (identified
# by class+name) just appears as multiple separate array entries with
# nothing marking "first fight" vs "rematch".

# Story-important trainer classes: these are the ones where the SAME
# class+name recurring legitimately means "the same story character,
# encountered again later" (a rematch) rather than coincidence.
# Confirmed against the real data: gym leaders each have their own
# uniquely-named class (TRAINERCLASS_LEADER_BROCK, etc.), so checking by
# class alone already disambiguates them; Rival, the Elite Four, the
# Champion, Team Rocket's executives, and the Rocket Boss share one
# class across multiple chronological encounters instead. Every OTHER
# class (Grunt, Camper, Swimmer, Beauty, Bug Catcher, etc.) can and does
# reuse the same class+name combination purely by coincidence across
# many unrelated, independent NPCs (e.g. dozens of different "Camper
# Mickey"s scattered across different routes) - those must NOT be
# collapsed into fake rematch tiers of one another.
HGSS_STORY_CLASS_PREFIXES = (
    "TRAINERCLASS_RIVAL",
    "TRAINERCLASS_LEADER_",
    "TRAINERCLASS_ELITE_FOUR_",
    "TRAINERCLASS_CHAMPION",
    "TRAINERCLASS_EXECUTIVE_",
    "TRAINERCLASS_ROCKET_BOSS",
)


def _hgss_is_story_class(cls):
    return any(cls == p or cls.startswith(p) for p in HGSS_STORY_CLASS_PREFIXES)


# Real bit -> AI_FLAG_ mapping, confirmed against script.s's own
# FlagTable (the actual Gen4 AI script dispatch table - each bit
# position selects a distinct AI script, run once per bit set in a
# trainer's AI bitmask). This REPLACES an earlier reconstruction that
# was inferred purely from observed bitmask values without the real
# header/table available - that guess was wrong: it had WEATHER and
# HARASSMENT at bit positions 6/7 instead of their real 9/10, and was
# missing BATON_PASS, TAG_STRATEGY, and CHECK_HP entirely, meaning any
# HGSS trainer whose AI bitmask used bits 6-10 would have silently run
# the wrong AI script (or none at all) for those bits. The previously
# "unexplained" bit 9 seen in real observed values (513/517/519) is
# confirmed here to be exactly AI_FLAG_WEATHER, which fully explains
# those values once decoded with this corrected table.
HGSS_AI_FLAG_BITS = {
    0: "AI_FLAG_BASIC",
    1: "AI_FLAG_EVALUATE_ATTACK",
    2: "AI_FLAG_EXPERT",
    3: "AI_FLAG_SETUP_FIRST_TURN",
    4: "AI_FLAG_RISKY",
    5: "AI_FLAG_PRIORITIZE_EXTREMES",
    6: "AI_FLAG_BATON_PASS",
    7: "AI_FLAG_TAG_STRATEGY",
    8: "AI_FLAG_CHECK_HP",
    9: "AI_FLAG_WEATHER",
    10: "AI_FLAG_HARASSMENT",
    28: "AI_FLAG_ROAMING_POKEMON",
    29: "AI_FLAG_SAFARI",
    30: "AI_FLAG_CATCH_TUTORIAL",
}

HGSS_ABILITY_OVERRIDE_TO_SLOT = {
    "TRPOKE_ABILITY_OVERRIDE_OFF": 0,
    "TRPOKE_ABILITY_OVERRIDE_FIRST": 0,
    "TRPOKE_ABILITY_OVERRIDE_SECOND": 1,
}


def _hgss_decode_ai_flags(bitmask):
    names = [name for bit, name in HGSS_AI_FLAG_BITS.items() if bitmask & (1 << bit)]
    return names if names else ["AI_FLAG_BASIC"]


def _hgss_strip_trname(name):
    """HGSS trainer names carry a literal '{TRNAME}' placeholder prefix
    (a template token the real game substitutes with class-appropriate
    flavor at render time) - stripped here since it isn't part of the
    actual display name. Falls back to '-' if nothing is left (matches
    the placeholder "{TRNAME} -" entry seen with an empty party, which
    gets filtered out separately anyway)."""
    return name.replace("{TRNAME}", "").strip() or "-"


def _hgss_normalize_word(w):
    """Strips punctuation and case for comparing a class-derived word
    against a name-derived word - e.g. so "Lt." (from the trainer's own
    name "Lt. Surge") correctly matches "LT" (from the class constant
    TRAINERCLASS_LEADER_LT_SURGE, which has no way to spell the
    period)."""
    return re.sub(r"[^A-Z0-9]", "", w.upper())


def _hgss_class_prefix(cls, trainer_name):
    """Converts an HGSS trainer class constant into the human-readable
    prefix real Pokemon games show before a trainer's name - e.g.
    'TRAINERCLASS_ELITE_FOUR_WILL' + 'Will' -> 'Elite Four' (the caller
    appends the name itself, giving 'Elite Four Will').

    Several classes embed the specific character's own name directly in
    the constant (gym leaders, Elite Four, Team Rocket executives) -
    that embedded name is stripped from the prefix here since the
    trainer's actual name gets appended separately, avoiding a
    duplicated "Elite Four Will Will". A trailing single-letter gender
    marker (Ace Trainer M/F, Swimmer M/F, Team Rocket F, School Kid M,
    Psychic M, Pokefan M...) or the "_GS" remake-internal marker (Bird
    Keeper Gs, Scientist Gs) is dropped outright, since neither is shown
    as part of the class name in the real games.

    The PKMN_TRAINER_* class family is collapsed to a plain "Pokemon
    Trainer" prefix regardless of its own suffix, rather than trying to
    strip a matching embedded name: several of those class constants
    don't actually correspond to the character they're used for in the
    real data (e.g. TRAINERCLASS_PKMN_TRAINER_BUCK is the class used for
    a trainer actually named Marley) - stripping only on an exact match
    would silently leave a wrong name in the prefix for those."""
    label = cls.replace("TRAINERCLASS_", "")
    if label.startswith("PKMN_TRAINER"):
        return "Pokemon Trainer"
    words = label.split("_")
    while words and words[-1] in ("M", "F", "GS") and len(words) > 1:
        words = words[:-1]
    name_words = trainer_name.split()
    while words and name_words and _hgss_normalize_word(words[-1]) == _hgss_normalize_word(name_words[-1]):
        words = words[:-1]
        name_words = name_words[:-1]
    return " ".join(w.title() for w in words)


def _hgss_trainer_strength_key(trainer):
    """Grouping key for detecting counter-pick variants of the SAME
    rematch tier - highest party level, then party size, then total
    levels. Encounters that match on all three are the same tier (e.g.
    Silver's starter-dependent rematches, which share an identical level
    list except for the starter species), not separate tiers."""
    party = trainer["party"]
    return (max(p["level"] for p in party), len(party), sum(p["level"] for p in party))


def _hgss_tier_order_key(index, trainer):
    """Ordering key for sorting DIFFERENT tiers into chronological
    sequence. Max level first - a later rematch is essentially always at
    least as strong as an earlier one. When two distinct groups tie on
    max level, party size turns out NOT to be a reliable tiebreaker
    (confirmed against the real data: a smaller, high-level "elite"
    rematch can chronologically follow a larger max-level-tied one) -
    array index is a much better proxy, since the source data is laid
    out in story order within each character's own set of encounters."""
    return (max(p["level"] for p in trainer["party"]), index)


def load_hgss_trainers_from_repo():
    """Returns (trainers_db, display_names) in exactly the same shape
    load_trainers_from_repo() produces for Platinum, so both can be
    merged or selected between at the __main__ prompt. See the module
    comment above for the format differences this bridges."""
    trainers_db = {}
    display_names = {}
    if not os.path.exists(HGSS_TRAINER_DATA_FILE):
        print(f"WARNING: HGSS trainer file not found at {HGSS_TRAINER_DATA_FILE}.")
        return trainers_db, display_names

    try:
        with open(HGSS_TRAINER_DATA_FILE, "r", encoding="utf-8") as f:
            raw_trainers = json.load(f)["trainers"]
    except Exception as e:
        print(f"WARNING: couldn't parse HGSS trainer file: {e}")
        return trainers_db, display_names

    # First pass: group story-important trainers by (class, name) so
    # their relative levels can be turned into rematch tier numbers.
    story_groups = defaultdict(list)
    for i, t in enumerate(raw_trainers):
        if t.get("party") and _hgss_is_story_class(t["class"]):
            story_groups[(t["class"], t["name"])].append(i)

    tier_of_index = {}
    for (cls, name), indices in story_groups.items():
        sorted_indices = sorted(indices, key=lambda i: _hgss_tier_order_key(i, raw_trainers[i]))
        tier_num = -1
        prev_key = None
        for i in sorted_indices:
            k = _hgss_trainer_strength_key(raw_trainers[i])
            if k != prev_key:
                tier_num += 1
                prev_key = k
            tier_of_index[i] = tier_num
    # How many distinct tiers each story character ends up with, needed
    # to match Platinum's own "Rematch" vs "Rematch N" display-naming
    # convention (a lone rematch gets no number, multiple get numbered).
    tier_counts = defaultdict(int)
    for (cls, name), indices in story_groups.items():
        tier_counts[(cls, name)] = len({tier_of_index[i] for i in indices})

    # Generic trainers sharing a class + name are phone-call rematches of one NPC (Ace Trainer Reena's four parties).
    # Rank them lowest to highest party level (array index breaks ties): the weakest keeps the plain name, the next
    # ones become "Rematch" / "Rematch N" like story characters, so every one gets a distinct display name and its
    # own battle-log files. Each trainer gets its own rank even on an exact strength tie, since a shared name would
    # make their logs overwrite each other. Keys are untouched (they already carry the array index).
    generic_groups = defaultdict(list)
    for i, t in enumerate(raw_trainers):
        if (t.get("party") and not _hgss_is_story_class(t["class"])
                and _hgss_strip_trname(t["name"]).strip().lower() != "mickey"):
            generic_groups[(t["class"], t["name"])].append(i)
    generic_rank = {}
    generic_group_size = {}
    for indices in generic_groups.values():
        for rank, i in enumerate(sorted(indices, key=lambda j: _hgss_tier_order_key(j, raw_trainers[j]))):
            generic_rank[i] = rank
            generic_group_size[i] = len(indices)

    skipped = []
    used_keys = set()
    for i, t in enumerate(raw_trainers):
        if not t.get("party"):
            continue

        # "Mickey" is a placeholder name reused across many otherwise-
        # unrelated generic trainer classes (Beauty, Swimmer, Camper,
        # Team Rocket, Super Nerd, Sage, etc.) - confirmed to be unused
        # template entries rather than real battle-able NPCs, so they're
        # skipped entirely rather than loaded as legitimate trainers.
        if _hgss_strip_trname(t["name"]).strip().lower() == "mickey":
            continue

        cls = t["class"]
        display_base_name = _hgss_strip_trname(t["name"])
        class_prefix = _hgss_class_prefix(cls, display_base_name)
        full_display_name = f"{class_prefix} {display_base_name}".strip() if class_prefix else display_base_name
        cls_slug = re.sub(r"[^a-z0-9]+", "_", cls.replace("TRAINERCLASS_", "").lower()).strip("_")
        name_slug = re.sub(r"[^a-z0-9]+", "_", display_base_name.lower()).strip("_") or "unnamed"

        if _hgss_is_story_class(cls):
            tier = tier_of_index.get(i, 0)
            n_tiers = tier_counts.get((cls, t["name"]), 1)
            # Reuses Platinum's own "_rematch"/"_rematch_N" key suffix
            # convention exactly (rather than a HGSS-specific "_tierN")
            # so parse_trainer_filename/is_postgame_trainer and anything
            # else that inspects trainer keys for rematch patterns works
            # identically across both games without needing to know
            # HGSS's data format differs at all.
            key = f"{cls_slug}_{name_slug}" if tier == 0 else f"{cls_slug}_{name_slug}_rematch_{tier}"
            if tier == 0:
                display = full_display_name
            elif n_tiers == 2:
                display = f"{full_display_name} Rematch"
            else:
                display = f"{full_display_name} Rematch {tier}"
        else:
            # Generic trainers: the array index guarantees uniqueness
            # even when class+name coincidentally repeats across
            # unrelated NPCs (see the module comment above).
            key = f"{cls_slug}_{name_slug}_{i:04d}"
            rank = generic_rank.get(i, 0)
            if rank == 0:
                display = full_display_name
            elif generic_group_size[i] == 2:
                display = f"{full_display_name} Rematch"
            else:
                display = f"{full_display_name} Rematch {rank}"

        if key in used_keys:
            key = f"{key}_{i:04d}"  # defensive: guard a slug collision between different groups
        used_keys.add(key)

        try:
            party_raw = []
            for p in t["party"]:
                mon = {
                    "species": p["species"],
                    "level": p["level"],
                    # Absent "moves" key -> None, exactly matching how
                    # Platinum's own explicit "moves": null is already
                    # handled by _build_party_mon (level-up-learnset-
                    # derived).
                    "moves": p.get("moves"),
                    # "difficulty" is HGSS's name for the IV scale (0-255); gender / ability come from the personality
                    "iv_scale": p.get("difficulty", 0),
                    "genderOverride": p.get("genderOverride", "TRPOKE_GENDER_OVERRIDE_OFF"),
                    "abilityOverride": p.get("abilityOverride", "TRPOKE_ABILITY_OVERRIDE_OFF"),
                }
                if p.get("item"):
                    mon["item"] = p["item"]
                party_raw.append(mon)
            if not personalise_hgss_party(party_raw, i, cls):
                for mon in party_raw:      # no decomp tables: the plain ability-slot override is all there is
                    mon["abilityNum"] = HGSS_ABILITY_OVERRIDE_TO_SLOT.get(mon["abilityOverride"], 0)
            party = [_build_party_mon(mon) for mon in party_raw]
            if not party:
                raise ValueError("empty party (no valid Pokemon parsed)")
            trainers_db[key] = {
                "class": cls,
                "base_name": display_base_name,
                "ai_flags": _hgss_decode_ai_flags(t.get("ai_flags", 0)),
                "items": [i for i in (t.get("items") or []) if i and i != "ITEM_NONE"],
                "party": party,
                "double_battle": t.get("double", 0) == 2,
            }
            display_names[key] = display
        except Exception as e:
            skipped.append((key, display, str(e)))

    if skipped:
        print(f"WARNING: skipped {len(skipped)} HGSS trainer(s) that couldn't be loaded into the tournament:")
        for key, display, reason in skipped:
            print(f"  - {display} ({key}): {reason}")

    return trainers_db, display_names


def load_combined_roster():
    """Platinum + HGSS as one roster. The HGSS keys get an "hgss_" prefix so they can never collide with a Platinum key. Six display
    names belong to one Platinum AND one HGSS trainer ("Ace Trainer Allen", "Hiker Daniel", ...); those two get a " (Platinum)" /
    " (HGSS)" tag. Everything that identifies a trainer by name - the battle-log file names, matches.csv, replaying a match from its
    seed - needs a name to pick out exactly one trainer; before this a Combined run let those pairs overwrite each other's logs."""
    plat_db, plat_names = load_trainers_from_repo()
    hgss_db, hgss_names = load_hgss_trainers_from_repo()
    db = dict(plat_db)
    names = dict(plat_names)
    for key, data in hgss_db.items():
        db[f"hgss_{key}"] = data
    for key, name in hgss_names.items():
        names[f"hgss_{key}"] = name
    counts = Counter(names.values())
    for key in list(names):
        if counts[names[key]] > 1:
            names[key] = f"{names[key]} ({'HGSS' if key.startswith('hgss_') else 'Platinum'})"
    return db, names


TRAINERS_DB, DISPLAY_NAMES = load_trainers_from_repo()


def safe_filename(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def has_flag(ai_flags, keyword):
    """Substring/normalized match so minor naming differences in the
    source repo's AI_FLAG_ constants still map correctly."""
    kw = keyword.replace("_", "").upper()
    for f in ai_flags:
        if kw in f.replace("_", "").upper():
            return True
    return False


# ============================================================
# DAMAGE CALCULATION
# ============================================================
def roll_multihit_count(rng):
    """The Gen1-4 multi-hit distribution (changed in Gen5+ to weight 2/3
    hits much more heavily - this sim targets Gen4): 2 or 3 hits are each
    3/8 likely, 4 or 5 hits are each 1/8 likely."""
    roll = rng.random()
    if roll < 3 / 8:
        return 2
    if roll < 6 / 8:
        return 3
    if roll < 7 / 8:
        return 4
    return 5


VANISH_COUNTER_MOVES = {
    # Moves that can still hit (and deal bonus damage to) a target that's
    # semi-invulnerable during the charge turn of Fly/Dig/Dive/Bounce.
    "FLY": {"MOVE_GUST", "MOVE_TWISTER", "MOVE_THUNDER"},
    "BOUNCE": {"MOVE_GUST", "MOVE_TWISTER"},
    "DIG": {"MOVE_EARTHQUAKE", "MOVE_MAGNITUDE", "MOVE_FISSURE"},
    "DIVE": {"MOVE_SURF", "MOVE_WHIRLPOOL"},
}


def compute_confusion_damage(combatant, rng, bstate=None):
    """Confusion self-hit damage, literal (battle_controller_player.c, the confusion stage of CheckStatusDisruption):
    CALC_SELF_HIT(MOVE_STRUGGLE, 40) = BattleSystem_CalcMoveDamage(Struggle, sideConditions 0, fieldConditions 0, power 40,
    inType 0, attacker = defender = the mon, crit 1), then BattleSystem_CalcDamageVariance (85-100%, one draw). Nothing else
    runs: no crit, no STAB, no type chart (a Ghost hurts itself), no Life Orb / Expert Belt.
    The mon is its own defender, so the real function's terms all land on it:
      * its Attack stage against its Defense stage (Simple doubles both, Unaware ignores both); burn halves unless Guts
      * Attack: Huge / Pure Power x2, Hustle and Guts (any status) x1.5, Slow Start /2, Choice Band, Thick Club (Cubone / Marowak)
      * Defense: Marvel Scale (any status) x1.5, Ditto's Metal Powder x2
      * power 40 (Struggle is Normal and Physical): Silk Scarf / Muscle Band, Light Ball (x2 for Pikachu), Rivalry (same gender
        as itself: x1.25), Helping Hand x1.5 - but NOT Technician (the check excludes MOVE_STRUGGLE)
    The macro hands the function 0 for the side and field conditions, so Reflect / Light Screen and every weather term (Flower
    Gift, rain, sun...) do NOT apply. Not modelled from the rest of subscript_hurt_self_in_confusion: CheckHoldOnWith1HP (Focus
    Band / Focus Sash; the engine has no held-item endure and no trainer holds either) and the resist-berry hook of
    subscript_update_hp (only a Chilan Berry could fire on this Normal hit; no trainer holds one). UnlockMoveChoice is the
    caller's (confusion_check)."""
    damage = calc_move_damage(combatant, combatant, STRUGGLE_MOVE_DATA, 40, STRUGGLE_MOVE_DATA["type"], None, bstate, 1, screens=False)
    if damage:
        damage = max(1, damage * (100 - int(rng.random() * 16)) // 100)
    return damage


# ============================================================
# DAMAGE: a literal integer port of BattleSystem_CalcMoveDamage / CalcCriticalMulti / CalcDamageVariance / ApplyTypeChart
# (battle_lib.c). The real order is: base damage (all integer, ends "+ 2") -> x crit -> Life Orb -> x variance (85..100) ->
# STAB -> the type chart row by row -> Filter/Solid Rock -> Expert Belt / Tinted Lens. The AI's own estimate
# (TrainerAI_CalcDamage) is the same chain with crit x1 and variance 100.
# ============================================================
_STAT_STAGE_FRACTIONS = [(10, 40), (10, 35), (10, 30), (10, 25), (10, 20), (10, 15), (10, 10),
                         (15, 10), (20, 10), (25, 10), (30, 10), (35, 10), (40, 10)]     # sStatStageBoosts, indexed stage + 6
_TYPE_BOOST_ITEM_EFFECTS = {f"HOLD_EFFECT_STRENGTHEN_{n}": f"TYPE_{n}" for n in (
    "BUG", "STEEL", "GROUND", "ROCK", "GRASS", "DARK", "ELECTRIC", "WATER", "FLYING", "POISON", "ICE", "GHOST", "PSYCHIC",
    "FIRE", "DRAGON", "NORMAL")}
_TYPE_BOOST_ITEM_EFFECTS["HOLD_EFFECT_STRENGTHEN_FIGHT"] = "TYPE_FIGHTING"
_TYPE_BOOST_ITEM_EFFECTS.update({f"HOLD_EFFECT_ARCEUS_{n}": f"TYPE_{n}" for n in (
    "FIRE", "WATER", "ELECTRIC", "GRASS", "ICE", "FIGHTING", "POISON", "GROUND", "FLYING", "PSYCHIC", "BUG", "ROCK", "GHOST")})
_PUNCHING_MOVES = frozenset(("MOVE_ICE_PUNCH", "MOVE_FIRE_PUNCH", "MOVE_THUNDER_PUNCH", "MOVE_MACH_PUNCH", "MOVE_FOCUS_PUNCH",
                             "MOVE_DIZZY_PUNCH", "MOVE_DYNAMIC_PUNCH", "MOVE_HAMMER_ARM", "MOVE_MEGA_PUNCH", "MOVE_COMET_PUNCH",
                             "MOVE_METEOR_MASH", "MOVE_SHADOW_PUNCH", "MOVE_DRAIN_PUNCH", "MOVE_BULLET_PUNCH", "MOVE_SKY_UPPERCUT"))
_CRIT_STAGE_RATES = (16, 8, 4, 3, 2)


def _bs_divide(dividend, divisor):
    """BattleSystem_Divide: C truncating division that never rounds a non-zero result down to 0."""
    if dividend == 0:
        return 0
    q = int(dividend / divisor)
    return q if q != 0 else (-1 if dividend < 0 else 1)


def _staged_stat(stat, stage, ignore_stage=False):
    """stat * sStatStageBoosts[stage] (integer): `stage` is -6..+6; a critical hit ignores the side that hurts it."""
    if ignore_stage:
        return stat
    num, den = _STAT_STAGE_FRACTIONS[max(-6, min(6, stage)) + 6]
    return stat * num // den


def _held_effect(mon):
    """Battler_HeldItemEffect / Battler_HeldItemPower: (effect, param); nothing under Klutz or Embargo."""
    return _acc_held_item(mon)


def crit_stage_multiplier(attacker, defender, move, rng, bstate=None):
    """BattleSystem_CalcCriticalMulti: 1, 2 (or 3 with Sniper). Draws once from rng."""
    effect, _ = _held_effect(attacker)
    species = attacker.get("species")
    stage = ((2 if attacker.get("focus_energy") else 0) + (1 if move.get("high_crit") else 0)
             + (1 if effect == "HOLD_EFFECT_CRITRATE_UP" else 0) + (1 if has_ability(attacker, "SUPER_LUCK") else 0)
             + (2 if effect == "HOLD_EFFECT_CHANSEY_CRITRATE_UP" and species == "SPECIES_CHANSEY" else 0)
             + (2 if effect == "HOLD_EFFECT_FARFETCHD_CRITRATE_UP" and species == "SPECIES_FARFETCHD" else 0))
    rate = _CRIT_STAGE_RATES[min(4, stage)]
    breaker = has_ability(attacker, "MOLD_BREAKER")
    lucky = bool(bstate) and bstate["sides"][bstate["side_of"](defender)].get("lucky_chant", 0) > 0
    armor = (has_ability(defender, "BATTLE_ARMOR") or has_ability(defender, "SHELL_ARMOR")) and not breaker
    if int(rng.random() * rate) == 0 and not armor and not lucky:
        return 3 if has_ability(attacker, "SNIPER") else 2
    return 1


# the effect scripts of the five recoil effects and crash-on-miss set BTLVAR_POWER_MULTI to 12 for a Reckless user
_RECKLESS_EFFECTS = frozenset(("BATTLE_EFFECT_RECOIL_QUARTER", "BATTLE_EFFECT_RECOIL_THIRD", "BATTLE_EFFECT_RECOIL_HALF",
                               "BATTLE_EFFECT_RECOIL_BURN_HIT", "BATTLE_EFFECT_RECOIL_PARALYZE_HIT", "BATTLE_EFFECT_CRASH_ON_MISS"))


def calc_move_damage(attacker, defender, move, power, move_type, weather, bstate, crit_mul=1, spread=False, screens=True, power_mul=True,
                      log=None):
    """BattleSystem_CalcMoveDamage: the integer base damage (including the trailing + 2), BEFORE crit, variance, STAB and the
    type chart. `power` is the move's (already adjusted) base power; `bstate` may be None. `weather` is the caller's
    fieldConditions (None = 0) and `screens=False` its sideConditions = 0: Reflect / Light Screen are then skipped even when
    bstate has them up (the real function is handed the side conditions, the sim reads them from bstate). `power_mul=False` is the AI's
    estimate: battleCtx->powerMul (which the effect scripts set, e.g. Reckless's 12) is still 10 when the AI evaluates a move.
    `log`, if given, marks this as a REAL hit (not AI-estimate/speculative scoring): when the screen actually reduces the damage,
    note_screen_reduced_hit records it for the Support role's "screen" assist (see the ASSIST TRACKING section)."""
    b_ignore = has_ability(attacker, "MOLD_BREAKER")               # Battler_IgnorableAbility: the DEFENDER's ability, unless...
    ignorable = lambda name: has_ability(defender, name) and not b_ignore
    if has_ability(attacker, "NORMALIZE"):
        move_type = "TYPE_NORMAL"
    move_class = move.get("class", "CLASS_PHYSICAL")
    move_name = move.get("name", "")
    level = attacker.get("level", 50)
    hp, max_hp = attacker["hp"], attacker.get("max_hp", attacker["hp"])
    a_status = attacker.get("status", "NONE") != "NONE"
    d_status = defender.get("status", "NONE") != "NONE"
    atk, dfn = attacker.get("atk", 70), defender.get("def", 70)
    spa, spd = attacker.get("spa", 70), defender.get("spd", 70)
    a_effect, a_param = _held_effect(attacker)
    d_effect, d_param = _held_effect(defender)
    a_species, d_species = attacker.get("species"), defender.get("species")

    power = int(power)
    if power_mul and has_ability(attacker, "RECKLESS") and _real_effect(move_name) in _RECKLESS_EFFECTS:
        power = power * 12 // 10                                  # movePower * powerMul / 10, before anything else touches the power
    if attacker.get("helping_hand"):
        power = power * 15 // 10
    if has_ability(attacker, "TECHNICIAN") and move_name != "MOVE_STRUGGLE" and power <= 60:
        power = power * 15 // 10
    if has_ability(attacker, "HUGE_POWER") or has_ability(attacker, "PURE_POWER"):
        atk *= 2
    if has_ability(attacker, "SLOW_START") and (bstate or {}).get("turn", 1) - 1 - attacker.get("entered_turn", 1) < 5:
        atk //= 2
    if _TYPE_BOOST_ITEM_EFFECTS.get(a_effect) == move_type:
        power = power * (100 + a_param) // 100
    if a_effect == "HOLD_EFFECT_CHOICE_ATK":
        atk = atk * 150 // 100
    if a_effect == "HOLD_EFFECT_CHOICE_SPATK":
        spa = spa * 150 // 100
    if a_effect == "HOLD_EFFECT_LATI_SPECIAL" and a_species in ("SPECIES_LATIOS", "SPECIES_LATIAS"):
        spa = spa * 150 // 100
    if d_effect == "HOLD_EFFECT_LATI_SPECIAL" and d_species in ("SPECIES_LATIOS", "SPECIES_LATIAS"):
        spd = spd * 150 // 100
    if a_effect == "HOLD_EFFECT_CLAMPERL_SPATK" and a_species == "SPECIES_CLAMPERL":
        spa *= 2
    if d_effect == "HOLD_EFFECT_CLAMPERL_SPDEF" and d_species == "SPECIES_CLAMPERL":
        spd *= 2
    if a_effect == "HOLD_EFFECT_PIKA_SPATK_UP" and a_species == "SPECIES_PIKACHU":
        power *= 2
    if d_effect == "HOLD_EFFECT_DITTO_DEF_UP" and d_species == "SPECIES_DITTO":
        dfn *= 2
    if a_effect == "HOLD_EFFECT_CUBONE_ATK_UP" and a_species in ("SPECIES_CUBONE", "SPECIES_MAROWAK"):
        atk *= 2
    if ((a_effect == "HOLD_EFFECT_DIALGA_BOOST" and move_type in ("TYPE_DRAGON", "TYPE_STEEL") and a_species == "SPECIES_DIALGA")
            or (a_effect == "HOLD_EFFECT_PALKIA_BOOST" and move_type in ("TYPE_DRAGON", "TYPE_WATER") and a_species == "SPECIES_PALKIA")
            or (a_effect == "HOLD_EFFECT_GIRATINA_BOOST" and move_type in ("TYPE_DRAGON", "TYPE_GHOST") and a_species == "SPECIES_GIRATINA"
                and not attacker.get("transformed"))):
        power = power * (100 + a_param) // 100
    if a_effect == "HOLD_EFFECT_POWER_UP_PHYS" and move_class == "CLASS_PHYSICAL":
        power = power * (100 + a_param) // 100
    if a_effect == "HOLD_EFFECT_POWER_UP_SPEC" and move_class == "CLASS_SPECIAL":
        power = power * (100 + a_param) // 100
    if ignorable("THICK_FAT") and move_type in ("TYPE_FIRE", "TYPE_ICE"):
        power //= 2
    if has_ability(attacker, "HUSTLE"):
        atk = atk * 150 // 100
    if has_ability(attacker, "GUTS") and a_status:
        atk = atk * 150 // 100
    if (has_ability(attacker, "PLUS") and side_ability_count(bstate, attacker, "MINUS")) \
            or (has_ability(attacker, "MINUS") and side_ability_count(bstate, attacker, "PLUS")):
        spa = spa * 150 // 100
    if ignorable("MARVEL_SCALE") and d_status:
        dfn = dfn * 150 // 100
    if move_type == "TYPE_ELECTRIC" and any_active_with(bstate, "mud_sport"):
        power //= 2
    if move_type == "TYPE_FIRE" and any_active_with(bstate, "water_sport"):
        power //= 2
    if hp <= max_hp // 3 and ((move_type == "TYPE_GRASS" and has_ability(attacker, "OVERGROW"))
                              or (move_type == "TYPE_FIRE" and has_ability(attacker, "BLAZE"))
                              or (move_type == "TYPE_WATER" and has_ability(attacker, "TORRENT"))
                              or (move_type == "TYPE_BUG" and has_ability(attacker, "SWARM"))):
        power = power * 150 // 100
    if move_type == "TYPE_FIRE" and ignorable("HEATPROOF"):
        power //= 2
    if move_type == "TYPE_FIRE" and ignorable("DRY_SKIN"):
        power = power * 125 // 100

    atk_stage, spa_stage = attacker.get("atk_stage", 0), attacker.get("spa_stage", 0)
    def_stage, spd_stage = defender.get("def_stage", 0), defender.get("spd_stage", 0)
    if has_ability(attacker, "SIMPLE"):
        atk_stage, spa_stage = max(-6, min(6, atk_stage * 2)), max(-6, min(6, spa_stage * 2))
    if ignorable("SIMPLE"):
        def_stage, spd_stage = max(-6, min(6, def_stage * 2)), max(-6, min(6, spd_stage * 2))
    if ignorable("UNAWARE"):
        atk_stage = spa_stage = 0
    if has_ability(attacker, "UNAWARE"):
        def_stage = spd_stage = 0

    a_gender, d_gender = attacker.get("gender", "GENDERLESS"), defender.get("gender", "GENDERLESS")
    if has_ability(attacker, "RIVALRY") and "GENDERLESS" not in (a_gender, d_gender):
        power = power * 125 // 100 if a_gender == d_gender else power * 75 // 100
    if has_ability(attacker, "IRON_FIST") and move_name in _PUNCHING_MOVES:
        power = power * 12 // 10
    if weather == "SUN" and has_ability(attacker, "SOLAR_POWER"):
        spa = spa * 15 // 10
    if weather == "SANDSTORM" and "TYPE_ROCK" in _ai_types(defender):
        spd = spd * 15 // 10
    if weather == "SUN" and side_ability_count(bstate, attacker, "FLOWER_GIFT"):
        atk = atk * 15 // 10
    if weather == "SUN" and not b_ignore and side_ability_count(bstate, defender, "FLOWER_GIFT"):
        spd = spd * 15 // 10
    if move.get("halve_defense") or _real_effect(move_name) == "BATTLE_EFFECT_HALVE_DEFENSE":
        dfn //= 2

    crit = crit_mul > 1
    if move_class == "CLASS_PHYSICAL":
        damage = _staged_stat(atk, atk_stage, ignore_stage=crit and atk_stage <= 0)
        damage *= power
        damage *= (level * 2 // 5 + 2)
        divisor = _staged_stat(dfn, def_stage, ignore_stage=crit and def_stage >= 0)
        damage //= max(1, divisor)
        damage //= 50
        if attacker.get("status") == "BURN" and not has_ability(attacker, "GUTS"):
            damage //= 2
        screen_key = "reflect"
    else:
        damage = _staged_stat(spa, spa_stage, ignore_stage=crit and spa_stage <= 0)
        damage *= power
        damage *= (level * 2 // 5 + 2)
        divisor = _staged_stat(spd, spd_stage, ignore_stage=crit and spd_stage >= 0)
        damage //= max(1, divisor)
        damage //= 50
        screen_key = "light_screen"
    if screens and bstate and not crit and _real_effect(move_name) != "BATTLE_EFFECT_REMOVE_SCREENS":
        if bstate["sides"][bstate["side_of"](defender)].get(screen_key, 0) > 0:
            both_up = bstate.get("is_double_battle") and (side_ability_count(bstate, defender, None) >= 2)
            damage = damage * 2 // 3 if both_up else damage // 2      # 2/3 only while BOTH defenders are alive
            if log is not None:
                note_screen_reduced_hit(bstate, defender, attacker, screen_key)
    if spread:
        damage = damage * 3 // 4
    if weather == "RAIN":
        if move_type == "TYPE_FIRE":
            damage //= 2
        elif move_type == "TYPE_WATER":
            damage = damage * 15 // 10
    if move_name == "MOVE_SOLAR_BEAM" and weather in ("RAIN", "SANDSTORM", "HAIL"):
        damage //= 2
    if weather == "SUN":
        if move_type == "TYPE_FIRE":
            damage = damage * 15 // 10
        elif move_type == "TYPE_WATER":
            damage //= 2
    if attacker.get("activated_flash_fire") and move_type == "TYPE_FIRE":
        damage = damage * 15 // 10
    return damage + 2


def apply_type_chart_damage(attacker, defender, move, move_type, damage, bstate=None, ignore_type_checks=False):
    """BattleSystem_ApplyTypeChart's damage output: STAB, then each matching chart row in table order (integer, never rounding
    a hit to 0), then Filter / Solid Rock (3/4), Expert Belt and Tinted Lens. A fully immune matchup returns 0."""
    move_name = move.get("name", "")
    if move_name == "MOVE_STRUGGLE":
        return damage
    if has_ability(attacker, "NORMALIZE"):
        move_type = "TYPE_NORMAL"
    power = move.get("power", 0)
    breaker = has_ability(attacker, "MOLD_BREAKER")
    if not ignore_type_checks and move_type in attacker.get("types", ()):
        damage = damage * 2 if has_ability(attacker, "ADAPTABILITY") else damage * 15 // 10
    gravity = bool(bstate) and bstate.get("gravity", 0) > 0
    d_effect, _ = _held_effect(defender)
    iron_ball = d_effect == "HOLD_EFFECT_SPEED_DOWN_GROUNDED"
    type1, type2 = _ai_types(defender)
    skip_ghost = bool(defender.get("foresight")) or has_ability(attacker, "SCRAPPY")
    flags = 0
    if has_ability(defender, "LEVITATE") and not breaker and move_type == "TYPE_GROUND" and not iron_ball and not gravity:
        return damage                          # Levitate: the move is stopped elsewhere (the chart is skipped)
    if not ignore_type_checks:
        for row_type, vs_type, mul in _AI_TYPE_CHART:
            if row_type == "MARKER":
                if skip_ghost:
                    break
                continue
            if row_type != move_type or vs_type not in (type1, type2):
                continue
            if vs_type == "TYPE_FLYING" and mul == 0 and (iron_ball or defender.get("ingrain") or gravity):
                continue
            if vs_type == "TYPE_DARK" and mul == 0 and defender.get("miracle_eye"):
                continue
            hits = (1 if vs_type == type1 else 0) + (1 if (vs_type == type2 and type1 != type2) else 0)
            for _ in range(hits):
                if damage:
                    damage = _bs_divide(damage * mul, 10)
        flags = _ai_chart_flags(move_type, type1, type2, skip_ghost, iron_ball, gravity, ingrain=bool(defender.get("ingrain")),
                                miracle_eye=bool(defender.get("miracle_eye")), update=power != 0)
        a_effect, a_param = _held_effect(attacker)
        if flags & _MS_SUPER_EFFECTIVE and power:
            if (has_ability(defender, "FILTER") or has_ability(defender, "SOLID_ROCK")) and not breaker:
                damage = _bs_divide(damage * 3, 4)
            if a_effect == "HOLD_EFFECT_POWER_UP_SE":
                damage = damage * (100 + a_param) // 100
        if flags & _MS_NOT_VERY_EFFECTIVE and power and has_ability(attacker, "TINTED_LENS"):
            damage *= 2
    return damage


def _locked_onto(attacker, defender):
    """MON_IS_LOCKED_ONTO: Lock-On / Mind Reader stored on the TARGET (`locked_on_by` = id of the mon that locked on) for
    two turn-ends; the locker's moves then never miss it (and reach it through Fly / Dig)."""
    return defender.get("lock_on_turns", 0) > 0 and defender.get("locked_on_by") == id(attacker)


def _ohko_outcome(attacker, defender, move, rng):
    """BtlCmd_TryOHKOMove (Fissure, Horn Drill, Guillotine, Sheer Cold): Sturdy blocks it; it always fails against a
    higher-level target (even with No Guard / Lock-On); otherwise it hits with probability accuracy + (attacker level -
    defender level) percent (always, under No Guard / Lock-On) and deals the target's current HP.
    Returns compute_damage's (damage, is_crit, effectiveness, missed)."""
    if has_ability(defender, "STURDY") and not has_ability(attacker, "MOLD_BREAKER"):
        return 0, False, 0.0, False
    a_level, d_level = attacker.get("level", 50), defender.get("level", 50)
    if a_level < d_level:
        return 0, False, 1.0, True
    sure = _locked_onto(attacker, defender) or has_ability(attacker, "NO_GUARD") or has_ability(defender, "NO_GUARD")
    if not sure and not int(rng.random() * 100) < (move.get("accuracy", 30) or 30) + a_level - d_level:
        return 0, False, 1.0, True
    return max(1, defender["hp"]), False, 1.0, False


# include/data/hit_rate_stages.h, indexed by 6 + evasion-side stages + accuracy-side stages (0..12)
_HIT_RATE_BY_STAGE = [(33, 100), (36, 100), (43, 100), (50, 100), (60, 100), (75, 100), (1, 1),
                      (133, 100), (166, 100), (2, 1), (233, 100), (133, 50), (3, 1)]


def _acc_held_item(mon):
    """Battler_HeldItemEffect / Battler_HeldItemPower: (hold_effect, param), nothing under Klutz or Embargo."""
    item = mon.get("item")
    if not item or not item_effects_active(mon) or has_ability(mon, "KLUTZ"):
        return "HOLD_EFFECT_NONE", 0
    info = get_item_info(item)
    return info.get("hold_effect", "HOLD_EFFECT_NONE"), info.get("effect_param", 0) or 0


def _accuracy_check_misses(attacker, defender, move, weather, rng, force_hit=False, bstate=None):
    """BattleControllerPlayer_CheckMoveHitAccuracy (+ the No Guard override): True if the move misses. Struggle-style
    always_hit moves and raw-accuracy-0 moves never roll; Thunder in Rain / Blizzard in Hail bypass accuracy; Thunder in Sun is
    50. Otherwise the real integer formula: the move's accuracy x HitRateByStage[6 + evasion stages + accuracy stages], then
    Compound Eyes, Sand Veil / Snow Cloak, Hustle, Tangled Feet, Bright Powder / Lax Incense, Wide Lens, Zoom Lens, Gravity,
    and a 1..100 roll that misses when it exceeds the result. Consumes exactly one rng draw when it can miss."""
    move_name = move.get("name", "")
    weather_bypass = move.get("weather_accuracy") and (
        (move_name == "MOVE_THUNDER" and weather == "RAIN") or (move_name == "MOVE_BLIZZARD" and weather == "HAIL")
    )
    if (move.get("always_hit") or move.get("no_accuracy_check") or force_hit or weather_bypass
            or has_ability(attacker, "NO_GUARD") or has_ability(defender, "NO_GUARD") or _locked_onto(attacker, defender)):
        return False
    breaker = has_ability(attacker, "MOLD_BREAKER")          # Battler_IgnorableAbility on the defender's abilities
    acc_stages = attacker.get("acc_stage", 0)
    eva_stages = -defender.get("eva_stage", 0)
    if has_ability(attacker, "SIMPLE"):
        acc_stages *= 2
    if has_ability(defender, "SIMPLE") and not breaker:
        eva_stages *= 2
    if has_ability(defender, "UNAWARE") and not breaker:
        acc_stages = 0
    if has_ability(attacker, "UNAWARE"):
        eva_stages = 0
    if (defender.get("foresight") or defender.get("miracle_eye")) and eva_stages < 0:      # MON_IS_IDENTIFIED
        eva_stages = 0
    num, den = _HIT_RATE_BY_STAGE[max(0, min(12, 6 + eva_stages + acc_stages))]

    hit_rate = move.get("accuracy", 100) or 100
    if move.get("weather_accuracy") and move_name == "MOVE_THUNDER" and weather == "SUN":
        hit_rate = 50
    hit_rate = hit_rate * num // den
    if has_ability(attacker, "COMPOUND_EYES"):
        hit_rate = hit_rate * 130 // 100
    if not breaker:
        if weather == "SANDSTORM" and has_ability(defender, "SAND_VEIL"):
            hit_rate = hit_rate * 80 // 100
        if weather == "HAIL" and has_ability(defender, "SNOW_CLOAK"):
            hit_rate = hit_rate * 80 // 100
    if has_ability(attacker, "HUSTLE") and move.get("class") == "CLASS_PHYSICAL":
        hit_rate = hit_rate * 80 // 100
    if defender.get("confused") and has_ability(defender, "TANGLED_FEET") and not breaker:
        hit_rate = hit_rate * 50 // 100
    effect, power = _acc_held_item(defender)
    if effect == "HOLD_EFFECT_ACC_REDUCE":
        hit_rate = hit_rate * (100 - power) // 100
    effect, power = _acc_held_item(attacker)
    if effect == "HOLD_EFFECT_ACCURACY_UP":
        hit_rate = hit_rate * (100 + power) // 100
    if effect == "HOLD_EFFECT_ACCURACY_UP_SLOWER" and bstate is not None and defender.get("_acted_turn") == bstate.get("turn"):
        hit_rate = hit_rate * (100 + power) // 100
    if bstate is not None and bstate.get("gravity", 0) > 0:
        hit_rate = hit_rate * 10 // 6
    if hit_rate >= 100:
        return False
    return int(rng.random() * 100) + 1 > hit_rate


def compute_damage(attacker, defender, move, weather, rng, is_crit=None, roll=None, force_hit=False, bstate=None, log=None,
                   spread=False, ai_estimate=False):
    """Returns (damage:int, is_crit:bool, effectiveness:float, missed:bool). `ai_estimate=True` is the trainer AI's own damage estimate
    (see calc_move_damage's power_mul).
    If is_crit/roll are given, uses them (deterministic; used by the AI
    for "expected"/"max" damage estimates); otherwise rolls randomly.
    force_hit=True skips the accuracy roll entirely - used for hits 2+ of
    a multi-hit move, since Gen4 only checks accuracy once per use; once
    the first hit connects, every subsequent hit in that same use always
    connects too.
    bstate, if given, is used for two field-state checks: Gravity (lets
    Ground-type moves bypass Flying's immunity/Levitate) and Lucky Chant
    (blocks critical hits against whichever side has it active)."""
    power = move.get("power", 0)
    m_type = move.get("type", "TYPE_NORMAL")
    if has_ability(attacker, "NORMALIZE") and not move.get("typeless"):
        m_type = "TYPE_NORMAL"
    m_class = move.get("class", "CLASS_PHYSICAL")
    move_name = move.get("name", "")
    typeless = move.get("typeless", False)
    gravity_active = bool(bstate) and bstate.get("gravity", 0) > 0
    lucky_chant_active = bool(bstate) and bstate["sides"][bstate["side_of"](defender)].get("lucky_chant", 0) > 0

    if m_class == "CLASS_STATUS":
        # Status moves aimed at another mon roll accuracy like any other move (Hypnosis 60, Thunder Wave, Toxic 85, ...); a
        # semi-invulnerable target evades them too. Self/field/side moves have raw accuracy 0 and skip the roll.
        if defender is not attacker and move.get("range") != "RANGE_OPPONENT_SIDE" and not move.get("no_accuracy_check"):
            if defender.get("vanished") and not (has_ability(attacker, "NO_GUARD") or has_ability(defender, "NO_GUARD")
                                                 or _locked_onto(attacker, defender)):
                return 0, False, 1.0, True
            if _accuracy_check_misses(attacker, defender, move, weather, rng, force_hit, bstate):
                return 0, False, 1.0, True
        return 0, False, 1.0, False
    if power <= 0:
        return 0, False, 1.0, False

    # --- semi-invulnerable targets (charge turn of Fly/Dig/Dive/Bounce) ---
    vanish_bonus = 1.0
    if defender.get("vanished"):
        if move_name in VANISH_COUNTER_MOVES.get(defender["vanished"], set()):
            vanish_bonus = 2.0
        elif has_ability(attacker, "NO_GUARD") or has_ability(defender, "NO_GUARD") or _locked_onto(attacker, defender):
            pass  # No Guard / Lock-On lets the move connect despite the target being vanished - no bonus multiplier, it just isn't evaded
        else:
            return 0, False, 1.0, True  # fully evaded - treated as a miss

    eff = get_type_effectiveness(m_type, attacker, defender, typeless=typeless, gravity=gravity_active)
    if eff == 0.0:
        if m_type == "TYPE_WATER" and not has_ability(attacker, "MOLD_BREAKER") \
                and (has_ability(defender, "WATER_ABSORB") or has_ability(defender, "DRY_SKIN")) \
                and defender["hp"] < defender.get("max_hp", defender["hp"]) and log is not None:
            heal = max(1, defender.get("max_hp", defender["hp"]) // 4)
            defender["hp"] = min(defender.get("max_hp", defender["hp"]), defender["hp"] + heal)
            ability_name = "Water Absorb" if has_ability(defender, "WATER_ABSORB") else "Dry Skin"
            ai_reveal_ability(defender)
            log.append(f"    {defender['species_display']}'s {ability_name} restored its HP!")
        if log is not None and (is_immune_by_ability(m_type, defender, attacker)
                                or (has_ability(defender, "WONDER_GUARD") and type_effectiveness_raw(m_type, defender.get("types", [])) != 0)):
            ai_reveal_ability(defender)          # "X's Levitate makes Ground moves miss!" etc.: the ability was shown
        return 0, False, 0.0, False

    if move.get("sound") and has_ability(defender, "SOUNDPROOF"):
        if log is not None:
            ai_reveal_ability(defender)
        return 0, False, 0.0, False

    if move.get("ohko") and roll is None and is_crit is None:
        return _ohko_outcome(attacker, defender, move, rng)

    # --- accuracy ---
    if _accuracy_check_misses(attacker, defender, move, weather, rng, force_hit, bstate):
        return 0, False, eff, True

    if move.get("fixed_damage") or move.get("fixed_damage_by_level"):
        # Dragon Rage/Sonic Boom (flat 40/20) and Night Shade/Seismic Toss
        # (damage = user's level) - everything above this point already
        # applies correctly (type immunity/Wonder Guard via eff==0.0,
        # Soundproof, the accuracy roll), but from here on these moves
        # skip STAB, weather, stat stages, and crits entirely - they
        # always deal exactly this fixed amount when they connect. The
        # effectiveness multiplier is reported as neutral (1.0) rather
        # than the real type-chart value: the real games don't show a
        # "Super effective!"/"Not very effective..." message for these
        # moves since the damage was never actually scaled by it - only
        # outright immunity (already handled above) matters here.
        fixed_dmg = move["fixed_damage"] if move.get("fixed_damage") else attacker.get("level", 50)
        return max(1, int(fixed_dmg)), False, 1.0, False

    power = int(power)
    if vanish_bonus > 1.0:
        power = power * 20 // 10                # powerMul 20: Surf/Whirlpool on a diver, Earthquake/Magnitude on a digger, ...
    if is_crit is None:
        crit_mul = crit_stage_multiplier(attacker, defender, move, rng, bstate)
        is_crit = crit_mul > 1
    else:
        crit_mul = 2 if is_crit else 1
    damage = calc_move_damage(attacker, defender, move, power, m_type, weather, bstate, crit_mul, spread, power_mul=not ai_estimate,
                              log=log) * crit_mul
    a_effect, a_param = _held_effect(attacker)
    if a_effect == "HOLD_EFFECT_HP_DRAIN_ON_ATK":                                   # Life Orb
        damage = damage * (100 + a_param) // 100
    if attacker.get("me_first"):
        damage = damage * 15 // 10
    variance = (100 - int(rng.random() * 16)) if roll is None else int(round(roll * 100))
    if damage:
        damage = max(1, damage * variance // 100)
    damage = apply_type_chart_damage(attacker, defender, move, m_type, damage, bstate, ignore_type_checks=typeless)

    resist_type = TYPE_RESIST_BERRY_TYPES.get(get_item_info(defender.get("item")).get("hold_effect"))
    if resist_type and resist_type == m_type and eff > 1.0 and item_effects_active(defender):
        damage = max(1, damage // 2)
        if log is not None:
            # Only consume the berry (and log the message) for a REAL
            # hit - this function is also called with log=None for the
            # AI's own damage-prediction scoring, which must never have
            # the side effect of actually consuming the opponent's berry
            # before any real attack happens.
            held_item_name = get_item_info(defender.get("item")).get("name", "berry")
            defender["item"] = None
            log.append(f"    {defender['species_display']}'s {held_item_name} weakened the attack!")
    return max(1, damage), is_crit, eff, False


def estimate_max_damage(attacker, defender, move, weather, bstate=None):
    """Deterministic best-case damage estimate for AI scoring purposes
    (no accuracy roll, best crit-eligible roll at 1.0x random factor).
    Mirrors what the in-game AI effectively does when comparing moves.
    bstate is optional (only needed for the Gravity type-effectiveness
    check - is_crit is forced anyway here, so Lucky Chant never matters
    for this deterministic estimate)."""
    if move.get("effect") == "ENDEAVOR":
        # Not power-based at all - its real "damage" is however much HP
        # the defender has above the attacker's own current HP. Without
        # this, the AI would see 0 power and never recognize Endeavor as
        # a real threat (e.g. the classic low-HP-Endeavor + fast-finisher
        # combo some Rival battles use).
        return max(0, defender["hp"] - attacker["hp"]), 1.0
    rng = random.Random(0)
    dmg, _, eff, _ = compute_damage(attacker, defender, move, weather, rng, is_crit=False, roll=1.0, force_hit=True, bstate=bstate,
                                    ai_estimate=True)
    return dmg, eff


# ============================================================
# AI SCORING: BASIC FLAG
# ============================================================
STAT_BOOST_MOVES_SATURATION_CHECK = True


AI_SOUNDPROOF_MOVES = {
    "MOVE_GROWL", "MOVE_ROAR", "MOVE_SING", "MOVE_SUPERSONIC", "MOVE_SCREECH", "MOVE_SNORE",
    "MOVE_UPROAR", "MOVE_METAL_SOUND", "MOVE_GRASS_WHISTLE", "MOVE_BUG_BUZZ", "MOVE_CHATTER",
}
AI_ABSORPTION_ABILITY_TYPE = {
    # Basic_CheckForImmunity's ability -> matching move-type table. Dry
    # Skin is faithfully OMITTED here: the real script's own line meant
    # to check it branches on ABILITY_LEVITATE again instead (a
    # documented bug), which is unreachable dead code since Levitate
    # was already caught one branch earlier - so Dry Skin never gets
    # this special -12 treatment in the real game's Basic flag at all.
    "VOLT_ABSORB": "TYPE_ELECTRIC", "MOTOR_DRIVE": "TYPE_ELECTRIC",
    "WATER_ABSORB": "TYPE_WATER", "FLASH_FIRE": "TYPE_FIRE", "LEVITATE": "TYPE_GROUND",
}


def _ai_ability(mon):
    """LoadBattlerAbility: ABILITY_NONE while the ability is suppressed
    (Gastro Acid). NOTE the real game only knows an OPPONENT's ability once
    it has been revealed, and otherwise guesses one of the species' two
    abilities with a coin flip; this simulator (like the rest of its Basic
    port) reads the opponent's real ability directly."""
    return "NONE" if mon.get("ability_suppressed") else ability_of(mon)


AI_TRAPPING_ABILITIES = frozenset(("SHADOW_TAG", "MAGNET_PULL", "ARENA_TRAP"))     # these announce themselves on entry


def ai_reveal_ability(mon):
    """BattleAI_SetAbility: the opposing AI now knows this mon's (current) ability - set whenever an ability is displayed in a
    battle message or an ability is changed, and forgotten when the mon leaves the field (see apply_entry_hazards)."""
    mon["ai_known_ability"] = ability_of(mon)


def ai_reveal_item(mon):
    """BattleAI_SetHeldItem: an item shown in a battle message (Leftovers/Black Sludge healing, a berry eaten or cured, White Herb,
    Trick/Switcheroo) is now known to the opposing AI; it is forgotten on switch-in and once the mon holds nothing."""
    mon["ai_known_item"] = mon.get("item")


def ai_load_ability(mon, viewer, rng, viewer_partner=False):
    """AICmd_LoadBattlerAbility. The viewer's own mon and its partner are read directly. An opponent's ability is what the AI
    has SEEN; a trapping ability is always known; otherwise the AI GUESSES one of the species' two abilities with a coin flip
    (one rng draw, only when the species really has two). Gastro Acid reads as no ability. Returns the ability name ('NONE'
    for none)."""
    if mon.get("ability_suppressed"):
        return "NONE"
    if mon is viewer or viewer_partner:
        return ability_of(mon)
    known = mon.get("ai_known_ability")
    if known and known != "NONE":
        return known
    real = ability_of(mon)
    if real in AI_TRAPPING_ABILITIES:
        return real
    slots = tuple(mon.get("species_abilities") or ())
    if len(slots) >= 2:
        return slots[0] if rng.randint(0, 1) else slots[1]
    return slots[0] if slots else "NONE"


def ai_check_ability(mon, expected, viewer, viewer_partner=False):
    """AICmd_CheckBattlerAbility: 'HAVE', 'NOT_HAVE' or 'UNKNOWN' (no rng). For an opponent whose ability has not been
    seen: a species with two abilities where NEITHER is `expected` reads NOT_HAVE (as its first ability); if one of them is
    `expected` the AI cannot tell (UNKNOWN); a single-ability species is known."""
    if mon.get("ability_suppressed"):
        tmp = "NONE"
    elif mon is viewer or viewer_partner:
        tmp = ability_of(mon)
    else:
        known = mon.get("ai_known_ability")
        real = ability_of(mon)
        if known and known != "NONE":
            tmp = known
        elif real in AI_TRAPPING_ABILITIES:
            tmp = real
        else:
            slots = tuple(mon.get("species_abilities") or ())
            if len(slots) >= 2:
                tmp = slots[0] if (slots[0] != expected and slots[1] != expected) else "NONE"
            else:
                tmp = slots[0] if slots else "NONE"
    if tmp == "NONE":
        return "UNKNOWN"
    return "HAVE" if tmp == expected else "NOT_HAVE"


def _basic_move_is_damage_comparable(move_name):
    """AICmd_FlagMoveDamageScore's eligibility gate, on the RAW move-table
    power: the move's effect is alt-power, OR power > 1 and the effect is
    not a no-damage-calc one. Everything else - every status move, and also
    the OHKO moves Guillotine/Sheer Cold with their power of 1 - yields
    AI_NO_COMPARISON_MADE."""
    power = (_MOVES_BY_NAME.get(move_name) or {}).get("power", 0) or 0
    return move_name in AI_ALT_POWER_MOVES or (power > 1 and move_name not in AI_NO_DAMAGE_CALC_MOVES)


def _basic_entry_checks(move_name, move, attacker, defender, bstate, rng, out=None):
    """Basic_Main from its first line through Basic_CheckSoundproof.
    Returns the final move score if the script TERMINATES here (every
    ScoreMinusN label ends in PopOrEnd, including the -12 absorption cases,
    so nothing later can add to them), or None to continue on to
    Basic_ScoreMoveEffect.

    Basic_CheckForImmunity - the type-chart immunity (-10) and the
    absorption-ability (-12) checks - only runs for Fissure/Horn Drill
    (which jump straight into it) and for moves that pass
    FlagMoveDamageScore's comparison gate. A status move gets
    AI_NO_COMPARISON_MADE and skips it entirely; type immunity for those is
    handled by their own effect-specific checks further down instead
    (e.g. Normal-type Swords Dance/Protect are NOT penalised against a
    Ghost here).

    The Dry Skin line in the real script is a retail bug (it re-tests
    Levitate, which was already matched a line earlier), so Dry Skin never
    gets the -12 water check - hence its absence from
    AI_ABSORPTION_ABILITY_TYPE."""
    if move_name in ("MOVE_FISSURE", "MOVE_HORN_DRILL") or _basic_move_is_damage_comparable(move_name):
        eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
        if eff == 0.0:
            return -10
        if _ai_ability(attacker) != "MOLD_BREAKER":
            dab = ai_load_ability(defender, attacker, rng)
            absorb_type = AI_ABSORPTION_ABILITY_TYPE.get(dab)
            if absorb_type is not None:
                # LoadTypeFrom LOAD_MOVE_TYPE reads the raw move-table type
                raw_type = (_MOVES_BY_NAME.get(move_name) or {}).get("type", move.get("type", "TYPE_NORMAL"))
                if absorb_type == raw_type:
                    return -12
            elif dab == "WONDER_GUARD" and eff not in (2.0, 4.0):
                return -12
    # Basic_CheckSoundproof: only the script's own 11 moves, not every sound move
    # The defender's ability is loaded again here (a fresh guess); whatever the script loaded LAST stays in its register
    # and Basic_CheckMagnitude later reads it (`out["loaded"]`).
    loaded = ai_load_ability(defender, attacker, rng)
    if loaded == "SOUNDPROOF":
        loaded = _ai_ability(attacker)
        if loaded != "MOLD_BREAKER" and move_name in AI_SOUNDPROOF_MOVES:
            return -10
    if out is not None:
        out["loaded"] = loaded
    return None


def _basic_ohko_would_fail(move, attacker, defender, bstate, rng):
    """Basic_CheckOHKOWouldFail: -10 if the OHKO move can never work - type
    chart immunity (NOT ability-folded: Wonder Guard/absorption abilities
    are not considered here), Sturdy (unless Mold Breaker), or the user
    being a lower level than the target. Otherwise no change."""
    if _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate) == 0.0:
        return -10
    if _ai_ability(attacker) != "MOLD_BREAKER" and ai_load_ability(defender, attacker, rng) == "STURDY":
        return -10
    if attacker.get("level", 50) < defender.get("level", 50):
        return -10
    return 0


# ---------------- Basic_Main: effect-specific scoring (script.s 133-1562) ----------------
# Basic_ScoreMoveEffect dispatches on the move's REAL BATTLE_EFFECT_* tag (152 rows, generated straight from the
# script; first match wins) - NOT on this file's own effect vocabulary, which is why several checks in the earlier
# hand-built version could never fire (Swords Dance has no "effect" tag here at all, Toxic is "TOXIC", ...).
# Every ScoreMinusN label in the script ends the script (PopOrEnd), so each handler returns the final delta.
BASIC_DISPATCH_ORDER = [
    ("BATTLE_EFFECT_STATUS_SLEEP", "Basic_CheckCannotSleep"),
    ("BATTLE_EFFECT_HALVE_DEFENSE", "Basic_CheckCannotExplode"),
    ("BATTLE_EFFECT_RECOVER_DAMAGE_SLEEP", "Basic_CheckDreamEater"),
    ("BATTLE_EFFECT_ATK_UP", "Basic_CheckHighStatStage_Attack"),
    ("BATTLE_EFFECT_DEF_UP", "Basic_CheckHighStatStage_Defense"),
    ("BATTLE_EFFECT_SPEED_UP", "Basic_CheckHighStatStage_Speed"),
    ("BATTLE_EFFECT_SP_ATK_UP", "Basic_CheckHighStatStage_SpAttack"),
    ("BATTLE_EFFECT_SP_DEF_UP", "Basic_CheckHighStatStage_SpDefense"),
    ("BATTLE_EFFECT_ACC_UP", "Basic_CheckHighStatStage_Accuracy"),
    ("BATTLE_EFFECT_EVA_UP", "Basic_CheckHighStatStage_Evasion"),
    ("BATTLE_EFFECT_ATK_DOWN", "Basic_CheckLowStatStage_Attack"),
    ("BATTLE_EFFECT_DEF_DOWN", "Basic_CheckLowStatStage_Defense"),
    ("BATTLE_EFFECT_SPEED_DOWN", "Basic_CheckLowStatStage_Speed"),
    ("BATTLE_EFFECT_SP_ATK_DOWN", "Basic_CheckLowStatStage_SpAttack"),
    ("BATTLE_EFFECT_SP_DEF_DOWN", "Basic_CheckLowStatStage_SpDefense"),
    ("BATTLE_EFFECT_ACC_DOWN", "Basic_CheckLowStatStage_Accuracy"),
    ("BATTLE_EFFECT_EVA_DOWN", "Basic_CheckLowStatStage_Evasion"),
    ("BATTLE_EFFECT_RESET_STAT_CHANGES", "Basic_CheckStatStageImbalance"),
    ("BATTLE_EFFECT_BIDE", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_FORCE_SWITCH", "Basic_CheckCanForceSwitch"),
    ("BATTLE_EFFECT_RESTORE_HALF_HP", "Basic_CheckCanRecoverHP"),
    ("BATTLE_EFFECT_STATUS_BADLY_POISON", "Basic_CheckCannotPoison"),
    ("BATTLE_EFFECT_SET_LIGHT_SCREEN", "Basic_CheckAlreadyUnderLightScreen"),
    ("BATTLE_EFFECT_ONE_HIT_KO", "Basic_CheckOHKOWouldFail"),
    ("BATTLE_EFFECT_CHARGE_TURN_HIGH_CRIT", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_HALVE_HP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_40_DAMAGE_FLAT", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_PREVENT_STAT_REDUCTION", "Basic_CheckAlreadyUnderMist"),
    ("BATTLE_EFFECT_CRIT_UP_2", "Basic_CheckAlreadyPumpedUp"),
    ("BATTLE_EFFECT_STATUS_CONFUSE", "Basic_CheckCannotConfuse"),
    ("BATTLE_EFFECT_ATK_UP_2", "Basic_CheckHighStatStage_Attack"),
    ("BATTLE_EFFECT_DEF_UP_2", "Basic_CheckHighStatStage_Defense"),
    ("BATTLE_EFFECT_SPEED_UP_2", "Basic_CheckHighStatStage_Speed"),
    ("BATTLE_EFFECT_SP_ATK_UP_2", "Basic_CheckHighStatStage_SpAttack"),
    ("BATTLE_EFFECT_SP_DEF_UP_2", "Basic_CheckHighStatStage_SpDefense"),
    ("BATTLE_EFFECT_ACC_UP_2", "Basic_CheckHighStatStage_Accuracy"),
    ("BATTLE_EFFECT_EVA_UP_2", "Basic_CheckHighStatStage_Evasion"),
    ("BATTLE_EFFECT_ATK_DOWN_2", "Basic_CheckLowStatStage_Attack"),
    ("BATTLE_EFFECT_DEF_DOWN_2", "Basic_CheckLowStatStage_Defense"),
    ("BATTLE_EFFECT_SPEED_DOWN_2", "Basic_CheckLowStatStage_Speed"),
    ("BATTLE_EFFECT_SP_ATK_DOWN_2", "Basic_CheckLowStatStage_SpAttack"),
    ("BATTLE_EFFECT_SP_DEF_DOWN_2", "Basic_CheckLowStatStage_SpDefense"),
    ("BATTLE_EFFECT_EVA_DOWN_2", "Basic_CheckLowStatStage_Accuracy"),
    ("BATTLE_EFFECT_ACC_DOWN_2", "Basic_CheckLowStatStage_Evasion"),
    ("BATTLE_EFFECT_SET_REFLECT", "Basic_CheckAlreadyUnderReflect"),
    ("BATTLE_EFFECT_STATUS_POISON", "Basic_CheckCannotPoison"),
    ("BATTLE_EFFECT_STATUS_PARALYZE", "Basic_CheckCannotParalyze"),
    ("BATTLE_EFFECT_SET_SUBSTITUTE", "Basic_CheckCannotSubstitute"),
    ("BATTLE_EFFECT_RECHARGE_AFTER", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_STATUS_LEECH_SEED", "Basic_CheckCannotLeechSeed"),
    ("BATTLE_EFFECT_DISABLE", "Basic_CheckCannotDisable"),
    ("BATTLE_EFFECT_LEVEL_DAMAGE_FLAT", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_RANDOM_DAMAGE_1_TO_150_LEVEL", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_COUNTER", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_ENCORE", "Basic_CheckCannotEncore"),
    ("BATTLE_EFFECT_DAMAGE_WHILE_ASLEEP", "Basic_CheckAttackerAsleep"),
    ("BATTLE_EFFECT_NEXT_ATTACK_ALWAYS_HITS", "Basic_CheckLockOn"),
    ("BATTLE_EFFECT_USE_RANDOM_LEARNED_MOVE_SLEEP", "Basic_CheckAttackerAsleep"),
    ("BATTLE_EFFECT_INCREASE_POWER_WITH_LESS_HP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_PREVENT_ESCAPE", "Basic_CheckMeanLook"),
    ("BATTLE_EFFECT_STATUS_NIGHTMARE", "Basic_CheckNightmare"),
    ("BATTLE_EFFECT_EVA_UP_2_MINIMIZE", "Basic_CheckHighStatStage_Evasion"),
    ("BATTLE_EFFECT_CURSE", "Basic_CheckCurse"),
    ("BATTLE_EFFECT_SET_SPIKES", "Basic_CheckSpikes"),
    ("BATTLE_EFFECT_FORESIGHT", "Basic_CheckForesight"),
    ("BATTLE_EFFECT_ALL_FAINT_3_TURNS", "Basic_CheckPerishSong"),
    ("BATTLE_EFFECT_WEATHER_SANDSTORM", "Basic_CheckSandstorm"),
    ("BATTLE_EFFECT_ATK_UP_2_STATUS_CONFUSION", "Basic_CheckCannotConfuse"),
    ("BATTLE_EFFECT_INFATUATE", "Basic_CheckCannotAttract"),
    ("BATTLE_EFFECT_POWER_BASED_ON_FRIENDSHIP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_RANDOM_POWER_MAYBE_HEAL", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_POWER_BASED_ON_LOW_FRIENDSHIP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_PREVENT_STATUS", "Basic_CheckAlreadyUnderSafeguard"),
    ("BATTLE_EFFECT_PSYWAVE", "Basic_CheckMagnitude"),
    ("BATTLE_EFFECT_PASS_STATS_AND_STATUS", "Basic_CheckBatonPass"),
    ("BATTLE_EFFECT_20_DAMAGE_FLAT", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_HEAL_HALF_MORE_IN_SUN", "Basic_CheckCanRecoverHP"),
    ("BATTLE_EFFECT_UNUSED_133", "Basic_CheckCanRecoverHP"),
    ("BATTLE_EFFECT_UNUSED_134", "Basic_CheckCanRecoverHP"),
    ("BATTLE_EFFECT_RANDOM_POWER_BASED_ON_IVS", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_WEATHER_RAIN", "Basic_CheckRainDance"),
    ("BATTLE_EFFECT_WEATHER_SUN", "Basic_CheckSunnyDay"),
    ("BATTLE_EFFECT_MAX_ATK_LOSE_HALF_MAX_HP", "Basic_CheckBellyDrum"),
    ("BATTLE_EFFECT_COPY_STAT_CHANGES", "Basic_CheckStatStageImbalance"),
    ("BATTLE_EFFECT_MIRROR_COAT", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_CHARGE_TURN_DEF_UP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_HIT_IN_3_TURNS", "Basic_CheckFutureSight"),
    ("BATTLE_EFFECT_FLEE_FROM_WILD_BATTLE", "ScoreMinus10"),
    ("BATTLE_EFFECT_DEF_UP_DOUBLE_ROLLOUT_POWER", "Basic_CheckHighStatStage_Defense"),
    ("BATTLE_EFFECT_UNUSED_157", "Basic_CheckCanRecoverHP"),
    ("BATTLE_EFFECT_ALWAYS_FLINCH_FIRST_TURN_ONLY", "Basic_CheckFirstTurnInBattle"),
    ("BATTLE_EFFECT_STOCKPILE", "Basic_CheckMaxStockpile"),
    ("BATTLE_EFFECT_SPIT_UP", "Basic_CheckCanSpitUpOrSwallow"),
    ("BATTLE_EFFECT_SWALLOW", "Basic_CheckCanSpitUpOrSwallow"),
    ("BATTLE_EFFECT_WEATHER_HAIL", "Basic_CheckHail"),
    ("BATTLE_EFFECT_TORMENT", "Basic_CheckTorment"),
    ("BATTLE_EFFECT_SP_ATK_UP_CAUSE_CONFUSION", "Basic_CheckCannotConfuse"),
    ("BATTLE_EFFECT_STATUS_BURN", "Basic_CheckCannotBurn"),
    ("BATTLE_EFFECT_FAINT_AND_ATK_SP_ATK_DOWN_2", "Basic_CheckMemento"),
    ("BATTLE_EFFECT_HIT_LAST_WHIFF_IF_HIT", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_BOOST_ALLY_POWER_BY_50_PERCENT", "Basic_CheckHelpingHand"),
    ("BATTLE_EFFECT_SWITCH_HELD_ITEMS", "Basic_CheckCanRemoveItem"),
    ("BATTLE_EFFECT_GROUND_TRAP_USER_CONTINUOUS_HEAL", "Basic_CheckAlreadyIngrained"),
    ("BATTLE_EFFECT_LOWER_OWN_ATK_AND_DEF", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_RECYCLE", "Basic_CheckCanRecycle"),
    ("BATTLE_EFFECT_STATUS_SLEEP_NEXT_TURN", "Basic_CheckCannotSleep"),
    ("BATTLE_EFFECT_REMOVE_HELD_ITEM", "Basic_CheckCanRemoveItem"),
    ("BATTLE_EFFECT_SET_HP_EQUAL_TO_USER", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_MAKE_SHARED_MOVES_UNUSEABLE", "Basic_CheckCanImprison"),
    ("BATTLE_EFFECT_HEAL_STATUS", "Basic_CheckCanRefreshStatus"),
    ("BATTLE_EFFECT_INCREASE_POWER_WITH_WEIGHT", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_HALVE_ELECTRIC_DAMAGE", "Basic_CheckCanMudSport"),
    ("BATTLE_EFFECT_ATK_DEF_DOWN", "Basic_CheckTickle"),
    ("BATTLE_EFFECT_DEF_SPD_UP", "Basic_CheckCosmicPower"),
    ("BATTLE_EFFECT_ATK_DEF_UP", "Basic_CheckBulkUp"),
    ("BATTLE_EFFECT_HALVE_FIRE_DAMAGE", "Basic_CheckWaterSport"),
    ("BATTLE_EFFECT_SP_ATK_SP_DEF_UP", "Basic_CheckCalmMind"),
    ("BATTLE_EFFECT_ATK_SPD_UP", "Basic_CheckDragonDance"),
    ("BATTLE_EFFECT_CAMOUFLAGE", "Basic_CheckCamouflage"),
    ("BATTLE_EFFECT_HEAL_HALF_REMOVE_FLYING_TYPE", "Basic_CheckCanRecoverHP"),
    ("BATTLE_EFFECT_GRAVITY", "Basic_CheckGravityActive"),
    ("BATTLE_EFFECT_IGNORE_EVATION_REMOVE_DARK_IMMUNE", "Basic_CheckMiracleEye"),
    ("BATTLE_EFFECT_POWER_BASED_ON_LOW_SPEED", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_FAINT_AND_FULL_HEAL_NEXT_MON", "Basic_CheckHealingWish"),
    ("BATTLE_EFFECT_NATURAL_GIFT", "Basic_CheckNaturalGift"),
    ("BATTLE_EFFECT_DOUBLE_SPEED_3_TURNS", "Basic_CheckTailwind"),
    ("BATTLE_EFFECT_RANDOM_STAT_UP_2", "Basic_CheckAcupressure"),
    ("BATTLE_EFFECT_METAL_BURST", "Basic_CheckMetalBurst"),
    ("BATTLE_EFFECT_PREVENT_ITEM_USE", "Basic_CheckEmbargo"),
    ("BATTLE_EFFECT_FLING", "Basic_CheckFling"),
    ("BATTLE_EFFECT_TRANSFER_STATUS", "Basic_CheckCanPsychoShift"),
    ("BATTLE_EFFECT_HIGHER_POWER_WHEN_LOW_PP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_PREVENT_HEALING", "Basic_CheckHealBlock"),
    ("BATTLE_EFFECT_INCREASE_POWER_WITH_MORE_HP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_SWAP_ATK_DEF", "Basic_CheckPowerTrick"),
    ("BATTLE_EFFECT_SUPRESS_ABILITY", "Basic_CheckGastroAcid"),
    ("BATTLE_EFFECT_PREVENT_CRITS", "Basic_CheckLuckyChant"),
    ("BATTLE_EFFECT_USE_LAST_USED_MOVE", "Basic_CheckCopycat"),
    ("BATTLE_EFFECT_SWAP_ATK_SP_ATK_STAT_CHANGES", "Basic_CheckPowerSwap"),
    ("BATTLE_EFFECT_SWAP_DEF_SP_DEF_STAT_CHANGES", "Basic_CheckGuardSwap"),
    ("BATTLE_EFFECT_INCREASE_POWER_WITH_MORE_STAT_UP", "Basic_CheckNonStandardDamageOrChargeTurn"),
    ("BATTLE_EFFECT_FAIL_IF_NOT_USED_ALL_OTHER_MOVES", "Basic_CheckLastResort"),
    ("BATTLE_EFFECT_SET_ABILITY_TO_INSOMNIA", "Basic_CheckWorrySeed"),
    ("BATTLE_EFFECT_TOXIC_SPIKES", "Basic_CheckToxicSpikes"),
    ("BATTLE_EFFECT_SWAP_STAT_CHANGES", "Basic_CheckStatStageImbalance"),
    ("BATTLE_EFFECT_RESTORE_HP_EVERY_TURN", "Basic_CheckAquaRing"),
    ("BATTLE_EFFECT_GIVE_GROUND_IMMUNITY", "Basic_CheckMagnetRise"),
    ("BATTLE_EFFECT_REMOVE_HAZARDS_SCREENS_EVA_DOWN", "Basic_CheckDefog"),
    ("BATTLE_EFFECT_TRICK_ROOM", "Basic_CheckTrickRoom"),
    ("BATTLE_EFFECT_SP_ATK_DOWN_2_OPPOSITE_GENDER", "Basic_CheckCaptivate"),
    ("BATTLE_EFFECT_STEALTH_ROCK", "Basic_CheckStealthRock"),
    ("BATTLE_EFFECT_FAINT_FULL_RESTORE_NEXT_MON", "Basic_CheckLunarDance"),
]

BASIC_NATURAL_GIFT_BERRIES = frozenset([
    "ITEM_CHERI_BERRY",
    "ITEM_CHESTO_BERRY",
    "ITEM_PECHA_BERRY",
    "ITEM_RAWST_BERRY",
    "ITEM_ASPEAR_BERRY",
    "ITEM_LEPPA_BERRY",
    "ITEM_ORAN_BERRY",
    "ITEM_PERSIM_BERRY",
    "ITEM_LUM_BERRY",
    "ITEM_SITRUS_BERRY",
    "ITEM_FIGY_BERRY",
    "ITEM_WIKI_BERRY",
    "ITEM_MAGO_BERRY",
    "ITEM_AGUAV_BERRY",
    "ITEM_IAPAPA_BERRY",
    "ITEM_RAZZ_BERRY",
    "ITEM_BLUK_BERRY",
    "ITEM_NANAB_BERRY",
    "ITEM_WEPEAR_BERRY",
    "ITEM_PINAP_BERRY",
    "ITEM_POMEG_BERRY",
    "ITEM_KELPSY_BERRY",
    "ITEM_QUALOT_BERRY",
    "ITEM_HONDEW_BERRY",
    "ITEM_GREPA_BERRY",
    "ITEM_TAMATO_BERRY",
    "ITEM_CORNN_BERRY",
    "ITEM_MAGOST_BERRY",
    "ITEM_RABUTA_BERRY",
    "ITEM_NOMEL_BERRY",
    "ITEM_SPELON_BERRY",
    "ITEM_PAMTRE_BERRY",
    "ITEM_WATMEL_BERRY",
    "ITEM_DURIN_BERRY",
    "ITEM_BELUE_BERRY",
    "ITEM_OCCA_BERRY",
    "ITEM_PASSHO_BERRY",
    "ITEM_WACAN_BERRY",
    "ITEM_RINDO_BERRY",
    "ITEM_YACHE_BERRY",
    "ITEM_CHOPLE_BERRY",
    "ITEM_KEBIA_BERRY",
    "ITEM_SHUCA_BERRY",
    "ITEM_COBA_BERRY",
    "ITEM_PAYAPA_BERRY",
    "ITEM_TANGA_BERRY",
    "ITEM_CHARTI_BERRY",
    "ITEM_KASIB_BERRY",
    "ITEM_HABAN_BERRY",
    "ITEM_COLBUR_BERRY",
    "ITEM_BABIRI_BERRY",
    "ITEM_CHILAN_BERRY",
    "ITEM_LIECHI_BERRY",
    "ITEM_GANLON_BERRY",
    "ITEM_SALAC_BERRY",
    "ITEM_PETAYA_BERRY",
    "ITEM_APICOT_BERRY",
    "ITEM_LANSAT_BERRY",
    "ITEM_STARF_BERRY",
    "ITEM_ENIGMA_BERRY",
    "ITEM_MICLE_BERRY",
    "ITEM_CUSTAP_BERRY",
    "ITEM_JABOCA_BERRY",
    "ITEM_ROWAP_BERRY",
])


BASIC_DISPATCH = {}
for _effect, _label in BASIC_DISPATCH_ORDER:
    BASIC_DISPATCH.setdefault(_effect, _label)


class _BC:
    """Everything a Basic handler can see: the two battlers, the field, the two 'other Pokemon alive' counts
    (CountAlivePartyBattlers), the attacker's party and active ally, and the AI rng (only used for the
    real speed-compare's tie coin flip)."""
    __slots__ = ("name", "move", "a", "d", "b", "att_alive", "dfn_alive", "party", "ally", "rng", "loaded")

    def __init__(self, name, move, a, d, b, att_alive, dfn_alive, party, ally, rng):
        self.name, self.move, self.a, self.d, self.b = name, move, a, d, b
        self.att_alive, self.dfn_alive, self.party, self.ally, self.rng = att_alive, dfn_alive, party, ally, rng
        self.loaded = None          # the script's "loaded value" register as Basic_ScoreMoveEffect is entered (see _basic_entry_checks)


def _bc_dab(c):
    """LoadBattlerAbility AI_BATTLER_DEFENDER for a Basic handler: the target's ability as the AI believes it (see ai_load_ability -
    each call is one script Load, so it may draw the guessing coin)."""
    return ai_load_ability(c.d, c.a, c.rng)


def _bc_status_any(m):
    """MON_CONDITION_ANY (this file stores 'NONE' for no status)."""
    return m.get("status", "NONE") not in (None, "NONE")


def _bc_safeguard(m):
    """SIDE_CONDITION_SAFEGUARD - this simulator stores Safeguard on the Pokemon, not the side."""
    return m.get("safeguard", 0) > 0


def _bc_side(c, m):
    return c.b["sides"][c.b["side_of"](m)]


def _bc_types(m):
    return {t for t in (m.get("type1"), m.get("type2")) if t}


def _bc_immune(c):
    """IfMoveEffectivenessEquals TYPE_MULTI_IMMUNE."""
    return _ai_move_effectiveness(c.move.get("type", "TYPE_NORMAL"), c.a, c.d, c.b) == 0.0


def _bc_faster(c):
    """IfSpeedCompareEqualTo COMPARE_SPEED_FASTER. The real compare returns FASTER by default and, on an exact
    speed tie, TIE on a coin flip - so a tie counts as FASTER half the time."""
    cmp_ = _speed_compare(c.a, c.d, c.b)
    return cmp_ == "FASTER" or (cmp_ == "TIE" and c.rng.randint(0, 1) == 0)


def _bc_hp_full(m):
    return ai_hp_percent(m) == 100


def _bc_high_stage(a, key):
    """Basic_CheckHighStatStage_*: -10 if a boost is pointless - with Simple, already at +3 or more (raw > 8);
    otherwise only when maxed at +6."""
    st = a.get(key, 0)
    if _ai_ability(a) == "SIMPLE":
        return -10 if st > 2 else 0
    return -10 if st == 6 else 0


def _bc_no_guard(c, attacker_first=False):
    """Either battler has No Guard. The script's load order differs per handler (the target's ability is a guess, so the
    order decides whether the guessing coin is drawn at all)."""
    if attacker_first:
        return _ai_ability(c.a) == "NO_GUARD" or _bc_dab(c) == "NO_GUARD"
    return _bc_dab(c) == "NO_GUARD" or _ai_ability(c.a) == "NO_GUARD"


def _bc_clear_body(c):
    """Basic_CheckClearBodyEffect (ignores Mold Breaker, as in the script)."""
    return -10 if _bc_dab(c) in ("CLEAR_BODY", "WHITE_SMOKE") else 0


def _bc_cannot_poison_status(c):
    d = c.d
    return _bc_status_any(d) or _bc_safeguard(d)


def _bh_cannot_sleep(c):
    d = c.d
    if _bc_status_any(d) or _bc_safeguard(d) or _bc_dab(c) in ("INSOMNIA", "VITAL_SPIRIT"):
        return -10
    return 0


def _bh_cannot_explode(c):
    if _bc_immune(c):
        return -10
    if _ai_ability(c.a) != "MOLD_BREAKER" and _bc_dab(c) == "DAMP":
        return -10
    # Basic_CheckLastMon: on our last Pokemon and the target's is not -> -10; both on their last -> only -1
    if c.att_alive != 0:
        return 0
    return -10 if c.dfn_alive != 0 else -1


def _bh_nightmare(c):
    d = c.d
    if d.get("nightmare"):
        return -10
    if d.get("status") != "SLEEP":
        return -8
    return -10 if _bc_dab(c) == "MAGIC_GUARD" else 0


def _bh_dream_eater(c):
    if c.d.get("status") != "SLEEP":
        return -8
    return -10 if _bc_immune(c) else 0


def _bh_belly_drum(c):
    # Falls through into Basic_CheckHighStatStage_Attack (no PopOrEnd in between)
    if ai_hp_percent(c.a) < 51:
        return -10
    return _bc_high_stage(c.a, "atk_stage")


def _bh_high_attack(c): return _bc_high_stage(c.a, "atk_stage")
def _bh_high_defense(c): return _bc_high_stage(c.a, "def_stage")
def _bh_high_spattack(c): return _bc_high_stage(c.a, "spa_stage")
def _bh_high_spdefense(c): return _bc_high_stage(c.a, "spd_stage")


def _bh_high_speed(c):
    if c.b.get("trick_room", 0) > 0:
        return -10
    return _bc_high_stage(c.a, "spe_stage")


def _bh_high_accuracy(c):
    return -10 if _bc_no_guard(c) else _bc_high_stage(c.a, "acc_stage")


def _bh_high_evasion(c):
    return -10 if _bc_no_guard(c) else _bc_high_stage(c.a, "eva_stage")


def _bh_low_attack(c):
    if c.d.get("atk_stage", 0) == -6 or _bc_dab(c) == "HYPER_CUTTER":
        return -10
    return _bc_clear_body(c)


def _bh_low_defense(c):
    return -10 if c.d.get("def_stage", 0) == -6 else _bc_clear_body(c)


def _bh_low_speed(c):
    if c.b.get("trick_room", 0) > 0 or c.d.get("spe_stage", 0) == -6 or ai_check_ability(c.d, "SPEED_BOOST", c.a) == "HAVE":
        return -10
    return _bc_clear_body(c)


def _bh_low_spattack(c):
    return -10 if c.d.get("spa_stage", 0) == -6 else _bc_clear_body(c)


def _bh_low_spdefense(c):
    return -10 if c.d.get("spd_stage", 0) == -6 else _bc_clear_body(c)


def _bh_low_accuracy(c):
    if c.d.get("acc_stage", 0) == -6 or _ai_ability(c.a) == "NO_GUARD" or _bc_dab(c) in ("KEEN_EYE", "NO_GUARD"):
        return -10
    return _bc_clear_body(c)


def _bh_low_evasion(c):
    if c.d.get("eva_stage", 0) == -6 or _bc_no_guard(c, attacker_first=True):
        return -10
    return _bc_clear_body(c)


_BC_ALL_STAGES = ("atk_stage", "def_stage", "spe_stage", "spa_stage", "spd_stage", "acc_stage", "eva_stage")


def _bh_stat_imbalance(c):
    """Haze / Psych Up / Heart Swap: -10 unless the user has a lowered stat or the target a raised one."""
    if any(c.a.get(k, 0) < 0 for k in _BC_ALL_STAGES) or any(c.d.get(k, 0) > 0 for k in _BC_ALL_STAGES):
        return 0
    return -10


def _bh_can_force_switch(c):
    if c.dfn_alive == 0:
        return -10
    if _ai_ability(c.a) != "MOLD_BREAKER" and _bc_dab(c) == "SUCTION_CUPS":
        return -10
    return 0


def _bh_can_recover_hp(c):
    return -8 if _bc_hp_full(c.a) else 0


def _bh_cannot_poison(c):
    d = c.d
    if _bc_types(d) & {"TYPE_STEEL", "TYPE_POISON"}:
        return -10
    ab = _bc_dab(c)
    if ab in ("IMMUNITY", "MAGIC_GUARD", "POISON_HEAL"):
        return -10
    if ab == "LEAF_GUARD" and c.b.get("weather") == "SUN":
        return -10
    if _bc_dab(c) == "HYDRATION" and c.b.get("weather") == "RAIN":          # the script loads the ability a SECOND time here
        return -10
    return -10 if _bc_cannot_poison_status(c) else 0


def _bh_light_screen(c): return -8 if _bc_side(c, c.a).get("light_screen") else 0
def _bh_mist(c): return -8 if _bc_side(c, c.a).get("mist") else 0
def _bh_reflect(c): return -8 if _bc_side(c, c.a).get("reflect") else 0


def _bh_ohko(c):
    return _basic_ohko_would_fail(c.move, c.a, c.d, c.b, c.rng)


def _bh_magnitude(c):
    """Basic_CheckMagnitude. Retail bug reproduced: it never loads the ATTACKER's ability, so the 'is it Mold Breaker' test
    reads whatever the script last loaded - the DEFENDER's guessed ability from Basic_CheckSoundproof (or the attacker's, when
    that was Soundproof) - before a fresh defender load feeds the Levitate check."""
    if c.loaded != "MOLD_BREAKER" and _bc_dab(c) == "LEVITATE":
        return -10
    return _bh_nonstandard_damage(c)


def _bh_nonstandard_damage(c):
    """Basic_CheckNonStandardDamageOrChargeTurn: -10 if immune by type, or Wonder Guard blocks it."""
    if _bc_immune(c):
        return -10
    if _bc_dab(c) != "WONDER_GUARD" or _ai_ability(c.a) == "MOLD_BREAKER":
        return 0
    eff = _ai_move_effectiveness(c.move.get("type", "TYPE_NORMAL"), c.a, c.d, c.b)
    return 0 if eff in (2.0, 4.0) else -10


def _bh_pumped_up(c): return -10 if c.a.get("focus_energy") else 0


def _bh_cannot_confuse(c):
    d = c.d
    if d.get("confused"):
        return -5
    return -10 if (_bc_dab(c) == "OWN_TEMPO" or _bc_safeguard(d)) else 0


def _bh_cannot_paralyze(c):
    d = c.d
    if _bc_immune(c) or _bc_dab(c) in ("LIMBER", "MAGIC_GUARD"):
        return -10
    if _ai_ability(c.a) != "MOLD_BREAKER" and c.name == "MOVE_THUNDER_WAVE" and _bc_dab(c) in ("MOTOR_DRIVE", "VOLT_ABSORB"):
        return -10
    return -10 if _bc_cannot_poison_status(c) else 0


def _bh_cannot_substitute(c):
    if c.a.get("substitute_hp", 0) > 0:
        return -8
    return -10 if ai_hp_percent(c.a) < 26 else 0


def _bh_cannot_leech_seed(c):
    d = c.d
    if d.get("leech_seeded") or "TYPE_GRASS" in _bc_types(d) or _bc_dab(c) == "MAGIC_GUARD":
        return -10
    return 0


def _bh_cannot_disable(c): return -8 if c.d.get("disabled_move") else 0
def _bh_cannot_encore(c): return -8 if c.d.get("encore_turns", 0) > 0 else 0
def _bh_attacker_asleep(c): return 0 if c.a.get("status") == "SLEEP" else -8


def _bh_lock_on(c):
    return -10 if (c.d.get("locked_on_by") or _bc_no_guard(c, attacker_first=True)) else 0


def _bh_mean_look(c):
    d = c.d
    return -10 if (d.get("trapped_turns", 0) > 0 or d.get("mean_look")) else 0


def _bh_curse(c):
    a, d = c.a, c.d
    if "TYPE_GHOST" in _bc_types(a):
        return -10 if (d.get("cursed") or _bc_dab(c) == "MAGIC_GUARD") else 0
    if _ai_ability(a) == "SIMPLE":
        return -10 if (a.get("atk_stage", 0) > 2 or a.get("def_stage", 0) > 2) else 0
    if a.get("atk_stage", 0) == 6:
        return -10
    return -8 if a.get("def_stage", 0) == 6 else 0


def _bh_spikes(c):
    if _bc_side(c, c.d).get("spikes", 0) == 3 or c.dfn_alive == 0:
        return -10
    return 0


def _bh_foresight(c): return -10 if c.d.get("foresight") else 0
def _bh_perish_song(c): return -10 if c.d.get("perish_song", 0) > 0 else 0
def _bh_sandstorm(c): return -8 if c.b.get("weather") == "SANDSTORM" else 0


def _bh_cannot_attract(c):
    a, d = c.a, c.d
    if d.get("attracted") or _bc_dab(c) == "OBLIVIOUS":
        return -10
    ga, gd = a.get("gender", "GENDERLESS"), d.get("gender", "GENDERLESS")
    if (ga == "MALE" and gd == "FEMALE") or (ga == "FEMALE" and gd == "MALE"):
        return 0
    return -10


def _bh_safeguard(c): return -8 if _bc_safeguard(c.a) else 0


def _bh_memento(c):
    a, d = c.a, c.d
    if _ai_ability(a) != "MOLD_BREAKER" and _bc_dab(c) in ("CLEAR_BODY", "WHITE_SMOKE"):
        return -10
    if d.get("atk_stage", 0) == -6:
        return -10
    if d.get("spa_stage", 0) == -6:
        return -8
    return -10 if c.att_alive == 0 else 0


def _bh_baton_pass(c): return -10 if c.att_alive == 0 else 0


def _bh_rain_dance(c):
    a, d = c.a, c.d
    if _ai_ability(a) not in ("SWIFT_SWIM", "HYDRATION") and _bc_dab(c) == "HYDRATION" and _bc_status_any(d):
        return -8
    return -8 if c.b.get("weather") == "RAIN" else 0


def _bh_sunny_day(c):
    """Retail bug reproduced: the script checks the target's HYDRATION here too (a copy-paste of Rain Dance's
    check), with a -10 instead of -8."""
    a, d = c.a, c.d
    if _ai_ability(a) not in ("FLOWER_GIFT", "LEAF_GUARD", "SOLAR_POWER") and _bc_dab(c) == "HYDRATION" and _bc_status_any(d):
        return -10
    return -8 if c.b.get("weather") == "SUN" else 0


def _bh_future_sight(c):
    return -12 if (_bc_side(c, c.d).get("future_sight") or _bc_side(c, c.a).get("future_sight")) else 0


def _bh_first_turn(c):
    """LoadIsFirstTurnInBattle: -10 once the user has already acted since it switched in (the same state the
    engine uses to decide whether Fake Out still works)."""
    return -10 if c.a.get("acted_since_switch_in") else 0


def _bh_max_stockpile(c): return -10 if c.a.get("stockpile", 0) == 3 else 0


def _bh_spit_up_or_swallow(c):
    if _bc_immune(c) or c.a.get("stockpile", 0) == 0:
        return -10
    if _real_effect(c.name) == "BATTLE_EFFECT_SWALLOW":
        return _bh_can_recover_hp(c)
    return 0


def _bh_hail(c):
    """-8 in Hail; -8 if the target has Ice Body, which the user's own Ice Body then cancels (retail quirk)."""
    if c.b.get("weather") == "HAIL":
        return -8
    if _bc_dab(c) != "ICE_BODY":
        return 0
    return 0 if _ai_ability(c.a) == "ICE_BODY" else -8


def _bh_torment(c): return -10 if c.d.get("tormented") else 0


def _bh_cannot_burn(c):
    d = c.d
    if _bc_dab(c) in ("WATER_VEIL", "MAGIC_GUARD") or _bc_status_any(d) or "TYPE_FIRE" in _bc_types(d) or _bc_safeguard(d):
        return -10
    return 0


def _bh_helping_hand(c): return 0 if c.b.get("is_double_battle") else -10


def _bh_can_remove_item(c):
    d = c.d
    return -10 if (_bc_dab(c) == "STICKY_HOLD" or not d.get("item")) else 0


def _bh_ingrain(c): return -10 if c.a.get("ingrain") else 0
def _bh_recycle(c): return 0 if c.a.get("consumed_item") else -10


def _bh_imprison(c):
    return -10 if (c.a.get("imprison_moves") or c.d.get("imprisoned_by_opponent")) else 0


def _bh_refresh(c):
    return 0 if c.a.get("status") in ("BURN", "POISON", "TOXIC", "PARALYSIS") else -10


def _bh_mud_sport(c): return -10 if c.a.get("mud_sport") else 0
def _bh_water_sport(c): return -10 if c.a.get("water_sport") else 0


def _bh_tickle(c):
    d = c.d
    if _ai_ability(c.a) != "MOLD_BREAKER" and _bc_dab(c) in ("CLEAR_BODY", "WHITE_SMOKE"):
        return -10
    if d.get("atk_stage", 0) == -6:
        return -10
    return -8 if d.get("def_stage", 0) == -6 else 0


def _bc_paired_boost(a, first, second):
    """Cosmic Power / Bulk Up / Calm Mind / Dragon Dance: with Simple, -10 if EITHER is already +3 or more;
    otherwise -10 if the first is at +6, -8 if only the second is."""
    if _ai_ability(a) == "SIMPLE":
        return -10 if (a.get(first, 0) > 2 or a.get(second, 0) > 2) else 0
    if a.get(first, 0) == 6:
        return -10
    return -8 if a.get(second, 0) == 6 else 0


def _bh_cosmic_power(c): return _bc_paired_boost(c.a, "def_stage", "spd_stage")
def _bh_bulk_up(c): return _bc_paired_boost(c.a, "atk_stage", "def_stage")
def _bh_calm_mind(c): return _bc_paired_boost(c.a, "spa_stage", "spd_stage")


def _bh_dragon_dance(c):
    if c.b.get("trick_room", 0) > 0:
        return -10
    return _bc_paired_boost(c.a, "atk_stage", "spe_stage")


def _bh_camouflage(c): return -10 if c.a.get("camouflaged") else 0
def _bh_gravity(c): return -10 if c.b.get("gravity", 0) > 0 else 0
def _bh_miracle_eye(c): return -10 if c.d.get("miracle_eye") else 0


def _bc_party_wounded(c):
    """IfAnyPartyMemberIsWounded: any party member other than the user's own slot not at full HP (fainted included)."""
    return any(m is not c.a and m.get("hp", 0) != m.get("max_hp", m.get("hp", 0)) for m in (c.party or ()))


def _bc_party_status(c):
    """IfPartyMemberStatus: an alive party member outside the active slot(s) with a status condition."""
    return any(m is not c.a and m is not c.ally and m.get("hp", 0) > 0 and _bc_status_any(m) for m in (c.party or ()))


def _bc_party_used_pp(c):
    for m in (c.party or ()):
        if m is c.a:
            continue
        for mn in m.get("moves", []):
            if m.get("move_pp", {}).get(mn) != get_move_data_by_name(mn).get("pp"):
                return True
    return False


def _bh_healing_wish(c):
    score = -20
    if c.att_alive == 0:
        return score - 10
    if _bc_party_status(c) or _bc_party_wounded(c):
        return score
    return score - 10


def _bh_lunar_dance(c):
    score = -20
    if c.att_alive == 0:
        return score - 10
    if _bc_party_wounded(c) or _bc_party_status(c) or _bc_party_used_pp(c):
        return score
    return score - 10


def _bh_natural_gift(c):
    if c.a.get("item") not in BASIC_NATURAL_GIFT_BERRIES:
        return -10
    return -10 if _bc_immune(c) else 0


def _bh_tailwind(c):
    return -10 if (c.b.get("trick_room", 0) > 0 or _bc_side(c, c.a).get("tailwind")) else 0


def _bh_acupressure(c):
    a = c.a
    keys = ("atk_stage", "def_stage", "spe_stage", "spa_stage", "spd_stage", "eva_stage", "acc_stage")
    if _ai_ability(a) == "SIMPLE":
        return -10 if any(a.get(k, 0) > 2 for k in keys) else 0
    return -10 if any(a.get(k, 0) == 6 for k in keys) else 0


def _bh_metal_burst(c):
    """Retail bugs reproduced: the script means to test for Lagging Tail but tests Stall and a held SHINY STONE
    instead; and the target's item is only known to the AI if it has been revealed."""
    a, d = c.a, c.d
    if _bc_immune(c):
        return -10
    if _bc_dab(c) == "STALL" or d.get("ai_known_item") == "ITEM_SHINY_STONE":
        return -10
    if _ai_ability(a) == "STALL" or a.get("item") == "ITEM_SHINY_STONE":
        return 0
    return -10 if _bc_faster(c) else 0


def _bh_embargo(c):
    if c.d.get("embargo_turns", 0) > 0:
        return -10
    return 0        # (the Battle Frontier check that follows can never apply in this simulator)


_BC_FLING_POISON = ("HOLD_EFFECT_PSN_USER", "HOLD_EFFECT_STRENGTHEN_POISON")


def _bh_fling(c):
    a, d = c.a, c.d
    if _bc_immune(c):
        return -10
    item = a.get("item")
    info = get_item_info(item)
    if (info.get("fling_power", 0) or 0) < 10 or _ai_ability(a) == "MULTITYPE":
        return -10
    he = info.get("hold_effect")
    if he in _BC_FLING_POISON:
        d_immune = (_bc_safeguard(d) or _bc_status_any(d) or _ai_ability(a) == "POISON_HEAL"
                    or bool(_bc_types(d) & {"TYPE_POISON", "TYPE_STEEL"})
                    or _bc_dab(c) in ("IMMUNITY", "POISON_HEAL", "MAGIC_GUARD"))
        if not d_immune:
            return 0
        if (_bc_safeguard(a) or _bc_status_any(a) or bool(_bc_types(a) & {"TYPE_POISON", "TYPE_STEEL"})
                or _ai_ability(a) in ("KLUTZ", "IMMUNITY", "POISON_HEAL", "MAGIC_GUARD", "GUTS")):
            return -5
        return 3
    if he == "HOLD_EFFECT_BRN_USER":
        d_immune = (_bc_safeguard(d) or _bc_status_any(d) or "TYPE_FIRE" in _bc_types(d)
                    or _bc_dab(c) in ("MAGIC_GUARD", "WATER_VEIL"))
        if not d_immune:
            return 0
        if (_bc_safeguard(a) or _bc_status_any(a) or "TYPE_FIRE" in _bc_types(a)
                or _ai_ability(a) in ("KLUTZ", "MAGIC_GUARD", "WATER_VEIL", "GUTS")):
            return -5
        return 3
    if he == "HOLD_EFFECT_PIKA_SPATK_UP":
        return -5 if (_bc_safeguard(d) or _bc_status_any(d) or _bc_dab(c) == "LIMBER") else 0
    return 0


def _bh_psycho_shift(c):
    a, d = c.a, c.d
    if not _bc_status_any(a) or _bc_status_any(d) or _bc_safeguard(d):
        return -10
    st = a.get("status")
    if st in ("POISON", "TOXIC"):
        if (_ai_ability(a) == "POISON_HEAL" or bool(_bc_types(d) & {"TYPE_POISON", "TYPE_STEEL"})
                or _bc_dab(c) in ("IMMUNITY", "POISON_HEAL", "MAGIC_GUARD")):
            return -10
    elif st == "BURN":
        if "TYPE_FIRE" in _bc_types(d) or _bc_dab(c) in ("MAGIC_GUARD", "WATER_VEIL"):
            return -10
    elif st == "PARALYSIS":
        if _bc_dab(c) == "LIMBER":
            return -10
    return 0


def _bh_heal_block(c): return -10 if c.d.get("heal_block_turns", 0) > 0 else 0
def _bh_power_trick(c): return -10 if c.a.get("power_trick") else 0


def _bh_gastro_acid(c):
    d = c.d
    if d.get("ability_suppressed"):
        return -10
    return -10 if _bc_dab(c) in ("MULTITYPE", "TRUANT", "SLOW_START", "STENCH", "RUN_AWAY", "PICKUP", "HONEY_GATHER") else 0


def _bh_lucky_chant(c): return -10 if _bc_side(c, c.a).get("lucky_chant") else 0


def _bh_copycat(c):
    if c.b.get("turn", 1) - 1 != 0:
        return 0
    return -10 if _bc_faster(c) else 0


def _bh_power_swap(c):
    a, d = c.a, c.d
    return -10 if (d.get("atk_stage", 0) - a.get("atk_stage", 0) < 1 and d.get("spa_stage", 0) - a.get("spa_stage", 0) < 1) else 0


def _bh_guard_swap(c):
    a, d = c.a, c.d
    return -10 if (d.get("def_stage", 0) - a.get("def_stage", 0) < 1 and d.get("spd_stage", 0) - a.get("spd_stage", 0) < 1) else 0


def _bh_last_resort(c):
    """IfCanUseLastResort: knows more than one move and has used every OTHER one since switching in."""
    a = c.a
    known = [m for m in a.get("moves", []) if m]
    others = [m for m in known if m != c.name]
    used = a.get("moves_used_this_stay") or ()
    return 0 if (len(known) > 1 and all(m in used for m in others)) else -10


def _bh_worry_seed(c):
    d = c.d
    if _bc_dab(c) in ("TRUANT", "INSOMNIA", "VITAL_SPIRIT", "MULTITYPE"):
        return -10
    if d.get("status") != "SLEEP":
        return 0
    seen = _ai_defender_known_moves(d)
    return 0 if ("MOVE_SLEEP_TALK" in seen or "MOVE_SNORE" in seen) else -10


def _bh_toxic_spikes(c):
    return -10 if (_bc_side(c, c.d).get("toxic_spikes", 0) == 2 or c.dfn_alive == 0) else 0


def _bh_aqua_ring(c): return -10 if c.a.get("aqua_ring") else 0


def _bh_magnet_rise(c):
    a = c.a
    if a.get("magnet_rise_turns", 0) > 0 or _ai_ability(a) == "LEVITATE" or "TYPE_FLYING" in _bc_types(a):
        return -10
    return 0


def _bh_defog(c):
    d = c.d
    if d.get("eva_stage", 0) != -6:
        return 0
    side = _bc_side(c, d)
    if side.get("light_screen") or side.get("reflect") or c.b.get("weather") == "DEEP_FOG":
        return 0
    if c.dfn_alive == 0:
        return -10
    return 0 if (side.get("spikes") or side.get("stealth_rock") or side.get("toxic_spikes")) else -10


def _bh_trick_room(c):
    cmp_ = _speed_compare(c.a, c.d, c.b)
    return -10 if cmp_ in ("FASTER", "TIE") else 0       # ties count as faster; both outcomes of the real coin flip score -10


def _bh_captivate(c):
    a, d = c.a, c.d
    if _ai_ability(a) != "MOLD_BREAKER" and _bc_dab(c) in ("OBLIVIOUS", "CLEAR_BODY", "WHITE_SMOKE"):
        return -10
    ga, gd = a.get("gender", "GENDERLESS"), d.get("gender", "GENDERLESS")
    if not ((ga == "MALE" and gd == "FEMALE") or (ga == "FEMALE" and gd == "MALE")):
        return -10
    return -10 if d.get("spa_stage", 0) == -6 else 0


def _bh_stealth_rock(c):
    return -10 if (_bc_side(c, c.d).get("stealth_rock") or c.dfn_alive == 0) else 0


def _bh_flee(c): return -10


BASIC_HANDLERS = {
    "Basic_CheckCannotSleep": _bh_cannot_sleep, "Basic_CheckCannotExplode": _bh_cannot_explode,
    "Basic_CheckDreamEater": _bh_dream_eater, "Basic_CheckHighStatStage_Attack": _bh_high_attack,
    "Basic_CheckHighStatStage_Defense": _bh_high_defense, "Basic_CheckHighStatStage_Speed": _bh_high_speed,
    "Basic_CheckHighStatStage_SpAttack": _bh_high_spattack, "Basic_CheckHighStatStage_SpDefense": _bh_high_spdefense,
    "Basic_CheckHighStatStage_Accuracy": _bh_high_accuracy, "Basic_CheckHighStatStage_Evasion": _bh_high_evasion,
    "Basic_CheckLowStatStage_Attack": _bh_low_attack, "Basic_CheckLowStatStage_Defense": _bh_low_defense,
    "Basic_CheckLowStatStage_Speed": _bh_low_speed, "Basic_CheckLowStatStage_SpAttack": _bh_low_spattack,
    "Basic_CheckLowStatStage_SpDefense": _bh_low_spdefense, "Basic_CheckLowStatStage_Accuracy": _bh_low_accuracy,
    "Basic_CheckLowStatStage_Evasion": _bh_low_evasion, "Basic_CheckStatStageImbalance": _bh_stat_imbalance,
    "Basic_CheckNonStandardDamageOrChargeTurn": _bh_nonstandard_damage, "Basic_CheckCanForceSwitch": _bh_can_force_switch,
    "Basic_CheckCanRecoverHP": _bh_can_recover_hp, "Basic_CheckCannotPoison": _bh_cannot_poison,
    "Basic_CheckAlreadyUnderLightScreen": _bh_light_screen, "Basic_CheckOHKOWouldFail": _bh_ohko,
    "Basic_CheckAlreadyUnderMist": _bh_mist, "Basic_CheckAlreadyPumpedUp": _bh_pumped_up,
    "Basic_CheckCannotConfuse": _bh_cannot_confuse, "Basic_CheckAlreadyUnderReflect": _bh_reflect,
    "Basic_CheckCannotParalyze": _bh_cannot_paralyze, "Basic_CheckCannotSubstitute": _bh_cannot_substitute,
    "Basic_CheckCannotLeechSeed": _bh_cannot_leech_seed, "Basic_CheckCannotDisable": _bh_cannot_disable,
    "Basic_CheckCannotEncore": _bh_cannot_encore, "Basic_CheckAttackerAsleep": _bh_attacker_asleep,
    "Basic_CheckLockOn": _bh_lock_on, "Basic_CheckMeanLook": _bh_mean_look, "Basic_CheckNightmare": _bh_nightmare,
    "Basic_CheckCurse": _bh_curse, "Basic_CheckSpikes": _bh_spikes, "Basic_CheckForesight": _bh_foresight,
    "Basic_CheckPerishSong": _bh_perish_song, "Basic_CheckSandstorm": _bh_sandstorm,
    "Basic_CheckCannotAttract": _bh_cannot_attract, "Basic_CheckAlreadyUnderSafeguard": _bh_safeguard,
    "Basic_CheckMagnitude": _bh_magnitude, "Basic_CheckBatonPass": _bh_baton_pass, "Basic_CheckRainDance": _bh_rain_dance,
    "Basic_CheckSunnyDay": _bh_sunny_day, "Basic_CheckBellyDrum": _bh_belly_drum, "Basic_CheckFutureSight": _bh_future_sight,
    "ScoreMinus10": _bh_flee, "Basic_CheckFirstTurnInBattle": _bh_first_turn, "Basic_CheckMaxStockpile": _bh_max_stockpile,
    "Basic_CheckCanSpitUpOrSwallow": _bh_spit_up_or_swallow, "Basic_CheckHail": _bh_hail, "Basic_CheckTorment": _bh_torment,
    "Basic_CheckCannotBurn": _bh_cannot_burn, "Basic_CheckMemento": _bh_memento, "Basic_CheckHelpingHand": _bh_helping_hand,
    "Basic_CheckCanRemoveItem": _bh_can_remove_item, "Basic_CheckAlreadyIngrained": _bh_ingrain,
    "Basic_CheckCanRecycle": _bh_recycle, "Basic_CheckCanImprison": _bh_imprison, "Basic_CheckCanRefreshStatus": _bh_refresh,
    "Basic_CheckCanMudSport": _bh_mud_sport, "Basic_CheckTickle": _bh_tickle, "Basic_CheckCosmicPower": _bh_cosmic_power,
    "Basic_CheckBulkUp": _bh_bulk_up, "Basic_CheckWaterSport": _bh_water_sport, "Basic_CheckCalmMind": _bh_calm_mind,
    "Basic_CheckDragonDance": _bh_dragon_dance, "Basic_CheckCamouflage": _bh_camouflage,
    "Basic_CheckGravityActive": _bh_gravity, "Basic_CheckMiracleEye": _bh_miracle_eye, "Basic_CheckHealingWish": _bh_healing_wish,
    "Basic_CheckNaturalGift": _bh_natural_gift, "Basic_CheckTailwind": _bh_tailwind, "Basic_CheckAcupressure": _bh_acupressure,
    "Basic_CheckMetalBurst": _bh_metal_burst, "Basic_CheckEmbargo": _bh_embargo, "Basic_CheckFling": _bh_fling,
    "Basic_CheckCanPsychoShift": _bh_psycho_shift, "Basic_CheckHealBlock": _bh_heal_block,
    "Basic_CheckPowerTrick": _bh_power_trick, "Basic_CheckGastroAcid": _bh_gastro_acid, "Basic_CheckLuckyChant": _bh_lucky_chant,
    "Basic_CheckCopycat": _bh_copycat, "Basic_CheckPowerSwap": _bh_power_swap, "Basic_CheckGuardSwap": _bh_guard_swap,
    "Basic_CheckLastResort": _bh_last_resort, "Basic_CheckWorrySeed": _bh_worry_seed, "Basic_CheckToxicSpikes": _bh_toxic_spikes,
    "Basic_CheckAquaRing": _bh_aqua_ring, "Basic_CheckMagnetRise": _bh_magnet_rise, "Basic_CheckDefog": _bh_defog,
    "Basic_CheckTrickRoom": _bh_trick_room, "Basic_CheckCaptivate": _bh_captivate, "Basic_CheckStealthRock": _bh_stealth_rock,
    "Basic_CheckLunarDance": _bh_lunar_dance,
}


def basic_flag_score_with_party(move_name, move, attacker, defender, bstate, rng,
                                 attacker_other_alive=0, defender_other_alive=0, attacker_party=None, ally=None):
    """Faithful port of Basic_Main: the entry section (see _basic_entry_checks), then Basic_ScoreMoveEffect's
    dispatch on the move's real effect. attacker_other_alive / defender_other_alive are CountAlivePartyBattlers
    for each side; attacker_party (and the active ally in doubles) feed the party-wide scans."""
    entry = {}
    early = _basic_entry_checks(move_name, move, attacker, defender, bstate, rng, entry)
    if early is not None:
        return early
    label = BASIC_DISPATCH.get(_real_effect(move_name))
    if label is None:
        return 0
    ctx = _BC(move_name, move, attacker, defender, bstate, attacker_other_alive, defender_other_alive, attacker_party, ally, rng)
    ctx.loaded = entry.get("loaded")
    return BASIC_HANDLERS[label](ctx)


def basic_flag_score(move_name, move, attacker, defender, bstate, rng):
    """basic_flag_score_with_party for a context with no party information (both sides count as on their last
    Pokemon)."""
    return basic_flag_score_with_party(move_name, move, attacker, defender, bstate, rng)


def _basic_fling_poison(attacker, defender):
    def target_immune():
        if defender.get("safeguard", 0) > 0:
            return False
        if defender.get("status", "NONE") != "NONE":
            return False
        if has_ability(attacker, "POISON_HEAL"):
            return False
        if any(t in defender.get("types", []) for t in ("TYPE_POISON", "TYPE_STEEL")):
            return False
        if has_ability(defender, "IMMUNITY") or has_ability(defender, "POISON_HEAL") or has_ability(defender, "MAGIC_GUARD"):
            return False
        return True
    if not target_immune():
        return 0
    if defender.get("safeguard", 0) > 0 or defender.get("status", "NONE") != "NONE" or \
            any(t in attacker.get("types", []) for t in ("TYPE_POISON", "TYPE_STEEL")) or \
            has_ability(attacker, "KLUTZ") or has_ability(attacker, "IMMUNITY") or \
            has_ability(attacker, "POISON_HEAL") or has_ability(attacker, "MAGIC_GUARD") or has_ability(attacker, "GUTS"):
        return -5
    return 3


def _basic_fling_burn(attacker, defender):
    def target_immune():
        if defender.get("safeguard", 0) > 0:
            return False
        if defender.get("status", "NONE") != "NONE":
            return False
        if "TYPE_FIRE" in defender.get("types", []):
            return False
        if has_ability(defender, "MAGIC_GUARD") or has_ability(defender, "WATER_VEIL"):
            return False
        return True
    if not target_immune():
        return 0
    if defender.get("safeguard", 0) > 0 or defender.get("status", "NONE") != "NONE" or \
            "TYPE_FIRE" in attacker.get("types", []) or has_ability(attacker, "KLUTZ") or \
            has_ability(attacker, "MAGIC_GUARD") or has_ability(attacker, "WATER_VEIL") or has_ability(attacker, "GUTS"):
        return -5
    return 3


def _basic_fling_paralyze(defender):
    if defender.get("safeguard", 0) > 0 or defender.get("status", "NONE") != "NONE" or has_ability(defender, "LIMBER"):
        return -5
    return 0


def _basic_stat_stage_imbalance(attacker, defender):
    for k in ("atk_stage", "def_stage", "spe_stage", "spa_stage", "spd_stage", "acc_stage", "eva_stage"):
        if attacker.get(k, 0) < 0 or defender.get(k, 0) > 0:
            return 0
    return -10





# ============================================================
# AI SCORING: EVALUATE ATTACK FLAG
# ============================================================
# Real Gen4 AI move-effect category tables, ported verbatim from
# trainer_ai.c's sNoDamageCalcMoveEffects/sAltPowerMoveEffects (cross-
# referenced against the real move data to resolve each BATTLE_EFFECT_
# constant to the actual move name(s) that use it). These feed
# flag_move_damage_score below, itself a faithful port of the real
# AICmd_FlagMoveDamageScore command - used by several AI scripts this
# file is porting from the real decompiled source (Basic, EvalAttack,
# PrioritizeExtremes, BatonPass, TagStrategy all call it).
AI_NO_DAMAGE_CALC_MOVES = {
    "MOVE_RAZOR_WIND", "MOVE_HYPER_BEAM", "MOVE_SOLAR_BEAM", "MOVE_SELFDESTRUCT", "MOVE_SKULL_BASH",
    "MOVE_DREAM_EATER", "MOVE_SKY_ATTACK", "MOVE_EXPLOSION", "MOVE_SPIT_UP", "MOVE_FOCUS_PUNCH",
    "MOVE_SUPERPOWER", "MOVE_ERUPTION", "MOVE_BLAST_BURN", "MOVE_HYDRO_CANNON", "MOVE_WATER_SPOUT",
    "MOVE_FRENZY_PLANT", "MOVE_SUCKER_PUNCH", "MOVE_GIGA_IMPACT", "MOVE_ROCK_WRECKER", "MOVE_HEAD_SMASH",
    "MOVE_ROAR_OF_TIME",
}
AI_ALT_POWER_MOVES = {
    "MOVE_SONIC_BOOM", "MOVE_LOW_KICK", "MOVE_SEISMIC_TOSS", "MOVE_DRAGON_RAGE", "MOVE_NIGHT_SHADE",
    "MOVE_PSYWAVE", "MOVE_RETURN", "MOVE_FRUSTRATION", "MOVE_HIDDEN_POWER", "MOVE_GYRO_BALL",
    "MOVE_NATURAL_GIFT", "MOVE_GRASS_KNOT", "MOVE_JUDGMENT",
}


def flag_move_damage_score(move_name, move, all_move_damages):
    """Faithful port of AICmd_FlagMoveDamageScore: returns
    'AI_MOVE_IS_HIGHEST_DAMAGE', 'AI_NOT_HIGHEST_DAMAGE', or
    'AI_NO_COMPARISON_MADE' for move_name, exactly matching the real
    three-way result other AI scripts branch on.

    The real condition for actually comparing damage at all is (move's
    effect is an alt-power one) OR (power > 1 AND effect is NOT a
    no-damage-calc one) - notably NOT simply "is this a damaging move":
    an alt-power move (Hidden Power, Return, Seismic Toss, etc.) always
    gets compared regardless of its listed power, while a move in the
    no-damage-calc list (Explosion, Rest's cousin Dream Eater, a 2-turn
    charge move, Sucker Punch, etc.) never does, EVEN THOUGH most of
    those still have power > 1 - unless it's also alt-power (none
    currently are both). Anything else with power <= 1 (status moves)
    also gets no comparison. all_move_damages is a name-keyed dict of
    every currently-usable move's estimated damage this same turn."""
    # The gate reads the RAW move-table power (MOVE_DATA(...).power), not the simulator's effective/computed
    # power: Magnitude, Flail, Reversal, Punishment, Wring Out... are power 1 there, so they are never compared.
    if _basic_move_is_damage_comparable(move_name):
        this_damage = all_move_damages.get(move_name, 0)
        if all(this_damage >= d for d in all_move_damages.values()):
            return "AI_MOVE_IS_HIGHEST_DAMAGE"
        return "AI_NOT_HIGHEST_DAMAGE"
    return "AI_NO_COMPARISON_MADE"


AI_PRIORITY_1_EFFECT_MOVES = {
    # BATTLE_EFFECT_PRIORITY_1 - checked by move EFFECT, not the move's
    # actual priority value. Notably includes Extreme Speed despite its
    # real +2 priority, since the AI only looks at this effect tag.
    "MOVE_QUICK_ATTACK", "MOVE_MACH_PUNCH", "MOVE_EXTREME_SPEED", "MOVE_VACUUM_WAVE",
    "MOVE_BULLET_PUNCH", "MOVE_ICE_SHARD", "MOVE_SHADOW_SNEAK", "MOVE_AQUA_JET",
}
AI_HIT_IN_3_TURNS_MOVES = {"MOVE_FUTURE_SIGHT", "MOVE_DOOM_DESIRE"}
AI_HALVE_DEFENSE_MOVES = {"MOVE_SELFDESTRUCT", "MOVE_EXPLOSION"}
AI_DEPRIORITIZED_KILL_MOVES = {"MOVE_FOCUS_PUNCH", "MOVE_SUCKER_PUNCH"} | AI_HIT_IN_3_TURNS_MOVES


def evaluate_attack_flag_score(move_name, move, attacker, defender, bstate, rng, all_move_damages, is_partner_target):
    """Faithful port of EvalAttack_Main, including its exact control
    flow (not just its individual score adjustments):

    - Ignored entirely against a partner target.
    - "Kills" can only be true if flag_move_damage_score doesn't return
      AI_NO_COMPARISON_MADE for this move - Focus Punch/Sucker Punch can
      NEVER register as a kill for this purpose (the real game's own
      documented quirk: their damage is never even calculated here).
    - If it kills: Explosion/Self-Destruct get nothing at all. Focus
      Punch/Sucker Punch/Future Sight/Doom Desire get +4 only ~33.6% of
      the time (else nothing). A Priority-1-effect move gets +2 AND ALSO
      the usual +4 (they stack, +6 total) - everything else just +4.
    - If it doesn't kill: AI_NOT_HIGHEST_DAMAGE means -1 and STOPS HERE -
      the deprioritize and quad-effective checks below never run for
      that move this pass, a real control-flow detail, not just an
      independent, always-applied penalty. Otherwise (highest damage, or
      no comparison was made at all e.g. a status move), Explosion/Focus
      Punch/Sucker Punch face an ~80% chance of -2, and ANY move that's
      quad-effective (4x) separately has a 68.75% chance of +2."""
    if is_partner_target:
        return 0

    comparison = flag_move_damage_score(move_name, move, all_move_damages)
    dmg, _ = estimate_max_damage(attacker, defender, move, weather_now(bstate), bstate=bstate)
    kills = comparison != "AI_NO_COMPARISON_MADE" and dmg >= defender["hp"]
    # IfMoveEffectivenessEquals applies the type chart to ANY move's type, status moves included (Cotton Spore into
    # Rock/Ground is "quad-effective"), so this cannot come from the damage estimate (which is 1.0 for a status move).
    eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)

    if kills:
        if move_name in AI_HALVE_DEFENSE_MOVES:
            return 0
        if move_name in AI_DEPRIORITIZED_KILL_MOVES:
            if rng.randint(0, 255) < 170:
                return 0
            return 4
        score = 4
        if move_name in AI_PRIORITY_1_EFFECT_MOVES:
            score += 2
        return score

    score = 0
    if comparison == "AI_NOT_HIGHEST_DAMAGE":
        return -1

    if move_name in AI_HALVE_DEFENSE_MOVES or move_name in ("MOVE_FOCUS_PUNCH", "MOVE_SUCKER_PUNCH"):
        if rng.randint(0, 255) >= 51:
            score -= 2

    if eff >= 4.0 and rng.randint(0, 255) >= 80:
        score += 2

    return score


# ============================================================
# AI SCORING: EXPERT FLAG (representative subset - see module docstring)
# ============================================================
_SPEED_STAGE_FRACTIONS = ((10, 40), (10, 35), (10, 30), (10, 25), (10, 20), (10, 15), (10, 10),
                          (15, 10), (20, 10), (25, 10), (30, 10), (35, 10), (40, 10))      # sStatStageBoosts, -6 .. +6
_SPEED_HALVING_ITEM_EFFECTS = frozenset((
    "HOLD_EFFECT_EVS_UP_SPEED_DOWN", "HOLD_EFFECT_SPEED_DOWN_GROUNDED", "HOLD_EFFECT_LVLUP_HP_EV_UP",
    "HOLD_EFFECT_LVLUP_ATK_EV_UP", "HOLD_EFFECT_LVLUP_DEF_EV_UP", "HOLD_EFFECT_LVLUP_SPEED_EV_UP",
    "HOLD_EFFECT_LVLUP_SPATK_EV_UP", "HOLD_EFFECT_LVLUP_SPDEF_EV_UP",
))


def weather_now(bstate):
    """The weather that actually has an effect: Cloud Nine / Air Lock on ANY living mon on the field cancels it (NO_CLOUD_NINE)."""
    weather = (bstate or {}).get("weather", "NONE")
    if weather == "NONE":
        return weather
    getter = (bstate or {}).get("all_actives")
    if getter and any(m is not None and m["hp"] > 0 and ability_of(m) in ("CLOUD_NINE", "AIR_LOCK") for m in getter()):
        return "NONE"
    return weather


def side_ability_count(bstate, mon, ability):
    """BattleSystem_CountAbility(COUNT_ALIVE_BATTLERS_OUR_SIDE): living mons on `mon`'s side (itself included) with the ability;
    ability=None counts every living mon on that side (without a field view it answers 2, i.e. "both up")."""
    getter = (bstate or {}).get("all_actives")
    if not getter or not (bstate or {}).get("side_of"):
        return 2 if ability is None else (1 if has_ability(mon, ability) else 0)
    side = bstate["side_of"](mon)
    return sum(1 for m in getter() if m is not None and m["hp"] > 0 and bstate["side_of"](m) == side and (ability is None or has_ability(m, ability)))


def action_order_swap(a, prio_a, b, prio_b, bstate, rng):
    """BattleSystem_SortMonActionOrder's test: True when `b` must act before `a`. A higher move priority goes first; at equal priority
    it is the literal speed compare (Lagging Tail / Stall last, Trick Room reversed), where an exact tie is a coin flip."""
    if prio_a != prio_b:
        return prio_a < prio_b
    result = _speed_compare(a, b, bstate)
    if result == "SLOWER":
        return True
    return result == "TIE" and rng.random() < 0.5


def order_actions(entries, bstate, rng):
    """The real exchange sort over `entries` = [(mon, priority, payload)], returned in acting order."""
    order = list(entries)
    for i in range(len(order) - 1):
        for j in range(i + 1, len(order)):
            if action_order_swap(order[i][0], order[i][1], order[j][0], order[j][1], bstate, rng):
                order[i], order[j] = order[j], order[i]
    return order


def _ai_effective_speed(mon, bstate):
    """Speed as BattleSystem_CompareBattlerSpeed computes it, in the same INTEGER arithmetic and order: stat stage
    (doubled by Simple) as a fraction, Swift Swim / Chlorophyll in their weather, speed-halving items (Macho Brace,
    Power items, Iron Ball; not hidden by Klutz), Choice Scarf, Quick Powder on Ditto, Quick Feet (x1.5) or paralysis (/4),
    Slow Start (/2 for its first turns), then Tailwind (x2).
    Unburden doubles it once the item it entered with is gone (can_unburden); Cloud Nine / Air Lock cancel the weather terms.
    Not modelled: Quick Claw / Custap Berry (they need the turn's speedRand)."""
    ability = _ai_battler_ability(mon, bstate)
    stage = mon.get("spe_stage", 0)
    if ability == "SIMPLE":
        stage = max(-6, min(6, stage * 2))
    num, den = _SPEED_STAGE_FRACTIONS[max(-6, min(6, stage)) + 6]
    spd = int(mon.get("speed", 100)) * num // den
    weather = weather_now(bstate)
    if (ability == "SWIFT_SWIM" and weather == "RAIN") or (ability == "CHLOROPHYLL" and weather == "SUN"):
        spd *= 2
    if get_item_info(mon.get("item")).get("hold_effect") in _SPEED_HALVING_ITEM_EFFECTS:
        spd //= 2
    item_effect = _ai_battler_item_effect(mon, bstate)
    if item_effect == "HOLD_EFFECT_CHOICE_SPEED":
        spd = spd * 15 // 10
    if item_effect == "HOLD_EFFECT_DITTO_SPEED_UP" and mon.get("species") == "SPECIES_DITTO":
        spd *= 2
    status = mon.get("status", "NONE")
    if ability == "QUICK_FEET" and status not in (None, "", "NONE"):
        spd = spd * 15 // 10
    elif status in ("PARALYSIS", "PARALYZE"):  # the engine stores "PARALYSIS"
        spd //= 4
    if ability == "SLOW_START" and (bstate.get("turn", 1) - 1) - mon.get("entered_turn", 1) < 5:
        spd //= 2
    if ability == "UNBURDEN" and mon.get("can_unburden") and not mon.get("item"):
        spd *= 2                                            # it started holding an item and no longer does
    side_of = bstate.get("side_of")
    if side_of is not None and bstate.get("sides", {}).get(side_of(mon), {}).get("tailwind", 0) > 0:
        spd *= 2
    return spd


def _speed_compare(attacker, defender, bstate):
    """The real script's IfSpeedCompareEqualTo / BattleSystem_CompareBattlerSpeed (Quick Claw ignored, equal priority):
    'FASTER', 'SLOWER', or 'TIE'. Lagging Tail / Full Incense holders and Stall users move last (both -> the slower one
    of the two goes first), otherwise the faster mon goes first, reversed under Trick Room. A TIE is where the real
    compare flips a coin (the callers do that, so the draw order stays theirs)."""
    a_spd = _ai_effective_speed(attacker, bstate)
    d_spd = _ai_effective_speed(defender, bstate)
    a_lag = _ai_battler_item_effect(attacker, bstate) == "HOLD_EFFECT_PRIORITY_DOWN"
    d_lag = _ai_battler_item_effect(defender, bstate) == "HOLD_EFFECT_PRIORITY_DOWN"
    a_stall = _ai_battler_ability(attacker, bstate) == "STALL"
    d_stall = _ai_battler_ability(defender, bstate) == "STALL"
    if a_lag and d_lag or (not a_lag and not d_lag and a_stall and d_stall):
        reverse = True
    elif a_lag != d_lag:
        return "SLOWER" if a_lag else "FASTER"
    elif a_stall != d_stall:
        return "SLOWER" if a_stall else "FASTER"
    else:
        reverse = bstate.get("trick_room", 0) > 0
    if reverse:
        a_spd, d_spd = -a_spd, -d_spd
    if a_spd > d_spd:
        return "FASTER"
    if a_spd < d_spd:
        return "SLOWER"
    return "TIE"


def ai_hp_percent(mon):
    """Faithful helper for AICmd_IfHPPercent*: the real AI computes
    `curHP * 100 / maxHP` in u32 arithmetic, i.e. an integer floor - not
    a float percentage. This matters at every threshold: a mon at 50.5%
    HP reads as 50, so `IfHPPercentGreaterThan 50` does NOT fire."""
    return (mon["hp"] * 100) // max(1, mon.get("max_hp", mon["hp"]))


def _ai_hp_is_zero(mon):
    """`IfHPPercentEqualTo <battler>, 0`: true for an absent/fainted
    battler, but ALSO for a live one under 1% HP (e.g. 1/200), which the
    real AI treats as gone."""
    return mon is None or ai_hp_percent(mon) == 0


def _ai_skip(rng, n):
    """`IfRandomLessThan N, <label>`: an 8-bit roll (0-255) strictly below
    N takes the jump, which in every Expert handler skips the modifier
    that follows. So the modifier applies with probability (256-N)/256."""
    return rng.randint(0, 255) < n


def _real_effect(move_name):
    """The real BATTLE_EFFECT_* tag of a move, straight from moves_db.json.
    Expert_Main dispatches on this, not on this file's own effect tags."""
    raw = _MOVES_BY_NAME.get(move_name)
    if not raw:
        return None
    eff = raw.get("effect")
    return eff.get("type") if isinstance(eff, dict) else eff


def _last_move_power_class(mon):
    """Faithful helper for LoadBattlerPreviousMove + LoadPowerOfLoadedMove /
    LoadDefenderLastUsedMoveClass: reads the RAW move-table power and class
    of the mon's last-used move. With no previous move the real game holds
    MOVE_NONE, which is power 0 / CLASS_PHYSICAL."""
    raw = _MOVES_BY_NAME.get(mon.get("last_move_used")) if mon.get("last_move_used") else None
    if not raw:
        return 0, "CLASS_PHYSICAL"
    return (raw.get("power", 0) or 0), raw.get("class", "CLASS_PHYSICAL")


AI_MIRROR_MOVE_TABLE = {
    "MOVE_SLEEP_POWDER", "MOVE_LOVELY_KISS", "MOVE_SPORE", "MOVE_HYPNOSIS", "MOVE_SING", "MOVE_GRASS_WHISTLE",
    "MOVE_SHADOW_PUNCH", "MOVE_SAND_ATTACK", "MOVE_SMOKE_SCREEN", "MOVE_TOXIC", "MOVE_GUILLOTINE",
    "MOVE_HORN_DRILL", "MOVE_FISSURE", "MOVE_SHEER_COLD", "MOVE_CROSS_CHOP", "MOVE_AEROBLAST",
    "MOVE_CONFUSE_RAY", "MOVE_SWEET_KISS", "MOVE_SCREECH", "MOVE_COTTON_SPORE", "MOVE_SCARY_FACE",
    "MOVE_FAKE_TEARS", "MOVE_METAL_SOUND", "MOVE_THUNDER_WAVE", "MOVE_GLARE", "MOVE_POISON_POWDER",
    "MOVE_SHADOW_BALL", "MOVE_DYNAMIC_PUNCH", "MOVE_HYPER_BEAM", "MOVE_EXTREME_SPEED", "MOVE_THIEF",
    "MOVE_COVET", "MOVE_ATTRACT", "MOVE_SWAGGER", "MOVE_TORMENT", "MOVE_FLATTER", "MOVE_TRICK",
    "MOVE_SUPERPOWER", "MOVE_SKILL_SWAP", "MOVE_PSYCHO_SHIFT", "MOVE_POWER_SWAP", "MOVE_GUARD_SWAP",
    "MOVE_SUCKER_PUNCH", "MOVE_HEART_SWAP", "MOVE_SWITCHEROO", "MOVE_CAPTIVATE", "MOVE_DARK_VOID",
}


def _ai_move_effectiveness(move_type, attacker, defender, bstate):
    """IfMoveEffectivenessEquals' view of a matchup (0.0 immune, 0.25, 0.5,
    1.0, 2.0, 4.0): BattleSystem_ApplyTypeChart's pure TYPE chart, which is
    NOT the same as real damage. Notably a Levitating or Magnet-Risen
    defender takes the Ground chart entirely SKIPPED - the AI sees a plain
    neutral matchup, never an immunity - and Wonder Guard never reads as
    an immunity here either. Foresight/Scrappy drop the Ghost immunity to
    Normal/Fighting, Miracle Eye drops Dark's immunity to Psychic, Gravity
    drops Flying's immunity to Ground, and Normalize forces Normal type."""
    if has_ability(attacker, "NORMALIZE"):
        move_type = "TYPE_NORMAL"
    gravity = bstate.get("gravity", 0) > 0
    if move_type == "TYPE_GROUND" and not gravity:
        if has_ability(defender, "LEVITATE") and not has_ability(attacker, "MOLD_BREAKER"):
            return 1.0
        if defender.get("magnet_rise_turns", 0) > 0 and not defender.get("ingrain"):
            return 1.0
    types = [t for t in (defender.get("type1"), defender.get("type2")) if t]
    if gravity and move_type == "TYPE_GROUND":
        types = [t for t in types if t != "TYPE_FLYING"]
    if move_type in ("TYPE_NORMAL", "TYPE_FIGHTING") and (defender.get("foresight") or has_ability(attacker, "SCRAPPY")):
        types = [t for t in types if t != "TYPE_GHOST"]
    if move_type == "TYPE_PSYCHIC" and defender.get("miracle_eye"):
        types = [t for t in types if t != "TYPE_DARK"]
    return type_effectiveness_raw(move_type, types)


def _expert_status_sleep(attacker):
    """Expert_StatusSleep: if the attacker itself knows a move that
    needs the target asleep (Dream Eater or Nightmare's effect), 50%
    chance of +1."""
    return any(
        _real_effect(m) in ("BATTLE_EFFECT_RECOVER_DAMAGE_SLEEP", "BATTLE_EFFECT_STATUS_NIGHTMARE")
        for m in attacker.get("moves", [])
    )


def expert_status_sleep_score(attacker, rng):
    if not _expert_status_sleep(attacker):
        return 0
    return 0 if rng.randint(0, 255) < 128 else 1


def expert_drain_move_score(move_type, attacker, defender, bstate, rng):
    """Expert_DrainMove: if the move is resisted, quarter-resisted, or
    outright immune, ~80.5% (206/256) chance of -3."""
    eff = _ai_move_effectiveness(move_type, attacker, defender, bstate)
    if eff not in (0.0, 0.5, 0.25):
        return 0
    return 0 if _ai_skip(rng, 50) else -3


def expert_explosion_score(attacker, defender, bstate, rng):
    """Expert_Explosion (Explosion/Self-Destruct, and Memento via the
    dispatch table).

    Control flow reproduced exactly, including that the medium-HP block
    FALLS THROUGH into the low-HP block: at <= 30% HP both apply
    independently (50% of +1, then ~80.5% of another +1)."""
    score = 0
    eva = defender.get("eva_stage", 0)
    if eva >= 1:                                   # raw >= 7
        score -= 1
        if eva >= 4 and not _ai_skip(rng, 128):    # raw >= 10
            score -= 1

    hp = ai_hp_percent(attacker)
    # CheckUserHighHP
    if hp >= 80 and _speed_compare(attacker, defender, bstate) != "SLOWER":
        if _ai_skip(rng, 50):
            return score
        return score - 3                           # GoTo ScoreMinus3 (terminates)
    # CheckUserMediumHP
    if hp > 50:                                    # -> TryScoreMinus1
        if _ai_skip(rng, 50):
            return score
        return score - 1
    if not _ai_skip(rng, 128):
        score += 1
    # CheckUserLowHP (reached by fallthrough from the block above)
    if hp > 30:
        return score
    if _ai_skip(rng, 50):
        return score
    return score + 1


def expert_dream_eater_score(move_type, attacker, defender, bstate, rng):
    eff = _ai_move_effectiveness(move_type, attacker, defender, bstate)
    if eff in (0.0, 0.25, 0.5):
        return -1
    if defender.get("status") == "SLEEP":
        return 0 if _ai_skip(rng, 51) else 3
    return 0


def expert_mirror_move_score(attacker, defender, bstate, rng):
    """Expert_MirrorMove. Faster (or tied) and the target's last move is in
    the table: 50% of +2. Every other case - slower, OR faster but the
    last move is not in the table - lands in TryScoreMinus1: if the last
    move is in the table nothing happens, otherwise ~68.75% of -1."""
    in_table = defender.get("last_move_used") in AI_MIRROR_MOVE_TABLE
    if _speed_compare(attacker, defender, bstate) != "SLOWER" and in_table:
        return 0 if _ai_skip(rng, 128) else 2
    # Expert_MirrorMove_TryScoreMinus1
    if in_table:
        return 0
    return 0 if _ai_skip(rng, 80) else -1


# ---------------- Stat-stage handlers (script.s 1978-2518) ----------------
# Real stat stages are stored raw 0-12 (6 = +0); this file uses -6..+6, so
# `raw < 9` is `stage < 3`, `raw > 3` is `stage > -3`, etc.
def _expert_offense_up(attacker, stage_key, final_roll, rng):
    """Expert_StatusAttackUp / Expert_StatusSpAttackUp (identical except the
    last roll: 40 for Attack, 70 for Sp. Atk)."""
    score = 0
    if attacker.get(stage_key, 0) < 3:                     # raw < 9 -> CheckUserAtMaxHP
        if ai_hp_percent(attacker) == 100 and not _ai_skip(rng, 128):
            score += 2
    elif not _ai_skip(rng, 100):
        score -= 1
    # CheckUserHPRange
    hp = ai_hp_percent(attacker)
    if hp > 70:
        return score
    if hp < 40:
        return score - 2
    if _ai_skip(rng, final_roll):
        return score
    return score - 2


def _expert_defense_up(attacker, defender, stage_key, punished_class, rng):
    """Expert_StatusDefenseUp (punished_class SPECIAL) / Expert_StatusSpDefenseUp
    (PHYSICAL). The last-move logic: power 0 (status, or nothing yet) goes
    straight to UserAtLowHP (one 60/256 roll -> ~76.6% of -2); the punished
    class is always -2; any other damaging class takes the 60 roll and then
    FALLS THROUGH into UserAtLowHP for a second one (~58.6% of -2)."""
    score = 0
    if attacker.get(stage_key, 0) < 3:                     # raw < 9
        if ai_hp_percent(attacker) == 100 and not _ai_skip(rng, 128):
            score += 2
    elif not _ai_skip(rng, 100):
        score -= 1
    # CheckUserHighHP
    hp = ai_hp_percent(attacker)
    if hp >= 70 and _ai_skip(rng, 200):
        return score
    # CheckUserMediumHP
    if hp < 40:
        return score - 2
    power, cls = _last_move_power_class(defender)
    if power != 0:
        if cls == punished_class:
            return score - 2
        if _ai_skip(rng, 60):
            return score
    # UserAtLowHP
    if _ai_skip(rng, 60):
        return score
    return score - 2


def _expert_speed_up(attacker, defender, bstate, rng):
    """Expert_StatusSpeedUp: faster (or tied) -> -3; slower -> ~72.7% of +3."""
    if _speed_compare(attacker, defender, bstate) != "SLOWER":
        return -3
    return 0 if _ai_skip(rng, 70) else 3


def _expert_speed_down(attacker, defender, bstate, rng):
    """Expert_StatusSpeedDown: slower -> ~72.7% of +2; faster (or tied) -> -3."""
    if _speed_compare(attacker, defender, bstate) != "SLOWER":
        return -3
    return 0 if _ai_skip(rng, 70) else 2


def _expert_accuracy_up(attacker, rng):
    """Expert_StatusAccuracyUp."""
    score = 0
    if attacker.get("acc_stage", 0) >= 3 and not _ai_skip(rng, 50):    # raw >= 9
        score -= 2
    # TryScoreMinus2 (reached by fallthrough as well as by jump)
    if ai_hp_percent(attacker) > 70:
        return score
    return score - 2


def _expert_evasion_up(attacker, defender, rng):
    """Expert_StatusEvasionUp. Every roll is its own draw, in script order;
    e.g. a Toxic'd target with the user at <= 50% HP needs two rolls
    (80 then 50) to reach +3, ~55.3%."""
    score = 0
    hp = ai_hp_percent(attacker)
    if hp >= 90 and not _ai_skip(rng, 100):
        score += 3
    if attacker.get("eva_stage", 0) >= 3 and not _ai_skip(rng, 128):
        score -= 1
    # CheckEnemyBadlyPoisoned
    if defender.get("status") == "TOXIC":
        if hp > 50:
            if not _ai_skip(rng, 50):
                score += 3
        elif not _ai_skip(rng, 80) and not _ai_skip(rng, 50):
            score += 3
    # CheckEnemySeeded
    if defender.get("leech_seeded") and not _ai_skip(rng, 70):
        score += 3
    # CheckUserIngrained / CheckUserHasAquaRing (Aqua Ring only checked if not Ingrained)
    if attacker.get("ingrain") or attacker.get("aqua_ring"):
        if not _ai_skip(rng, 128):
            score += 2
    # CheckEnemyCursed
    if defender.get("cursed") and not _ai_skip(rng, 70):
        score += 3
    # CheckHPRanges
    if hp > 70:
        return score
    if attacker.get("eva_stage", 0) == 0:
        return score
    if hp < 40 or ai_hp_percent(defender) < 40:
        return score - 2
    if _ai_skip(rng, 70):
        return score
    return score - 2


def _expert_bypass_accuracy(attacker, defender, rng):
    """Expert_BypassAccuracyMove."""
    score = 0
    if defender.get("eva_stage", 0) > 4 or attacker.get("acc_stage", 0) < -4:      # raw > 10 / raw < 2
        score += 1                                                                   # ScorePlus1, then falls into TryScorePlus1
    elif defender.get("eva_stage", 0) > 2 or attacker.get("acc_stage", 0) < -2:    # raw > 8 / raw < 4
        pass                                                                         # TryScorePlus1 only
    else:
        return 0
    if _ai_skip(rng, 100):
        return score
    return score + 1


def _expert_offense_down(attacker, defender, stage_key, punished_class, rng):
    """Expert_StatusAttackDown (punished_class SPECIAL) /
    Expert_StatusSpAttackDown (PHYSICAL)."""
    score = 0
    if defender.get(stage_key, 0) != 0:                    # raw != 6
        score -= 1
        if ai_hp_percent(attacker) <= 90:
            score -= 1
        if defender.get(stage_key, 0) <= -3 and not _ai_skip(rng, 50):    # NOT raw > 3
            score -= 2
    # CheckTargetHP
    if ai_hp_percent(defender) <= 70:
        score -= 2
    # CheckLastUsedMove
    _, cls = _last_move_power_class(defender)
    if cls != punished_class:
        return score
    if _ai_skip(rng, 128):
        return score
    return score - 2


def _expert_defense_down(attacker, defender, stage_key, rng):
    """Expert_StatusDefenseDown / SpDefenseDown / EvasionDown (same shape).
    Enters the 50-roll if the user is below 70% HP, OR the target is
    already at -3 or lower."""
    score = 0
    if ai_hp_percent(attacker) < 70 or defender.get(stage_key, 0) <= -3:
        if not _ai_skip(rng, 50):
            score -= 2
    if ai_hp_percent(defender) <= 70:
        score -= 2
    return score


def _expert_accuracy_down(attacker, defender, rng):
    """Expert_StatusAccuracyDown. Note the real script's final range check
    tests the TARGET's accuracy stage (== +0 ends), despite the comment
    saying attacker - reproduced as written."""
    score = 0
    hp = ai_hp_percent(attacker)
    if hp < 70 or ai_hp_percent(defender) <= 70:
        if not _ai_skip(rng, 100):
            score -= 1
    # CheckUserAccuracy
    if attacker.get("acc_stage", 0) <= -2 and not _ai_skip(rng, 80):      # NOT raw > 4
        score -= 2
    # CheckTargetBadlyPoisoned
    if defender.get("status") == "TOXIC" and not _ai_skip(rng, 70):
        score += 2
    # CheckTargetSeeded
    if defender.get("leech_seeded") and not _ai_skip(rng, 70):
        score += 2
    # CheckUserIngrained / CheckUserHasAquaRing
    if attacker.get("ingrain") or attacker.get("aqua_ring"):
        if not _ai_skip(rng, 128):
            score += 1
    # CheckTargetCursed
    if defender.get("cursed") and not _ai_skip(rng, 70):
        score += 2
    # CheckHPRanges
    if hp > 70:
        return score
    if defender.get("acc_stage", 0) == 0:
        return score
    if hp < 40 or ai_hp_percent(defender) < 40:
        return score - 2
    if _ai_skip(rng, 70):
        return score
    return score - 2


_SPEED_DOWN_ON_HIT_MOVES = ("MOVE_ICY_WIND", "MOVE_ROCK_TOMB", "MOVE_MUD_SHOT")


def _expert_speed_down_on_hit(move_name, move, attacker, defender, bstate, rng):
    """Expert_SpeedDownOnHit: no modifier if the target is immune to or
    resists the move; otherwise ONLY Icy Wind, Rock Tomb and Mud Shot are
    scored (as Speed-lowering status moves)."""
    eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
    if eff in (0.0, 0.25, 0.5):
        return 0
    if move_name in _SPEED_DOWN_ON_HIT_MOVES:
        return _expert_speed_down(attacker, defender, bstate, rng)
    return 0


# ---------------- Batch 2: Haze .. StatusParalyze (script.s 2520-2954) ----------------
def _ai_total_turns(bstate):
    """LoadTurnCount: the real game's totalTurns is 0 on the first turn;
    this file's bstate["turn"] starts at 1."""
    return bstate.get("turn", 1) - 1


def _ai_battler_turn_count(mon, bstate):
    """LoadBattlerTurnCount: totalTurns minus the turn the mon switched in
    (0 on the turn it entered). apply_entry_hazards stamps "entered_turn"."""
    return bstate.get("turn", 1) - mon.get("entered_turn", 1)


def _ai_side_conditions(bstate, mon):
    side_of = bstate.get("side_of")
    sides = bstate.get("sides")
    if side_of is None or not sides:
        return {}
    return sides.get(side_of(mon), {})


def _ai_defender_known_moves(defender):
    """Names of the moves the AI has SEEN the defender use (AI_CONTEXT.battlerMoves,
    filled from movePrevByBattler and cleared on switch-in) - NOT its full moveset."""
    names = set(defender.get("moves_used_this_stay") or ())
    if defender.get("last_move_used"):
        names.add(defender["last_move_used"])
    return names


def _ai_defender_known_effects(defender):
    """Real BATTLE_EFFECT_* set of _ai_defender_known_moves."""
    return {_real_effect(n) for n in _ai_defender_known_moves(defender)}


def _ai_attacker_known_effects(attacker):
    """Real effects of ALL the attacker's own moves (IfMoveEffectKnown, ATTACKER)."""
    return {_real_effect(n) for n in attacker.get("moves", [])}


_STAT_STAGES_GUARDED = ("atk_stage", "def_stage", "spa_stage", "spd_stage")


def _expert_haze(attacker, defender, rng):
    """Expert_Haze. Note the script's asymmetric stat lists, reproduced
    as written: the user's EVASION is checked but not its accuracy in
    the 'discourage' block, and the target's ACCURACY (not evasion) is
    checked for being lowered; the 'encourage' block mirrors that."""
    score = 0
    if (any(attacker.get(k, 0) >= 3 for k in _STAT_STAGES_GUARDED + ("eva_stage",))
            or any(defender.get(k, 0) <= -3 for k in _STAT_STAGES_GUARDED + ("acc_stage",))):
        if not _ai_skip(rng, 50):
            score -= 3
    # CheckToEncourage (always reached)
    if (any(defender.get(k, 0) >= 3 for k in _STAT_STAGES_GUARDED + ("eva_stage",))
            or any(attacker.get(k, 0) <= -3 for k in _STAT_STAGES_GUARDED + ("acc_stage",))):
        if not _ai_skip(rng, 50):
            score += 3
    elif not _ai_skip(rng, 50):
        score -= 1
    return score


def _expert_bide(attacker):
    """Expert_Bide: -2 unless the user's HP > 90%."""
    return 0 if ai_hp_percent(attacker) > 90 else -2


def _expert_force_switch(defender, bstate, rng):
    """Expert_ForceSwitch. When the target has been out for MORE than 3
    turns the script's 75%-block FALLS THROUGH into the 50%-block, so both
    rolls apply (up to +4); otherwise hazards or a +3 stage on the target
    reach the 50% block alone, else -3."""
    score = 0
    if _ai_battler_turn_count(defender, bstate) > 3:
        if not _ai_skip(rng, 64):
            score += 2
    else:
        side = _ai_side_conditions(bstate, defender)
        if not (side.get("spikes", 0) > 0 or side.get("stealth_rock") or side.get("toxic_spikes", 0) > 0
                or any(defender.get(k, 0) >= 3 for k in _STAT_STAGES_GUARDED + ("eva_stage",))):
            return -3
    if _ai_skip(rng, 128):
        return score
    return score + 2


def _expert_conversion(attacker, bstate, rng):
    """Expert_Conversion: -2 when the user is <= 90% HP; after the first
    turn, ~78.1% of another -2 (here the jump target IS the penalty)."""
    score = -2 if ai_hp_percent(attacker) <= 90 else 0
    if _ai_total_turns(bstate) == 0:
        return score
    if _ai_skip(rng, 200):
        return score - 2
    return score


def _expert_recovery(attacker, defender, bstate, rng, score=0):
    """Expert_Recovery (also reached by fallthrough from Expert_Synthesis,
    carrying its -2). A tie in speed counts as 'not slower'."""
    hp = ai_hp_percent(attacker)
    if hp == 100:
        return score - 3
    if _speed_compare(attacker, defender, bstate) != "SLOWER":
        return score - 8
    # CheckHP
    if hp >= 70 and not _ai_skip(rng, 30):
        return score - 3
    # CheckForSnatch -> TryScorePlus2. A target known to have Snatch adds an
    # extra roll (the 100-roll falls through into the 20-roll).
    if "BATTLE_EFFECT_STEAL_STATUS_MOVE" in _ai_defender_known_effects(defender):
        if _ai_skip(rng, 100):
            return score
    if _ai_skip(rng, 20):
        return score
    return score + 2


def _expert_synthesis(attacker, defender, bstate, rng):
    """Expert_Synthesis: Recovery, plus -2 in Hail, Rain or Sandstorm."""
    score = -2 if bstate.get("weather") in ("HAIL", "RAIN", "SANDSTORM") else 0
    return _expert_recovery(attacker, defender, bstate, rng, score)


def _expert_toxic_leech_seed(attacker, defender, rng):
    """Expert_ToxicLeechSeed (Toxic and Leech Seed). The HP checks only run
    if the user knows a damaging move (any raw non-zero power)."""
    score = 0
    moves = attacker.get("moves", [])
    if any((_MOVES_BY_NAME.get(m) or {}).get("power", 0) for m in moves):
        if ai_hp_percent(attacker) <= 50 and not _ai_skip(rng, 50):
            score -= 3
        if ai_hp_percent(defender) <= 50 and not _ai_skip(rng, 50):
            score -= 3
    known = _ai_attacker_known_effects(attacker)
    if ("BATTLE_EFFECT_SP_DEF_UP" in known or "BATTLE_EFFECT_PROTECT" in known) and not _ai_skip(rng, 60):
        score += 2
    return score


def _expert_screen(attacker, defender, punished_class, rng):
    """Expert_LightScreen (SPECIAL) / Expert_Reflect (PHYSICAL)."""
    hp = ai_hp_percent(attacker)
    if hp < 50:
        return -2
    score = 0
    if hp >= 90 and not _ai_skip(rng, 128):
        score += 1
    _, cls = _last_move_power_class(defender)
    if cls != punished_class:
        return score
    if _ai_skip(rng, 64):
        return score
    return score + 1


def _expert_rest(attacker, defender, bstate, rng):
    """Expert_Rest."""
    hp = ai_hp_percent(attacker)
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        if hp >= 60:
            if hp > 70:
                return -3
            if not _ai_skip(rng, 50):
                return -3
    else:
        if hp == 100:
            return -8
        if hp >= 40:
            if hp > 50:
                return -3
            if not _ai_skip(rng, 70):
                return -3
    # CheckForSnatch -> TryScorePlus3 (a Snatch-knowing target adds a 50-roll first)
    if "BATTLE_EFFECT_STEAL_STATUS_MOVE" in _ai_defender_known_effects(defender):
        if _ai_skip(rng, 50):
            return 0
    if _ai_skip(rng, 10):
        return 0
    return 3


def _expert_ohko(rng):
    """Expert_OHKOMove: 25% of +1."""
    return 0 if _ai_skip(rng, 192) else 1


def _expert_super_fang(defender):
    """Expert_SuperFang: -1 when the target is at <= 50% HP."""
    return 0 if ai_hp_percent(defender) > 50 else -1


def _expert_binding_move(defender, rng):
    """Expert_BindingMove (Wrap-likes and Mean Look-likes): 50% of +1 if the
    target is Badly Poisoned, Cursed, Perish Song'd or Infatuated."""
    if not (defender.get("status") == "TOXIC" or defender.get("cursed")
            or defender.get("perish_song", 0) > 0 or defender.get("attracted")):
        return 0
    return 0 if _ai_skip(rng, 128) else 1


def _expert_high_critical(move, attacker, defender, bstate, rng):
    """Expert_HighCritical: super-effective -> 50% of +1; neutral -> a 128
    roll first and then the same 128 roll (25%); resisted/immune -> nothing."""
    eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
    if eff in (0.0, 0.25, 0.5):
        return 0
    if eff not in (2.0, 4.0) and _ai_skip(rng, 128):
        return 0
    return 0 if _ai_skip(rng, 128) else 1


def _expert_status_confuse(defender, rng, score=0):
    """Expert_StatusConfuse (also the tail of Flatter and Swagger)."""
    hp = ai_hp_percent(defender)
    if hp > 70:
        return score
    if not _ai_skip(rng, 128):
        score -= 1
    # CheckHP
    if hp > 50:
        return score
    score -= 1
    if hp > 30:
        return score
    return score - 1


def _expert_flatter(defender, rng):
    """Expert_Flatter: 50% of +1, then Expert_StatusConfuse."""
    score = 0 if _ai_skip(rng, 128) else 1
    return _expert_status_confuse(defender, rng, score)


def _expert_swagger(attacker, defender, bstate, rng):
    """Expert_Swagger: with Psych Up in the moveset, a +3 (or +5 on the
    first turn) - but -5 if the target's Attack is above -3; otherwise
    behaves exactly like Flatter."""
    if "MOVE_PSYCH_UP" not in attacker.get("moves", []):
        return _expert_flatter(defender, rng)
    if defender.get("atk_stage", 0) > -3:                  # raw > 3
        return -5
    return 3 if _ai_total_turns(bstate) != 0 else 5


def _expert_status_poison(attacker, defender):
    """Expert_StatusPoison: -1 if the user is < 50% HP or the target <= 50%."""
    if ai_hp_percent(attacker) < 50 or ai_hp_percent(defender) <= 50:
        return -1
    return 0


def _expert_status_paralyze(attacker, defender, bstate, rng):
    """Expert_StatusParalyze: slower -> ~92.2% of +3; otherwise -1 at <= 70% HP."""
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return 0 if _ai_skip(rng, 20) else 3
    return 0 if ai_hp_percent(attacker) > 70 else -1


# ---------------- Batch 3: VitalThrow .. Spikes (script.s 2956-3606) ----------------
def _ai_has_status(mon):
    """MON_CONDITION_ANY: any non-volatile status (this file stores 'NONE' for none)."""
    return mon.get("status") not in (None, "NONE")


def _ai_protect_chain(mon):
    """LoadProtectChain: 0 unless the mon's LAST move was Protect/Detect/Endure,
    in which case the number of consecutive successful uses."""
    return mon.get("protect_chain", 0) if mon.get("protect_used_last") else 0


_EXPERT_COUNTER_PHYSICAL_TYPES = frozenset((
    "TYPE_NORMAL", "TYPE_FIGHTING", "TYPE_FLYING", "TYPE_POISON", "TYPE_GROUND",
    "TYPE_ROCK", "TYPE_BUG", "TYPE_GHOST", "TYPE_STEEL",
))

# Expert_Encore_EncouragedMoveEffects and Expert_Thief_EncouragedItemEffects,
# extracted straight from script.s (82 and 25 entries).
EXPERT_ENCORE_EFFECTS = frozenset([
    "BATTLE_EFFECT_RECOVER_DAMAGE_SLEEP",
    "BATTLE_EFFECT_ATK_UP",
    "BATTLE_EFFECT_DEF_UP",
    "BATTLE_EFFECT_SPEED_UP",
    "BATTLE_EFFECT_SP_ATK_UP",
    "BATTLE_EFFECT_RESET_STAT_CHANGES",
    "BATTLE_EFFECT_FORCE_SWITCH",
    "BATTLE_EFFECT_CONVERSION",
    "BATTLE_EFFECT_STATUS_BADLY_POISON",
    "BATTLE_EFFECT_SET_LIGHT_SCREEN",
    "BATTLE_EFFECT_REST",
    "BATTLE_EFFECT_HALVE_HP",
    "BATTLE_EFFECT_SP_DEF_UP_2",
    "BATTLE_EFFECT_STATUS_CONFUSE",
    "BATTLE_EFFECT_STATUS_POISON",
    "BATTLE_EFFECT_STATUS_PARALYZE",
    "BATTLE_EFFECT_STATUS_LEECH_SEED",
    "BATTLE_EFFECT_DO_NOTHING",
    "BATTLE_EFFECT_ATK_UP_2",
    "BATTLE_EFFECT_ENCORE",
    "BATTLE_EFFECT_CONVERSION2",
    "BATTLE_EFFECT_NEXT_ATTACK_ALWAYS_HITS",
    "BATTLE_EFFECT_CURE_PARTY_STATUS",
    "BATTLE_EFFECT_PREVENT_ESCAPE",
    "BATTLE_EFFECT_STATUS_NIGHTMARE",
    "BATTLE_EFFECT_PROTECT",
    "BATTLE_EFFECT_SWITCH_ABILITIES",
    "BATTLE_EFFECT_FORESIGHT",
    "BATTLE_EFFECT_ALL_FAINT_3_TURNS",
    "BATTLE_EFFECT_WEATHER_SANDSTORM",
    "BATTLE_EFFECT_SURVIVE_WITH_1_HP",
    "BATTLE_EFFECT_ATK_UP_2_STATUS_CONFUSION",
    "BATTLE_EFFECT_INFATUATE",
    "BATTLE_EFFECT_PREVENT_STATUS",
    "BATTLE_EFFECT_WEATHER_RAIN",
    "BATTLE_EFFECT_WEATHER_SUN",
    "BATTLE_EFFECT_MAX_ATK_LOSE_HALF_MAX_HP",
    "BATTLE_EFFECT_COPY_STAT_CHANGES",
    "BATTLE_EFFECT_HIT_IN_3_TURNS",
    "BATTLE_EFFECT_ALWAYS_FLINCH_FIRST_TURN_ONLY",
    "BATTLE_EFFECT_STOCKPILE",
    "BATTLE_EFFECT_SPIT_UP",
    "BATTLE_EFFECT_SWALLOW",
    "BATTLE_EFFECT_WEATHER_HAIL",
    "BATTLE_EFFECT_TORMENT",
    "BATTLE_EFFECT_STATUS_BURN",
    "BATTLE_EFFECT_MAKE_GLOBAL_TARGET",
    "BATTLE_EFFECT_SP_DEF_UP_DOUBLE_ELECTRIC_POWER",
    "BATTLE_EFFECT_SWITCH_HELD_ITEMS",
    "BATTLE_EFFECT_COPY_ABILITY",
    "BATTLE_EFFECT_GROUND_TRAP_USER_CONTINUOUS_HEAL",
    "BATTLE_EFFECT_RECYCLE",
    "BATTLE_EFFECT_REMOVE_HELD_ITEM",
    "BATTLE_EFFECT_SWITCH_ABILITIES",
    "BATTLE_EFFECT_MAKE_SHARED_MOVES_UNUSEABLE",
    "BATTLE_EFFECT_HEAL_STATUS",
    "BATTLE_EFFECT_REMOVE_ALL_PP_ON_DEFEAT",
    "BATTLE_EFFECT_CONFUSE_ALL",
    "BATTLE_EFFECT_HALVE_ELECTRIC_DAMAGE",
    "BATTLE_EFFECT_HALVE_FIRE_DAMAGE",
    "BATTLE_EFFECT_ATK_SPD_UP",
    "BATTLE_EFFECT_CAMOUFLAGE",
    "BATTLE_EFFECT_GRAVITY",
    "BATTLE_EFFECT_IGNORE_EVATION_REMOVE_DARK_IMMUNE",
    "BATTLE_EFFECT_FAINT_AND_FULL_HEAL_NEXT_MON",
    "BATTLE_EFFECT_NATURAL_GIFT",
    "BATTLE_EFFECT_REMOVE_PROTECT",
    "BATTLE_EFFECT_DOUBLE_SPEED_3_TURNS",
    "BATTLE_EFFECT_RANDOM_STAT_UP_2",
    "BATTLE_EFFECT_FLING",
    "BATTLE_EFFECT_TRANSFER_STATUS",
    "BATTLE_EFFECT_PREVENT_HEALING",
    "BATTLE_EFFECT_SWAP_ATK_DEF",
    "BATTLE_EFFECT_SUPRESS_ABILITY",
    "BATTLE_EFFECT_PREVENT_CRITS",
    "BATTLE_EFFECT_SWAP_ATK_SP_ATK_STAT_CHANGES",
    "BATTLE_EFFECT_SWAP_DEF_SP_DEF_STAT_CHANGES",
    "BATTLE_EFFECT_SET_ABILITY_TO_INSOMNIA",
    "BATTLE_EFFECT_SWAP_STAT_CHANGES",
    "BATTLE_EFFECT_RESTORE_HP_EVERY_TURN",
    "BATTLE_EFFECT_GIVE_GROUND_IMMUNITY",
    "BATTLE_EFFECT_TRICK_ROOM",
])

EXPERT_THIEF_ITEM_EFFECTS = frozenset([
    "HOLD_EFFECT_SLP_RESTORE",
    "HOLD_EFFECT_STATUS_RESTORE",
    "HOLD_EFFECT_HP_RESTORE",
    "HOLD_EFFECT_ACC_REDUCE",
    "HOLD_EFFECT_HP_RESTORE_GRADUAL",
    "HOLD_EFFECT_PIKA_SPATK_UP",
    "HOLD_EFFECT_CUBONE_ATK_UP",
    "HOLD_EFFECT_WEAKEN_SE_FIRE",
    "HOLD_EFFECT_WEAKEN_SE_WATER",
    "HOLD_EFFECT_WEAKEN_SE_ELECTRIC",
    "HOLD_EFFECT_WEAKEN_SE_GRASS",
    "HOLD_EFFECT_WEAKEN_SE_ICE",
    "HOLD_EFFECT_WEAKEN_SE_FIGHT",
    "HOLD_EFFECT_WEAKEN_SE_POISON",
    "HOLD_EFFECT_WEAKEN_SE_GROUND",
    "HOLD_EFFECT_WEAKEN_SE_FLYING",
    "HOLD_EFFECT_WEAKEN_SE_PSYCHIC",
    "HOLD_EFFECT_WEAKEN_SE_BUG",
    "HOLD_EFFECT_WEAKEN_SE_ROCK",
    "HOLD_EFFECT_WEAKEN_SE_GHOST",
    "HOLD_EFFECT_WEAKEN_SE_DRAGON",
    "HOLD_EFFECT_WEAKEN_SE_DARK",
    "HOLD_EFFECT_WEAKEN_SE_STEEL",
    "HOLD_EFFECT_WEAKEN_NORMAL",
    "HOLD_EFFECT_HP_RESTORE_PSN_TYPE",
])



def _expert_vital_throw(attacker, defender, bstate, rng):
    """Expert_VitalThrow: slower or > 60% HP -> nothing; < 40% -> ~80.5% of -1;
    40-60% -> the 180-roll then FALLS THROUGH into the 50-roll (~23.9% of -1)."""
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return 0
    hp = ai_hp_percent(attacker)
    if hp > 60:
        return 0
    if hp >= 40 and _ai_skip(rng, 180):
        return 0
    return 0 if _ai_skip(rng, 50) else -1


def _expert_substitute(attacker, defender, bstate, rng):
    """Expert_Substitute. The target-status checks are keyed off what the
    opponent LAST used: after an ailment-inducing move, +1 at ~60.9% if the
    opponent does NOT currently have that condition (the script jumps on
    IfNot*, despite the source comment saying otherwise) - reproduced as coded."""
    score = 0
    if "MOVE_FOCUS_PUNCH" in attacker.get("moves", []) and not _ai_skip(rng, 96):
        score += 1
    hp = ai_hp_percent(attacker)
    if hp <= 90:
        for _ in range(1 if hp > 70 else 2 if hp > 50 else 3):
            if not _ai_skip(rng, 100):
                score -= 1
    # CheckTargetLastMove
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return score
    last = defender.get("last_move_used")
    effect = _real_effect(last) if last else None
    if effect in ("BATTLE_EFFECT_STATUS_SLEEP", "BATTLE_EFFECT_STATUS_BADLY_POISON", "BATTLE_EFFECT_STATUS_POISON",
                  "BATTLE_EFFECT_STATUS_PARALYZE", "BATTLE_EFFECT_STATUS_BURN"):
        if _ai_has_status(defender):
            return score
    elif effect == "BATTLE_EFFECT_STATUS_CONFUSE":
        if defender.get("confused"):
            return score
    elif effect == "BATTLE_EFFECT_STATUS_LEECH_SEED":
        if defender.get("leech_seeded"):
            return score
    else:
        return score
    # TryScorePlus1
    return score if _ai_skip(rng, 100) else score + 1


def _expert_recharge_turn(move, attacker, defender, bstate, rng):
    """Expert_RechargeTurn (Hyper Beam and friends)."""
    eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
    if eff in (0.0, 0.25, 0.5):
        return -1
    if has_ability(attacker, "TRUANT"):
        return 0 if _ai_skip(rng, 80) else 1
    hp = ai_hp_percent(attacker)
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return 0 if hp < 60 else -1
    return -1 if hp > 40 else 0


def _expert_disable(attacker, defender, bstate, rng):
    """Expert_Disable: slower -> nothing; the target's last move damaging -> +1;
    status/none -> ~60.9% of -1."""
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return 0
    power, _ = _last_move_power_class(defender)
    if power != 0:
        return 1
    return 0 if _ai_skip(rng, 100) else -1


def _expert_counter(attacker, defender, rng):
    """Expert_Counter."""
    if defender.get("status") == "SLEEP" or defender.get("attracted") or defender.get("confused"):
        return -1
    score = 0
    hp = ai_hp_percent(attacker)
    if hp <= 30 and not _ai_skip(rng, 10):
        score -= 1
    if hp <= 50 and not _ai_skip(rng, 100):
        score -= 1
    # CheckLastUsedMove
    if "MOVE_MIRROR_COAT" in attacker.get("moves", []):
        return score if _ai_skip(rng, 100) else score + 4
    power, cls = _last_move_power_class(defender)
    taunted = defender.get("taunt_turns", 0) > 0
    if power != 0:
        if taunted and not _ai_skip(rng, 100):
            score += 1
        if cls != "CLASS_PHYSICAL":
            return score - 1
        return score if _ai_skip(rng, 100) else score + 1
    # TryScorePlus1 (last move was a status move, or none yet)
    if taunted and not _ai_skip(rng, 100):
        score += 1
    if (defender.get("type1") in _EXPERT_COUNTER_PHYSICAL_TYPES
            or defender.get("type2") in _EXPERT_COUNTER_PHYSICAL_TYPES):
        return score
    if _ai_skip(rng, 50):
        return score
    return score if _ai_skip(rng, 100) else score + 4


def _expert_encore(attacker, defender, bstate, rng):
    """Expert_Encore."""
    if not defender.get("disabled_move"):
        if _speed_compare(attacker, defender, bstate) == "SLOWER":
            return -2
        last = defender.get("last_move_used")
        if not last or _real_effect(last) not in EXPERT_ENCORE_EFFECTS:
            return -2
    return 0 if _ai_skip(rng, 30) else 3


def _expert_pain_split(attacker, defender, bstate):
    """Expert_PainSplit."""
    if ai_hp_percent(defender) < 80:
        return -1
    threshold = 60 if _speed_compare(attacker, defender, bstate) == "SLOWER" else 40
    return -1 if ai_hp_percent(attacker) > threshold else 1


def _expert_sleep_talk(attacker):
    """Expert_SleepTalk: +10 while asleep, otherwise -5."""
    return 10 if attacker.get("status") == "SLEEP" else -5


def _expert_destiny_bond(attacker, defender, bstate, rng):
    """Expert_DestinyBond: starts at -1 and each HP tier below can add back."""
    score = -1
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return score
    hp = ai_hp_percent(attacker)
    if hp > 70:
        return score
    if not _ai_skip(rng, 128):
        score += 1
    if hp > 50:
        return score
    if not _ai_skip(rng, 128):
        score += 1
    if hp > 30:
        return score
    return score if _ai_skip(rng, 100) else score + 2


def _expert_reversal(attacker, defender, bstate, rng):
    """Expert_Reversal (Flail/Reversal)."""
    hp = ai_hp_percent(attacker)
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        if hp > 60:
            return -1
        if hp > 40:
            return 0
        score = 0
    else:
        if hp > 33:
            return -1
        if hp > 20:
            return 0
        score = 1 if hp < 8 else 0          # ScorePlus1 falls through into TryScorePlus1
    return score if _ai_skip(rng, 100) else score + 1


def _expert_heal_bell(attacker, ally, attacker_party):
    """Expert_HealBell: -5 unless the user or a BENCHED, alive party member
    (not the active battler(s)) has a status condition."""
    if _ai_has_status(attacker):
        return 0
    for m in attacker_party or ():
        if m is attacker or m is ally:
            continue
        if m.get("hp", 0) > 0 and _ai_has_status(m):
            return 0
    return -5


def _expert_thief(defender, rng):
    """Expert_Thief. The AI only 'knows' the opponent's held item once it has
    been announced in a battle message (and forgets it on switch-in), so with
    nothing revealed (no "ai_known_item") the item's hold effect reads as
    HOLD_EFFECT_NONE, which is not an encouraged effect -> -2."""
    item = defender.get("ai_known_item")
    hold_effect = get_item_info(item).get("hold_effect") if item else "HOLD_EFFECT_NONE"
    if hold_effect not in EXPERT_THIEF_ITEM_EFFECTS:
        return -2
    return 0 if _ai_skip(rng, 50) else 1


def _expert_curse(attacker, rng):
    """Expert_Curse. Ghost-types take the Ghost branch (Curse's real
    effect). Otherwise the +1 rolls chain: a Gyro Ball/Trick Room user first
    rolls ~87.5% for +1 (and only then gets the 50% coin flip), and the Defense-stage checks are
    cumulative (note '+3 or higher' in the source comment is really raw > 9,
    i.e. +4)."""
    if attacker.get("type1") == "TYPE_GHOST" or attacker.get("type2") == "TYPE_GHOST":
        return 0 if ai_hp_percent(attacker) > 80 else -1
    stage = attacker.get("def_stage", 0)
    if stage > 3:                                       # raw > 9
        return 0
    score = 0
    moves = attacker.get("moves", [])
    flip_coin = True
    if "MOVE_GYRO_BALL" in moves or "MOVE_TRICK_ROOM" in moves:
        # HighChanceScorePlus1: a roll below 32 jumps STRAIGHT to CheckDefenseStage
        # (skipping the coin flip too); otherwise +1 and on to the coin flip.
        if _ai_skip(rng, 32):
            flip_coin = False
        else:
            score += 1
    if flip_coin and not _ai_skip(rng, 128):
        score += 1
    # CheckDefenseStage
    if stage > 1:                                       # raw > 7
        return score
    if not _ai_skip(rng, 128):
        score += 1
    # CheckDefenseStageAnyBoosts
    if stage > 0:                                       # raw > 6
        return score
    if not _ai_skip(rng, 128):
        score += 1
    return score


def _expert_protect(attacker, defender, bstate, rng):
    """Expert_Protect (Protect/Detect). Faithful control flow, including that
    several branches terminate early and that 'known' target moves/effects
    are only those the AI has SEEN the target use."""
    score = 0
    known_moves = _ai_defender_known_moves(defender)
    if ("MOVE_FEINT" in known_moves or "MOVE_SHADOW_FORCE" in known_moves) and not _ai_skip(rng, 128):
        score -= 2
    # CheckStatusConditions
    chain = _ai_protect_chain(attacker)
    if chain > 1:
        return score - 2

    def afflicted(m):
        return (m.get("status") == "TOXIC" or m.get("cursed") or m.get("perish_song", 0) > 0
                or m.get("attracted") or m.get("leech_seeded") or m.get("yawn_turn", 0) > 0)

    known_effects = _ai_defender_known_effects(defender)
    if (afflicted(attacker) or "BATTLE_EFFECT_RESTORE_HALF_HP" in known_effects
            or "BATTLE_EFFECT_DEF_UP_DOUBLE_ROLLOUT_POWER" in known_effects):
        # CheckAttackerLockedOnto: no penalty if an opponent has Locked On to us
        return score if attacker.get("locked_on_by") else score - 2
    if (afflicted(defender) or bstate.get("is_double_battle") or attacker.get("locked_on_by")
            or _ai_skip(rng, 85)):
        score += 2                                      # ScorePlus2
    # TryScoreMinus1
    if not _ai_skip(rng, 128):
        score -= 1
    # CheckEmptyChain
    if chain == 0:
        return score
    score -= 1
    return score if _ai_skip(rng, 128) else score - 1


def _expert_spikes(attacker, rng):
    """Expert_Spikes: 50% of nothing, else +1 (and ~75% of another +1 when the
    user also knows Roar or Whirlwind)."""
    if _ai_skip(rng, 128):
        return 0
    score = 1
    moves = attacker.get("moves", [])
    if ("MOVE_ROAR" in moves or "MOVE_WHIRLWIND" in moves) and not _ai_skip(rng, 64):
        score += 1
    return score


# ---------------- Batch 4: Foresight .. FocusPunch (script.s 3608-4163) ----------------
def _ai_speed_faster(a, d, bstate, rng):
    """IfSpeedCompareEqualTo COMPARE_SPEED_FASTER: the real compare returns FASTER by default and TIE on a coin
    flip when speeds are exactly equal, so a tie is FASTER half the time (one rng draw, only on a tie)."""
    cmp_ = _speed_compare(a, d, bstate)
    return cmp_ == "FASTER" or (cmp_ == "TIE" and rng.randint(0, 1) == 0)


def _ai_first_turn(mon):
    """LoadIsFirstTurnInBattle: TRUE until the mon has acted since it switched in (the engine's own Fake Out state)."""
    return not mon.get("acted_since_switch_in")


def _ai_weather(bstate):
    return bstate.get("weather", "NONE")


_EXPERT_MIRROR_COAT_SPECIAL_TYPES = frozenset((
    "TYPE_FIRE", "TYPE_WATER", "TYPE_GRASS", "TYPE_ELECTRIC", "TYPE_PSYCHIC", "TYPE_ICE", "TYPE_DRAGON", "TYPE_DARK",
))
_EXPERT_SAND_IMMUNE_TYPES = frozenset(("TYPE_GROUND", "TYPE_ROCK", "TYPE_STEEL"))


def _expert_foresight(attacker, defender, rng):
    """Expert_Foresight. Retail bug reproduced: the script tests the ATTACKER for a Ghost type (it means the
    opponent). A Ghost user needs two rolls of 80 (~47.3% of +2); otherwise a target at +3 Evasion or more
    needs one (~68.75%); anything else is -2."""
    if "TYPE_GHOST" in (attacker.get("type1"), attacker.get("type2")):
        if _ai_skip(rng, 80):
            return 0
    elif defender.get("eva_stage", 0) > 2:                      # raw > 8
        pass
    else:
        return -2
    return 0 if _ai_skip(rng, 80) else 2


def _expert_endure(attacker, rng):
    """Expert_Endure. Below 4% HP: -1. 4-34%: ~72.7% of +1. At 35% or more the script FALLS THROUGH into the
    -1 label, so Endure is penalised whenever the user is not in trouble."""
    hp = ai_hp_percent(attacker)
    if hp < 4:
        return -1
    if hp < 35:
        return 0 if _ai_skip(rng, 70) else 1
    return -1


def _expert_baton_pass(attacker, defender, bstate, rng):
    """Expert_BatonPass (only Attack/Defense/SpAtk/SpDef/Evasion are looked at, never Speed)."""
    keys = ("atk_stage", "def_stage", "spa_stage", "spd_stage", "eva_stage")
    hp = ai_hp_percent(attacker)
    slower = _speed_compare(attacker, defender, bstate) == "SLOWER"
    if any(attacker.get(k, 0) > 2 for k in keys):                # raw > 8
        if hp > (70 if slower else 60):
            return 0
        return 0 if _ai_skip(rng, 80) else 2
    if any(attacker.get(k, 0) > 1 for k in keys):                # raw > 7
        if slower:
            return 0 if hp < 70 else -2
        return -2 if hp > 60 else 0
    return -2


def _expert_pursuit(attacker, defender, rng):
    """Expert_Pursuit."""
    score = 0
    d_types = (defender.get("type1"), defender.get("type2"))
    if _ai_first_turn(attacker) or "TYPE_GHOST" in d_types or "TYPE_PSYCHIC" in d_types:
        if not _ai_skip(rng, 128):
            score += 1
    if "MOVE_U_TURN" in _ai_defender_known_moves(defender) and not _ai_skip(rng, 128):
        score += 1
    return score


def _expert_rain_dance(attacker, defender, bstate, rng):
    """Expert_RainDance."""
    if not _ai_speed_faster(attacker, defender, bstate, rng) and _ai_ability(attacker) == "SWIFT_SWIM":
        return 1
    if ai_hp_percent(attacker) < 40:
        return -1
    if _ai_weather(bstate) in ("HAIL", "SUN", "SANDSTORM"):
        return 1
    ab = _ai_ability(attacker)
    if ab == "RAIN_DISH":
        return 1
    return 1 if (ab == "HYDRATION" and _bc_status_any(attacker)) else 0


def _expert_sunny_day(attacker, bstate):
    """Expert_SunnyDay. Retail bug reproduced: Leaf Guard is rewarded when the user IS statused (it should be
    when it is not)."""
    if ai_hp_percent(attacker) < 40:
        return -1
    if _ai_weather(bstate) in ("HAIL", "RAIN", "SANDSTORM"):
        return 1
    ab = _ai_ability(attacker)
    if ab == "FLOWER_GIFT":
        return 1
    return 1 if (ab == "LEAF_GUARD" and _bc_status_any(attacker)) else 0


def _expert_belly_drum(attacker):
    return -2 if ai_hp_percent(attacker) < 90 else 0


def _expert_psych_up(attacker, defender, rng):
    """Expert_Psych_Up."""
    if not any(defender.get(k, 0) > 2 for k in ("atk_stage", "def_stage", "spa_stage", "spd_stage", "eva_stage")):
        return -2
    if any(attacker.get(k, 0) < 1 for k in ("atk_stage", "def_stage", "spa_stage", "spd_stage")):
        return 1
    if attacker.get("eva_stage", 0) < 1:
        return 2
    return 0 if _ai_skip(rng, 50) else -2


def _expert_mirror_coat(attacker, defender, rng):
    """Expert_MirrorCoat: Counter's mirror image (Special where Counter has Physical). The opponent-types branch
    falls through into the +4 roll, as in Counter."""
    if defender.get("status") == "SLEEP" or defender.get("attracted") or defender.get("confused"):
        return -1
    score = 0
    hp = ai_hp_percent(attacker)
    if hp <= 30 and not _ai_skip(rng, 10):
        score -= 1
    if hp <= 50 and not _ai_skip(rng, 100):
        score -= 1
    if "MOVE_COUNTER" in attacker.get("moves", []):
        return score if _ai_skip(rng, 100) else score + 4
    power, cls = _last_move_power_class(defender)
    taunted = defender.get("taunt_turns", 0) > 0
    if power != 0:
        if taunted and not _ai_skip(rng, 100):
            score += 1
        if cls != "CLASS_SPECIAL":
            return score - 1
        return score if _ai_skip(rng, 100) else score + 1
    if taunted and not _ai_skip(rng, 100):
        score += 1
    d_types = {defender.get("type1"), defender.get("type2") or defender.get("type1")}
    if d_types & _EXPERT_MIRROR_COAT_SPECIAL_TYPES:
        return score
    if _ai_skip(rng, 50):
        return score
    return score if _ai_skip(rng, 100) else score + 4


def _expert_charge_turn_no_invuln(move_name, move, attacker, defender, bstate):
    """Expert_ChargeTurnNoInvuln (Razor Wind/Sky Attack-style charge moves, Solar Beam, Skull Bash)."""
    eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
    if eff in (0.0, 0.25, 0.5):
        return -2
    if _real_effect(move_name) == "BATTLE_EFFECT_SKIP_CHARGE_TURN_IN_SUN" and _ai_weather(bstate) == "SUN":
        return 2
    if attacker.get("item") == "ITEM_POWER_HERB":
        return 2
    if "BATTLE_EFFECT_PROTECT" in _ai_defender_known_effects(defender):
        return -2
    return 0 if ai_hp_percent(attacker) > 38 else -1


def _expert_charge_turn_with_invuln(attacker, defender, move, bstate, rng, shadow_force=False):
    """Expert_ChargeTurnWithInvuln (Fly/Dig/Dive/Bounce) and, entered directly, Expert_ShadowForce."""
    if not shadow_force:
        if attacker.get("item") == "ITEM_POWER_HERB":
            return 2
        if "BATTLE_EFFECT_PROTECT" in _ai_defender_known_effects(defender):
            return -1
    # Expert_ShadowForce
    eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
    if eff in (0.0, 0.25, 0.5):
        return 1
    if attacker.get("item") == "ITEM_POWER_HERB":
        return 1
    try_plus1 = False
    if defender.get("status") == "TOXIC" or defender.get("cursed") or defender.get("leech_seeded"):
        try_plus1 = True
    else:
        w = _ai_weather(bstate)
        a_types = {attacker.get("type1"), attacker.get("type2") or attacker.get("type1")}
        if w == "SANDSTORM" and a_types & _EXPERT_SAND_IMMUNE_TYPES:
            try_plus1 = True
        elif w == "HAIL" and "TYPE_ICE" in a_types:
            try_plus1 = True
    if not try_plus1:
        if _speed_compare(attacker, defender, bstate) == "SLOWER":
            return 0
        last = defender.get("last_move_used")
        last_effect = _real_effect(last) if last else "BATTLE_EFFECT_HIT"     # MOVE_NONE is a plain hit
        if last_effect == "BATTLE_EFFECT_NEXT_ATTACK_ALWAYS_HITS":
            return 0
    return 0 if _ai_skip(rng, 80) else 1


def _expert_spit_up(attacker, rng):
    if attacker.get("stockpile", 0) < 2:
        return 0
    return 0 if _ai_skip(rng, 80) else 2


def _expert_hail(attacker, bstate):
    """Expert_Hail. The Ice Body bonus sits INSIDE the wrong-weather branch, so it only ever applies when the
    current weather is Sun, Rain or Sandstorm."""
    if ai_hp_percent(attacker) < 40:
        return -1
    if _ai_weather(bstate) not in ("SUN", "RAIN", "SANDSTORM"):
        return 0
    score = 1
    if "MOVE_BLIZZARD" in attacker.get("moves", []):
        score += 2
    if _ai_ability(attacker) == "ICE_BODY":
        score += 2
    return score


def _expert_facade(defender):
    """Expert_Facade. Retail bug reproduced: it checks the TARGET's status, not the user's."""
    return 1 if defender.get("status") in ("BURN", "POISON", "TOXIC", "PARALYSIS") else 0


def _expert_focus_punch(move, attacker, defender, bstate, rng):
    """Expert_FocusPunch."""
    eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
    if eff in (0.0, 0.25, 0.5):
        return -1
    if attacker.get("substitute_hp", 0) > 0:
        return 5
    if defender.get("status") == "SLEEP":
        return 1
    if defender.get("attracted") or defender.get("confused"):
        return 0 if _ai_skip(rng, 100) else 1
    if _ai_first_turn(attacker):
        return 0
    return 0 if _ai_skip(rng, 200) else 1


# ---------------- Batch 5: SmellingSalts .. PsychoShift (script.s 4165-5306), except U-Turn ----------------
# Item / ability / hold-effect tables extracted straight from script.s
EXPERT_TRICK_FLAVOR_BERRIES = frozenset((
    "HOLD_EFFECT_HP_RESTORE_SPICY",
    "HOLD_EFFECT_HP_RESTORE_DRY",
    "HOLD_EFFECT_HP_RESTORE_SWEET",
    "HOLD_EFFECT_HP_RESTORE_BITTER",
    "HOLD_EFFECT_HP_RESTORE_SOUR",
))

EXPERT_TRICK_DISRUPTIVE_ITEMS = frozenset((
    "HOLD_EFFECT_CHOICE_ATK",
    "HOLD_EFFECT_CHOICE_SPATK",
    "HOLD_EFFECT_CHOICE_SPEED",
    "HOLD_EFFECT_SPEED_DOWN_GROUNDED",
    "HOLD_EFFECT_PRIORITY_DOWN",
    "HOLD_EFFECT_DMG_USER_CONTACT_XFR",
    "HOLD_EFFECT_LVLUP_ATK_EV_UP",
    "HOLD_EFFECT_LVLUP_DEF_EV_UP",
    "HOLD_EFFECT_LVLUP_SPATK_EV_UP",
    "HOLD_EFFECT_LVLUP_DEF_EV_UP",
    "HOLD_EFFECT_LVLUP_SPDEF_EV_UP",
    "HOLD_EFFECT_LVLUP_SPEED_EV_UP",
    "HOLD_EFFECT_LVLUP_HP_EV_UP",
))

EXPERT_TRICK_BAD_OPPONENT_ITEMS = frozenset((
    "HOLD_EFFECT_EVS_UP_SPEED_DOWN",
    "HOLD_EFFECT_CHOICE_ATK",
    "HOLD_EFFECT_CHOICE_SPATK",
    "HOLD_EFFECT_CHOICE_SPEED",
    "HOLD_EFFECT_SPEED_DOWN_GROUNDED",
    "HOLD_EFFECT_PRIORITY_DOWN",
    "HOLD_EFFECT_DMG_USER_CONTACT_XFR",
    "HOLD_EFFECT_LVLUP_ATK_EV_UP",
    "HOLD_EFFECT_LVLUP_DEF_EV_UP",
    "HOLD_EFFECT_LVLUP_SPATK_EV_UP",
    "HOLD_EFFECT_LVLUP_SPDEF_EV_UP",
    "HOLD_EFFECT_LVLUP_SPEED_EV_UP",
    "HOLD_EFFECT_LVLUP_HP_EV_UP",
    "HOLD_EFFECT_PSN_USER",
    "HOLD_EFFECT_BRN_USER",
    "HOLD_EFFECT_HP_RESTORE_PSN_TYPE",
))

EXPERT_TRICK_BAD_OPPONENT_ITEMS_AND_FLAVOR_BERRIES = frozenset((
    "HOLD_EFFECT_HP_RESTORE_SPICY",
    "HOLD_EFFECT_HP_RESTORE_DRY",
    "HOLD_EFFECT_HP_RESTORE_SWEET",
    "HOLD_EFFECT_HP_RESTORE_BITTER",
    "HOLD_EFFECT_HP_RESTORE_SOUR",
    "HOLD_EFFECT_EVS_UP_SPEED_DOWN",
    "HOLD_EFFECT_CHOICE_ATK",
    "HOLD_EFFECT_CHOICE_SPATK",
    "HOLD_EFFECT_CHOICE_SPEED",
    "HOLD_EFFECT_SPEED_DOWN_GROUNDED",
    "HOLD_EFFECT_PRIORITY_DOWN",
    "HOLD_EFFECT_DMG_USER_CONTACT_XFR",
    "HOLD_EFFECT_LVLUP_ATK_EV_UP",
    "HOLD_EFFECT_LVLUP_DEF_EV_UP",
    "HOLD_EFFECT_LVLUP_SPATK_EV_UP",
    "HOLD_EFFECT_LVLUP_SPDEF_EV_UP",
    "HOLD_EFFECT_LVLUP_SPEED_EV_UP",
    "HOLD_EFFECT_LVLUP_HP_EV_UP",
    "HOLD_EFFECT_PSN_USER",
    "HOLD_EFFECT_BRN_USER",
    "HOLD_EFFECT_HP_RESTORE_PSN_TYPE",
))

EXPERT_CHANGE_ABILITY_DESIRABLE = frozenset((
    "SPEED_BOOST",
    "BATTLE_ARMOR",
    "SAND_VEIL",
    "STATIC",
    "FLASH_FIRE",
    "WONDER_GUARD",
    "EFFECT_SPORE",
    "SWIFT_SWIM",
    "HUGE_POWER",
    "RAIN_DISH",
    "CUTE_CHARM",
    "SHED_SKIN",
    "MARVEL_SCALE",
    "PURE_POWER",
    "CHLOROPHYLL",
    "SHIELD_DUST",
    "ADAPTABILITY",
    "MAGIC_GUARD",
    "MOLD_BREAKER",
    "SUPER_LUCK",
    "UNAWARE",
    "TINTED_LENS",
    "FILTER",
    "SOLID_ROCK",
    "RECKLESS",
))

EXPERT_FEINT_GRADUAL_RECOVERY_EFFECTS = frozenset((
    "HOLD_EFFECT_HP_RESTORE_GRADUAL",
    "HOLD_EFFECT_HP_RESTORE_PSN_TYPE",
))

EXPERT_FLING_DESIRABLE_EFFECTS = frozenset((
    "HOLD_EFFECT_SOMETIMES_FLINCH",
    "HOLD_EFFECT_STRENGTHEN_POISON",
    "HOLD_EFFECT_PSN_USER",
    "HOLD_EFFECT_BRN_USER",
    "HOLD_EFFECT_PIKA_SPATK_UP",
))

EXPERT_RECYCLE_DESIRABLE_ITEMS = frozenset((
    "ITEM_CHESTO_BERRY",
    "ITEM_LUM_BERRY",
    "ITEM_STARF_BERRY",
))



def _ex_hold_effect(mon, known_only):
    """LoadHeldItemEffect: the user's own item is read directly; an OPPONENT's only once the AI has seen it."""
    item = mon.get("ai_known_item") if known_only else mon.get("item")
    return get_item_info(item).get("hold_effect", "HOLD_EFFECT_NONE") if item else "HOLD_EFFECT_NONE"


def _ex_resisted(move, attacker, defender, bstate):
    """The 'immune to, or would resist' gate used by dozens of handlers."""
    return _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate) in (0.0, 0.25, 0.5)


def _ex_types(mon):
    return {mon.get("type1"), mon.get("type2") or mon.get("type1")}


def _expert_smelling_salts(defender):
    return 1 if defender.get("status") == "PARALYSIS" else 0


def _expert_trick_poison_immune(mon, klutz, load_ability=None):
    """Whether a battler shrugs off Toxic Orb-style poisoning (the attacker's version also counts Klutz). `load_ability` is the
    LoadBattlerAbility read for this mon (a guess for the opponent); it only runs after the status/type checks, as in the script."""
    abilities = ("IMMUNITY", "MAGIC_GUARD", "POISON_HEAL") + (("KLUTZ",) if klutz else ())
    return bool(_bc_status_any(mon) or _bc_safeguard(mon) or (_ex_types(mon) & {"TYPE_STEEL", "TYPE_POISON"})
                or (load_ability or _ai_ability)(mon) in abilities)


def _expert_trick(attacker, defender, rng):
    """Expert_Trick (Trick/Switcheroo). Dispatch is on the HOLD EFFECT of the user's item. Two retail quirks are
    reproduced: Black Sludge against a Magic Guard target runs the Toxic Orb attacker check, and a burn-orb user
    with Klutz scores -5 (the shared ScoreMinus5 label) where every other case is -3. An item that matches
    nothing falls into the -3 label."""
    he_a = _ex_hold_effect(attacker, False)
    he_d = _ex_hold_effect(defender, True)
    bad_opponent = he_d in EXPERT_TRICK_BAD_OPPONENT_ITEMS
    def defender_ability():
        return ai_load_ability(defender, attacker, rng)
    if he_a in EXPERT_TRICK_DISRUPTIVE_ITEMS:
        return -3 if bad_opponent else 5
    if he_a == "HOLD_EFFECT_PSN_USER":
        if bad_opponent:
            return -3
        if not _expert_trick_poison_immune(defender, False, lambda m: defender_ability()):
            return 5
        return -3 if _expert_trick_poison_immune(attacker, True) else 5
    if he_a == "HOLD_EFFECT_BRN_USER":
        if bad_opponent:
            return -3
        d_immune = (defender_ability() in ("WATER_VEIL", "MAGIC_GUARD") or _bc_status_any(defender)
                    or _bc_safeguard(defender) or "TYPE_FIRE" in _ex_types(defender))
        if not d_immune:
            return 5
        ab = _ai_ability(attacker)
        if ab in ("WATER_VEIL", "MAGIC_GUARD"):
            return -3
        if ab == "KLUTZ":
            return -5
        if _bc_status_any(attacker) or _bc_safeguard(attacker) or "TYPE_FIRE" in _ex_types(attacker):
            return -3
        return 5
    if he_a == "HOLD_EFFECT_HP_RESTORE_PSN_TYPE":               # Black Sludge
        if bad_opponent:
            return -3
        if "TYPE_POISON" in _ex_types(defender):
            if ("TYPE_POISON" in _ex_types(attacker) or _ai_ability(attacker) in ("MAGIC_GUARD", "KLUTZ")):
                return -3
            return 5
        if defender_ability() == "MAGIC_GUARD":
            return -3 if _expert_trick_poison_immune(attacker, True) else 5
        return 5
    if he_a in EXPERT_TRICK_FLAVOR_BERRIES:
        if he_d in EXPERT_TRICK_BAD_OPPONENT_ITEMS_AND_FLAVOR_BERRIES:
            return -3
        return 0 if _ai_skip(rng, 50) else 2
    return -3


def _expert_change_user_ability(attacker, defender, rng):
    """Expert_ChangeUserAbility (Skill Swap-likes). Falls through into the -1 label, so unless only the opponent
    has a desirable ability the score is -1."""
    if _ai_ability(attacker) in EXPERT_CHANGE_ABILITY_DESIRABLE:
        return -1
    if ai_load_ability(defender, attacker, rng) in EXPERT_CHANGE_ABILITY_DESIRABLE:
        return 0 if _ai_skip(rng, 50) else 2
    return -1


def _expert_superpower(move, attacker, defender, bstate):
    if _ex_resisted(move, attacker, defender, bstate) or attacker.get("atk_stage", 0) < 0:
        return -1
    hp = ai_hp_percent(attacker)
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return 0 if hp < 60 else -1
    return -1 if hp > 40 else 0


def _expert_magic_coat(attacker, defender, rng):
    """Expert_MagicCoat (the instructions after the first-turn branch's GoTo are dead code in the script)."""
    score = 0
    if ai_hp_percent(defender) <= 30 and not _ai_skip(rng, 100):
        score -= 1
    if _ai_first_turn(attacker):
        return score if _ai_skip(rng, 150) else score + 1
    return score if _ai_skip(rng, 30) else score - 1


def _expert_recycle(attacker, rng):
    """Expert_Recycle: only Chesto, Lum and Starf Berries are worth recycling."""
    item = attacker.get("consumed_item")
    if item not in EXPERT_RECYCLE_DESIRABLE_ITEMS:
        return -2
    return 0 if _ai_skip(rng, 50) else 1


def _expert_revenge(defender, rng):
    if defender.get("status") == "SLEEP" or defender.get("attracted") or defender.get("confused"):
        return -2
    return -2 if _ai_skip(rng, 180) else 2


def _expert_brick_break(defender, bstate, side_of_defender):
    side = bstate["sides"][side_of_defender]
    return 1 if (side.get("reflect") or side.get("light_screen")) else 0


def _expert_knock_off(attacker, defender, rng):
    if ai_hp_percent(defender) < 30 or _ai_first_turn(attacker):
        return 0
    return 0 if _ai_skip(rng, 180) else 1


def _expert_endeavor(attacker, defender, bstate):
    if ai_hp_percent(defender) < 70:
        return -1
    threshold = 50 if _speed_compare(attacker, defender, bstate) == "SLOWER" else 40
    return -1 if ai_hp_percent(attacker) > threshold else 1


def _expert_water_spout(move, attacker, defender, bstate):
    """Expert_WaterSpout. Retail bug reproduced: it checks the OPPONENT's HP where it means the user's."""
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    threshold = 70 if _speed_compare(attacker, defender, bstate) == "SLOWER" else 50
    return 0 if ai_hp_percent(defender) > threshold else -1


def _expert_imprison(attacker, rng):
    if _ai_first_turn(attacker):
        return 0
    return 0 if _ai_skip(rng, 100) else 2


def _expert_refresh(defender):
    return -1 if ai_hp_percent(defender) < 50 else 0


def _expert_snatch(attacker, defender, bstate, rng):
    """Expert_Snatch."""
    def try_minus2():
        return 0 if _ai_skip(rng, 30) else -2

    if _ai_first_turn(attacker):
        return 0 if _ai_skip(rng, 150) else 2
    if _ai_skip(rng, 30):
        return 0
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        if ai_hp_percent(defender) > 25:
            return try_minus2()
        known = _ai_defender_known_effects(defender)
        if "BATTLE_EFFECT_RESTORE_HALF_HP" in known or "BATTLE_EFFECT_DEF_UP_DOUBLE_ROLLOUT_POWER" in known:
            return 0 if _ai_skip(rng, 150) else 2
        if _ai_skip(rng, 230):
            return try_minus2()
        return 1
    if ai_hp_percent(attacker) != 100 or ai_hp_percent(defender) < 70:
        return try_minus2()
    if _ai_skip(rng, 60):
        return 0
    return try_minus2()


def _expert_mud_or_water_sport(attacker, defender, favored_type):
    """Expert_MudSport (Electric) / Expert_WaterSport (Fire)."""
    if ai_hp_percent(attacker) < 50:
        return -1
    return 1 if favored_type in _ex_types(defender) else -1


def _expert_overheat_like(move, attacker, defender, bstate, slower_threshold, faster_threshold):
    """Expert_Overheat (80/60) and Expert_CloseCombat (80/60): -1 when resisted or the user is hurt enough."""
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    threshold = slower_threshold if _speed_compare(attacker, defender, bstate) == "SLOWER" else faster_threshold
    return 0 if ai_hp_percent(attacker) > threshold else -1


def _expert_dragon_dance(attacker, defender, bstate, rng):
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return 0 if _ai_skip(rng, 128) else 1
    if ai_hp_percent(attacker) > 50 or _ai_skip(rng, 70):
        return 0
    return -1


def _expert_gravity(attacker, defender, rng):
    """Expert_Gravity."""
    grounded_out = (ai_load_ability(defender, attacker, rng) == "LEVITATE" or defender.get("magnet_rise_turns", 0) > 0
                    or "TYPE_FLYING" in _ex_types(defender))
    if not grounded_out:
        if ai_hp_percent(attacker) < 60:
            return 0
        if not _ai_skip(rng, 128):          # a roll of 128+ ends the script; below 128 goes on to the +1 roll
            return 0
    return 0 if _ai_skip(rng, 64) else 1


def _expert_miracle_eye(defender, rng):
    """Expert_MiracleEye: like Foresight, but keyed on the OPPONENT being Dark."""
    if "TYPE_DARK" in _ex_types(defender):
        if _ai_skip(rng, 80):
            return 0
    elif defender.get("eva_stage", 0) > 2:
        pass
    else:
        return -2
    return 0 if _ai_skip(rng, 80) else 2


def _expert_wake_up_slap(move, attacker, defender, bstate):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    return 1 if defender.get("status") == "SLEEP" else 0


def _expert_hammer_arm(move, attacker, defender, bstate):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    return 1 if _speed_compare(attacker, defender, bstate) == "SLOWER" else 0


def _expert_brine(move, attacker, defender, bstate, rng):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    if ai_hp_percent(defender) > 50:
        return 0
    return 1 if _ai_skip(rng, 128) else 2


def _expert_feint(attacker, defender, rng):
    """Expert_Feint. A Protect chain of exactly 2 falls through into the chain-0 roll (the script's comparisons
    skip it), and the opponent's item is only known if the AI has seen it."""
    score = 0
    known_protect = "BATTLE_EFFECT_PROTECT" in _ai_defender_known_effects(defender)
    if not known_protect and not _ai_skip(rng, 64):
        return 0
    # CheckConditions
    afflicted = (attacker.get("status") == "TOXIC" or attacker.get("cursed") or attacker.get("perish_song", 0) > 0
                 or attacker.get("attracted") or attacker.get("leech_seeded") or attacker.get("yawn_turn", 0) > 0)
    try_plus1 = afflicted
    if not afflicted:
        if ai_hp_percent(defender) != 100 and _ex_hold_effect(defender, True) in EXPERT_FEINT_GRADUAL_RECOVERY_EFFECTS:
            try_plus1 = True
    if try_plus1 and not _ai_skip(rng, 128):
        score += 1
    chain = _ai_protect_chain(defender)
    if chain > 2:
        return score - 2
    if chain == 1:
        return score if _ai_skip(rng, 192) else score + 1
    return score if _ai_skip(rng, 128) else score + 1


def _expert_pluck(move, attacker, defender, bstate, rng):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    score = 0
    if _ai_first_turn(attacker) and not _ai_skip(rng, 64):
        score += 1
    return score if _ai_skip(rng, 128) else score + 1


def _expert_tailwind(attacker, defender, bstate, rng):
    if _ai_skip(rng, 64):
        return 0
    if _ai_speed_faster(attacker, defender, bstate, rng):
        return -1
    hp = ai_hp_percent(attacker)
    if hp < 31:
        return -1
    if hp > 75:
        return 1
    return 0 if _ai_skip(rng, 64) else 1


def _expert_acupressure(attacker, rng):
    hp = ai_hp_percent(attacker)
    if hp < 51:
        return -1
    if hp <= 90 and _ai_skip(rng, 128):
        return 0
    return 0 if _ai_skip(rng, 64) else 1


def _expert_metal_burst(attacker, defender, rng):
    """Expert_MetalBurst: the Counter/Mirror Coat pattern, with a +1 roll tacked on for everyone."""
    known = _ai_defender_known_effects(defender)
    if (defender.get("status") == "SLEEP" or defender.get("attracted") or defender.get("confused")
            or known & {"BATTLE_EFFECT_DOUBLE_POWER_IF_HIT", "BATTLE_EFFECT_HIT_LAST_WHIFF_IF_HIT",
                        "BATTLE_EFFECT_PRIORITY_NEG_1_BYPASS_ACCURACY"}):
        return -1
    score = 0
    hp = ai_hp_percent(attacker)
    if hp <= 30 and not _ai_skip(rng, 10):
        score -= 1
    if hp <= 50 and not _ai_skip(rng, 100):
        score -= 1
    if not _ai_skip(rng, 192):
        score += 1
    taunted = defender.get("taunt_turns", 0) > 0
    power, _cls = _last_move_power_class(defender)
    if power != 0 and taunted and not _ai_skip(rng, 100):
        score += 1
    if not taunted:
        return score
    return score if _ai_skip(rng, 100) else score + 1


def _expert_payback(move, attacker, defender, bstate, rng):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    if _ai_speed_faster(attacker, defender, bstate, rng) or ai_hp_percent(attacker) < 30:
        return 0
    return 0 if _ai_skip(rng, 64) else 1


def _expert_assurance(move, attacker, defender, bstate, rng):
    """Expert_Assurance. Retail bug reproduced: the recoil-berry table holds ITEM ids but is compared to a HOLD
    EFFECT, so a Jaboca/Rowap Berry never matches."""
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    if _ai_speed_faster(attacker, defender, bstate, rng):
        return 0
    if _ai_ability(attacker) != "ROUGH_SKIN" and not _ai_skip(rng, 128):
        return 0                            # a roll of 128+ ends the script; below 128 goes on to the +1 roll
    return 0 if _ai_skip(rng, 128) else 1


def _expert_fling(move, attacker, defender, bstate, rng):
    """Expert_Fling."""
    if _ex_resisted(move, attacker, defender, bstate):
        return 0 if _ex_hold_effect(attacker, False) in EXPERT_FLING_DESIRABLE_EFFECTS else -1
    item = attacker.get("item")
    power = (get_item_info(item).get("fling_power", 0) or 0) if item else 0
    if power < 30:
        return -2
    if power > 90:
        eff = _ai_move_effectiveness(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
        if eff in (2.0, 4.0):
            score = 4
        else:
            score = 0 if _ai_skip(rng, 128) else 1
            # (either way it then takes the +1 roll below)
        return score if _ai_skip(rng, 64) else score + 1
    if power > 60:
        return 0 if _ai_skip(rng, 64) else 1
    return 0 if _ai_skip(rng, 128) else -1


def _expert_psycho_shift(attacker, defender, rng):
    if not _bc_status_any(attacker):
        return -10
    if _ai_skip(rng, 128) or ai_hp_percent(defender) < 30:
        return 0
    return 1


# ---------------- Batch 6: TrumpCard .. HealingWish + U-Turn (script.s 5308-6351) ----------------
EXPERT_COPYCAT_ENCOURAGED_MOVES = frozenset((
    "MOVE_SLEEP_POWDER",
    "MOVE_LOVELY_KISS",
    "MOVE_SPORE",
    "MOVE_HYPNOSIS",
    "MOVE_SING",
    "MOVE_GRASS_WHISTLE",
    "MOVE_SHADOW_PUNCH",
    "MOVE_SAND_ATTACK",
    "MOVE_SMOKE_SCREEN",
    "MOVE_TOXIC",
    "MOVE_GUILLOTINE",
    "MOVE_HORN_DRILL",
    "MOVE_FISSURE",
    "MOVE_SHEER_COLD",
    "MOVE_CROSS_CHOP",
    "MOVE_AEROBLAST",
    "MOVE_CONFUSE_RAY",
    "MOVE_SWEET_KISS",
    "MOVE_SCREECH",
    "MOVE_COTTON_SPORE",
    "MOVE_SCARY_FACE",
    "MOVE_FAKE_TEARS",
    "MOVE_METAL_SOUND",
    "MOVE_THUNDER_WAVE",
    "MOVE_GLARE",
    "MOVE_POISON_POWDER",
    "MOVE_SHADOW_BALL",
    "MOVE_DYNAMIC_PUNCH",
    "MOVE_HYPER_BEAM",
    "MOVE_EXTREME_SPEED",
    "MOVE_THIEF",
    "MOVE_COVET",
    "MOVE_ATTRACT",
    "MOVE_SWAGGER",
    "MOVE_TORMENT",
    "MOVE_FLATTER",
    "MOVE_TRICK",
    "MOVE_SUPERPOWER",
    "MOVE_SKILL_SWAP",
    "MOVE_PSYCHO_SHIFT",
    "MOVE_POWER_SWAP",
    "MOVE_GUARD_SWAP",
    "MOVE_SUCKER_PUNCH",
    "MOVE_HEART_SWAP",
    "MOVE_SWITCHEROO",
    "MOVE_CAPTIVATE",
    "MOVE_DARK_VOID",
))



# --- damage-comparison predicates ---------------------------------------------------------------------------
# IfHasSuperEffectiveMove / IfBattlerDealsMoreDamage / IfPartyMemberDealsMoreDamage all lean on the damage
# calculator, so they are built on this simulator's own estimate_max_damage. The control flow around them is
# exact; the numbers underneath are the simulator's estimate, not the game's TrainerAI_CalcAllDamage.
def _ai_move_max_damage(user, target, move_name, bstate):
    mv = get_effective_move_data(move_name, user, defender=target, bstate=bstate)
    dmg, _eff = estimate_max_damage(user, target, mv, weather_now(bstate), bstate=bstate)
    return dmg


def _ai_best_damage(user, target, move_names, bstate):
    return max([_ai_move_max_damage(user, target, n, bstate) for n in move_names if n] or [0])


def _ai_has_super_effective_move(attacker, defender, bstate):
    """AI_HasSuperEffectiveMove (flag TRUE, singles): any DAMAGING move of the user's that the target is weak to
    on at least one of its types (the game sets the super-effective flag per type entry, and only for moves with
    power)."""
    for name in attacker.get("moves", []):
        raw = _MOVES_BY_NAME.get(name) or {}
        if not name or not (raw.get("power", 0) or 0):
            continue
        mtype = get_effective_move_data(name, attacker, defender=defender, bstate=bstate).get("type", "TYPE_NORMAL")
        if _ai_move_effectiveness_flags(mtype, attacker, defender, bstate):
            return True
    return False


def _ai_move_effectiveness_flags(move_type, attacker, defender, bstate):
    """True if any single (chart-adjusted) defender type takes 2x from the move type."""
    if has_ability(attacker, "NORMALIZE"):
        move_type = "TYPE_NORMAL"
    gravity = bstate.get("gravity", 0) > 0
    if move_type == "TYPE_GROUND" and not gravity:
        if has_ability(defender, "LEVITATE") and not has_ability(attacker, "MOLD_BREAKER"):
            return False
        if defender.get("magnet_rise_turns", 0) > 0 and not defender.get("ingrain"):
            return False
    types = [t for t in (defender.get("type1"), defender.get("type2")) if t]
    if gravity and move_type == "TYPE_GROUND":
        types = [t for t in types if t != "TYPE_FLYING"]
    if move_type in ("TYPE_NORMAL", "TYPE_FIGHTING") and (defender.get("foresight") or has_ability(attacker, "SCRAPPY")):
        types = [t for t in types if t != "TYPE_GHOST"]
    if move_type == "TYPE_PSYCHIC" and defender.get("miracle_eye"):
        types = [t for t in types if t != "TYPE_DARK"]
    return any(type_effectiveness_raw(move_type, [t]) == 2.0 for t in types)


def _ai_defender_deals_more(attacker, defender, bstate):
    """IfBattlerDealsMoreDamage DEFENDER: the target's LAST-USED move (not its best move) against us out-damages
    the user's best move against it. No last move counts as 0 damage."""
    last = defender.get("last_move_used")
    theirs = _ai_move_max_damage(defender, attacker, last, bstate) if last else 0
    return theirs > _ai_best_damage(attacker, defender, attacker.get("moves", []), bstate)


def _ai_party_deals_more(attacker, party, defender, bstate):
    """IfPartyMemberDealsMoreDamage: some other living party member's moves would out-damage the user's, judged
    with the USER's stats (the game passes the active battler into the damage calculation, moves swapped in)."""
    mine = _ai_best_damage(attacker, defender, attacker.get("moves", []), bstate)
    for m in party or ():
        if m is attacker or m.get("hp", 0) <= 0:
            continue
        if _ai_best_damage(attacker, defender, m.get("moves", []), bstate) > mine:
            return True
    return False


def _ai_can_use_last_resort(attacker):
    known = [m for m in attacker.get("moves", []) if m]
    used = attacker.get("moves_used_this_stay") or ()
    return len(known) > 1 and all(m in used for m in known if m != "MOVE_LAST_RESORT")


def _swap_chain(start, rng):
    """PowerSwap/GuardSwap's TryScorePlusN ladder: each step rolls 128 and either drops one rung or stops there
    and scores that rung (no accumulation - every rung ends the script)."""
    for n in range(start, 0, -1):
        if not _ai_skip(rng, 128):
            return n
    return 0


def _swap_score(first_diff, second_diff, rng):
    """Expert_PowerSwap / Expert_GuardSwap: the outer stage difference picks a table row, the second stat's
    difference a column; the resulting rung is then rolled down. A second difference of exactly +1 (or a negative
    one) ends the script with no change, except in the no-difference row where +1 still counts."""
    if first_diff > 3:
        rungs = (5, 4, 3)
    elif first_diff > 1:
        rungs = (4, 3, 2)
    elif first_diff > 0:
        rungs = (3, 2, 1)
    elif first_diff == 0:
        if second_diff > 3:
            return _swap_chain(3, rng)
        if second_diff > 1:
            return _swap_chain(2, rng)
        return _swap_chain(1, rng) if second_diff > 0 else 0
    else:
        return 0
    if second_diff > 3:
        return _swap_chain(rungs[0], rng)
    if second_diff > 1:
        return _swap_chain(rungs[1], rng)
    return _swap_chain(rungs[2], rng) if second_diff == 0 else 0


def _expert_trump_card(move_name, move, attacker, defender, bstate, rng):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    pp = attacker.get("move_pp", {}).get(move_name)
    if pp == 1:
        return 3
    if pp == 2:
        score = 1
        return score if _ai_skip(rng, 100) else score + 1
    if pp == 3:
        return 0 if _ai_skip(rng, 100) else 1
    score = 0
    if ai_load_ability(defender, attacker, rng) == "PRESSURE" and not _ai_skip(rng, 30):
        score += 1
    if defender.get("eva_stage", 0) > 4 or attacker.get("acc_stage", 0) < -4:
        score += 1
        return score if _ai_skip(rng, 100) else score + 1
    if defender.get("eva_stage", 0) > 2 or attacker.get("acc_stage", 0) < -2:
        return score if _ai_skip(rng, 100) else score + 1
    return score


_EXPERT_HEAL_BLOCK_EFFECTS = frozenset((
    "BATTLE_EFFECT_RECOVER_DAMAGE_SLEEP", "BATTLE_EFFECT_RESTORE_HALF_HP", "BATTLE_EFFECT_HEAL_HALF_REMOVE_FLYING_TYPE",
    "BATTLE_EFFECT_UNUSED_157", "BATTLE_EFFECT_HEAL_HALF_MORE_IN_SUN", "BATTLE_EFFECT_REST", "BATTLE_EFFECT_SWALLOW",
    "BATTLE_EFFECT_RECOVER_HALF_DAMAGE_DEALT", "BATTLE_EFFECT_GROUND_TRAP_USER_CONTINUOUS_HEAL",
    "BATTLE_EFFECT_RESTORE_HP_EVERY_TURN", "BATTLE_EFFECT_STATUS_LEECH_SEED",
    "BATTLE_EFFECT_FAINT_AND_FULL_HEAL_NEXT_MON", "BATTLE_EFFECT_FAINT_FULL_RESTORE_NEXT_MON",
))


def _expert_heal_block(attacker, defender, rng):
    triggered = (bool(_ai_defender_known_effects(defender) & _EXPERT_HEAL_BLOCK_EFFECTS) or attacker.get("leech_seeded")
                 or defender.get("aqua_ring") or defender.get("ingrain"))
    if not triggered and not _ai_skip(rng, 96):
        return 0
    return 0 if _ai_skip(rng, 25) else 1


def _expert_wring_out(move, attacker, defender, bstate, rng):
    if _ex_resisted(move, attacker, defender, bstate) or ai_hp_percent(defender) < 50:
        return -1
    hp = ai_hp_percent(defender)
    score = 0
    if hp == 100:
        score = 1 if _speed_compare(attacker, defender, bstate) == "SLOWER" else 2
    elif hp <= 85:
        return 0
    return score if _ai_skip(rng, 25) else score + 1


def _expert_power_trick(attacker, rng):
    hp = ai_hp_percent(attacker)
    if hp > 90:
        return 0 if _ai_skip(rng, 96) else 1
    if hp > 60:
        return 0 if _ai_skip(rng, 128) else 1
    if hp > 30:
        return 0 if _ai_skip(rng, 164) else 1
    return -2


def _expert_gastro_acid(defender, rng):
    if _ai_skip(rng, 64):
        return 0
    score = 1
    hp = ai_hp_percent(defender)
    if hp > 70:
        return score
    if not _ai_skip(rng, 128):
        score -= 1
    if hp > 50:
        return score
    score -= 1
    if hp > 30:
        return score
    return score - 1


_EXPERT_HIGH_CRIT_EFFECTS = frozenset(("BATTLE_EFFECT_HIGH_CRITICAL", "BATTLE_EFFECT_HIGH_CRITICAL_BURN_HIT",
                                       "BATTLE_EFFECT_HIGH_CRITICAL_POISON_HIT"))


def _expert_lucky_chant(attacker, defender, rng):
    if ai_hp_percent(attacker) < 70:
        return -1
    if _ai_defender_known_effects(defender) & _EXPERT_HIGH_CRIT_EFFECTS:
        return 1
    return 1 if _ai_skip(rng, 64) else 0


def _expert_me_first(attacker, defender, bstate, rng):
    """Expert_MeFirst. IfBattlerDealsMoreDamage names the DEFENDER, so the bonus is for when the opponent's last
    move out-damages ours (the script's own comment says the opposite)."""
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return -2
    score = 0
    if _ai_defender_deals_more(attacker, defender, bstate) and not _ai_skip(rng, 32):
        score += 1
    _, cls = _last_move_power_class(defender)
    if cls != "CLASS_STATUS" and _ai_skip(rng, 128):
        return score                         # a low roll ends the script here, before the final +1 roll
    if cls != "CLASS_STATUS":
        score += 1
    return score if _ai_skip(rng, 64) else score + 1


def _expert_copycat(attacker, defender, bstate, rng):
    """Expert_Copycat."""
    def check_encouraged():
        if _ai_defender_deals_more(attacker, defender, bstate):
            return 0
        if defender.get("last_move_used") in EXPERT_COPYCAT_ENCOURAGED_MOVES:
            return 0
        return 0 if _ai_skip(rng, 80) else -1

    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return check_encouraged()
    if _ai_defender_deals_more(attacker, defender, bstate):
        return 0 if _ai_skip(rng, 32) else 2
    if defender.get("last_move_used") not in EXPERT_COPYCAT_ENCOURAGED_MOVES:
        return check_encouraged()
    return 0 if _ai_skip(rng, 128) else 2


def _expert_power_swap(attacker, defender, rng):
    return _swap_score(defender.get("atk_stage", 0) - attacker.get("atk_stage", 0),
                       defender.get("spa_stage", 0) - attacker.get("spa_stage", 0), rng)


def _expert_guard_swap(attacker, defender, rng):
    return _swap_score(defender.get("def_stage", 0) - attacker.get("def_stage", 0),
                       defender.get("spd_stage", 0) - attacker.get("spd_stage", 0), rng)


def _expert_punishment(move, attacker, defender, bstate, rng):
    """Expert_Punishment. The TryScorePlusN labels FALL THROUGH into each other, so the rungs accumulate (the
    script's comment describes a single rung)."""
    if _ex_resisted(move, attacker, defender, bstate):
        return 0
    total = sum(max(0, defender.get(k, 0)) for k in _BC_ALL_STAGES)
    if total > 6:
        start = 4
    elif total > 5:
        start = 3
    elif total > 4:
        start = 2
    elif total > 2:
        start = 1
    else:
        return 0
    score = 0
    for n in range(start, 0, -1):
        if not _ai_skip(rng, 128):
            score += n
    return score


def _expert_last_resort(move, attacker, defender, bstate):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    return 1 if _ai_can_use_last_resort(attacker) else 0


def _expert_worry_seed(attacker, defender, rng):
    score = 1 if "MOVE_REST" in _ai_defender_known_moves(defender) else 0
    if ai_hp_percent(attacker) >= 50 and not _ai_skip(rng, 128):
        score += 1
    return score if _ai_skip(rng, 64) else score + 1


def _expert_sucker_punch(move, attacker, defender, bstate, rng):
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    return 0 if _ai_skip(rng, 64) else 1


def _expert_heart_swap(attacker, defender, rng):
    keys = ("atk_stage", "def_stage", "spa_stage", "spd_stage", "eva_stage")
    if not (any(defender.get(k, 0) > 1 for k in keys) or defender.get("focus_energy")):
        return -2
    if any(attacker.get(k, 0) < 1 for k in ("atk_stage", "def_stage", "spa_stage", "spd_stage")):
        return 1
    if attacker.get("eva_stage", 0) < 1:
        return 2
    if not attacker.get("focus_energy"):
        return 1
    return 0 if _ai_skip(rng, 50) else -2


def _expert_aqua_ring(attacker, rng):
    if ai_hp_percent(attacker) < 30:
        return 0
    return 0 if _ai_skip(rng, 128) else 1


def _expert_magnet_rise(attacker, defender, rng):
    if ai_hp_percent(attacker) < 50:
        return 0
    score = 0
    seen = _ai_defender_known_moves(defender)
    if seen & {"MOVE_EARTHQUAKE", "MOVE_EARTH_POWER", "MOVE_FISSURE"}:
        score += 1
    if "TYPE_GROUND" in _ex_types(defender):
        return score + 1
    return score if _ai_skip(rng, 128) else score + 1


def _expert_defog(attacker, defender, bstate, att_alive, dfn_alive, rng):
    """Expert_Defog."""
    score = 0
    side = bstate["sides"][bstate["side_of"](defender)]
    hazards = bool(side.get("spikes") or side.get("stealth_rock") or side.get("toxic_spikes"))
    screens = bool(side.get("light_screen") or side.get("reflect"))
    a_hp, d_hp = ai_hp_percent(attacker), ai_hp_percent(defender)

    def opponent_hp_penalty(score):
        return score if d_hp > 70 else score - 2

    def try_minus2(score):
        if not _ai_skip(rng, 50):
            score -= 2
        return opponent_hp_penalty(score)

    def check_user_hp_and_evasion(score):
        if a_hp < 70:
            return try_minus2(score)
        if defender.get("eva_stage", 0) > -3:                     # raw > 3 -> straight to the opponent-HP check
            return opponent_hp_penalty(score)
        return try_minus2(score)

    if screens:
        if a_hp <= 30 and att_alive == 0:
            return try_minus2(score)
        score += 1
        if dfn_alive == 0:
            return score
        if hazards and not _ai_skip(rng, 128):
            score -= 1
        return check_user_hp_and_evasion(score)
    if hazards:
        score -= 2
    return check_user_hp_and_evasion(score)


def _expert_trick_room(attacker, defender, bstate, att_alive, rng):
    if bstate.get("is_double_battle"):
        return 0
    if ai_hp_percent(attacker) <= 30 and att_alive == 0:
        return 0
    if _speed_compare(attacker, defender, bstate) == "SLOWER":
        return 0 if _ai_skip(rng, 64) else 3
    return -1


def _expert_blizzard(move, attacker, defender, bstate, rng):
    if _ex_resisted(move, attacker, defender, bstate):
        return 0 if _ai_skip(rng, 50) else -3
    return 1 if _ai_weather(bstate) == "HAIL" else 0


def _expert_captivate(attacker, defender, rng):
    score = 0
    if defender.get("spa_stage", 0) != 0:
        score -= 1
        if ai_hp_percent(attacker) <= 90:
            score -= 1
        if defender.get("spa_stage", 0) <= -3 and not _ai_skip(rng, 50):
            score -= 2
    if ai_hp_percent(defender) <= 70:
        score -= 2
    _, cls = _last_move_power_class(defender)
    if cls != "CLASS_PHYSICAL" or _ai_skip(rng, 64):
        return score
    return score - 1


def _expert_recoil_move(move, attacker, defender, bstate):
    if _ex_resisted(move, attacker, defender, bstate):
        return 0
    return 1 if _ai_ability(attacker) in ("ROCK_HEAD", "MAGIC_GUARD") else 0


def _expert_healing_wish(attacker, defender, bstate, party, rng):
    """Expert_HealingWish."""
    hp = ai_hp_percent(attacker)
    score = 0
    happy_path = hp < 80 or _speed_compare(attacker, defender, bstate) == "SLOWER"
    if not happy_path:
        return 0 if _ai_skip(rng, 192) else -5
    if hp > 50:
        return 0 if _ai_skip(rng, 50) else -1
    if not _ai_skip(rng, 192):
        score += 1
        if not _ai_has_super_effective_move(attacker, defender, bstate) and not _ai_skip(rng, 192):
            score += 1
        if _ai_party_deals_more(attacker, party, defender, bstate) and not _ai_skip(rng, 128):
            score += 1
    if hp > 30:
        return score
    return score if _ai_skip(rng, 128) else score + 1


def _expert_u_turn(move, attacker, defender, bstate, att_alive, party, rng):
    """Expert_UTurn. (The script's comment promises +2 for a last Pokemon; the code just ends.)"""
    if _ex_resisted(move, attacker, defender, bstate):
        return -1
    if att_alive == 0:
        return 0
    score = 0
    if _ai_has_super_effective_move(attacker, defender, bstate) and not _ai_skip(rng, 64):
        score -= 2
    if not _ai_party_deals_more(attacker, party, defender, bstate) and not _ai_skip(rng, 64):
        return score - 2
    d_hp = ai_hp_percent(defender)
    if d_hp > 70:
        if not _ai_skip(rng, 64):
            score += 1
        fifty = True
    elif d_hp > 30:
        fifty = True
    else:
        fifty = not _ai_skip(rng, 128)                           # a roll below 128 goes straight to the speed check
    if fifty and not _ai_skip(rng, 128):
        score += 1
    if _ai_speed_faster(attacker, defender, bstate, rng):
        return score + 1
    return score if _ai_skip(rng, 128) else score + 1


# ---------------- Dispatch (script.s 1628-1808, verbatim order) ----------------
# Generated directly from Expert_Main's IfCurrentMoveEffectEqualTo table.
# First match wins. Retail quirks preserved as written, e.g.:
#   * EVA_DOWN_2 -> AccuracyDown and ACC_DOWN_2 -> EvasionDown (swapped)
#   * ATK_DEF_DOWN -> DefenseDown, ATK_DEF_UP -> DefenseUp, DEF_SPD_UP and
#     SP_ATK_SP_DEF_UP -> SpDefenseUp
#   * The Expert_Thunder row repeats BATTLE_EFFECT_SKIP_CHARGE_TURN_IN_SUN,
#     so it can never be reached (retail bug - Thunder is never scored).
EXPERT_DISPATCH_ORDER = [
    ("BATTLE_EFFECT_STATUS_SLEEP", "Expert_StatusSleep"),
    ("BATTLE_EFFECT_RECOVER_HALF_DAMAGE_DEALT", "Expert_DrainMove"),
    ("BATTLE_EFFECT_HALVE_DEFENSE", "Expert_Explosion"),
    ("BATTLE_EFFECT_RECOVER_DAMAGE_SLEEP", "Expert_DreamEater"),
    ("BATTLE_EFFECT_COPY_MOVE", "Expert_MirrorMove"),
    ("BATTLE_EFFECT_ATK_UP", "Expert_StatusAttackUp"),
    ("BATTLE_EFFECT_DEF_UP", "Expert_StatusDefenseUp"),
    ("BATTLE_EFFECT_SPEED_UP", "Expert_StatusSpeedUp"),
    ("BATTLE_EFFECT_SP_ATK_UP", "Expert_StatusSpAttackUp"),
    ("BATTLE_EFFECT_SP_DEF_UP", "Expert_StatusSpDefenseUp"),
    ("BATTLE_EFFECT_ACC_UP", "Expert_StatusAccuracyUp"),
    ("BATTLE_EFFECT_EVA_UP", "Expert_StatusEvasionUp"),
    ("BATTLE_EFFECT_BYPASS_ACCURACY", "Expert_BypassAccuracyMove"),
    ("BATTLE_EFFECT_ATK_DOWN", "Expert_StatusAttackDown"),
    ("BATTLE_EFFECT_DEF_DOWN", "Expert_StatusDefenseDown"),
    ("BATTLE_EFFECT_SPEED_DOWN", "Expert_StatusSpeedDown"),
    ("BATTLE_EFFECT_SP_ATK_DOWN", "Expert_StatusSpAttackDown"),
    ("BATTLE_EFFECT_SP_DEF_DOWN", "Expert_StatusSpDefenseDown"),
    ("BATTLE_EFFECT_ACC_DOWN", "Expert_StatusAccuracyDown"),
    ("BATTLE_EFFECT_EVA_DOWN", "Expert_StatusEvasionDown"),
    ("BATTLE_EFFECT_RESET_STAT_CHANGES", "Expert_Haze"),
    ("BATTLE_EFFECT_BIDE", "Expert_Bide"),
    ("BATTLE_EFFECT_FORCE_SWITCH", "Expert_ForceSwitch"),
    ("BATTLE_EFFECT_CONVERSION", "Expert_Conversion"),
    ("BATTLE_EFFECT_RESTORE_HALF_HP", "Expert_Recovery"),
    ("BATTLE_EFFECT_STATUS_BADLY_POISON", "Expert_ToxicLeechSeed"),
    ("BATTLE_EFFECT_SET_LIGHT_SCREEN", "Expert_LightScreen"),
    ("BATTLE_EFFECT_REST", "Expert_Rest"),
    ("BATTLE_EFFECT_ONE_HIT_KO", "Expert_OHKOMove"),
    ("BATTLE_EFFECT_CHARGE_TURN_HIGH_CRIT", "Expert_ChargeTurnNoInvuln"),
    ("BATTLE_EFFECT_HALVE_HP", "Expert_SuperFang"),
    ("BATTLE_EFFECT_BIND_HIT", "Expert_BindingMove"),
    ("BATTLE_EFFECT_HIGH_CRITICAL", "Expert_HighCritical"),
    ("BATTLE_EFFECT_RECOIL_QUARTER", "Expert_RecoilMove"),
    ("BATTLE_EFFECT_STATUS_CONFUSE", "Expert_StatusConfuse"),
    ("BATTLE_EFFECT_ATK_UP_2", "Expert_StatusAttackUp"),
    ("BATTLE_EFFECT_DEF_UP_2", "Expert_StatusDefenseUp"),
    ("BATTLE_EFFECT_SPEED_UP_2", "Expert_StatusSpeedUp"),
    ("BATTLE_EFFECT_SP_ATK_UP_2", "Expert_StatusSpAttackUp"),
    ("BATTLE_EFFECT_SP_DEF_UP_2", "Expert_StatusSpDefenseUp"),
    ("BATTLE_EFFECT_ACC_UP_2", "Expert_StatusAccuracyUp"),
    ("BATTLE_EFFECT_EVA_UP_2", "Expert_StatusEvasionUp"),
    ("BATTLE_EFFECT_ATK_DOWN_2", "Expert_StatusAttackDown"),
    ("BATTLE_EFFECT_DEF_DOWN_2", "Expert_StatusDefenseDown"),
    ("BATTLE_EFFECT_SPEED_DOWN_2", "Expert_StatusSpeedDown"),
    ("BATTLE_EFFECT_SP_ATK_DOWN_2", "Expert_StatusSpAttackDown"),
    ("BATTLE_EFFECT_SP_DEF_DOWN_2", "Expert_StatusSpDefenseDown"),
    ("BATTLE_EFFECT_EVA_DOWN_2", "Expert_StatusAccuracyDown"),
    ("BATTLE_EFFECT_ACC_DOWN_2", "Expert_StatusEvasionDown"),
    ("BATTLE_EFFECT_SET_REFLECT", "Expert_Reflect"),
    ("BATTLE_EFFECT_STATUS_POISON", "Expert_StatusPoison"),
    ("BATTLE_EFFECT_STATUS_PARALYZE", "Expert_StatusParalyze"),
    ("BATTLE_EFFECT_ATK_UP_2_STATUS_CONFUSION", "Expert_Swagger"),
    ("BATTLE_EFFECT_LOWER_SPEED_HIT", "Expert_SpeedDownOnHit"),
    ("BATTLE_EFFECT_CHARGE_TURN_HIGH_CRIT_FLINCH", "Expert_ChargeTurnNoInvuln"),
    ("BATTLE_EFFECT_PRIORITY_NEG_1_BYPASS_ACCURACY", "Expert_VitalThrow"),
    ("BATTLE_EFFECT_SET_SUBSTITUTE", "Expert_Substitute"),
    ("BATTLE_EFFECT_RECHARGE_AFTER", "Expert_RechargeTurn"),
    ("BATTLE_EFFECT_STATUS_LEECH_SEED", "Expert_ToxicLeechSeed"),
    ("BATTLE_EFFECT_DISABLE", "Expert_Disable"),
    ("BATTLE_EFFECT_COUNTER", "Expert_Counter"),
    ("BATTLE_EFFECT_ENCORE", "Expert_Encore"),
    ("BATTLE_EFFECT_AVERAGE_HP", "Expert_PainSplit"),
    ("BATTLE_EFFECT_DAMAGE_WHILE_ASLEEP", "Expert_Nightmare"),
    ("BATTLE_EFFECT_NEXT_ATTACK_ALWAYS_HITS", "Expert_LockOn"),
    ("BATTLE_EFFECT_USE_RANDOM_LEARNED_MOVE_SLEEP", "Expert_SleepTalk"),
    ("BATTLE_EFFECT_KO_MON_THAT_DEFEATED_USER", "Expert_DestinyBond"),
    ("BATTLE_EFFECT_INCREASE_POWER_WITH_LESS_HP", "Expert_Reversal"),
    ("BATTLE_EFFECT_CURE_PARTY_STATUS", "Expert_HealBell"),
    ("BATTLE_EFFECT_STEAL_HELD_ITEM", "Expert_Thief"),
    ("BATTLE_EFFECT_PREVENT_ESCAPE", "Expert_BindingMove"),
    ("BATTLE_EFFECT_EVA_UP_2_MINIMIZE", "Expert_StatusEvasionUp"),
    ("BATTLE_EFFECT_CURSE", "Expert_Curse"),
    ("BATTLE_EFFECT_PROTECT", "Expert_Protect"),
    ("BATTLE_EFFECT_SET_SPIKES", "Expert_Spikes"),
    ("BATTLE_EFFECT_FORESIGHT", "Expert_Foresight"),
    ("BATTLE_EFFECT_SURVIVE_WITH_1_HP", "Expert_Endure"),
    ("BATTLE_EFFECT_PASS_STATS_AND_STATUS", "Expert_BatonPass"),
    ("BATTLE_EFFECT_HIT_BEFORE_SWITCH", "Expert_Pursuit"),
    ("BATTLE_EFFECT_HEAL_HALF_MORE_IN_SUN", "Expert_Synthesis"),
    ("BATTLE_EFFECT_UNUSED_133", "Expert_Synthesis"),
    ("BATTLE_EFFECT_UNUSED_134", "Expert_Synthesis"),
    ("BATTLE_EFFECT_WEATHER_RAIN", "Expert_RainDance"),
    ("BATTLE_EFFECT_WEATHER_SUN", "Expert_SunnyDay"),
    ("BATTLE_EFFECT_MAX_ATK_LOSE_HALF_MAX_HP", "Expert_BellyDrum"),
    ("BATTLE_EFFECT_COPY_STAT_CHANGES", "Expert_PsychUp"),
    ("BATTLE_EFFECT_MIRROR_COAT", "Expert_MirrorCoat"),
    ("BATTLE_EFFECT_CHARGE_TURN_DEF_UP", "Expert_ChargeTurnNoInvuln"),
    ("BATTLE_EFFECT_SKIP_CHARGE_TURN_IN_SUN", "Expert_ChargeTurnNoInvuln"),
    ("BATTLE_EFFECT_SKIP_CHARGE_TURN_IN_SUN", "Expert_Thunder"),
    ("BATTLE_EFFECT_FLY", "Expert_ChargeTurnWithInvuln"),
    ("BATTLE_EFFECT_UNUSED_157", "Expert_Recovery"),
    ("BATTLE_EFFECT_ALWAYS_FLINCH_FIRST_TURN_ONLY", "Expert_FakeOut"),
    ("BATTLE_EFFECT_SPIT_UP", "Expert_SpitUp"),
    ("BATTLE_EFFECT_SWALLOW", "Expert_Recovery"),
    ("BATTLE_EFFECT_WEATHER_HAIL", "Expert_Hail"),
    ("BATTLE_EFFECT_SP_ATK_UP_CAUSE_CONFUSION", "Expert_Flatter"),
    ("BATTLE_EFFECT_FAINT_AND_ATK_SP_ATK_DOWN_2", "Expert_Explosion"),
    ("BATTLE_EFFECT_DOUBLE_POWER_WHEN_STATUSED", "Expert_Facade"),
    ("BATTLE_EFFECT_HIT_LAST_WHIFF_IF_HIT", "Expert_FocusPunch"),
    ("BATTLE_EFFECT_DOUBLE_POWER_AND_CURE_PARALYSIS", "Expert_SmellingSalts"),
    ("BATTLE_EFFECT_SWITCH_HELD_ITEMS", "Expert_Trick"),
    ("BATTLE_EFFECT_COPY_ABILITY", "Expert_ChangeUserAbility"),
    ("BATTLE_EFFECT_GROUND_TRAP_USER_CONTINUOUS_HEAL", "Expert_Ingrain"),
    ("BATTLE_EFFECT_LOWER_OWN_ATK_AND_DEF", "Expert_Superpower"),
    ("BATTLE_EFFECT_APPLY_MAGIC_COAT", "Expert_MagicCoat"),
    ("BATTLE_EFFECT_RECYCLE", "Expert_Recycle"),
    ("BATTLE_EFFECT_DOUBLE_POWER_IF_HIT", "Expert_Revenge"),
    ("BATTLE_EFFECT_REMOVE_SCREENS", "Expert_BrickBreak"),
    ("BATTLE_EFFECT_REMOVE_HELD_ITEM", "Expert_KnockOff"),
    ("BATTLE_EFFECT_SET_HP_EQUAL_TO_USER", "Expert_Endeavor"),
    ("BATTLE_EFFECT_DECREASE_POWER_WITH_LESS_USER_HP", "Expert_WaterSpout"),
    ("BATTLE_EFFECT_SWITCH_ABILITIES", "Expert_ChangeUserAbility"),
    ("BATTLE_EFFECT_MAKE_SHARED_MOVES_UNUSEABLE", "Expert_Imprison"),
    ("BATTLE_EFFECT_HEAL_STATUS", "Expert_Refresh"),
    ("BATTLE_EFFECT_STEAL_STATUS_MOVE", "Expert_Snatch"),
    ("BATTLE_EFFECT_RECOIL_THIRD", "Expert_RecoilMove"),
    ("BATTLE_EFFECT_HIGH_CRITICAL_BURN_HIT", "Expert_HighCritical"),
    ("BATTLE_EFFECT_HALVE_ELECTRIC_DAMAGE", "Expert_MudSport"),
    ("BATTLE_EFFECT_USER_SP_ATK_DOWN_2", "Expert_Overheat"),
    ("BATTLE_EFFECT_ATK_DEF_DOWN", "Expert_StatusDefenseDown"),
    ("BATTLE_EFFECT_DEF_SPD_UP", "Expert_StatusSpDefenseUp"),
    ("BATTLE_EFFECT_ATK_DEF_UP", "Expert_StatusDefenseUp"),
    ("BATTLE_EFFECT_HIGH_CRITICAL_POISON_HIT", "Expert_HighCritical"),
    ("BATTLE_EFFECT_HALVE_FIRE_DAMAGE", "Expert_WaterSport"),
    ("BATTLE_EFFECT_SP_ATK_SP_DEF_UP", "Expert_StatusSpDefenseUp"),
    ("BATTLE_EFFECT_ATK_SPD_UP", "Expert_DragonDance"),
    ("BATTLE_EFFECT_HEAL_HALF_REMOVE_FLYING_TYPE", "Expert_Recovery"),
    ("BATTLE_EFFECT_GRAVITY", "Expert_Gravity"),
    ("BATTLE_EFFECT_IGNORE_EVATION_REMOVE_DARK_IMMUNE", "Expert_MiracleEye"),
    ("BATTLE_EFFECT_DOUBLE_POWER_HEAL_SLEEP", "Expert_WakeUpSlap"),
    ("BATTLE_EFFECT_SPEED_DOWN_HIT", "Expert_HammerArm"),
    ("BATTLE_EFFECT_POWER_BASED_ON_LOW_SPEED", "Expert_GyroBall"),
    ("BATTLE_EFFECT_FAINT_AND_FULL_HEAL_NEXT_MON", "Expert_HealingWish"),
    ("BATTLE_EFFECT_DOUBLE_POWER_WHEN_BELOW_HALF", "Expert_Brine"),
    ("BATTLE_EFFECT_REMOVE_PROTECT", "Expert_Feint"),
    ("BATTLE_EFFECT_EAT_BERRY", "Expert_Pluck"),
    ("BATTLE_EFFECT_DOUBLE_SPEED_3_TURNS", "Expert_Tailwind"),
    ("BATTLE_EFFECT_RANDOM_STAT_UP_2", "Expert_Acupressure"),
    ("BATTLE_EFFECT_METAL_BURST", "Expert_MetalBurst"),
    ("BATTLE_EFFECT_SWITCH_HIT", "Expert_UTurn"),
    ("BATTLE_EFFECT_DEF_SPD_DOWN_HIT", "Expert_CloseCombat"),
    ("BATTLE_EFFECT_DOUBLE_POWER_IF_MOVING_SECOND", "Expert_Payback"),
    ("BATTLE_EFFECT_DOUBLE_POWER_IF_TARGET_HIT", "Expert_Assurance"),
    ("BATTLE_EFFECT_PREVENT_ITEM_USE", "Expert_Embargo"),
    ("BATTLE_EFFECT_FLING", "Expert_Fling"),
    ("BATTLE_EFFECT_TRANSFER_STATUS", "Expert_PsychoShift"),
    ("BATTLE_EFFECT_HIGHER_POWER_WHEN_LOW_PP", "Expert_TrumpCard"),
    ("BATTLE_EFFECT_PREVENT_HEALING", "Expert_HealBlock"),
    ("BATTLE_EFFECT_INCREASE_POWER_WITH_MORE_HP", "Expert_WringOut"),
    ("BATTLE_EFFECT_SWAP_ATK_DEF", "Expert_PowerTrick"),
    ("BATTLE_EFFECT_SUPRESS_ABILITY", "Expert_GastroAcid"),
    ("BATTLE_EFFECT_PREVENT_CRITS", "Expert_LuckyChant"),
    ("BATTLE_EFFECT_USE_MOVE_FIRST", "Expert_MeFirst"),
    ("BATTLE_EFFECT_USE_LAST_USED_MOVE", "Expert_Copycat"),
    ("BATTLE_EFFECT_SWAP_ATK_SP_ATK_STAT_CHANGES", "Expert_PowerSwap"),
    ("BATTLE_EFFECT_SWAP_DEF_SP_DEF_STAT_CHANGES", "Expert_GuardSwap"),
    ("BATTLE_EFFECT_INCREASE_POWER_WITH_MORE_STAT_UP", "Expert_Punishment"),
    ("BATTLE_EFFECT_FAIL_IF_NOT_USED_ALL_OTHER_MOVES", "Expert_LastResort"),
    ("BATTLE_EFFECT_SET_ABILITY_TO_INSOMNIA", "Expert_WorrySeed"),
    ("BATTLE_EFFECT_HIT_FIRST_IF_TARGET_ATTACKING", "Expert_SuckerPunch"),
    ("BATTLE_EFFECT_TOXIC_SPIKES", "Expert_ToxicSpikes"),
    ("BATTLE_EFFECT_SWAP_STAT_CHANGES", "Expert_HeartSwap"),
    ("BATTLE_EFFECT_RESTORE_HP_EVERY_TURN", "Expert_AquaRing"),
    ("BATTLE_EFFECT_GIVE_GROUND_IMMUNITY", "Expert_MagnetRise"),
    ("BATTLE_EFFECT_RECOIL_BURN_HIT", "Expert_RecoilMove"),
    ("BATTLE_EFFECT_DIVE", "Expert_ChargeTurnWithInvuln"),
    ("BATTLE_EFFECT_DIG", "Expert_ChargeTurnWithInvuln"),
    ("BATTLE_EFFECT_REMOVE_HAZARDS_SCREENS_EVA_DOWN", "Expert_Defog"),
    ("BATTLE_EFFECT_TRICK_ROOM", "Expert_TrickRoom"),
    ("BATTLE_EFFECT_BLIZZARD", "Expert_Blizzard"),
    ("BATTLE_EFFECT_RECOIL_PARALYZE_HIT", "Expert_RecoilMove"),
    ("BATTLE_EFFECT_BOUNCE", "Expert_ChargeTurnWithInvuln"),
    ("BATTLE_EFFECT_SP_ATK_DOWN_2_OPPOSITE_GENDER", "Expert_Captivate"),
    ("BATTLE_EFFECT_STEALTH_ROCK", "Expert_StealthRock"),
    ("BATTLE_EFFECT_RECOIL_HALF", "Expert_RecoilMove"),
    ("BATTLE_EFFECT_FAINT_FULL_RESTORE_NEXT_MON", "Expert_HealingWish"),
    ("BATTLE_EFFECT_SHADOW_FORCE", "Expert_ShadowForce"),
]

EXPERT_DISPATCH = {}
for _effect, _label in EXPERT_DISPATCH_ORDER:
    EXPERT_DISPATCH.setdefault(_effect, _label)      # first match wins; later duplicates are dead


def _h_status_sleep(move_name, move, attacker, defender, bstate, rng):
    return expert_status_sleep_score(attacker, rng)


def _h_drain(move_name, move, attacker, defender, bstate, rng):
    return expert_drain_move_score(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate, rng)


def _h_explosion(move_name, move, attacker, defender, bstate, rng):
    return expert_explosion_score(attacker, defender, bstate, rng)


def _h_dream_eater(move_name, move, attacker, defender, bstate, rng):
    return expert_dream_eater_score(move.get("type", "TYPE_NORMAL"), attacker, defender, bstate, rng)


def _h_mirror_move(move_name, move, attacker, defender, bstate, rng):
    return expert_mirror_move_score(attacker, defender, bstate, rng)


# Handlers ported so far, by real script label. Anything in the dispatch
# table without an entry here is not yet ported and scores 0.
EXPERT_HANDLERS = {
    "Expert_StatusSleep": _h_status_sleep,
    "Expert_DrainMove": _h_drain,
    "Expert_Explosion": _h_explosion,
    "Expert_DreamEater": _h_dream_eater,
    "Expert_MirrorMove": _h_mirror_move,
    "Expert_StatusAttackUp": lambda n, m, a, d, b, r: _expert_offense_up(a, "atk_stage", 40, r),
    "Expert_StatusDefenseUp": lambda n, m, a, d, b, r: _expert_defense_up(a, d, "def_stage", "CLASS_SPECIAL", r),
    "Expert_StatusSpeedUp": lambda n, m, a, d, b, r: _expert_speed_up(a, d, b, r),
    "Expert_StatusSpAttackUp": lambda n, m, a, d, b, r: _expert_offense_up(a, "spa_stage", 70, r),
    "Expert_StatusSpDefenseUp": lambda n, m, a, d, b, r: _expert_defense_up(a, d, "spd_stage", "CLASS_PHYSICAL", r),
    "Expert_StatusAccuracyUp": lambda n, m, a, d, b, r: _expert_accuracy_up(a, r),
    "Expert_StatusEvasionUp": lambda n, m, a, d, b, r: _expert_evasion_up(a, d, r),
    "Expert_BypassAccuracyMove": lambda n, m, a, d, b, r: _expert_bypass_accuracy(a, d, r),
    "Expert_StatusAttackDown": lambda n, m, a, d, b, r: _expert_offense_down(a, d, "atk_stage", "CLASS_SPECIAL", r),
    "Expert_StatusDefenseDown": lambda n, m, a, d, b, r: _expert_defense_down(a, d, "def_stage", r),
    "Expert_SpeedDownOnHit": _expert_speed_down_on_hit,
    "Expert_StatusSpeedDown": lambda n, m, a, d, b, r: _expert_speed_down(a, d, b, r),
    "Expert_StatusSpAttackDown": lambda n, m, a, d, b, r: _expert_offense_down(a, d, "spa_stage", "CLASS_PHYSICAL", r),
    "Expert_StatusSpDefenseDown": lambda n, m, a, d, b, r: _expert_defense_down(a, d, "spd_stage", r),
    "Expert_StatusAccuracyDown": lambda n, m, a, d, b, r: _expert_accuracy_down(a, d, r),
    "Expert_StatusEvasionDown": lambda n, m, a, d, b, r: _expert_defense_down(a, d, "eva_stage", r),
    "Expert_Haze": lambda n, m, a, d, b, r: _expert_haze(a, d, r),
    "Expert_Bide": lambda n, m, a, d, b, r: _expert_bide(a),
    "Expert_ForceSwitch": lambda n, m, a, d, b, r: _expert_force_switch(d, b, r),
    "Expert_Conversion": lambda n, m, a, d, b, r: _expert_conversion(a, b, r),
    "Expert_Synthesis": lambda n, m, a, d, b, r: _expert_synthesis(a, d, b, r),
    "Expert_Recovery": lambda n, m, a, d, b, r: _expert_recovery(a, d, b, r),
    "Expert_ToxicLeechSeed": lambda n, m, a, d, b, r: _expert_toxic_leech_seed(a, d, r),
    "Expert_LightScreen": lambda n, m, a, d, b, r: _expert_screen(a, d, "CLASS_SPECIAL", r),
    "Expert_Reflect": lambda n, m, a, d, b, r: _expert_screen(a, d, "CLASS_PHYSICAL", r),
    "Expert_Rest": lambda n, m, a, d, b, r: _expert_rest(a, d, b, r),
    "Expert_OHKOMove": lambda n, m, a, d, b, r: _expert_ohko(r),
    "Expert_SuperFang": lambda n, m, a, d, b, r: _expert_super_fang(d),
    "Expert_BindingMove": lambda n, m, a, d, b, r: _expert_binding_move(d, r),
    "Expert_HighCritical": lambda n, m, a, d, b, r: _expert_high_critical(m, a, d, b, r),
    "Expert_StatusConfuse": lambda n, m, a, d, b, r: _expert_status_confuse(d, r),
    "Expert_Flatter": lambda n, m, a, d, b, r: _expert_flatter(d, r),
    "Expert_Swagger": lambda n, m, a, d, b, r: _expert_swagger(a, d, b, r),
    "Expert_StatusPoison": lambda n, m, a, d, b, r: _expert_status_poison(a, d),
    "Expert_StatusParalyze": lambda n, m, a, d, b, r: _expert_status_paralyze(a, d, b, r),
    "Expert_VitalThrow": lambda n, m, a, d, b, r: _expert_vital_throw(a, d, b, r),
    "Expert_Substitute": lambda n, m, a, d, b, r: _expert_substitute(a, d, b, r),
    "Expert_RechargeTurn": lambda n, m, a, d, b, r: _expert_recharge_turn(m, a, d, b, r),
    "Expert_Disable": lambda n, m, a, d, b, r: _expert_disable(a, d, b, r),
    "Expert_Counter": lambda n, m, a, d, b, r: _expert_counter(a, d, r),
    "Expert_Encore": lambda n, m, a, d, b, r: _expert_encore(a, d, b, r),
    "Expert_PainSplit": lambda n, m, a, d, b, r: _expert_pain_split(a, d, b),
    "Expert_Nightmare": lambda n, m, a, d, b, r: 2,
    "Expert_LockOn": lambda n, m, a, d, b, r: 0 if _ai_skip(r, 128) else 2,
    "Expert_SleepTalk": lambda n, m, a, d, b, r: _expert_sleep_talk(a),
    "Expert_DestinyBond": lambda n, m, a, d, b, r: _expert_destiny_bond(a, d, b, r),
    "Expert_Reversal": lambda n, m, a, d, b, r: _expert_reversal(a, d, b, r),
    "Expert_Thief": lambda n, m, a, d, b, r: _expert_thief(d, r),
    "Expert_Curse": lambda n, m, a, d, b, r: _expert_curse(a, r),
    "Expert_Protect": lambda n, m, a, d, b, r: _expert_protect(a, d, b, r),
    "Expert_Spikes": lambda n, m, a, d, b, r: _expert_spikes(a, r),
    "Expert_Foresight": lambda n, m, a, d, b, r: _expert_foresight(a, d, r),
    "Expert_Endure": lambda n, m, a, d, b, r: _expert_endure(a, r),
    "Expert_BatonPass": lambda n, m, a, d, b, r: _expert_baton_pass(a, d, b, r),
    "Expert_Pursuit": lambda n, m, a, d, b, r: _expert_pursuit(a, d, r),
    "Expert_RainDance": lambda n, m, a, d, b, r: _expert_rain_dance(a, d, b, r),
    "Expert_SunnyDay": lambda n, m, a, d, b, r: _expert_sunny_day(a, b),
    "Expert_BellyDrum": lambda n, m, a, d, b, r: _expert_belly_drum(a),
    "Expert_PsychUp": lambda n, m, a, d, b, r: _expert_psych_up(a, d, r),
    "Expert_MirrorCoat": lambda n, m, a, d, b, r: _expert_mirror_coat(a, d, r),
    "Expert_ChargeTurnNoInvuln": lambda n, m, a, d, b, r: _expert_charge_turn_no_invuln(n, m, a, d, b),
    "Expert_ChargeTurnWithInvuln": lambda n, m, a, d, b, r: _expert_charge_turn_with_invuln(a, d, m, b, r),
    "Expert_ShadowForce": lambda n, m, a, d, b, r: _expert_charge_turn_with_invuln(a, d, m, b, r, shadow_force=True),
    "Expert_FakeOut": lambda n, m, a, d, b, r: 2,
    "Expert_SpitUp": lambda n, m, a, d, b, r: _expert_spit_up(a, r),
    "Expert_Hail": lambda n, m, a, d, b, r: _expert_hail(a, b),
    "Expert_Facade": lambda n, m, a, d, b, r: _expert_facade(d),
    "Expert_FocusPunch": lambda n, m, a, d, b, r: _expert_focus_punch(m, a, d, b, r),
    "Expert_SmellingSalts": lambda n, m, a, d, b, r: _expert_smelling_salts(d),
    "Expert_Trick": lambda n, m, a, d, b, r: _expert_trick(a, d, r),
    "Expert_ChangeUserAbility": lambda n, m, a, d, b, r: _expert_change_user_ability(a, d, r),
    "Expert_Ingrain": lambda n, m, a, d, b, r: 0,
    "Expert_Superpower": lambda n, m, a, d, b, r: _expert_superpower(m, a, d, b),
    "Expert_MagicCoat": lambda n, m, a, d, b, r: _expert_magic_coat(a, d, r),
    "Expert_Recycle": lambda n, m, a, d, b, r: _expert_recycle(a, r),
    "Expert_Revenge": lambda n, m, a, d, b, r: _expert_revenge(d, r),
    "Expert_BrickBreak": lambda n, m, a, d, b, r: _expert_brick_break(d, b, b["side_of"](d)),
    "Expert_KnockOff": lambda n, m, a, d, b, r: _expert_knock_off(a, d, r),
    "Expert_Endeavor": lambda n, m, a, d, b, r: _expert_endeavor(a, d, b),
    "Expert_WaterSpout": lambda n, m, a, d, b, r: _expert_water_spout(m, a, d, b),
    "Expert_Imprison": lambda n, m, a, d, b, r: _expert_imprison(a, r),
    "Expert_Refresh": lambda n, m, a, d, b, r: _expert_refresh(d),
    "Expert_Snatch": lambda n, m, a, d, b, r: _expert_snatch(a, d, b, r),
    "Expert_MudSport": lambda n, m, a, d, b, r: _expert_mud_or_water_sport(a, d, "TYPE_ELECTRIC"),
    "Expert_WaterSport": lambda n, m, a, d, b, r: _expert_mud_or_water_sport(a, d, "TYPE_FIRE"),
    "Expert_Overheat": lambda n, m, a, d, b, r: _expert_overheat_like(m, a, d, b, 80, 60),
    "Expert_CloseCombat": lambda n, m, a, d, b, r: _expert_overheat_like(m, a, d, b, 80, 60),
    "Expert_DragonDance": lambda n, m, a, d, b, r: _expert_dragon_dance(a, d, b, r),
    "Expert_Gravity": lambda n, m, a, d, b, r: _expert_gravity(a, d, r),
    "Expert_MiracleEye": lambda n, m, a, d, b, r: _expert_miracle_eye(d, r),
    "Expert_WakeUpSlap": lambda n, m, a, d, b, r: _expert_wake_up_slap(m, a, d, b),
    "Expert_HammerArm": lambda n, m, a, d, b, r: _expert_hammer_arm(m, a, d, b),
    "Expert_GyroBall": lambda n, m, a, d, b, r: 0,
    "Expert_Brine": lambda n, m, a, d, b, r: _expert_brine(m, a, d, b, r),
    "Expert_Feint": lambda n, m, a, d, b, r: _expert_feint(a, d, r),
    "Expert_Pluck": lambda n, m, a, d, b, r: _expert_pluck(m, a, d, b, r),
    "Expert_Tailwind": lambda n, m, a, d, b, r: _expert_tailwind(a, d, b, r),
    "Expert_Acupressure": lambda n, m, a, d, b, r: _expert_acupressure(a, r),
    "Expert_MetalBurst": lambda n, m, a, d, b, r: _expert_metal_burst(a, d, r),
    "Expert_Payback": lambda n, m, a, d, b, r: _expert_payback(m, a, d, b, r),
    "Expert_Assurance": lambda n, m, a, d, b, r: _expert_assurance(m, a, d, b, r),
    "Expert_Embargo": lambda n, m, a, d, b, r: 0 if _ai_skip(r, 128) else 1,
    "Expert_Fling": lambda n, m, a, d, b, r: _expert_fling(m, a, d, b, r),
    "Expert_PsychoShift": lambda n, m, a, d, b, r: _expert_psycho_shift(a, d, r),
    "Expert_TrumpCard": lambda n, m, a, d, b, r: _expert_trump_card(n, m, a, d, b, r),
    "Expert_HealBlock": lambda n, m, a, d, b, r: _expert_heal_block(a, d, r),
    "Expert_WringOut": lambda n, m, a, d, b, r: _expert_wring_out(m, a, d, b, r),
    "Expert_PowerTrick": lambda n, m, a, d, b, r: _expert_power_trick(a, r),
    "Expert_GastroAcid": lambda n, m, a, d, b, r: _expert_gastro_acid(d, r),
    "Expert_LuckyChant": lambda n, m, a, d, b, r: _expert_lucky_chant(a, d, r),
    "Expert_MeFirst": lambda n, m, a, d, b, r: _expert_me_first(a, d, b, r),
    "Expert_Copycat": lambda n, m, a, d, b, r: _expert_copycat(a, d, b, r),
    "Expert_PowerSwap": lambda n, m, a, d, b, r: _expert_power_swap(a, d, r),
    "Expert_GuardSwap": lambda n, m, a, d, b, r: _expert_guard_swap(a, d, r),
    "Expert_Punishment": lambda n, m, a, d, b, r: _expert_punishment(m, a, d, b, r),
    "Expert_LastResort": lambda n, m, a, d, b, r: _expert_last_resort(m, a, d, b),
    "Expert_WorrySeed": lambda n, m, a, d, b, r: _expert_worry_seed(a, d, r),
    "Expert_SuckerPunch": lambda n, m, a, d, b, r: _expert_sucker_punch(m, a, d, b, r),
    "Expert_ToxicSpikes": lambda n, m, a, d, b, r: _expert_spikes(a, r),
    "Expert_StealthRock": lambda n, m, a, d, b, r: _expert_spikes(a, r),
    "Expert_HeartSwap": lambda n, m, a, d, b, r: _expert_heart_swap(a, d, r),
    "Expert_AquaRing": lambda n, m, a, d, b, r: _expert_aqua_ring(a, r),
    "Expert_MagnetRise": lambda n, m, a, d, b, r: _expert_magnet_rise(a, d, r),
    "Expert_Blizzard": lambda n, m, a, d, b, r: _expert_blizzard(m, a, d, b, r),
    "Expert_Captivate": lambda n, m, a, d, b, r: _expert_captivate(a, d, r),
    "Expert_RecoilMove": lambda n, m, a, d, b, r: _expert_recoil_move(m, a, d, b),
}

# Handlers that also need the user's party, active ally and the two 'other Pokemon alive'
# counts (CountAlivePartyBattlers): called with (ally, attacker_party, att_alive, dfn_alive)
# on top of the usual arguments.
EXPERT_PARTY_HANDLERS = {
    "Expert_HealBell": lambda n, m, a, d, b, r, ally, party, aa, da: _expert_heal_bell(a, ally, party),
    "Expert_HealingWish": lambda n, m, a, d, b, r, ally, party, aa, da: _expert_healing_wish(a, d, b, party, r),
    "Expert_UTurn": lambda n, m, a, d, b, r, ally, party, aa, da: _expert_u_turn(m, a, d, b, aa, party, r),
    "Expert_Defog": lambda n, m, a, d, b, r, ally, party, aa, da: _expert_defog(a, d, b, aa, da, r),
    "Expert_TrickRoom": lambda n, m, a, d, b, r, ally, party, aa, da: _expert_trick_room(a, d, b, aa, r),
}


def expert_flag_score(move_name, move, attacker, defender, bstate, rng, attacker_party=None, ally=None,
                      att_alive=0, dfn_alive=0):
    """Faithful port of Expert_Main - by far the largest AI script
    (~4,729 lines in the real source), built up handler by handler.
    Dispatches on the move's REAL BATTLE_EFFECT_* tag through
    EXPERT_DISPATCH (first match wins). Effects whose handler has not been
    ported yet (see EXPERT_HANDLERS) fall through to 0.
    The caller (choose_move) skips this flag entirely when scoring a move
    against the user's own partner, as Expert_Main's first line does."""
    label = EXPERT_DISPATCH.get(_real_effect(move_name))
    if label is None:
        return 0
    party_handler = EXPERT_PARTY_HANDLERS.get(label)
    if party_handler is not None:
        return party_handler(move_name, move, attacker, defender, bstate, rng, ally, attacker_party, att_alive, dfn_alive)
    handler = EXPERT_HANDLERS.get(label)
    if handler is None:
        return 0
    return handler(move_name, move, attacker, defender, bstate, rng)



# ============================================================
# AI SCORING: remaining simpler flags
# ============================================================
SETUP_EFFECTS = {"REFLECT", "LIGHT_SCREEN", "SUBSTITUTE", "LEECH_SEED", "WEATHER_RAIN", "WEATHER_SUN",
                  "SLEEP", "POISON", "TOXIC", "PARALYZE", "BURN", "CONFUSE", "STOCKPILE",
                  "MIST", "LUCKY_CHANT", "TRICK_ROOM", "GRAVITY", "IMPRISON"}
AI_SETUP_FIRST_TURN_MOVES = {
    # Ported verbatim from SetupFirstTurn_SetupEffects, resolved against
    # real move data - replaces an approximation built from this file's
    # own internal effect-tag vocabulary, which missed most of the real
    # ~50-move list (e.g. Swords Dance, Calm Mind, Bulk Up, Tailwind,
    # Acupressure weren't in it at all) and included some things (a
    # generic "any weather move") that aren't part of the real table as
    # such. Notably includes Whirlpool, which isn't a stat-boosting move
    # at all but is in the real game's own table regardless - faithful
    # here means keeping that, not "fixing" it.
    "MOVE_MEDITATE", "MOVE_SHARPEN", "MOVE_HOWL", "MOVE_HARDEN", "MOVE_WITHDRAW", "MOVE_GROWTH",
    "MOVE_DOUBLE_TEAM", "MOVE_GROWL", "MOVE_TAIL_WHIP", "MOVE_LEER", "MOVE_STRING_SHOT",
    "MOVE_SAND_ATTACK", "MOVE_SMOKE_SCREEN", "MOVE_KINESIS", "MOVE_FLASH", "MOVE_SWEET_SCENT",
    "MOVE_CONVERSION", "MOVE_LIGHT_SCREEN", "MOVE_AMNESIA", "MOVE_FOCUS_ENERGY",
    "MOVE_SUPERSONIC", "MOVE_CONFUSE_RAY", "MOVE_SWEET_KISS", "MOVE_SWORDS_DANCE",
    "MOVE_BARRIER", "MOVE_ACID_ARMOR", "MOVE_IRON_DEFENSE", "MOVE_AGILITY", "MOVE_ROCK_POLISH",
    "MOVE_TAIL_GLOW", "MOVE_NASTY_PLOT", "MOVE_CHARM", "MOVE_FEATHER_DANCE", "MOVE_SCREECH",
    "MOVE_COTTON_SPORE", "MOVE_SCARY_FACE", "MOVE_FAKE_TEARS", "MOVE_METAL_SOUND", "MOVE_REFLECT",
    "MOVE_POISON_POWDER", "MOVE_POISON_GAS", "MOVE_STUN_SPORE", "MOVE_THUNDER_WAVE", "MOVE_GLARE",
    "MOVE_SUBSTITUTE", "MOVE_LEECH_SEED", "MOVE_MINIMIZE", "MOVE_CURSE", "MOVE_SWAGGER", "MOVE_CAMOUFLAGE",
    "MOVE_YAWN", "MOVE_DEFENSE_CURL", "MOVE_TORMENT", "MOVE_FLATTER", "MOVE_WILL_O_WISP", "MOVE_INGRAIN",
    "MOVE_IMPRISON", "MOVE_TEETER_DANCE", "MOVE_TICKLE", "MOVE_COSMIC_POWER", "MOVE_DEFEND_ORDER",
    "MOVE_BULK_UP", "MOVE_CALM_MIND", "MOVE_TAILWIND", "MOVE_ACUPRESSURE", "MOVE_LUCKY_CHANT",
    "MOVE_MAGNET_RISE", "MOVE_DEFOG", "MOVE_WHIRLPOOL",
}
RISKY_EFFECTS = {"SLEEP", "CONFUSE"}
AI_RISKY_MOVES = {
    # Ported verbatim from Risky_RiskyEffects in the real AI script,
    # resolved against real move data (some BATTLE_EFFECT_ entries cover
    # several moves, e.g. every OHKO move or every high-crit move).
    "MOVE_SING", "MOVE_SLEEP_POWDER", "MOVE_HYPNOSIS", "MOVE_LOVELY_KISS", "MOVE_SPORE", "MOVE_GRASS_WHISTLE",
    "MOVE_DARK_VOID", "MOVE_SELFDESTRUCT", "MOVE_EXPLOSION", "MOVE_MIRROR_MOVE",
    "MOVE_GUILLOTINE", "MOVE_HORN_DRILL", "MOVE_FISSURE", "MOVE_SHEER_COLD",
    "MOVE_KARATE_CHOP", "MOVE_RAZOR_LEAF", "MOVE_CRABHAMMER", "MOVE_SLASH", "MOVE_AEROBLAST", "MOVE_CROSS_CHOP",
    "MOVE_AIR_CUTTER", "MOVE_LEAF_BLADE", "MOVE_NIGHT_SLASH", "MOVE_SHADOW_CLAW", "MOVE_PSYCHO_CUT",
    "MOVE_STONE_EDGE", "MOVE_ATTACK_ORDER", "MOVE_SPACIAL_REND",
    "MOVE_SUPERSONIC", "MOVE_CONFUSE_RAY", "MOVE_SWEET_KISS", "MOVE_METRONOME", "MOVE_PSYWAVE", "MOVE_COUNTER",
    "MOVE_DESTINY_BOND", "MOVE_SWAGGER", "MOVE_ATTRACT", "MOVE_PRESENT",
    "MOVE_ANCIENT_POWER", "MOVE_SILVER_WIND", "MOVE_OMINOUS_WIND",
    "MOVE_BELLY_DRUM", "MOVE_MIRROR_COAT", "MOVE_FOCUS_PUNCH", "MOVE_REVENGE", "MOVE_AVALANCHE",
    "MOVE_TEETER_DANCE", "MOVE_GYRO_BALL", "MOVE_ACUPRESSURE", "MOVE_METAL_BURST", "MOVE_PAYBACK",
    "MOVE_ME_FIRST", "MOVE_SUCKER_PUNCH",
}


def setup_first_turn_flag_score(move_name, bstate, is_partner_target, rng):
    """Faithful port of SetupFirstTurn_Main: ignored against a partner
    target, only applies on turn 1 of the battle, and only for a move in
    the fixed AI_SETUP_FIRST_TURN_MOVES list - +2 at 176/256 (~68.75%)."""
    if is_partner_target:
        return 0
    if bstate.get("turn", 1) != 1:
        return 0
    if move_name not in AI_SETUP_FIRST_TURN_MOVES:
        return 0
    if rng.randint(0, 255) < 80:
        return 0
    return 2


def risky_flag_score(move_name, is_partner_target, rng):
    """Faithful port of Risky_Main: skipped entirely against a partner
    target (doubles), otherwise +2 exactly 50% (128/256) of the time for
    any move in AI_RISKY_MOVES - a fixed, specific move list in the real
    game, not a description-derived category like "high-crit or OHKO or
    otherwise risky", which is closely related but was this file's own
    earlier approximation rather than the real list."""
    if is_partner_target or move_name not in AI_RISKY_MOVES:
        return 0
    if rng.randint(0, 255) < 128:
        return 0
    return 2


def prioritize_extremes_flag_score(move_name, move, all_move_damages, is_partner_target, rng):
    """Faithful port of PrioritizeExtremes_Main. Ignored entirely against
    a partner target (doubles). The +2 bonus applies only when
    flag_move_damage_score finds NO comparison was made for this move -
    i.e. status moves and the specific handful of moves in
    AI_NO_DAMAGE_CALC_MOVES (Explosion, Focus Punch, Sucker Punch, a
    2-turn charge move, etc.) - NOT alt-power moves like Hidden Power or
    Return, and NOT ordinary damaging moves, despite what a literal
    reading of the move's own in-game description/comment might suggest.
    The real probability is 156/256 (not using it 100/256 of the time),
    which is ~60.9%, not a round 61%."""
    if is_partner_target:
        return 0
    if flag_move_damage_score(move_name, move, all_move_damages) != "AI_NO_COMPARISON_MADE":
        return 0
    if rng.randint(0, 255) < 100:
        return 0
    return 2


_WEATHER_MOVE_EFFECT_WEATHER = {
    "BATTLE_EFFECT_WEATHER_SUN": "SUN", "BATTLE_EFFECT_WEATHER_RAIN": "RAIN",
    "BATTLE_EFFECT_WEATHER_SANDSTORM": "SANDSTORM", "BATTLE_EFFECT_WEATHER_HAIL": "HAIL",
}


def weather_flag_score(move_name, attacker, bstate, is_partner_target, rng):
    """Faithful port of Weather_Main: ignored against a partner target and only on turn 1 of the battle. Retail bug
    reproduced: the four IfCurrentMoveEffectEqualTo dispatch lines have no fall-through guard, so a move that is NOT
    a weather move drops straight into Weather_Sun. Every such move (and Sunny Day itself) therefore gets +5 on the
    attacker's first turn unless the field is already Sunny, while a weather move whose own weather is already up
    gets nothing - which is why this flag ends up discouraging redundant weather moves rather than encouraging setters.
    The +5 itself is flat (no roll) and needs LoadIsFirstTurnInBattle for the attacker."""
    if is_partner_target:
        return 0
    if bstate.get("turn", 1) != 1:
        return 0
    wanted = _WEATHER_MOVE_EFFECT_WEATHER.get(_real_effect(move_name), "SUN")
    if bstate.get("weather", "NONE") == wanted:
        return 0
    return 5 if _ai_first_turn(attacker) else 0


AI_HARASSMENT_MOVES = {
    # Ported verbatim from Harrassment_Effects, resolved against real
    # move data. Replaces an earlier, much smaller and partly-incorrect
    # guess (it included FORCE_SWITCH/NIGHTMARE, which aren't in the
    # real table at all, while missing most of the real 32 moves).
    "MOVE_SING", "MOVE_SLEEP_POWDER", "MOVE_HYPNOSIS", "MOVE_LOVELY_KISS", "MOVE_SPORE", "MOVE_GRASS_WHISTLE",
    "MOVE_DARK_VOID", "MOVE_GROWL", "MOVE_TAIL_WHIP", "MOVE_LEER",
    "MOVE_SAND_ATTACK", "MOVE_SMOKE_SCREEN", "MOVE_KINESIS", "MOVE_FLASH", "MOVE_SWEET_SCENT",
    "MOVE_SUPERSONIC", "MOVE_CONFUSE_RAY", "MOVE_SWEET_KISS", "MOVE_CHARM", "MOVE_FEATHER_DANCE",
    "MOVE_SCREECH", "MOVE_COTTON_SPORE", "MOVE_SCARY_FACE", "MOVE_FAKE_TEARS", "MOVE_METAL_SOUND",
    "MOVE_POISON_POWDER", "MOVE_POISON_GAS", "MOVE_STUN_SPORE", "MOVE_THUNDER_WAVE", "MOVE_GLARE",
    "MOVE_LEECH_SEED", "MOVE_ENCORE", "MOVE_SPITE", "MOVE_SPIKES", "MOVE_SWAGGER", "MOVE_ATTRACT",
    "MOVE_TORMENT", "MOVE_FLATTER", "MOVE_WILL_O_WISP", "MOVE_NATURE_POWER", "MOVE_YAWN",
    "MOVE_KNOCK_OFF", "MOVE_IMPRISON", "MOVE_SECRET_POWER", "MOVE_TEETER_DANCE", "MOVE_TICKLE",
    "MOVE_CAMOUFLAGE", "MOVE_EMBARGO", "MOVE_PSYCHO_SHIFT", "MOVE_TOXIC_SPIKES", "MOVE_DEFOG", "MOVE_CAPTIVATE",
}


AI_BATON_PASS_SETUP_MOVES = {"MOVE_SWORDS_DANCE", "MOVE_DRAGON_DANCE", "MOVE_CALM_MIND", "MOVE_NASTY_PLOT"}
AI_PROTECT_EFFECT_MOVES = {"MOVE_PROTECT", "MOVE_DETECT"}


AI_CHECKHP_HIGH_HP_MOVES = {
    # CheckHP_DiscourageAtHighHP (attacker >70% HP)
    "MOVE_SELFDESTRUCT", "MOVE_EXPLOSION", "MOVE_RECOVER", "MOVE_SOFTBOILED", "MOVE_MILK_DRINK",
    "MOVE_SLACK_OFF", "MOVE_HEAL_ORDER", "MOVE_REST", "MOVE_DESTINY_BOND", "MOVE_FLAIL", "MOVE_REVERSAL",
    "MOVE_ENDURE", "MOVE_MORNING_SUN", "MOVE_SYNTHESIS", "MOVE_MOONLIGHT", "MOVE_MEMENTO", "MOVE_GRUDGE",
    "MOVE_ROOST", "MOVE_HEALING_WISH", "MOVE_LUNAR_DANCE",
}
AI_CHECKHP_MEDIUM_HP_MOVES = {
    # CheckHP_DiscourageAtMediumHP (attacker 31-70% HP)
    "MOVE_SELFDESTRUCT", "MOVE_EXPLOSION", "MOVE_MEDITATE", "MOVE_SHARPEN", "MOVE_HOWL", "MOVE_HARDEN",
    "MOVE_WITHDRAW", "MOVE_GROWTH", "MOVE_DOUBLE_TEAM", "MOVE_GROWL", "MOVE_TAIL_WHIP", "MOVE_LEER",
    "MOVE_STRING_SHOT", "MOVE_SAND_ATTACK", "MOVE_SMOKE_SCREEN", "MOVE_KINESIS", "MOVE_FLASH",
    "MOVE_SWEET_SCENT", "MOVE_BIDE", "MOVE_CONVERSION", "MOVE_LIGHT_SCREEN", "MOVE_MIST",
    "MOVE_FOCUS_ENERGY", "MOVE_SWORDS_DANCE", "MOVE_BARRIER", "MOVE_ACID_ARMOR", "MOVE_IRON_DEFENSE",
    "MOVE_AGILITY", "MOVE_ROCK_POLISH", "MOVE_TAIL_GLOW", "MOVE_NASTY_PLOT", "MOVE_AMNESIA", "MOVE_CHARM",
    "MOVE_FEATHER_DANCE", "MOVE_SCREECH", "MOVE_COTTON_SPORE", "MOVE_SCARY_FACE", "MOVE_FAKE_TEARS",
    "MOVE_METAL_SOUND", "MOVE_CONVERSION_2", "MOVE_SAFEGUARD", "MOVE_BELLY_DRUM", "MOVE_TICKLE",
    "MOVE_COSMIC_POWER", "MOVE_DEFEND_ORDER", "MOVE_BULK_UP", "MOVE_CALM_MIND", "MOVE_DRAGON_DANCE",
    "MOVE_LUCKY_CHANT", "MOVE_POWER_SWAP", "MOVE_GUARD_SWAP", "MOVE_CAPTIVATE",
}
AI_CHECKHP_LOW_HP_MOVES = {
    # CheckHP_DiscourageAtLowHP (attacker 1-30% HP) - notably NOT Explosion/
    # Self-Destruct: sacrificing the Pokemon isn't discouraged when it's
    # about to faint from residual/attacks anyway.
    "MOVE_MEDITATE", "MOVE_SHARPEN", "MOVE_HOWL", "MOVE_HARDEN", "MOVE_WITHDRAW", "MOVE_GROWTH",
    "MOVE_DOUBLE_TEAM", "MOVE_GROWL", "MOVE_TAIL_WHIP", "MOVE_LEER", "MOVE_STRING_SHOT", "MOVE_SAND_ATTACK",
    "MOVE_SMOKE_SCREEN", "MOVE_KINESIS", "MOVE_FLASH", "MOVE_SWEET_SCENT", "MOVE_BIDE", "MOVE_CONVERSION",
    "MOVE_LIGHT_SCREEN", "MOVE_MIST", "MOVE_FOCUS_ENERGY", "MOVE_SWORDS_DANCE", "MOVE_BARRIER",
    "MOVE_ACID_ARMOR", "MOVE_IRON_DEFENSE", "MOVE_AGILITY", "MOVE_ROCK_POLISH", "MOVE_TAIL_GLOW",
    "MOVE_NASTY_PLOT", "MOVE_AMNESIA", "MOVE_CHARM", "MOVE_FEATHER_DANCE", "MOVE_SCREECH",
    "MOVE_COTTON_SPORE", "MOVE_SCARY_FACE", "MOVE_FAKE_TEARS", "MOVE_METAL_SOUND", "MOVE_RAGE",
    "MOVE_CONVERSION_2", "MOVE_MIND_READER", "MOVE_LOCK_ON",
    "MOVE_SAFEGUARD", "MOVE_BELLY_DRUM", "MOVE_PSYCH_UP", "MOVE_MIRROR_COAT", "MOVE_ERUPTION",
    "MOVE_WATER_SPOUT", "MOVE_TICKLE", "MOVE_COSMIC_POWER", "MOVE_DEFEND_ORDER", "MOVE_BULK_UP",
    "MOVE_CALM_MIND", "MOVE_DRAGON_DANCE", "MOVE_MUD_SPORT", "MOVE_WATER_SPORT", "MOVE_ACUPRESSURE",
    "MOVE_METAL_BURST", "MOVE_CAPTIVATE",
}
AI_CHECKHP_TARGET_HIGH_HP_MOVES = set()  # CheckHP_Target_DiscourageAtHighHP is an empty table in the real game
AI_CHECKHP_TARGET_MEDIUM_HP_MOVES = {
    # CheckHP_Target_DiscourageAtMediumHP (target 31-70% HP)
    "MOVE_MEDITATE", "MOVE_SHARPEN", "MOVE_HOWL", "MOVE_HARDEN", "MOVE_WITHDRAW", "MOVE_GROWTH",
    "MOVE_DOUBLE_TEAM", "MOVE_GROWL", "MOVE_TAIL_WHIP", "MOVE_LEER", "MOVE_STRING_SHOT", "MOVE_SAND_ATTACK",
    "MOVE_SMOKE_SCREEN", "MOVE_KINESIS", "MOVE_FLASH", "MOVE_SWEET_SCENT", "MOVE_MIST", "MOVE_FOCUS_ENERGY",
    "MOVE_SWORDS_DANCE", "MOVE_BARRIER", "MOVE_ACID_ARMOR", "MOVE_IRON_DEFENSE", "MOVE_AGILITY",
    "MOVE_ROCK_POLISH", "MOVE_TAIL_GLOW", "MOVE_NASTY_PLOT", "MOVE_AMNESIA", "MOVE_CHARM",
    "MOVE_FEATHER_DANCE", "MOVE_SCREECH", "MOVE_COTTON_SPORE", "MOVE_SCARY_FACE", "MOVE_FAKE_TEARS",
    "MOVE_METAL_SOUND", "MOVE_POISON_POWDER", "MOVE_POISON_GAS", "MOVE_PAIN_SPLIT", "MOVE_PERISH_SONG",
    "MOVE_SAFEGUARD", "MOVE_TICKLE", "MOVE_COSMIC_POWER", "MOVE_DEFEND_ORDER", "MOVE_BULK_UP",
    "MOVE_CALM_MIND", "MOVE_DRAGON_DANCE", "MOVE_ACUPRESSURE", "MOVE_WRING_OUT", "MOVE_CRUSH_GRIP",
    "MOVE_CAPTIVATE",
}
AI_CHECKHP_TARGET_LOW_HP_MOVES = {
    # CheckHP_Target_DiscourageAtLowHP (target 1-30% HP)
    "MOVE_SING", "MOVE_SLEEP_POWDER", "MOVE_HYPNOSIS", "MOVE_LOVELY_KISS", "MOVE_SPORE", "MOVE_GRASS_WHISTLE",
    "MOVE_DARK_VOID", "MOVE_SELFDESTRUCT", "MOVE_EXPLOSION", "MOVE_MEDITATE", "MOVE_SHARPEN", "MOVE_HOWL",
    "MOVE_HARDEN", "MOVE_WITHDRAW", "MOVE_GROWTH", "MOVE_DOUBLE_TEAM", "MOVE_GROWL", "MOVE_TAIL_WHIP",
    "MOVE_LEER", "MOVE_STRING_SHOT", "MOVE_SAND_ATTACK", "MOVE_SMOKE_SCREEN", "MOVE_KINESIS", "MOVE_FLASH",
    "MOVE_SWEET_SCENT", "MOVE_BIDE", "MOVE_CONVERSION", "MOVE_TOXIC", "MOVE_LIGHT_SCREEN", "MOVE_MIST",
    "MOVE_GUILLOTINE", "MOVE_HORN_DRILL", "MOVE_FISSURE", "MOVE_SHEER_COLD", "MOVE_SUPER_FANG",
    "MOVE_FOCUS_ENERGY", "MOVE_SUPERSONIC", "MOVE_CONFUSE_RAY", "MOVE_SWEET_KISS", "MOVE_SWORDS_DANCE",
    "MOVE_BARRIER", "MOVE_ACID_ARMOR", "MOVE_IRON_DEFENSE", "MOVE_AGILITY", "MOVE_ROCK_POLISH",
    "MOVE_TAIL_GLOW", "MOVE_NASTY_PLOT", "MOVE_AMNESIA", "MOVE_CHARM", "MOVE_FEATHER_DANCE",
    "MOVE_SCREECH", "MOVE_COTTON_SPORE", "MOVE_SCARY_FACE", "MOVE_FAKE_TEARS", "MOVE_METAL_SOUND",
    "MOVE_POISON_POWDER", "MOVE_POISON_GAS", "MOVE_STUN_SPORE", "MOVE_THUNDER_WAVE", "MOVE_GLARE",
    "MOVE_PAIN_SPLIT", "MOVE_CONVERSION_2", "MOVE_MIND_READER", "MOVE_LOCK_ON", "MOVE_SPITE",
    "MOVE_PERISH_SONG", "MOVE_SWAGGER", "MOVE_FURY_CUTTER", "MOVE_ATTRACT", "MOVE_SAFEGUARD",
    "MOVE_PSYCH_UP", "MOVE_MIRROR_COAT", "MOVE_WILL_O_WISP", "MOVE_TICKLE", "MOVE_COSMIC_POWER",
    "MOVE_DEFEND_ORDER", "MOVE_BULK_UP", "MOVE_CALM_MIND", "MOVE_DRAGON_DANCE", "MOVE_ACUPRESSURE",
    "MOVE_WRING_OUT", "MOVE_CRUSH_GRIP", "MOVE_CAPTIVATE",
}


AI_FLAT_DAMAGE_EFFECT_MOVES = {
    # ONE_HIT_KO, 40_DAMAGE_FLAT, LEVEL_DAMAGE_FLAT, RANDOM_DAMAGE_1_TO_150_LEVEL, 20_DAMAGE_FLAT
    "MOVE_GUILLOTINE", "MOVE_HORN_DRILL", "MOVE_FISSURE", "MOVE_SHEER_COLD",
    "MOVE_DRAGON_RAGE", "MOVE_SEISMIC_TOSS", "MOVE_NIGHT_SHADE", "MOVE_PSYWAVE", "MOVE_SONIC_BOOM",
}
AI_ABSORPTION_ABILITIES_ELECTRIC = {"ABILITY_MOTOR_DRIVE", "ABILITY_VOLT_ABSORB"}


def compute_speed_ranks(attacker, ally, defender, defender_partner, bstate):
    """Assigns a transient "_speed_rank" (0=moves first, 3=last) to each battler, exactly as AICmd_LoadBattlerSpeedRank
    does: an exchange sort driven by BattleSystem_CompareBattlerSpeed, where a living mon always outranks a fainted one.
    (Ties are left in party order; the real compare flips a coin.) Fainted or absent battlers are left unranked."""
    battlers = []
    for m in (defender, attacker, defender_partner, ally):
        if m is not None and not any(m is b for b in battlers):     # a partner-targeted call repeats mons
            battlers.append(m)

    def swap_needed(m1, m2):
        if m1.get("hp", 0) <= 0 < m2.get("hp", 0):
            return True
        if m2.get("hp", 0) <= 0 < m1.get("hp", 0):
            return False
        return _speed_compare(m1, m2, bstate) == "SLOWER"

    order = list(battlers)
    for i in range(len(order) - 1):
        for j in range(i + 1, len(order)):
            if swap_needed(order[i], order[j]):
                order[i], order[j] = order[j], order[i]
    for rank, m in enumerate(order):
        if m.get("hp", 0) > 0:
            m["_speed_rank"] = rank


def ai_move_damage_table(mon, target, bstate):
    """TrainerAI_CalcAllDamage: max-roll damage of EVERY learned move slot (PP is irrelevant), where only moves that pass
    the FlagMoveDamageScore gate are calculated at all - every other move (status moves, Explosion, Hyper Beam, Focus
    Punch, ...) counts as 0 damage however hard it would really hit."""
    table = {}
    for name in mon.get("moves", []):
        if not name:
            continue
        if _basic_move_is_damage_comparable(name):
            mv = get_effective_move_data(name, mon, defender=target, bstate=bstate)
            table[name] = estimate_max_damage(mon, target, mv, weather_now(bstate), bstate=bstate)[0]
        else:
            table[name] = 0
    return table


def check_highest_damage_with_partner(move_name, mv, attacker, ally, defender, bstate):
    """Faithful port of AICmd_CheckIfHighestDamageWithPartner. Same
    comparison-eligibility gate as flag_move_damage_score, but "highest"
    here means at least as much as every one of the attacker's OWN
    moves AND every one of its ally's own moves (each computed against
    the same target) - not just the attacker's own moveset. Notably,
    the real game computes all 4 move slots' damage regardless of
    remaining PP, so this doesn't filter by PP either, and (as in
    TrainerAI_CalcAllDamage) a move that is not damage-comparable counts as 0."""
    if not _basic_move_is_damage_comparable(move_name):
        return "AI_NO_COMPARISON_MADE"
    my_dmg = ai_move_damage_table(attacker, defender, bstate).get(move_name, 0)
    for mon in (attacker, ally):
        if mon is None:
            continue
        if any(dmg > my_dmg for dmg in ai_move_damage_table(mon, defender, bstate).values()):
            return "AI_NOT_HIGHEST_DAMAGE"
    return "AI_MOVE_IS_HIGHEST_DAMAGE"


def tag_strategy_partner_score(move_name, mv, attacker, ally, defender, all_move_damages, rng):
    """Faithful port of TagStrategy_Partner and its many sub-handlers -
    runs when a doubles Pokemon under AI_FLAG_TAG_STRATEGY targets its
    OWN ally. ally here is the ally being targeted (i.e. what the real
    script calls AI_BATTLER_ATTACKER_PARTNER relative to this action)."""
    if ally is None or ally.get("hp", 0) <= 0:
        return -30

    comparison = flag_move_damage_score(move_name, mv, all_move_damages)
    if comparison == "AI_NO_COMPARISON_MADE":
        return _tag_strategy_partner_status_move(move_name, attacker, ally, rng)

    move_type = mv.get("type")
    if move_type == "TYPE_FIRE":
        return _tag_strategy_partner_fire_absorption(ally, rng)
    if move_type == "TYPE_ELECTRIC":
        return _tag_strategy_partner_electric_absorption(ally, rng)
    if move_type == "TYPE_WATER":
        return _tag_strategy_partner_water_absorption(ally, rng)
    if move_name == "MOVE_FLING":
        return 0  # TagStrategy_PartnerTrick: PopOrEnd, no effect at all
    return -30    # TagStrategy_ScoreMinus30: any other damaging move aimed at the ally


def _tag_strategy_partner_fire_absorption(ally, rng):
    if not _ai_has_ability(ally, "FLASH_FIRE"):
        return -30
    if ally.get("activated_flash_fire"):
        return -30
    return 3


def _tag_strategy_partner_electric_absorption(ally, rng):
    if _ai_has_ability(ally, "MOTOR_DRIVE"):
        if rng.randint(0, 255) < 160:
            return 0
        if ally.get("spe_stage", 0) >= 6:
            return -30
        return 3
    if _ai_has_ability(ally, "VOLT_ABSORB"):
        return _partner_hp_tiered_absorption_score(ally, rng)
    return -30


def _tag_strategy_partner_water_absorption(ally, rng):
    if _ai_has_ability(ally, "WATER_ABSORB") or _ai_has_ability(ally, "DRY_SKIN"):
        return _partner_hp_tiered_absorption_score(ally, rng)
    return -30


def _partner_hp_tiered_absorption_score(ally, rng):
    """Shared by Volt Absorb and Water Absorb/Dry Skin: -10 at exactly
    100% HP (an absorbing ally can't benefit from more healing there),
    no change above 90%, then increasing odds of +3 the lower the HP."""
    hp_pct = ai_hp_percent(ally)
    if hp_pct == 100:
        return -10
    if hp_pct > 90:
        return 0
    if hp_pct > 75:
        thresh = 64
    elif hp_pct > 50:
        thresh = 128
    else:
        thresh = 192
    return 3 if rng.randint(0, 255) < thresh else 0


def _tag_strategy_partner_status_move(move_name, attacker, ally, rng):
    if move_name == "MOVE_SKILL_SWAP":
        return _tag_strategy_partner_skill_swap(attacker, ally, rng)
    if move_name == "MOVE_WILL_O_WISP":
        if _ai_has_ability(ally, "FLASH_FIRE"):
            return _tag_strategy_partner_fire_absorption(ally, rng)
        if not _ai_has_ability(ally, "GUTS"):
            return -30
        if ally.get("status", "NONE") != "NONE":
            return -30
        if _ai_has_type(ally, "TYPE_FIRE"):
            return -30
        if ally.get("item") in ("ITEM_FLAME_ORB", "ITEM_TOXIC_ORB"):
            return -30
        if ai_hp_percent(ally) < 81:
            return -30
        return 5
    if move_name == "MOVE_THUNDER_WAVE":
        if _ai_has_type(ally, "TYPE_GROUND"):
            return -30
        if _ai_has_ability(ally, "MOTOR_DRIVE") or _ai_has_ability(ally, "VOLT_ABSORB"):
            return _tag_strategy_partner_electric_absorption(ally, rng)
        return -30
    if move_name in ("MOVE_TOXIC", "MOVE_POISON_POWDER", "MOVE_POISON_GAS"):
        if not _ai_has_ability(ally, "POISON_HEAL"):
            return -30
        if ally.get("status", "NONE") != "NONE":
            return -30
        if ally.get("item") == "ITEM_TOXIC_ORB":
            return -30
        if ai_hp_percent(ally) > 91:
            return -30
        return 5
    if move_name == "MOVE_HELPING_HAND":
        if _ai_hp_is_zero(ally):
            return -30
        hp_pct = ai_hp_percent(ally)
        moves_first = ally.get("_speed_rank", 1) < 1
        if hp_pct > 50 or moves_first:
            return -1 if rng.randint(0, 255) < 64 else 2
        return 0
    if move_name == "MOVE_SWAGGER":
        if ally.get("item") not in ("ITEM_PERSIM_BERRY", "ITEM_LUM_BERRY"):
            return -30
        if ally.get("atk_stage", 0) > 1:
            return 0
        return 3
    if move_name in ("MOVE_TRICK", "MOVE_SWITCHEROO"):
        return 0  # TagStrategy_PartnerTrick: PopOrEnd, no effect
    if move_name == "MOVE_GASTRO_ACID":
        if ally.get("ability_suppressed"):
            return -30
        if _ai_has_ability(ally, "TRUANT") or _ai_has_ability(ally, "SLOW_START"):
            return 5
        return 0
    if move_name == "MOVE_ACUPRESSURE":
        return _tag_strategy_partner_acupressure(ally, rng)
    return -30


def _tag_strategy_partner_skill_swap(attacker, ally, rng):
    """TagStrategy_PartnerSkillSwap. +10 to cure a Truant/Slow Start ally; Levitate-for-an-Electric-ally is worth +1 per
    Electric slot; giving Compound Eyes/No Guard to an ally with an inaccurate move is +3; everything else -30. The
    running score carries into the fall-through: an Electric-type-1 ally whose second slot is not Electric still gets its
    +1 before dropping into the accuracy branch."""
    # The target is read in the DEFENDER role (a guess, one Load per read - it is loaded again for the Levitate test)
    if ai_load_ability(ally, None, rng) in ("TRUANT", "SLOW_START"):
        return 10
    score = 0
    if _ai_ability(attacker) == "LEVITATE":
        if ai_load_ability(ally, None, rng) == "LEVITATE":
            return -30
        if ally.get("type1") == "TYPE_ELECTRIC":
            score += 1
            if (ally.get("type2") or ally.get("type1")) == "TYPE_ELECTRIC":
                return score + 1
    if _ai_ability(attacker) in ("COMPOUND_EYES", "NO_GUARD"):
        if ally.get("hp", 0) > 0 and any(m in _AI_SKILL_SWAP_INACCURATE_MOVES for m in ally.get("moves", [])):
            return score + 3
    return score - 30


_AI_SKILL_SWAP_INACCURATE_MOVES = {
    "MOVE_FIRE_BLAST", "MOVE_THUNDER", "MOVE_CROSS_CHOP", "MOVE_HYDRO_PUMP", "MOVE_DYNAMIC_PUNCH",
    "MOVE_BLIZZARD", "MOVE_ZAP_CANNON", "MOVE_MEGAHORN", "MOVE_FOCUS_BLAST", "MOVE_GUNK_SHOT",
    "MOVE_MAGMA_STORM", "MOVE_POWER_WHIP", "MOVE_SEED_FLARE", "MOVE_HEAD_SMASH",
}


def _tag_strategy_partner_acupressure(ally, rng):
    stages = [ally.get(k, 0) for k in ("atk_stage", "def_stage", "spe_stage", "spa_stage", "spd_stage",
                                        "eva_stage", "acc_stage")]
    if _ai_has_ability(ally, "SIMPLE"):
        if any(s > 2 for s in stages):  # real stage >8 raw == my_stage>2
            return -10
    else:
        if any(s == 6 for s in stages):  # real stage ==12 raw == my_stage==6 (max)
            return -30
    hp_pct = ai_hp_percent(ally)
    if hp_pct < 51:  # TagStrategy_PartnerAcupressure: IfHPPercentLessThan 51
        return -1
    thresh = 80
    if hp_pct > 90:
        if rng.randint(0, 255) < thresh:
            return 0
        return 2
    if rng.randint(0, 255) < 128:
        return 0
    if rng.randint(0, 255) < thresh:
        return 0
    return 2


_TAG_FLAT_DAMAGE_EFFECTS = frozenset((
    "BATTLE_EFFECT_ONE_HIT_KO", "BATTLE_EFFECT_40_DAMAGE_FLAT", "BATTLE_EFFECT_LEVEL_DAMAGE_FLAT",
    "BATTLE_EFFECT_RANDOM_DAMAGE_1_TO_150_LEVEL", "BATTLE_EFFECT_20_DAMAGE_FLAT",
))


def _ai_has_ability(mon, name):
    """CheckBattlerAbility == AI_HAVE: reads through Gastro Acid suppression, and an absent battler has no ability."""
    return mon is not None and _ai_ability(mon) == name


def _ai_has_type(mon, type_name):
    """FlagBattlerIsType / MON_HAS_TYPE."""
    return mon is not None and type_name in (mon.get("type1"), mon.get("type2"))


def tag_strategy_flag_score(move_name, mv, attacker, ally, defender, defender_partner, all_move_damages,
                             is_partner_target, bstate, rng):
    """Faithful port of TagStrategy_Main - a doubles-only script,
    automatically active for every doubles trainer regardless of their
    own AI bitmask. Dispatches to TagStrategy_Partner's whole separate
    routine when targeting an ally (see tag_strategy_partner_score).

    Control flow of the damaging-move half (only moves that pass the damage-comparison gate get here):
      resist penalty (-1 / -2, 75%, skipped on a kill or when the target's partner is gone)
        -> ScoreMove: a highest-damage move (counting the ally's moves too) gets +1 (50%, or ~80% for a priority-1 effect),
           and ONLY when that +1 lands does it skip TagStrategy_CheckBeforeScoring's super-effective bonus.
        -> CheckSpecialScoring: the per-move / per-type routines."""
    compute_speed_ranks(attacker, ally, defender, defender_partner, bstate)
    if is_partner_target:
        return tag_strategy_partner_score(move_name, mv, attacker, ally, defender, all_move_damages, rng)

    score = 0
    effect = _real_effect(move_name)
    if flag_move_damage_score(move_name, mv, all_move_damages) != "AI_NO_COMPARISON_MADE":
        is_flat_damage = effect in _TAG_FLAT_DAMAGE_EFFECTS
        eff = _ai_move_effectiveness(mv.get("type", "TYPE_NORMAL"), attacker, defender, bstate)
        if not is_flat_damage and eff in (0.5, 0.25):
            # TagStrategy_TryScoreMinus1 / TryScoreMinus2. The target's partner check is IfHPPercentEqualTo
            # DEFENDER_PARTNER 0, i.e. the opposing side is down to its last active Pokemon.
            dmg, _ = estimate_max_damage(attacker, defender, mv, weather_now(bstate), bstate=bstate)
            kills = dmg >= defender.get("hp", 0)
            if not kills and not _ai_hp_is_zero(defender_partner):
                if rng.randint(0, 255) >= 64:
                    score -= 1 if eff == 0.5 else 2

        # TagStrategy_ScoreMove
        reach_before_scoring = True
        if check_highest_damage_with_partner(move_name, mv, attacker, ally, defender, bstate) == "AI_MOVE_IS_HIGHEST_DAMAGE":
            if effect == "BATTLE_EFFECT_HALVE_DEFENSE":
                reach_before_scoring = False
            elif move_name in AI_PRIORITY_1_EFFECT_MOVES:
                if rng.randint(0, 255) >= 50:
                    score += 1
                    reach_before_scoring = False
            elif rng.randint(0, 255) >= 128:
                score += 1
                reach_before_scoring = False

        # TagStrategy_CheckBeforeScoring
        if reach_before_scoring and not is_flat_damage:
            if eff == 2.0:
                if rng.randint(0, 255) >= 100:
                    score += 1
            elif eff == 4.0:
                if rng.randint(0, 255) >= 64:
                    score += 1

    score += _tag_strategy_special_move_dispatch(move_name, mv, attacker, ally, defender, defender_partner, bstate, rng)
    return score


def _tag_strategy_special_move_dispatch(move_name, mv, attacker, ally, defender, defender_partner, bstate, rng):
    """TagStrategy_CheckSpecialScoring's dispatch by specific move/type. Each routine ends the script, so the
    elemental-type routines and the Helping Hand bonus are mutually exclusive."""
    if move_name == "MOVE_SKILL_SWAP":
        # TagStrategy_SkillSwap: dump a bad ability of our own (+5), or steal a strong one from the target (+2)
        if _ai_ability(attacker) in ("TRUANT", "SLOW_START", "STALL", "KLUTZ"):
            return 5
        if ai_load_ability(defender, None, rng) in ("SHADOW_TAG", "PURE_POWER", "HUGE_POWER", "MOLD_BREAKER", "SOLID_ROCK",
                                                    "FILTER", "FLOWER_GIFT"):
            return 2
        return 0

    if move_name in ("MOVE_EARTHQUAKE", "MOVE_MAGNITUDE"):
        if ally is not None:
            if ally.get("magnet_rise_turns", 0) > 0 or _ai_has_ability(ally, "LEVITATE") or _ai_has_type(ally, "TYPE_FLYING"):
                return 2
            if any(_ai_has_type(ally, t) for t in ("TYPE_FIRE", "TYPE_ELECTRIC", "TYPE_POISON", "TYPE_ROCK")):
                return -10
        return -3  # applies even with no ally present - a real, faithfully-reproduced quirk

    if move_name in ("MOVE_FUTURE_SIGHT", "MOVE_DOOM_DESIRE"):
        return _tag_strategy_future_sight(attacker, ally, rng)

    if move_name == "MOVE_RAIN_DANCE":
        return _tag_strategy_weather_ability_pair(
            attacker, ally, lambda m: (_ai_has_ability(m, "HYDRATION") and m.get("status", "NONE") != "NONE") or _ai_has_ability(m, "DRY_SKIN"))

    if move_name == "MOVE_SUNNY_DAY":
        return _tag_strategy_sunny_day(attacker, ally, rng)

    if move_name == "MOVE_HAIL":
        return _tag_strategy_weather_ability_pair(
            attacker, ally, lambda m: _ai_has_ability(m, "ICE_BODY") or _ai_has_ability(m, "SNOW_CLOAK") or "MOVE_BLIZZARD" in m.get("moves", []))

    if move_name == "MOVE_SANDSTORM":
        return _tag_strategy_weather_ability_pair(
            attacker, ally, lambda m: _ai_has_ability(m, "SAND_VEIL") or _ai_has_type(m, "TYPE_ROCK"))

    if move_name == "MOVE_GRAVITY":
        return _tag_strategy_gravity(attacker, ally, defender, defender_partner, bstate, rng)

    if move_name == "MOVE_TRICK_ROOM":
        return _tag_strategy_trick_room(attacker, ally, defender, defender_partner, rng)

    if move_name == "MOVE_FOLLOW_ME":
        return _tag_strategy_follow_me(attacker, ally, rng)

    move_type = mv.get("type")
    if move_type == "TYPE_ELECTRIC":
        return _tag_strategy_electric_move(move_name, ally, defender_partner, rng)
    if move_type == "TYPE_WATER":
        return _tag_strategy_water_move(move_name, ally, defender_partner)
    if move_type == "TYPE_FIRE":
        return _tag_strategy_fire_move(move_name, attacker, ally)

    if ally is not None and ally.get("hp", 0) > 0 and "MOVE_HELPING_HAND" in ally.get("moves", []):
        # TagStrategy_PartnerKnowsHelpingHand: damaging moves (flat-damage ones excepted) get +1
        if _real_effect(move_name) not in _TAG_FLAT_DAMAGE_EFFECTS and _basic_move_is_damage_comparable(move_name):
            return 1
    return 0


def _tag_strategy_future_sight(attacker, ally, rng):
    if _ai_hp_is_zero(ally):
        return 0
    if "MOVE_FUTURE_SIGHT" not in ally.get("moves", []) and "MOVE_DOOM_DESIRE" not in ally.get("moves", []):
        return 0
    self_rank = attacker.get("_speed_rank", 0)
    ally_rank = ally.get("_speed_rank", 1)
    if self_rank == 3:
        return -3
    if self_rank == 2:
        if ally_rank in (0, 1):
            return -3
        if rng.randint(0, 255) < 128:
            return 0
        return -3 if ally_rank == 2 else 0
    if self_rank == 1:
        if ally_rank == 0:
            return -3
        if rng.randint(0, 255) < 128:
            return 0
        return -3 if ally_rank == 1 else 0
    if self_rank == 0:
        if rng.randint(0, 255) < 128:
            return 0
        return -3 if ally_rank == 0 else 0
    return 0


def _tag_strategy_weather_ability_pair(attacker, ally, predicate):
    score = 0
    if predicate(attacker):
        score += 2
    if ally is not None and predicate(ally):
        score += 2
    return score


def _tag_strategy_sunny_day(attacker, ally, rng):
    score = 0
    for mon in (attacker, ally):
        if mon is None:
            continue
        ability = _ai_ability(mon)
        if ability == "LEAF_GUARD":
            if mon.get("status", "NONE") == "NONE" and ai_hp_percent(mon) >= 30:
                score += 2
        elif ability == "FLOWER_GIFT":
            score += 2
        elif ability == "DRY_SKIN":
            score -= 2
        elif ability == "SOLAR_POWER":
            # Retail quirk: the +1 branch has no exit, so it falls into the same 50% roll for -2 that a
            # low-HP Solar Power user takes on its own.
            if ai_hp_percent(mon) >= 50:
                score += 1
            if rng.randint(0, 255) >= 128:
                score -= 2
    return score


def _tag_strategy_gravity(attacker, ally, defender, defender_partner, bstate, rng):
    if bstate.get("gravity", 0) > 0:
        return -30          # Gravity is already up

    def grounded_exempt(mon, opposing=False):
        """CheckBattlerAbility LEVITATE (a guess for an opposing battler: only a known/certain Levitate counts), a Flying type,
        or Magnet Rise."""
        if mon is None:
            return False
        levitate = (ai_check_ability(mon, "LEVITATE", None) == "HAVE") if opposing else _ai_has_ability(mon, "LEVITATE")
        return levitate or _ai_has_type(mon, "TYPE_FLYING") or mon.get("magnet_rise_turns", 0) > 0

    score = 0
    if grounded_exempt(attacker):
        score -= 5
    if grounded_exempt(ally):
        score -= 5
    if grounded_exempt(defender, True) and rng.randint(0, 255) >= 64:
        score += 3
    if grounded_exempt(defender_partner, True) and rng.randint(0, 255) >= 64:
        score += 3
    return score


def _tag_strategy_trick_room(attacker, ally, defender, defender_partner, rng):
    if _ai_hp_is_zero(ally) or _ai_hp_is_zero(defender_partner) or _ai_hp_is_zero(defender):
        return -30
    self_rank = attacker.get("_speed_rank", 0)
    ally_rank = ally.get("_speed_rank", 1)
    if self_rank == 0:
        if ally_rank in (0, 1):
            return -30
        return -5
    if self_rank == 1:
        if ally_rank == 0:
            return -30
        return -5
    if self_rank == 2:
        if ally_rank != 3:
            return -5
        return 5 if rng.randint(0, 255) >= 64 else -5
    if self_rank == 3:
        if ally_rank != 2:
            return -5
        return 5 if rng.randint(0, 255) >= 64 else -5
    return 0


def _tag_strategy_follow_me(attacker, ally, rng):
    self_hp = ai_hp_percent(attacker)
    ally_hp = ai_hp_percent(ally) if ally is not None else 0

    def try_score(delta):
        return delta if rng.randint(0, 255) >= 64 else 0

    if self_hp > 90:
        if ally_hp > 90:
            return try_score(-1)
        if ally_hp > 50:
            return try_score(1)
        if ally_hp > 30:
            return try_score(2)
        return try_score(3)
    if self_hp > 50:
        if ally_hp > 90:
            return try_score(-2)
        if ally_hp > 50:
            return try_score(-1)
        if ally_hp > 30:
            return try_score(1)
        return try_score(2)
    if self_hp > 30:
        if ally_hp > 90:
            return try_score(-2)
        if ally_hp > 50:
            return try_score(-2)
        if ally_hp > 30:
            return try_score(1)
        return try_score(2)
    return try_score(-5)


def _tag_strategy_electric_move(move_name, ally, defender_partner, rng):
    """TagStrategy_CheckElectricMove. Discharge jumps straight to the spread routine (skipping the Lightning Rod
    checks); any other Electric move is -1 into a Lightning Rod target's partner (a further -8 if that partner is
    Ground-typed and so immune) and -10 if our own partner has Lightning Rod."""
    if move_name == "MOVE_DISCHARGE":
        return _tag_strategy_spread_electric(ally)
    score = 0
    if defender_partner is not None and ai_check_ability(defender_partner, "LIGHTNING_ROD", None) == "HAVE":
        score -= 1
        if _ai_has_type(defender_partner, "TYPE_GROUND"):
            score -= 8
    if _ai_has_ability(ally, "LIGHTNING_ROD"):
        score -= 10
    return score


def _tag_strategy_spread_electric(ally):
    if ally is None:
        return -3
    if _ai_has_ability(ally, "MOTOR_DRIVE") or _ai_has_ability(ally, "VOLT_ABSORB"):
        return 3
    if _ai_has_type(ally, "TYPE_WATER") or _ai_has_type(ally, "TYPE_FLYING"):
        return -10
    # BUG (faithfully reproduced): Ground-type immunity is checked AFTER
    # Water/Flying above, so a partner that's e.g. both Water and Ground
    # (Swampert) or Flying and Ground (Gliscor) never reaches this
    # Ground check at all - it's caught by the Water/Flying check first
    # and scored -10 instead of the intended +3 for being immune.
    if _ai_has_type(ally, "TYPE_GROUND"):
        return 3
    return -3


def _tag_strategy_water_move(move_name, ally, defender_partner):
    """TagStrategy_CheckWaterMove. Surf jumps straight to the spread routine. Any other Water move is -1 UNLESS the
    target's partner is known to lack Storm Drain (an unknown or absent ability reads as AI_UNKNOWN, which is not
    AI_NOT_HAVE, so it is penalised too), and -10 if our own partner has Storm Drain."""
    if move_name == "MOVE_SURF":
        return _tag_strategy_spread_water(ally)
    score = 0
    verdict = ai_check_ability(defender_partner, "STORM_DRAIN", None) if defender_partner is not None else "UNKNOWN"
    if verdict != "NOT_HAVE":
        score -= 1
    if _ai_has_ability(ally, "STORM_DRAIN"):
        score -= 10
    return score


def _tag_strategy_spread_water(ally):
    if ally is None:
        return -3
    if _ai_has_ability(ally, "DRY_SKIN") or _ai_has_ability(ally, "WATER_ABSORB"):
        return 3
    # BUG (faithfully reproduced): the real game's own comment notes
    # this should also check for the Rock type, but does not.
    if _ai_has_type(ally, "TYPE_GROUND") or _ai_has_type(ally, "TYPE_FIRE"):
        return -10
    return -3


def _tag_strategy_fire_move(move_name, attacker, ally):
    score = 1 if attacker.get("activated_flash_fire") else 0
    if move_name != "MOVE_LAVA_PLUME":
        return score
    if ally is None:
        return score - 3
    if _ai_has_ability(ally, "DRY_SKIN"):
        # BUG (faithfully reproduced): the real game's own comment says
        # a Dry Skin partner should score +3 here, but the actual code
        # branches to ScoreMinus3 instead - a genuine mismatch between
        # the comment and the implementation in the original game.
        return score - 3
    if _ai_has_ability(ally, "FLASH_FIRE"):
        return score + 3
    if any(_ai_has_type(ally, t) for t in ("TYPE_GRASS", "TYPE_STEEL", "TYPE_ICE", "TYPE_BUG")):
        return score - 10
    return score - 3


def check_hp_flag_score(move_name, attacker, defender, is_partner_target, rng, mv=None, ally=None,
                        all_move_damages=None, bstate=None, defender_partner=None):
    """Faithful port of CheckHP_Main. Two independent passes, each of
    which can apply its own -2 (they stack if a move matches both):

    First pass looks at the ATTACKER's own HP tier (>70% / 31-70% /
    1-30%) and checks the move against that tier's specific move list
    (AI_CHECKHP_HIGH/MEDIUM/LOW_HP_MOVES). Second pass looks at the
    TARGET's HP tier the exact same way, against a different set of
    lists (AI_CHECKHP_TARGET_*_HP_MOVES) - notably the target's >70%
    tier is an empty table in the real game, so it can never apply at
    all. Each pass's -2 lands independently at ~80.5% (206/256).

    When the target is a partner (doubles), the real game instead
    delegates entirely to TagStrategy_Partner (`IfTargetIsPartner
    TagStrategy_Partner`), so this flag then contributes that routine's
    score - on top of TagStrategy's own, since both run for a doubles AI."""
    if is_partner_target:
        compute_speed_ranks(attacker, ally, defender, defender_partner, bstate)
        return tag_strategy_partner_score(move_name, mv, attacker, ally, defender, all_move_damages, rng)

    score = 0
    atk_hp_pct = ai_hp_percent(attacker)
    if atk_hp_pct > 70:
        attacker_table = AI_CHECKHP_HIGH_HP_MOVES
    elif atk_hp_pct > 30:
        attacker_table = AI_CHECKHP_MEDIUM_HP_MOVES
    else:
        attacker_table = AI_CHECKHP_LOW_HP_MOVES
    if move_name in attacker_table and rng.randint(0, 255) >= 50:
        score -= 2

    def_hp_pct = ai_hp_percent(defender)
    if def_hp_pct > 70:
        target_table = AI_CHECKHP_TARGET_HIGH_HP_MOVES
    elif def_hp_pct > 30:
        target_table = AI_CHECKHP_TARGET_MEDIUM_HP_MOVES
    else:
        target_table = AI_CHECKHP_TARGET_LOW_HP_MOVES
    if move_name in target_table and rng.randint(0, 255) >= 50:
        score -= 2

    return score


def baton_pass_flag_score(move_name, move, attacker, all_move_damages, other_party_alive_count, bstate, is_partner_target, rng):
    """Faithful port of BatonPass_Main.

    Ignored entirely against a partner target, if there's no one else
    alive in the party to pass to, or if the move deals real damage
    (only non-damaging/no-comparison-made moves are considered - see
    flag_move_damage_score). If the attacker doesn't even know Baton
    Pass itself, there's a flat 31.25% (80/256) chance nothing here
    applies at all, before any of the rest of this routine runs.

    Four different moves get bespoke handling: Swords Dance/Dragon
    Dance/Calm Mind/Nasty Plot are treated as "big turn-1 setup" moves
    (+5 on the very first turn, -10 below 60% HP, else +1). Protect/
    Detect get -2 if the attacker's own last move was also Protect or
    Detect (discouraging spam), else +2. Baton Pass itself gets -2 on
    turn 1, otherwise scores off whichever of Attack/Special Attack is
    boosted - checking Attack's three tiers (+1/+2/+3 stage -> +1/+2/+3
    score) FIRST and stopping there the moment any of them match, only
    falling through to check Special Attack's own three tiers if Attack
    isn't boosted at all. This means a Pokemon with Attack +1 and
    Special Attack +3 still only gets +1 here - Attack's lowest
    threshold already satisfied the check before Special Attack is ever
    examined, a real quirk in the original game, not a simplification.
    Every other non-damaging move otherwise reaching this routine gets +3
    with ~92.2% (236/256) probability, and then FALLS THROUGH into the
    setup-move tail (see the comment at the end of this function)."""
    if is_partner_target:
        return 0
    if other_party_alive_count <= 0:
        return 0
    if flag_move_damage_score(move_name, move, all_move_damages) != "AI_NO_COMPARISON_MADE":
        return 0

    knows_baton_pass = any(_real_effect(n) == "BATTLE_EFFECT_PASS_STATS_AND_STATUS" for n in attacker.get("moves", []) if n)
    if not knows_baton_pass and rng.randint(0, 255) < 80:
        return 0

    def setup_at_high_hp():
        # BatonPass_SetupAtHighHP
        if bstate.get("turn", 1) == 1:
            return 5
        if ai_hp_percent(attacker) < 60:
            return -10
        return 1

    if move_name in AI_BATON_PASS_SETUP_MOVES:
        return setup_at_high_hp()

    if _real_effect(move_name) == "BATTLE_EFFECT_PROTECT":
        if attacker.get("last_move_used") in AI_PROTECT_EFFECT_MOVES:
            return -2
        return 2

    if move_name == "MOVE_BATON_PASS":
        if bstate.get("turn", 1) == 1:
            return -2
        for stat in ("atk_stage", "spa_stage"):
            stage = attacker.get(stat, 0)
            if stage >= 3:
                return 3
            if stage >= 2:
                return 2
            if stage >= 1:
                return 1
        return 0

    # Retail quirk: after its +3 this branch has no PopOrEnd and FALLS THROUGH into BatonPass_SetupAtHighHP, so every
    # other non-damaging move also gets +5 on turn 1, or -10 below 60% HP, or +1 - i.e. +8 / -7 / +4 in total.
    if rng.randint(0, 255) < 20:
        return 0
    return 3 + setup_at_high_hp()


def harassment_flag_score(move_name, is_partner_target, rng):
    """Faithful port of Harrassment_Main: ignored against a partner
    target, then a flat 50% (128/256) chance of +2 for any move in
    AI_HARASSMENT_MOVES - a fixed, specific move list, not a derived
    category like "inflicts a status or lowers a target's stat"."""
    if is_partner_target or move_name not in AI_HARASSMENT_MOVES:
        return 0
    if rng.randint(0, 255) < 128:
        return 0
    return 2


# ============================================================
# MASTER MOVE CHOICE
# ============================================================
def count_other_alive_party_members(party, active_idxs):
    """How many Pokemon in party (other than the currently-active one(s)
    at active_idxs - an int for singles, or a collection of indices for
    doubles to also exclude an active ally) are still alive - used by
    baton_pass_flag_score's real CountAlivePartyBattlers check."""
    excluded = {active_idxs} if isinstance(active_idxs, int) else set(active_idxs)
    return sum(1 for i, mon in enumerate(party) if i not in excluded and mon.get("hp", 0) > 0)


def _forced_or_usable_moves(attacker, defender, bstate):
    """The part of move choice that happens before any scoring: locked-in moves (Solar Beam charge, rampage, Bide, Encore, ...)
    and the PP / Taunt / Torment / Imprison filters. Returns (forced_move, None) or (None, usable_move_names)."""
    pp_pool = attacker.get("move_pp", {})
    # Locked-in moves bypass scoring entirely - the Pokemon has no choice
    # - unless it's actually out of PP, in which case even a locked-in
    # move must yield to Struggle (same as normal selection), which also
    # correctly breaks the lock rather than looping on 0 PP forever.
    if attacker.get("vanished"):
        matching = next((n for n in attacker.get("moves", [])
                          if get_move_data_by_name(n).get("charge_move") == attacker["vanished"]), None)
        if matching and pp_pool.get(matching, 0) > 0:
            return (matching, None)
        attacker["vanished"] = None
    if attacker.get("charging_solar_beam"):
        if pp_pool.get("MOVE_SOLAR_BEAM", 0) > 0:
            return ("MOVE_SOLAR_BEAM", None)
        attacker["charging_solar_beam"] = None
    if attacker.get("rampage_turns", 0) > 0 and attacker.get("rampage_move"):
        if pp_pool.get(attacker["rampage_move"], 0) > 0:
            return (attacker["rampage_move"], None)
        attacker["rampage_turns"] = 0
        attacker["rampage_move"] = None
    if attacker.get("rollout_move") and attacker.get("rollout_turns", 0) > 0:
        if pp_pool.get(attacker["rollout_move"], 0) > 0:
            return (attacker["rollout_move"], None)
        attacker["rollout_turns"] = 0
        attacker["rollout_move"] = None
    if attacker.get("bide_turns", 0) > 0:
        if pp_pool.get("MOVE_BIDE", 0) > 0:
            return ("MOVE_BIDE", None)
        attacker["bide_turns"] = 0
        attacker["bide_damage"] = 0
    if attacker.get("encore_turns", 0) > 0 and attacker.get("encore_move"):
        encore_move = attacker["encore_move"]
        if pp_pool.get(encore_move, 0) <= 0:
            # Encore ends immediately if the locked move runs out of PP -
            # falls through to normal choice logic below rather than
            # forcing anything this same turn.
            attacker["encore_turns"] = 0
            attacker["encore_move"] = None
        else:
            encore_mv_data = get_move_data_by_name(encore_move)
            blocked = (
                (encore_mv_data.get("class") == "CLASS_STATUS" and attacker.get("taunt_turns", 0) > 0) or
                (encore_move in (defender.get("imprison_moves") or [])) or
                (attacker.get("tormented") and attacker.get("last_move_used") == encore_move)
            )
            if blocked:
                return ("MOVE_STRUGGLE", None)
            return (encore_move, None)

    move_names = attacker.get("moves", [])
    usable_names = [n for n in move_names if pp_pool.get(n, 0) > 0]
    if attacker.get("taunt_turns", 0) > 0:
        # Taunt disables CLASS_STATUS move selection - if that leaves
        # nothing usable, PP-based Struggle logic below still applies.
        usable_names = [n for n in usable_names if get_move_data_by_name(n).get("class") != "CLASS_STATUS"]
    if attacker.get("tormented") and attacker.get("last_move_used") in usable_names:
        # Torment blocks using the SAME move as the immediately
        # preceding turn - a rolling restriction, not a permanent ban on
        # that move. If this was chosen before Torment landed THIS same
        # turn, it isn't affected here (last_move_used only reflects
        # PRIOR turns at the point choose_move runs for both sides) -
        # matching "may still use the move this turn even if it moves
        # after the user of Torment". A single-move Pokemon naturally
        # ends up Struggling every second round: the move is excluded,
        # forcing Struggle (via the empty-usable_names fallback below),
        # and next turn last_move_used is Struggle - which was never in
        # usable_names to begin with - so the original move is eligible
        # again.
        usable_names = [n for n in usable_names if n != attacker["last_move_used"]]
    if defender.get("imprison_moves"):
        # Imprison: any move the OPPONENT also knows (sealed at the
        # moment they used Imprison) can't be selected while they're
        # still on the field with it active.
        usable_names = [n for n in usable_names if n not in defender["imprison_moves"]]
    if attacker.get("disabled_move"):
        usable_names = [n for n in usable_names if n != attacker["disabled_move"]]          # Disable
    if attacker.get("heal_block_turns", 0) > 0:
        usable_names = [n for n in usable_names if not heal_blocked_move(attacker, n)]      # Heal Block
    if not usable_names:
        # Every move is out of PP (or this Pokemon has no moves at all) -
        # Gen4 forces Struggle here, bypassing the whole scoring pipeline.
        return ("MOVE_STRUGGLE", None)
    return (None, usable_names)


def _score_usable_moves(attacker, defender, ai_flags, bstate, rng, usable_names, other_party_alive_count, ally,
                        defender_partner, defender_other_alive_count, attacker_party):
    """Runs every active AI flag over each usable move against ONE target (`defender`) and returns {move: score}."""
    if not defender.get("item"):
        defender["ai_known_item"] = None        # BattleMon_CopyToParty: a mon holding nothing has no known item
    moves = {name: get_effective_move_data(name, attacker, defender=defender, bstate=bstate) for name in usable_names}
    # TrainerAI_CalcAllDamage: every LEARNED move slot takes part in the "highest damage" comparisons (PP, Taunt and
    # Disable do not remove a move from it), and any move that fails the comparison gate counts as 0.
    all_damages = ai_move_damage_table(attacker, defender, bstate)

    is_partner_target = bstate.get("side_of") is not None and bstate["side_of"](attacker) == bstate["side_of"](defender)

    scores = {}
    for name, mv in moves.items():
        score = 100
        if has_flag(ai_flags, "BASIC"):
            score += basic_flag_score_with_party(name, mv, attacker, defender, bstate, rng,
                                                  other_party_alive_count, defender_other_alive_count, attacker_party, ally=ally)
        if has_flag(ai_flags, "EVAL"):
            score += evaluate_attack_flag_score(name, mv, attacker, defender, bstate, rng, all_damages, is_partner_target)
        if has_flag(ai_flags, "EXPERT") and not is_partner_target:      # Expert_Main: IfTargetIsPartner Terminate
            score += expert_flag_score(name, mv, attacker, defender, bstate, rng,
                                       attacker_party=attacker_party, ally=ally,
                                       att_alive=other_party_alive_count, dfn_alive=defender_other_alive_count)
        if has_flag(ai_flags, "SETUP"):
            score += setup_first_turn_flag_score(name, bstate, is_partner_target, rng)
        if has_flag(ai_flags, "RISKY"):
            score += risky_flag_score(name, is_partner_target, rng)
        if has_flag(ai_flags, "EXTREME"):
            score += prioritize_extremes_flag_score(name, mv, all_damages, is_partner_target, rng)
        if has_flag(ai_flags, "WEATHER"):
            score += weather_flag_score(name, attacker, bstate, is_partner_target, rng)
        if has_flag(ai_flags, "HARASSMENT"):
            score += harassment_flag_score(name, is_partner_target, rng)
        if has_flag(ai_flags, "CHECK_HP"):
            score += check_hp_flag_score(name, attacker, defender, is_partner_target, rng, mv=mv, ally=ally,
                                         all_move_damages=all_damages, bstate=bstate, defender_partner=defender_partner)
        if has_flag(ai_flags, "BATON_PASS"):
            score += baton_pass_flag_score(name, mv, attacker, all_damages, other_party_alive_count, bstate, is_partner_target, rng)
        if has_flag(ai_flags, "TAG_STRATEGY") or bstate.get("is_double_battle"):
            score += tag_strategy_flag_score(name, mv, attacker, ally, defender, defender_partner, all_damages,
                                              is_partner_target, bstate, rng)
        scores[name] = score

    return scores


def choose_move(attacker, defender, ai_flags, bstate, rng, other_party_alive_count=0, ally=None, defender_partner=None,
                 defender_other_alive_count=0, attacker_party=None):
    forced, usable_names = _forced_or_usable_moves(attacker, defender, bstate)
    if forced is not None:
        return forced
    scores = _score_usable_moves(attacker, defender, ai_flags, bstate, rng, usable_names, other_party_alive_count, ally,
                                 defender_partner, defender_other_alive_count, attacker_party)
    best_score = max(scores.values())
    best_moves = [n for n, s in scores.items() if s == best_score]
    return rng.choice(best_moves)


def choose_move_and_target_double(attacker, opponents, ally, ai_flags, bstate, rng, other_party_alive_count=0,
                                  defender_other_alive_count=0, attacker_party=None):
    """TrainerAI_MainDoubles: score every usable move against EVERY possible target (each living opponent AND the ally), keep
    each target's best move (random among ties), then pick the target whose best score is highest (random among ties).
    A move aimed at the ally whose best score is under 100 counts as -1, i.e. the ally is only ever targeted by something the
    flags actively like. Returns (move_name, target); target is None when the move was forced (locked-in / Struggle) and the
    caller resolves the target from the move's range."""
    first = opponents[0] if opponents else attacker
    forced, usable_names = _forced_or_usable_moves(attacker, first, bstate)
    if forced is not None:
        return forced, None
    candidates = []
    for opp in opponents:
        candidates.append((opp, next((o for o in opponents if o is not opp), None), ally))
    if ally is not None:
        candidates.append((ally, attacker, ally))
    best_by_target = []
    for target, defender_partner, ally_arg in candidates:
        scores = _score_usable_moves(attacker, target, ai_flags, bstate, rng, usable_names, other_party_alive_count, ally_arg,
                                    defender_partner, defender_other_alive_count, attacker_party)
        top = max(scores.values())
        move = rng.choice([n for n, sc in scores.items() if sc == top])
        if target is ally and top < 100:
            top = -1
        best_by_target.append((top, move, target))
    max_score = max(t[0] for t in best_by_target)
    _, move, target = rng.choice([t for t in best_by_target if t[0] == max_score])
    return move, target


# ============================================================
# TRAINER AI: SWITCHING
# ============================================================
# See should_voluntarily_switch further down for the full 7-condition
# real Gen4 procedure this section now implements (previously a much
# simpler stand-in covering just Perish Song escape and a basic
# hopeless-matchup heuristic).


# ============================================================
# TRAINER AI: SWITCHING - a LITERAL port of trainer_ai.c's TrainerAI_ShouldSwitch and its AI_* helpers, plus
# BattleAI_PostKOSwitchIn (battle_lib.c). Every branch, every short-circuit and every RandNext draw follows the C, so a
# scripted-RNG test can pin the exact draw sequence. `BattleSystem_RandNext` is a u16 (`_ai_rand_next`).
#
# Retail behaviour reproduced on purpose (see the individual helpers):
#   * AI_PerishSongKO never fires (the counter is never 0 when it looks);
#   * the "am I trapped" guard is naive: Arena Trap traps a Flying/Levitating AI mon, Magnet Pull is ignored for allies...;
#   * AI_OnlyIneffectiveMoves counts only the INEFFECTIVE bit (a Levitate/Wonder Guard block does not count), a fainted
#     defender makes it bail out, and its second party pass treats a fainted defender as "normally effective";
#   * type-chart flags come from the chart in TABLE ORDER, so e.g. Ground vs Flying/Rock reads INEFFECTIVE|SUPER_EFFECTIVE;
#   * AI_HasSuperEffectiveMove(FALSE) has a 10% miss per super-effective move, and only counts moves with power != 0
#     (ApplyTypeChart only updates the resist/weak flags for moves with power) - CalcEffectiveness (party members) does not;
#   * Post-KO scoring is done in u8 (320 wraps to 64) and stage 2 reuses a STALE `score` when a slot is empty or power 1.
# Modelling notes (not in the C): hit tracking is `move_hit` / `move_hit_slot` on the mon, set by the engine; the
# damage estimate in Post-KO stage 2 is the simulator's own (wrapped to u8 once instead of the real two wraps).
# ============================================================
SNATCH_EXCLUDED_MOVES = {
    "MOVE_SNATCH", "MOVE_METRONOME", "MOVE_MIRROR_MOVE", "MOVE_ASSIST", "MOVE_SLEEP_TALK",
    "MOVE_MIMIC", "MOVE_SKETCH", "MOVE_COPYCAT", "MOVE_ME_FIRST", "MOVE_ROAR", "MOVE_WHIRLWIND",
}

_MS_SUPER_EFFECTIVE = 1 << 1
_MS_NOT_VERY_EFFECTIVE = 1 << 2
_MS_INEFFECTIVE = 1 << 3
_MS_LEVITATED, _MS_MAGNET_RISE, _MS_WONDER_GUARD = 1 << 8, 1 << 9, 1 << 10      # only ApplyTypeChart sets these
_MS_IMMUNE = _MS_INEFFECTIVE | _MS_WONDER_GUARD | _MS_LEVITATED | _MS_MAGNET_RISE   # MOVE_STATUS_IMMUNE

# sTypeMatchupMultipliers in TABLE ORDER (battle_lib.c). 0 = immune, 5 = not very effective, 20 = super effective. The
# MARKER row separates the Ghost immunities that Foresight/Scrappy remove.
_AI_TYPE_CHART = (
    ("TYPE_NORMAL", "TYPE_ROCK", 5), ("TYPE_NORMAL", "TYPE_STEEL", 5), ("TYPE_FIRE", "TYPE_FIRE", 5),
    ("TYPE_FIRE", "TYPE_WATER", 5), ("TYPE_FIRE", "TYPE_GRASS", 20), ("TYPE_FIRE", "TYPE_ICE", 20),
    ("TYPE_FIRE", "TYPE_BUG", 20), ("TYPE_FIRE", "TYPE_ROCK", 5), ("TYPE_FIRE", "TYPE_DRAGON", 5),
    ("TYPE_FIRE", "TYPE_STEEL", 20), ("TYPE_WATER", "TYPE_FIRE", 20), ("TYPE_WATER", "TYPE_WATER", 5),
    ("TYPE_WATER", "TYPE_GRASS", 5), ("TYPE_WATER", "TYPE_GROUND", 20), ("TYPE_WATER", "TYPE_ROCK", 20),
    ("TYPE_WATER", "TYPE_DRAGON", 5), ("TYPE_ELECTRIC", "TYPE_WATER", 20), ("TYPE_ELECTRIC", "TYPE_ELECTRIC", 5),
    ("TYPE_ELECTRIC", "TYPE_GRASS", 5), ("TYPE_ELECTRIC", "TYPE_GROUND", 0), ("TYPE_ELECTRIC", "TYPE_FLYING", 20),
    ("TYPE_ELECTRIC", "TYPE_DRAGON", 5), ("TYPE_GRASS", "TYPE_FIRE", 5), ("TYPE_GRASS", "TYPE_WATER", 20),
    ("TYPE_GRASS", "TYPE_GRASS", 5), ("TYPE_GRASS", "TYPE_POISON", 5), ("TYPE_GRASS", "TYPE_GROUND", 20),
    ("TYPE_GRASS", "TYPE_FLYING", 5), ("TYPE_GRASS", "TYPE_BUG", 5), ("TYPE_GRASS", "TYPE_ROCK", 20),
    ("TYPE_GRASS", "TYPE_DRAGON", 5), ("TYPE_GRASS", "TYPE_STEEL", 5), ("TYPE_ICE", "TYPE_WATER", 5),
    ("TYPE_ICE", "TYPE_GRASS", 20), ("TYPE_ICE", "TYPE_ICE", 5), ("TYPE_ICE", "TYPE_GROUND", 20),
    ("TYPE_ICE", "TYPE_FLYING", 20), ("TYPE_ICE", "TYPE_DRAGON", 20), ("TYPE_ICE", "TYPE_STEEL", 5),
    ("TYPE_ICE", "TYPE_FIRE", 5), ("TYPE_FIGHTING", "TYPE_NORMAL", 20), ("TYPE_FIGHTING", "TYPE_ICE", 20),
    ("TYPE_FIGHTING", "TYPE_POISON", 5), ("TYPE_FIGHTING", "TYPE_FLYING", 5), ("TYPE_FIGHTING", "TYPE_PSYCHIC", 5),
    ("TYPE_FIGHTING", "TYPE_BUG", 5), ("TYPE_FIGHTING", "TYPE_ROCK", 20), ("TYPE_FIGHTING", "TYPE_DARK", 20),
    ("TYPE_FIGHTING", "TYPE_STEEL", 20), ("TYPE_POISON", "TYPE_GRASS", 20), ("TYPE_POISON", "TYPE_POISON", 5),
    ("TYPE_POISON", "TYPE_GROUND", 5), ("TYPE_POISON", "TYPE_ROCK", 5), ("TYPE_POISON", "TYPE_GHOST", 5),
    ("TYPE_POISON", "TYPE_STEEL", 0), ("TYPE_GROUND", "TYPE_FIRE", 20), ("TYPE_GROUND", "TYPE_ELECTRIC", 20),
    ("TYPE_GROUND", "TYPE_GRASS", 5), ("TYPE_GROUND", "TYPE_POISON", 20), ("TYPE_GROUND", "TYPE_FLYING", 0),
    ("TYPE_GROUND", "TYPE_BUG", 5), ("TYPE_GROUND", "TYPE_ROCK", 20), ("TYPE_GROUND", "TYPE_STEEL", 20),
    ("TYPE_FLYING", "TYPE_ELECTRIC", 5), ("TYPE_FLYING", "TYPE_GRASS", 20), ("TYPE_FLYING", "TYPE_FIGHTING", 20),
    ("TYPE_FLYING", "TYPE_BUG", 20), ("TYPE_FLYING", "TYPE_ROCK", 5), ("TYPE_FLYING", "TYPE_STEEL", 5),
    ("TYPE_PSYCHIC", "TYPE_FIGHTING", 20), ("TYPE_PSYCHIC", "TYPE_POISON", 20),
    ("TYPE_PSYCHIC", "TYPE_PSYCHIC", 5), ("TYPE_PSYCHIC", "TYPE_DARK", 0), ("TYPE_PSYCHIC", "TYPE_STEEL", 5),
    ("TYPE_BUG", "TYPE_FIRE", 5), ("TYPE_BUG", "TYPE_GRASS", 20), ("TYPE_BUG", "TYPE_FIGHTING", 5),
    ("TYPE_BUG", "TYPE_POISON", 5), ("TYPE_BUG", "TYPE_FLYING", 5), ("TYPE_BUG", "TYPE_PSYCHIC", 20),
    ("TYPE_BUG", "TYPE_GHOST", 5), ("TYPE_BUG", "TYPE_DARK", 20), ("TYPE_BUG", "TYPE_STEEL", 5),
    ("TYPE_ROCK", "TYPE_FIRE", 20), ("TYPE_ROCK", "TYPE_ICE", 20), ("TYPE_ROCK", "TYPE_FIGHTING", 5),
    ("TYPE_ROCK", "TYPE_GROUND", 5), ("TYPE_ROCK", "TYPE_FLYING", 20), ("TYPE_ROCK", "TYPE_BUG", 20),
    ("TYPE_ROCK", "TYPE_STEEL", 5), ("TYPE_GHOST", "TYPE_NORMAL", 0), ("TYPE_GHOST", "TYPE_PSYCHIC", 20),
    ("TYPE_GHOST", "TYPE_DARK", 5), ("TYPE_GHOST", "TYPE_STEEL", 5), ("TYPE_GHOST", "TYPE_GHOST", 20),
    ("TYPE_DRAGON", "TYPE_DRAGON", 20), ("TYPE_DRAGON", "TYPE_STEEL", 5), ("TYPE_DARK", "TYPE_FIGHTING", 5),
    ("TYPE_DARK", "TYPE_PSYCHIC", 20), ("TYPE_DARK", "TYPE_GHOST", 20), ("TYPE_DARK", "TYPE_DARK", 5),
    ("TYPE_DARK", "TYPE_STEEL", 5), ("TYPE_STEEL", "TYPE_FIRE", 5), ("TYPE_STEEL", "TYPE_WATER", 5),
    ("TYPE_STEEL", "TYPE_ELECTRIC", 5), ("TYPE_STEEL", "TYPE_ICE", 20), ("TYPE_STEEL", "TYPE_ROCK", 20),
    ("TYPE_STEEL", "TYPE_STEEL", 5), ("MARKER", "MARKER", 0), ("TYPE_NORMAL", "TYPE_GHOST", 0),
    ("TYPE_FIGHTING", "TYPE_GHOST", 0),
)
_AI_ON_DAMAGING_TURN_EXCLUDED_EFFECTS = frozenset((
    "BATTLE_EFFECT_BIDE", "BATTLE_EFFECT_CHARGE_TURN_HIGH_CRIT", "BATTLE_EFFECT_CHARGE_TURN_HIGH_CRIT_FLINCH",
    "BATTLE_EFFECT_CHARGE_TURN_DEF_UP", "BATTLE_EFFECT_SKIP_CHARGE_TURN_IN_SUN", "BATTLE_EFFECT_FLY", "BATTLE_EFFECT_DIVE",
    "BATTLE_EFFECT_DIG", "BATTLE_EFFECT_BOUNCE", "BATTLE_EFFECT_FLINCH_BURN_HIT",
))
_AI_SWITCH_ABSORB_ABILITY = {"TYPE_FIRE": "FLASH_FIRE", "TYPE_WATER": "WATER_ABSORB", "TYPE_ELECTRIC": "VOLT_ABSORB"}
_AI_NO_SLOT = 6            # aiSwitchedPartySlot == 6: "no explicit pick, use the post-KO logic"


def _ai_rand_next(rng):
    """BattleSystem_RandNext: a u16."""
    return rng.randint(0, 65535)


def _ai_ms_update(flags, mul, update=True):
    """ApplyTypeMultiplier / UpateMoveStatusForTypeMul: how one matching chart row changes the move-status flags."""
    if mul == 0:
        return (flags | _MS_INEFFECTIVE) & ~(_MS_NOT_VERY_EFFECTIVE | _MS_SUPER_EFFECTIVE)
    if not update:
        return flags
    if mul == 5:
        return (flags & ~_MS_SUPER_EFFECTIVE) if flags & _MS_SUPER_EFFECTIVE else (flags | _MS_NOT_VERY_EFFECTIVE)
    return (flags & ~_MS_NOT_VERY_EFFECTIVE) if flags & _MS_NOT_VERY_EFFECTIVE else (flags | _MS_SUPER_EFFECTIVE)


def _ai_chart_flags(move_type, type1, type2, skip_ghost_rows, iron_ball, gravity, ingrain=False,
                    miracle_eye=False, update=True):
    """The chart walk shared by BattleSystem_CalcEffectiveness and BattleSystem_ApplyTypeChart (`update` is the move's
    power != 0 for the latter). Rows are visited in TABLE order, which is why the result is not simply a multiplier."""
    flags = 0
    for row_type, vs_type, mul in _AI_TYPE_CHART:
        if row_type == "MARKER":
            if skip_ghost_rows:
                break
            continue
        if row_type != move_type or vs_type not in (type1, type2):
            continue
        if vs_type == "TYPE_FLYING" and mul == 0 and (iron_ball or ingrain or gravity):
            continue                                                   # Iron Ball / Ingrain / Gravity ground the target
        if vs_type == "TYPE_DARK" and mul == 0 and miracle_eye:
            continue
        if vs_type == type1:
            flags = _ai_ms_update(flags, mul, update)
        if vs_type == type2 and type1 != type2:
            flags = _ai_ms_update(flags, mul, update)
    return flags


def _ai_move_raw_power(move_name):
    return ((_MOVES_BY_NAME.get(move_name) or {}).get("power", 0) or 0) if move_name else 0


def _ai_move_raw_type(move_name):
    return (_MOVES_BY_NAME.get(move_name) or {}).get("type", "TYPE_NORMAL")


def _ai_types(mon):
    """(TYPE_1, TYPE_2): a mono-type mon reads as dual-type of the same type."""
    t1 = mon.get("type1") or "TYPE_NORMAL"
    return t1, (mon.get("type2") or t1)


def _ai_battler_ability(mon, bstate):
    """Battler_Ability: Gastro Acid, and Levitate under Gravity or Ingrain, read as no ability."""
    if mon.get("ability_suppressed"):
        return "NONE"
    ability = ability_of(mon)
    if ability == "LEVITATE" and ((bstate or {}).get("gravity", 0) > 0 or mon.get("ingrain")):
        return "NONE"
    return ability


def _ai_battler_item_effect(mon, bstate):
    """Battler_HeldItemEffect: Klutz and Embargo hide the item."""
    if _ai_battler_ability(mon, bstate) == "KLUTZ" or mon.get("embargo_turns", 0) > 0:
        return "HOLD_EFFECT_NONE"
    return get_item_info(mon.get("item")).get("hold_effect", "HOLD_EFFECT_NONE")


def _ai_party_item_effect(mon):
    """A party Pokemon's raw held-item effect (no Klutz/Embargo: those are battle-mon state)."""
    return get_item_info(mon.get("item")).get("hold_effect", "HOLD_EFFECT_NONE")


def _ai_calc_effectiveness(move_name, move_type, attacker_ability, defender_ability, defender_iron_ball, type1, type2, gravity):
    """BattleSystem_CalcEffectiveness: move-status flags for a move against raw defender data (used for party members
    and for the last-hit move). Status moves count too: it is by TYPE only."""
    if move_name == "MOVE_STRUGGLE":
        return 0
    if attacker_ability == "NORMALIZE":
        move_type = "TYPE_NORMAL"
    if attacker_ability != "MOLD_BREAKER" and defender_ability == "LEVITATE" and move_type == "TYPE_GROUND" \
            and not gravity and not defender_iron_ball:
        flags = _MS_INEFFECTIVE
    else:
        flags = _ai_chart_flags(move_type, type1, type2, attacker_ability == "SCRAPPY", defender_iron_ball, gravity)
    if attacker_ability != "MOLD_BREAKER" and defender_ability == "WONDER_GUARD" \
            and _real_effect(move_name) not in _AI_ON_DAMAGING_TURN_EXCLUDED_EFFECTS \
            and (not flags & _MS_SUPER_EFFECTIVE or (flags & (_MS_SUPER_EFFECTIVE | _MS_NOT_VERY_EFFECTIVE)) == (_MS_SUPER_EFFECTIVE | _MS_NOT_VERY_EFFECTIVE)):
        flags |= _MS_INEFFECTIVE
    return flags


def _ai_apply_type_chart(move_name, move_type, attacker, defender, bstate):
    """BattleSystem_ApplyTypeChart's move-status flags (its damage output is not needed by the switch code) for two
    battle mons. Differences from CalcEffectiveness: Levitate / Magnet Rise short-circuit the chart (LEVITATED and
    MAGNET_RISE are NOT the INEFFECTIVE bit), Foresight/Ingrain/Miracle Eye apply, and the resist/weak flags are only
    updated for a move with power != 0. Wonder Guard adds its own flag (part of MOVE_STATUS_IMMUNE, not of INEFFECTIVE)."""
    if move_name == "MOVE_STRUGGLE":
        return 0
    gravity = (bstate or {}).get("gravity", 0) > 0
    attacker_ability = _ai_battler_ability(attacker, bstate)
    defender_ability = _ai_battler_ability(defender, bstate)
    if attacker_ability == "NORMALIZE":
        move_type = "TYPE_NORMAL"
    iron_ball = _ai_battler_item_effect(defender, bstate) == "HOLD_EFFECT_SPEED_DOWN_GROUNDED"
    power = _ai_move_raw_power(move_name)
    if defender_ability == "LEVITATE" and attacker_ability != "MOLD_BREAKER" and move_type == "TYPE_GROUND" and not iron_ball:
        flags = _MS_LEVITATED
    elif defender.get("magnet_rise_turns", 0) > 0 and not defender.get("ingrain") and move_type == "TYPE_GROUND" and not iron_ball:
        flags = _MS_MAGNET_RISE
    else:
        type1, type2 = _ai_types(defender)
        flags = _ai_chart_flags(move_type, type1, type2, bool(defender.get("foresight")) or attacker_ability == "SCRAPPY",
                                iron_ball, gravity, ingrain=bool(defender.get("ingrain")),
                                miracle_eye=bool(defender.get("miracle_eye")), update=power != 0)
    if defender_ability == "WONDER_GUARD" and attacker_ability != "MOLD_BREAKER"             and _real_effect(move_name) not in _AI_ON_DAMAGING_TURN_EXCLUDED_EFFECTS and power             and (not flags & _MS_SUPER_EFFECTIVE or (flags & (_MS_SUPER_EFFECTIVE | _MS_NOT_VERY_EFFECTIVE)) == (_MS_SUPER_EFFECTIVE | _MS_NOT_VERY_EFFECTIVE)):
        flags |= _MS_WONDER_GUARD
    return flags


def _ai_type_matchup_multiplier(attack_type, type1, type2):
    """BattleSystem_TypeMatchupMultiplier: 40 * (row/10) per matching row, in integer arithmetic (160/80/40/20/10/0)."""
    mul = 40
    for row_type, vs_type, row_mul in _AI_TYPE_CHART:
        if row_type == attack_type:
            if vs_type == type1:
                mul = mul * row_mul // 10
            if vs_type == type2 and type1 != type2:
                mul = mul * row_mul // 10
    return mul


class _AISwitch:
    """The slice of BattleContext that TrainerAI_ShouldSwitch reads, for ONE AI battler.

    party / self_idx / partner_idx: the AI's party and the party slots of its active mons (`selectedPartySlot[aiSlot1]`,
    `[aiSlot2]`; partner_idx is None in singles, where aiSlot2 == aiSlot1). `claimed` holds `aiSwitchedPartySlot` values
    other slots already took this turn. opp_slots: the two opposing battler slots (PLAYER_1, PLAYER_2), each a mon or
    None; in singles only slot 0 exists and it stands in for both. across_slot: the slot directly opposite us.
    move_hit / move_hit_battler: the last move that hit this battler (`moveHit`) and who used it (`moveHitBattler`)."""

    def __init__(self, party, self_idx, partner_idx, opp_slots, bstate, rng, is_double=False, across_slot=0,
                 claimed=(), move_hit=None, move_hit_battler=None):
        self.party, self.self_idx, self.partner_idx = party, self_idx, partner_idx
        self.opp_slots = list(opp_slots) + [None] * (2 - len(opp_slots))
        self.b, self.rng, self.is_double, self.across_slot = bstate or {}, rng, is_double, across_slot
        self.active = party[self_idx]
        self.selected = {self_idx, partner_idx if partner_idx is not None else self_idx}
        self.claimed = set(claimed)
        self.move_hit, self.move_hit_battler = move_hit, move_hit_battler
        self.gravity = self.b.get("gravity", 0) > 0
        self.switched_slot = _AI_NO_SLOT           # battleCtx->aiSwitchedPartySlot[battler]

    # ---- small helpers
    def rand(self):
        return _ai_rand_next(self.rng)

    def eligible(self, i):
        mon = self.party[i]
        return mon["hp"] > 0 and i not in self.selected and i not in self.claimed

    def pick(self, i):
        self.switched_slot = i

    def moves(self, mon):
        return [m for m in mon.get("moves", []) if m]

    def move_type(self, name, mon, target):
        """TrainerAI_MoveType / Move_CalcVariableType: the move's type as its user will use it."""
        return get_effective_move_data(name, mon, defender=target, bstate=self.b).get("type", "TYPE_NORMAL")

    def defender_slots(self):
        d1 = self.opp_slots[0]
        return (d1, self.opp_slots[1]) if self.is_double else (d1, d1)

    def flags_vs_battler(self, name, mon, target):
        """`effectiveness = 0; if (curHP) ApplyTypeChart(...)` for one of our battle mons against an opposing battler."""
        if target is None or target["hp"] <= 0:
            return 0
        return _ai_apply_type_chart(name, self.move_type(name, mon, target), mon, target, self.b)

    def flags_from_party_mon(self, name, mon, target):
        """`if (curHP) CalcEffectiveness(...)` for a party Pokemon's move against an opposing battler."""
        if target is None or target["hp"] <= 0:
            return 0
        t1, t2 = _ai_types(target)
        return _ai_calc_effectiveness(
            name, self.move_type(name, mon, target), ability_of(mon), _ai_battler_ability(target, self.b),
            _ai_battler_item_effect(target, self.b) == "HOLD_EFFECT_SPEED_DOWN_GROUNDED", t1, t2, self.gravity)

    # ---- the AI_* routines
    def perish_song_ko(self):
        """AI_PerishSongKO: bugged in retail - it fires only at perishSongTurns == 0, which the AI never gets to see."""
        return False

    def cannot_damage_wonder_guard(self):
        """AI_CannotDamageWonderGuard (singles only): our moves cannot hurt a Wonder Guard foe, so switch 2/3 of the time
        to a party member that can."""
        if self.is_double:
            return False
        foe = self.opp_slots[0]
        if foe is None or ability_of(foe) != "WONDER_GUARD":
            return False
        for name in self.moves(self.active):
            if self.flags_vs_battler(name, self.active, foe) & _MS_SUPER_EFFECTIVE:
                return False
        for i, mon in enumerate(self.party):
            if mon["hp"] > 0 and i != self.self_idx:
                for name in self.moves(mon):
                    if self.flags_from_party_mon(name, mon, foe) & _MS_SUPER_EFFECTIVE and self.rand() % 3 < 2:
                        self.pick(i)
                        return True
        return False

    def only_ineffective_moves(self):
        """AI_OnlyIneffectiveMoves: every damaging move of ours is type-immune against both opposing battlers (and we have
        at least two of them) -> switch to a benched mon with a super-effective move (2/3), else a normal one (1/2)."""
        d1, d2 = self.defender_slots()
        num_moves = 0
        for name in self.moves(self.active):
            if _ai_move_raw_power(name):
                num_moves += 1
                if not self.flags_vs_battler(name, self.active, d1) & _MS_INEFFECTIVE:
                    return False
                if not self.flags_vs_battler(name, self.active, d2) & _MS_INEFFECTIVE:
                    return False
        if num_moves < 2:
            return False
        for i, mon in enumerate(self.party):                                    # super-effective, 2/3
            if not self.eligible(i):
                continue
            for name in self.moves(mon):
                if _ai_move_raw_power(name):
                    if self.flags_from_party_mon(name, mon, d1) & _MS_SUPER_EFFECTIVE and self.rand() % 3 < 2:
                        self.pick(i)
                        return True
                    if self.flags_from_party_mon(name, mon, d2) & _MS_SUPER_EFFECTIVE and self.rand() % 3 < 2:
                        self.pick(i)
                        return True
        for i, mon in enumerate(self.party):                                    # normally effective, 1/2
            if not self.eligible(i):
                continue
            for name in self.moves(mon):
                if _ai_move_raw_power(name):
                    if self.flags_from_party_mon(name, mon, d1) == 0 and self.rand() % 2 == 0:
                        self.pick(i)
                        return True
                    if self.flags_from_party_mon(name, mon, d2) == 0 and self.rand() % 2 == 0:
                        self.pick(i)
                        return True
        return False

    def has_super_effective_move(self, always):
        """AI_HasSuperEffectiveMove. always=False: each super-effective move only counts 90% of the time."""
        for slot in ((self.across_slot,) if not self.is_double else (self.across_slot, 1 - self.across_slot)):
            foe = self.opp_slots[slot]
            if foe is None or foe["hp"] <= 0:                                 # battlersSwitchingMask
                continue
            for name in self.moves(self.active):
                if self.flags_vs_battler(name, self.active, foe) & _MS_SUPER_EFFECTIVE:
                    if always:
                        return True
                    if self.rand() % 10 != 0:
                        return True
        return False

    def has_absorb_ability_in_party(self):
        """AI_HasAbsorbAbilityInParty: the last move to hit us was Fire/Water/Electric and a benched mon absorbs it."""
        if self.has_super_effective_move(True) and self.rand() % 3 != 0:
            return False
        if not self.move_hit:
            return False
        if _ai_move_raw_power(self.move_hit) == 0:
            return False
        check_ability = _AI_SWITCH_ABSORB_ABILITY.get(_ai_move_raw_type(self.move_hit))
        if check_ability is None:
            return False
        if _ai_battler_ability(self.active, self.b) == check_ability:
            return False
        for i, mon in enumerate(self.party):
            if self.eligible(i) and ability_of(mon) == check_ability and (self.rand() & 1):
                self.pick(i)
                return True
        return False

    def has_party_member_with_super_effective_move(self, check_effectiveness, rand):
        """AI_HasPartyMemberWithSuperEffectiveMove: a benched mon whose type answers the last hit (immune = INEFFECTIVE bit,
        resist = NOT_VERY_EFFECTIVE bit) and that has a super-effective move against whoever hit us."""
        hitter = self.move_hit_battler
        if not self.move_hit or hitter is None:
            return False
        if _ai_move_raw_power(self.move_hit) == 0:
            return False
        hitter_ability = _ai_battler_ability(hitter, self.b)
        hitter_item_iron = _ai_battler_item_effect(hitter, self.b) == "HOLD_EFFECT_SPEED_DOWN_GROUNDED"
        h1, h2 = _ai_types(hitter)
        for i, mon in enumerate(self.party):
            if not self.eligible(i):
                continue
            m1, m2 = _ai_types(mon)
            flags = _ai_calc_effectiveness(
                self.move_hit, self.move_type(self.move_hit, hitter, mon), hitter_ability, ability_of(mon),
                _ai_party_item_effect(mon) == "HOLD_EFFECT_SPEED_DOWN_GROUNDED", m1, m2, self.gravity)
            if flags & check_effectiveness:
                for name in self.moves(mon):
                    flags = _ai_calc_effectiveness(
                        name, self.move_type(name, mon, hitter), ability_of(mon), hitter_ability, hitter_item_iron, h1, h2, self.gravity)
                    if flags & _MS_SUPER_EFFECTIVE and self.rand() % rand == 0:
                        self.pick(i)
                        return True
        return False

    def is_asleep_with_natural_cure(self):
        """AI_IsAsleepWithNaturalCure."""
        a = self.active
        if a.get("status") != "SLEEP" or _ai_battler_ability(a, self.b) != "NATURAL_CURE" or a["hp"] < a["max_hp"] // 2:
            return False
        if not self.move_hit and (self.rand() & 1):
            self.pick(_AI_NO_SLOT)
            return True
        if _ai_move_raw_power(self.move_hit) == 0 and (self.rand() & 1):
            self.pick(_AI_NO_SLOT)
            return True
        if self.has_party_member_with_super_effective_move(_MS_INEFFECTIVE, 1):
            return True
        if self.has_party_member_with_super_effective_move(_MS_NOT_VERY_EFFECTIVE, 1):
            return True
        if self.rand() & 1:
            self.pick(_AI_NO_SLOT)
            return True
        return False

    def is_heavily_stat_boosted(self):
        """AI_IsHeavilyStatBoosted: the positive stat stages sum to 4 or more."""
        return sum(max(0, self.active.get(k, 0)) for k in
                   ("atk_stage", "def_stage", "spe_stage", "spa_stage", "spd_stage", "acc_stage", "eva_stage")) >= 4

    def is_trapped(self):
        """The 'illegal switch' guard at the top of TrainerAI_ShouldSwitch (naive on purpose, see the module comment)."""
        a = self.active
        if a.get("trapped_turns", 0) > 0 or a.get("mean_look") or a.get("ingrain"):
            return True
        for foe in self.opp_slots[:2 if self.is_double else 1]:
            if foe is not None and _ai_battler_ability(foe, self.b) in ("SHADOW_TAG", "ARENA_TRAP"):
                return True
        if "TYPE_STEEL" in _ai_types(a):
            others = [m for m in self.opp_slots[:2 if self.is_double else 1] if m is not None]
            if self.partner_idx is not None:
                others.append(self.party[self.partner_idx])
            if any(_ai_battler_ability(m, self.b) == "MAGNET_PULL" for m in others):
                return True
        return False

    def should_switch(self):
        """TrainerAI_ShouldSwitch. Returns True when the AI switches; `switched_slot` then holds the chosen party slot, or
        _AI_NO_SLOT when the caller must pick a replacement with the post-KO logic."""
        if self.is_trapped():
            return False
        alive_party_mons = sum(1 for i in range(len(self.party)) if self.eligible(i))
        if not alive_party_mons:
            return False
        if self.perish_song_ko():
            return True
        if self.cannot_damage_wonder_guard():
            return True
        if self.only_ineffective_moves():
            return True
        if self.has_absorb_ability_in_party():
            return True
        if self.is_asleep_with_natural_cure():
            return True
        if self.has_super_effective_move(False):
            return False
        if self.is_heavily_stat_boosted():
            return False
        if self.has_party_member_with_super_effective_move(_MS_INEFFECTIVE, 2):           # 0x8: immune to the last hit
            return True
        if self.has_party_member_with_super_effective_move(_MS_NOT_VERY_EFFECTIVE, 3):         # 0x4: resists the last hit
            return True
        return False


def ai_post_ko_switch_in(party, exclude_indices, opponents, battler, bstate, rng, is_double=False):
    """BattleAI_PostKOSwitchIn: who replaces a fainted (or Natural-Cure-retreating) battler. Returns a party index, or
    _AI_NO_SLOT when nothing scored (the caller then takes the first living, unselected mon in party order).

    exclude_indices are the slots that cannot be picked (both active slots plus anything already claimed). `opponents` is
    the opposing battler slots; in doubles one is picked with a RandNext draw first (falling back to the other one when it
    has fainted). `battler` is the mon that just left: Stage 2 rates every candidate's moves AS IF the fainted battler used
    them (its Attack/level/types), so only the moves differ between candidates."""
    exclude = set(exclude_indices)
    slots = [m for m in list(opponents) + [None, None]][:2]
    if is_double:
        rnd = _ai_rand_next(rng) & 1
        defender = slots[rnd]
        if defender is None or defender["hp"] <= 0:
            defender = slots[rnd ^ 1]
    else:
        defender = slots[0]
    if defender is None:
        return _AI_NO_SLOT
    d1, d2 = _ai_types(defender)
    gravity = (bstate or {}).get("gravity", 0) > 0
    party_size = len(party)

    def candidate(i):
        return party[i]["hp"] > 0 and i not in exclude

    score = 0                                     # u8 in the C, and NOT reset between the two stages
    disregarded = 0
    while disregarded != 0x3F:
        max_score, picked = 0, _AI_NO_SLOT
        for i in range(party_size):
            if candidate(i) and not (disregarded >> i) & 1:
                m1, m2 = _ai_types(party[i])
                score = (_ai_type_matchup_multiplier(m1, d1, d2) + _ai_type_matchup_multiplier(m2, d1, d2)) & 0xFF
                if max_score < score:
                    max_score, picked = score, i
            else:
                disregarded |= 1 << i
        if picked != _AI_NO_SLOT:
            mon = party[picked]
            found = False
            for name in mon.get("moves", []):
                if not name:
                    continue
                move_type = get_effective_move_data(name, mon, defender=defender, bstate=bstate).get("type", "TYPE_NORMAL")
                flags = _ai_calc_effectiveness(name, move_type, ability_of(mon), _ai_battler_ability(defender, bstate),
                                               _ai_battler_item_effect(defender, bstate) == "HOLD_EFFECT_SPEED_DOWN_GROUNDED",
                                               d1, d2, gravity)
                if flags & _MS_SUPER_EFFECTIVE:
                    found = True
                    break
            if not found:
                disregarded |= 1 << picked
            else:
                return picked
        else:
            disregarded = 0x3F

    max_score, picked = 0, _AI_NO_SLOT
    for i in range(party_size):
        if candidate(i):
            names = list(party[i].get("moves", []))[:4] + [None] * (4 - len(party[i].get("moves", [])[:4]))
            for name in names:
                if name and _ai_move_raw_power(name) != 1:
                    mv = get_effective_move_data(name, battler, defender=defender, bstate=bstate)
                    flags = _ai_apply_type_chart(name, mv.get("type", "TYPE_NORMAL"), battler, defender, bstate)
                    if flags & _MS_IMMUNE:
                        score = 0
                    else:
                        try:
                            score = estimate_max_damage(battler, defender, mv, weather_now(bstate),
                                                        bstate=bstate)[0] & 0xFF
                        except ZeroDivisionError:
                            score = 0
                if max_score < score:
                    max_score, picked = score, i
    return picked


def select_switch_in_target(party, exclude_indices, target, bstate, rng, battler=None, opponents=None, is_double=False):
    """The engine-facing send-in picker (after a faint or a pivot move): BattleAI_PostKOSwitchIn, then PickCommand's
    fallback of the first living, unselected party member. Returns a party index, or None if nobody is left.
    `battler` defaults to the first excluded slot's mon (the one that just left)."""
    exclude = list(exclude_indices)
    if not any(party[i]["hp"] > 0 for i in range(len(party)) if i not in exclude):
        return None
    if battler is None:
        battler = party[exclude[0]] if exclude else next((m for m in party if m["hp"] > 0), party[0])
    picked = ai_post_ko_switch_in(party, exclude, opponents if opponents is not None else [target], battler, bstate, rng,
                                  is_double=is_double)
    if picked == _AI_NO_SLOT:
        picked = next((i for i in range(len(party)) if party[i]["hp"] > 0 and i not in exclude), None)
    return picked


def _ai_switch_decision(ctx):
    """Shared tail of the two voluntary-switch entry points: run ShouldSwitch, then resolve a 'use post-KO logic' pick."""
    if not ctx.should_switch():
        return None
    slot = ctx.switched_slot
    if slot == _AI_NO_SLOT:
        slot = select_switch_in_target(ctx.party, sorted(ctx.selected | ctx.claimed), ctx.opp_slots[0], ctx.b, ctx.rng,
                                       battler=ctx.active, opponents=ctx.opp_slots, is_double=ctx.is_double)
    return slot


def should_voluntarily_switch(active, active_idx, opponent, party, bstate, rng):
    """TrainerAI_ShouldSwitch for a singles battler. Returns the party index to switch to, or None."""
    if opponent is None:
        return None
    ctx = _AISwitch(party, active_idx, None, [opponent], bstate, rng, move_hit=active.get("move_hit"),
                    move_hit_battler=opponent if active.get("move_hit") else None)
    return _ai_switch_decision(ctx)


def should_voluntarily_switch_double(active, active_idx, ally_idx, opponents, party, bstate, rng, slot=0, opp_slots=None,
                                     claimed=()):
    """TrainerAI_ShouldSwitch for one doubles battler. `opponents` are the living opposing mons; `opp_slots` (both opposing
    slots in order, fainted ones included) and `slot` (our slot index, which is the one directly across) refine it."""
    if opp_slots is None:
        opp_slots = list(opponents)
    hit_slot = active.get("move_hit_slot")
    hitter = opp_slots[hit_slot] if (active.get("move_hit") and hit_slot is not None and hit_slot < len(opp_slots)) else None
    ctx = _AISwitch(party, active_idx, ally_idx, opp_slots, bstate, rng, is_double=True, across_slot=slot, claimed=claimed,
                    move_hit=active.get("move_hit"), move_hit_battler=hitter)
    return _ai_switch_decision(ctx)


# ============================================================
# TRAINER AI: ITEM USE - a literal port of TrainerAI_ShouldUseItem (trainer_ai.c). Retail quirks reproduced:
#   * the loop has NO break: once one item fires, every later in-gate slot is "used" too (its slot is emptied and it becomes
#     `usedItem`, while the category/condition stay those of the item that actually matched);
#   * an item is only eligible when `i == 0 or alive_mons <= count - i + 1`, with `count` the trainer's starting item total;
#   * Full Heal reads as a Sleep cure only (the chain tests one heal flag at a time);
#   * stat boosters and Guard Spec only fire while `fakeOutTurnNumber - totalTurns >= 0`, i.e. on the turn a mon enters and
#     the next one; an item with no recognised effect is inert.
# The item's effect (heal amount, cure, +1 stage, Mist) follows the bag-item scripts; using one costs the turn.
# ============================================================
AI_MAX_TRAINER_ITEMS = 4
# Doubles: BattleControllerPlayer_InitAI fills trainerItems[battler >> 1] from BattleSystem_GetTrainerItem(battler), i.e. from
# battleSys->trainers[battler] itself, and Trainer_Encounter only loads a trainer for a battler whose trainerIDs entry is set.
# A single-trainer double (encounter.c) leaves trainerIDs[BATTLER_ENEMY_2] = 0, so the second slot owns NO items and only the
# first slot's mon can ever use the trainer's four (they are not a shared pool). Two-trainer (tag/multi) battles would give
# each slot its own pool; the tournament only ever fields one trainer per side.
AI_ITEM_POOL_SLOT = 0


def new_ai_item_state(item_names):
    """BattleControllerPlayer_InitAI: the trainer's non-empty items, in order, plus the starting count."""
    items = [i for i in (item_names or []) if i and i != "ITEM_NONE"][:AI_MAX_TRAINER_ITEMS] if TRAINER_ITEMS_ENABLED else []
    return {"items": items, "count": len(items)}


def _ai_item_u8(value):
    return int(value) & 0xFF if value is not None else 0


def ai_should_use_item(mon, party, state, bstate):
    """TrainerAI_ShouldUseItem for one battler. Returns None, or {"item", "category", "condition"} and empties the used
    slots of `state` (see the quirk notes above)."""
    if not state or not state["items"] or mon.get("embargo_turns", 0) > 0:
        return None
    alive = sum(1 for m in party if m["hp"] > 0)
    items, count = state["items"], state["count"]
    hp, max_hp = mon["hp"], mon["max_hp"]
    status = mon.get("status", "NONE")
    first_turns = mon.get("entered_turn", 1) - (bstate.get("turn", 1) - 1) >= 0     # fakeOutTurnNumber - totalTurns >= 0
    result, category, condition, used = False, None, 0, None
    for i in range(AI_MAX_TRAINER_ITEMS):
        if i == 0 or alive <= count - i + 1:
            item = items[i] if i < len(items) else None
            if not item:
                continue
            params = get_item_info(item).get("use_params") or {}
            hp_restore = _ai_item_u8(params.get("hpRestored"))
            if item == "ITEM_FULL_RESTORE":
                if hp < max_hp // 4 and hp:
                    category, result = "FULL_RESTORE", True
            elif params.get("hpRestored") is not None:
                if hp_restore and hp and (hp < max_hp // 4 or (max_hp - hp) > hp_restore):
                    category, result = "RECOVER_HP", True
            elif params.get("healSleep"):
                if status == "SLEEP":
                    category, condition, result = "RECOVER_STATUS", condition | (1 << 5), True
            elif params.get("healPoison"):
                if status in ("POISON", "TOXIC"):
                    category, condition, result = "RECOVER_STATUS", condition | (1 << 4), True
            elif params.get("healBurn"):
                if status == "BURN":
                    category, condition, result = "RECOVER_STATUS", condition | (1 << 3), True
            elif params.get("healFreeze"):
                if status == "FREEZE":
                    category, condition, result = "RECOVER_STATUS", condition | (1 << 2), True
            elif params.get("healParalysis"):
                if status == "PARALYSIS":
                    category, condition, result = "RECOVER_STATUS", condition | (1 << 1), True
            elif params.get("healConfusion"):
                if mon.get("confused"):
                    category, condition, result = "RECOVER_STATUS", condition | (1 << 0), True
            elif first_turns:
                for key, stat in (("atkStages", "atk"), ("defStages", "def"), ("spatkStages", "spa"), ("spdefStages", "spd"),
                                  ("speedStages", "spe"), ("accStages", "acc")):
                    if params.get(key):
                        category, condition, result = "STAT_BOOSTER", stat, True
                        break
                else:
                    if params.get("guardSpec") and not bstate["sides"][bstate["side_of"](mon)].get("mist", 0):
                        category, result = "GUARD_SPEC", True
            if result:
                used = item
                items[i] = None
    if not result:
        return None
    state["items"] = [None if i is None else i for i in items]
    return {"item": used, "category": category, "condition": condition}


def apply_ai_item(mon, use, bstate, log, trainer_name):
    """The bag-item scripts' effect on the user (the AI's own mon)."""
    info = get_item_info(use["item"])
    params = info.get("use_params") or {}
    log.append(f"  > {trainer_name} uses one {info.get('name', use['item'])}!")
    cat = use["category"]
    if cat == "FULL_RESTORE":
        mon["status"] = "NONE"
        clear_confusion(mon)
    if cat in ("FULL_RESTORE", "RECOVER_HP"):
        amount = _ai_item_u8(params.get("hpRestored"))
        heal = mon["max_hp"] - mon["hp"] if amount == 255 else min(amount, mon["max_hp"] - mon["hp"])
        mon["hp"] += heal
        log.append(f"    {mon['species_display']} recovered {heal} HP!")
    elif cat == "RECOVER_STATUS":
        if use["condition"] & 1:
            clear_confusion(mon)
        else:
            mon["status"] = "NONE"
        log.append(f"    {mon['species_display']}'s status was cured!")
    elif cat == "STAT_BOOSTER":
        key = f"{use['condition']}_stage"
        mon[key] = min(6, mon.get(key, 0) + 1)
        log.append(f"    {mon['species_display']}'s {use['condition'].upper()} rose!")
    elif cat == "GUARD_SPEC":
        bstate["sides"][bstate["side_of"](mon)]["mist"] = 5
        log.append("    The team became shrouded in mist!")


def move_targets_opponent_for_pressure(mv):
    """Whether mv should be considered as "targeting" an opposing
    Pokemon for Pressure purposes - true for anything except a move
    whose range is purely the user or the user's own side (stat-
    boosting setup moves, Recover/Rest, Reflect/Light Screen/Safeguard,
    Substitute, etc.). Field-wide moves like Rain Dance still count,
    matching the real mechanic - defaulting to True for any range this
    doesn't specifically recognize as self/own-side-only is the safer
    choice, since that's exactly what the real mechanic does for
    weather-setting and other field-wide moves."""
    return mv.get("range") not in ("RANGE_USER", "RANGE_USER_SIDE")


def apply_pressure_extra_pp(actor, mv, mv_name, targets):
    """Pressure: each DISTINCT other Pokemon among targets that currently
    has Pressure costs one extra PP beyond the normal 1 already deducted
    by the caller - applies even on a miss, against multiple targets, a
    field-wide move, or a target immune/protected against the move,
    since none of that changes whether the move was used AT the
    Pressure holder. No extra deduction once PP has already hit 0."""
    if mv_name == "MOVE_STRUGGLE" or mv_name not in actor.get("move_pp", {}):
        return
    if not move_targets_opponent_for_pressure(mv):
        return
    if actor["move_pp"][mv_name] <= 0:
        return
    seen = set()
    extra = 0
    for t in targets:
        if t is None or t is actor:
            continue
        tid = id(t)
        if tid in seen:
            continue
        seen.add(tid)
        if t.get("hp", 0) > 0 and has_ability(t, "PRESSURE"):
            extra += 1
    if extra > 0:
        actor["move_pp"][mv_name] = max(0, actor["move_pp"][mv_name] - extra)


def note_move_used_on(actor, target, mv_name, mv, actor_slot=0):
    """UpdateFlagsWhenHit / ClearFlags: a move used on a target is remembered as that target's `moveHit` (whatever the
    move, hit or miss - the AI later only cares whether it had power), and the user's OWN record is wiped once it acts.
    Self- and side-targeted moves have no defender, so they record nothing."""
    actor["move_hit"] = None
    if target is not None and target is not actor and mv.get("range") not in ("RANGE_USER", "RANGE_USER_SIDE"):
        target["move_hit"] = mv_name
        target["move_hit_slot"] = actor_slot
        if "MOVE_FLAG_CAN_MIRROR_MOVE" in ((_MOVES_BY_NAME.get(mv_name) or {}).get("flags") or []):
            target["move_copied"] = mv_name


def choose_switch(active, opponent, party, active_idx, rng, bstate=None):
    """Decides whether the trainer AI switches its active Pokemon out THIS turn, before either side picks a move.
    Returns the party index to switch to, or None to keep fighting. Trapping (binding moves, Mean Look, Ingrain, Shadow
    Tag / Arena Trap / Magnet Pull) is judged inside TrainerAI_ShouldSwitch itself - see _AISwitch.is_trapped."""
    return should_voluntarily_switch(active, active_idx, opponent, party, bstate, rng)


def apply_switch_in_ability(mon, opponent, bstate, log, defer_weather=False):
    """Intimidate / weather-setting abilities triggering on a mid-battle
    switch-in. (apply_entry_abilities below only covers the two Pokemon
    sent out at the very start of the battle.)

    defer_weather=True is for a MID-TURN fainting replacement
    specifically: the replacement "doesn't actually hit the field until
    the very end of the turn" for damage-calculation purposes, so a
    weather-setting ability triggering here stores the new weather as
    PENDING (bstate["pending_weather"]) rather than committing it to
    bstate["weather"] immediately - the message still logs right away,
    matching the real games' visible switch-in announcement, but the
    weather doesn't actually start dealing (or blocking) damage until
    the commit step after this turn's own weather-damage phase has
    already run using whatever weather was active before this switch-in.
    An end-of-turn fainting replacement doesn't need this at all, since
    that phase has already fully completed by the time it happens - the
    new weather can't retroactively affect this turn's damage regardless
    of how it's set. Neither does a battle-start entry or an ordinary
    voluntary switch, both of which should immediately count for this
    same turn's damage as normal."""
    try_trace(mon, [opponent], log)
    ab = ability_of(mon)
    if ab == "INTIMIDATE" and _intimidate_lands(opponent):
        before = opponent.get("atk_stage", 0)
        opponent["atk_stage"] = max(-6, before - 1)
        ai_reveal_ability(mon)
        log.append(f"    {opponent['species_display']}'s ATK fell from Intimidate!")
        if opponent["atk_stage"] != before:
            note_debuff_source(bstate, opponent, "atk", mon, before - opponent["atk_stage"])
    elif ab == "PRESSURE":
        ai_reveal_ability(mon)
        log.append(f"    {mon['species_display']} is exerting its Pressure!")
    elif ab in ("DROUGHT", "DRIZZLE", "SAND_STREAM", "SNOW_WARNING"):
        weather, weather_msg = {
            "DROUGHT": ("SUN", "The sunlight turned harsh!"),
            "DRIZZLE": ("RAIN", "It started to rain!"),
            "SAND_STREAM": ("SANDSTORM", "A sandstorm kicked up!"),
            "SNOW_WARNING": ("HAIL", "It started to hail!"),
        }[ab]
        ai_reveal_ability(mon)
        note_weather_set(bstate, weather, mon)
        log.append(f"    {mon['species_display']}'s {ab.replace('_', ' ').title()} - {weather_msg}")
        if defer_weather:
            bstate["pending_weather"] = (weather, PERMANENT_WEATHER_TURNS)
        else:
            # Ability-triggered weather is permanent in Gen4, unlike the
            # 5-turn weather a MOVE like Rain Dance/Sandstorm sets.
            bstate["weather"], bstate["weather_turns"] = weather, PERMANENT_WEATHER_TURNS
    try_download(mon, [opponent], log)


def perform_forced_switch(target_party, target_idx, rng, exclude=()):
    """Whirlwind/Roar: forces a RANDOM different, non-fainted party member
    to replace the current active Pokemon (unlike a voluntary switch,
    the target's AI has no say in which one). Returns the new active
    index, or None if there's no one else to bring in (last Pokemon
    standing) - in which case the move simply fails."""
    bench = [i for i, p in enumerate(target_party) if i != target_idx and i not in exclude and p["hp"] > 0]
    if not bench:
        return None
    return rng.choice(bench)


# ============================================================
# CONFUSION: subscript_confuse.s, the confusion stage of BattleControllerPlayer_CheckStatusDisruption,
# subscript_snap_out_of_confusion.s / subscript_hurt_self_in_confusion.s and the Thrash-end check of the mon condition loop.
# Confusion is a volatile condition whose 3 low bits (VOLATILE_CONDITION_CONFUSION_0..2) are a COUNTER, not a flag:
#   * subscript_confuse rolls `Random 3, 2` = RandNext() % (3 + 1) + 2, i.e. 2, 3, 4 or 5 (each 1/4), and ORs it into the volatile word
#   * each time the confused mon is about to act the counter drops by one BEFORE anything else: if it is still > 0 the mon
#     rolls RandNext() & 1 (half the time "is confused!" and the move goes ahead, half the time it hurts itself and the move is
#     lost); if it reached 0 the mon "snapped out of confusion!" and moves normally that same turn - no self-hit chance.
#     So a confusion rolled as n costs n-1 turns with a 50% self-hit, then a free turn that also ends it.
#   * the check sits after sleep / freeze / truant / recharge / flinch / disable / taunt and BEFORE paralysis and attraction: a
#     mon that is fully paralyzed has already ticked (and may already have hurt itself); it runs when the mon's action comes up
#     (check_status_disruption), not at the top of the turn
#   * a self-hit sets moveFailFlags.confused, and BattleContext_MoveFailed at the end of the turn cancels a Thrash lock (no fatigue)
#   * Baton Pass keeps the counter (VOLATILE_CONDITION_BATON_PASSED); switching out, Lum Berry and the AI's Full Restore / Full
#     Heal-style items clear it (UpdateMonData FLAG_OFF CONFUSION)
# The sim keeps `confused` (the flag every AI check reads) next to `confuse_turns` (the counter); they always change together.
# ============================================================
CONFUSION_DIRECT, CONFUSION_INDIRECT, CONFUSION_MOVE_EFFECT = "DIRECT", "INDIRECT", "MOVE_EFFECT"


def roll_confusion_turns(rng):
    """`Random 3, 2` in subscript_confuse: RandNext() % (3 + 1) + 2."""
    return 2 + int(rng.random() * 4)


def clear_confusion(mon):
    mon["confused"] = False
    mon["confuse_turns"] = 0


def try_confuse(target, source, rng, log, kind):
    """subscript_confuse.s for one target. `source` is the mon whose move causes it (a Mold Breaker source ignores Own Tempo),
    None for the rampage fatigue. `kind` is the side-effect type the retail scripts run it with:
      DIRECT       a status move (Confuse Ray, Supersonic, Sweet Kiss, Teeter Dance) or Swagger / Flatter: stopped by Own Tempo,
                   a Substitute, an existing confusion or Safeguard
      INDIRECT     a secondary effect (Psybeam, Confusion, Dynamic Punch...): the same gates (Shield Dust is the caller's)
      MOVE_EFFECT  subscript_thrash_end: ONLY Own Tempo stops it - a Substitute and Safeguard do not (the mon condition loop
                   only starts the script while the mon is not already confused, see rampage_fatigue)
    On success the counter is OR-ed into the volatile word (UpdateMonDataFromVar FLAG_ON). Returns whether it landed."""
    if has_ability(target, "OWN_TEMPO") and not (source is not None and has_ability(source, "MOLD_BREAKER")):
        return False
    if kind != CONFUSION_MOVE_EFFECT and (_substituted(target) or target.get("confused") or target.get("safeguard", 0) > 0):
        return False
    target["confused"] = True
    target["confuse_turns"] = target.get("confuse_turns", 0) | roll_confusion_turns(rng)
    log.append(f"    {target['species_display']} became confused{' due to fatigue' if kind == CONFUSION_MOVE_EFFECT else ''}!")
    return True


def rampage_fatigue(actor, rng, log):
    """MON_COND_CHECK_STATE_THRASH: the Outrage / Petal Dance / Thrash lock has run out; subscript_thrash_end confuses the mon
    unless it is already confused (an existing confusion keeps its own counter)."""
    if not actor.get("confused"):
        try_confuse(actor, None, rng, log, CONFUSION_MOVE_EFFECT)


def confusion_check(mon, rng, log, bstate=None):
    """The confusion stage of CheckStatusDisruption for a mon that is about to act. Returns False when it hurt itself."""
    turns = mon.get("confuse_turns", 0) - 1
    if turns > 0:
        mon["confuse_turns"] = turns
        if rng.random() < 0.5:                                  # RandNext() & 1 == 0: subscript_hurt_self_in_confusion
            dmg = compute_confusion_damage(mon, rng, bstate)
            mon["hp"] -= dmg
            mon["_damage_taken_this_turn"] = mon.get("_damage_taken_this_turn", 0) + dmg
            unlock_move_choice(mon)                             # subscript_hurt_self_in_confusion: UnlockMoveChoice
            mon["rampage_turns"] = 0                            # moveFailFlags.confused -> BattleContext_MoveFailed ends a Thrash lock
            mon["rampage_move"] = None
            log.append(f"    {mon['species_display']} is confused! It hurt itself in its confusion! (-{dmg} HP)")
            return False
        log.append(f"    {mon['species_display']} is confused!")
        return True
    clear_confusion(mon)                                        # counter reached 0: subscript_snap_out_of_confusion, then it moves
    log.append(f"    {mon['species_display']} snapped out of confusion!")
    return True


# ============================================================
# STATUS / END-OF-TURN PROCESSING
# ============================================================
# Retail runs the disruption stages (below) when a mon's ACTION comes up, not at the top of the turn: BattleControllerPlayer_FightCommand ->
# BeforeMove -> CheckStatusDisruption. Everything before that is the same for every mon: the AI has already picked its move (a sleeping,
# paralyzed or flinch-doomed mon has chosen first, and the choice fixes its place in the action order), and a status that lands MID-turn
# (a faster mon's Spore, Thunder Wave, Confuse Ray, Headbutt...) takes effect on a slower mon in that very turn.
# Stages, in the C order (Truant, Uproar, Imprison, Gravity, Heal Block and the Disable / Taunt re-check are not modelled here: the sim filters
# Disable / Taunt / Imprison / Heal Block when the move is CHOSEN, and has no Truant or Uproar):
#   CHECK_STATUS_START       Destiny Bond / Grudge end (the caller clears them where the action starts)
#   SLEEP        the counter ticks; still asleep = the action is lost, unless the move is Sleep Talk or Snore; asleep and waking = goes on
#   FREEZE       20% thaws (goes on); otherwise stays frozen, unless the move thaws its user (Flame Wheel, Sacred Fire, Flare Blitz)
#   RECHARGING   the flag is used up, the action is lost (UnlockMoveChoice)
#   FLINCH       the flag is used up, the action is lost (Steadfast +1 Speed) (UnlockMoveChoice, ends a Thrash lock: moveFailFlags.flinched)
#   CONFUSION    counter tick + 50% self-hit (see confusion_check)
#   PARALYSIS    25% fully paralyzed (not with Magic Guard) (UnlockMoveChoice, ends a Thrash lock)
#   ATTRACT      50% immobilized by love (UnlockMoveChoice, ends a Thrash lock)
#   SELF_THAW    a frozen mon whose move thaws its user is defrosted by it
# The first stage that loses the action ends the chain, so the later stages neither roll nor tick. BattleControllerPlayer_SetupNextTurn (turn
# end) clears every flinch flag, whether or not it was used.
_THAW_USER_EFFECTS = frozenset(("BATTLE_EFFECT_THAW_AND_BURN_HIT", "BATTLE_EFFECT_RECOIL_BURN_HIT"))      # Flame Wheel / Sacred Fire, Flare Blitz


def unlock_move_choice(mon):
    """Battler_UnlockMoveChoice, run by subscript_recharging / _flinched / _fully_paralyzed / _immobilized_by_love /
    _hurt_self_in_confusion: whatever locks the mon into a move it started - a two-turn move's hiding or charging, Bide, the Rollout
    counter - ends. (The choice-item lock and the Fury Cutter count are not modelled.)"""
    mon["vanished"] = None
    mon["charging_solar_beam"] = None
    mon["bide_turns"] = 0
    mon["bide_damage"] = 0
    mon["rollout_turns"] = 0
    mon["rollout_move"] = None


def _action_lost(mon):
    """The stages that set a moveFailFlags bit (flinched / paralyzed / infatuated): BattleContext_MoveFailed then cancels a Thrash lock
    (the mon condition loop clears VOLATILE_CONDITION_THRASH), on top of UnlockMoveChoice."""
    unlock_move_choice(mon)
    mon["rampage_turns"] = 0
    mon["rampage_move"] = None


def _cure_status_berry(mon, log):
    cured_item = try_eat_status_cure_berry(mon)
    if cured_item:
        ai_reveal_item(mon)
        log.append(f"    {mon['species_display']}'s {cured_item} cured its status!")
    return cured_item


def check_status_disruption(mon, rng, log, chosen_move=None, bstate=None):
    """BattleControllerPlayer_CheckStatusDisruption for the mon whose action has just come up (both engines call it right before the
    move would be executed). `chosen_move` is the move the AI picked at the top of the turn (None for a recharging mon, which picked
    nothing): Sleep Talk / Snore get through the sleep stage and a thawing move through the freeze stage. `bstate` reaches the
    confusion self-hit's damage calculation (Slow Start, Plus / Minus...). Returns True when the mon
    goes on to use its move, False when the action is lost; the flags and counters are updated as the C does.

    A status-cure berry is eaten first: retail eats it right after the move that inflicted the status (AFTER_MOVE_EFFECT_HELD_ITEM_STATUS),
    i.e. before anything below could matter - which for a status landed mid-turn is exactly this moment."""
    _cure_status_berry(mon, log)
    name = mon["species_display"]
    move_effect = _real_effect(chosen_move) if chosen_move else None

    if mon.get("status") == "SLEEP":
        turns_asleep = mon.get("sleep_turns", 0)
        if mon.get("rest_sleep"):
            # Rest's sleep duration is fixed, not the usual random
            # chance: exactly 2 turns unable to act (1 for an Early Bird
            # user, since it "spends one fewer turn asleep") - guaranteed
            # to wake up the turn after, never a probability roll.
            required_turns = 1 if has_ability(mon, "EARLY_BIRD") else 2
            woke_up = turns_asleep >= required_turns
        else:
            wake_chance = 0.66 if has_ability(mon, "EARLY_BIRD") else 0.33
            woke_up = turns_asleep >= 1 and rng.random() < wake_chance
        if woke_up:
            mon["status"] = "NONE"
            mon["sleep_turns"] = 0
            mon["rest_sleep"] = False
            mon["nightmare"] = False  # Nightmare only bites while actually asleep
            log.append(f"    {name} woke up!")
        else:
            mon["sleep_turns"] = turns_asleep + 1
            log.append(f"    {name} is fast asleep.")
            # `moveCur != MOVE_SNORE && moveTemp != MOVE_SLEEP_TALK`: only these two moves are used while asleep (the turn still
            # counts toward the wake-up threshold above like any other asleep turn); each fails unless the user is asleep.
            if chosen_move not in ("MOVE_SLEEP_TALK", "MOVE_SNORE"):
                return False

    if mon.get("status") == "FREEZE":
        if rng.random() < 0.20:
            mon["status"] = "NONE"
            log.append(f"    {name} thawed out!")
        elif move_effect not in _THAW_USER_EFFECTS:
            log.append(f"    {name} is frozen solid!")
            return False

    if mon.get("must_recharge"):
        mon["must_recharge"] = False
        log.append(f"    {name} must recharge!")
        unlock_move_choice(mon)
        return False

    if mon.get("flinched"):
        mon["flinched"] = False
        log.append(f"    {name} flinched and couldn't move!")
        if has_ability(mon, "STEADFAST"):                       # subscript_flinched
            ai_reveal_ability(mon)
            raise_stage(mon, "spe_stage", 1)
            log.append(f"    {name}'s Steadfast raised its Speed!")
        _action_lost(mon)
        return False

    if mon.get("confused") and not confusion_check(mon, rng, log, bstate):
        return False

    if mon.get("status") in ("PARALYSIS", "PARALYZE") and not has_ability(mon, "MAGIC_GUARD"):
        if rng.random() < 0.25:                                 # RandNext() % 4 == 0
            log.append(f"    {name} is paralyzed! It can't move!")
            _action_lost(mon)
            return False

    if mon.get("attracted"):
        if rng.random() < 0.5:                                  # RandNext() & 1 == 0: subscript_immobilized_by_love
            log.append(f"    {name} is immobilized by love!")
            _action_lost(mon)
            return False

    if mon.get("status") == "FREEZE" and move_effect in _THAW_USER_EFFECTS:     # CHECK_STATUS_STATE_SELF_THAW
        mon["status"] = "NONE"
        log.append(f"    {name} was defrosted by {chosen_move.replace('MOVE_', '').replace('_', ' ').title()}!")
    return True


def process_status_start_turn(combatant, rng, log, bstate=None):
    """The TOP of the turn, before the AI picks anybody's move. Returns (can_pick_command, speed_multiplier).
      * a held status-cure berry is eaten (the AI then sees the cured mon; a status that lands mid-turn is handled by the same berry
        check at the start of check_status_disruption);
      * the speed multiplier: x2 for Chlorophyll in sun / Swift Swim in rain, x0.5 for paralysis;
      * can_pick_command is Battler_CanPickCommand: a recharging mon is locked into its move and the AI is not asked (no rng draws).
    Nothing that stops a mon from ACTING happens here: sleep, freeze, recharge, flinch, confusion, paralysis and attraction are checked
    by check_status_disruption when the mon's action comes up."""
    _cure_status_berry(combatant, log)
    speed_multiplier = 1.0
    if bstate is not None and bstate.get("weather") == "SUN" and has_ability(combatant, "CHLOROPHYLL"):
        speed_multiplier = 2.0
    if bstate is not None and bstate.get("weather") == "RAIN" and has_ability(combatant, "SWIFT_SWIM"):
        speed_multiplier = 2.0
    if combatant.get("status", "NONE") in ("PARALYSIS", "PARALYZE"):
        speed_multiplier *= 0.5
    return not combatant.get("must_recharge"), speed_multiplier


def process_weather_end_turn(combatant, bstate, log):
    """Phase (2) of end-of-turn, split out from process_status_end_turn
    so it can run for both active Pokemon BEFORE delayed moves (3)
    resolve, which in turn need to happen before phases (4)-(6) - see
    process_status_end_turn's own docstring for the full ordering."""
    if combatant["hp"] <= 0:
        return
    if combatant.get("skip_weather_this_turn"):
        # Set on a MID-TURN fainting replacement (see the "-> sends out"
        # call site) - it doesn't take (or benefit from) weather damage
        # the very turn it's switched in, matching the real games'
        # timing where the replacement doesn't hit the field until after
        # this turn's weather-damage phase has already run.
        combatant["skip_weather_this_turn"] = False
        return
    max_hp = combatant.get("max_hp", combatant["hp"])
    weather = weather_now(bstate)
    if not has_ability(combatant, "MAGIC_GUARD"):
        if weather == "SANDSTORM" and not (set(combatant.get("types", [])) & {"TYPE_ROCK", "TYPE_GROUND", "TYPE_STEEL"}) \
                and not has_ability(combatant, "SAND_VEIL") and not has_ability(combatant, "SAND_FORCE") and not has_ability(combatant, "SAND_RUSH"):
            dmg = max(1, max_hp // 16)
            combatant["hp"] -= dmg
            note_weather_damage(bstate, combatant, weather)
            log.append(f"    {combatant['species_display']} is buffeted by the sandstorm! (-{dmg} HP)")
        elif weather == "HAIL" and "TYPE_ICE" not in combatant.get("types", []) and not has_ability(combatant, "ICE_BODY") and not has_ability(combatant, "SNOW_CLOAK"):
            dmg = max(1, max_hp // 16)
            combatant["hp"] -= dmg
            note_weather_damage(bstate, combatant, weather)
            log.append(f"    {combatant['species_display']} is pelted by hail! (-{dmg} HP)")
        if weather == "SUN" and combatant["hp"] > 0:
            if has_ability(combatant, "DRY_SKIN"):
                dmg = max(1, max_hp // 8)
                combatant["hp"] -= dmg
                note_weather_damage(bstate, combatant, weather)
                log.append(f"    {combatant['species_display']}'s Dry Skin is hurt by the sunlight! (-{dmg} HP)")
            elif has_ability(combatant, "SOLAR_POWER"):
                dmg = max(1, max_hp // 8)
                combatant["hp"] -= dmg
                note_weather_damage(bstate, combatant, weather)
                log.append(f"    {combatant['species_display']}'s Solar Power is hurt by the sunlight! (-{dmg} HP)")
    if weather == "HAIL" and has_ability(combatant, "ICE_BODY") and combatant["hp"] > 0 and combatant["hp"] < max_hp:
        heal = max(1, max_hp // 16)
        combatant["hp"] = min(max_hp, combatant["hp"] + heal)
        ai_reveal_ability(combatant)
        log.append(f"    {combatant['species_display']}'s Ice Body restored its HP! (+{heal} HP)")
    if weather == "RAIN" and combatant["hp"] > 0 and combatant["hp"] < max_hp:
        if has_ability(combatant, "DRY_SKIN"):
            heal = max(1, max_hp // 8)
            combatant["hp"] = min(max_hp, combatant["hp"] + heal)
            ai_reveal_ability(combatant)
            log.append(f"    {combatant['species_display']}'s Dry Skin restored its HP! (+{heal} HP)")
        elif has_ability(combatant, "RAIN_DISH"):
            heal = max(1, max_hp // 16)
            combatant["hp"] = min(max_hp, combatant["hp"] + heal)
            ai_reveal_ability(combatant)
            log.append(f"    {combatant['species_display']}'s Rain Dish restored its HP! (+{heal} HP)")


def _slot_key(mon, bstate):
    return bstate["side_of"](mon), bstate["slot_of"](mon)


def delayed_pending(bstate, mon, kind):
    """Is a Future Sight ("fs") aimed at `mon`'s slot, or a Wish ("wish") made from it, still pending?"""
    return bool(bstate.get("delayed", {}).get(_slot_key(mon, bstate), {}).get(kind))


def start_future_sight(actor, target, mv, mv_name, bstate, rng, log):
    """BtlCmd_TryFutureSight: keyed on the TARGET's slot (fails if one is already pending there). The damage is calculated NOW - the
    ordinary damage formula with no crit, no STAB and no type chart, then the 85-100 variance, x1.5 again under Helping Hand - and
    hits whoever occupies that slot two turns later (subject to an accuracy roll at that point)."""
    slot = bstate.setdefault("delayed", {}).setdefault(_slot_key(target, bstate), {})
    if slot.get("fs"):
        return False
    damage = calc_move_damage(actor, target, mv, mv.get("power", 0), mv.get("type", "TYPE_NORMAL"), weather_now(bstate), bstate, 1)
    if damage:
        damage = max(1, damage * (100 - int(rng.random() * 16)) // 100)
    if actor.get("helping_hand"):
        damage = damage * 15 // 10
    slot["fs"] = {"turns_left": 3, "move": mv_name, "mv": mv, "attacker": actor, "damage": damage}
    bstate["sides"][bstate["side_of"](target)]["future_sight"] = True          # SIDE_CONDITION_FUTURE_SIGHT (what the AI reads)
    log.append(f"    {actor['species_display']} foresaw an attack with {mv_name.replace('MOVE_', '').replace('_', ' ').title()}!")
    return True


def start_wish(actor, bstate, log):
    """BtlCmd_TryWish: keyed on the USER's slot; fails if that slot already has a wish coming."""
    slot = bstate.setdefault("delayed", {}).setdefault(_slot_key(actor, bstate), {})
    if slot.get("wish"):
        return False
    slot["wish"] = {"turns_left": 2, "by": actor}
    log.append(f"    {actor['species_display']} made a wish!")
    return True


def resolve_delayed_moves_end_turn(bstate, log, rng):
    """FIELD_COND_CHECK: the delayed hits and wishes of every slot, in battler order. A Future Sight lands on whoever now occupies its
    slot: after an accuracy check, on a Substitute if there is one, otherwise on the HP (and it never checks types). A Wish heals
    half of the OCCUPANT's max HP (not the wisher's). Retail quirks kept: the counter ticks even if the slot's mon has fainted (the
    hit is then lost), and the side's Future Sight flag is only cleared when a hit actually lands."""
    delayed = bstate.get("delayed") or {}
    occupants = bstate["occupants"]()
    for key in (("a", 0), ("b", 0), ("a", 1), ("b", 1)):
        slot = delayed.get(key)
        mon = occupants.get(key)
        if not slot:
            continue
        pending = slot.get("fs")
        if pending:
            pending["turns_left"] -= 1
            if pending["turns_left"] <= 0:
                slot["fs"] = None
                if mon is not None and mon["hp"] > 0:
                    bstate["sides"][key[0]]["future_sight"] = None
                    move_display = pending["move"].replace("MOVE_", "").replace("_", " ").title()
                    log.append(f"    {pending['attacker']['species_display']}'s {move_display} struck {mon['species_display']}!")
                    hit_mv = dict(pending["mv"], always_hit=False)     # the use turn skips the roll; the delayed hit makes it
                    if _accuracy_check_misses(pending["attacker"], mon, hit_mv, weather_now(bstate), rng, bstate=bstate):
                        log.append("    But it failed!")
                    elif mon.get("substitute_hp", 0) > 0:
                        absorbed = min(mon["substitute_hp"], pending["damage"])
                        mon["substitute_hp"] -= absorbed
                        log.append(f"    {mon['species_display']}'s Substitute took {absorbed} damage!")
                    else:
                        mon["hp"] -= pending["damage"]
                        _record_damaging_hit_event(bstate, mon, pending["attacker"])
                        log.append(f"    Dealt {pending['damage']} damage to {mon['species_display']}!")
        wish = slot.get("wish")
        if wish:
            wish["turns_left"] -= 1
            if wish["turns_left"] <= 0:
                slot["wish"] = None
                if mon is not None and mon["hp"] > 0:
                    if mon.get("heal_block_turns", 0):
                        log.append(f"    {mon['species_display']} was prevented from healing!")
                    elif mon["hp"] >= mon.get("max_hp", mon["hp"]):
                        log.append(f"    {mon['species_display']}'s HP is full!")
                    else:
                        heal = max(1, mon["max_hp"] // 2)
                        mon["hp"] = min(mon["max_hp"], mon["hp"] + heal)
                        note_cleric_support(bstate, wish.get("by"), mon)
                        log.append(f"    {mon['species_display']}'s wish came true! (+{heal} HP)")


def process_status_end_turn(combatant, opponent, bstate, log):
    """End-of-turn effects for one Pokemon, in the standard ordering:
    (1) weather expiration is handled separately at the battle-loop
    level, since it's a once-per-turn field event rather than per-mon;
    (2) weather damage/healing (Sandstorm/Hail, Ice Body) - handled by
    process_weather_end_turn, called separately for both Pokemon before
    this function; (3) delayed moves (Future Sight/Doom Desire/Wish) -
    handled by resolve_delayed_moves_end_turn, called once per turn
    between weather and this function; (4) item/ability healing and
    Leech Seed - Leftovers, Ingrain/Aqua Ring, then Leech Seed's drain;
    (5) status residual damage - Poison/Toxic (or Poison Heal's healing
    instead), Burn, Nightmare, Curse, binding-move damage; (6) status/
    field countdowns last - Perish Song's count (and the faint it can
    cause), Yawn turning into sleep, Taunt/Encore wearing off (Torment
    has no turn-based countdown in any generation - it only ends on
    switch-out, so there's nothing to tick down for it here). Form
    changes and emergency switch-outs (Schooling/Shields Down/Zen Mode,
    Emergency Exit/Wimp Out) aren't implemented."""
    if combatant.get("disabled_move"):                      # battle_controller_player.c: the Disable countdown
        if combatant["disabled_move"] not in combatant.get("moves", ()):
            combatant["disabled_turns"] = 0
        if combatant.get("disabled_turns", 0):
            combatant["disabled_turns"] -= 1
        else:
            combatant["disabled_move"] = None
            log.append(f"    {combatant['species_display']} is no longer disabled!")
    if combatant.get("magnet_rise_turns", 0) > 0:
        combatant["magnet_rise_turns"] -= 1
    if combatant.get("heal_block_turns", 0) > 0:
        combatant["heal_block_turns"] -= 1
    if combatant.get("lock_on_turns", 0) > 0:               # Lock-On / Mind Reader countdown (battle_controller_player.c)
        combatant["lock_on_turns"] -= 1
        if combatant["lock_on_turns"] <= 0:
            combatant["locked_on_by"] = None
    max_hp = combatant.get("max_hp", combatant["hp"])
    if combatant["hp"] <= 0:
        return

    # --- (4) item/ability healing, then Leech Seed ---
    # USE_ITEM (a berry whose HP threshold is met) comes before Leftovers / Black Sludge, and both come before Leech Seed and poison. Leftovers
    # is a heal - Magic Guard does not stop it - and no item does anything under Klutz or Embargo.
    use_held_item(combatant, log)
    item = combatant.get("item") if item_effects_active(combatant) and not has_ability(combatant, "KLUTZ") else None
    if item == "ITEM_LEFTOVERS" and combatant["hp"] < max_hp:
        healed = max(1, max_hp // 16)
        combatant["hp"] = min(max_hp, combatant["hp"] + healed)
        ai_reveal_item(combatant)
        log.append(f"    {combatant['species_display']} restored a little HP using its Leftovers!")
    if item == "ITEM_BLACK_SLUDGE":
        if "TYPE_POISON" in combatant.get("types", []):
            # The Poison-type healing side is beneficial, so it still
            # applies even with Magic Guard - only the non-Poison-type
            # damage side below counts as "indirect damage" to block.
            if combatant["hp"] < max_hp:
                healed = max(1, max_hp // 16)
                combatant["hp"] = min(max_hp, combatant["hp"] + healed)
                ai_reveal_item(combatant)
                log.append(f"    {combatant['species_display']} restored a little HP using its Black Sludge!")
        elif not has_ability(combatant, "MAGIC_GUARD") and combatant["hp"] > 0:
            dmg = max(1, max_hp // 8)
            combatant["hp"] = max(0, combatant["hp"] - dmg)
            ai_reveal_item(combatant)
            log.append(f"    {combatant['species_display']} is hurt by its Black Sludge! (-{dmg} HP)")
    if (combatant.get("aqua_ring") or combatant.get("ingrain")) and combatant["hp"] > 0 and not combatant.get("heal_block_turns", 0):
        healed = max(1, max_hp // 16)
        combatant["hp"] = min(max_hp, combatant["hp"] + healed)
        log.append(f"    {combatant['species_display']}'s HP was restored. (+{healed} HP)")
    recipient = opponent
    seed_slot = combatant.get("leech_seed_slot")
    if seed_slot is not None and bstate.get("occupants"):
        recipient = bstate["occupants"]().get(seed_slot)          # MOVE_EFFECT_LEECH_SEED_RECIPIENT is a battler SLOT: whoever stands there now
    if (not has_ability(combatant, "MAGIC_GUARD") and combatant.get("leech_seeded") and combatant["hp"] > 0
            and recipient is not None and recipient["hp"] > 0):
        # BattleController_CheckMonCondition (MON_COND_CHECK_STATE_LEECH_SEED) only runs the effect while the mon it feeds is still
        # standing (battleMons[recipient].curHP): with the seeder fainted, nothing happens at all - no drain and, above all, no "heal"
        # that would hand a fainted mon hit points back and leave it fighting on. Then subscript_leech_seed_effect: the same amount
        # (Big Root scales it) goes to the recipient, or - when the seeded mon has Liquid Ooze - is taken from it instead (Magic Guard
        # on the recipient blocks that damage); Heal Block on the recipient only stops the healing.
        drained = max(1, max_hp // 8)
        combatant["hp"] -= drained
        amount = drained
        leech_effect, leech_param = _held_effect(recipient)
        if leech_effect == "HOLD_EFFECT_LEECH_BOOST":
            amount = max(1, amount * (100 + leech_param) // 100)
        log.append(f"    {combatant['species_display']}'s health is sapped by Leech Seed! (-{drained} HP)")
        if has_ability(combatant, "LIQUID_OOZE"):
            ai_reveal_ability(combatant)
            if not has_ability(recipient, "MAGIC_GUARD"):
                recipient["hp"] -= amount
                note_ko_cause(recipient, KO_CAUSE_RETALIATION)
            log.append(f"    {recipient['species_display']} sucked up the liquid ooze!")
        elif not recipient.get("heal_block_turns", 0):
            opp_max = recipient.get("max_hp", recipient["hp"])
            recipient["hp"] = min(opp_max, recipient["hp"] + amount)
    if combatant["hp"] <= 0:
        return

    # --- (5) status residual damage ---
    # Magic Guard is checked INSIDE the damage scripts (subscript_poison_damage / _burn_damage / _nightmare_effect / _curse_damage /
    # _bind_effect), never in the controller states that decide what happens: the Toxic counter and the Bind counter advance for a Magic
    # Guard holder too, and a nightmare that has nothing left to bite ends whatever the ability.
    status = combatant.get("status", "NONE")
    if status == "TOXIC":
        combatant["toxic_turns"] = min(15, combatant.get("toxic_turns", 0) + 1)       # MON_COND_CHECK_STATE_TOXIC: capped at the 4-bit counter
    if combatant.get("nightmare") and combatant["hp"] > 0 and combatant.get("status") != "SLEEP":
        combatant["nightmare"] = False
    if not has_ability(combatant, "MAGIC_GUARD"):
        if status == "POISON":
            if has_ability(combatant, "POISON_HEAL"):
                if combatant["hp"] < max_hp:                          # the script does nothing at full HP
                    healed = max(1, max_hp // 8)
                    combatant["hp"] = min(max_hp, combatant["hp"] + healed)
                    ai_reveal_ability(combatant)
                    log.append(f"    {combatant['species_display']}'s Poison Heal restored its HP! (+{healed} HP)")
            else:
                dmg = max(1, max_hp // 8)
                combatant["hp"] -= dmg
                log.append(f"    {combatant['species_display']} is hurt by poison! (-{dmg} HP)")
        elif status == "TOXIC":
            if has_ability(combatant, "POISON_HEAL"):
                if combatant["hp"] < max_hp:
                    healed = max(1, max_hp // 8)
                    combatant["hp"] = min(max_hp, combatant["hp"] + healed)
                    ai_reveal_ability(combatant)
                    log.append(f"    {combatant['species_display']}'s Poison Heal restored its HP! (+{healed} HP)")
            else:
                dmg = max(1, max_hp // 16) * combatant["toxic_turns"]           # Divide(maxHP, 16) FIRST, then x counter
                combatant["hp"] -= dmg
                log.append(f"    {combatant['species_display']} is hurt by poison! (-{dmg} HP)")
        elif status == "BURN":
            dmg = max(1, max_hp // 8)
            combatant["hp"] -= dmg
            log.append(f"    {combatant['species_display']} is hurt by its burn! (-{dmg} HP)")

        if combatant.get("nightmare") and combatant["hp"] > 0:
            if combatant.get("status") == "SLEEP":
                dmg = max(1, max_hp // 4)
                combatant["hp"] -= dmg
                log.append(f"    {combatant['species_display']} is tormented by a nightmare! (-{dmg} HP)")
            else:
                combatant["nightmare"] = False  # no longer asleep - the nightmare has nothing to bite

        if combatant.get("cursed") and combatant["hp"] > 0:
            dmg = max(1, max_hp // 4)
            combatant["hp"] -= dmg
            log.append(f"    {combatant['species_display']} is afflicted by the curse! (-{dmg} HP)")

    if combatant.get("trapped_turns", 0) > 0 and combatant["hp"] > 0:
        # MON_COND_CHECK_STATE_BIND: the counter drops FIRST (Magic Guard or not); while it stays above 0 subscript_bind_effect hurts the
        # mon by 1/16 (the ability only cancels that damage), and the tick that reaches 0 frees it with no damage
        combatant["trapped_turns"] -= 1
        if combatant["trapped_turns"] > 0:
            if not has_ability(combatant, "MAGIC_GUARD"):
                dmg = max(1, max_hp // 16)
                combatant["hp"] -= dmg
                trapper = combatant.get("trapped_by_species", "something")
                log.append(f"    {combatant['species_display']} is hurt by {trapper}'s binding move! (-{dmg} HP)")
        else:
            log.append(f"    {combatant['species_display']} was freed!")

    if (opponent is not None and has_ability(combatant, "SYNCHRONIZE") and status in ("BURN", "POISON", "PARALYZE")
            and opponent.get("status", "NONE") == "NONE" and opponent["hp"] > 0):
        opponent["status"] = status
        note_contribution(bstate, opponent, combatant, "status")
        ai_reveal_ability(combatant)

    if has_ability(combatant, "SHED_SKIN") and status != "NONE" and rng_global.random() < 0.33:
        ai_reveal_ability(combatant)
        log.append(f"    {combatant['species_display']}'s Shed Skin cured its {status.title()}!")
        combatant["status"] = "NONE"

    if combatant["hp"] <= 0:
        return

    # --- (6) status/field countdowns (last) ---
    # Perish Song ticks down (and can faint the Pokemon) regardless of
    # Magic Guard - unlike poison/burn/sandstorm etc. this isn't
    # "damage" in the game's own sense, it's a separate faint-on-zero
    # mechanic.
    if combatant.get("perish_song", 0) > 0:
        combatant["perish_song"] -= 1
        if combatant["perish_song"] <= 0:
            combatant["hp"] = 0
            log.append(f"    {combatant['species_display']}'s perish count hit zero!")
            return

    # Yawn: the drowsiness itself isn't damage either, so this also
    # ignores Magic Guard. Falling asleep still respects the normal
    # immunities (already has a status, or an ability like Insomnia/
    # Vital Spirit) at the moment the countdown actually hits 0 - not
    # just at the moment Yawn was originally used.
    if combatant.get("yawn_turn", 0) > 0:
        combatant["yawn_turn"] -= 1
        if combatant["yawn_turn"] <= 0:
            if combatant.get("status", "NONE") == "NONE" and not status_blocked_by_ability("SLEEP", combatant):
                combatant["status"] = "SLEEP"
                combatant["sleep_turns"] = 0
                note_contribution(bstate, combatant, combatant.get("yawn_source"), "status")
                log.append(f"    {combatant['species_display']} fell asleep from drowsiness!")

    if combatant.get("taunt_turns", 0) > 0:
        combatant["taunt_turns"] -= 1
        if combatant["taunt_turns"] <= 0:
            log.append(f"    {combatant['species_display']}'s taunt wore off!")

    if combatant.get("embargo_turns", 0) > 0:
        combatant["embargo_turns"] -= 1
        if combatant["embargo_turns"] <= 0:
            log.append(f"    {combatant['species_display']}'s Embargo wore off!")

    if combatant.get("encore_turns", 0) > 0:
        combatant["encore_turns"] -= 1
        if combatant["encore_turns"] <= 0:
            combatant["encore_move"] = None
            log.append(f"    {combatant['species_display']}'s encore ended!")

    detrimental_held_item(combatant, bstate, log)              # Toxic Orb / Flame Orb: the last state of the battler's end of turn


rng_global = random.Random()  # used only by ability procs that don't have a battle rng handy (Shed Skin, Future Sight's hit)


def _seed_rng_global(seed, trainer_a, trainer_b, game_num):
    """Makes a seeded battle reproducible: the procs above draw from rng_global, so it is re-seeded per battle from the same
    inputs as the battle rng (without consuming any of that rng's draws). An unseeded battle keeps a free-running stream."""
    if seed is not None:
        rng_global.seed(f"{seed}|{trainer_a}|{trainer_b}|{game_num}")


def process_natural_cure(mon, log=None):
    if has_ability(mon, "NATURAL_CURE") and mon.get("status", "NONE") != "NONE":
        if log is not None and mon.get("hp", 0) > 0:
            ai_reveal_ability(mon)
            log.append(f"    {mon['species_display']}'s Natural Cure healed its {mon['status'].title()}!")
        mon["status"] = "NONE"
        mon["toxic_turns"] = 0


def process_end_of_turn_abilities(mon):
    if has_ability(mon, "SPEED_BOOST"):
        mon["spe_stage"] = min(6, mon.get("spe_stage", 0) + 1)


# Status-specific "_RESTORE" cure berries - confirmed Cheri
# (HOLD_EFFECT_PRZ_RESTORE -> paralysis) directly from real data; the
# other four follow the same naming pattern by analogy (Chesto/sleep,
# Pecha/poison, Rawst/burn, Aspear/freeze) and haven't been individually
# confirmed, but the pattern is consistent enough across a real,
# confirmed example to trust it. Each entry maps to a TUPLE of matching
# internal status values, since Pecha-style poison cures need to match
# both "POISON" and "TOXIC" (badly poisoned) - two distinct internal
# status values for what's a single "poisoned" status family in the
# real games.
STATUS_RESTORE_BERRY_EFFECTS = {
    "HOLD_EFFECT_PRZ_RESTORE": ("PARALYSIS",), "HOLD_EFFECT_SLP_RESTORE": ("SLEEP",),
    "HOLD_EFFECT_PSN_RESTORE": ("POISON", "TOXIC"), "HOLD_EFFECT_BRN_RESTORE": ("BURN",),
    "HOLD_EFFECT_FRZ_RESTORE": ("FREEZE",),
}
# Pinch stat-boost berries (Liechi/Ganlon/Salac/Petaya/Apicot-style) -
# confirmed Salac (HOLD_EFFECT_PINCH_SPEED_UP -> spe_stage) directly;
# the other four follow the same naming pattern by analogy and haven't
# been individually confirmed.
PINCH_STAT_BERRY_EFFECTS = {
    "HOLD_EFFECT_PINCH_ATK_UP": "atk_stage", "HOLD_EFFECT_PINCH_DEF_UP": "def_stage",
    "HOLD_EFFECT_PINCH_SPATK_UP": "spa_stage", "HOLD_EFFECT_PINCH_SPDEF_UP": "spd_stage",
    "HOLD_EFFECT_PINCH_SPEED_UP": "spe_stage",
}


def berry_hp_trigger_fraction(item_name):
    """Returns the HP fraction (of max HP) at or below which item_name's
    berry effect should naturally trigger, or None if it isn't an
    HP-threshold-triggered berry at all (status-cure berries trigger on
    the status itself, not on HP). HP-recovery berries (Oran/Sitrus-
    style) trigger at 50%; pinch stat-boost berries (Salac-style)
    trigger at 1/effect_param of max HP - confirmed from Salac's own
    data (effectParam: 4 -> 25%), matching the well-documented real
    threshold for this whole berry family."""
    info = get_item_info(item_name)
    hold_effect = info.get("hold_effect")
    if hold_effect in ("HOLD_EFFECT_HP_PCT_RESTORE", "HOLD_EFFECT_HP_RESTORE") or item_name in (
            "ITEM_ORAN_BERRY", "ITEM_SITRUS_BERRY"):
        return 0.5
    if hold_effect in PINCH_STAT_BERRY_EFFECTS:
        param = info.get("effect_param", 0)
        return (1.0 / param) if param > 0 else 0.25
    return None


def eat_berry(eater, holder=None, log=None):
    """Applies the effect of holder's currently held berry to eater, and
    clears holder's item - used for natural HP-threshold/status-cure
    self-consumption (holder defaults to eater) as well as Pluck's
    forced consumption of the TARGET's berry, where the effect lands on
    the attacker instead of the berry's own holder. Returns a display
    name for logging, or None if there was no berry or its hold effect
    isn't one of the ones recognized below.

    Recognized hold effects: HOLD_EFFECT_HP_RESTORE/HP_PCT_RESTORE (Oran/
    Sitrus-style flat or percent HP restore), HOLD_EFFECT_STATUS_RESTORE
    (Lum-style - cures any status AND confusion), the per-status
    "_RESTORE" cure berries in STATUS_RESTORE_BERRY_EFFECTS (Cheri-
    style), and the PINCH_*_UP stat-boost berries in
    PINCH_STAT_BERRY_EFFECTS (Salac-style - boosts the stat by 1 stage).
    Eating one of these clears the OTHER kind of pending trigger too
    (e.g. eating a status-cure berry also can't leave an HP-threshold
    berry half-consumed), since a mon only ever holds one item at a
    time."""
    if holder is None:
        holder = eater
    item = holder.get("item")
    if not item or not item_effects_active(holder):
        return None
    info = get_item_info(item)
    if not info.get("is_berry"):
        return None
    hold_effect = info.get("hold_effect")
    max_hp = eater.get("max_hp", eater["hp"])
    acted = False
    if hold_effect == "HOLD_EFFECT_HP_PCT_RESTORE":
        heal = max(1, int(max_hp * info.get("effect_param", 0) / 100.0))
        eater["hp"] = min(max_hp, eater["hp"] + heal)
        acted = True
    elif hold_effect == "HOLD_EFFECT_HP_RESTORE":
        heal = max(1, int(info.get("effect_param", 0)))
        eater["hp"] = min(max_hp, eater["hp"] + heal)
        acted = True
    elif hold_effect == "HOLD_EFFECT_STATUS_RESTORE":
        eater["status"] = "NONE"
        clear_confusion(eater)
        acted = True
    elif hold_effect in STATUS_RESTORE_BERRY_EFFECTS:
        if eater.get("status") in STATUS_RESTORE_BERRY_EFFECTS[hold_effect]:
            eater["status"] = "NONE"
            acted = True
    elif hold_effect in PINCH_STAT_BERRY_EFFECTS:
        stat_key = PINCH_STAT_BERRY_EFFECTS[hold_effect]
        eater[stat_key] = max(-6, min(6, eater.get(stat_key, 0) + 1))
        acted = True
    elif item == "ITEM_ORAN_BERRY":
        # Fallback for when real item data isn't available (e.g. a test
        # environment without the actual item json files) - matches
        # this berry's known real effect directly.
        eater["hp"] = min(max_hp, eater["hp"] + 10)
        acted = True
    elif item == "ITEM_SITRUS_BERRY":
        eater["hp"] = min(max_hp, eater["hp"] + max_hp // 4)
        acted = True
    if not acted:
        return None
    holder["consumed_item"] = holder["item"]             # BattleContext.recycleItem
    holder["item"] = None
    return info.get("name") or item.replace("ITEM_", "").replace("_", " ").title()


def try_eat_status_cure_berry(mon, log=None):
    """Checks mon's currently held berry against its current status/
    confusion and eats it immediately if it matches (Lum cures anything;
    the per-status berries in STATUS_RESTORE_BERRY_EFFECTS only cure
    their own matching status) - called at the top of every turn from
    process_status_start_turn (before the AI looks at the mon) and again
    from check_status_disruption, right before status effects that would
    otherwise prevent movement are checked, so the cure lands before it
    could matter this turn even for a status that landed mid-turn.
    Returns a display name for logging, or None if nothing happened."""
    item = mon.get("item")
    if not item or has_ability(mon, "KLUTZ"):
        return None
    info = get_item_info(item)
    if not info.get("is_berry"):
        return None
    hold_effect = info.get("hold_effect")
    has_curable_status = mon.get("status", "NONE") != "NONE" or mon.get("confused")
    if hold_effect == "HOLD_EFFECT_STATUS_RESTORE" and has_curable_status:
        return eat_berry(mon)
    if hold_effect in STATUS_RESTORE_BERRY_EFFECTS and mon.get("status") in STATUS_RESTORE_BERRY_EFFECTS[hold_effect]:
        return eat_berry(mon)
    return None


def process_item_effects(mon):
    """Checks HP-threshold berries (Sitrus/Salac-style) right after the
    mon takes damage from an attack, so they trigger immediately rather
    than waiting for end of turn - this matches how these berries
    actually work (mid-battle, the instant HP crosses the threshold).
    Leftovers is NOT checked here - it's a true end-of-turn-only effect,
    handled in process_status_end_turn instead."""
    item = mon.get("item")
    hp = mon["hp"]
    max_hp = mon.get("max_hp", hp)
    if hp <= 0 or has_ability(mon, "KLUTZ"):
        return None  # a fainted Pokemon never procs a held item, and Klutz switches the item's effect off
    if item:
        threshold = berry_hp_trigger_fraction(item)
        if threshold is not None and threshold < 0.5 and has_ability(mon, "GLUTTONY"):
            threshold = min(0.5, threshold * 2)                  # the pinch berries eat at 1/2 instead of 1/4
        if threshold is not None and hp <= max_hp * threshold:
            result = eat_berry(mon)
            if result:
                return result
    return None


def use_held_item(mon, log):
    """BattleSystem_TriggerHeldItem for one battler: a berry whose HP threshold is met is eaten now. Retail calls it after EVERY move (the
    attacker, then the defender - hit or not) and once per battler in the end-of-turn USE_ITEM state, which is BEFORE Leftovers, Leech
    Seed and poison: a mon that a residual effect drops below the threshold eats at the next opportunity, not in the same turn."""
    eaten = process_item_effects(mon)
    if eaten:
        log.append(f"    {mon['species_display']} consumed/used its {eaten}!")


def detrimental_held_item(mon, bstate, log):
    """BattleSystem_TriggerDetrimentalHeldItem, the LAST per-battler end-of-turn state: a Toxic Orb badly poisons and a Flame Orb burns its
    holder, so the damage starts at the NEXT end of turn. The HELD_ITEM path of subscript_badly_poison / subscript_burn is stopped by an
    existing status, Safeguard, the holder's own Immunity / Water Veil, Leaf Guard in harsh sunlight, and the Poison / Steel types (Fire for
    the burn). Magic Guard does not matter (it only stops the damage later)."""
    if mon["hp"] <= 0:
        return
    effect, _ = _held_effect(mon)
    if effect not in ("HOLD_EFFECT_PSN_USER", "HOLD_EFFECT_BRN_USER"):
        return
    poison = effect == "HOLD_EFFECT_PSN_USER"
    if mon.get("status", "NONE") != "NONE" or mon.get("safeguard", 0) > 0:
        return
    if has_ability(mon, "LEAF_GUARD") and weather_now(bstate) == "SUN":
        return
    kind = "TOXIC" if poison else "BURN"
    if has_ability(mon, "IMMUNITY" if poison else "WATER_VEIL") or status_blocked_by_type(kind, mon):
        return
    mon["status"] = kind
    mon["toxic_turns"] = 0
    ai_reveal_item(mon)
    log.append(f"    {mon['species_display']} was {'badly poisoned' if poison else 'burned'} by its {'Toxic' if poison else 'Flame'} Orb!")


# ---- switch-in abilities (BattleSystem_CheckSwitchInAbilities: Trace, weather, Intimidate, Download) -----------------------
_TRACE_BLOCKED = ("FORECAST", "TRACE", "MULTITYPE")


def _intimidate_lands(target):
    """subscript_intimidate: skips a fainted or Substitute-protected foe; the stat drop is then blocked by Hyper Cutter / Clear Body /
    White Smoke (the AbilityBlocksStatReduction check)."""
    return target is not None and target["hp"] > 0 and not target.get("substitute_hp", 0) \
        and not any(has_ability(target, a) for a in ("HYPER_CUTTER", "CLEAR_BODY", "WHITE_SMOKE"))


def raise_stage(mon, key, amount):
    """One stat-stage change with Simple applied (clamped to +-6). Returns True if the stage moved."""
    before = mon.get(key, 0)
    mon[key] = max(-6, min(6, before + amount * (2 if has_ability(mon, "SIMPLE") else 1)))
    return mon[key] != before


def try_trace(mon, foes, log):
    """SWITCH_IN_CHECK_STATE_TRACE / ChooseTraceTarget: copy a random eligible foe's ability (reverts on switch-out)."""
    if not has_ability(mon, "TRACE") or mon["hp"] <= 0 or mon.get("item") == "ITEM_GRISEOUS_ORB":
        return
    candidates = [f for f in foes if f is not None and f["hp"] > 0 and (f.get("ability") or "NONE").upper() not in _TRACE_BLOCKED]
    if not candidates:
        return
    target = candidates[0] if len(candidates) == 1 else candidates[1 if rng_global.random() < 0.5 else 0]
    mon.setdefault("_orig_ability", mon.get("ability"))
    mon["ability"] = target["ability"]
    ai_reveal_ability(mon)
    ai_reveal_ability(target)
    log.append(f"    {mon['species_display']} traced {target['species_display']}'s {ability_of(target).replace('_', ' ').title()}!")


def try_download(mon, foes, log):
    """SWITCH_IN_CHECK_STATE_DOWNLOAD: +1 Sp. Atk if the foes' summed (staged) Defense is at least their Sp. Def, otherwise +1 Attack;
    foes behind a Substitute do not count."""
    if not has_ability(mon, "DOWNLOAD") or mon["hp"] <= 0:
        return
    sum_def = sum_spd = 0
    for f in foes:
        if f is not None and f["hp"] > 0 and not f.get("substitute_hp", 0):
            sum_def += _staged_stat(f.get("def", 0), f.get("def_stage", 0))
            sum_spd += _staged_stat(f.get("spd", 0), f.get("spd_stage", 0))
    if sum_def + sum_spd == 0:
        return
    key = "spa_stage" if sum_def >= sum_spd else "atk_stage"
    ai_reveal_ability(mon)
    raise_stage(mon, key, 1)
    log.append(f"    {mon['species_display']}'s Download raised its {'Sp. Atk' if key == 'spa_stage' else 'Attack'}!")


def apply_entry_abilities(t1, t2, bstate, log):
    apply_entry_hazards(t1, bstate, "a")            # the mons are rebuilt from party data BEFORE their abilities fire
    apply_entry_hazards(t2, bstate, "b")
    try_trace(t1, [t2], log)
    try_trace(t2, [t1], log)
    weather = bstate.get("weather", "NONE")
    weather_setter = None
    for attacker, defender in [(t1, t2), (t2, t1)]:
        ab = ability_of(attacker)
        if ab == "INTIMIDATE" and _intimidate_lands(defender):
            before = defender.get("atk_stage", 0)
            defender["atk_stage"] = max(-6, before - 1)
            ai_reveal_ability(attacker)
            log.append(f"    {attacker['species_display']}'s Intimidate lowered {defender['species_display']}'s ATK!")
            if defender["atk_stage"] != before:
                note_debuff_source(bstate, defender, "atk", attacker, before - defender["atk_stage"])
        elif ab == "PRESSURE":
            ai_reveal_ability(attacker)
            log.append(f"    {attacker['species_display']} is exerting its Pressure!")
        elif ab == "DROUGHT":
            weather, weather_setter = "SUN", attacker
        elif ab == "DRIZZLE":
            weather, weather_setter = "RAIN", attacker
        elif ab == "SAND_STREAM":
            weather, weather_setter = "SANDSTORM", attacker
        elif ab == "SNOW_WARNING":
            weather, weather_setter = "HAIL", attacker
    bstate["weather"] = weather
    if weather_setter is not None:
        # Ability-triggered weather is permanent in Gen4, unlike the
        # 5-turn weather a MOVE like Rain Dance/Sandstorm sets.
        bstate["weather_turns"] = PERMANENT_WEATHER_TURNS
        weather_msg = {"SUN": "The sunlight turned harsh!", "RAIN": "It started to rain!",
                        "SANDSTORM": "A sandstorm kicked up!", "HAIL": "It started to hail!"}[weather]
        ai_reveal_ability(weather_setter)
        note_weather_set(bstate, weather, weather_setter)
        log.append(f"    {weather_setter['species_display']}'s {ability_of(weather_setter).replace('_', ' ').title()} - {weather_msg}")
    elif weather != "NONE":
        bstate["weather_turns"] = 5
    try_download(t1, [t2], log)
    try_download(t2, [t1], log)


def revert_transform(mon):
    """Reverts a Transformed Pokemon back to its original species, types,
    ability, stats, stat stages, and moves - called at the same points
    as revert_mimicked_move (switch-out, faint, and implicitly at the
    start of every fresh battle). A no-op if this mon hasn't
    Transformed. HP and level are never touched here since Transform
    never changes them in the first place."""
    orig = mon.get("pre_transform")
    if orig:
        mon["species"] = orig["species"]
        mon["species_display"] = orig["species_display"]
        mon["type1"] = orig["type1"]
        mon["type2"] = orig["type2"]
        mon["types"] = orig["types"]
        mon["ability"] = orig["ability"]
        mon["atk"] = orig["atk"]
        mon["def"] = orig["def"]
        mon["spa"] = orig["spa"]
        mon["spd"] = orig["spd"]
        mon["spe"] = orig["spe"]
        mon["atk_stage"] = orig["atk_stage"]
        mon["def_stage"] = orig["def_stage"]
        mon["spa_stage"] = orig["spa_stage"]
        mon["spd_stage"] = orig["spd_stage"]
        mon["spe_stage"] = orig["spe_stage"]
        mon["acc_stage"] = orig["acc_stage"]
        mon["eva_stage"] = orig["eva_stage"]
        mon["moves"] = orig["moves"]
        mon["move_pp"] = orig["move_pp"]
        mon["pre_transform"] = None
        mon["transformed"] = False


def revert_mimicked_move(mon):
    """Reverts a Mimic-copied move back to MOVE_MIMIC itself - called
    whenever the user faints, is switched out, or (implicitly, since
    every battle starts from a fresh deep copy of the party) the battle
    ends. A no-op if Mimic hasn't copied anything."""
    copied = mon.get("mimic_active_move")
    if copied:
        moves = mon.get("moves", [])
        if copied in moves:
            moves[moves.index(copied)] = "MOVE_MIMIC"
        mon["mimic_active_move"] = None


# ---- BattleSystem_InitBattleMon / UpdateAfterSwitch: what a mon carries onto the field --------------------------------
_STAGE_KEYS = ("atk_stage", "def_stage", "spa_stage", "spd_stage", "spe_stage", "acc_stage", "eva_stage")
_FRESH_ENTRY_STATE = {
    "substitute_hp": 0, "focus_energy": False, "mean_look": None, "confused": False, "confuse_turns": 0, "cursed": False,
    "leech_seeded": False, "leech_seed_slot": None, "ingrain": False, "aqua_ring": False, "mud_sport": False, "water_sport": False, "power_trick": False,
    "ability_suppressed": False, "heal_block_turns": 0, "magnet_rise_turns": 0, "foresight": False, "miracle_eye": False,
    "flinched": False, "protected": False, "charged": False, "defense_curled": False, "attracted": False,
    "protect_used_last": False, "protect_chain": 0, "helping_hand": False, "last_move_used": None,
    "disabled_move": None, "disabled_turns": 0, "destiny_bond": False, "move_copied": None, "me_first": False,
}
# what Baton Pass keeps (VOLATILE_CONDITION_BATON_PASSED / MOVE_EFFECT_BATON_PASSED / the moveEffectsData copies)
_BATON_PASSED_FIELDS = _STAGE_KEYS + (
    "substitute_hp", "focus_energy", "mean_look", "confused", "confuse_turns", "cursed", "leech_seeded", "leech_seed_slot", "perish_song", "ingrain",
    "aqua_ring", "mud_sport", "water_sport", "power_trick", "ability_suppressed", "embargo_turns", "heal_block_turns",
    "magnet_rise_turns")


def reset_on_switch_in(mon):
    """A mon entering the field is rebuilt from its party data: stat stages, volatile conditions and move effects are gone, and
    Worry Seed / Role Play / Skill Swap ability changes revert. (A Baton Pass re-applies its kept fields afterwards.)"""
    if "_orig_ability" in mon:
        mon["ability"] = mon.pop("_orig_ability")
    if "_orig_types" in mon:                                # Conversion
        mon["type1"], mon["type2"], mon["types"] = mon.pop("_orig_types")
    if mon.get("power_trick"):
        mon["atk"], mon["def"] = mon.get("def"), mon.get("atk")
    for key in _STAGE_KEYS:
        mon[key] = 0
    mon.update(_FRESH_ENTRY_STATE)
    mon["supporters"] = {}                                  # a healing teammate's credit lasts only while the healed mon stays out
    mon["debuff_source"] = {}                               # stat stages just reset to 0, so any prior attribution is now stale
    mon["baton_pass_from"] = None                            # likewise a Baton Pass's credit - see note_baton_pass_support


def baton_state(mon):
    """The fields a Baton Pass hands to the replacement (captured before the passer's own switch-out reset)."""
    return {k: mon[k] for k in _BATON_PASSED_FIELDS if k in mon}


def apply_baton_state(new_mon, passed, old_mon, bstate):
    """Give the replacement the passed fields, and let Mean Look / Lock-On links that pointed at the passer follow the slot."""
    new_mon.update(passed)
    getter = (bstate or {}).get("all_actives")
    for m in (getter() if getter else ()):
        if m is None or m is new_mon:
            continue
        if m.get("mean_look") == id(old_mon):
            m["mean_look"] = id(new_mon)
        if m.get("locked_on_by") == id(old_mon) and m.get("lock_on_turns", 0) > 0:
            m["locked_on_by"], m["lock_on_turns"] = id(new_mon), 2         # the timer is refreshed by a Baton Pass


def _apply_entry_hazards(mon, bstate, side_key):
    side = bstate["sides"][side_key]
    mon["acted_since_switch_in"] = False
    mon["entered_turn"] = bstate.get("turn", 1)     # LoadBattlerTurnCount (Expert_ForceSwitch)
    mon["move_hit"] = None                          # moveHit / moveHitBattler are wiped when a mon enters
    mon["move_hit_slot"] = None
    mon["ai_known_ability"] = None                  # BattleAI_ClearKnownAbility / ClearKnownItem on entry
    mon["ai_known_item"] = None
    mon["can_unburden"] = bool(mon.get("item"))     # BattleSystem_InitBattleMon: canUnburden
    mon["locked_on_by"] = None                      # Lock-On / Mind Reader end when either mon leaves
    mon["lock_on_turns"] = 0
    reset_on_switch_in(mon)
    if mon["hp"] <= 0:
        return
    if has_ability(mon, "MAGIC_GUARD"):
        return          # subscript_hazards_check jumps straight to its end: no Toxic Spikes (neither poisoning nor absorbing), no Spikes, no rocks
    # the script's own order: Toxic Spikes, then Spikes (both only for a grounded mon), then Stealth Rock (everybody)
    if _hazard_grounded(mon, bstate):
        tlayers = side.get("toxic_spikes", 0)
        if tlayers:
            if "TYPE_POISON" in mon.get("types", []):
                side["toxic_spikes"] = 0  # absorbed
                side.get("hazard_setters", {}).pop("toxic_spikes", None)
            elif "TYPE_STEEL" not in mon.get("types", []) and can_inflict_status("TOXIC" if tlayers >= 2 else "POISON", mon, mon):
                mon["status"] = "TOXIC" if tlayers >= 2 else "POISON"
                note_hazard_damage(bstate, mon, side_key, "toxic_spikes")
        layers = side.get("spikes", 0)
        if layers and mon["hp"] > 0:
            mon["hp"] -= max(1, mon["max_hp"] // ((5 - min(3, layers)) * 2))        # BtlCmd_CheckSpikes: 1/8, 1/6, 1/4
            note_hazard_damage(bstate, mon, side_key, "spikes")
    if side.get("stealth_rock") and mon["hp"] > 0:
        eff = type_effectiveness_raw("TYPE_ROCK", mon.get("types", []))              # BtlCmd_CheckStealthRock: 1/2, 1/4, 1/8, 1/16, 1/32
        if eff > 0:
            mon["hp"] -= max(1, mon["max_hp"] // int(round(8 / eff)))
            note_hazard_damage(bstate, mon, side_key, "stealth_rock")


def _hazard_grounded(mon, bstate):
    """The grounded test of subscript_hazards_check: Gravity or an Iron Ball grounds anybody; otherwise Levitate, a Flying type or Magnet
    Rise keeps a mon clear of Toxic Spikes and Spikes (Stealth Rock ignores all of it)."""
    if (bstate or {}).get("gravity", 0) > 0 or _held_effect(mon)[0] == "HOLD_EFFECT_SPEED_DOWN_GROUNDED":
        return True
    return not (has_ability(mon, "LEVITATE") or "TYPE_FLYING" in mon.get("types", []) or mon.get("magnet_rise_turns", 0) > 0)


def apply_entry_hazards(mon, bstate, side_key):
    """A mon entering the field: rebuilt from party data, then hazards, then a pending Healing Wish / Lunar Dance."""
    _apply_entry_hazards(mon, bstate, side_key)
    claim_healing_wish(mon, bstate, side_key)


# ============================================================
# MOVE EFFECT APPLICATION (post-damage)
# ============================================================
def clear_stockpile(mon):
    """Resets a Pokemon's stockpile counter to 0 and undoes the Def/SpDef
    boost it granted (see the STOCKPILE branch in apply_move_effect).
    Used by Swallow, Spit Up, AND by run_battle when a Pokemon switches
    out - Gen4's Stockpile boost is explicitly undone "when it faints or
    is withdrawn", not just when cashed in via Swallow/Spit Up."""
    stacks = mon.get("stockpile", 0)
    if stacks:
        mon["def_stage"] = max(-6, mon.get("def_stage", 0) - stacks)
        mon["spd_stage"] = max(-6, mon.get("spd_stage", 0) - stacks)
        mon["stockpile"] = 0


def check_white_herb(mon, log):
    """White Herb: if ANY of the holder's stat stages are currently
    negative (including accuracy/evasion, not just the 5 combat stats),
    consumes the herb and resets EVERY negative stage back to 0 in one
    go - positive stages are left untouched. This is checked once right
    after a move's full effect resolves, covering every way a stat could
    have just been lowered (the user's own move like Overheat, an
    opponent's move, a triggered ability) from one central point rather
    than needing a check at every individual stat-change call site."""
    if mon.get("item") != "ITEM_WHITE_HERB" or not item_effects_active(mon):
        return
    stat_keys = ("atk_stage", "def_stage", "spa_stage", "spd_stage", "spe_stage", "acc_stage", "eva_stage")
    if any(mon.get(k, 0) < 0 for k in stat_keys):
        for k in stat_keys:
            if mon.get(k, 0) < 0:
                mon[k] = 0
        mon["consumed_item"] = mon["item"]
        mon["item"] = None
        ai_reveal_item(mon)
        log.append(f"    {mon['species_display']}'s White Herb restored its stats!")


# ============================================================
# STATUS-MOVE EFFECTS THE ENGINE USED TO SKIP. Each handler is a port of the move's effect script + subscript
# (res/battle/scripts/effects, subscripts) and the BtlCmd_* it calls; they are keyed on the REAL BATTLE_EFFECT_* and run from
# apply_move_effect. A handler returns False for "But it failed!". The accuracy roll (where the move has one) already happened
# in compute_damage; these run only on a hit.
# ============================================================
_ALL_STAT_KEYS = ("atk_stage", "def_stage", "spa_stage", "spd_stage", "spe_stage", "acc_stage", "eva_stage")


def _substituted(mon):
    return mon.get("substitute_hp", 0) > 0


def _eff_foresight(move, a, d, bstate, rng, log):
    d["foresight"] = True                      # VOLATILE_CONDITION_FORESIGHT: Ghost immunities and evasion gains ignored
    log.append(f"    {a['species_display']} identified {d['species_display']}!")
    return True


def _eff_miracle_eye(move, a, d, bstate, rng, log):
    d["miracle_eye"] = True                    # MOVE_EFFECT_MIRACLE_EYE: Dark loses its Psychic immunity, evasion ignored
    log.append(f"    {a['species_display']} identified {d['species_display']}!")
    return True


def _eff_mean_look(move, a, d, bstate, rng, log):
    if d.get("mean_look") or _substituted(d):
        return False
    d["mean_look"] = id(a)                     # BATTLEMON_MEAN_LOOK_TARGET: lasts while the user stays in
    log.append(f"    {d['species_display']} can no longer escape!")
    return True


def _eff_mud_sport(move, a, d, bstate, rng, log):
    if a.get("mud_sport"):
        return False
    a["mud_sport"] = True                      # any mon on the field with it halves Electric power; ends when the user leaves
    log.append("    Electricity's power was weakened!")
    return True


def _eff_water_sport(move, a, d, bstate, rng, log):
    if a.get("water_sport"):
        return False
    a["water_sport"] = True
    log.append("    Fire's power was weakened!")
    return True


def _eff_magnet_rise(move, a, d, bstate, rng, log):
    if a.get("magnet_rise_turns", 0) or has_ability(a, "LEVITATE") or a.get("ingrain"):
        return False
    a["magnet_rise_turns"] = 5                 # Ground-immune for five turn-ends
    log.append(f"    {a['species_display']} levitated on electromagnetism!")
    return True


def _eff_worry_seed(move, a, d, bstate, rng, log):
    if _substituted(d) or has_ability(d, "TRUANT") or has_ability(d, "MULTITYPE") or d.get("item") == "ITEM_GRISEOUS_ORB":
        return False
    d.setdefault("_orig_ability", d.get("ability"))
    d["ability"] = "INSOMNIA"
    ai_reveal_ability(d)                       # "{0} acquired Insomnia!"
    log.append(f"    {d['species_display']} acquired Insomnia!")
    return True


def _eff_psych_up(move, a, d, bstate, rng, log):
    for key in _ALL_STAT_KEYS:                 # BtlCmd_CopyStatStages: every stage plus the Focus Energy flag
        a[key] = d.get(key, 0)
    if d.get("focus_energy"):
        a["focus_energy"] = True
    log.append(f"    {a['species_display']} copied {d['species_display']}'s stat changes!")
    return True


def _eff_role_play(move, a, d, bstate, rng, log):
    if (has_ability(d, "WONDER_GUARD") or has_ability(d, "MULTITYPE") or has_ability(a, "MULTITYPE") or has_ability(d, "NONE")
            or a.get("item") == "ITEM_GRISEOUS_ORB"):
        return False
    a.setdefault("_orig_ability", a.get("ability"))
    a["ability"] = d["ability"]
    ai_reveal_ability(a)
    log.append(f"    {a['species_display']} copied {d['species_display']}'s {ability_of(d).replace('_', ' ').title()}!")
    return True


def _eff_skill_swap(move, a, d, bstate, rng, log):
    if any(has_ability(m, name) for m in (a, d) for name in ("WONDER_GUARD", "MULTITYPE")) \
            or a.get("item") == "ITEM_GRISEOUS_ORB" or d.get("item") == "ITEM_GRISEOUS_ORB":
        return False
    if has_ability(a, "NONE") and has_ability(d, "NONE"):
        return False
    a.setdefault("_orig_ability", a.get("ability"))
    d.setdefault("_orig_ability", d.get("ability"))
    a["ability"], d["ability"] = d.get("ability"), a.get("ability")
    ai_reveal_ability(a)
    ai_reveal_ability(d)
    log.append(f"    {a['species_display']} swapped abilities with its target!")
    return True


def _eff_refresh(move, a, d, bstate, rng, log):
    if a.get("status", "NONE") not in ("POISON", "TOXIC", "BURN", "PARALYSIS"):      # MON_CONDITION_FACADE_BOOST
        return False
    a["status"] = "NONE"
    log.append(f"    {a['species_display']}'s status returned to normal!")
    return True


def _eff_recycle(move, a, d, bstate, rng, log):
    if a.get("item") or not a.get("consumed_item"):
        return False
    a["item"], a["consumed_item"] = a["consumed_item"], None
    log.append(f"    {a['species_display']} found one {get_item_info(a['item']).get('name', a['item'])}!")
    return True


def _eff_gastro_acid(move, a, d, bstate, rng, log):
    if _substituted(d) or d.get("ability_suppressed") or has_ability(d, "MULTITYPE"):
        return False
    d["ability_suppressed"] = True
    log.append(f"    {d['species_display']}'s ability was suppressed!")
    return True


def _eff_power_trick(move, a, d, bstate, rng, log):
    a["power_trick"] = not a.get("power_trick")            # MOVE_EFFECT_POWER_TRICK toggles, and swaps the two stats
    a["atk"], a["def"] = a.get("def"), a.get("atk")
    log.append(f"    {a['species_display']} switched its Attack and Defense!")
    return True


def _swap_stages(a, d, keys):
    for key in keys:
        a[key], d[key] = d.get(key, 0), a.get(key, 0)


def _eff_heart_swap(move, a, d, bstate, rng, log):
    _swap_stages(a, d, _ALL_STAT_KEYS)
    a["focus_energy"], d["focus_energy"] = bool(d.get("focus_energy")), bool(a.get("focus_energy"))
    log.append(f"    {a['species_display']} switched stat changes with the target!")
    return True


def _eff_power_swap(move, a, d, bstate, rng, log):
    _swap_stages(a, d, ("atk_stage", "spa_stage"))
    log.append(f"    {a['species_display']} switched all changes to its Attack and Sp. Atk with the target!")
    return True


def _eff_guard_swap(move, a, d, bstate, rng, log):
    _swap_stages(a, d, ("def_stage", "spd_stage"))
    log.append(f"    {a['species_display']} switched all changes to its Defense and Sp. Def with the target!")
    return True


def _eff_teeter_dance(move, a, d, bstate, rng, log):
    """SUBSCRIPT_CONFUSE (a DIRECT effect) on every other mon (the move's range is ALL_ADJACENT; doubles calls this once per
    target). Own Tempo (unless the user has Mold Breaker), Safeguard, a Substitute or an existing confusion stop it."""
    if not try_confuse(d, a, rng, log, CONFUSION_DIRECT):
        return False
    note_contribution(bstate, d, a, "status")
    return True


def _eff_psycho_shift(move, a, d, bstate, rng, log):
    """CheckCanShareStatus: needs a status on the user, none on the target, and no Substitute; the target gets the user's status
    (through the normal status subscript, so ability / type immunities still apply) and the user is cured if it landed."""
    if d.get("status", "NONE") != "NONE" or _substituted(d) or a.get("status", "NONE") == "NONE":
        return False
    status = a["status"]
    key = {"SLEEP": "SLEEP", "POISON": "POISON", "BURN": "BURN", "PARALYSIS": "PARALYZE", "TOXIC": "TOXIC", "FREEZE": "FREEZE"}.get(status)
    if key and can_inflict_status(key, a, d, weather_now(bstate)):
        d["status"] = status
        a["status"] = "NONE"
        log.append(f"    {d['species_display']} was afflicted with {status}!")
        note_contribution(bstate, d, a, "status")
        _synchronize(d, a, status, bstate, log)
    return True


_ENGINE_STATUS_EFFECTS = {
    "BATTLE_EFFECT_FORESIGHT": _eff_foresight,
    "BATTLE_EFFECT_IGNORE_EVATION_REMOVE_DARK_IMMUNE": _eff_miracle_eye,
    "BATTLE_EFFECT_PREVENT_ESCAPE": _eff_mean_look,
    "BATTLE_EFFECT_HALVE_ELECTRIC_DAMAGE": _eff_mud_sport,
    "BATTLE_EFFECT_HALVE_FIRE_DAMAGE": _eff_water_sport,
    "BATTLE_EFFECT_GIVE_GROUND_IMMUNITY": _eff_magnet_rise,
    "BATTLE_EFFECT_SET_ABILITY_TO_INSOMNIA": _eff_worry_seed,
    "BATTLE_EFFECT_COPY_STAT_CHANGES": _eff_psych_up,
    "BATTLE_EFFECT_COPY_ABILITY": _eff_role_play,
    "BATTLE_EFFECT_SWITCH_ABILITIES": _eff_skill_swap,
    "BATTLE_EFFECT_HEAL_STATUS": _eff_refresh,
    "BATTLE_EFFECT_RECYCLE": _eff_recycle,
    "BATTLE_EFFECT_SUPRESS_ABILITY": _eff_gastro_acid,
    "BATTLE_EFFECT_SWAP_ATK_DEF": _eff_power_trick,
    "BATTLE_EFFECT_SWAP_STAT_CHANGES": _eff_heart_swap,
    "BATTLE_EFFECT_SWAP_ATK_SP_ATK_STAT_CHANGES": _eff_power_swap,
    "BATTLE_EFFECT_SWAP_DEF_SP_DEF_STAT_CHANGES": _eff_guard_swap,
    "BATTLE_EFFECT_CONFUSE_ALL": _eff_teeter_dance,
    "BATTLE_EFFECT_TRANSFER_STATUS": _eff_psycho_shift,
}


# ---- Batch B: moves whose effects live in the battle loops' state (last move, PP, party, faint order) ---------------------------
def _eff_disable(move, a, d, bstate, rng, log):
    """BtlCmd_TryDisable: the target's LAST used move, if it still knows it with PP left and nothing is disabled yet; 3-6 turns."""
    last = d.get("last_move_used")
    if d.get("disabled_move") or not last or last not in d.get("moves", []) or d.get("move_pp", {}).get(last, 0) <= 0:
        return False
    d["disabled_move"] = last
    d["disabled_turns"] = int(rng.random() * 4) + 3
    log.append(f"    {d['species_display']}'s {last.replace('MOVE_', '').replace('_', ' ').title()} was disabled!")
    return True


def _eff_spite(move, a, d, bstate, rng, log):
    """BtlCmd_TrySpite: the target's last move loses 4 PP (or what is left)."""
    last = d.get("last_move_used")
    if not last or last not in d.get("moves", []) or d.get("move_pp", {}).get(last, 0) <= 0:
        return False
    dec = min(4, d["move_pp"][last])
    d["move_pp"][last] -= dec
    log.append(f"    It reduced the PP of {d['species_display']}'s {last.replace('MOVE_', '').replace('_', ' ').title()} by {dec}!")
    return True


def _eff_destiny_bond(move, a, d, bstate, rng, log):
    a["destiny_bond"] = True                   # lasts until the user's next move attempt (CHECK_STATUS_START clears it)
    log.append(f"    {a['species_display']} is trying to take its foe down with it!")
    return True


def _eff_follow_me(move, a, d, bstate, rng, log):
    side = bstate["side_of"](a)
    bstate.setdefault("follow_me", {})[side] = a          # sideConditions[side].followMe: this turn's single-target moves aim here
    log.append(f"    {a['species_display']} became the center of attention!")
    return True


def _eff_heal_bell(move, a, d, bstate, rng, log):
    """BtlCmd_TryPartyStatusRefresh + the party refresh: every party member's status is cured (Heal Bell skips Soundproof
    holders, Aromatherapy does not), and the on-field user / partner lose Nightmare."""
    party_of = bstate.get("party_of")
    members = party_of(a) if party_of else [a]
    heal_bell = move.get("name") == "MOVE_HEAL_BELL"
    getter = bstate.get("all_actives")
    on_field = {id(m) for m in getter() if m is not None} if getter else set()
    for mon in members:
        if heal_bell and has_ability(mon, "SOUNDPROOF"):
            continue
        if mon.get("status", "NONE") != "NONE" and id(mon) in on_field:
            note_cleric_support(bstate, a, mon)                  # an on-field teammate it actually cured
        mon["status"] = "NONE"
        mon["nightmare"] = False
    log.append("    A bell chimed!" if heal_bell else "    A soothing aroma wafted through the area!")
    return True


def _eff_healing_wish(move, a, d, bstate, rng, log):
    """FAINT_AND_FULL_HEAL_NEXT_MON / FAINT_FULL_RESTORE_NEXT_MON: fails with no replacement; otherwise the user faints and
    whoever comes in next on that side is fully healed (Lunar Dance also restores PP)."""
    party_of = bstate.get("party_of")
    getter = bstate.get("all_actives")
    on_field = {id(m) for m in getter() if m is not None} if getter else {id(a)}
    if not party_of or not any(m["hp"] > 0 and id(m) not in on_field for m in party_of(a)):
        return False
    side = bstate["side_of"](a)
    bstate["sides"][side]["healing_wish"] = "LUNAR_DANCE" if move.get("name") == "MOVE_LUNAR_DANCE" else "HEALING_WISH"
    bstate["sides"][side]["healing_wish_by"] = a
    a["hp"] = 0
    note_ko_cause(a, KO_CAUSE_SUICIDE)
    log.append(f"    {a['species_display']} fainted so its replacement can be healed!")
    return True


def _eff_teleport(move, a, d, bstate, rng, log):
    return False                                # a wild-battle escape: it always fails against a trainer


def _eff_conversion(move, a, d, bstate, rng, log):
    """BtlCmd_TryConversion: become the type of a random OTHER move whose type the user does not already have."""
    if has_ability(a, "MULTITYPE"):
        return False
    moves = [m for m in a.get("moves", []) if m]
    own = set(a.get("types", ()))

    def move_type(name):
        t = get_move_data_by_name(name).get("type", "TYPE_NORMAL")
        if t == "TYPE_MYSTERY":
            return "TYPE_GHOST" if "TYPE_GHOST" in own else "TYPE_NORMAL"
        return t
    candidates = [m for m in moves if m != "MOVE_CONVERSION"]
    if not candidates or all(move_type(m) in own for m in candidates):
        return False
    while True:
        pick = moves[int(rng.random() * len(moves))]
        if pick != "MOVE_CONVERSION" and move_type(pick) not in own:
            break
    t = move_type(pick)
    a.setdefault("_orig_types", (a.get("type1"), a.get("type2"), list(a.get("types", ()))))
    a["type1"], a["type2"], a["types"] = t, None, [t]
    log.append(f"    {a['species_display']} transformed into the {t.replace('TYPE_', '').title()} type!")
    return True


def _eff_belly_drum(move, a, d, bstate, rng, log):
    """subscript_belly_drum: fails when the Attack is already at +6 or the HP is at most half (curHP <= Divide(maxHP, 2)); otherwise the
    Attack goes to +6 and the user pays that half. A direct HP change: Magic Guard has nothing to say about it."""
    cost = max(1, a["max_hp"] // 2)
    if a.get("atk_stage", 0) >= 6 or a["hp"] <= cost:
        return False
    a["hp"] -= cost
    a["atk_stage"] = 6
    log.append(f"    {a['species_display']} cut its own HP and maximized its Attack!")
    return True


_ENGINE_STATUS_EFFECTS.update({
    "BATTLE_EFFECT_MAX_ATK_LOSE_HALF_MAX_HP": _eff_belly_drum,
    "BATTLE_EFFECT_DISABLE": _eff_disable,
    "BATTLE_EFFECT_DECREASE_LAST_MOVE_PP": _eff_spite,
    "BATTLE_EFFECT_KO_MON_THAT_DEFEATED_USER": _eff_destiny_bond,
    "BATTLE_EFFECT_MAKE_GLOBAL_TARGET": _eff_follow_me,
    "BATTLE_EFFECT_CURE_PARTY_STATUS": _eff_heal_bell,
    "BATTLE_EFFECT_FAINT_AND_FULL_HEAL_NEXT_MON": _eff_healing_wish,
    "BATTLE_EFFECT_FAINT_FULL_RESTORE_NEXT_MON": _eff_healing_wish,
    "BATTLE_EFFECT_FLEE_FROM_WILD_BATTLE": _eff_teleport,
    "BATTLE_EFFECT_CONVERSION": _eff_conversion,
})


def claim_healing_wish(mon, bstate, side_key):
    """A mon entering a side with a pending Healing Wish / Lunar Dance is fully restored (status cured; Lunar Dance restores PP)."""
    side = bstate["sides"][side_key]
    kind = side.get("healing_wish")
    if not kind or mon["hp"] <= 0:
        return
    side["healing_wish"] = None
    if mon["hp"] < mon["max_hp"] or mon.get("status", "NONE") != "NONE":
        note_cleric_support(bstate, side.pop("healing_wish_by", None), mon)
    mon["hp"] = mon["max_hp"]
    mon["status"] = "NONE"
    if kind == "LUNAR_DANCE":
        for name in mon.get("moves", []):
            mon["move_pp"][name] = get_move_data_by_name(name).get("pp", mon["move_pp"].get(name, 5))


# ---- moves that call another move --------------------------------------------------------------------------------------
_CALLED_MOVE_EFFECTS = {"BATTLE_EFFECT_CALL_RANDOM_MOVE": "METRONOME", "BATTLE_EFFECT_COPY_MOVE": "MIRROR_MOVE",
                        "BATTLE_EFFECT_USE_RANDOM_ALLY_MOVE": "ASSIST"}
_CANNOT_METRONOME = frozenset((
    "MOVE_METRONOME", "MOVE_STRUGGLE", "MOVE_SKETCH", "MOVE_MIMIC", "MOVE_CHATTER", "MOVE_SLEEP_TALK", "MOVE_ASSIST",
    "MOVE_MIRROR_MOVE", "MOVE_COUNTER", "MOVE_MIRROR_COAT", "MOVE_PROTECT", "MOVE_DETECT", "MOVE_ENDURE", "MOVE_DESTINY_BOND",
    "MOVE_THIEF", "MOVE_FOLLOW_ME", "MOVE_SNATCH", "MOVE_HELPING_HAND", "MOVE_COVET", "MOVE_TRICK", "MOVE_FOCUS_PUNCH",
    "MOVE_FEINT", "MOVE_COPYCAT", "MOVE_ME_FIRST", "MOVE_SWITCHEROO"))
_INVOKER_MOVES = frozenset(("MOVE_NONE", "MOVE_SLEEP_TALK", "MOVE_COPYCAT", "MOVE_ASSIST", "MOVE_ME_FIRST", "MOVE_MIRROR_MOVE",
                            "MOVE_METRONOME"))
_GRAVITY_MOVES = frozenset(("MOVE_FLY", "MOVE_BOUNCE", "MOVE_JUMP_KICK", "MOVE_HI_JUMP_KICK", "MOVE_SPLASH", "MOVE_MAGNET_RISE"))
_CANNOT_ENCORE_EFFECTS = frozenset(_real_effect(m) for m in ("MOVE_TRANSFORM", "MOVE_MIMIC", "MOVE_SKETCH", "MOVE_MIRROR_MOVE",
                                                              "MOVE_ENCORE", "MOVE_STRUGGLE"))
_NUM_VALID_MOVES = 467
_MOVE_NAME_BY_ID = {int(v["id"]): v["name"] for v in _MOVES_BY_NAME.values() if "id" in v}


def _can_be_metronomed(name, bstate):
    return name not in _CANNOT_METRONOME and not (bstate.get("gravity", 0) > 0 and name in _GRAVITY_MOVES)


# ---- terrain-dependent and remaining moves ------------------------------------------------------------------------------------
# The real game picks Nature Power's move and Camouflage's type from the battle terrain (the location of the fight). A tournament has
# no location, so this is a setting: TERRAIN_BUILDING (an arena / gym: Tri Attack, Normal type) unless changed. Terrains are the
# names in generated/battle_terrains.txt; the special-trainer terrains (Aaron ... Cynthia) behave like TERRAIN_BUILDING here.
BATTLE_TERRAIN = "TERRAIN_BUILDING"
_TERRAIN_MOVE = {"TERRAIN_PLAIN": "MOVE_EARTHQUAKE", "TERRAIN_SAND": "MOVE_EARTHQUAKE", "TERRAIN_GRASS": "MOVE_SEED_BOMB",
                 "TERRAIN_PUDDLE": "MOVE_SEED_BOMB", "TERRAIN_MOUNTAIN": "MOVE_ROCK_SLIDE", "TERRAIN_CAVE": "MOVE_ROCK_SLIDE",
                 "TERRAIN_SNOW": "MOVE_BLIZZARD", "TERRAIN_WATER": "MOVE_HYDRO_PUMP", "TERRAIN_ICE": "MOVE_ICE_BEAM",
                 "TERRAIN_BUILDING": "MOVE_TRI_ATTACK", "TERRAIN_GREAT_MARSH": "MOVE_MUD_BOMB", "TERRAIN_BRIDGE": "MOVE_AIR_SLASH",
                 "TERRAIN_SPECIAL": "MOVE_TRI_ATTACK"}
_TERRAIN_TYPE = {"TERRAIN_PLAIN": "TYPE_GROUND", "TERRAIN_SAND": "TYPE_GROUND", "TERRAIN_GRASS": "TYPE_GRASS", "TERRAIN_PUDDLE": "TYPE_GRASS",
                 "TERRAIN_MOUNTAIN": "TYPE_ROCK", "TERRAIN_CAVE": "TYPE_ROCK", "TERRAIN_SNOW": "TYPE_ICE", "TERRAIN_WATER": "TYPE_WATER",
                 "TERRAIN_ICE": "TYPE_ICE", "TERRAIN_BUILDING": "TYPE_NORMAL", "TERRAIN_GREAT_MARSH": "TYPE_GROUND",
                 "TERRAIN_BRIDGE": "TYPE_FLYING", "TERRAIN_SPECIAL": "TYPE_NORMAL"}
_CANNOT_ME_FIRST_EFFECTS = frozenset(_real_effect(m) for m in ("MOVE_COUNTER", "MOVE_MIRROR_COAT", "MOVE_THIEF", "MOVE_COVET",
                                                                "MOVE_FOCUS_PUNCH", "MOVE_CHATTER"))
_HEAL_BLOCKED_MOVES = frozenset(("MOVE_RECOVER", "MOVE_SOFTBOILED", "MOVE_REST", "MOVE_MILK_DRINK", "MOVE_MORNING_SUN", "MOVE_SYNTHESIS",
                                 "MOVE_MOONLIGHT", "MOVE_SWALLOW", "MOVE_HEAL_ORDER", "MOVE_SLACK_OFF", "MOVE_ROOST", "MOVE_LUNAR_DANCE",
                                 "MOVE_HEALING_WISH", "MOVE_WISH"))


def _terrain_key():
    return BATTLE_TERRAIN if BATTLE_TERRAIN in _TERRAIN_MOVE else "TERRAIN_SPECIAL"


def _eff_camouflage(move, a, d, bstate, rng, log):
    """BtlCmd_TryCamouflage: become the terrain's type (fails for Multitype or a mon that already is that type)."""
    t = _TERRAIN_TYPE[_terrain_key()]
    if has_ability(a, "MULTITYPE") or t in a.get("types", ()):
        return False
    a.setdefault("_orig_types", (a.get("type1"), a.get("type2"), list(a.get("types", ()))))
    a["type1"], a["type2"], a["types"] = t, None, [t]
    log.append(f"    {a['species_display']} transformed into the {t.replace('TYPE_', '').title()} type!")
    return True


def _eff_conversion2(move, a, d, bstate, rng, log):
    """BtlCmd_TryConversion2: become a type that resists the type of the last move that hit the user (a random matching chart row
    whose defending type the user does not already have)."""
    hit = a.get("move_hit")
    if has_ability(a, "MULTITYPE") or not hit:
        return False
    move_type = get_move_data_by_name(hit).get("type", "TYPE_NORMAL")
    own = set(a.get("types", ()))
    rows = [vs for row, vs, mul in _AI_TYPE_CHART if row == move_type and mul <= 5 and vs not in own]
    if not rows:
        return False
    t = rows[int(rng.random() * len(rows))]
    a.setdefault("_orig_types", (a.get("type1"), a.get("type2"), list(a.get("types", ()))))
    a["type1"], a["type2"], a["types"] = t, None, [t]
    log.append(f"    {a['species_display']} transformed into the {t.replace('TYPE_', '').title()} type!")
    return True


def _eff_heal_block(move, a, d, bstate, rng, log):
    """subscript_heal_block_start: five turns; fails behind a Substitute or if already blocked."""
    if _substituted(d) or d.get("heal_block_turns", 0):
        return False
    d["heal_block_turns"] = 5
    log.append(f"    {d['species_display']} was prevented from healing!")
    return True


_ENGINE_STATUS_EFFECTS.update({
    "BATTLE_EFFECT_CAMOUFLAGE": _eff_camouflage,
    "BATTLE_EFFECT_CONVERSION2": _eff_conversion2,
    "BATTLE_EFFECT_PREVENT_HEALING": _eff_heal_block,
})
_CALLED_MOVE_EFFECTS.update({"BATTLE_EFFECT_NATURE_POWER": "NATURE_POWER", "BATTLE_EFFECT_USE_MOVE_FIRST": "ME_FIRST"})


def heal_blocked_move(mon, move_name):
    """Move_HealBlocked: the healing moves are unusable while the user is under Heal Block."""
    return mon.get("heal_block_turns", 0) > 0 and move_name in _HEAL_BLOCKED_MOVES


def pick_called_move(kind, actor, bstate, rng, party=None, target=None, target_selected=None):
    """The move Metronome / Mirror Move / Assist turns into (BtlCmd_Metronome, BtlCmd_SetMirrorMove, BtlCmd_TryAssist), or None
    when it fails."""
    if kind == "METRONOME":
        known = set(actor.get("moves", ()))
        for _ in range(100000):
            name = _MOVE_NAME_BY_ID.get(int(rng.random() * _NUM_VALID_MOVES) + 1)
            if name and name not in known and _can_be_metronomed(name, bstate):
                return name
        return None
    if kind == "NATURE_POWER":
        return _TERRAIN_MOVE[_terrain_key()]
    if kind == "ME_FIRST":
        # BtlCmd_TryMeFirst: the foe's chosen move, if it has not acted yet, is damaging and copyable, and is not Struggle
        if (target is None or not target_selected or target_selected == "MOVE_STRUGGLE" or target.get("_acted_turn") == (bstate or {}).get("turn")
                or get_move_data_by_name(target_selected).get("power", 0) <= 0 or _real_effect(target_selected) in _CANNOT_ME_FIRST_EFFECTS):
            return None
        return target_selected
    if kind == "MIRROR_MOVE":
        name = actor.get("move_copied")         # BattleContext.moveCopied: the last mirrorable move a foe used on this mon
        raw = _MOVES_BY_NAME.get(name) if name else None
        if raw and "MOVE_FLAG_CAN_MIRROR_MOVE" in (raw.get("flags") or []) and _real_effect(name) not in _CANNOT_ENCORE_EFFECTS:
            return name
        return None
    candidates = [m for mon in (party or ()) if mon is not actor for m in mon.get("moves", ())
                  if m not in _INVOKER_MOVES and _can_be_metronomed(m, bstate)]
    return candidates[int(rng.random() * len(candidates))] if candidates else None


def note_hit_taken(defender, attacker, dmg, mv):
    """Remember who hit `defender` this turn with what class and how much (BattleContext.turnFlags physicalDamageTakenFrom / special... /
    lastAttacker), for Counter, Mirror Coat and Metal Burst. Only damage that reached the HP counts (a Substitute hit does not)."""
    defender.setdefault("_hits_taken", []).append((attacker, dmg, mv.get("class", "CLASS_PHYSICAL")))


def counter_source(actor, effect, bstate):
    """BtlCmd_Counter / BtlCmd_MirrorCoat / BtlCmd_TryMetalBurst: (mon to hit back, damage to deal) or None when it fails.
    Counter / Mirror Coat return twice the damage taken FROM the last physical / special attacker (that attacker alone); Metal Burst
    returns 1.5x the last hit of either class. The source must still be up and on the other side."""
    hits = actor.get("_hits_taken") or []
    if effect == "METAL_BURST":
        chosen = hits[-1:] and hits[-1]
        source, damage = (chosen[0], int(chosen[1] * 15 // 10)) if chosen else (None, 0)
    else:
        cls = "CLASS_PHYSICAL" if effect == "COUNTER" else "CLASS_SPECIAL"
        matching = [h for h in hits if h[2] == cls]
        if not matching:
            return None
        source = matching[-1][0]
        damage = sum(h[1] for h in matching if h[0] is source) * 2
    if source is None or damage <= 0 or source["hp"] <= 0 or bstate["side_of"](source) == bstate["side_of"](actor):
        return None
    return source, damage


def resolve_called_move(actor, mv_name, mv, target, bstate, rng, log, party, target_selected=None):
    """Swap a calling move for the move it calls. Returns (mv_name, mv, ok); ok=False means 'But it failed!'."""
    kind = _CALLED_MOVE_EFFECTS.get(_real_effect(mv_name))
    if not kind:
        return mv_name, mv, True
    called = pick_called_move(kind, actor, bstate, rng, party, target, target_selected)
    if called is None:
        return mv_name, mv, False
    log.append(f"    {actor['species_display']}'s {mv_name.replace('MOVE_', '').replace('_', ' ').title()} called "
               f"{called.replace('MOVE_', '').replace('_', ' ').title()}!")
    called_mv = get_effective_move_data(called, actor, defender=target, bstate=bstate, rng=rng)
    if kind == "ME_FIRST":
        actor["me_first"] = True                              # x1.5 damage on this use (BattleScript_CalcMoveDamage)
    bstate["last_move_used"] = called
    actor["last_move_used"] = called
    return called, called_mv, True


def any_active_with(bstate, key):
    """True if any mon on the field has `key` set (BattleSystem_AnyBattlersWithMoveEffect); bstate["all_actives"] is a
    zero-argument callable each engine installs."""
    getter = (bstate or {}).get("all_actives")
    return any(m is not None and m.get(key) for m in getter()) if getter else False


def cleanup_stale_links(bstate):
    """Mean Look / Block / Spider Web last only while the user is still on the field (and alive)."""
    getter = (bstate or {}).get("all_actives")
    if not getter:
        return
    mons = [m for m in getter() if m is not None]
    live = {id(m) for m in mons if m["hp"] > 0}
    for m in mons:
        if m.get("mean_look") and m["mean_look"] not in live:
            m["mean_look"] = None


def apply_move_effect(move, attacker, defender, bstate, rng, log):
    effect = move.get("effect")
    side_of = bstate["side_of"]

    engine_handler = _ENGINE_STATUS_EFFECTS.get(_real_effect(move.get("name", ""))) if move.get("class") == "CLASS_STATUS" else None
    if engine_handler:
        if not engine_handler(move, attacker, defender, bstate, rng, log):
            log.append("    But it failed!")
        return

    if move.get("name") in ("MOVE_LOCK_ON", "MOVE_MIND_READER") and defender is not attacker:
        defender["locked_on_by"] = id(attacker)
        defender["lock_on_turns"] = 2          # MOVE_EFFECT_LOCK_ON_INITIAL_DURATION: this turn and the next
        log.append(f"    {attacker['species_display']} took aim at {defender['species_display']}!")

    if move.get("charges_electric"):
        attacker["charged"] = True

    if move.get("also_confuses") and _substituted(defender):
        # subscript_swagger / subscript_flatter open with CheckSubstitute: the whole move fails, the stat boost included
        log.append("    But it failed!")
        return

    for (target, stat, stages) in move.get("stat_changes", []):
        if stat == "random":
            stat = rng.choice(["atk", "def", "spa", "spd", "spe", "acc", "eva"])
        mon = attacker if target == "self" else defender
        key = f"{stat}_stage"
        if key not in mon:
            continue
        if (has_ability(mon, "CLEAR_BODY") or has_ability(mon, "WHITE_SMOKE")) and stages < 0 and target == "target" \
                and not has_ability(attacker, "MOLD_BREAKER"):
            continue
        if stat == "acc" and stages < 0 and target == "target" and has_ability(mon, "KEEN_EYE") and not has_ability(attacker, "MOLD_BREAKER"):
            continue
        if stat == "atk" and stages < 0 and target == "target" and has_ability(mon, "HYPER_CUTTER") and not has_ability(attacker, "MOLD_BREAKER"):
            continue
        if stages < 0 and target == "target" and bstate["sides"][side_of(defender)].get("mist", 0) > 0:
            # Standard Gen4 Mold Breaker does not bypass Mist, so this is
            # an unconditional block - no ability check needed.
            log.append(f"    {defender['species_display']} is protected by Mist!")
            continue
        before = mon.get(key, 0)
        effective_stages = stages * (2 if has_ability(mon, "SIMPLE") else 1)
        mon[key] = max(-6, min(6, before + effective_stages))
        if mon[key] != before:
            log.append(f"    {mon['species_display']}'s {stat.upper()} {'rose' if stages > 0 else 'fell'}!")
            if mon[key] < before and stat in ("atk", "def", "spa", "spd", "spe"):
                note_debuff_source(bstate, mon, stat, attacker, before - mon[key])

    if move.get("also_confuses"):
        # Swagger/Flatter: boosts a stat (handled generically above), then subscript_confuse (DIRECT) - which runs even if the
        # boost was capped at +6, and is skipped only when the target is already confused
        if try_confuse(defender, attacker, rng, log, CONFUSION_DIRECT):
            note_contribution(bstate, defender, attacker, "status")

    if effect in ("SLEEP", "POISON", "TOXIC", "PARALYZE", "BURN"):
        status_name = {"POISON": "POISON", "TOXIC": "TOXIC", "PARALYZE": "PARALYSIS", "BURN": "BURN", "SLEEP": "SLEEP"}[effect]
        # Ground-types are immune to Thunder Wave specifically - a hardcoded exception on the move itself, not a
        # general status-move-respects-type-immunity rule (status moves otherwise ignore the type chart in Gen4:
        # Confuse Ray still confuses Normal-types, Glare still paralyzes Ghost-types). Scoped to this exact move via
        # can_inflict_status's own caller rather than can_inflict_status/status_blocked_by_type themselves, since
        # those are shared with Body Slam's secondary paralysis and Stun Spore, which must still work on Ground-types.
        thunder_wave_blocked = (move.get("name") == "MOVE_THUNDER_WAVE"
                                 and "TYPE_GROUND" in (defender.get("type1"), defender.get("type2")))
        if not thunder_wave_blocked and can_inflict_status(effect, attacker, defender, weather_now(bstate)):
            defender["status"] = status_name
            log.append(f"    {defender['species_display']} was afflicted with {status_name}!")
            note_contribution(bstate, defender, attacker, "status")
            _synchronize(defender, attacker, status_name, bstate, log)
    elif effect == "CONFUSE":
        if try_confuse(defender, attacker, rng, log, CONFUSION_DIRECT):
            note_contribution(bstate, defender, attacker, "status")
    elif effect == "ATTRACT":
        # Was previously "if can_inflict_status(...) or True:", which made
        # the whole condition unconditionally true - Oblivious, matching
        # genders, and genderless targets were never actually enforced
        # here even though basic_flag_score already knows to steer the AI
        # away from a doomed Attract for exactly these reasons.
        if defender.get("attracted"):
            log.append(f"    But it failed! {defender['species_display']} is already in love.")
        elif has_ability(defender, "OBLIVIOUS") and not has_ability(attacker, "MOLD_BREAKER"):
            log.append(f"    It doesn't affect {defender['species_display']} (Oblivious)!")
        elif defender.get("gender") == attacker.get("gender") or "GENDERLESS" in (attacker.get("gender"), defender.get("gender")):
            log.append(f"    But it failed! {defender['species_display']} can't be attracted.")
        else:
            defender["attracted"] = True
            log.append(f"    {defender['species_display']} fell in love!")
    elif effect == "LEECH_SEED":
        if "TYPE_GRASS" not in defender.get("types", []):          # Magic Guard only cancels the sapping later, not the seed
            defender["leech_seeded"] = True
            defender["leech_seed_slot"] = _slot_key(attacker, bstate) if bstate.get("slot_of") else None
            log.append(f"    {defender['species_display']} was seeded!")
            note_contribution(bstate, defender, attacker, "status")
    elif effect == "PERISH_SONG":
        # Affects every Pokemon currently on the field (in this 1v1 sim,
        # that's both actives, including the user), not just the target.
        # A Pokemon already counting down doesn't get its count reset,
        # and Soundproof blocks it entirely.
        for mon in (attacker, defender):
            if mon["hp"] <= 0 or has_ability(mon, "SOUNDPROOF"):
                continue
            if mon.get("perish_song", 0) == 0:
                mon["perish_song"] = 3
                log.append(f"    {mon['species_display']}'s perish count will hit zero in 3 turns!")
    elif effect == "STOCKPILE":
        # Handled entirely here rather than via the generic stat_changes
        # list above, so a 4th use (already at 3 stacks) fails outright -
        # no stack gained AND no Def/SpDef boost - instead of the boost
        # silently applying (or silently no-op'ing) regardless of the cap.
        current = attacker.get("stockpile", 0)
        if current >= 3:
            log.append(f"    {attacker['species_display']}'s stockpile is already full - it failed!")
        else:
            attacker["stockpile"] = current + 1
            for stat in ("def", "spd"):
                key = f"{stat}_stage"
                before = attacker.get(key, 0)
                attacker[key] = max(-6, min(6, before + 1))
                if attacker[key] != before:
                    log.append(f"    {attacker['species_display']}'s {stat.upper()} rose!")
            log.append(f"    {attacker['species_display']} stockpiled {attacker['stockpile']}!")
    elif effect == "SWALLOW":
        stacks = attacker.get("stockpile", 0)
        if stacks <= 0:
            log.append(f"    But it failed! {attacker['species_display']} had nothing stockpiled.")
        else:
            heal_fraction = {1: 0.25, 2: 0.5, 3: 1.0}[stacks]
            heal = int(attacker["max_hp"] * heal_fraction)
            attacker["hp"] = min(attacker["max_hp"], attacker["hp"] + heal)
            log.append(f"    {attacker['species_display']} swallowed its stockpiled energy and recovered HP!")
            # Swallowing reverses the Def/SpDef boosts Stockpile granted and
            # empties the counter, per Gen4 mechanics (a simplification:
            # this assumes those exact stages weren't touched by anything
            # else in between, which is true for the vast majority of games).
            clear_stockpile(attacker)
    elif effect == "SPIT_UP":
        # The damage itself (100/200/300 power for 1/2/3 stacks) was
        # already resolved above using the stockpile count AT THE TIME OF
        # USE (see run_battle, which builds a per-use copy of this move's
        # data before stockpile gets reset here) - this branch only
        # handles the "consumes the stockpile" side effect, same as Swallow.
        stacks = attacker.get("stockpile", 0)
        if stacks <= 0:
            log.append(f"    But it failed! {attacker['species_display']} had nothing stockpiled.")
        else:
            clear_stockpile(attacker)
            log.append(f"    {attacker['species_display']}'s stockpiled energy was released!")
    elif effect == "ENDEAVOR":
        if defender.get("substitute_hp", 0) > 0:
            log.append("    But it failed against the Substitute!")
        elif attacker["hp"] >= defender["hp"]:
            log.append(f"    But it failed! {attacker['species_display']}'s HP is not below {defender['species_display']}'s.")
        else:
            dmg = defender["hp"] - attacker["hp"]
            defender["hp"] = attacker["hp"]
            log.append(f"    {defender['species_display']}'s HP was cut down to match {attacker['species_display']}'s! (-{dmg} HP)")
    elif effect == "CURSE":
        # Curse's behavior depends on the USER's own type, not anything
        # fixed in the move's data - a non-Ghost user gets a self-buff,
        # a Ghost-type user instead pays HP to curse the TARGET.
        if "TYPE_GHOST" in attacker.get("types", []):
            if defender.get("cursed"):
                log.append(f"    But it failed! {defender['species_display']} is already cursed.")
            else:
                cost = max(1, attacker["max_hp"] // 2)
                attacker["hp"] = max(0, attacker["hp"] - cost)
                defender["cursed"] = True
                log.append(f"    {attacker['species_display']} cut its own HP and laid a curse on {defender['species_display']}!")
        else:
            for stat, stages in (("atk", 1), ("def", 1), ("spe", -1)):
                key = f"{stat}_stage"
                before = attacker.get(key, 0)
                attacker[key] = max(-6, min(6, before + stages))
                if attacker[key] != before:
                    log.append(f"    {attacker['species_display']}'s {stat.upper()} {'rose' if stages > 0 else 'fell'}!")
    elif effect in ("RECOVER",):
        heal = int(attacker["max_hp"] * move.get("heal_fraction", 0.5))
        if move.get("sun_boosted"):
            if bstate["weather"] == "SUN":
                heal = int(attacker["max_hp"] * 0.667)
            elif bstate["weather"] in ("RAIN", "SANDSTORM", "HAIL"):
                heal = int(attacker["max_hp"] * 0.25)
        attacker["hp"] = min(attacker["max_hp"], attacker["hp"] + heal)
        log.append(f"    {attacker['species_display']} restored its HP!")
    elif effect == "REST":
        if attacker["hp"] >= attacker["max_hp"]:
            log.append(f"    But it failed! {attacker['species_display']} has full HP.")
        elif has_ability(attacker, "INSOMNIA") or has_ability(attacker, "VITAL_SPIRIT"):
            log.append(f"    But it failed! {attacker['species_display']} won't fall asleep.")
        else:
            attacker["hp"] = attacker["max_hp"]
            attacker["status"] = "SLEEP"
            attacker["sleep_turns"] = 0
            attacker["rest_sleep"] = True
            log.append(f"    {attacker['species_display']} went to sleep and restored its HP!")
    elif effect and effect.startswith("WEATHER_"):
        new_weather = effect.replace("WEATHER_", "")
        if new_weather == "SUN" and bstate["weather"] == "SUN":
            # Sunny Day specifically fails outright if the sun is already
            # shining (from an earlier Sunny Day or a weather-setting
            # ability) - unlike Rain Dance/Sandstorm/Hail, which simply
            # refresh their own duration when re-used on themselves.
            log.append("    But it failed! The sunlight is already harsh.")
        else:
            bstate["weather"] = new_weather
            note_weather_set(bstate, new_weather, attacker)
            bstate["weather_turns"] = 8 if (new_weather == "SUN" and attacker.get("item") == "ITEM_HEAT_ROCK" and item_effects_active(attacker)) else 5
            log.append(f"    The weather became {bstate['weather']}!")
    elif effect == "REFLECT":
        duration = 8 if attacker.get("item") == "ITEM_LIGHT_CLAY" and item_effects_active(attacker) else 5
        bstate["sides"][side_of(attacker)]["reflect"] = duration
        note_screen_set(bstate, side_of(attacker), "reflect", attacker)
        log.append(f"    {attacker['species_display']}'s side gained a Reflect barrier!")
    elif effect == "LIGHT_SCREEN":
        duration = 8 if attacker.get("item") == "ITEM_LIGHT_CLAY" and item_effects_active(attacker) else 5
        bstate["sides"][side_of(attacker)]["light_screen"] = duration
        note_screen_set(bstate, side_of(attacker), "light_screen", attacker)
        log.append(f"    {attacker['species_display']}'s side gained a Light Screen barrier!")
    elif effect == "SAFEGUARD":
        attacker["safeguard"] = 5
        log.append(f"    {attacker['species_display']} became cloaked in a mystical veil!")
    elif effect == "TAILWIND":
        bstate["sides"][side_of(attacker)]["tailwind"] = 4
        note_tailwind_set(bstate, side_of(attacker), attacker)
        log.append(f"    A tailwind blew behind {attacker['species_display']}'s side!")
    elif effect == "MIST":
        bstate["sides"][side_of(attacker)]["mist"] = 5
        log.append(f"    {attacker['species_display']}'s side became shrouded in mist!")
    elif effect == "HAZE":
        # Resets every stat stage - both boosts and drops - back to 0
        # for both combatants at once, not just the caster's own side.
        # In doubles this reaches only the two Pokemon directly involved
        # in this move's resolution, not all 4 active Pokemon, matching
        # this engine's established doubles-simplification pattern for
        # effects that would otherwise need the full field.
        for mon in (attacker, defender):
            for stat_key in ("atk_stage", "def_stage", "spa_stage", "spd_stage", "spe_stage", "acc_stage", "eva_stage"):
                mon[stat_key] = 0
        log.append("    All stat changes were eliminated!")
    elif effect == "FOCUS_ENERGY":
        if attacker.get("focus_energy"):
            log.append(f"    But it failed! {attacker['species_display']} is already focused.")
        else:
            attacker["focus_energy"] = True
            log.append(f"    {attacker['species_display']} is getting pumped!")
    elif effect == "CAPTIVATE":
        # Only affects a target of the OPPOSITE gender - fails outright
        # against a genderless target (e.g. Magnemite) or if the user
        # itself is genderless, and Oblivious blocks it entirely
        # (bypassed by Mold Breaker, like any other ignorable ability).
        atk_gender, def_gender = attacker.get("gender"), defender.get("gender")
        if atk_gender in (None, "GENDERLESS") or def_gender in (None, "GENDERLESS") or atk_gender == def_gender:
            log.append("    But it failed!")
        elif has_ability(defender, "OBLIVIOUS") and not has_ability(attacker, "MOLD_BREAKER"):
            log.append(f"    It doesn't affect {defender['species_display']} (Oblivious)!")
        elif has_ability(defender, "CLEAR_BODY") and not has_ability(attacker, "MOLD_BREAKER"):
            pass
        elif bstate["sides"][side_of(defender)].get("mist", 0) > 0:
            log.append(f"    {defender['species_display']} is protected by Mist!")
        else:
            before = defender.get("spa_stage", 0)
            effective_stages = -2 * (2 if has_ability(defender, "SIMPLE") else 1)
            defender["spa_stage"] = max(-6, min(6, before + effective_stages))
            if defender["spa_stage"] != before:
                log.append(f"    {defender['species_display']}'s SPA fell!")
                note_debuff_source(bstate, defender, "spa", attacker, before - defender["spa_stage"])
    elif effect == "MEMENTO":
        # By the time this branch runs the move has already successfully
        # hit a real, non-Substitute-protected target (a miss, no valid
        # target, or a Substitute block are all handled earlier in the
        # dispatch and never reach here) - so the user faints
        # unconditionally, even if Clear Body/Mist/an already-minimum
        # stat happens to no-op the stat drop itself.
        for stat, key in (("atk", "atk_stage"), ("spa", "spa_stage")):
            if has_ability(defender, "CLEAR_BODY") and not has_ability(attacker, "MOLD_BREAKER"):
                continue
            if stat == "atk" and has_ability(defender, "HYPER_CUTTER") and not has_ability(attacker, "MOLD_BREAKER"):
                continue
            if bstate["sides"][side_of(defender)].get("mist", 0) > 0:
                continue
            before = defender.get(key, 0)
            effective_stages = -2 * (2 if has_ability(defender, "SIMPLE") else 1)
            defender[key] = max(-6, min(6, before + effective_stages))
            if defender[key] != before:
                log.append(f"    {defender['species_display']}'s {stat.upper()} fell!")
                note_debuff_source(bstate, defender, stat, attacker, before - defender[key])
        attacker["hp"] = 0
        note_ko_cause(attacker, KO_CAUSE_SUICIDE)
        log.append(f"    {attacker['species_display']} cut its own HP to hurt the opposing Pokemon!")
    elif effect == "LUCKY_CHANT":
        bstate["sides"][side_of(attacker)]["lucky_chant"] = 5
        log.append(f"    {attacker['species_display']}'s side is shielded by the Lucky Chant!")
    elif effect == "TRICK_ROOM":
        # A genuine TOGGLE in Gen4: using it again while already active
        # turns it back OFF immediately rather than refreshing the
        # duration, unlike screens/Mist/Lucky Chant which just reset to 5.
        if bstate.get("trick_room", 0) > 0:
            bstate["trick_room"] = 0
            log.append("    The twisted dimensions returned to normal!")
        else:
            bstate["trick_room"] = 5
            log.append(f"    {attacker['species_display']} twisted the dimensions!")
    elif effect == "GRAVITY":
        if bstate.get("gravity", 0) > 0:
            log.append("    But it failed! Gravity is already intense.")
        else:
            bstate["gravity"] = 5
            log.append("    Gravity intensified!")
    elif effect == "YAWN":
        if defender.get("status", "NONE") != "NONE" or defender.get("yawn_turn", 0) > 0 \
                or (status_blocked_by_ability("SLEEP", defender) and not has_ability(attacker, "MOLD_BREAKER")):
            log.append(f"    But it failed! {defender['species_display']} can't be made drowsy.")
        else:
            defender["yawn_turn"] = 2
            defender["yawn_source"] = (bstate["side_of"](attacker), _true_species(attacker)) if "side_of" in bstate else None
            log.append(f"    {defender['species_display']} grew drowsy!")
    elif effect == "NIGHTMARE":
        if defender.get("status") != "SLEEP":
            log.append(f"    But it failed! {defender['species_display']} is not asleep.")
        elif defender.get("nightmare"):
            log.append(f"    But it failed! {defender['species_display']} is already locked in a nightmare.")
        else:
            defender["nightmare"] = True
            log.append(f"    {defender['species_display']} began having a nightmare!")
    elif effect == "TAUNT":
        if defender.get("taunt_turns", 0) > 0:
            log.append(f"    But it failed! {defender['species_display']} is already taunted.")
        else:
            defender["taunt_turns"] = rng.randint(3, 5)
            log.append(f"    {defender['species_display']} fell for the taunt!")
    elif effect == "TORMENT":
        if defender.get("tormented"):
            log.append(f"    But it failed! {defender['species_display']} is already tormented.")
        else:
            defender["tormented"] = True
            log.append(f"    {defender['species_display']} was subjected to torment!")
    elif effect == "EMBARGO":
        if defender.get("embargo_turns", 0) > 0:
            log.append(f"    But it failed! {defender['species_display']} is already under Embargo.")
        else:
            defender["embargo_turns"] = 5
            log.append(f"    {defender['species_display']} can't use items anymore!")
    elif effect == "GRUDGE":
        attacker["grudge_active"] = True
        log.append(f"    {attacker['species_display']} wants its target to bear a grudge!")
    elif effect == "SNATCH":
        bstate.setdefault("snatchers", []).append(attacker)
        log.append(f"    {attacker['species_display']} waits for a target to make a move!")
    elif effect == "TRICK":
        if not attacker.get("item") and not defender.get("item"):
            log.append("    But it failed!")
        elif defender.get("substitute_hp", 0) > 0:
            log.append("    But it failed!")
        else:
            attacker["item"], defender["item"] = defender.get("item"), attacker.get("item")
            log.append(f"    {attacker['species_display']} switched items with its target!")
            ai_reveal_item(attacker)
            ai_reveal_item(defender)
    elif effect == "ENCORE":
        last_move = defender.get("last_move_used")
        if defender.get("encore_turns", 0) > 0:
            log.append(f"    But it failed! {defender['species_display']} is already encored.")
        elif (not last_move or last_move in ("MOVE_TRANSFORM", "MOVE_MIMIC", "MOVE_SKETCH", "MOVE_MIRROR_MOVE",
                                              "MOVE_ENCORE", "MOVE_STRUGGLE")
              or defender.get("move_pp", {}).get(last_move, 0) <= 0):
            log.append("    But it failed!")
        else:
            defender["encore_move"] = last_move
            defender["encore_turns"] = rng.randint(3, 7)
            log.append(f"    {defender['species_display']} received an encore!")
    elif effect == "IMPRISON":
        if attacker.get("imprison_moves"):
            log.append(f"    But it failed! {attacker['species_display']} is already imprisoning its foe.")
        else:
            attacker["imprison_moves"] = list(attacker.get("moves", []))
            log.append(f"    {attacker['species_display']} sealed any of the opponent's moves it shares!")
    elif effect == "STEALTH_ROCK":
        bstate["sides"][side_of(defender)]["stealth_rock"] = True
        note_hazard_set(bstate, side_of(defender), "stealth_rock", attacker)
    elif effect == "SPIKES":
        s = bstate["sides"][side_of(defender)]
        s["spikes"] = min(3, s.get("spikes", 0) + 1)
        note_hazard_set(bstate, side_of(defender), "spikes", attacker)
    elif effect == "TOXIC_SPIKES":
        s = bstate["sides"][side_of(defender)]
        s["toxic_spikes"] = min(2, s.get("toxic_spikes", 0) + 1)
        note_hazard_set(bstate, side_of(defender), "toxic_spikes", attacker)
    elif effect == "ENDURE":
        attacker["endure_active"] = True
    elif effect == "AQUA_RING":
        attacker["aqua_ring"] = True
        log.append(f"    {attacker['species_display']} surrounded itself with a veil of water!")
    elif effect == "INGRAIN":
        attacker["ingrain"] = True
        log.append(f"    {attacker['species_display']} planted its roots!")

    if move.get("protect"):
        chain = attacker.get("protect_chain", 0)
        success_chance = 1 / (3 ** chain) if attacker.get("protect_used_last") else 1.0
        if rng.random() < success_chance:
            attacker["protected"] = True
            attacker["protect_chain"] = chain + 1
        else:
            attacker["protect_chain"] = 0
        attacker["protect_used_last"] = True
    else:
        attacker["protect_used_last"] = False
        if not move.get("substitute"):
            attacker["protect_chain"] = 0

    if move.get("substitute") and attacker.get("substitute_hp", 0) <= 0:
        cost = attacker["max_hp"] // 4
        if attacker["hp"] > cost:
            attacker["hp"] -= cost
            attacker["substitute_hp"] = cost
            log.append(f"    {attacker['species_display']} put up a Substitute!")


# ============================================================
# BATTLE ENGINE
# ============================================================
def new_side_state():
    return {"reflect": 0, "light_screen": 0, "safeguard": 0, "spikes": 0, "toxic_spikes": 0,
            "stealth_rock": False, "tailwind": 0, "mist": 0, "lucky_chant": 0,
            "future_sight": None, "wish": None}


def _record_damaging_hit_event(bstate, defender, attacker=None):
    """Record one direct damaging hit that reached the Pokemon's real HP.

    Substitute absorption, entry hazards, residual status/weather, recoil and
    confusion self-damage deliberately do not call this helper, so the wall
    metric represents attacks the Pokemon itself actually absorbed. The
    attacker (when known) also earns a "damage" assist credit on the defender.
    """
    if attacker is not None:
        note_contribution(bstate, defender, attacker, "damage")
    side = bstate["side_of"](defender)
    trainer_key = bstate.get("trainer_keys", {}).get(side)
    if trainer_key is None:
        return
    bstate.setdefault("_analytics_damaging_hit_events", []).append({
        "trainer": trainer_key,
        "species": defender.get("species") or defender.get("species_display"),
    })


def _record_secondary_roll_event(bstate, attacker, sec, effective_chance, success):
    """Record one *eligible* secondary-effect RNG roll in memory.

    Defender-targeted secondaries produce no event on KO hits because Gen 4
    skips those rolls entirely. Self-directed secondaries remain eligible on a
    KO hit. Storing the effective chance plus success/failure lets Luck_Score
    compare the outcome to its expectation without inventing phantom failures.
    """
    side = bstate["side_of"](attacker)
    trainer_key = bstate.get("trainer_keys", {}).get(side)
    if trainer_key is None:
        return
    bstate.setdefault("_analytics_secondary_roll_events", []).append({
        "trainer": trainer_key,
        "species": attacker.get("species") or attacker.get("species_display"),
        "effect": sec.get("effect"),
        "target": sec.get("target"),
        "chance": min(1.0, max(0.0, float(effective_chance))),
        "success": bool(success),
    })


# ============================================================
# ASSIST TRACKING (feeds the KDA metric - see export_species_analytics_csv)
# ============================================================
# Every combatant carries small dicts, all empty (or None) at the start of each battle / on switch-in (see reset_on_switch_in):
#   mon["contributors"]    = {species: {category: turn}}  who helped bring THIS mon down, and how
#   mon["supporters"]      = {species: turn}               teammates that healed / cured this mon while it has been on the field
#   mon["screened_hits"]   = {id(attacker): (side, species)} which attackers had a hit on THIS mon actually reduced by its side's
#                             Reflect / Light Screen, and who set that screen (persists for the whole battle, not just one stay)
#   mon["baton_pass_from"] = (side, species) or None        who Baton Passed a real buff onto this mon, while it stays out
#   mon["debuff_source"]   = {stat: (side, species, turn, magnitude)} who most recently lowered this mon's atk/def/spa/spd/spe stage
#                             (opponent-sourced only - a self-inflicted drawback drop like Superpower never gets recorded here), used
#                             only while that stat's stage is still negative right now (see note_debuff_source)
# Categories: "damage" (direct HP damage from a move or Rough Skin), "status" (a sleep / paralysis / burn / poison / toxic / freeze /
# confusion / Leech Seed it inflicted, also through Synchronize, Static & co, Yawn and Psycho Shift), "hazard" (Stealth Rock / Spikes /
# Toxic Spikes it laid, when they hurt), "weather" (the weather it set, when the weather hurts), "cleric" (a teammate it healed or
# cured with Wish / Healing Wish / Lunar Dance / Heal Bell / Aromatherapy that then landed damage or a status), "screen" (its Reflect /
# Light Screen actually reduced a hit on a teammate, and that teammate went on to help faint the very attacker that landed it),
# "pass" (it Baton Passed a real buff - a positive stat stage, Substitute, Aqua Ring, Ingrain, Focus Energy, Power Trick or an active
# Magnet Rise, not just a hindrance or nothing - onto a teammate that then scored a KO while still carrying it), "debuff" (it lowered
# the eventual victim's Defense/Sp.Defense and a matching physical/special hit later landed the KO; or it lowered the eventual victim's
# own Attack/Sp.Attack, which made that victim's own hit fall short of a KO it would otherwise have scored, letting the survivor finish
# the victim off later - see note_debuff_source and the Mechanic A/B hooks in _record_damaging_hit_event's call sites) and "tailwind"
# (its Tailwind let a teammate that wasn't already faster act first and land the KO - mirrors "debuff" for Speed, see
# note_tailwind_set). "cleric", "screen", "debuff" and "tailwind" all roll up into the species-tier "Support" role, "pass" into
# "Passer" (see ROLE_CATEGORIES). When a mon faints, whoever struck the final blow gets the KO (the engine's ko_events, unchanged) and
# every OTHER species in its contributors gets one assist that carries the categories it contributed; a passive faint (poison, weather,
# hazards, confusion...) has no killer, so every contributor gets one. Credit only ever crosses sides: self-inflicted and friendly-fire
# damage never counts. The events land in bstate["_analytics_assist_events"] and from there in game_stats["assist_events"].
ASSIST_CATEGORIES = ("damage", "status", "hazard", "weather", "cleric", "screen", "pass", "debuff", "tailwind")
# None: any contribution earlier in the same battle still counts (the default); N: only contributions from the last N turns do.
ASSIST_WINDOW_TURNS = None


def _true_species(mon):
    """The species a mon really is - a Transformed mon keeps its own identity in the analytics."""
    return (mon.get("pre_transform") or {}).get("species") or mon.get("species") or mon.get("species_display")


def _contribution_source(bstate, source):
    """(side, species, mon-or-None) of a contribution source: a mon dict, or an already-resolved (side, species) pair."""
    if isinstance(source, tuple):
        return source[0], source[1], None
    return bstate["side_of"](source), _true_species(source), source


def note_contribution(bstate, victim, source, category):
    """`source` helped bring `victim` down in the way `category` names. Same-side sources are ignored (self-inflicted damage, friendly
    fire), so callers can report every damage / status event without checking. A source that was itself healed by a teammate cleric
    passes that teammate's credit along (damage and status only), and likewise a source that had a hit off THIS SAME victim reduced by
    a teammate's Reflect / Light Screen passes that screen-setter's credit along too - it is the victim beating the attacker that once
    hurt it less that matters, not any earlier faint."""
    if not bstate or victim is None or source is None or "side_of" not in bstate:
        return
    side, species, src_mon = _contribution_source(bstate, source)
    if species is None or side == bstate["side_of"](victim):
        return
    turn = bstate.get("turn", 0)
    contributors = victim.setdefault("contributors", {})
    contributors.setdefault(species, {})[category] = turn
    if src_mon is not None and category in ("damage", "status"):
        for helper, since in (src_mon.get("supporters") or {}).items():
            if helper != species and (ASSIST_WINDOW_TURNS is None or turn - since <= ASSIST_WINDOW_TURNS):
                contributors.setdefault(helper, {})["cleric"] = turn
        screen_setter = (src_mon.get("screened_hits") or {}).get(id(victim))
        if screen_setter is not None and screen_setter[1] != species \
                and (ASSIST_WINDOW_TURNS is None or turn - screen_setter[2] <= ASSIST_WINDOW_TURNS):
            contributors.setdefault(screen_setter[1], {})["screen"] = turn


def note_cleric_support(bstate, cleric, recipient):
    """`cleric` healed or cured its on-field teammate `recipient`: until the recipient leaves the field, whatever damage or status it lands
    also credits the cleric with a "cleric" assist."""
    if not bstate or cleric is None or recipient is None or cleric is recipient or recipient["hp"] <= 0 or "side_of" not in bstate:
        return
    if bstate["side_of"](cleric) != bstate["side_of"](recipient):
        return
    recipient.setdefault("supporters", {})[_true_species(cleric)] = bstate.get("turn", 0)


def note_hazard_set(bstate, target_side, hazard, setter):
    """`setter` laid `hazard` ("stealth_rock" / "spikes" / "toxic_spikes") on `target_side`; it stays credited while the hazard lasts."""
    if "side_of" in bstate:
        bstate["sides"][target_side].setdefault("hazard_setters", {}).setdefault(hazard, set()).add(
            (bstate["side_of"](setter), _true_species(setter)))


def note_hazard_damage(bstate, victim, side_key, hazard):
    """`victim` was hurt (or poisoned) by `hazard` on entering `side_key`: every mon that laid it earns a "hazard" credit."""
    for who in bstate["sides"][side_key].get("hazard_setters", {}).get(hazard, ()):
        note_contribution(bstate, victim, who, "hazard")


def note_weather_set(bstate, weather, setter):
    """`setter` (a move user or an ability holder) made it `weather`."""
    if "side_of" in bstate:
        bstate.setdefault("weather_setters", {})[weather] = (bstate["side_of"](setter), _true_species(setter))


def note_weather_damage(bstate, victim, weather):
    """`victim` took damage from `weather`: whoever set it earns a "weather" credit (unless that was the victim's own side)."""
    who = (bstate.get("weather_setters") or {}).get(weather)
    if who is not None:
        note_contribution(bstate, victim, who, "weather")


def note_screen_set(bstate, side, screen_key, setter):
    """`setter` raised `screen_key` ("reflect" / "light_screen") for `side`; it stays credited (replacing any earlier setter of the
    same screen) while the barrier lasts."""
    if "side_of" in bstate:
        bstate["sides"][side].setdefault("screen_setters", {})[screen_key] = (bstate["side_of"](setter), _true_species(setter))


def note_screen_reduced_hit(bstate, defender, attacker, screen_key):
    """`attacker`'s hit on `defender` was just actually reduced by `defender`'s side's `screen_key`: remember who set it (and when),
    keyed to this exact attacker, so that if `defender` later helps faint that same attacker, the setter gets a "screen" assist too -
    subject to the same ASSIST_WINDOW_TURNS as every other forwarded credit (see note_contribution). Nothing to remember if the screen
    has no setter on record (e.g. a dataset from before this tracking existed resimulated mid-battle - never happens in practice, but
    note_screen_set always runs first when it does)."""
    if not bstate or "side_of" not in bstate:
        return
    setter = bstate["sides"][bstate["side_of"](defender)].get("screen_setters", {}).get(screen_key)
    if setter is not None:
        defender.setdefault("screened_hits", {})[id(attacker)] = (setter[0], setter[1], bstate.get("turn", 0))


def note_debuff_source(bstate, target, stat_key, source, magnitude):
    """`source` just lowered `target`'s `stat_key` ("atk"/"def"/"spa"/"spd"/"spe") stage by `magnitude` stages (already applied - this
    only records attribution for a later "debuff" assist). Self-inflicted drawback drops (Superpower, Overheat, Close Combat...) are
    same-side and so are ignored here exactly like note_contribution ignores them - this also means a self-drop can never clobber an
    earlier real opponent attribution. Only the single most recent opponent-sourced drop per stat is kept (stages have no change
    history in this engine, just one clamped int), which is exact for the common single-drop case and a reasonable approximation when
    several different opponents stack drops on the same stat in one battle."""
    if not bstate or source is None or "side_of" not in bstate:
        return
    side, species, _src_mon = _contribution_source(bstate, source)
    if species is None or side == bstate["side_of"](target):
        return
    target.setdefault("debuff_source", {})[stat_key] = (side, species, bstate.get("turn", 0), magnitude)


def note_tailwind_set(bstate, side, setter):
    """`setter` raised Tailwind for `side`; it stays credited (replacing any earlier setter) while Tailwind lasts - mirrors
    note_screen_set/note_weather_set."""
    if "side_of" in bstate:
        bstate["sides"][side]["tailwind_setter"] = (bstate["side_of"](setter), _true_species(setter))


def note_stat_drop_ko_assists(bstate, attacker, defender, mv, dmg, pre_hit_hp, is_crit, rng):
    """Call right after a REAL damaging hit (`attacker`'s `mv` dealt `dmg` to `defender`, whose HP was `pre_hit_hp` right before this
    hit) has already been subtracted from `defender["hp"]`. Covers two of the four "debuff" assist mechanics (the other two - Speed/
    Tailwind turn-order flips - are handled separately at the turn-order decision points):

    Mechanic A (Defense/Sp.Defense): if `defender` currently has a live, opponent-sourced drop on the stat this exact move category
    benefits from (Defense for a physical hit, Sp.Defense for a special one), the original debuffer earns a "debuff" credit toward
    defender's eventual faint - refreshed on every such hit, exactly like the existing hazard/weather credit refreshes.

    Mechanic B ("Counter-KO"): if `attacker` currently has a live, opponent-sourced drop on the stat this move category uses (Attack
    for physical, Sp.Attack for special), and this hit did NOT faint `defender`, recompute what this exact hit would have dealt with
    that drop undone (reusing the save/mutate/recompute/restore pattern already used by _crash_damage/estimate_max_damage elsewhere in
    this file). If the undone-drop damage would have brought `defender` to 0 HP, `defender` only survived because of the drop - the
    original debuffer earns a "debuff" credit toward `attacker`'s OWN eventual faint (by any means, not necessarily by `defender`
    specifically - consistent with every other assist category, none of which require a particular killer beyond excluding its own
    species)."""
    move_class = mv.get("class")
    def_key = "def" if move_class == "CLASS_PHYSICAL" else "spd" if move_class == "CLASS_SPECIAL" else None
    if def_key and defender.get(f"{def_key}_stage", 0) < 0:
        src = (defender.get("debuff_source") or {}).get(def_key)
        if src is not None:
            note_contribution(bstate, defender, (src[0], src[1]), "debuff")

    atk_key = "atk" if move_class == "CLASS_PHYSICAL" else "spa" if move_class == "CLASS_SPECIAL" else None
    if atk_key and defender["hp"] > 0 and attacker.get(f"{atk_key}_stage", 0) < 0:
        src = (attacker.get("debuff_source") or {}).get(atk_key)
        if src is not None:
            magnitude = src[3]
            stage_field = f"{atk_key}_stage"
            saved_stage = attacker[stage_field]
            attacker[stage_field] = saved_stage + magnitude
            try:
                would_dmg = compute_damage(attacker, defender, mv, weather_now(bstate), random.Random(0),
                                            is_crit=is_crit, roll=1.0, force_hit=True, bstate=bstate)[0]
            finally:
                attacker[stage_field] = saved_stage
            if would_dmg >= pre_hit_hp:
                note_contribution(bstate, attacker, (src[0], src[1]), "debuff")


_BATON_PASS_BUFF_STAGE_KEYS = ("atk_stage", "def_stage", "spa_stage", "spd_stage", "spe_stage", "acc_stage", "eva_stage")


def _baton_pass_is_buff(passed):
    """True if what a Baton Pass handed over is actually helpful to the receiver - a positive stat stage, Substitute, Aqua Ring,
    Ingrain, Focus Energy, Power Trick or an active Magnet Rise - not merely a Baton Pass carrying nothing (or only a hindrance like
    Leech Seed, confusion or Perish Song) along."""
    if any(passed.get(k, 0) > 0 for k in _BATON_PASS_BUFF_STAGE_KEYS):
        return True
    return bool(passed.get("substitute_hp", 0) > 0 or passed.get("aqua_ring") or passed.get("ingrain")
                or passed.get("focus_energy") or passed.get("power_trick") or passed.get("magnet_rise_turns", 0) > 0)


def note_baton_pass_support(bstate, passer, receiver, passed):
    """`passer` Baton Passed into `receiver`. If `passed` was actually a buff (see _baton_pass_is_buff), remember the passer so that a
    KO `receiver` scores while still carrying it earns the passer a "pass" assist (note_baton_pass_ko, called at the KO event)."""
    if not bstate or "side_of" not in bstate or not _baton_pass_is_buff(passed):
        return
    receiver["baton_pass_from"] = (bstate["side_of"](passer), _true_species(passer))


def note_baton_pass_ko(bstate, killer, killer_trainer):
    """`killer` just scored a KO (a real, move-attributed one - see the two ko_events.append call sites) for `killer_trainer`: if it
    still carries a Baton-Passed buff, the passer's species earns a "pass" assist too, rolling up into the Passer role."""
    if not bstate or killer_trainer is None:
        return
    passer = killer.get("baton_pass_from")
    if not passer:
        return
    bstate.setdefault("_analytics_assist_events", []).append({
        "trainer": killer_trainer, "species": passer[1], "categories": ["pass"],
        "victim_trainer": None, "victim_species": None, "turn": bstate.get("turn", 0),
    })


def resolve_faint_credit(bstate, victim, killer=None):
    """`victim` just fainted (once - a repeat call is ignored). `killer` is the mon that struck the final blow, or None for a passive faint;
    it gets the KO elsewhere (ko_events), so it is left out here. Every other contributing species gets one assist event carrying the
    categories it contributed (within ASSIST_WINDOW_TURNS, if set)."""
    if not bstate or victim.get("_faint_credited"):
        return
    victim["_faint_credited"] = True
    bstate["_faint_seq"] = victim["_ko_seq"] = bstate.get("_faint_seq", 0) + 1      # the order the faints happened in (see decide_double_ko)
    contributors, victim["contributors"] = victim.get("contributors") or {}, {}
    if not contributors or "side_of" not in bstate:
        return
    side = bstate["side_of"](victim)
    other = "b" if side == "a" else "a"
    keys = bstate.get("trainer_keys", {})
    if keys.get(other) is None:
        return
    killer_species = _true_species(killer) if killer is not None else None
    turn = bstate.get("turn", 0)
    events = bstate.setdefault("_analytics_assist_events", [])
    for species, cats in contributors.items():
        if species == killer_species:
            continue
        live = [c for c in ASSIST_CATEGORIES if c in cats and (ASSIST_WINDOW_TURNS is None or turn - cats[c] <= ASSIST_WINDOW_TURNS)]
        if "damage" in live and "debuff" in live and cats["damage"] == cats["debuff"]:
            # The same single hit both dealt damage and applied (or benefited from) a matching stat drop - one credit, not two.
            live.remove("damage")
        if live:
            events.append({"trainer": keys[other], "species": species, "categories": live,
                           "victim_trainer": keys.get(side), "victim_species": _true_species(victim), "turn": turn})


# ============================================================
# DOUBLE KO: who wins when both sides lose their last Pokemon in the same step
# ============================================================
# Retail (BattleControllerPlayer_CheckBattleOver) reports a DRAW when both sides are out at the same check, which a tournament cannot use, so the
# official double-KO rules decide instead. `resolve_faint_credit` numbers every faint in the order it happened (`_ko_seq`), and the HP losses the rules
# care about record their cause (`note_ko_cause`; the FIRST cause that takes a mon to 0 counts):
#   KO_CAUSE_RECOIL         the mon's own move finished it after it landed its hit (recoil, Struggle recoil, crash; Life Orb would be the same): its
#                           HP hit 0 second, so its side wins
#   KO_CAUSE_SUICIDE        Explosion / Self-Destruct / Memento / Healing Wish / Lunar Dance: the user's side loses
#   KO_CAUSE_RETALIATION    what the OPPONENT's Pokemon does after the hit - Rough Skin, Aftermath, Liquid Ooze (abilities), Destiny Bond: the owner's
#                           side wins the exchange
# anything else (a direct hit, end-of-turn damage) falls back on the order of the faints: the side whose last Pokemon fainted LATER wins. The end-of-turn
# steps run in speed order (Trick Room reversed) and stop the moment a side is out, exactly like retail's CheckBattleOver between steps, so "both faint
# at the end of the turn" (Sandstorm, poison, Perish Song) leaves the SLOWER one standing.
KO_CAUSE_RECOIL, KO_CAUSE_SUICIDE, KO_CAUSE_RETALIATION = "recoil", "suicide", "retaliation"


def note_ko_cause(mon, cause):
    """Call right after HP was taken from `mon`: if that brought it to 0 and no earlier cause is on record, remember why."""
    if mon["hp"] <= 0 and "_ko_cause" not in mon:
        mon["_ko_cause"] = cause


def decide_double_ko(party1, party2, rng):
    """Both parties are out. Returns ("a" | "b", reason): the winning side and a log line saying which rule decided it. `rng` is only used
    when the faints cannot be ordered at all (never in the engines, which number every faint)."""
    last = []
    for party in (party1, party2):
        dead = [m for m in party if m["hp"] <= 0]
        last.append(max(dead, key=lambda m: m.get("_ko_seq", 0)) if dead else None)
    mon_a, mon_b = last
    if mon_a is None or mon_b is None:
        return ("a" if rng.random() < 0.5 else "b"), "no Pokemon left to compare, decided by coin flip"
    for mon, other in ((mon_a, "b"), (mon_b, "a")):
        cause = mon.get("_ko_cause")
        if cause == KO_CAUSE_RETALIATION:
            return other, f"{mon['species_display']} fell to the opponent's ability / Destiny Bond: its owner wins the exchange"
    for mon, other in ((mon_a, "b"), (mon_b, "a")):
        if mon.get("_ko_cause") == KO_CAUSE_SUICIDE:
            return other, f"{mon['species_display']} fainted from its own self-destructing move: its user loses"
    for mon, own in ((mon_a, "a"), (mon_b, "b")):
        if mon.get("_ko_cause") == KO_CAUSE_RECOIL:
            return own, f"{mon['species_display']} fainted from its own recoil after landing the knockout: the attacker wins"
    seq_a, seq_b = mon_a.get("_ko_seq", 0), mon_b.get("_ko_seq", 0)
    if seq_a != seq_b:
        later = mon_a if seq_a > seq_b else mon_b
        return ("a" if seq_a > seq_b else "b"), f"{later['species_display']} fainted last"
    return ("a" if rng.random() < 0.5 else "b"), "the faints cannot be ordered, decided by coin flip"


def run_battle(trainer_a, trainer_b, seed=None, game_num=1):
    """trainer_a / trainer_b are the unique TRAINERS_DB keys (filenames,
    not display names - see load_trainers_from_repo). Display names are
    looked up just for the log text and the winner is returned as a key."""
    name_a = DISPLAY_NAMES.get(trainer_a, trainer_a)
    name_b = DISPLAY_NAMES.get(trainer_b, trainer_b)
    rng = random.Random(seed)
    _seed_rng_global(seed, trainer_a, trainer_b, game_num)
    t1_data, t2_data = TRAINERS_DB[trainer_a], TRAINERS_DB[trainer_b]
    # CRITICAL: must be a DEEP copy, not dict(p). t1_data["party"]/t2_data["party"]
    # are the same mon dicts stored in the module-level TRAINERS_DB, reused
    # across every game and every match a trainer plays for the whole
    # tournament. dict(p) only copies the top-level keys - nested mutable
    # values like move_pp (a dict) would still be the SAME object as the
    # master copy, so decrementing PP here would permanently drain the
    # master trainer's PP. The very next game (or the next match against a
    # different opponent) would then start with 0 PP left on every move and
    # be forced into Struggle for the entire battle. copy.deepcopy avoids
    # this by giving every game a fully independent party.
    party1 = [copy.deepcopy(p) for p in t1_data["party"]]
    party2 = [copy.deepcopy(p) for p in t2_data["party"]]
    idx1, idx2 = 0, 0
    active1, active2 = party1[idx1], party2[idx2]
    ai_a = t1_data.get("ai_flags", ["TRAINER_AI_BASIC"])
    ai_b = t2_data.get("ai_flags", ["TRAINER_AI_BASIC"])

    bstate = {
        "turn": 1, "weather": "NONE", "weather_turns": 0, "trick_room": 0, "gravity": 0, "last_move_used": None, "is_double_battle": False,
        "sides": {"a": new_side_state(), "b": new_side_state()},
        "trainer_keys": {"a": trainer_a, "b": trainer_b},
        "ai_items": {"a": new_ai_item_state(t1_data.get("items")), "b": new_ai_item_state(t2_data.get("items"))},
        "_analytics_secondary_roll_events": [],
        "_analytics_damaging_hit_events": [],
        "_analytics_assist_events": [],
    }
    bstate["side_of"] = lambda mon: "a" if any(mon is m for m in party1) else "b"     # identity, not ==: mirror matches have equal dicts
    bstate["all_actives"] = lambda: (active1, active2)
    bstate["slot_of"] = lambda mon: 0
    bstate["occupants"] = lambda: {("a", 0): active1, ("b", 0): active2}
    bstate["party_of"] = lambda mon: party1 if any(mon is m for m in party1) else party2

    def _alive(party):
        return any(p["hp"] > 0 for p in party)

    log = [f"=== GAME {game_num}: {name_a} vs {name_b} ===", ""]
    log.extend(format_team_roster_for_log(name_a, party1))
    log.append("")
    log.extend(format_team_roster_for_log(name_b, party2))
    log.append("")
    apply_entry_abilities(active1, active2, bstate, log)
    turns = 0
    # One dict per KO landed this game: {"species", "trainer", "move"} of
    # whoever landed the fainting blow - deliberately move-based faints
    # only (a Pokemon "landing a blow"), not passive end-of-turn faints
    # (Perish Song, poison, sandstorm, etc.) where there's no attacker to
    # credit. Feeds the species/individual-Pokemon/move "deadliest"
    # trackers built in run_tournament.
    ko_events = []
    while _alive(party1) and _alive(party2) and turns < MAX_BATTLE_TURNS:
        turns += 1
        bstate["turn"] = turns
        # Reset once per turn - Avalanche/Revenge check this to see if
        # the user was hit by the opponent EARLIER THIS SAME TURN.
        active1["_damage_taken_this_turn"] = 0
        active2["_damage_taken_this_turn"] = 0
        active1["_damage_taken_class_this_turn"] = None
        active2["_damage_taken_class_this_turn"] = None
        active1["_hits_taken"] = []
        active2["_hits_taken"] = []
        # Rotate last turn's hit-tracking forward - several voluntary-
        # switch conditions need "what type of damaging move hit me last
        # turn", which must mean the turn that JUST ended, not stale data
        # from further back if nothing hit this Pokemon since.
        active1["prev_turn_hit_type"] = active1.get("this_turn_hit_type")
        active1["this_turn_hit_type"] = None
        active2["prev_turn_hit_type"] = active2.get("this_turn_hit_type")
        active2["this_turn_hit_type"] = None
        cleanup_stale_links(bstate)
        log.append(f"--- Turn {turns} ---")
        log.append(f"{name_a}'s Lv. {active1['level']} {active1['species_display']} (HP: {max(0,active1['hp'])}/{active1['max_hp']}) vs "
                    f"{name_b}'s Lv. {active2['level']} {active2['species_display']} (HP: {max(0,active2['hp'])}/{active2['max_hp']})")

        # Snapshot of who's on the field as the turn BEGINS, before any
        # switching this turn - in the real games, both trainers pick
        # their action (a move or a switch) simultaneously, each unaware
        # of what the other is about to do. A trainer who chooses to
        # attack picks their move based on this starting matchup; if the
        # opponent then switches away before moves resolve, the
        # already-chosen move still executes and hits whoever ends up on
        # the field (see the actual target assignment further down,
        # which correctly uses the POST-switch active1/active2, not this
        # snapshot - only move CHOICE below should use it).
        turn_start_active1 = active1
        turn_start_active2 = active2

        # --- voluntary switching (Perish Song escape + hopeless-matchup) ---
        # Resolved before either side even considers a move - a switch
        # uses up the whole turn, same as in the real games, and clears
        # any active Perish Song countdown on the way out.
        switched_a = switched_b = False
        switch_idx_a = choose_switch(active1, active2, party1, idx1, rng, bstate=bstate)
        if switch_idx_a is not None:
            process_natural_cure(active1, log)
            active1["perish_song"] = 0
            clear_stockpile(active1)
            revert_mimicked_move(active1)
            revert_transform(active1)
            active1["cursed"] = False
            active1["yawn_turn"] = 0
            active1["nightmare"] = False
            active1["must_recharge"] = False
            active1["rampage_turns"] = 0
            active1["rampage_move"] = None
            active1["rollout_turns"] = 0
            active1["rollout_move"] = None
            active1["taunt_turns"] = 0
            active1["tormented"] = False
            active1["encore_turns"] = 0
            active1["encore_move"] = None
            active1["focus_energy"] = False
            active1["moves_used_this_stay"] = set()
            active1["embargo_turns"] = 0
            active1["grudge_active"] = False
            active1["trapped_turns"] = 0
            active1["vanished"] = None
            active1["imprison_moves"] = None
            active1["bide_turns"] = 0
            active1["bide_damage"] = 0
            old_species = active1["species_display"]
            idx1 = switch_idx_a
            active1 = party1[idx1]
            log.append(f"  {name_a} withdraws {old_species} and sends out {active1['species_display']}!")
            apply_entry_hazards(active1, bstate, "a")
            apply_switch_in_ability(active1, active2, bstate, log)
            switched_a = True
        else:
            use_a = ai_should_use_item(active1, party1, bstate["ai_items"]["a"], bstate)
            if use_a:
                apply_ai_item(active1, use_a, bstate, log, name_a)
                switched_a = True       # using an item costs the action, like a switch
        switch_idx_b = choose_switch(active2, active1, party2, idx2, rng, bstate=bstate)
        if switch_idx_b is not None:
            process_natural_cure(active2, log)
            active2["perish_song"] = 0
            clear_stockpile(active2)
            revert_mimicked_move(active2)
            revert_transform(active2)
            active2["cursed"] = False
            active2["yawn_turn"] = 0
            active2["nightmare"] = False
            active2["must_recharge"] = False
            active2["rampage_turns"] = 0
            active2["rampage_move"] = None
            active2["rollout_turns"] = 0
            active2["rollout_move"] = None
            active2["taunt_turns"] = 0
            active2["tormented"] = False
            active2["encore_turns"] = 0
            active2["encore_move"] = None
            active2["focus_energy"] = False
            active2["moves_used_this_stay"] = set()
            active2["embargo_turns"] = 0
            active2["grudge_active"] = False
            active2["trapped_turns"] = 0
            active2["vanished"] = None
            active2["imprison_moves"] = None
            active2["bide_turns"] = 0
            active2["bide_damage"] = 0
            old_species = active2["species_display"]
            idx2 = switch_idx_b
            active2 = party2[idx2]
            log.append(f"  {name_b} withdraws {old_species} and sends out {active2['species_display']}!")
            apply_entry_hazards(active2, bstate, "b")
            apply_switch_in_ability(active2, active1, bstate, log)
            switched_b = True
        else:
            use_b = ai_should_use_item(active2, party2, bstate["ai_items"]["b"], bstate)
            if use_b:
                apply_ai_item(active2, use_b, bstate, log, name_b)
                switched_b = True

        # A Pokemon that just switched in used its action switching, so it neither picks a move nor acts. Every other mon runs the
        # start-of-turn part (berry cure) and the AI picks its move WHATEVER its status: sleep, freeze, flinch, confusion, paralysis and
        # attraction are only checked when its action comes up (check_status_disruption, in the loop below), as in retail, where a mon
        # that is about to lose its turn has chosen first (and the choice fixes its place in the order). Only a recharging mon
        # (Battler_CanPickCommand) is not asked: its action is the recharge turn.
        picks_a, sm_a = (False, 1.0) if switched_a else process_status_start_turn(active1, rng, log, bstate)
        picks_b, sm_b = (False, 1.0) if switched_b else process_status_start_turn(active2, rng, log, bstate)
        recharging_a = not switched_a and not picks_a
        recharging_b = not switched_b and not picks_b
        move_a = choose_move(active1, turn_start_active2, ai_a, bstate, rng, count_other_alive_party_members(party1, idx1),
                              defender_other_alive_count=count_other_alive_party_members(party2, idx2), attacker_party=party1) if picks_a else None
        move_b = choose_move(active2, turn_start_active1, ai_b, bstate, rng, count_other_alive_party_members(party2, idx2),
                              defender_other_alive_count=count_other_alive_party_members(party1, idx1), attacker_party=party2) if picks_b else None

        mv_a_data = get_move_data_by_name(move_a) if move_a else None
        mv_b_data = get_move_data_by_name(move_b) if move_b else None
        prio_a = mv_a_data.get("priority", 0) if mv_a_data else (0 if recharging_a else -99)      # a recharging mon is locked into a priority-0 move
        prio_b = mv_b_data.get("priority", 0) if mv_b_data else (0 if recharging_b else -99)

        first = (active1, active2, name_a, move_a, ai_a, recharging_a)
        second = (active2, active1, name_b, move_b, ai_b, recharging_b)
        # BattleSystem_SortMonActionOrder: priority first, then the literal speed compare (Trick Room only reverses the speed
        # comparison within a priority bracket; Lagging Tail / Stall act last; an exact tie is a coin flip).
        if action_order_swap(active1, prio_a, active2, prio_b, bstate, rng):
            first, second = second, first

        # Mechanic C/D ("debuff"/"tailwind" turn-order-flip assists): stale notes from a mover that acted first last turn but never
        # scored a KO off it must not leak into this turn, so always clear before (maybe) setting a fresh one.
        active1.pop("_turn_order_credit", None)
        active2.pop("_turn_order_credit", None)
        if prio_a == prio_b:
            mover, opp_mon = first[0], second[0]
            note = {}
            spe_src = (opp_mon.get("debuff_source") or {}).get("spe")
            if spe_src is not None and opp_mon.get("spe_stage", 0) < 0:
                saved_spe = opp_mon["spe_stage"]
                opp_mon["spe_stage"] = saved_spe + spe_src[3]
                flipped = _speed_compare(mover, opp_mon, bstate) == "SLOWER"
                opp_mon["spe_stage"] = saved_spe
                if flipped:
                    note["debuff"] = (spe_src[0], spe_src[1])
            mover_side = bstate["side_of"](mover)
            if bstate["sides"][mover_side].get("tailwind", 0) > 0:
                saved_tw = bstate["sides"][mover_side]["tailwind"]
                bstate["sides"][mover_side]["tailwind"] = 0
                flipped = _speed_compare(mover, opp_mon, bstate) == "SLOWER"
                bstate["sides"][mover_side]["tailwind"] = saved_tw
                if flipped:
                    tw_setter = bstate["sides"][mover_side].get("tailwind_setter")
                    if tw_setter is not None:
                        note["tailwind"] = tw_setter
            if note:
                mover["_turn_order_credit"] = note

        for order_idx, (actor, target, actor_name, mv_name, actor_ai, recharging) in enumerate((first, second)):
            if actor["hp"] <= 0 or (mv_name is None and not recharging):
                continue
            if actor is not active1 and actor is not active2:
                # This mon was force-switched out (Roar/Whirlwind/U-turn/
                # Baton Pass) by an earlier action THIS SAME turn, before
                # its own turn came up - it doesn't get to act, same as
                # fainting.
                continue
            if target is not active1 and target is not active2:
                # The OPPONENT pivoted out (U-turn/Baton Pass) earlier
                # this turn - redirect to whichever Pokemon is now
                # actually active on that side rather than hitting a
                # stale, benched reference.
                target = active1 if bstate["side_of"](target) == "a" else active2
            moved_second = (order_idx == 1)

            # BEFORE_MOVE_STATE_STATUS_DISRUPTION comes before the target check, the PP charge and the move's own script: a mon that
            # loses its action to sleep / flinch / paralysis / ... pays no PP, and it still counts as having taken its turn.
            already_acted = actor.get("acted_since_switch_in", False)
            actor["acted_since_switch_in"] = True
            actor["_acted_turn"] = bstate.get("turn", 1)        # BattleSystem "moved this turn" (Zoom Lens, flinch, Sucker Punch)
            actor["destiny_bond"] = False                        # CHECK_STATUS_START
            actor["me_first"] = False
            if not check_status_disruption(actor, rng, log, mv_name, bstate):
                # A move attempt that is prevented outright invalidates the last-used-move tracker Copycat relies on (UpdateMoveBuffers).
                bstate["last_move_used"] = None
                actor["last_move_used"] = None
                continue
            if mv_name is None or target["hp"] <= 0:
                continue

            mv = get_effective_move_data(mv_name, actor, defender=target, bstate=bstate, rng=rng, moved_second=moved_second)

            # --- Two-turn semi-invulnerable moves: Fly/Dig/Dive/Bounce ---
            # Turn 1 just charges (no damage; see compute_damage's vanish
            # check for what can still hit it); turn 2 is forced to
            # continue the same move (see choose_move) and resolves as a
            # normal attack below.
            if mv.get("charge_move") and actor.get("vanished") != mv["charge_move"]:
                actor["move_hit"] = None
                log.append(f"  > {actor_name}'s {actor['species_display']} uses {mv_name.replace('MOVE_', '').replace('_', ' ').title()}!")
                actor.setdefault("moves_used_this_stay", set()).add(mv_name)
                if mv_name != "MOVE_STRUGGLE" and mv_name in actor.get("move_pp", {}):
                    actor["move_pp"][mv_name] = max(0, actor["move_pp"][mv_name] - 1)
                    apply_pressure_extra_pp(actor, mv, mv_name, [target])
                actor["vanished"] = mv["charge_move"]
                # Charging turn doesn't count as a valid last-used move
                # for Copycat's purposes - only the execution turn does.
                bstate["last_move_used"] = None
                actor["last_move_used"] = None
                verb = {"FLY": "flew up high", "DIG": "burrowed underground",
                        "DIVE": "hid underwater", "BOUNCE": "sprang up"}.get(mv["charge_move"], "vanished")
                log.append(f"    {actor['species_display']} {verb}!")
                continue
            if actor.get("vanished"):
                actor["vanished"] = None  # this IS turn 2 now - resolves normally below

            if mv.get("solar_charge") and weather_now(bstate) != "SUN" and not actor.get("charging_solar_beam"):
                actor["move_hit"] = None
                log.append(f"  > {actor_name}'s {actor['species_display']} uses {mv_name.replace('MOVE_', '').replace('_', ' ').title()}!")
                actor.setdefault("moves_used_this_stay", set()).add(mv_name)
                if mv_name != "MOVE_STRUGGLE" and mv_name in actor.get("move_pp", {}):
                    actor["move_pp"][mv_name] = max(0, actor["move_pp"][mv_name] - 1)
                    apply_pressure_extra_pp(actor, mv, mv_name, [target])
                actor["charging_solar_beam"] = True
                bstate["last_move_used"] = None
                actor["last_move_used"] = None
                log.append(f"    {actor['species_display']} took in sunlight!")
                continue
            if actor.get("charging_solar_beam"):
                actor["charging_solar_beam"] = None  # turn 2 (or sun is now up) - resolves normally below

            if bstate.get("snatchers") and mv.get("class") == "CLASS_STATUS" and mv.get("effect") != "SNATCH" \
                    and mv_name not in SNATCH_EXCLUDED_MOVES and actor not in bstate["snatchers"]:
                # Only the LAST (most recently added) waiting snatcher
                # catches it - since snatchers are appended in the order
                # they used Snatch (fastest first, as Snatch's own high
                # priority still resolves speed ties among snatchers
                # normally), the last one added is the SLOWEST of the
                # group, matching "only the slowest Snatch user ends up
                # with the stolen effect" without needing to simulate
                # the intermediate cascade of thefts explicitly.
                snatcher = bstate["snatchers"].pop()
                if snatcher["hp"] > 0:
                    original_user = actor
                    log.append(f"    {snatcher['species_display']} snatched {original_user['species_display']}'s move!")
                    if mv_name == "MOVE_PSYCH_UP":
                        target = original_user  # targets whoever it was stolen from
                    elif mv_name == "MOVE_ACUPRESSURE" or target is original_user:
                        target = snatcher  # self-targeted moves now apply to the new user instead
                    # else: a foe-targeted move (e.g. Toxic) keeps its original target
                    actor = snatcher
                    actor_name = name_a if actor is active1 else name_b

            log.append(f"  > {actor_name}'s {actor['species_display']} uses {mv_name.replace('MOVE_', '').replace('_', ' ').title()}!")
            note_move_used_on(actor, target, mv_name, mv)
            actor.setdefault("moves_used_this_stay", set()).add(mv_name)
            if not mv.get("copycat"):
                # Copycat needs to see whatever was the last-used move
                # BEFORE its own turn, so it deliberately doesn't
                # overwrite last_move_used here - see its own branch
                # below, which updates it correctly once it knows what
                # it actually executed as.
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name

            if mv_name != "MOVE_STRUGGLE" and mv_name in actor.get("move_pp", {}):
                actor["move_pp"][mv_name] = max(0, actor["move_pp"][mv_name] - 1)
                apply_pressure_extra_pp(actor, mv, mv_name, [target])

            mv_name, mv, _called_ok = resolve_called_move(actor, mv_name, mv, target, bstate, rng, log,
                                                          party1 if bstate["side_of"](actor) == "a" else party2,
                                                          target_selected=(move_b if actor is active1 else move_a))
            # --- preconditions that make a move fail outright before it
            # ever reaches the damage/effect resolution below ---
            precheck_failed = not _called_ok
            damp_blocked = bool(mv.get("self_destruct")) and _damp_blocks(actor, bstate)
            if damp_blocked:
                precheck_failed = True
                log.append(f"    {actor['species_display']} can't use {mv_name.replace('MOVE_', '').replace('_', ' ').title()} because of Damp!")
            if mv.get("sucker_punch"):
                opp_move_name = move_b if actor is active1 else move_a
                opp_mv = get_move_data_by_name(opp_move_name) if opp_move_name else None
                if not opp_mv or opp_mv.get("class") == "CLASS_STATUS" or opp_mv.get("power", 0) <= 0 \
                        or target.get("_acted_turn") == bstate.get("turn", 1):     # the target already took its turn
                    precheck_failed = True
            if mv.get("fake_out") and already_acted:
                precheck_failed = True
            if _real_effect(mv_name) == "BATTLE_EFFECT_DAMAGE_WHILE_ASLEEP" and actor.get("status") != "SLEEP":
                precheck_failed = True                           # Snore only works while the user is asleep
            if mv.get("class") == "CLASS_STATUS" and actor.get("taunt_turns", 0) > 0:
                # Taunt blocks status move SELECTION going forward (see
                # choose_move's own filtering), but a move already chosen
                # before Taunt landed this same turn - because both
                # sides pick simultaneously at the start of the turn -
                # still needs to fail here if the taunting side moved
                # first and just landed it.
                precheck_failed = True
            if mv.get("effect") == "FUTURE_SIGHT" and delayed_pending(bstate, target, "fs"):
                precheck_failed = True
            if mv.get("effect") == "WISH" and delayed_pending(bstate, actor, "wish"):
                precheck_failed = True
            if mv.get("effect") == "LAST_RESORT":
                known_moves = actor.get("moves", [])
                other_moves = [m for m in known_moves if m != "MOVE_LAST_RESORT"]
                used_this_stay = actor.get("moves_used_this_stay", set())
                if "MOVE_LAST_RESORT" not in known_moves or not other_moves or not all(m in used_this_stay for m in other_moves):
                    precheck_failed = True
            if mv.get("effect") == "NATURAL_GIFT":
                # Power and type come entirely from the user's held
                # berry - the berry is used up regardless of whether the
                # move actually connects, so it's consumed here rather
                # than only on a hit. Fails outright with no berry (or a
                # non-berry item, or a berry with no naturalGiftPower
                # defined for some reason), or if the user is under
                # Embargo (which blocks Fling/Natural Gift entirely,
                # separately from negating an item's own passive effect).
                if not item_effects_active(actor):
                    precheck_failed = True
                else:
                    ng_item = actor.get("item")
                    ng_info = get_item_info(ng_item) if ng_item else None
                    if not ng_item or not ng_info.get("is_berry") or ng_info.get("natural_gift_power", 0) <= 0:
                        precheck_failed = True
                    else:
                        mv = dict(mv, power=ng_info["natural_gift_power"], type=ng_info.get("natural_gift_type") or mv.get("type"))
                        actor["item"] = None
            if mv.get("effect") == "FLING":
                # Fling's power and secondary effect come entirely from
                # the user's held item (flingPower/flingEffect) - the
                # item is thrown away regardless of whether the throw
                # actually connects, so it's consumed here rather than
                # only on a hit. FLING_EFFECT_FLINCH is handled through
                # the ordinary secondary-effect dispatch below (like any
                # other move's flinch chance); the four status effects
                # map onto this engine's own status names directly.
                # Embargo blocks Fling entirely, same as Natural Gift.
                if not item_effects_active(actor):
                    precheck_failed = True
                else:
                    fling_item = actor.get("item")
                    if not fling_item:
                        precheck_failed = True
                    else:
                        item_info = get_item_info(fling_item)
                        fling_power = item_info.get("fling_power", 0)
                        fling_effect = item_info.get("fling_effect", "FLING_EFFECT_NONE")
                        actor["item"] = None
                        if fling_power <= 0:
                            precheck_failed = True
                        else:
                            status_map = {"FLING_EFFECT_BURN": "BURN", "FLING_EFFECT_PARALYZE": "PARALYZE",
                                          "FLING_EFFECT_POISON": "POISON", "FLING_EFFECT_BADLY_POISON": "TOXIC"}
                            new_mv = dict(mv, power=fling_power)
                            if fling_effect == "FLING_EFFECT_FLINCH":
                                new_mv["secondary"] = {"effect": "FLINCH", "chance": 1.0}
                            elif fling_effect in status_map:
                                new_mv["secondary"] = {"effect": status_map[fling_effect], "chance": 1.0}
                            mv = new_mv
            if mv.get("effect") in ("COUNTER", "MIRROR_COAT", "METAL_BURST"):
                # These retaliate against damage actually taken THIS turn
                # (reset at turn start, so a faster user - relevant for
                # Metal Burst's normal priority - hasn't taken any yet).
                # Counter/Mirror Coat require the matching damage class;
                # Metal Burst accepts either. The tracking field only
                # updates when a hit lands on the user's own HP (a
                # Substitute absorbing it doesn't count), which already
                # gives Metal Burst its "fails if a Substitute absorbed
                # the hit" behavior for free. Computing the retaliation
                # amount as a fixed_damage override lets it flow through
                # compute_damage's existing fixed-damage path below,
                # which already checks type immunity (Ghost vs Counter,
                # Dark vs Mirror Coat) before applying it, and reuses the
                # normal application/fainting/KO-tracking code rather
                # than duplicating any of it here.
                _cs = counter_source(actor, mv["effect"], bstate)
                if _cs is None:
                    precheck_failed = True
                else:
                    target = _cs[0]
                    # power must be set to something nonzero too - compute_damage
                    # itself ignores power for a fixed_damage move, but the
                    # dispatch code below gates whether the returned damage
                    # gets applied/logged at all on mv.get("power", 0) > 0.
                    mv = dict(mv, fixed_damage=max(1, _cs[1]), power=1)
            if mv.get("copycat"):
                # Copycat becomes whatever move was last validly used
                # anywhere in the battle (even by the user itself) -
                # substituting mv/mv_name here lets the rest of this
                # dispatch (the precondition checks below, Bide/multi-hit/
                # normal damage, and the separate status-effect
                # application after it) run exactly as if the user had
                # chosen that move directly, including its own accuracy,
                # type, and effects. Fails outright if nothing valid has
                # been used yet this battle. The move that gets executed
                # becomes the new last-used move, same as any other move.
                last_move = bstate.get("last_move_used")
                if not last_move:
                    precheck_failed = True
                else:
                    mv = get_effective_move_data(last_move, actor, defender=target, bstate=bstate, rng=rng)
                    mv_name = last_move
                    bstate["last_move_used"] = mv_name
                    actor["last_move_used"] = mv_name

            if mv.get("effect") == "SLEEP_TALK":
                # Substituting mv/mv_name here (same mechanism as
                # Copycat above) lets the called move's own accuracy,
                # type, and effects resolve normally below - but unlike
                # every other path into this dispatch, the PP deduction
                # for the CALLED move is deliberately skipped entirely:
                # Sleep Talk's own PP was already deducted earlier
                # (before this precondition section runs), and the real
                # mechanic explicitly allows calling a move with 0 PP
                # left, so the called move's own PP is never touched.
                eligible = [m for m in actor.get("moves", []) if m not in SLEEP_TALK_EXCLUDED_MOVES]
                if actor.get("status") != "SLEEP" or not eligible:      # effect script: CompareMonData FLAG_NOT sleep -> failed
                    precheck_failed = True
                else:
                    called_move = rng.choice(eligible)
                    mv = get_effective_move_data(called_move, actor, defender=target, bstate=bstate, rng=rng)
                    mv_name = called_move
                    bstate["last_move_used"] = mv_name
                    actor["last_move_used"] = mv_name
                    log.append(f"    {actor['species_display']}'s Sleep Talk called "
                               f"{called_move.replace('MOVE_', '').replace('_', ' ').title()}!")

            if precheck_failed:
                log.append("    But it failed!")
                missed = True
            elif mv.get("effect") == "FUTURE_SIGHT":
                if not start_future_sight(actor, target, mv, mv_name, bstate, rng, log):
                    log.append("    But it failed!")
                missed = True
            elif mv.get("effect") == "WISH":
                if not start_wish(actor, bstate, log):
                    log.append("    But it failed!")
                missed = True
            elif mv.get("effect") == "TRANSFORM":
                if target.get("vanished"):
                    log.append("    But it failed!")
                else:
                    if not actor.get("pre_transform"):
                        # Only backed up once - if the user is somehow
                        # already Transformed and Transforms again, it
                        # should copy the NEW target starting from its
                        # own true original stats, not compound onto
                        # whatever it's currently copying.
                        actor["pre_transform"] = {
                            "species": actor.get("species"), "species_display": actor.get("species_display"),
                            "type1": actor.get("type1"), "type2": actor.get("type2"), "types": list(actor.get("types", [])),
                            "ability": actor.get("ability"), "atk": actor.get("atk"), "def": actor.get("def"),
                            "spa": actor.get("spa"), "spd": actor.get("spd"), "spe": actor.get("spe"),
                            "atk_stage": actor.get("atk_stage", 0), "def_stage": actor.get("def_stage", 0),
                            "spa_stage": actor.get("spa_stage", 0), "spd_stage": actor.get("spd_stage", 0),
                            "spe_stage": actor.get("spe_stage", 0), "acc_stage": actor.get("acc_stage", 0),
                            "eva_stage": actor.get("eva_stage", 0),
                            "moves": list(actor.get("moves", [])), "move_pp": dict(actor.get("move_pp", {})),
                        }
                    actor["species"] = target.get("species")
                    actor["species_display"] = target.get("species_display")
                    actor["type1"] = target.get("type1")
                    actor["type2"] = target.get("type2")
                    actor["types"] = list(target.get("types", []))
                    actor["ability"] = target.get("ability")
                    ai_reveal_ability(actor)
                    actor["atk"] = target.get("atk")
                    actor["def"] = target.get("def")
                    actor["spa"] = target.get("spa")
                    actor["spd"] = target.get("spd")
                    actor["spe"] = target.get("spe")
                    actor["atk_stage"] = target.get("atk_stage", 0)
                    actor["def_stage"] = target.get("def_stage", 0)
                    actor["spa_stage"] = target.get("spa_stage", 0)
                    actor["spd_stage"] = target.get("spd_stage", 0)
                    actor["spe_stage"] = target.get("spe_stage", 0)
                    actor["acc_stage"] = target.get("acc_stage", 0)
                    actor["eva_stage"] = target.get("eva_stage", 0)
                    new_moves = list(target.get("moves", []))
                    actor["moves"] = new_moves
                    new_pp = {}
                    for m in new_moves:
                        max_pp = get_move_data_by_name(m).get("pp", 5)
                        new_pp[m] = min(5, max_pp)
                    actor["move_pp"] = new_pp
                    actor["transformed"] = True
                    log.append(f"    {actor['species_display']} transformed into {target['species_display']}!")
                missed = True
            elif mv.get("effect") == "PAIN_SPLIT":
                if target.get("vanished") or _substituted(target):        # the script opens with CheckSubstitute
                    log.append("    But it failed!")
                else:
                    shared_hp = (actor["hp"] + target["hp"]) // 2
                    actor["hp"] = min(actor["max_hp"], shared_hp)
                    target["hp"] = min(target["max_hp"], shared_hp)
                    log.append(f"    {actor['species_display']} shared its pain with {target['species_display']}!")
                missed = True
            elif mv.get("mimic"):
                # Mimic: copies the TARGET's own last used move into the
                # user's Mimic slot at 5 PP (separate from whatever PP
                # Mimic itself has left), kept until the user faints,
                # switches out, or the battle ends - see the switch-out/
                # faint-replacement reset lists for where it's cleared.
                # Fails against Sketch/Struggle/Metronome/Chatter, a move
                # the user already knows, or (Gen3+) a target currently
                # semi-invulnerable (Fly/Dig mid-flight) - otherwise it
                # always hits, no accuracy check at all.
                target_move = target.get("last_move_used")
                mimic_idx = actor["moves"].index("MOVE_MIMIC") if "MOVE_MIMIC" in actor.get("moves", []) else None
                if (target.get("vanished") or not target_move or target_move in MIMIC_EXCLUDED_MOVES
                        or target_move in actor.get("moves", []) or mimic_idx is None):
                    log.append("    But it failed!")
                else:
                    actor["moves"][mimic_idx] = target_move
                    actor["move_pp"][target_move] = 5
                    actor["mimic_active_move"] = target_move
                    copied_display = target_move.replace("MOVE_", "").replace("_", " ").title()
                    log.append(f"    {actor['species_display']} learned {copied_display}!")
                missed = True
            elif mv.get("bide"):
                # Bide: charges for 2 turns (self-targeting, so the
                # opponent's Protect can't interrupt the charge), then
                # releases 2x whatever damage it took across those two
                # turns - THAT hit can be Protected against normally.
                if actor.get("bide_turns", 0) <= 0:
                    actor["bide_turns"] = 2
                    actor["bide_damage"] = 0
                    log.append(f"    {actor['species_display']} is storing energy!")
                    missed = True
                else:
                    actor["bide_turns"] -= 1
                    if actor["bide_turns"] > 0:
                        log.append(f"    {actor['species_display']} is storing energy!")
                        missed = True
                    else:
                        # The final Bide turn doesn't count as a valid
                        # last-used move for Copycat's purposes, even
                        # though it just showed "uses Bide!" like normal.
                        bstate["last_move_used"] = None
                        actor["last_move_used"] = None
                        bide_dmg = actor.get("bide_damage", 0)
                        actor["bide_damage"] = 0
                        if target.get("protected") and mv.get("can_be_protected", True):
                            log.append("    Protected!")
                            missed = True
                        elif bide_dmg <= 0 or target["hp"] <= 0:
                            log.append("    But it failed!")
                            missed = True
                        else:
                            bide_eff = get_type_effectiveness("TYPE_NORMAL", actor, target, gravity=bstate.get("gravity", 0) > 0)
                            if bide_eff == 0.0:
                                log.append("    It had no effect.")
                                missed = True
                            else:
                                release_dmg = max(1, bide_dmg * 2)
                                missed = False
                                if target.get("substitute_hp", 0) > 0:
                                    absorbed = min(target["substitute_hp"], release_dmg)
                                    target["substitute_hp"] -= absorbed
                                    log.append(f"    {actor['species_display']} unleashed its energy! The Substitute took {absorbed} damage!")
                                else:
                                    target["hp"] -= release_dmg
                                    _record_damaging_hit_event(bstate, target, actor)
                                    log.append(f"    {actor['species_display']} unleashed its energy! Dealt {release_dmg} damage!")
            elif target.get("protected") and mv.get("can_be_protected", True) and not mv.get("protect"):
                log.append("    Protected!")
                missed = True  # treated as "didn't connect" for the dispatch logic below
            elif mv.get("multihit") or mv.get("multihit_fixed"):
                # --- multi-hit moves (Fury Swipes, Double Kick, etc.) ---
                # Accuracy is checked ONCE for the whole use (force_hit=True
                # on every hit after the first): if it connects at all,
                # every subsequent hit in the same use is guaranteed to
                # land too. Each hit still gets its own crit roll, damage
                # roll, secondary-effect chance, and contact-ability
                # trigger, and the sequence stops early if the target (or
                # the user, via a contact ability like Rough Skin) faints
                # partway through.
                num_hits = mv["multihit_fixed"] if mv.get("multihit_fixed") else (5 if has_ability(actor, "SKILL_LINK") else roll_multihit_count(rng))
                hits_landed = 0
                total_dmg = 0
                any_crit = False
                last_eff = 1.0
                missed = False
                for hit_i in range(num_hits):
                    dmg, is_crit, eff, missed_this = compute_damage(actor, target, mv, weather_now(bstate), rng, force_hit=(hit_i > 0), bstate=bstate, log=log)
                    if hit_i == 0 and missed_this:
                        missed = True
                        break
                    last_eff = eff
                    if eff == 0.0:
                        break
                    if target.get("substitute_hp", 0) > 0:
                        absorbed = min(target["substitute_hp"], dmg)
                        target["substitute_hp"] -= absorbed
                        total_dmg += absorbed
                    else:
                        pre_hit_hp_this = target["hp"]
                        target["hp"] -= dmg
                        total_dmg += dmg
                        _record_damaging_hit_event(bstate, target, actor)
                        note_stat_drop_ko_assists(bstate, actor, target, mv, dmg, pre_hit_hp_this, is_crit, rng)
                        target["_damage_taken_this_turn"] = target.get("_damage_taken_this_turn", 0) + dmg
                        target["_damage_taken_class_this_turn"] = mv.get("class", "CLASS_PHYSICAL")
                        note_hit_taken(target, actor, dmg, mv)
                        target["this_turn_hit_type"] = mv.get("type", "TYPE_NORMAL")
                        if target.get("bide_turns", 0) > 0:
                            target["bide_damage"] = target.get("bide_damage", 0) + dmg
                    hits_landed += 1
                    any_crit = any_crit or is_crit
                    _anger_point(target, is_crit, log)

                    _apply_secondary_effects(actor, target, mv, bstate, rng, log)
                    _apply_contact_abilities(actor, target, mv, rng, log, bstate)

                    if target["hp"] <= 0 or actor["hp"] <= 0:
                        break

                if missed:
                    log.append("    Attack missed!")
                elif hits_landed == 0:
                    log.append("    It had no effect.")
                else:
                    msg = f"    Hit {hits_landed} time{'s' if hits_landed != 1 else ''}! Dealt {total_dmg} damage total!"
                    if any_crit:
                        msg += " At least one critical hit!"
                    if last_eff > 1.0:
                        msg += " Super effective!"
                    elif 0 < last_eff < 1.0:
                        msg += " Not very effective..."
                    log.append(msg)
            else:
                dmg, is_crit, eff, missed = compute_damage(actor, target, mv, weather_now(bstate), rng, bstate=bstate, log=log)
                if missed:
                    log.append("    Attack missed!")
                elif mv.get("class") != "CLASS_STATUS" and mv.get("power", 0) > 0:
                    if eff == 0.0:
                        log.append("    It had no effect.")
                    else:
                        if target.get("substitute_hp", 0) > 0:
                            absorbed = min(target["substitute_hp"], dmg)
                            target["substitute_hp"] -= absorbed
                            log.append(f"    The Substitute took {absorbed} damage!")
                            if mv.get("struggle_recoil"):
                                _struggle_recoil(actor, log)            # MOVE_SIDE_EFFECT_ON_HIT: a Substitute hit counts
                        else:
                            pre_hit_hp = target["hp"]
                            target["hp"] -= dmg
                            _record_damaging_hit_event(bstate, target, actor)
                            note_stat_drop_ko_assists(bstate, actor, target, mv, dmg, pre_hit_hp, is_crit, rng)
                            target["_damage_taken_this_turn"] = target.get("_damage_taken_this_turn", 0) + dmg
                            target["_damage_taken_class_this_turn"] = mv.get("class", "CLASS_PHYSICAL")
                            note_hit_taken(target, actor, dmg, mv)
                            target["this_turn_hit_type"] = mv.get("type", "TYPE_NORMAL")
                            inflicted = min(dmg, max(0, pre_hit_hp))  # actual HP lost, capped - see below
                            if target.get("bide_turns", 0) > 0:
                                target["bide_damage"] = target.get("bide_damage", 0) + inflicted
                            msg = f"    Dealt {dmg} damage!"
                            if is_crit:
                                msg += " Critical hit!"
                            if eff > 1.0:
                                msg += " Super effective!"
                            elif 0 < eff < 1.0:
                                msg += " Not very effective..."
                            log.append(msg)
                            _anger_point(target, is_crit, log)
                            if mv.get("effect") == "PLUCK" and target["hp"] > 0 and not (has_ability(target, "STICKY_HOLD") and not has_ability(actor, "MOLD_BREAKER")):
                                # Pluck: eating the target's berry only
                                # reaches here at all when the hit landed
                                # on the target's real HP rather than a
                                # Substitute (this whole branch is
                                # already gated on that), and the berry's
                                # effect applies regardless of whether
                                # its own normal trigger condition (e.g.
                                # Sitrus needing <=50% HP) is actually
                                # met - matching Liechi/Sitrus-style
                                # berries always being eaten when Pluck
                                # connects.
                                target_item_info = get_item_info(target.get("item"))
                                if target_item_info.get("is_berry"):
                                    eaten = eat_berry(actor, holder=target)
                                    if eaten:
                                        log.append(f"    {actor['species_display']} plucked and ate {target['species_display']}'s {eaten}!")
                            # Recoil and drain are based on the damage actually
                            # inflicted on the target - capped at whatever HP
                            # it had left before this hit - not the raw
                            # theoretical damage the move would have dealt
                            # against a tougher target. A hit that would deal
                            # 484 to a 21-HP target only actually inflicts (and
                            # recoils/drains off) 21, not 484.
                            if mv.get("drain") and actor["hp"] > 0:
                                _apply_drain(actor, target, inflicted, mv["drain"], log)
                            if mv.get("struggle_recoil"):
                                _struggle_recoil(actor, log)
                            elif mv.get("recoil") and not has_ability(actor, "ROCK_HEAD") and not has_ability(actor, "MAGIC_GUARD"):
                                move_recoil_dmg = max(1, int(inflicted * mv["recoil"]))
                                actor["hp"] -= move_recoil_dmg
                                actor["_damage_taken_this_turn"] = actor.get("_damage_taken_this_turn", 0) + move_recoil_dmg
                                note_ko_cause(actor, KO_CAUSE_RECOIL)
                                log.append(f"    {actor['species_display']} was hurt by recoil! (-{move_recoil_dmg} HP)")

                            _apply_secondary_effects(actor, target, mv, bstate, rng, log)
                            _apply_contact_abilities(actor, target, mv, rng, log, bstate)

            # status/stat-changing effects apply even on a 0-power status move
            if mv.get("class") == "CLASS_STATUS" and not missed:
                apply_move_effect(mv, actor, target, bstate, rng, log)
            elif mv.get("protect") or mv.get("substitute"):
                apply_move_effect(mv, actor, target, bstate, rng, log)
            elif mv.get("effect") == "SPIT_UP" and not missed:
                # Spit Up deals real damage (handled above like any
                # other attack) but ALSO needs its stockpile-consuming
                # side effect applied, same as Swallow.
                apply_move_effect(mv, actor, target, bstate, rng, log)
            elif mv.get("effect") == "ENDEAVOR" and not missed:
                apply_move_effect(mv, actor, target, bstate, rng, log)
            elif mv.get("stat_changes") and not missed:
                # A damaging move with its own GUARANTEED (not chance-
                # based - that's "secondary"/"secondaries", handled
                # separately below) stat change: Close Combat/Superpower/
                # Hammer Arm dropping the user's own Def/Spe, Overheat/
                # Draco Meteor/Leaf Storm/Psycho Boost dropping the
                # user's own SpA. None of these are CLASS_STATUS, so
                # without this branch they'd silently never apply.
                apply_move_effect(mv, actor, target, bstate, rng, log)

            # Whirlwind/Roar: forces the target to switch to a random other
            # party member. Handled directly here (not via
            # apply_move_effect) since it needs the target's actual party
            # list and active index, not just its own Pokemon dict.
            if mv.get("effect") == "FORCE_SWITCH" and not missed and target["hp"] > 0:
                if target.get("substitute_hp", 0) > 0:
                    log.append("    But it failed against the Substitute!")
                elif (has_ability(target, "SUCTION_CUPS") and not has_ability(actor, "MOLD_BREAKER")) or target.get("ingrain"):
                    log.append(f"    {target['species_display']} anchors itself!")
                else:
                    side = bstate["side_of"](target)
                    t_party = party1 if side == "a" else party2
                    t_idx = idx1 if side == "a" else idx2
                    new_idx = perform_forced_switch(t_party, t_idx, rng)
                    if new_idx is None:
                        log.append(f"    But it failed! {target['species_display']} has nowhere to switch to.")
                    else:
                        process_natural_cure(target, log)
                        target["perish_song"] = 0
                        clear_stockpile(target)
                        target["cursed"] = False
                        target["yawn_turn"] = 0
                        target["nightmare"] = False
                        target["must_recharge"] = False
                        target["rampage_turns"] = 0
                        target["rampage_move"] = None
                        target["rollout_turns"] = 0
                        target["rollout_move"] = None
                        target["taunt_turns"] = 0
                        target["tormented"] = False
                        target["encore_turns"] = 0
                        target["encore_move"] = None
                        target["focus_energy"] = False
                        target["moves_used_this_stay"] = set()
                        target["embargo_turns"] = 0
                        target["grudge_active"] = False
                        target["trapped_turns"] = 0
                        target["vanished"] = None
                        target["imprison_moves"] = None
                        target["bide_turns"] = 0
                        target["bide_damage"] = 0
                        old_species = target["species_display"]
                        revert_mimicked_move(target)                  # retail rebuilds a mon from its party data when it is sent out again: Transform / Mimic do not survive a Roar either
                        revert_transform(target)
                        if side == "a":
                            idx1 = new_idx
                            active1 = party1[idx1]
                            new_mon, disp_name = active1, name_a
                        else:
                            idx2 = new_idx
                            active2 = party2[idx2]
                            new_mon, disp_name = active2, name_b
                        log.append(f"    {old_species} was blown away! {disp_name} sent out {new_mon['species_display']}!")
                        apply_entry_hazards(new_mon, bstate, side)
                        apply_switch_in_ability(new_mon, actor, bstate, log)

            use_held_item(actor, log)                        # AFTER_MOVE_EFFECT_ATTACKER_ITEM, then DEFENDER_ITEM: after EVERY move, hit or not
            if target is not actor:
                use_held_item(target, log)

            # --- Pivoting moves: U-turn/Baton Pass switch the ACTOR out ---
            # after everything above has resolved (Baton Pass also carries
            # stat stages and an active Substitute to the replacement).
            # Unlike a normal voluntary switch, pivot moves (Baton Pass,
            # U-turn, Volt Switch, Flip Turn, Parting Shot) explicitly
            # bypass trapping abilities (Arena Trap/Magnet Pull/Shadow
            # Tag) and always switch out regardless.
            if mv.get("pivot") and actor["hp"] > 0:
                p_side = bstate["side_of"](actor)
                p_party = party1 if p_side == "a" else party2
                p_idx = idx1 if p_side == "a" else idx2
                new_idx = select_switch_in_target(p_party, [p_idx], target, bstate, rng)
                if new_idx is not None:
                    passed = baton_state(actor) if mv.get("baton_pass") else None
                    old_mon, old_species = actor, actor["species_display"]
                    process_natural_cure(actor, log)
                    for reset_key, reset_val in (("perish_song", 0), ("cursed", False), ("yawn_turn", 0),
                                                  ("nightmare", False), ("must_recharge", False), ("rampage_turns", 0),
                                                  ("rampage_move", None), ("rollout_turns", 0), ("rollout_move", None),
                                                  ("taunt_turns", 0), ("tormented", False), ("encore_turns", 0), ("encore_move", None), ("focus_energy", False), ("trapped_turns", 0), ("vanished", None), ("moves_used_this_stay", set()), ("embargo_turns", 0), ("grudge_active", False),
                                                  ("imprison_moves", None), ("bide_turns", 0), ("bide_damage", 0)):
                        actor[reset_key] = reset_val
                    clear_stockpile(actor)
                    revert_mimicked_move(actor)
                    revert_transform(actor)
                    if p_side == "a":
                        idx1 = new_idx
                        active1 = p_party[idx1]
                        new_mon, disp_name = active1, name_a
                    else:
                        idx2 = new_idx
                        active2 = p_party[idx2]
                        new_mon, disp_name = active2, name_b
                    new_mon["acted_since_switch_in"] = False
                    if mv.get("baton_pass"):
                        log.append(f"    {old_species} passed the baton to {new_mon['species_display']}!")
                    else:
                        log.append(f"    {old_species} came back! {disp_name} sent out {new_mon['species_display']}!")
                    apply_entry_hazards(new_mon, bstate, p_side)
                    if passed is not None:
                        apply_baton_state(new_mon, passed, old_mon, bstate)
                        note_baton_pass_support(bstate, old_mon, new_mon, passed)
                    apply_switch_in_ability(new_mon, target, bstate, log)

            # --- Crash damage: High Jump Kick/Jump Kick lose 1/2 max HP
            # if they miss OR are blocked by Protect ---
            if mv.get("crash") and missed and actor["hp"] > 0:
                _crash_damage(actor, target, mv, bstate, rng, log)

            # --- Explosion/Self-Destruct: the user faints no matter what,
            # hit, miss, or Protect ---
            if mv.get("self_destruct") and actor["hp"] > 0 and not damp_blocked:
                actor["hp"] = 0
                note_ko_cause(actor, KO_CAUSE_SUICIDE)
                log.append(f"    {actor['species_display']} exploded!")

            # --- Binding moves: trap the target for 2-5 turns with
            # residual damage each end of turn (see process_status_end_turn) ---
            if mv.get("binding") and not missed and target["hp"] > 0 and target.get("trapped_turns", 0) <= 0:
                target["trapped_turns"] = _bind_counter(actor, rng)
                target["trapped_by_species"] = actor["species_display"]
                log.append(f"    {target['species_display']} became trapped!")

            # --- Recharge moves: Hyper Beam/Giga Impact force a skipped
            # turn next, but ONLY if the move actually connected. This
            # was true unconditionally in Gen 1, but from Gen 2 onward
            # (including Gen 4) a miss or a Protect block means no
            # recharge is needed - "missed" is already True for both of
            # those cases (see the dispatch logic above), so this one
            # check covers both.
            if mv.get("recharge") and actor["hp"] > 0 and not missed:
                actor["must_recharge"] = True

            # --- Locked rampage moves: Outrage/Petal Dance/Thrash lock
            # the user into repeating this same move for 2-3 turns (fixed
            # at first use, regardless of hits/misses along the way), then
            # confuse it once the lock ends ---
            if mv.get("rampage") and actor["hp"] > 0:
                if actor.get("rampage_turns", 0) <= 0:
                    actor["rampage_turns"] = rng.choice([2, 3])
                    actor["rampage_move"] = mv_name
                actor["rampage_turns"] -= 1
                if actor["rampage_turns"] <= 0:
                    actor["rampage_move"] = None
                    rampage_fatigue(actor, rng, log)

            # --- Rollout/Ice Ball: locked in for up to 5 uses, doubling
            # power each time (see get_effective_move_data) - a miss ends
            # the lock early, unlike rampage moves ---
            if mv.get("rollout") and actor["hp"] > 0:
                if not actor.get("rollout_move"):
                    actor["rollout_move"] = mv_name
                    actor["rollout_turns"] = 0
                actor["rollout_turns"] += 1
                if missed or actor["rollout_turns"] >= 5:
                    actor["rollout_move"] = None
                    actor["rollout_turns"] = 0

            check_white_herb(actor, log)
            check_white_herb(target, log)

            if actor.get("grudge_active") and mv.get("effect") != "GRUDGE":
                actor["grudge_active"] = False
            if actor.get("charged") and not mv.get("charges_electric"):
                actor["charged"] = False

            if target["hp"] <= 0:
                target["hp"] = 0
                log.append(f"  X {target['species_display']} fainted!\n")
                target["_fainted_already_logged"] = True
                for category, src in (actor.pop("_turn_order_credit", None) or {}).items():
                    note_contribution(bstate, target, src, category)
                resolve_faint_credit(bstate, target, actor)
                if target.get("grudge_active") and mv_name != "MOVE_STRUGGLE" and mv_name in actor.get("move_pp", {}):
                    actor["move_pp"][mv_name] = 0
                    move_display = mv_name.replace("MOVE_", "").replace("_", " ").title()
                    log.append(f"    {actor['species_display']}'s {move_display} lost all its PP due to the grudge!")
                revert_mimicked_move(target)
                revert_transform(target)
                if target.get("destiny_bond") and actor["hp"] > 0:
                    actor["hp"] = 0                                 # subscript_faint_check_destiny_bond
                    note_ko_cause(actor, KO_CAUSE_RETALIATION)
                    log.append(f"    {target['species_display']} took {actor['species_display']} down with it!")
                _aftermath(actor, target, mv_name, bstate, log)
                ko_events.append({
                    "species": actor["species"],
                    "trainer": trainer_a if bstate["side_of"](actor) == "a" else trainer_b,
                    "move": mv_name,
                    "victim_species": target["species"],
                    "victim_trainer": trainer_b if bstate["side_of"](actor) == "a" else trainer_a,
                })
                note_baton_pass_ko(bstate, actor, trainer_a if bstate["side_of"](actor) == "a" else trainer_b)
                process_natural_cure(actor, log)
                process_natural_cure(target, log)
                # Gen4 changed this from Gen3: a fainted mon's replacement - whether it died mid-turn to a direct
                # hit (here) or during the end-of-turn phase to residual damage (see the post-EOT block below) - is
                # ALWAYS sent out only after the ENTIRE end-of-turn sequence finishes for the turn it fainted in
                # (Smogon's end-of-turn ordering: screens/Wish/weather/Gravity/Leftovers-orbs-status-damage/Perish
                # Song/Future Sight/Trick Room all resolve first, THEN "Pokemon is switched in" is its own final
                # step). So no replacement happens here - target/active1/active2 just stay pointing at the fainted
                # (hp==0) mon for the rest of this turn, exactly like an actor fainting to its own recoil/Explosion
                # already does today (there's no inline-replace block for that case either). The post-EOT block is
                # the only place replacement happens now, for both this case and the EOT-phase-faint case alike.
                break

            if not (_alive(party1) and _alive(party2)):      # BattleControllerPlayer_MoveEnd -> CheckBattleOver: nothing else happens this turn
                break

        active1["protected"] = False
        active2["protected"] = False
        active1["flinched"] = active2["flinched"] = False       # BattleSystem_SetupNextTurn: a flinch lasts only for its own turn
        bstate["snatchers"] = []
        # Retail runs each end-of-turn step for the battlers in SPEED order (monSpeedOrder; Trick Room reversed) and re-checks the battle
        # (CheckBattleOver) between steps: once a side is out the battle is over and the survivor is not touched by the steps still to come.
        over = lambda: not (_alive(party1) and _alive(party2))
        eot = [(active1, active2), (active2, active1)]
        if action_order_swap(active1, 0, active2, 0, bstate, rng):
            eot.reverse()
        for mon, _foe in eot:
            if not over():
                process_weather_end_turn(mon, bstate, log)
        if bstate.get("pending_weather"):
            bstate["weather"], bstate["weather_turns"] = bstate.pop("pending_weather")
        if not over():
            resolve_delayed_moves_end_turn(bstate, log, rng)
        for mon, foe in eot:
            if mon["hp"] > 0 and not over():
                process_status_end_turn(mon, foe, bstate, log)
        for mon, _foe in eot:
            if not over():
                process_end_of_turn_abilities(mon)
        side_names = {"a": name_a, "b": name_b}
        for side_key, side in bstate["sides"].items():
            for key in ("reflect", "light_screen", "tailwind"):
                if side[key] > 0:
                    side[key] -= 1
            if side.get("mist", 0) > 0:
                side["mist"] -= 1
                if side["mist"] == 0:
                    log.append(f"    {side_names[side_key]}'s team is no longer protected by Mist!")
            if side.get("lucky_chant", 0) > 0:
                side["lucky_chant"] -= 1
                if side["lucky_chant"] == 0:
                    log.append(f"    {side_names[side_key]}'s Lucky Chant wore off!")
        if bstate.get("trick_room", 0) > 0:
            bstate["trick_room"] -= 1
            if bstate["trick_room"] == 0:
                log.append("    The twisted dimensions returned to normal!")
        if bstate.get("gravity", 0) > 0:
            bstate["gravity"] -= 1
            if bstate["gravity"] == 0:
                log.append("    Gravity returned to normal!")
        if active1.get("safeguard", 0) > 0:
            active1["safeguard"] -= 1
        if active2.get("safeguard", 0) > 0:
            active2["safeguard"] -= 1
        if bstate["weather_turns"] > 0:
            bstate["weather_turns"] -= 1
            if bstate["weather_turns"] == 0:
                weather_end_msg = {"SUN": "The sunlight faded!", "RAIN": "The rain stopped!",
                                    "SANDSTORM": "The sandstorm subsided!", "HAIL": "The hail stopped!"}.get(bstate["weather"])
                if weather_end_msg:
                    log.append(f"    {weather_end_msg}")
                bstate["weather"] = "NONE"
        log.append("")
        # A Pokemon that faints from end-of-turn damage (weather, poison,
        # Leech Seed, etc.) is replaced only AFTER every other currently-
        # active Pokemon has already had its own end-of-turn damage
        # applied using the weather/state as it stood at the start of
        # this phase. The replacement's own switch-in ability (Sand
        # Stream, Intimidate, etc.) still triggers and logs here - a
        # newly-set weather just doesn't retroactively deal damage to
        # anyone else this same turn, only from the following turn on.
        if not _alive(party1) and not _alive(party2):
            for mon, _foe in eot:                    # both sides are out: number the still unlogged faints in speed order (see decide_double_ko)
                if mon["hp"] <= 0 and not mon.get("_fainted_already_logged"):
                    log.append(f"  X {mon['species_display']} fainted!\n")
                    mon["_fainted_already_logged"] = True
                    resolve_faint_credit(bstate, mon)
                    revert_mimicked_move(mon)
                    revert_transform(mon)
        # The replacement attempt itself runs whenever hp<=0, regardless of _fainted_already_logged - a mid-turn
        # faint (see the fainted-target block above) already logged/credited the faint inline when it happened, and
        # only deferred the replacement to here, so the logging half stays gated but the replacement half must not be.
        # A while loop, not if: a replacement can itself faint immediately to Stealth Rock/Spikes (real Gen4 hazard-
        # chain behavior), which needs its own log/credit/next-replacement pass rather than being left as a silent
        # hp<=0 mon nobody ever announces or credits.
        while active1["hp"] <= 0:
            if not active1.get("_fainted_already_logged"):
                log.append(f"  X {active1['species_display']} fainted!\n")
                active1["_fainted_already_logged"] = True
                resolve_faint_credit(bstate, active1)
                revert_mimicked_move(active1)
                revert_transform(active1)
            replacement = select_switch_in_target(party1, [idx1], active2, bstate, rng)
            if replacement is None:
                break
            idx1 = replacement
            active1 = party1[idx1]
            apply_entry_hazards(active1, bstate, "a")
            log.append(f"  -> {name_a} sends out {active1['species_display']}!\n")
            apply_switch_in_ability(active1, active2, bstate, log)
        while active2["hp"] <= 0:
            if not active2.get("_fainted_already_logged"):
                log.append(f"  X {active2['species_display']} fainted!\n")
                active2["_fainted_already_logged"] = True
                resolve_faint_credit(bstate, active2)
                revert_mimicked_move(active2)
                revert_transform(active2)
            replacement = select_switch_in_target(party2, [idx2], active1, bstate, rng)
            if replacement is None:
                break
            idx2 = replacement
            active2 = party2[idx2]
            apply_entry_hazards(active2, bstate, "b")
            log.append(f"  -> {name_b} sends out {active2['species_display']}!\n")
            apply_switch_in_ability(active2, active1, bstate, log)

    alive_a, alive_b = _alive(party1), _alive(party2)
    if alive_a and alive_b:
        # Loop only ended because the turn cap was hit, not a real KO -
        # decide it by who has more Pokemon left, then by total remaining
        # HP among survivors, so the outcome is at least a reasonable
        # reflection of who was winning rather than an arbitrary pick.
        remaining_a = sum(1 for p in party1 if p["hp"] > 0)
        remaining_b = sum(1 for p in party2 if p["hp"] > 0)
        if remaining_a != remaining_b:
            winner = trainer_a if remaining_a > remaining_b else trainer_b
        else:
            hp_a = sum(max(0, p["hp"]) for p in party1)
            hp_b = sum(max(0, p["hp"]) for p in party2)
            winner = trainer_a if hp_a >= hp_b else trainer_b
        log.append(f"=== TURN LIMIT REACHED ({MAX_BATTLE_TURNS} turns) - decided by Pokemon/HP remaining ===")
    elif not alive_a and not alive_b:
        # Both sides lost their last Pokemon in the same step (recoil, Explosion, Rough Skin / Aftermath, Destiny Bond, ...): the official
        # double-KO rules decide the winner (see decide_double_ko).
        side, reason = decide_double_ko(party1, party2, rng)
        winner = trainer_a if side == "a" else trainer_b
        log.append(f"=== DOUBLE KO - {reason} ===")
    else:
        winner = trainer_a if alive_a else trainer_b
    log.append(f"=== WINNER: {DISPLAY_NAMES.get(winner, winner)} ===")
    os.makedirs(f"tournament_results{OUTPUT_SUFFIX}", exist_ok=True)
    log_filename = f"tournament_results{OUTPUT_SUFFIX}/{safe_filename(name_a)}_vs_{safe_filename(name_b)}_game{game_num}.txt"
    log_text = "\n".join(log)
    with open(log_filename, "w", encoding="utf-8") as f:
        f.write(log_text)

    loser = trainer_b if winner == trainer_a else trainer_a
    winner_party = party1 if winner == trainer_a else party2
    game_stats = {
        "seed": seed,
        "game_num": game_num,
        "winner": winner,
        "loser": loser,
        "turns": turns,
        "winner_remaining_hp": sum(max(0, p["hp"]) for p in winner_party),
        "knockouts": ko_events,
        "secondary_roll_events": bstate.get("_analytics_secondary_roll_events", ()),
        "damaging_hit_events": bstate.get("_analytics_damaging_hit_events", ()),
        "assist_events": bstate.get("_analytics_assist_events", ()),
        "log_file": log_filename,
        # Keep the already-built lines in memory for analytics. The old
        # pipeline reopened every log file immediately after writing it,
        # creating thousands of avoidable disk reads.
        "log_lines": log,
    }
    return winner, turns, game_stats


# ============================================================
# DOUBLE BATTLES (2v2)
# ============================================================
# The functions below are the doubles counterpart to run_battle and its
# immediate helpers. They deliberately reuse the same core mechanics
# (compute_damage, apply_move_effect, choose_move, process_status_start_
# turn/process_status_end_turn, ability/status helpers) applied per
# attacker/defender pair, rather than duplicating that logic - the
# genuinely new machinery is: two active slots per side, a turn order
# across up to four combatants instead of two, single-target moves
# needing an explicit target choice (see choose_target), and spread
# moves (RANGE_ALL_ADJACENT/RANGE_OPPONENT_SIDE) resolving against
# multiple simultaneous targets with the real games' 0.75x spread-damage
# penalty when more than one target is actually hit.
#
# Known, deliberate simplifications relative to the singles engine
# (documented here rather than silently guessed at): voluntary switching runs
# the literal TrainerAI_ShouldSwitch port (see should_voluntarily_switch_double);
# Copycat resolves against whatever target(s) it had already been assigned rather
# than re-deriving targets for the copied move's own range. Counter / Mirror Coat /
# Metal Burst (last attacker of the matching class), Follow Me, Lightning Rod /
# Storm Drain and per-slot Future Sight / Wish follow the real code.
# Multi-hit moves, two-turn semi-invulnerable / Solar Beam moves, Bide, Sucker
# Punch / Fake Out, Explosion, recharge, crash, binding, Roar/Whirlwind, U-turn /
# Baton Pass, rampage / Rollout locks and berries after a hit are all ported (see
# _resolve_hit_double, _post_move_effects_double and the action loop of
# run_battle_double); a slot that switches or uses an item spends its action.
# Everything else a normal damaging or status move does - type effectiveness, STAB,
# weather, crits, abilities, status infliction, stat changes, secondary effects,
# recoil/drain, contact abilities, Protect, Substitute - is shared with singles.
def apply_entry_abilities_double(actives_a, actives_b, bstate, log):
    """Doubles version of apply_entry_abilities: Intimidate lowers Attack
    on BOTH opposing Pokemon (there are two to hit instead of one),
    applied once per initially-active Pokemon on either side."""
    for actives, side_key in ((actives_a, "a"), (actives_b, "b")):
        for mon in actives:
            apply_entry_hazards(mon, bstate, side_key)        # rebuilt from party data BEFORE the abilities fire
    for actives, opp_actives in ((actives_a, actives_b), (actives_b, actives_a)):
        for mon in actives:
            try_trace(mon, opp_actives, log)
    weather = bstate.get("weather", "NONE")
    weather_setter = None
    for actives, opp_actives in ((actives_a, actives_b), (actives_b, actives_a)):
        for attacker in actives:
            ab = ability_of(attacker)
            if ab == "INTIMIDATE":
                for defender in opp_actives:
                    if _intimidate_lands(defender):
                        before = defender.get("atk_stage", 0)
                        defender["atk_stage"] = max(-6, before - 1)
                        ai_reveal_ability(attacker)
                        log.append(f"    {attacker['species_display']}'s Intimidate lowered {defender['species_display']}'s ATK!")
                        if defender["atk_stage"] != before:
                            note_debuff_source(bstate, defender, "atk", attacker, before - defender["atk_stage"])
            elif ab == "PRESSURE":
                ai_reveal_ability(attacker)
                log.append(f"    {attacker['species_display']} is exerting its Pressure!")
            elif ab == "DROUGHT":
                weather, weather_setter = "SUN", attacker
            elif ab == "DRIZZLE":
                weather, weather_setter = "RAIN", attacker
            elif ab == "SAND_STREAM":
                weather, weather_setter = "SANDSTORM", attacker
            elif ab == "SNOW_WARNING":
                weather, weather_setter = "HAIL", attacker
    bstate["weather"] = weather
    if weather_setter is not None:
        # Ability-triggered weather is permanent in Gen4, unlike the
        # 5-turn weather a MOVE like Rain Dance/Sandstorm sets.
        bstate["weather_turns"] = PERMANENT_WEATHER_TURNS
        weather_msg = {"SUN": "The sunlight turned harsh!", "RAIN": "It started to rain!",
                        "SANDSTORM": "A sandstorm kicked up!", "HAIL": "It started to hail!"}[weather]
        ai_reveal_ability(weather_setter)
        note_weather_set(bstate, weather, weather_setter)
        log.append(f"    {weather_setter['species_display']}'s {ability_of(weather_setter).replace('_', ' ').title()} - {weather_msg}")
    elif weather != "NONE":
        bstate["weather_turns"] = 5
    for actives, opp_actives in ((actives_a, actives_b), (actives_b, actives_a)):
        for mon in actives:
            try_download(mon, opp_actives, log)


def apply_switch_in_ability_double(mon, opponents, bstate, log, defer_weather=False):
    """Doubles version of apply_switch_in_ability for a mid-battle
    replacement: Intimidate hits BOTH current opponents, whichever are
    still alive. See apply_switch_in_ability's own docstring for
    defer_weather - same MID-TURN-fainting-replacement-only deferral,
    committed via bstate["pending_weather"] after this turn's own
    weather-damage phase has already run."""
    try_trace(mon, opponents, log)
    ab = ability_of(mon)
    if ab == "INTIMIDATE":
        for opponent in opponents:
            if _intimidate_lands(opponent):
                before = opponent.get("atk_stage", 0)
                opponent["atk_stage"] = max(-6, before - 1)
                ai_reveal_ability(mon)
                log.append(f"    {opponent['species_display']}'s ATK fell from Intimidate!")
                if opponent["atk_stage"] != before:
                    note_debuff_source(bstate, opponent, "atk", mon, before - opponent["atk_stage"])
    elif ab == "PRESSURE":
        ai_reveal_ability(mon)
        log.append(f"    {mon['species_display']} is exerting its Pressure!")
    elif ab in ("DROUGHT", "DRIZZLE", "SAND_STREAM", "SNOW_WARNING"):
        weather, weather_msg = {
            "DROUGHT": ("SUN", "The sunlight turned harsh!"),
            "DRIZZLE": ("RAIN", "It started to rain!"),
            "SAND_STREAM": ("SANDSTORM", "A sandstorm kicked up!"),
            "SNOW_WARNING": ("HAIL", "It started to hail!"),
        }[ab]
        ai_reveal_ability(mon)
        note_weather_set(bstate, weather, mon)
        log.append(f"    {mon['species_display']}'s {ab.replace('_', ' ').title()} - {weather_msg}")
        if defer_weather:
            bstate["pending_weather"] = (weather, PERMANENT_WEATHER_TURNS)
        else:
            # Ability-triggered weather is permanent in Gen4, unlike the
            # 5-turn weather a MOVE like Rain Dance/Sandstorm sets.
            bstate["weather"], bstate["weather_turns"] = weather, PERMANENT_WEATHER_TURNS
    try_download(mon, opponents, log)


def choose_target(move, actor, opponents, bstate):
    """Given a move the actor has already chosen to use (see choose_move,
    reused unchanged for the "which move" decision in run_battle_double),
    picks which of the 1-2 alive opponents a RANGE_SINGLE_TARGET move
    should hit. A real but simple AI: damaging moves target whichever
    opponent takes more damage from it; status moves default to the
    first alive one, with no deeper reasoning about which opponent
    benefits most from a given status or stat change. No move in this
    move set targets an ally, so an ally is never considered here."""
    if len(opponents) == 1:
        return opponents[0]
    if move.get("class") != "CLASS_STATUS" and move.get("power", 0) > 0:
        weather = weather_now(bstate) if bstate else "NONE"
        return max(opponents, key=lambda opp: estimate_max_damage(actor, opp, move, weather, bstate=bstate))
    return opponents[0]


def _apply_secondary_effects(attacker, defender, mv, bstate, rng, log):
    """The secondary effects (flinch / stat change / status, incl. self-directed ones) of ONE landed hit. Shared by every hit
    path (singles single/multi-hit, doubles)."""
    secondary_list = mv.get("secondaries") or ([mv["secondary"]] if mv.get("secondary") else [])
    for sec in secondary_list:
        is_self_directed = (sec.get("effect") == "RAISE_ALL_STATS" or (sec.get("effect") == "STAT_CHANGE" and sec.get("target") == "self"))
        if not is_self_directed and (defender["hp"] <= 0 or (has_ability(defender, "SHIELD_DUST") and not has_ability(attacker, "MOLD_BREAKER"))):
            break
        chance = sec["chance"] * (2 if has_ability(attacker, "SERENE_GRACE") else 1)
        secondary_success = rng.random() < chance
        _record_secondary_roll_event(bstate, attacker, sec, chance, secondary_success)
        if not secondary_success:
            continue
        if sec["effect"] == "FLINCH":
            # subscript_flinch_mon: no flinch if it already moved this turn, has a Substitute, or has Inner Focus (Mold Breaker ignores it)
            if defender.get("_acted_turn") == bstate.get("turn") or defender.get("substitute_hp", 0) > 0 \
                    or (has_ability(defender, "INNER_FOCUS") and not has_ability(attacker, "MOLD_BREAKER")):
                pass
            else:
                defender["flinched"] = True
        elif sec["effect"] == "STAT_CHANGE":
            recipient = attacker if is_self_directed else defender
            if sec["stages"] < 0 and not is_self_directed and (has_ability(recipient, "CLEAR_BODY") or has_ability(recipient, "WHITE_SMOKE")) \
                    and not has_ability(attacker, "MOLD_BREAKER"):
                pass
            elif sec["stages"] < 0 and not is_self_directed and sec["stat"] == "acc" and has_ability(recipient, "KEEN_EYE") \
                    and not has_ability(attacker, "MOLD_BREAKER"):
                pass
            elif sec["stages"] < 0 and not is_self_directed and sec["stat"] == "atk" and has_ability(recipient, "HYPER_CUTTER") and not has_ability(attacker, "MOLD_BREAKER"):
                pass
            elif sec["stages"] < 0 and bstate["sides"][bstate["side_of"](recipient)].get("mist", 0) > 0:
                log.append(f"    {recipient['species_display']} is protected by Mist!")
            else:
                key = f"{sec['stat']}_stage"
                before = recipient.get(key, 0)
                effective_stages = sec["stages"] * (2 if has_ability(recipient, "SIMPLE") else 1)
                recipient[key] = max(-6, min(6, before + effective_stages))
                if recipient[key] != before:
                    log.append(f"    {recipient['species_display']}'s {sec['stat'].upper()} {'rose' if sec['stages'] > 0 else 'fell'}!")
                    if sec["stages"] < 0 and sec["stat"] in ("atk", "def", "spa", "spd", "spe"):
                        note_debuff_source(bstate, recipient, sec["stat"], attacker, before - recipient[key])
        elif sec["effect"] == "RAISE_ALL_STATS":
            for stat_key in ("atk_stage", "def_stage", "spa_stage", "spd_stage", "spe_stage"):
                attacker[stat_key] = max(-6, min(6, attacker.get(stat_key, 0) + (2 if has_ability(attacker, "SIMPLE") else 1)))
            log.append(f"    {attacker['species_display']}'s stats all rose!")
        elif sec["effect"] == "CONFUSE":
            # subscript_confuse as an INDIRECT effect (Psybeam, Confusion, Signal Beam, Water Pulse, Dizzy / Dynamic Punch...); this
            # used to fall into the status branch below and stamp the bogus status "CONFUSE" on the target
            if try_confuse(defender, attacker, rng, log, CONFUSION_INDIRECT):
                note_contribution(bstate, defender, attacker, "status")
        else:
            status_name = {"BURN": "BURN", "PARALYZE": "PARALYSIS", "FREEZE": "FREEZE",
                           "POISON": "POISON", "TOXIC": "TOXIC"}.get(sec["effect"], sec["effect"])
            if can_inflict_status(sec["effect"], attacker, defender, weather_now(bstate)):
                defender["status"] = status_name
                log.append(f"    {defender['species_display']} was afflicted with {status_name}!")
                note_contribution(bstate, defender, attacker, "status")
                _synchronize(defender, attacker, status_name, bstate, log)


def _aftermath(attacker, defender, mv_name, bstate, log):
    """Aftermath: a holder KO'd by a contact move costs the attacker 1/4 of its max HP (not with Damp on the field or Magic Guard)."""
    if (has_ability(defender, "AFTERMATH") and attacker["hp"] > 0 and not has_ability(attacker, "MAGIC_GUARD") and not _any_damp(bstate)
            and get_move_data_by_name(mv_name).get("makes_contact")):
        ai_reveal_ability(defender)
        attacker["hp"] -= max(1, attacker["max_hp"] // 4)
        note_ko_cause(attacker, KO_CAUSE_RETALIATION)
        log.append(f"    {attacker['species_display']} was hurt by {defender['species_display']}'s Aftermath!")


def _synchronize(holder, source, status_name, bstate, log):
    """BattleSystem_SynchronizeStatus: a Synchronize holder that just got poisoned / burned / paralyzed passes it to `source` (the mon
    that caused it), through the ordinary status check; poison arrives as plain poison, sleep and freeze never synchronize."""
    if not has_ability(holder, "SYNCHRONIZE") or status_name not in ("POISON", "TOXIC", "BURN", "PARALYSIS") or source["hp"] <= 0:
        return
    passed = "POISON" if status_name == "TOXIC" else status_name
    key = {"PARALYSIS": "PARALYZE"}.get(passed, passed)
    if can_inflict_status(key, holder, source, weather_now(bstate)):
        source["status"] = passed
        note_contribution(bstate, source, holder, "status")
        ai_reveal_ability(holder)
        log.append(f"    {holder['species_display']}'s Synchronize passed its {passed} on to {source['species_display']}!")


def _any_damp(bstate):
    getter = (bstate or {}).get("all_actives")
    return any(m is not None and m["hp"] > 0 and has_ability(m, "DAMP") for m in (getter() if getter else ()))


def _damp_blocks(user, bstate):
    """Explosion / Self-Destruct: any Damp on the field stops them (Mold Breaker ignores it)."""
    return _any_damp(bstate) and not has_ability(user, "MOLD_BREAKER")


def _anger_point(defender, is_crit, log):
    """subscript_critical_hit: a critical hit maxes the Anger Point holder's Attack."""
    if is_crit and has_ability(defender, "ANGER_POINT") and defender["hp"] > 0 and defender.get("atk_stage", 0) < 6:
        defender["atk_stage"] = 6
        ai_reveal_ability(defender)
        log.append(f"    {defender['species_display']}'s Anger Point maxed its Attack!")


def _struggle_recoil(actor, log):
    """subscript_struggle: the user loses 1/4 of its MAX HP (BattleSystem_Divide, so at least 1). The effect script sets
    MOVE_SIDE_EFFECT_ON_HIT, which fires whenever the move did not miss / get protected / fail - a hit that only reaches a Substitute
    counts - and the subscript checks no ability: Rock Head and Magic Guard do not stop it."""
    recoil = max(1, actor["max_hp"] // 4)
    actor["hp"] -= recoil
    actor["_damage_taken_this_turn"] = actor.get("_damage_taken_this_turn", 0) + recoil
    note_ko_cause(actor, KO_CAUSE_RECOIL)
    log.append(f"    {actor['species_display']} was hurt by recoil! (-{recoil} HP)")


def _crash_damage(actor, target, mv, bstate, rng, log):
    """subscript_missed -> subscript_crash_on_miss (Jump Kick / High Jump Kick that did not hit: a miss, Protect, a semi-invulnerable target):
    half of the damage the move WOULD have dealt - the effect script's CalcCrit / CalcDamage already ran, so their two rng draws happen - but
    at most half of the TARGET's max HP. Only Magic Guard prevents it (Rock Head does not), and a move that would have done nothing (an immune
    target) costs nothing."""
    if target is None:
        return
    saved, target["vanished"] = target.get("vanished"), None            # CalcDamage does not care about the invulnerable turn
    try:
        would = compute_damage(actor, target, mv, weather_now(bstate), rng, force_hit=True, bstate=bstate)[0]
    finally:
        target["vanished"] = saved
    if would <= 0 or has_ability(actor, "MAGIC_GUARD"):
        return
    crash = min(max(1, would // 2), max(1, target.get("max_hp", target["hp"]) // 2))
    actor["hp"] -= crash
    actor["_damage_taken_this_turn"] = actor.get("_damage_taken_this_turn", 0) + crash
    note_ko_cause(actor, KO_CAUSE_RECOIL)
    log.append(f"    {actor['species_display']} kept going and crashed! (-{crash} HP)")


def _bind_counter(attacker, rng):
    """subscript_bind_start: Random 3,3 = RandNext() % 4 + 3 turns (the draw happens whatever the item); a Grip Claw makes it 6."""
    turns = 3 + int(rng.random() * 4)
    return 6 if _held_effect(attacker)[0] == "HOLD_EFFECT_EXTEND_TRAPPING" else turns


def _apply_drain(attacker, defender, inflicted, frac, log):
    """drain_half_damage_dealt: heal half the damage (Big Root boosts it); Liquid Ooze turns it into damage unless Magic Guard."""
    heal = max(1, int(inflicted * frac))
    effect, param = _held_effect(attacker)
    if effect == "HOLD_EFFECT_LEECH_BOOST":
        heal = max(1, heal * (100 + param) // 100)
    if attacker.get("heal_block_turns", 0) > 0 and not has_ability(defender, "LIQUID_OOZE"):
        return                                                  # Heal Block: the drain heals nothing
    if has_ability(defender, "LIQUID_OOZE"):
        ai_reveal_ability(defender)
        if not has_ability(attacker, "MAGIC_GUARD"):
            attacker["hp"] -= heal
            note_ko_cause(attacker, KO_CAUSE_RETALIATION)
            log.append(f"    {attacker['species_display']} sucked up the liquid ooze!")
        return
    attacker["hp"] = min(attacker["max_hp"], attacker["hp"] + heal)
    log.append(f"    {attacker['species_display']} drained {heal} HP!")


def _apply_contact_abilities(attacker, defender, mv, rng, log, bstate=None):
    """The defender's on-hit abilities after a landed hit (BattleSystem_TriggerAbilityOnHit): Color Change (any damaging hit) and, for
    contact moves, Rough Skin / Static / Flame Body / Poison Point / Effect Spore / Cute Charm, with Synchronize passing a status the
    ability just caused back. As in the C these fire even if the defender just fainted; Rough Skin does nothing to a Magic Guard user."""
    if (has_ability(defender, "COLOR_CHANGE") and defender["hp"] > 0 and mv.get("power", 0) > 0 and mv.get("name") != "MOVE_STRUGGLE"
            and mv.get("type") not in defender.get("types", ())):
        defender.setdefault("_orig_types", (defender.get("type1"), defender.get("type2"), list(defender.get("types", ()))))
        defender["type1"], defender["type2"], defender["types"] = mv["type"], None, [mv["type"]]
        ai_reveal_ability(defender)
        log.append(f"    {defender['species_display']}'s Color Change made it the {mv['type'].replace('TYPE_', '').title()} type!")
    if not mv.get("makes_contact") or attacker["hp"] <= 0:
        return
    dab = ability_of(defender)
    if dab in ("ROUGH_SKIN", "IRON_BARBS"):
        if not has_ability(attacker, "MAGIC_GUARD"):
            ai_reveal_ability(defender)
            attacker["hp"] -= max(1, attacker["max_hp"] // 8)
            note_ko_cause(attacker, KO_CAUSE_RETALIATION)
            note_contribution(bstate, attacker, defender, "damage")
    elif dab == "STATIC" and rng.random() < 0.3 and can_inflict_status("PARALYZE", defender, attacker):
        attacker["status"] = "PARALYSIS"
        note_contribution(bstate, attacker, defender, "status")
        ai_reveal_ability(defender)
        log.append(f"    {attacker['species_display']} was paralyzed by Static!")
        _synchronize(attacker, defender, "PARALYSIS", bstate, log)
    elif dab == "FLAME_BODY" and rng.random() < 0.3 and can_inflict_status("BURN", defender, attacker):
        attacker["status"] = "BURN"
        note_contribution(bstate, attacker, defender, "status")
        ai_reveal_ability(defender)
        log.append(f"    {attacker['species_display']} was burned by Flame Body!")
        _synchronize(attacker, defender, "BURN", bstate, log)
    elif dab == "POISON_POINT" and rng.random() < 0.3 and can_inflict_status("POISON", defender, attacker):
        attacker["status"] = "POISON"
        note_contribution(bstate, attacker, defender, "status")
        ai_reveal_ability(defender)
        log.append(f"    {attacker['species_display']} was poisoned by Poison Point!")
        _synchronize(attacker, defender, "POISON", bstate, log)
    elif dab == "EFFECT_SPORE" and attacker.get("status", "NONE") == "NONE" and rng.random() < 0.3:
        kind = ("POISON", "PARALYZE", "SLEEP")[int(rng.random() * 3)]
        if can_inflict_status(kind, defender, attacker, weather_now(bstate)):
            status_name = "PARALYSIS" if kind == "PARALYZE" else kind
            attacker["status"] = status_name
            note_contribution(bstate, attacker, defender, "status")
            ai_reveal_ability(defender)
            log.append(f"    {attacker['species_display']} was afflicted with {status_name} by Effect Spore!")
            _synchronize(attacker, defender, status_name, bstate, log)
    elif dab == "CUTE_CHARM" and rng.random() < 0.3 and can_be_attracted(defender, attacker):
        attacker["attracted"] = True
        log.append(f"    {attacker['species_display']} fell in love with {defender['species_display']} (Cute Charm)!")


def _record_faint(attacker, defender, mv_name, log, ko_events, trainer_of, bstate=None):
    """A defender that just reached 0 HP: log it once, Grudge, revert Mimic/Transform, and record the KO event."""
    defender["hp"] = 0
    if defender.get("_fainted_already_logged"):
        return
    log.append(f"  X {defender['species_display']} fainted!\n")
    defender["_fainted_already_logged"] = True
    for category, src in (attacker.get("_turn_order_credit") or {}).get(id(defender), {}).items():
        note_contribution(bstate, defender, src, category)
    resolve_faint_credit(bstate, defender, attacker)
    if defender.get("grudge_active") and mv_name != "MOVE_STRUGGLE" and mv_name in attacker.get("move_pp", {}):
        attacker["move_pp"][mv_name] = 0
        move_display = mv_name.replace("MOVE_", "").replace("_", " ").title()
        log.append(f"    {attacker['species_display']}'s {move_display} lost all its PP due to the grudge!")
    revert_mimicked_move(defender)
    revert_transform(defender)
    ko_events.append({
        "species": attacker["species"], "trainer": trainer_of(attacker), "move": mv_name,
        "victim_species": defender["species"], "victim_trainer": trainer_of(defender),
    })
    note_baton_pass_ko(bstate, attacker, trainer_of(attacker))
    if defender.get("destiny_bond") and attacker["hp"] > 0 and trainer_of(attacker) != trainer_of(defender):
        attacker["hp"] = 0                                          # subscript_faint_check_destiny_bond
        note_ko_cause(attacker, KO_CAUSE_RETALIATION)
        log.append(f"    {defender['species_display']} took {attacker['species_display']} down with it!")
    _aftermath(attacker, defender, mv_name, bstate, log)


def _resolve_multihit_double(attacker, defender, mv, mv_name, bstate, rng, log, spread_hit, ko_events, trainer_of):
    """Multi-hit moves (Fury Swipes, Double Kick, ...) on one target: accuracy is checked once, every later hit is guaranteed,
    each hit has its own crit / damage roll / secondaries / contact procs, and the sequence stops when either mon faints.
    Returns (fainted, connected)."""
    num_hits = mv["multihit_fixed"] if mv.get("multihit_fixed") else (5 if has_ability(attacker, "SKILL_LINK") else roll_multihit_count(rng))
    hits_landed, total_dmg, any_crit, last_eff = 0, 0, False, 1.0
    for hit_i in range(num_hits):
        dmg, is_crit, eff, missed_this = compute_damage(attacker, defender, mv, weather_now(bstate), rng,
                                                        force_hit=(hit_i > 0), bstate=bstate, log=log, spread=spread_hit)
        if hit_i == 0 and missed_this:
            log.append(f"    Attack on {defender['species_display']} missed!")
            return False, False
        last_eff = eff
        if eff == 0.0:
            break
        if defender.get("substitute_hp", 0) > 0:
            absorbed = min(defender["substitute_hp"], dmg)
            defender["substitute_hp"] -= absorbed
            total_dmg += absorbed
        else:
            pre_hit_hp_this = defender["hp"]
            defender["hp"] -= dmg
            total_dmg += dmg
            _record_damaging_hit_event(bstate, defender, attacker)
            note_stat_drop_ko_assists(bstate, attacker, defender, mv, dmg, pre_hit_hp_this, is_crit, rng)
            defender["_damage_taken_this_turn"] = defender.get("_damage_taken_this_turn", 0) + dmg
            defender["_damage_taken_class_this_turn"] = mv.get("class", "CLASS_PHYSICAL")
            note_hit_taken(defender, attacker, dmg, mv)
            defender["this_turn_hit_type"] = mv.get("type", "TYPE_NORMAL")
            if defender.get("bide_turns", 0) > 0:
                defender["bide_damage"] = defender.get("bide_damage", 0) + dmg
        hits_landed += 1
        any_crit = any_crit or is_crit
        _anger_point(defender, is_crit, log)
        _apply_secondary_effects(attacker, defender, mv, bstate, rng, log)
        _apply_contact_abilities(attacker, defender, mv, rng, log, bstate)
        if defender["hp"] <= 0 or attacker["hp"] <= 0:
            break
    if hits_landed == 0:
        log.append(f"    It had no effect on {defender['species_display']}.")
        return False, True
    msg = f"    Hit {hits_landed} time{'s' if hits_landed != 1 else ''}! Dealt {total_dmg} damage total to {defender['species_display']}!"
    if any_crit:
        msg += " At least one critical hit!"
    if last_eff > 1.0:
        msg += " Super effective!"
    elif 0 < last_eff < 1.0:
        msg += " Not very effective..."
    log.append(msg)
    fainted = defender["hp"] <= 0
    if fainted:
        _record_faint(attacker, defender, mv_name, log, ko_events, trainer_of, bstate)
    return fainted, True


def _resolve_hit_double(attacker, defender, mv, mv_name, bstate, rng, log, spread_hit, ko_events, trainer_of):
    """Resolves ONE move use hitting ONE target, within run_battle_double - used both for a single-target move and for each
    individual target of a spread move. spread_hit=True applies the real games' 0.75x damage penalty for actually hitting more
    than one target with this use. Mirrors run_battle's single-hit dispatch (see there for the fuller commentary on each piece),
    sharing the secondary-effect / contact-ability helpers with it. Returns (fainted, connected): connected is False when the
    move missed or was blocked by Protect (what Hyper Beam's recharge, a crash move, binding and Rollout key off)."""
    if defender["hp"] <= 0:
        return False, False
    if defender.get("protected") and mv.get("can_be_protected", True) and not mv.get("protect"):
        log.append(f"    {defender['species_display']} protected itself!")
        return False, False
    if mv.get("class") == "CLASS_STATUS":
        # compute_damage only rolls the accuracy check for a status move (see there); the effect applies on a hit.
        _, _, _, missed = compute_damage(attacker, defender, mv, weather_now(bstate), rng, bstate=bstate, log=log)
        if missed:
            log.append(f"    Attack on {defender['species_display']} missed!")
            return False, False
        apply_move_effect(mv, attacker, defender, bstate, rng, log)
        return False, True
    if mv.get("multihit") or mv.get("multihit_fixed"):
        return _resolve_multihit_double(attacker, defender, mv, mv_name, bstate, rng, log, spread_hit, ko_events, trainer_of)

    dmg, is_crit, eff, missed = compute_damage(attacker, defender, mv, weather_now(bstate), rng, bstate=bstate, log=log,
                                               spread=spread_hit)
    if missed:
        log.append(f"    Attack on {defender['species_display']} missed!")
        return False, False
    if eff == 0.0:
        log.append(f"    It had no effect on {defender['species_display']}.")
        return False, True
    if mv.get("stat_changes"):
        # A damaging move with its own GUARANTEED stat change (Close
        # Combat/Superpower/Hammer Arm dropping the user's own Def/Spe,
        # Overheat/Draco Meteor/Leaf Storm/Psycho Boost dropping the
        # user's own SpA) - see the matching fix in run_battle's own
        # single-hit dispatch for the fuller explanation.
        apply_move_effect(mv, attacker, defender, bstate, rng, log)

    if defender.get("substitute_hp", 0) > 0:
        absorbed = min(defender["substitute_hp"], dmg)
        defender["substitute_hp"] -= absorbed
        log.append(f"    {defender['species_display']}'s Substitute took {absorbed} damage!")
        if mv.get("struggle_recoil"):
            _struggle_recoil(attacker, log)                             # MOVE_SIDE_EFFECT_ON_HIT: a Substitute hit counts
        return False, True

    pre_hit_hp = defender["hp"]
    defender["hp"] -= dmg
    _record_damaging_hit_event(bstate, defender, attacker)
    note_stat_drop_ko_assists(bstate, attacker, defender, mv, dmg, pre_hit_hp, is_crit, rng)
    defender["_damage_taken_this_turn"] = defender.get("_damage_taken_this_turn", 0) + dmg
    defender["_damage_taken_class_this_turn"] = mv.get("class", "CLASS_PHYSICAL")
    note_hit_taken(defender, attacker, dmg, mv)
    defender["this_turn_hit_type"] = mv.get("type", "TYPE_NORMAL")
    inflicted = min(dmg, max(0, pre_hit_hp))  # actual HP lost, capped - see run_battle's own note on this
    if defender.get("bide_turns", 0) > 0:
        defender["bide_damage"] = defender.get("bide_damage", 0) + inflicted
    msg = f"    Dealt {dmg} damage to {defender['species_display']}!"
    if is_crit:
        msg += " Critical hit!"
    if eff > 1.0:
        msg += " Super effective!"
    elif 0 < eff < 1.0:
        msg += " Not very effective..."
    log.append(msg)
    _anger_point(defender, is_crit, log)

    if mv.get("effect") == "PLUCK" and defender["hp"] > 0 and not (has_ability(defender, "STICKY_HOLD") and not has_ability(attacker, "MOLD_BREAKER")):
        defender_item_info = get_item_info(defender.get("item"))
        if defender_item_info.get("is_berry"):
            eaten = eat_berry(attacker, holder=defender)
            if eaten:
                log.append(f"    {attacker['species_display']} plucked and ate {defender['species_display']}'s {eaten}!")

    if mv.get("drain") and attacker["hp"] > 0:
        _apply_drain(attacker, defender, inflicted, mv["drain"], log)
    if mv.get("struggle_recoil"):
        _struggle_recoil(attacker, log)
    elif mv.get("recoil") and not has_ability(attacker, "ROCK_HEAD") and not has_ability(attacker, "MAGIC_GUARD"):
        recoil_dmg = max(1, int(inflicted * mv["recoil"]))
        attacker["hp"] -= recoil_dmg
        attacker["_damage_taken_this_turn"] = attacker.get("_damage_taken_this_turn", 0) + recoil_dmg
        note_ko_cause(attacker, KO_CAUSE_RECOIL)
        log.append(f"    {attacker['species_display']} was hurt by recoil! (-{recoil_dmg} HP)")

    check_white_herb(attacker, log)
    check_white_herb(defender, log)

    if attacker.get("grudge_active") and mv.get("effect") != "GRUDGE":
        attacker["grudge_active"] = False
    if attacker.get("charged") and not mv.get("charges_electric"):
        attacker["charged"] = False

    fainted = defender["hp"] <= 0
    if fainted:
        _record_faint(attacker, defender, mv_name, log, ko_events, trainer_of, bstate)

    if mv.get("effect") in ("SPIT_UP", "ENDEAVOR"):
        apply_move_effect(mv, attacker, defender, bstate, rng, log)
    _apply_secondary_effects(attacker, defender, mv, bstate, rng, log)
    _apply_contact_abilities(attacker, defender, mv, rng, log, bstate)
    return fainted, True


_SWITCH_OUT_RESETS = (("perish_song", 0), ("cursed", False), ("yawn_turn", 0), ("nightmare", False), ("must_recharge", False),
                      ("rampage_turns", 0), ("rampage_move", None), ("rollout_turns", 0), ("rollout_move", None), ("taunt_turns", 0),
                      ("tormented", False), ("encore_turns", 0), ("encore_move", None), ("focus_energy", False), ("trapped_turns", 0),
                      ("vanished", None), ("embargo_turns", 0), ("grudge_active", False), ("imprison_moves", None),
                      ("bide_turns", 0), ("bide_damage", 0))


def _clear_switch_out_state(mon, log):
    """Everything that ends when a mon leaves the field (the same reset list every switch / pivot / Roar site uses)."""
    process_natural_cure(mon, log)
    for key, value in _SWITCH_OUT_RESETS:
        mon[key] = value
    mon["moves_used_this_stay"] = set()
    clear_stockpile(mon)
    revert_mimicked_move(mon)
    revert_transform(mon)


def _bide_double(actor, target, mv, mv_name, bstate, log, ko_events, trainer_of):
    """Bide (doubles): stores energy for two turns (self-targeting, so Protect can't interrupt), then releases 2x the damage
    taken over them on `target` - the release can be Protected against. Mirrors run_battle's Bide branch."""
    bstate["last_move_used"] = mv_name
    actor["last_move_used"] = mv_name
    if actor.get("bide_turns", 0) <= 0:
        actor["bide_turns"] = 2
        actor["bide_damage"] = 0
        log.append(f"    {actor['species_display']} is storing energy!")
        return
    actor["bide_turns"] -= 1
    if actor["bide_turns"] > 0:
        log.append(f"    {actor['species_display']} is storing energy!")
        return
    bstate["last_move_used"] = None          # the release turn is not a valid Copycat move
    actor["last_move_used"] = None
    bide_dmg = actor.get("bide_damage", 0)
    actor["bide_damage"] = 0
    if target is None or target["hp"] <= 0 or bide_dmg <= 0:
        log.append("    But it failed!")
        return
    if target.get("protected") and mv.get("can_be_protected", True):
        log.append("    Protected!")
        return
    if get_type_effectiveness("TYPE_NORMAL", actor, target, gravity=bstate.get("gravity", 0) > 0) == 0.0:
        log.append("    It had no effect.")
        return
    release_dmg = max(1, bide_dmg * 2)
    if target.get("substitute_hp", 0) > 0:
        absorbed = min(target["substitute_hp"], release_dmg)
        target["substitute_hp"] -= absorbed
        log.append(f"    {actor['species_display']} unleashed its energy! The Substitute took {absorbed} damage!")
        return
    target["hp"] -= release_dmg
    _record_damaging_hit_event(bstate, target, actor)
    log.append(f"    {actor['species_display']} unleashed its energy! Dealt {release_dmg} damage to {target['species_display']}!")
    if target["hp"] <= 0:
        _record_faint(actor, target, mv_name, log, ko_events, trainer_of, bstate)


def redirect_to_rod(mv, actor, target, opponents, bstate):
    """BattleSystem_RedirectSingleTarget: an Electric (Water) move aimed at one foe is pulled to a foe with Lightning Rod (Storm Drain);
    not for a Normalize / Mold Breaker user, and a Follow Me user takes precedence (applied when the move executes)."""
    if has_ability(actor, "NORMALIZE") or has_ability(actor, "MOLD_BREAKER"):
        return target
    move_type = mv.get("type")
    wanted = {"TYPE_ELECTRIC": "LIGHTNING_ROD", "TYPE_WATER": "STORM_DRAIN"}.get(move_type)
    if not wanted:
        return target
    for foe in opponents:
        if foe is not None and foe["hp"] > 0 and has_ability(foe, wanted):
            return foe
    return target


def resolve_targets_double(mv, actor, chosen_target, ally, opponents, bstate, rng):
    """The mons a doubles move use lands on, from its range: `chosen_target` is the AI's pick (None when the move was forced or the
    pick left the field), `opponents` the living foes, `ally` the living partner or None."""
    move_range = mv.get("range", "RANGE_SINGLE_TARGET")
    if move_range in ("RANGE_SINGLE_TARGET", "RANGE_SINGLE_TARGET_SPECIAL", "RANGE_SINGLE_TARGET_ME_FIRST"):
        target = chosen_target if chosen_target is not None else choose_target(mv, actor, opponents, bstate)
        return [redirect_to_rod(mv, actor, target, opponents, bstate)] if move_range == "RANGE_SINGLE_TARGET" else [target]
    if move_range == "RANGE_ADJACENT_OPPONENTS":
        return list(opponents)
    if move_range == "RANGE_RANDOM_OPPONENT":
        return [redirect_to_rod(mv, actor, rng.choice(opponents), opponents, bstate)]
    if move_range == "RANGE_ALLY":
        return [ally] if ally is not None else [actor]
    if move_range == "RANGE_USER_OR_ALLY":
        return [chosen_target] if (chosen_target is ally and ally is not None) else [actor]
    if move_range == "RANGE_ALL_ADJACENT":
        return opponents + ([ally] if ally is not None else [])
    if move_range == "RANGE_OPPONENT_SIDE":
        # Side-wide effects (entry hazards) - a single use affects the opposing SIDE once, not once per Pokemon currently
        # standing on it (that would let a single Spikes use in doubles wrongly add 2 layers instead of 1). Any one opponent
        # is just a stand-in so apply_move_effect's side_of(defender) lookup resolves to the right side.
        return [opponents[0]]
    return [actor]                # RANGE_USER, RANGE_USER_SIDE - self/side-wide, resolved via apply_move_effect on the actor itself


def _post_move_effects_double(actor, targets, mv, mv_name, missed, party1, party2, idx1, idx2, name_a, name_b, bstate, rng, log,
                              damp_blocked=False):
    """What run_battle does after a move resolves, for one doubles action: Roar/Whirlwind, U-turn / Baton Pass, crash damage,
    Explosion, binding, Hyper Beam recharge, Outrage-style rampage lock and Rollout. `missed` is True when the move failed,
    missed or was Protected against on every target. idx1/idx2 are the two-slot lists of active party indices."""
    target = targets[0] if targets else None

    def side_state(mon):
        side = bstate["side_of"](mon)
        return side, (party1 if side == "a" else party2), (idx1 if side == "a" else idx2), (name_a if side == "a" else name_b)

    # Whirlwind/Roar: a random benched mon replaces the target
    if mv.get("effect") == "FORCE_SWITCH" and not missed and target is not None and target["hp"] > 0:
        if target.get("substitute_hp", 0) > 0:
            log.append("    But it failed against the Substitute!")
        elif (has_ability(target, "SUCTION_CUPS") and not has_ability(actor, "MOLD_BREAKER")) or target.get("ingrain"):
            log.append(f"    {target['species_display']} anchors itself!")
        else:
            side, t_party, t_idx, disp = side_state(target)
            slot = next((i for i in (0, 1) if t_idx[i] is not None and t_party[t_idx[i]] is target), None)
            new_idx = None
            if slot is not None:
                new_idx = perform_forced_switch(t_party, t_idx[slot], rng, exclude=[i for i in t_idx if i is not None])
            if new_idx is None:
                log.append(f"    But it failed! {target['species_display']} has nowhere to switch to.")
            else:
                old_species = target["species_display"]
                _clear_switch_out_state(target, log)
                t_idx[slot] = new_idx
                new_mon = t_party[new_idx]
                log.append(f"    {old_species} was blown away! {disp} sent out {new_mon['species_display']}!")
                apply_entry_hazards(new_mon, bstate, side)
                foes = [m for m in ((party2 if side == "a" else party1)[i] for i in (idx2 if side == "a" else idx1) if i is not None) if m["hp"] > 0]
                apply_switch_in_ability_double(new_mon, foes, bstate, log)

    # U-turn / Volt Switch / Flip Turn / Parting Shot / Baton Pass: the user switches out after the move
    if mv.get("pivot") and actor["hp"] > 0:
        side, p_party, p_idx, disp = side_state(actor)
        slot = next((i for i in (0, 1) if p_idx[i] is not None and p_party[p_idx[i]] is actor), None)
        foes = [m for m in ((party2 if side == "a" else party1)[i] for i in (idx2 if side == "a" else idx1) if i is not None) if m["hp"] > 0]
        new_idx = None
        if slot is not None:
            new_idx = select_switch_in_target(p_party, [i for i in p_idx if i is not None], target, bstate, rng,
                                              battler=actor, opponents=foes, is_double=True)
        if new_idx is not None:
            passed = baton_state(actor) if mv.get("baton_pass") else None
            old_mon, old_species = actor, actor["species_display"]
            _clear_switch_out_state(actor, log)
            p_idx[slot] = new_idx
            new_mon = p_party[new_idx]
            new_mon["acted_since_switch_in"] = False
            if mv.get("baton_pass"):
                log.append(f"    {old_species} passed the baton to {new_mon['species_display']}!")
            else:
                log.append(f"    {old_species} came back! {disp} sent out {new_mon['species_display']}!")
            apply_entry_hazards(new_mon, bstate, side)
            if passed is not None:
                apply_baton_state(new_mon, passed, old_mon, bstate)
                note_baton_pass_support(bstate, old_mon, new_mon, passed)
            apply_switch_in_ability_double(new_mon, foes, bstate, log)

    # High Jump Kick / Jump Kick: crash for half max HP when they miss or are blocked
    if mv.get("crash") and missed and actor["hp"] > 0:
        _crash_damage(actor, target, mv, bstate, rng, log)

    # Explosion / Self-Destruct: the user faints whatever happens
    if mv.get("self_destruct") and actor["hp"] > 0 and not damp_blocked:
        actor["hp"] = 0
        note_ko_cause(actor, KO_CAUSE_SUICIDE)
        log.append(f"    {actor['species_display']} exploded!")

    # Binding moves trap the target for 2-5 turns
    if mv.get("binding") and not missed and target is not None and target["hp"] > 0 and target.get("trapped_turns", 0) <= 0:
        target["trapped_turns"] = _bind_counter(actor, rng)
        target["trapped_by_species"] = actor["species_display"]
        log.append(f"    {target['species_display']} became trapped!")

    # Hyper Beam / Giga Impact: recharge next turn, but only if the move connected
    if mv.get("recharge") and actor["hp"] > 0 and not missed:
        actor["must_recharge"] = True

    # Outrage / Petal Dance / Thrash: locked in for 2-3 turns, then confused
    if mv.get("rampage") and actor["hp"] > 0:
        if actor.get("rampage_turns", 0) <= 0:
            actor["rampage_turns"] = rng.choice([2, 3])
            actor["rampage_move"] = mv_name
        actor["rampage_turns"] -= 1
        if actor["rampage_turns"] <= 0:
            actor["rampage_move"] = None
            rampage_fatigue(actor, rng, log)

    # Rollout / Ice Ball: up to 5 uses, a miss ends the lock
    if mv.get("rollout") and actor["hp"] > 0:
        if not actor.get("rollout_move"):
            actor["rollout_move"] = mv_name
            actor["rollout_turns"] = 0
        actor["rollout_turns"] += 1
        if missed or actor["rollout_turns"] >= 5:
            actor["rollout_move"] = None
            actor["rollout_turns"] = 0


def run_battle_double(trainer_a, trainer_b, seed=None, game_num=1):
    """Doubles (2v2) counterpart to run_battle - see the module comment
    just above this section for exactly which mechanics are reused as-is
    and which are simplified for this first doubles implementation."""
    name_a = DISPLAY_NAMES.get(trainer_a, trainer_a)
    name_b = DISPLAY_NAMES.get(trainer_b, trainer_b)
    rng = random.Random(seed)
    _seed_rng_global(seed, trainer_a, trainer_b, game_num)
    t1_data, t2_data = TRAINERS_DB[trainer_a], TRAINERS_DB[trainer_b]
    party1 = [copy.deepcopy(p) for p in t1_data["party"]]
    party2 = [copy.deepcopy(p) for p in t2_data["party"]]
    ai_a = t1_data.get("ai_flags", ["TRAINER_AI_BASIC"])
    ai_b = t2_data.get("ai_flags", ["TRAINER_AI_BASIC"])

    # Two active slots per side: idx1[0]/idx1[1] index into party1, or
    # None if that slot has no living Pokemon to occupy it. Both sides
    # start with min(2, len(party)) slots filled - run_battle_double is
    # only ever invoked (see determine_battle_format) when BOTH parties
    # have at least 2 Pokemon, so both start with both slots filled, but
    # slots can still empty out to None over the course of the battle
    # once a side runs out of replacements.
    idx1 = [0, 1]
    idx2 = [0, 1]

    def actives(party, idx_pair):
        return [party[i] for i in idx_pair if i is not None]

    def slot_mon(party, idx_pair, slot):
        i = idx_pair[slot]
        return party[i] if i is not None else None

    def slot_list(party, idx_pair):
        """Both battler slots in order (None for an empty slot, fainted mons included) - the AI's view of a side."""
        return [party[i] if i is not None else None for i in idx_pair]

    def trainer_of(mon):
        return trainer_a if any(mon is m for m in party1) else trainer_b

    bstate = {
        "turn": 1, "weather": "NONE", "weather_turns": 0, "trick_room": 0, "gravity": 0, "last_move_used": None, "is_double_battle": True,
        "sides": {"a": new_side_state(), "b": new_side_state()},
        "trainer_keys": {"a": trainer_a, "b": trainer_b},
        "_analytics_secondary_roll_events": [],
        "_analytics_damaging_hit_events": [],
        "_analytics_assist_events": [],
        "ai_items": {"a": new_ai_item_state(t1_data.get("items")), "b": new_ai_item_state(t2_data.get("items"))},
    }
    bstate["side_of"] = lambda mon: "a" if any(mon is m for m in party1) else "b"     # identity, not ==: mirror matches have equal dicts
    bstate["all_actives"] = lambda: actives(party1, idx1) + actives(party2, idx2)
    bstate["slot_of"] = lambda mon: next((sl for prt, ip in ((party1, idx1), (party2, idx2)) for sl in (0, 1)
                                          if slot_mon(prt, ip, sl) is mon), 0)
    bstate["occupants"] = lambda: {(sd, sl): slot_mon(prt, ip, sl) for sd, prt, ip in (("a", party1, idx1), ("b", party2, idx2)) for sl in (0, 1)}
    bstate["party_of"] = lambda mon: party1 if any(mon is m for m in party1) else party2

    log = [f"=== GAME {game_num}: {name_a} vs {name_b} (DOUBLE BATTLE) ===", ""]
    log.extend(format_team_roster_for_log(name_a, party1))
    log.append("")
    log.extend(format_team_roster_for_log(name_b, party2))
    log.append("")

    apply_entry_abilities_double(actives(party1, idx1), actives(party2, idx2), bstate, log)

    def _alive(party):
        return any(p["hp"] > 0 for p in party)

    def _replace_fainted_slots(party, idx_pair, side_key, opponents_now, fill=True):
        """After any faints this turn/end-of-turn, vacates fainted slots (logging/crediting the faint the first
        time it's seen) and, if fill=True, fills them using the same faithful send-in procedure as singles (see
        select_switch_in_target), scored against the first currently alive opponent as a representative target -
        applying entry hazards and switch-in abilities (Intimidate hitting both current opponents) for each
        newly-sent-in Pokemon.

        fill=False is for the MID-TURN call site only: Gen4 always defers a fainted mon's replacement until AFTER
        the entire end-of-turn sequence finishes for the turn it fainted in (Smogon's end-of-turn ordering - the
        same rule the EOT-phase-faint case already follows), regardless of whether it fainted mid-turn to a direct
        hit (here) or during the end-of-turn phase itself to residual damage. So the mid-turn call just vacates the
        slot (idx_pair[slot] = None) and stops - the slot stays empty (not targetable, see on_field()/target
        revalidation elsewhere in this function) for the rest of the turn. The post-EOT call site (fill=True,
        the default) is the only place a replacement is ever actually sent in, picking up both slots vacated
        mid-turn and any new EOT-phase faints together."""
        for slot in (0, 1):
            while True:
                i = idx_pair[slot]
                fainted_mon = None
                if i is not None and party[i]["hp"] <= 0:
                    fainted_mon = party[i]
                    if not fainted_mon.get("_fainted_already_logged"):     # a passive faint: poison, weather, hazards, confusion...
                        log.append(f"  X {fainted_mon['species_display']} fainted!\n")
                        fainted_mon["_fainted_already_logged"] = True
                        revert_mimicked_move(fainted_mon)
                        revert_transform(fainted_mon)
                        resolve_faint_credit(bstate, fainted_mon)
                    idx_pair[slot] = None
                    i = None
                if i is None and fill:
                    already_active = [j for j in idx_pair if j is not None]
                    opponents = [o for o in opponents_now() if o is not None]
                    target = opponents[0] if opponents else None
                    replacement = select_switch_in_target(party, already_active, target, bstate, rng, battler=fainted_mon,
                                                          opponents=list(opponents_now()), is_double=True)
                    if replacement is None:
                        break
                    idx_pair[slot] = replacement
                    new_mon = party[replacement]
                    apply_entry_hazards(new_mon, bstate, side_key)
                    log.append(f"  -> {name_a if side_key == 'a' else name_b} sends out {new_mon['species_display']}!\n")
                    apply_switch_in_ability_double(new_mon, opponents, bstate, log)
                    if new_mon["hp"] <= 0:
                        # Fainted immediately to Stealth Rock/Spikes (real Gen4 hazard-chain behavior) - loop back
                        # around to log/credit it and try the next bench mon, rather than leaving a silent hp<=0
                        # mon nobody ever announces or credits.
                        continue
                    break
                else:
                    break

    turns = 0
    ko_events = []
    while _alive(party1) and _alive(party2) and turns < MAX_BATTLE_TURNS:
        turns += 1
        bstate["turn"] = turns
        cleanup_stale_links(bstate)
        for mon in actives(party1, idx1) + actives(party2, idx2):
            mon["_damage_taken_this_turn"] = 0
            mon["_damage_taken_class_this_turn"] = None
            mon["_hits_taken"] = []
            mon["prev_turn_hit_type"] = mon.get("this_turn_hit_type")
            mon["this_turn_hit_type"] = None
            mon["helping_hand"] = False
        log.append(f"--- Turn {turns} ---")
        log.append(f"{name_a}'s side: " + ", ".join(
            f"Lv. {m['level']} {m['species_display']} (HP: {max(0, m['hp'])}/{m['max_hp']})" for m in actives(party1, idx1)))
        log.append(f"{name_b}'s side: " + ", ".join(
            f"Lv. {m['level']} {m['species_display']} (HP: {max(0, m['hp'])}/{m['max_hp']})" for m in actives(party2, idx2)))

        # Snapshot of each side's actives as the turn begins, before any
        # switching this turn - see the matching singles comment above
        # run_battle's own turn loop for the full explanation. Move
        # CHOICE below uses this; the actual target list a few lines
        # further down correctly keeps using the current, post-switch
        # actives.
        turn_start_actives_a = list(actives(party1, idx1))
        turn_start_actives_b = list(actives(party2, idx2))

        # --- voluntary switching / item use (both sides, both slots) ---
        # Resolved before either side even considers a move, same timing
        # as singles - see should_voluntarily_switch_double. Like singles, a slot that switches or uses an item spends its
        # action doing so (`spent_action`): it neither runs its start-of-turn status check nor picks a move.
        spent_action = set()
        for side_key, party, idx_pair, opp_party, opp_idx_pair, side_name in (
            ("a", party1, idx1, party2, idx2, name_a), ("b", party2, idx2, party1, idx1, name_b)
        ):
            for slot in (0, 1):
                actor = slot_mon(party, idx_pair, slot)
                if actor is None or actor["hp"] <= 0:
                    continue
                ally_idx = idx_pair[1 - slot]
                opponents = [m for m in actives(opp_party, opp_idx_pair) if m["hp"] > 0]
                switch_idx = should_voluntarily_switch_double(actor, idx_pair[slot], ally_idx, opponents, party, bstate, rng,
                                                              slot=slot, opp_slots=slot_list(opp_party, opp_idx_pair))
                if switch_idx is not None:
                    process_natural_cure(actor, log)
                    for reset_key, reset_val in (("perish_song", 0), ("cursed", False), ("yawn_turn", 0),
                                                  ("nightmare", False), ("must_recharge", False), ("rampage_turns", 0),
                                                  ("rampage_move", None), ("rollout_turns", 0), ("rollout_move", None),
                                                  ("taunt_turns", 0), ("tormented", False), ("encore_turns", 0), ("encore_move", None), ("focus_energy", False), ("trapped_turns", 0), ("vanished", None), ("moves_used_this_stay", set()), ("embargo_turns", 0), ("grudge_active", False),
                                                  ("imprison_moves", None), ("bide_turns", 0), ("bide_damage", 0)):
                        actor[reset_key] = reset_val
                    clear_stockpile(actor)
                    revert_mimicked_move(actor)
                    revert_transform(actor)
                    old_species = actor["species_display"]
                    idx_pair[slot] = switch_idx
                    new_mon = party[switch_idx]
                    log.append(f"  {side_name} withdraws {old_species} and sends out {new_mon['species_display']}!")
                    apply_entry_hazards(new_mon, bstate, side_key)
                    apply_switch_in_ability_double(new_mon, opponents, bstate, log)
                    spent_action.add((side_key, slot))
                elif slot == AI_ITEM_POOL_SLOT:
                    # Only the slot that owns the trainer's items may use them (see AI_ITEM_POOL_SLOT).
                    use = ai_should_use_item(actor, party, bstate["ai_items"][side_key], bstate)
                    if use:
                        apply_ai_item(actor, use, bstate, log, side_name)
                        spent_action.add((side_key, slot))

        # --- move + target selection for every alive active combatant ---
        actions = []
        for side_key, party, idx_pair, opp_party, opp_idx_pair, ai_flags, side_name, turn_start_opp in (
            ("a", party1, idx1, party2, idx2, ai_a, name_a, turn_start_actives_b),
            ("b", party2, idx2, party1, idx1, ai_b, name_b, turn_start_actives_a)
        ):
            for slot in (0, 1):
                actor = slot_mon(party, idx_pair, slot)
                if actor is None or actor["hp"] <= 0 or (side_key, slot) in spent_action:
                    continue
                opponents = [m for m in actives(opp_party, opp_idx_pair) if m["hp"] > 0]
                if not opponents:
                    continue
                ally = slot_mon(party, idx_pair, 1 - slot)
                ally = ally if (ally is not None and ally["hp"] > 0) else None
                # Berry cure, then the AI picks whatever the mon's status (retail: the disruption stages run when its action comes up -
                # check_status_disruption in the execution loop below). Only a recharging mon is not asked (Battler_CanPickCommand).
                picks, speed_mult = process_status_start_turn(actor, rng, log, bstate)
                if not picks:
                    actions.append({"actor": actor, "slot": slot, "side": side_key, "side_name": side_name, "move_name": None,
                                     "mv": None, "targets": [], "speed_mult": speed_mult, "recharging": True})
                    continue
                primary_opponent = opponents[0]
                # Move CHOICE is scored against whoever was on the
                # opposing side when the turn began (falling back to the
                # current opponent if that Pokemon has since fainted
                # outright, e.g. from an earlier hazard/status tick this
                # same phase) - not the post-switch opponent, matching
                # real simultaneous turn resolution: this Pokemon decided
                # its move without knowing the other side was about to
                # switch. The move still executes against and damages
                # whoever ends up on the field, via the current
                # primary_opponent/opponents used everywhere below.
                choice_opponents = [m for m in turn_start_opp if m["hp"] > 0] or [primary_opponent]
                move_name, chosen_target = choose_move_and_target_double(
                    actor, choice_opponents, ally, ai_flags, bstate, rng, count_other_alive_party_members(party, idx_pair),
                    defender_other_alive_count=count_other_alive_party_members(opp_party, opp_idx_pair), attacker_party=party)
                if chosen_target is not None and not (chosen_target is ally or any(chosen_target is o for o in opponents)):
                    chosen_target = None        # it switched out or fainted since the turn began: re-aim by range below
                mv = get_effective_move_data(move_name, actor, defender=chosen_target or primary_opponent, bstate=bstate, rng=rng)
                targets = resolve_targets_double(mv, actor, chosen_target, ally, opponents, bstate, rng)
                actions.append({"actor": actor, "slot": slot, "side": side_key, "side_name": side_name, "move_name": move_name,
                                 "mv": mv, "targets": targets, "speed_mult": speed_mult})

        # --- turn order: priority first, then speed (with Trick Room
        # reversing the speed tiebreak, and Tailwind doubling it, exactly
        # as in singles), extended from 2 entries to up to 4 ---
        # the real battler order is P1, E1, P2, E2 (slot by slot, our side first), then the exchange sort of
        # BattleSystem_SortMonActionOrder
        actions.sort(key=lambda x: (x["slot"], 0 if x["side"] == "a" else 1))
        actions = [e[2] for e in order_actions([(x["actor"], x["mv"].get("priority", 0) if x["mv"] else (0 if x.get("recharging") else -99), x)
                                                for x in actions], bstate, rng)]

        # Mechanic C/D ("debuff"/"tailwind" turn-order-flip assists): per queued (actor, its own target) pair rather than one global
        # comparison, since up to 4 actors can be involved. actor["_turn_order_credit"] is always (re)set here (even to {}), so a note
        # from a mover that acted first last turn but never scored a KO off it can never leak into this turn.
        _action_index_by_actor = {id(a["actor"]): i for i, a in enumerate(actions)}
        for _i, _action in enumerate(actions):
            _actor = _action["actor"]
            _note_by_target = {}
            _mv = _action.get("mv")
            _actor_prio = _mv.get("priority", 0) if _mv else (0 if _action.get("recharging") else -99)
            for _target in _action.get("targets") or []:
                if _target is None or bstate["side_of"](_target) == bstate["side_of"](_actor):
                    continue
                _j = _action_index_by_actor.get(id(_target))
                if _j is None or _j <= _i:
                    continue            # target has no action this turn, or already resolved before actor - no flip to detect
                _target_action = actions[_j]
                _target_mv = _target_action.get("mv")
                _target_prio = _target_mv.get("priority", 0) if _target_mv else (0 if _target_action.get("recharging") else -99)
                if _actor_prio != _target_prio:
                    continue
                _note = {}
                _spe_src = (_target.get("debuff_source") or {}).get("spe")
                if _spe_src is not None and _target.get("spe_stage", 0) < 0:
                    _saved_spe = _target["spe_stage"]
                    _target["spe_stage"] = _saved_spe + _spe_src[3]
                    _flipped = _speed_compare(_actor, _target, bstate) == "SLOWER"
                    _target["spe_stage"] = _saved_spe
                    if _flipped:
                        _note["debuff"] = (_spe_src[0], _spe_src[1])
                _actor_side = bstate["side_of"](_actor)
                if bstate["sides"][_actor_side].get("tailwind", 0) > 0:
                    _saved_tw = bstate["sides"][_actor_side]["tailwind"]
                    bstate["sides"][_actor_side]["tailwind"] = 0
                    _flipped = _speed_compare(_actor, _target, bstate) == "SLOWER"
                    bstate["sides"][_actor_side]["tailwind"] = _saved_tw
                    if _flipped:
                        _tw_setter = bstate["sides"][_actor_side].get("tailwind_setter")
                        if _tw_setter is not None:
                            _note["tailwind"] = _tw_setter
                if _note:
                    _note_by_target[id(_target)] = _note
            _actor["_turn_order_credit"] = _note_by_target

        # --- execute in order ---
        def on_field(mon):
            return any(mon is m for m in actives(party1, idx1) + actives(party2, idx2))

        for action in actions:
            actor = action["actor"]
            if actor["hp"] <= 0 or (action["move_name"] is None and not action.get("recharging")):
                continue
            if not on_field(actor):
                continue        # force-switched / pivoted out earlier this turn: it doesn't get to act
            # BEFORE_MOVE_STATE_STATUS_DISRUPTION comes before the target check, the PP charge and the move's own script (see run_battle).
            already_acted = actor.get("acted_since_switch_in", False)      # Fake Out only works on a mon's first turn out
            actor["acted_since_switch_in"] = True
            actor["_acted_turn"] = bstate.get("turn", 1)
            actor["destiny_bond"] = False                                  # CHECK_STATUS_START
            actor["me_first"] = False
            if not check_status_disruption(actor, rng, log, action["move_name"], bstate):
                bstate["last_move_used"] = None                            # a prevented move attempt invalidates Copycat's last move
                actor["last_move_used"] = None
                continue
            if action["move_name"] is None:
                continue
            mv_name, mv = action["move_name"], action["mv"]
            # Re-validate targets: drop any that fainted (or left the field) earlier this
            # same turn, and for a single-target move whose one chosen target
            # died, retarget to the other opponent if one is still alive.
            targets = [t for t in action["targets"] if t["hp"] > 0 and on_field(t)]
            if not targets:
                if mv.get("range") == "RANGE_SINGLE_TARGET":
                    fallback = [m for m in actives(party2 if action["side"] == "a" else party1,
                                                    idx2 if action["side"] == "a" else idx1) if m["hp"] > 0]
                    if fallback:
                        targets = [fallback[0]]
                if not targets:
                    continue

            display_side_name = action["side_name"]
            _fm = (bstate.get("follow_me") or {}).get("b" if action["side"] == "a" else "a")
            if (_fm is not None and _fm["hp"] > 0 and on_field(_fm) and mv.get("range") in ("RANGE_SINGLE_TARGET", "RANGE_SINGLE_TARGET_SPECIAL")
                    and targets and targets[0] is not _fm and bstate["side_of"](targets[0]) != action["side"]):
                targets = [_fm]                                  # BattleSystem_Defender: Follow Me pulls single-target moves

            # --- Two-turn moves: Fly/Dig/Dive/Bounce vanish on turn 1, Solar Beam charges unless it is sunny. Turn 2 is
            # forced by _forced_or_usable_moves and resolves as a normal attack below. ---
            def charge_turn(state_key, state_value, verb_text):
                actor["move_hit"] = None
                log.append(f"  > {display_side_name}'s {actor['species_display']} uses {mv_name.replace('MOVE_', '').replace('_', ' ').title()}!")
                actor.setdefault("moves_used_this_stay", set()).add(mv_name)
                if mv_name != "MOVE_STRUGGLE" and mv_name in actor.get("move_pp", {}):
                    actor["move_pp"][mv_name] = max(0, actor["move_pp"][mv_name] - 1)
                    apply_pressure_extra_pp(actor, mv, mv_name, targets)
                actor[state_key] = state_value
                bstate["last_move_used"] = None         # a charging turn is not a valid Copycat move
                actor["last_move_used"] = None
                log.append(f"    {actor['species_display']} {verb_text}")

            if mv.get("charge_move") and actor.get("vanished") != mv["charge_move"]:
                charge_turn("vanished", mv["charge_move"], {"FLY": "flew up high!", "DIG": "burrowed underground!",
                                                            "DIVE": "hid underwater!", "BOUNCE": "sprang up!"}.get(mv["charge_move"], "vanished!"))
                continue
            if actor.get("vanished"):
                actor["vanished"] = None        # this IS turn 2 now
            if mv.get("solar_charge") and weather_now(bstate) != "SUN" and not actor.get("charging_solar_beam"):
                charge_turn("charging_solar_beam", True, "took in sunlight!")
                continue
            if actor.get("charging_solar_beam"):
                actor["charging_solar_beam"] = None

            if bstate.get("snatchers") and mv.get("class") == "CLASS_STATUS" and mv.get("effect") != "SNATCH" \
                    and mv_name not in SNATCH_EXCLUDED_MOVES and actor not in bstate["snatchers"]:
                # Same "only the slowest waiting snatcher catches it" rule
                # as singles - see that implementation's fuller comment.
                snatcher = bstate["snatchers"].pop()
                if snatcher["hp"] > 0:
                    original_user = actor
                    log.append(f"    {snatcher['species_display']} snatched {original_user['species_display']}'s move!")
                    if mv_name == "MOVE_PSYCH_UP":
                        targets = [original_user]
                    elif mv_name == "MOVE_ACUPRESSURE" or targets == [original_user]:
                        targets = [snatcher]
                    # else: a foe-targeted move keeps its original target(s)
                    actor = snatcher
                    display_side_name = name_a if bstate["side_of"](actor) == "a" else name_b

            if mv_name != "MOVE_STRUGGLE" and mv_name in actor.get("move_pp", {}):
                actor["move_pp"][mv_name] = max(0, actor["move_pp"][mv_name] - 1)
                apply_pressure_extra_pp(actor, mv, mv_name, targets)
            actor["acted_since_switch_in"] = True
            log.append(f"  > {display_side_name}'s {actor['species_display']} uses "
                       f"{mv_name.replace('MOVE_', '').replace('_', ' ').title()}!")
            _slot_of_actor = next((sl for prt, ip in ((party1, idx1), (party2, idx2)) for sl in (0, 1)
                                   if slot_mon(prt, ip, sl) is actor), 0)
            actor["move_hit"] = None
            actor["_acted_turn"] = bstate.get("turn", 1)
            for _t in targets:
                note_move_used_on(actor, _t, mv_name, mv, _slot_of_actor)
            if mv_name == "MOVE_HELPING_HAND":
                # Helping Hand: the ally's damaging move this turn gets x1.5 power - it fails if the ally already acted
                _ht = targets[0] if targets else None
                if _ht is not None and _ht is not actor and _ht["hp"] > 0 and _ht.get("_acted_turn") != bstate.get("turn", 1):
                    _ht["helping_hand"] = True
                    log.append(f"    {actor['species_display']} is ready to help {_ht['species_display']}!")
                else:
                    log.append("    But it failed!")
            actor.setdefault("moves_used_this_stay", set()).add(mv_name)

            # --- preconditions that make a move fail outright (see the matching block in run_battle) ---
            _own_party, _own_idx = (party1, idx1) if action["side"] == "a" else (party2, idx2)
            _foe_party, _foe_idx = (party2, idx2) if action["side"] == "a" else (party1, idx1)
            _foes = [m for m in actives(_foe_party, _foe_idx) if m["hp"] > 0]
            _ally = next((m for m in actives(_own_party, _own_idx) if m is not actor and m["hp"] > 0), None)
            _t0 = targets[0] if targets else None
            _t0_action = next((x for x in actions if x["actor"] is _t0), None)
            _called_name, _called_mv, _called_ok = resolve_called_move(actor, mv_name, mv, _t0, bstate, rng, log, _own_party,
                                                                       target_selected=(_t0_action["move_name"] if _t0_action else None))
            if _called_ok and _called_name != mv_name and _foes:
                mv_name, mv = _called_name, _called_mv
                targets = resolve_targets_double(mv, actor, targets[0] if targets else None, _ally, _foes, bstate, rng)
            precheck_failed = not _called_ok
            damp_blocked = bool(mv.get("self_destruct")) and _damp_blocks(actor, bstate)
            if damp_blocked:
                precheck_failed = True
                log.append(f"    {actor['species_display']} can't use {mv_name.replace('MOVE_', '').replace('_', ' ').title()} because of Damp!")
            if mv.get("sucker_punch"):
                _tgt = targets[0]
                _t_action = next((x for x in actions if x["actor"] is _tgt), None)
                _t_mv = _t_action["mv"] if _t_action else None
                if not _t_mv or _t_mv.get("class") == "CLASS_STATUS" or _t_mv.get("power", 0) <= 0 \
                        or _tgt.get("_acted_turn") == bstate.get("turn", 1):
                    precheck_failed = True
            if mv.get("fake_out") and already_acted:
                precheck_failed = True
            if _real_effect(mv_name) == "BATTLE_EFFECT_DAMAGE_WHILE_ASLEEP" and actor.get("status") != "SLEEP":
                precheck_failed = True                                     # Snore only works while the user is asleep
            if mv.get("class") == "CLASS_STATUS" and actor.get("taunt_turns", 0) > 0:
                precheck_failed = True
            if mv.get("effect") == "LAST_RESORT":
                _known = actor.get("moves", [])
                _others = [m for m in _known if m != "MOVE_LAST_RESORT"]
                _used = actor.get("moves_used_this_stay", set())
                if "MOVE_LAST_RESORT" not in _known or not _others or not all(m in _used for m in _others):
                    precheck_failed = True
            failed_mv = mv
            if precheck_failed:
                log.append("    But it failed!")
                mv = {"name": mv_name, "class": "CLASS_STATUS", "range": "RANGE_USER"}      # inert: the chain below falls to its plain branch

            # --- Copycat/Mimic: same mechanics as singles (see there for
            # the fuller explanation), simplified for doubles - Copycat
            # resolves against whatever target(s) it had already been
            # assigned rather than re-deriving targets for the copied
            # move's own range, and Mimic only ever targets a single
            # Pokemon (it's RANGE_SINGLE_TARGET), matching targets[0]. ---
            handled_specially = precheck_failed
            if mv.get("effect") == "SLEEP_TALK":
                eligible = [m for m in actor.get("moves", []) if m not in SLEEP_TALK_EXCLUDED_MOVES]
                if actor.get("status") != "SLEEP" or not eligible:         # effect script: CompareMonData FLAG_NOT sleep -> failed
                    log.append("    But it failed!")
                    handled_specially = True
                else:
                    called_move = rng.choice(eligible)
                    mv = get_effective_move_data(called_move, actor, defender=(targets[0] if targets else None),
                                                  bstate=bstate, rng=rng)
                    mv_name = called_move
                    bstate["last_move_used"] = mv_name
                    actor["last_move_used"] = mv_name
                    log.append(f"    {actor['species_display']}'s Sleep Talk called "
                               f"{called_move.replace('MOVE_', '').replace('_', ' ').title()}!")
            if mv.get("copycat"):
                last_move = bstate.get("last_move_used")
                if not last_move:
                    log.append("    But it failed!")
                    handled_specially = True
                else:
                    mv = get_effective_move_data(last_move, actor, defender=(targets[0] if targets else None),
                                                  bstate=bstate, rng=rng)
                    mv_name = last_move
                    bstate["last_move_used"] = mv_name
                    actor["last_move_used"] = mv_name
            elif mv.get("mimic"):
                handled_specially = True
                mimic_target = targets[0] if targets else None
                target_move = mimic_target.get("last_move_used") if mimic_target else None
                mimic_idx = actor["moves"].index("MOVE_MIMIC") if "MOVE_MIMIC" in actor.get("moves", []) else None
                if (not mimic_target or mimic_target.get("vanished") or not target_move
                        or target_move in MIMIC_EXCLUDED_MOVES or target_move in actor.get("moves", [])
                        or mimic_idx is None):
                    log.append("    But it failed!")
                else:
                    actor["moves"][mimic_idx] = target_move
                    actor["move_pp"][target_move] = 5
                    actor["mimic_active_move"] = target_move
                    copied_display = target_move.replace("MOVE_", "").replace("_", " ").title()
                    log.append(f"    {actor['species_display']} learned {copied_display}!")
                bstate["last_move_used"] = "MOVE_MIMIC"
                actor["last_move_used"] = "MOVE_MIMIC"
            elif mv.get("effect") == "TRANSFORM":
                handled_specially = True
                tf_target = targets[0] if targets else None
                if tf_target is None or tf_target.get("vanished"):
                    log.append("    But it failed!")
                else:
                    if not actor.get("pre_transform"):
                        actor["pre_transform"] = {
                            "species": actor.get("species"), "species_display": actor.get("species_display"),
                            "type1": actor.get("type1"), "type2": actor.get("type2"), "types": list(actor.get("types", [])),
                            "ability": actor.get("ability"), "atk": actor.get("atk"), "def": actor.get("def"),
                            "spa": actor.get("spa"), "spd": actor.get("spd"), "spe": actor.get("spe"),
                            "atk_stage": actor.get("atk_stage", 0), "def_stage": actor.get("def_stage", 0),
                            "spa_stage": actor.get("spa_stage", 0), "spd_stage": actor.get("spd_stage", 0),
                            "spe_stage": actor.get("spe_stage", 0), "acc_stage": actor.get("acc_stage", 0),
                            "eva_stage": actor.get("eva_stage", 0),
                            "moves": list(actor.get("moves", [])), "move_pp": dict(actor.get("move_pp", {})),
                        }
                    actor["species"] = tf_target.get("species")
                    actor["species_display"] = tf_target.get("species_display")
                    actor["type1"] = tf_target.get("type1")
                    actor["type2"] = tf_target.get("type2")
                    actor["types"] = list(tf_target.get("types", []))
                    actor["ability"] = tf_target.get("ability")
                    ai_reveal_ability(actor)
                    actor["atk"] = tf_target.get("atk")
                    actor["def"] = tf_target.get("def")
                    actor["spa"] = tf_target.get("spa")
                    actor["spd"] = tf_target.get("spd")
                    actor["spe"] = tf_target.get("spe")
                    actor["atk_stage"] = tf_target.get("atk_stage", 0)
                    actor["def_stage"] = tf_target.get("def_stage", 0)
                    actor["spa_stage"] = tf_target.get("spa_stage", 0)
                    actor["spd_stage"] = tf_target.get("spd_stage", 0)
                    actor["spe_stage"] = tf_target.get("spe_stage", 0)
                    actor["acc_stage"] = tf_target.get("acc_stage", 0)
                    actor["eva_stage"] = tf_target.get("eva_stage", 0)
                    new_moves = list(tf_target.get("moves", []))
                    actor["moves"] = new_moves
                    new_pp = {}
                    for m in new_moves:
                        max_pp = get_move_data_by_name(m).get("pp", 5)
                        new_pp[m] = min(5, max_pp)
                    actor["move_pp"] = new_pp
                    actor["transformed"] = True
                    log.append(f"    {actor['species_display']} transformed into {tf_target['species_display']}!")
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name
            elif mv.get("effect") == "PAIN_SPLIT":
                handled_specially = True
                ps_target = targets[0] if targets else None
                if ps_target is None or ps_target.get("vanished") or _substituted(ps_target):
                    log.append("    But it failed!")
                else:
                    shared_hp = (actor["hp"] + ps_target["hp"]) // 2
                    actor["hp"] = min(actor["max_hp"], shared_hp)
                    ps_target["hp"] = min(ps_target["max_hp"], shared_hp)
                    log.append(f"    {actor['species_display']} shared its pain with {ps_target['species_display']}!")
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name
            elif mv.get("effect") == "FUTURE_SIGHT":
                handled_specially = True
                fs_target = targets[0] if targets else None
                if fs_target is None or not start_future_sight(actor, fs_target, mv, mv_name, bstate, rng, log):
                    log.append("    But it failed!")
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name
            elif mv.get("effect") == "WISH":
                handled_specially = True
                if not start_wish(actor, bstate, log):
                    log.append("    But it failed!")
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name
            elif mv.get("effect") == "NATURAL_GIFT":
                if not item_effects_active(actor):
                    log.append("    But it failed!")
                    handled_specially = True
                else:
                    ng_item = actor.get("item")
                    ng_info = get_item_info(ng_item) if ng_item else None
                    if not ng_item or not ng_info.get("is_berry") or ng_info.get("natural_gift_power", 0) <= 0:
                        log.append("    But it failed!")
                        handled_specially = True
                    else:
                        mv = dict(mv, power=ng_info["natural_gift_power"],
                                  type=ng_info.get("natural_gift_type") or mv.get("type"))
                        actor["item"] = None
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name
            elif mv.get("effect") == "FLING":
                if not item_effects_active(actor):
                    log.append("    But it failed!")
                    handled_specially = True
                else:
                    fling_item = actor.get("item")
                    if not fling_item:
                        log.append("    But it failed!")
                        handled_specially = True
                    else:
                        item_info = get_item_info(fling_item)
                        fling_power = item_info.get("fling_power", 0)
                        fling_effect = item_info.get("fling_effect", "FLING_EFFECT_NONE")
                        actor["item"] = None
                        if fling_power <= 0:
                            log.append("    But it failed!")
                            handled_specially = True
                        else:
                            status_map = {"FLING_EFFECT_BURN": "BURN", "FLING_EFFECT_PARALYZE": "PARALYZE",
                                          "FLING_EFFECT_POISON": "POISON", "FLING_EFFECT_BADLY_POISON": "TOXIC"}
                            new_mv = dict(mv, power=fling_power)
                            if fling_effect == "FLING_EFFECT_FLINCH":
                                new_mv["secondary"] = {"effect": "FLINCH", "chance": 1.0}
                            elif fling_effect in status_map:
                                new_mv["secondary"] = {"effect": status_map[fling_effect], "chance": 1.0}
                            mv = new_mv
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name
            elif mv.get("bide"):
                handled_specially = True
                _bide_double(actor, targets[0] if targets else None, mv, mv_name, bstate, log, ko_events, trainer_of)
            elif mv.get("effect") in ("COUNTER", "MIRROR_COAT", "METAL_BURST"):
                _cs = counter_source(actor, mv["effect"], bstate)
                if _cs is None:
                    log.append("    But it failed!")
                    handled_specially = True
                else:
                    _src = _cs[0]
                    _fm2 = (bstate.get("follow_me") or {}).get(bstate["side_of"](_src))
                    targets = [_fm2 if (_fm2 is not None and _fm2["hp"] > 0 and on_field(_fm2)) else _src]     # Follow Me takes it
                    mv = dict(mv, fixed_damage=max(1, _cs[1]), power=1)
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name
            else:
                bstate["last_move_used"] = mv_name
                actor["last_move_used"] = mv_name

            if precheck_failed:
                mv = failed_mv
            spread_hit = len(targets) > 1
            connected_any = False
            if not handled_specially:
                for target in targets:
                    if actor["hp"] <= 0:
                        break
                    _fainted, _connected = _resolve_hit_double(actor, target, mv, mv_name, bstate, rng, log, spread_hit, ko_events, trainer_of)
                    connected_any = connected_any or _connected
            missed = precheck_failed or (not handled_specially and not connected_any)
            _post_move_effects_double(actor, targets, mv, mv_name, missed, party1, party2, idx1, idx2, name_a, name_b, bstate, rng, log,
                                      damp_blocked=damp_blocked)
            for holder in [actor] + [t for t in targets if t is not actor]:      # attacker's item, then each defender's (hit or not)
                if on_field(holder):
                    use_held_item(holder, log)

            if actor.get("grudge_active") and mv.get("effect") != "GRUDGE":
                actor["grudge_active"] = False
            if actor.get("charged") and not mv.get("charges_electric"):
                actor["charged"] = False

            if actor["hp"] <= 0 and not actor.get("_fainted_already_logged"):
                log.append(f"  X {actor['species_display']} fainted!\n")
                actor["_fainted_already_logged"] = True
                resolve_faint_credit(bstate, actor)
                revert_mimicked_move(actor)
                revert_transform(actor)

            # Vacate (but do NOT fill) whichever slot(s) just lost a Pokemon - Gen4 always defers a fainted mon's
            # replacement until after the entire end-of-turn sequence finishes for the turn it fainted in, same as
            # the EOT-phase-faint case already does (see _replace_fainted_slots' own docstring). The post-EOT call
            # below is the only place either slot actually gets refilled.
            _replace_fainted_slots(party1, idx1, "a", lambda: actives(party2, idx2), fill=False)
            _replace_fainted_slots(party2, idx2, "b", lambda: actives(party1, idx1), fill=False)
            if not (_alive(party1) and _alive(party2)):      # BattleControllerPlayer_MoveEnd -> CheckBattleOver: nothing else happens this turn
                break

        # --- end of turn: status/weather/ability processing for every
        # currently-active combatant, then side-wide countdowns once per
        # side (unaffected by how many Pokemon are on it) ---
        for mon in actives(party1, idx1) + actives(party2, idx2):
            mon["protected"] = False
            mon["flinched"] = False                                        # BattleSystem_SetupNextTurn: a flinch lasts only for its own turn
        bstate["snatchers"] = []
        bstate["follow_me"] = {}
        # Each step runs for the battlers in SPEED order (monSpeedOrder; Trick Room reversed) and the battle is re-checked between steps
        # (CheckBattleOver): once a side is out the survivors are not touched by the steps still to come.
        over = lambda: not (_alive(party1) and _alive(party2))
        eot = [e[2] for e in order_actions([(m, 0, m) for m in actives(party1, idx1) + actives(party2, idx2)], bstate, rng)]
        for mon in eot:
            if not over():
                process_weather_end_turn(mon, bstate, log)
        if bstate.get("pending_weather"):
            bstate["weather"], bstate["weather_turns"] = bstate.pop("pending_weather")
        # Future Sight / Doom Desire / Wish: per slot, resolved against whoever occupies it now (see resolve_delayed_moves_end_turn)
        if not over():
            resolve_delayed_moves_end_turn(bstate, log, rng)
        for mon in eot:
            if mon["hp"] > 0 and not over():
                foes = actives(party2, idx2) if bstate["side_of"](mon) == "a" else actives(party1, idx1)
                process_status_end_turn(mon, next(iter(foes), None), bstate, log)
                process_end_of_turn_abilities(mon)

        side_names = {"a": name_a, "b": name_b}
        for side_key, side in bstate["sides"].items():
            for key in ("reflect", "light_screen", "tailwind"):
                if side[key] > 0:
                    side[key] -= 1
            if side.get("mist", 0) > 0:
                side["mist"] -= 1
                if side["mist"] == 0:
                    log.append(f"    {side_names[side_key]}'s team is no longer protected by Mist!")
            if side.get("lucky_chant", 0) > 0:
                side["lucky_chant"] -= 1
                if side["lucky_chant"] == 0:
                    log.append(f"    {side_names[side_key]}'s Lucky Chant wore off!")
        if bstate.get("trick_room", 0) > 0:
            bstate["trick_room"] -= 1
            if bstate["trick_room"] == 0:
                log.append("    The twisted dimensions returned to normal!")
        if bstate.get("gravity", 0) > 0:
            bstate["gravity"] -= 1
            if bstate["gravity"] == 0:
                log.append("    Gravity returned to normal!")
        for mon in actives(party1, idx1) + actives(party2, idx2):
            if mon.get("safeguard", 0) > 0:
                mon["safeguard"] -= 1
        if bstate["weather_turns"] > 0:
            bstate["weather_turns"] -= 1
            if bstate["weather_turns"] == 0:
                weather_end_msg = {"SUN": "The sunlight faded!", "RAIN": "The rain stopped!",
                                    "SANDSTORM": "The sandstorm subsided!", "HAIL": "The hail stopped!"}.get(bstate["weather"])
                if weather_end_msg:
                    log.append(f"    {weather_end_msg}")
                bstate["weather"] = "NONE"
        log.append("")
        # Fainted slots (from the end-of-turn damage just applied above)
        # are replaced only now - the replacement's own switch-in ability
        # (Sand Stream, Intimidate, etc.) still triggers and logs, but a
        # newly-set weather doesn't retroactively deal damage to anyone
        # else this same turn, only from the following turn on.
        if not _alive(party1) and not _alive(party2):
            for mon in eot:                          # both sides are out: number the still unlogged faints in speed order (see decide_double_ko)
                if mon["hp"] <= 0 and not mon.get("_fainted_already_logged"):
                    log.append(f"  X {mon['species_display']} fainted!\n")
                    mon["_fainted_already_logged"] = True
                    revert_mimicked_move(mon)
                    revert_transform(mon)
                    resolve_faint_credit(bstate, mon)
        _replace_fainted_slots(party1, idx1, "a", lambda: actives(party2, idx2))
        _replace_fainted_slots(party2, idx2, "b", lambda: actives(party1, idx1))

    alive_a, alive_b = _alive(party1), _alive(party2)
    if alive_a and alive_b:
        remaining_a = sum(1 for p in party1 if p["hp"] > 0)
        remaining_b = sum(1 for p in party2 if p["hp"] > 0)
        if remaining_a != remaining_b:
            winner = trainer_a if remaining_a > remaining_b else trainer_b
        else:
            hp_a = sum(max(0, p["hp"]) for p in party1)
            hp_b = sum(max(0, p["hp"]) for p in party2)
            winner = trainer_a if hp_a >= hp_b else trainer_b
        log.append(f"=== TURN LIMIT REACHED ({MAX_BATTLE_TURNS} turns) - decided by Pokemon/HP remaining ===")
    elif not alive_a and not alive_b:
        side, reason = decide_double_ko(party1, party2, rng)
        winner = trainer_a if side == "a" else trainer_b
        log.append(f"=== DOUBLE KO - {reason} ===")
    else:
        winner = trainer_a if alive_a else trainer_b
    log.append(f"=== WINNER: {DISPLAY_NAMES.get(winner, winner)} ===")
    os.makedirs(f"tournament_results{OUTPUT_SUFFIX}", exist_ok=True)
    log_filename = f"tournament_results{OUTPUT_SUFFIX}/{safe_filename(name_a)}_vs_{safe_filename(name_b)}_game{game_num}.txt"
    log_text = "\n".join(log)
    with open(log_filename, "w", encoding="utf-8") as f:
        f.write(log_text)

    loser = trainer_b if winner == trainer_a else trainer_a
    winner_party = party1 if winner == trainer_a else party2
    game_stats = {
        "seed": seed,
        "game_num": game_num,
        "winner": winner,
        "loser": loser,
        "turns": turns,
        "winner_remaining_hp": sum(max(0, p["hp"]) for p in winner_party),
        "knockouts": ko_events,
        "secondary_roll_events": bstate.get("_analytics_secondary_roll_events", ()),
        "damaging_hit_events": bstate.get("_analytics_damaging_hit_events", ()),
        "assist_events": bstate.get("_analytics_assist_events", ()),
        "log_file": log_filename,
        # Keep the already-built lines in memory for analytics. The old
        # pipeline reopened every log file immediately after writing it,
        # creating thousands of avoidable disk reads.
        "log_lines": log,
    }
    return winner, turns, game_stats


# ============================================================
# BEST-OF-3 MATCH + ROUND ROBIN TOURNAMENT
# ============================================================
def run_match(trainer_a, trainer_b, seed_base):
    """Plays a "Tiebreak" format match: after every game, the match ends
    as soon as one side's LEAD reaches 2 games (2-0, 3-1, 4-2, ...), or
    once 7 games total have been played, whichever comes first - the
    same shape as a "win by 2" rule (table tennis, volleyball). A score
    like 2-1 or 3-2 is only ever a PASSING state on the way to a 2-game
    lead, never how the match actually ends, UNLESS the 7-game cap is
    hit first: starting from a 3-3 tie at game 6, game 7 is forced to
    produce a final 4-3 (lead of only 1), which still ends the match
    purely because the cap has been reached, not because of the lead
    itself. Resets each Pokemon's HP/status/stat-stages fresh every game
    since it's a new battle. Returns the ordered list of per-game winner
    keys (not just an aggregate count) so the caller can apply Elo/
    upset-tracking in the order the games actually happened, plus a
    parallel list of per-game telemetry dicts (see run_battle's
    game_stats return value) for the CSV/JSON/Reddit export pipeline.

    The battle format (singles or doubles - see determine_battle_format)
    is decided ONCE for the whole match, not per game: it depends only on
    each trainer's party size and double_battle flag plus the tournament-
    wide TOURNAMENT_BATTLE_MODE, none of which change between games of
    the same match."""
    battle_fn = run_battle_double if determine_battle_format(
        TRAINERS_DB[trainer_a]["party"], TRAINERS_DB[trainer_b]["party"], TOURNAMENT_BATTLE_MODE,
        TRAINERS_DB[trainer_a].get("double_battle", False), TRAINERS_DB[trainer_b].get("double_battle", False),
    ) == "doubles" else run_battle

    MAX_GAMES = 7
    LEAD_NEEDED = 2
    wins_a = wins_b = 0
    game_num = 0
    total_turns = 0
    game_results = []
    game_stats_list = []
    while game_num < MAX_GAMES:
        game_num += 1
        winner, turns, game_stats = battle_fn(trainer_a, trainer_b, seed=seed_base + game_num, game_num=game_num)
        total_turns += turns
        game_results.append(winner)
        game_stats_list.append(game_stats)
        if winner == trainer_a:
            wins_a += 1
        else:
            wins_b += 1

        if abs(wins_a - wins_b) >= LEAD_NEEDED or game_num >= MAX_GAMES:
            break

    match_winner = trainer_a if wins_a > wins_b else trainer_b
    return match_winner, wins_a, wins_b, game_num, total_turns, game_results, game_stats_list


def compute_k_factor(games_played):
    """Adaptive K-factor, used instead of one flat constant for a trainer's
    entire ~900-opponent round robin.

    Why not just a flat K=4 (the naive fix for the old K=32 runaway
    inflation)? A flat K is a real trade-off: small enough to avoid
    long-run drift, but that same smallness makes EVERY trainer converge
    from the shared 1500 starting point agonizingly slowly, so ratings
    stay clustered and uninformative for a long stretch of the
    tournament. Real rating systems (USCF/FIDE) solve this the same way:
    a bigger K while a player's rating is still "provisional" (few games
    played) so it corrects quickly from an uninformative starting value,
    then a smaller, stable K once there's enough of a track record that
    big swings would do more harm (noise) than good (signal). With a
    full round robin this large, only a trainer's first few dozen games
    are "provisional" - the remaining ~800+ all settle into the flattest,
    most stable band, which is exactly where the earlier flat-K=4 idea
    already wanted to end up. This keeps that stability while fixing the
    slow-convergence trade-off.

        games_played < 20   -> K = 24  (provisional: converge fast)
        games_played < 60   -> K = 12  (settling)
        games_played >= 60  -> K = 4   (long-run stable floor)

    Note this makes individual updates slightly asymmetric (the two
    sides of a game can move by different amounts, since each uses its
    OWN games-played count), so the pairwise zero-sum property the old
    flat-K system relied on no longer holds exactly. That's fine here:
    the tier list is now calibrated from the tournament's ACTUAL final
    Elo distribution (see compute_tier_thresholds) rather than assuming
    the population mean stays pinned at exactly 1500, so it isn't
    sensitive to that small amount of drift.
    """
    if games_played < 20:
        return 24
    if games_played < 60:
        return 12
    return 4


def update_elo(w_rat, l_rat, k_w=4, k_l=4):
    """Updates both ratings from one game's result. k_w/k_l are each
    side's OWN K-factor (see compute_k_factor) - they need not match, the
    same way a veteran and a newcomer can reasonably move by different
    amounts off the same result. Defaults to a flat k=4 for both sides
    when called without explicit per-trainer K's."""
    exp_w = 1 / (1 + 10 ** ((l_rat - w_rat) / 400))
    exp_l = 1 / (1 + 10 ** ((w_rat - l_rat) / 400))
    return round(w_rat + k_w * (1 - exp_w), 1), round(l_rat + k_l * (0 - exp_l), 1)


# ============================================================
# ELO TIER LIST (S+ down to F-, just for fun)
# ============================================================
# The tier table is built from the tournament's ACTUAL final Elo
# distribution (see compute_tier_thresholds) rather than a hardcoded band
# width, so it isn't tied to one particular K-factor's typical spread.
#
# The first version of this self-calibrating table placed thresholds at
# even standard-deviation steps from the mean, which implicitly assumes
# the ratings end up roughly normally distributed. They don't: a full
# roster runs from Level 5 Youngsters up through a Level 100 Champion, so
# the real final-Elo distribution is heavily skewed, with a long tail of
# strong postgame trainers pulling the standard deviation up far past
# where most of the roster actually sits. In one real run this left only
# 7 of the 18 tiers (B+ through D+) ever populated - every S-tier and
# everything below D+ sat empty, because "N standard deviations above
# the mean" landed above literally every trainer's rating on one end, and
# below literally everyone's on the other.
#
# Tiering by PERCENTILE RANK instead of by distance-from-mean fixes this
# unconditionally: sort every final rating and slice the sorted list into
# 18 equal-sized bands. However skewed or lopsided the real skill spread
# turns out to be, exactly (about) 1/18th of the roster lands in each
# tier by construction - there's no distributional assumption left to
# violate.
TIER_NAMES_DESCENDING = [
    "S+", "S", "S-", "A+", "A", "A-", "B+", "B", "B-",
    "C+", "C", "C-", "D+", "D", "D-", "E+", "E", "E-", "F+", "F", "F-",
]

# The 5% Micro-Tier System: each tier's threshold is a PERCENTILE RANK
# (from the top of the field, by Elo) a trainer must meet or exceed to
# qualify - not an equal division of the roster the way the old system
# worked. S+ is a narrow top-1% band; every other named tier down
# through F is a flat 5% band; F- is simply everyone below the bottom 5%
# (0.0 threshold, since it needs to catch everything the rest of the
# table doesn't).
TIER_PERCENTILE_THRESHOLDS = [
    ("S+", 0.99), ("S", 0.95), ("S-", 0.90),
    ("A+", 0.85), ("A", 0.80), ("A-", 0.75),
    ("B+", 0.70), ("B", 0.65), ("B-", 0.60),
    ("C+", 0.55), ("C", 0.50), ("C-", 0.45),
    ("D+", 0.40), ("D", 0.35), ("D-", 0.30),
    ("E+", 0.25), ("E", 0.20), ("E-", 0.15),
    ("F+", 0.10), ("F", 0.05), ("F-", 0.0),
]


def compute_tier_thresholds(elo_values, tier_names=None):
    """Builds an (elo_threshold, tier_name) table, highest threshold
    first, from the 5% Micro-Tier System's FIXED percentile bands
    (TIER_PERCENTILE_THRESHOLDS) - not equal-sized buckets. A trainer at
    0-indexed rank r (0 = highest Elo) out of n total has percentile
    rank (n - r) / n; solving "(n - r) / n >= pct" for the largest valid
    (i.e. lowest-Elo) r gives r <= n * (1 - pct), so each tier's Elo
    threshold is the value sitting at rank floor(n * (1 - pct)) in the
    Elo-descending sort. With ties at that boundary, everyone sharing
    that exact Elo value still qualifies (get_elo_tier compares with
    >=), which is intentional - "meets or exceeds a percentile" should
    include ties at the boundary rather than arbitrarily excluding some
    of them. Falls back to a single middle-tier band if there's nothing
    to rank (an empty roster)."""
    tier_names = tier_names if tier_names is not None else TIER_NAMES_DESCENDING
    n = len(elo_values)
    if n == 0:
        return [(float("-inf"), tier_names[len(tier_names) // 2])]

    sorted_desc = sorted(elo_values, reverse=True)
    wanted = set(tier_names)
    table = []
    for name, pct in TIER_PERCENTILE_THRESHOLDS:
        if name not in wanted:
            continue
        rank = min(n - 1, max(0, int(n * (1.0 - pct) + 1e-9)))
        table.append((sorted_desc[rank], name))
    table[-1] = (float("-inf"), table[-1][1])  # bottom tier catches everything below the lowest band
    return table


def get_elo_tier(elo, tier_table):
    """tier_table must come from compute_tier_thresholds - there's no more
    module-level default, since a sensible table can only be built AFTER
    the tournament's final Elo distribution is known."""
    for threshold, tier in tier_table:
        if elo >= threshold:
            return tier
    return tier_table[-1][1] if tier_table else "F-"  # unreachable if table is well-formed, but safe


def new_standing_entry():
    return {
        "match_wins": 0, "match_losses": 0, "game_wins": 0, "game_losses": 0, "elo": 1500.0,
        "elo_games": 0,  # how many rated games this trainer has played so far - feeds compute_k_factor
        "best_win": {"opponent": None, "opponent_elo": None},
        "worst_loss": {"opponent": None, "opponent_elo": None},
        # Raw sets of opponent keys beaten/lost to, recorded as the
        # tournament plays out - resolved into best_win/worst_loss using
        # each opponent's FINAL Elo only once the whole tournament (and
        # therefore every trainer's rating) is settled. See
        # resolve_best_win_worst_loss.
        "beaten_opponents": set(), "lost_to_opponents": set(),
        # This trainer's own single longest match BY GAME COUNT (not
        # turns - see the tournament-wide "longest_match"/"longest_battle"
        # trackers elsewhere for the turn-based ones) - which opponent it
        # was against and how many games that match went, computed
        # directly as the tournament plays out since (unlike best_win/
        # worst_loss) it doesn't depend on anyone's final Elo.
        "longest_match_games": 0, "longest_match_opponent": None,
    }


# The species token is matched lazily (.+?) rather than \S+: species_display has spaces for Mr. Mime, Mime Jr., Porygon-Z and Nidoran M/F,
# and a \S+ token made every one of their log lines (moves, faints, switches, items...) invisible to the analytics.
_LOG_TEAM_HEADER_RE = re.compile(r"^(.+?)'s team:$")
_LOG_ROSTER_LINE_RE = re.compile(r"^  Lv\. \d+ (.+?) \((.+?)\)(?: @ .+?)?: (.+)$")
_LOG_TURN_RE = re.compile(r"^--- Turn (\d+) ---$")
_LOG_TURN_STATE_RE = re.compile(r"^(.+?)'s Lv\. \d+ (.+?) \(HP: [\d/]+\) vs (.+?)'s Lv\. \d+ (.+?) \(HP: [\d/]+\)$")
_LOG_DOUBLE_SIDE_RE = re.compile(r"^(.+?)'s side: (.+)$")
_LOG_DOUBLE_MON_RE = re.compile(r"Lv\. \d+ (.+?) \(HP: [\d/]+\)")
_LOG_MOVE_USE_RE = re.compile(r"^  > (.+?)'s (.+?) uses (.+?)!$")
_LOG_MIMIC_LEARN_RE = re.compile(r"^    (.+?) learned (.+?)!$")
_LOG_FAINT_RE = re.compile(r"^  X (.+?) fainted!$")
_LOG_VOLUNTARY_SWITCH_RE = re.compile(r"^  (.+?) withdraws (.+?) and sends out (.+?)!$")
_LOG_SEND_OUT_RE = re.compile(r"^  -> (.+?) sends out (.+?)!$")
_LOG_DOUBLE_MISS_RE = re.compile(r"^\s+Attack on (.+?) missed!$")
_LOG_SINGLE_DAMAGE_RE = re.compile(r"^\s+Dealt (\d+) damage!")
_LOG_DOUBLE_DAMAGE_RE = re.compile(r"^\s+Dealt (\d+) damage to (.+?)!")
_LOG_MULTI_HIT_DAMAGE_RE = re.compile(r"^\s+Hit (\d+) times?! Dealt (\d+) damage total!")
_LOG_BIDE_DAMAGE_RE = re.compile(r"^\s+(.+?) unleashed its energy! Dealt (\d+) damage!")
_LOG_DELAYED_STRIKE_RE = re.compile(r"^\s+(.+?)'s (Future Sight|Doom Desire) struck (.+?)!$")
_LOG_ITEM_USED_RE = re.compile(r"^\s+.+? consumed/used its (.+)!$")
_LOG_ITEM_CURE_RE = re.compile(r"^\s+.+?'s (.+?) cured its status!$")
_LOG_ITEM_WEAKEN_RE = re.compile(r"^\s+.+?'s (.+?) weakened the attack!$")
_LOG_ITEM_WHITE_HERB_RE = re.compile(r"^\s+.+?'s (White Herb) restored its stats!$")


def _analytics_species_name(species):
    """Normalizes SPECIES_GARCHOMP / GARCHOMP to the log-facing GARCHOMP form."""
    return (species or "UNKNOWN").replace("SPECIES_", "").replace("_", " ")


def _analytics_ident(trainer_key, species):
    species_name = _analytics_species_name(species)
    return f"{trainer_key}_{species_name.title().replace(' ', '')}"


def count_item_activations(log_lines):
    """Counts consumable held-item activations from an in-memory battle log.

    The simulator emits distinct messages for threshold berries, status-cure
    berries, type-resist berries, and White Herb. Parsing these already-built
    lines avoids touching the filesystem and keeps the item metric independent
    of battle-engine branches that consume an item.
    """
    counts = Counter()
    for line in log_lines:
        m = _LOG_ITEM_USED_RE.match(line)
        if not m:
            m = _LOG_ITEM_CURE_RE.match(line)
        if not m:
            m = _LOG_ITEM_WEAKEN_RE.match(line)
        if not m:
            m = _LOG_ITEM_WHITE_HERB_RE.match(line)
        if m:
            counts[m.group(1).strip()] += 1
    return counts


def parse_battle_log_for_analytics(log_source, trainer_a_key, trainer_a_name, trainer_b_key, trainer_b_name):
    """Parse one already-generated battle log entirely in memory.

    The fast path accepts the engine's list of log lines directly; a text
    string is supported for compatibility. Regexes are module-level and
    precompiled. The parser tracks field state so misses/dodges, damaging hits,
    lead survival, switches, and same-turn switch-in deaths are attributed to
    the correct trainer/species in both singles and doubles.

    Secondary-effect RNG itself is *not* inferred from text here because some
    real successful rolls (especially flinch) are intentionally unprinted.
    Those are captured at the exact engine RNG site and merged afterward by
    apply_secondary_roll_events(). This also enforces the Gen 4 KO rule: a
    defender-targeted secondary skipped on a KO hit never becomes a fake
    failed luck event, while self-directed effects can still proc on that hit.
    """
    lines = log_source if isinstance(log_source, (list, tuple)) else log_source.splitlines()
    name_to_key = {trainer_a_name: trainer_a_key, trainer_b_name: trainer_b_key}
    opponent_key = {trainer_a_key: trainer_b_key, trainer_b_key: trainer_a_key}

    # Roster headers -> known moves/abilities. Keeping these in memory also
    # gives delayed-move parsing a cheap species->trainer disambiguation map.
    moves_known = {}
    ability_known = {}
    species_owners = defaultdict(set)
    i = 0
    total_lines = len(lines)
    while i < total_lines:
        line = lines[i]
        m = _LOG_TEAM_HEADER_RE.match(line)
        if m:
            tkey = name_to_key.get(m.group(1))
            i += 1
            while i < total_lines and lines[i].startswith("  Lv."):
                rm = _LOG_ROSTER_LINE_RE.match(lines[i])
                if rm and tkey:
                    species, ability_text, moves_str = rm.groups()
                    moves_known.setdefault((tkey, species), tuple(mv.strip() for mv in moves_str.split("/")))
                    ability_known[(tkey, species)] = ability_text.upper().replace(" ", "_")
                    species_owners[species].add(tkey)
                i += 1
            continue
        if line.startswith("--- Turn"):
            break
        i += 1

    stats = {}

    def get_slot(trainer_key, species):
        species = _analytics_species_name(species)
        ident = _analytics_ident(trainer_key, species)
        slot = stats.get(ident)
        if slot is None:
            slot = {
                "trainer_key": trainer_key,
                "species": species,
                "moves_known": moves_known.get((trainer_key, species), ()),
                "move_usage": Counter(),
                "mimic_move_usage": Counter(),
                "kos": 0,
                "assists": 0,
                "assist_categories": Counter(),
                "deaths": 0,
                "turns_survived": 0,
                "crits": 0,
                "missed_attacks": 0,
                "dodged_attacks": 0,
                "secondary_procs": 0,
                "secondary_luck_delta": 0.0,
                "voluntary_switches": 0,
                "hits_taken": 0,
                "switch_in_casualties": 0,
                "ko_against": Counter(),
                "killed_by": Counter(),
                "sweep_count": 0,
                "lead_appearances": 0,
                "lead_survived_opening": 0,
                "_first_turn_seen": None,
                "_last_turn_seen": None,
            }
            stats[ident] = slot
        return slot

    active = {trainer_a_key: (), trainer_b_key: ()}
    leads = {trainer_a_key: (), trainer_b_key: ()}
    lead_resolved = set()
    lead_dead = set()
    switch_in_turn = {}
    # (trainer_key, species) -> the move name (log-display form, e.g. "Thunderbolt") a Mimic-user's Mimic slot currently
    # holds, if any - set on "{species} learned {move}!" and cleared whenever the real engine would also clear
    # mimic_active_move (switch-out, faint; a fresh game/log always starts empty). While set, THIS SPECIFIC move name
    # coming from THIS actor routes into mimic_move_usage instead of move_usage below, so a Mimic user's "moves
    # executed" isn't cluttered with whatever it temporarily copied - see Mimic_Move_Usage in analytics_species.csv.
    mimic_active = {}
    current_turn = 0
    actor_key = actor_species = None
    target_key = target_species = None
    delayed_actor_key = delayed_actor_species = None
    delayed_target_key = delayed_target_species = None

    def mark_lead_result(tkey, species, survived):
        token = (tkey, species)
        if token in lead_resolved or species not in leads.get(tkey, ()):
            return
        slot = get_slot(tkey, species)
        slot["lead_survived_opening"] += int(bool(survived))
        lead_resolved.add(token)

    def initialize_leads(tkey, species_tuple):
        if leads[tkey] or not species_tuple:
            return
        leads[tkey] = tuple(species_tuple)
        for sp in leads[tkey]:
            get_slot(tkey, sp)["lead_appearances"] += 1

    def update_active(tkey, species_tuple):
        """Update active slots and resolve opening survival when a lead exits."""
        species_tuple = tuple(species_tuple)
        previous = active[tkey]
        initialize_leads(tkey, species_tuple)
        other = opponent_key[tkey]

        if previous:
            prev_set, new_set = set(previous), set(species_tuple)
            for sp in leads[tkey]:
                if sp in prev_set and sp not in new_set and (tkey, sp) not in lead_resolved:
                    mark_lead_result(tkey, sp, (tkey, sp) not in lead_dead)
            for own_sp in leads[tkey]:
                if own_sp in prev_set and own_sp not in new_set:
                    for opp_sp in leads[other]:
                        if opp_sp in active.get(other, ()):
                            mark_lead_result(other, opp_sp, (other, opp_sp) not in lead_dead)

        active[tkey] = species_tuple
        for sp in species_tuple:
            slot = get_slot(tkey, sp)
            if slot["_first_turn_seen"] is None:
                slot["_first_turn_seen"] = current_turn
            slot["_last_turn_seen"] = current_turn

    def replace_active(tkey, old_species, new_species):
        current = list(active.get(tkey, ()))
        try:
            idx = current.index(old_species)
            current[idx] = new_species
        except ValueError:
            if len(current) <= 1:
                current = [new_species]
            elif new_species not in current:
                current.append(new_species)
        update_active(tkey, tuple(current))

    def add_replacement_active(tkey, new_species):
        current = list(active.get(tkey, ()))
        if new_species not in current:
            current.append(new_species)
        # Singles can only have one active; doubles can have at most two.
        if len(current) > 2:
            current = current[-2:]
        update_active(tkey, tuple(current))

    def remove_active(tkey, species):
        current = list(active.get(tkey, ()))
        try:
            current.remove(species)
        except ValueError:
            return
        active[tkey] = tuple(current)

    def resolve_species_owner(species, preferred=None):
        if preferred and species in active.get(preferred, ()):
            return preferred
        for tkey in (trainer_a_key, trainer_b_key):
            if species in active.get(tkey, ()):
                return tkey
        owners = species_owners.get(species, set())
        return next(iter(owners)) if len(owners) == 1 else None

    def current_defender(species_hint=None):
        if actor_key is None:
            return (None, None)
        other = opponent_key[actor_key]
        opponents = active.get(other, ())
        if species_hint:
            return (other, species_hint) if species_hint in opponents or not opponents else (other, species_hint)
        if len(opponents) == 1:
            return other, opponents[0]
        if target_key == other and target_species:
            return target_key, target_species
        return None, None

    def record_miss(attacker_key, attacker_species_name, defender_key, defender_species_name):
        if attacker_key and attacker_species_name:
            get_slot(attacker_key, attacker_species_name)["missed_attacks"] += 1
        if defender_key and defender_species_name:
            get_slot(defender_key, defender_species_name)["dodged_attacks"] += 1

    def record_hits(defender_key, defender_species_name, hit_count):
        if defender_key and defender_species_name and hit_count > 0:
            get_slot(defender_key, defender_species_name)["hits_taken"] += int(hit_count)

    while i < total_lines:
        line = lines[i].rstrip("\n")

        m = _LOG_TURN_RE.match(line)
        if m:
            current_turn = int(m.group(1))
            delayed_actor_key = delayed_actor_species = None
            delayed_target_key = delayed_target_species = None
            i += 1
            continue

        m = _LOG_TURN_STATE_RE.match(line)
        if m:
            name_a_here, species_a, name_b_here, species_b = m.groups()
            key_a_here, key_b_here = name_to_key.get(name_a_here), name_to_key.get(name_b_here)
            if key_a_here:
                update_active(key_a_here, (species_a,))
            if key_b_here:
                update_active(key_b_here, (species_b,))
            i += 1
            continue

        m = _LOG_DOUBLE_SIDE_RE.match(line)
        if m:
            tkey = name_to_key.get(m.group(1))
            if tkey:
                update_active(tkey, tuple(_LOG_DOUBLE_MON_RE.findall(m.group(2))))
            i += 1
            continue

        m = _LOG_VOLUNTARY_SWITCH_RE.match(line)
        if m:
            trainer_name_here, withdrawn_species, new_species = m.groups()
            tkey = name_to_key.get(trainer_name_here)
            if tkey:
                get_slot(tkey, withdrawn_species)["voluntary_switches"] += 1
                switch_in_turn[(tkey, new_species)] = current_turn
                replace_active(tkey, withdrawn_species, new_species)
                mark_lead_result(tkey, withdrawn_species, True)
                mimic_active.pop((tkey, withdrawn_species), None)
            actor_key = actor_species = target_key = target_species = None
            i += 1
            continue

        m = _LOG_SEND_OUT_RE.match(line)
        if m:
            trainer_name_here, new_species = m.groups()
            tkey = name_to_key.get(trainer_name_here)
            if tkey:
                switch_in_turn[(tkey, new_species)] = current_turn
                add_replacement_active(tkey, new_species)
            i += 1
            continue

        m = _LOG_MOVE_USE_RE.match(line)
        if m:
            actor_name_here, actor_species_here, move_name_here = m.groups()
            actor_key = name_to_key.get(actor_name_here)
            actor_species = actor_species_here
            target_key = target_species = None
            delayed_actor_key = delayed_actor_species = None
            delayed_target_key = delayed_target_species = None
            if actor_key:
                slot_here = get_slot(actor_key, actor_species)
                if mimic_active.get((actor_key, actor_species)) == move_name_here:
                    slot_here["mimic_move_usage"][move_name_here] += 1
                else:
                    slot_here["move_usage"][move_name_here] += 1
                other = opponent_key[actor_key]
                opponents = active.get(other, ())
                if len(opponents) == 1:
                    target_key, target_species = other, opponents[0]
            i += 1
            continue

        # Always immediately follows that same actor's "uses Mimic!" line (see MOVE_MIMIC's two log.append call sites) -
        # actor_key/actor_species from the match just above are still this Mimic user's own.
        m = _LOG_MIMIC_LEARN_RE.match(line)
        if m and actor_key:
            _mimic_user_species, mimic_copied_move = m.groups()
            mimic_active[(actor_key, actor_species)] = mimic_copied_move
            i += 1
            continue

        # Delayed moves resolve without a normal "uses" line on this turn.
        m = _LOG_DELAYED_STRIKE_RE.match(line)
        if m:
            delayed_actor_species, _move_display, delayed_target_species = m.groups()
            delayed_target_key = resolve_species_owner(delayed_target_species)
            owners = species_owners.get(delayed_actor_species, set())
            delayed_actor_key = next(iter(owners)) if len(owners) == 1 else None
            i += 1
            continue

        m = _LOG_DOUBLE_MISS_RE.match(line)
        if m:
            defender_species = m.group(1)
            defender_key, _ = current_defender(defender_species)
            record_miss(actor_key, actor_species, defender_key, defender_species)
            i += 1
            continue

        if line.strip() == "Attack missed!":
            if delayed_target_species:
                record_miss(delayed_actor_key, delayed_actor_species,
                            delayed_target_key, delayed_target_species)
                delayed_actor_key = delayed_actor_species = None
                delayed_target_key = delayed_target_species = None
            else:
                defender_key, defender_species = current_defender()
                record_miss(actor_key, actor_species, defender_key, defender_species)
            i += 1
            continue

        m = _LOG_MULTI_HIT_DAMAGE_RE.match(line)
        if m:
            hits = int(m.group(1))
            defender_key, defender_species = current_defender()
            record_hits(defender_key, defender_species, hits)
            if "critical hit!" in line.lower() and actor_key:
                get_slot(actor_key, actor_species)["crits"] += 1
            i += 1
            continue

        m = _LOG_DOUBLE_DAMAGE_RE.match(line)
        if m:
            defender_species = m.group(2)
            defender_key, _ = current_defender(defender_species)
            record_hits(defender_key, defender_species, 1)
            target_key, target_species = defender_key, defender_species
            if "critical hit!" in line.lower() and actor_key:
                get_slot(actor_key, actor_species)["crits"] += 1
            i += 1
            continue

        m = _LOG_BIDE_DAMAGE_RE.match(line)
        if m:
            defender_key, defender_species = current_defender()
            record_hits(defender_key, defender_species, 1)
            i += 1
            continue

        m = _LOG_SINGLE_DAMAGE_RE.match(line)
        if m:
            if delayed_target_species:
                record_hits(delayed_target_key, delayed_target_species, 1)
                delayed_actor_key = delayed_actor_species = None
                delayed_target_key = delayed_target_species = None
            else:
                defender_key, defender_species = current_defender()
                record_hits(defender_key, defender_species, 1)
            if "critical hit!" in line.lower() and actor_key:
                get_slot(actor_key, actor_species)["crits"] += 1
            i += 1
            continue

        # Keep the old critical-hit fallback for unusual damage messages not
        # matched above. The guard avoids double counting normal damage lines.
        if "critical hit!" in line.lower() and actor_key:
            get_slot(actor_key, actor_species)["crits"] += 1
            i += 1
            continue

        m = _LOG_FAINT_RE.match(line)
        if m:
            fainted_species = m.group(1)
            preferred = opponent_key.get(actor_key) if actor_key else None
            fainted_key = resolve_species_owner(fainted_species, preferred=preferred)
            if fainted_key:
                mimic_active.pop((fainted_key, fainted_species), None)
                slot = get_slot(fainted_key, fainted_species)
                slot["deaths"] += 1
                if switch_in_turn.get((fainted_key, fainted_species)) == current_turn:
                    slot["switch_in_casualties"] += 1
                if slot["_first_turn_seen"] is not None:
                    slot["turns_survived"] = slot["_last_turn_seen"] - slot["_first_turn_seen"] + 1
                if fainted_species in leads[fainted_key]:
                    lead_dead.add((fainted_key, fainted_species))
                    mark_lead_result(fainted_key, fainted_species, False)
                    other = opponent_key[fainted_key]
                    for sp in leads[other]:
                        if sp in active.get(other, ()):
                            mark_lead_result(other, sp, (other, sp) not in lead_dead)
                remove_active(fainted_key, fainted_species)
            i += 1
            continue

        i += 1

    # Credit survivors' lifespan and resolve opening leads that never left.
    for slot in stats.values():
        if slot["deaths"] == 0 and slot["_first_turn_seen"] is not None:
            slot["turns_survived"] = slot["_last_turn_seen"] - slot["_first_turn_seen"] + 1
        del slot["_first_turn_seen"]
        del slot["_last_turn_seen"]
    for tkey in (trainer_a_key, trainer_b_key):
        for sp in leads[tkey]:
            if (tkey, sp) not in lead_resolved:
                mark_lead_result(tkey, sp, (tkey, sp) not in lead_dead)

    return stats

def apply_knockout_relationships(game_analytics, ko_events):
    """Merge exact move-KO attacker/victim relationships from engine events.

    KO credit comes from the engine rather than "last move seen" text state, so
    passive end-of-turn faints can never be accidentally credited as move KOs.
    """
    for ko in ko_events:
        victim_species = ko.get("victim_species")
        victim_trainer = ko.get("victim_trainer")
        if not victim_species or not victim_trainer:
            continue
        attacker_species = _analytics_species_name(ko.get("species"))
        victim_species_name = _analytics_species_name(victim_species)
        attacker = game_analytics.get(_analytics_ident(ko.get("trainer"), attacker_species))
        victim = game_analytics.get(_analytics_ident(victim_trainer, victim_species_name))
        if attacker is not None:
            attacker["kos"] += 1
            attacker["ko_against"][victim_species_name] += 1
        if victim is not None:
            victim["killed_by"][attacker_species] += 1


def apply_assist_events(game_analytics, assist_events):
    """Merge the engine's assist events (one per contributing species per faint, see resolve_faint_credit). Each adds one to that
    species' assists and one to every category it carried, so the category counts can add up to more than the assists."""
    for event in assist_events:
        slot = game_analytics.get(_analytics_ident(event.get("trainer"), _analytics_species_name(event.get("species"))))
        if slot is None:
            continue
        slot["assists"] += 1
        slot["assist_categories"].update(event.get("categories", ()))


def apply_secondary_roll_events(game_analytics, secondary_roll_events):
    """Merge exact eligible secondary-effect RNG rolls from the engine.

    A successful roll increments Secondary_Effect_Procs. Luck gets a centered
    contribution of (success - chance): success on a 20% effect contributes
    +0.8, failure contributes -0.2, and a guaranteed 100% effect contributes 0.
    Defender-targeted KO effects are absent entirely because no roll occurs.
    """
    for event in secondary_roll_events:
        trainer_key = event.get("trainer")
        species = _analytics_species_name(event.get("species"))
        slot = game_analytics.get(_analytics_ident(trainer_key, species))
        if slot is None:
            continue
        chance = min(1.0, max(0.0, float(event.get("chance", 0.0) or 0.0)))
        success = bool(event.get("success"))
        if success:
            slot["secondary_procs"] += 1
        slot["secondary_luck_delta"] += (1.0 if success else 0.0) - chance



def apply_damaging_hit_events(game_analytics, damaging_hit_events):
    """Replace log-estimated hit counts with exact engine direct-hit events."""
    for slot in game_analytics.values():
        slot["hits_taken"] = 0
    for event in damaging_hit_events:
        trainer_key = event.get("trainer")
        species = _analytics_species_name(event.get("species"))
        slot = game_analytics.get(_analytics_ident(trainer_key, species))
        if slot is not None:
            slot["hits_taken"] += 1


def resolve_best_win_worst_loss(standings):
    """Fills in best_win ("the highest-FINAL-Elo opponent this trainer
    beat") and worst_loss ("the lowest-FINAL-Elo opponent this trainer
    lost to") for every trainer, using each opponent's rating as it
    stood at the END of the tournament - not the snapshot mid-tournament
    Elo the fight actually happened at. A trainer who started weak but
    climbed the whole event should still count as an impressive win for
    whoever beat them early on, and vice versa for a strong trainer who
    later fell off."""
    for data in standings.values():
        if data["beaten_opponents"]:
            best = max(data["beaten_opponents"], key=lambda k: standings[k]["elo"])
            data["best_win"] = {"opponent": DISPLAY_NAMES.get(best, best), "opponent_elo": standings[best]["elo"]}
        if data["lost_to_opponents"]:
            worst = min(data["lost_to_opponents"], key=lambda k: standings[k]["elo"])
            data["worst_loss"] = {"opponent": DISPLAY_NAMES.get(worst, worst), "opponent_elo": standings[worst]["elo"]}


def format_wl_ratio(wins, losses):
    if losses == 0:
        return "Undefeated" if wins > 0 else "0-0"
    return f"{wins / losses:.2f}"


# ============================================================
# DATA EXPORT PIPELINES (CSV / JSON / Reddit Markdown)
# ============================================================
# Every export below is built from the SAME ordered list of per-trainer
# row dicts (see _standings_rows), so standings.csv, tournament_summary.json,
# reddit_post.md and the console "FINAL STANDINGS" text can never disagree
# with each other. Only the standard library is used (csv/json/collections),
# no third-party dependencies.
def format_team_and_movesets(party):
    """One string summarizing a trainer's full team and movesets, e.g.
    'Garchomp Lv50 (Sand Veil): Outrage/Earthquake/Fire Fang/Swords Dance | Spiritomb
    Lv50 (Pressure): ...' - used for standings.csv's Team_and_Movesets column so the
    raw team behind every Elo rating is fully auditable without having to
    cross-reference the original trainer JSON files. The ability sits between the level and the
    moves - not next to the species, like format_team_roster_for_log's battle-log header - so every
    existing Team_and_Movesets reader in app.py (which all split on " Lv" for the species/item and
    on ": " for the moves) keeps working unmodified; only what falls between those two split points
    changed. (Added so app.py's "Filter by Ability" sidebar control - which searches this same column,
    the same way its Pokemon/Move/Item siblings do - would have anything to actually find; it never
    did before this, on any dataset this project has ever generated.)"""
    parts = []
    for mon in party:
        species_display = (mon.get("species") or "UNKNOWN").replace("SPECIES_", "").replace("_", " ").title()
        moves = mon.get("moves") or []
        moves_display = "/".join(m.replace("MOVE_", "").replace("_", " ").title() for m in moves) or "(no moves)"
        item = mon.get("item")
        item_display = item.replace("ITEM_", "").replace("_", " ").title() if item and item != "ITEM_NONE" else None
        held_item = f" @ {item_display}" if item_display else ""
        ability_display = (mon.get("ability") or "NONE").replace("_", " ").title()
        parts.append(f"{species_display}{held_item} Lv{mon.get('level', '?')} ({ability_display}): {moves_display}")
    return " | ".join(parts)


def get_team_species(party):
    """Just the species names for a trainer's team, no movesets/levels -
    used for reddit_post.md's one-column-per-Pokemon breakdown. Movesets
    stay in standings.csv's Team_and_Movesets column, which already has
    the full detail, so the Reddit tables don't need to repeat it."""
    return [(mon.get("species") or "UNKNOWN").replace("SPECIES_", "").replace("_", " ").title() for mon in party]


def format_team_roster_for_log(trainer_name, party):
    """Multi-line team roster (species, level, ability, held item,
    moveset) for a battle log's own header. Unlike
    format_team_and_movesets/get_team_species (which Title-Case species
    for CSV/Reddit tables), species here are shown ALL CAPS via
    species_display and levels as "Lv. N" - matching exactly how both
    already appear everywhere else in this same battle log's text, so
    the header reads consistently with the rest of the file. The held
    item uses the same "@ Item" convention already established in
    standings.csv's Team_and_Movesets column."""
    lines = [f"{trainer_name}'s team:"]
    for mon in party:
        species = mon.get("species_display") or (mon.get("species") or "UNKNOWN").replace("SPECIES_", "").replace("_", " ")
        ability = (mon.get("ability") or "NONE").replace("_", " ").title()
        item = mon.get("item")
        item_display = item.replace("ITEM_", "").replace("_", " ").title() if item and item != "ITEM_NONE" else None
        held_item = f" @ {item_display}" if item_display else ""
        moves = mon.get("moves") or []
        moves_display = "/".join(m.replace("MOVE_", "").replace("_", " ").title() for m in moves) or "(no moves)"
        lines.append(f"  Lv. {mon.get('level', '?')} {species} ({ability}){held_item}: {moves_display}")
    return lines


# Gym Leaders, Elite Four, Champions, and Rivals - matched on the trainer
# KEY (filename) prefix, which is also what format_display_from_key turns
# into the display name in the first place.
BOSS_KEY_PREFIXES = ("leader_", "elite_four_", "champion_")
_RIVAL_KEY_PATTERN = re.compile(r"^rival\d*_")


def is_boss_trainer(key):
    """Used by the "Bosses Only" sub-leaderboard and to find the top
    performing GENERIC (non-Boss) NPC. Rival's own prefix is matched
    with a regex rather than a plain string prefix, since the real
    class constant could be a bare "TRAINERCLASS_RIVAL" (yielding a
    "rival_..." key, as HGSS's single rival would) or a numbered
    "TRAINERCLASS_RIVAL1"/"RIVAL2" (Platinum's multi-rival convention,
    yielding "rival1_..."/"rival2_...") - either should count."""
    key = key.lower()
    return key.startswith(BOSS_KEY_PREFIXES) or bool(_RIVAL_KEY_PATTERN.match(key))


def is_battleground_trainer(key):
    """Battleground trainers (Riley, Mira, Buck, Marley, Cheryl, etc. at
    the Fight Area/Survival Area) are notable postgame challenge fights,
    not run-of-the-mill NPCs. They don't match any of the Leader/Elite
    Four/Champion/Rival prefixes, so is_boss_trainer doesn't count them
    and they never appear in the "Bosses Only" leaderboard - but they're
    still excluded from "Top Performing Generic NPC" alongside true
    Bosses, so a Battleground trainer can never be crowned "generic" -
    see build_tournament_summary."""
    return "battleground" in key.lower()


def is_postgame_trainer(key):
    """Rematches, Battleground trainers, and Survival Area/Fight Area
    encounters (e.g. 'rival_survival_area_turtwig') are all postgame
    content - not part of a first playthrough's roster. Used to build a
    "clean" Top 25 Leaderboard of first-playthrough trainers only."""
    lower = key.lower()
    _, tier = parse_trainer_filename(key)
    return tier != 0 or is_battleground_trainer(key) or "survival_area" in lower or "fight_area" in lower


def find_starter_triangle_trainers(roster_keys):
    """The repo encodes Rival Barry's 3 possible Survival Area teams (one
    per possible PLAYER starter) as separate trainer files, so a full
    round robin plays all three. Only the base (non-rematch) encounter is
    used, for a single clean three-way comparison. Returns
    {player_starter: trainer_key} for whichever of the three are present
    (roster_keys may only include a subset, e.g. in a test run)."""
    found = {}
    for key in roster_keys:
        _, tier = parse_trainer_filename(key)
        if tier != 0:
            continue
        lower = key.lower()
        if "rival" not in lower or "survival" not in lower:
            continue
        for starter in STARTER_COUNTER_PICK:
            if starter.lower() in lower:
                found[starter] = key
                break
    return found


def _standings_rows(standings, roster_keys, tier_table, turns_by_trainer):
    """Ranks roster_keys the same way the console standings text always
    has (match wins first, then Elo as the tiebreaker) and flattens each
    trainer's standing into a plain dict ready for csv.writer / json.dump.
    tier_table comes from compute_tier_thresholds, built from this same
    tournament's final Elo distribution. turns_by_trainer maps trainer_key
    -> {"total_turns", "games"}, used for the average-turns-per-game
    figure (see the Top Staller / Glass Cannon highlights)."""
    ordered = sorted(roster_keys, key=lambda k: (standings[k]["match_wins"], standings[k]["elo"]), reverse=True)
    rows = []
    for rank, t in enumerate(ordered, start=1):
        data = standings[t]
        matches_played = data["match_wins"] + data["match_losses"]
        win_rate = round(data["match_wins"] / matches_played, 3) if matches_played else 0.0
        bw, wl = data["best_win"], data["worst_loss"]
        class_title = format_class_title(TRAINERS_DB.get(t, {}).get("class")) or "Trainer"
        turn_data = turns_by_trainer.get(t, {"total_turns": 0, "games": 0})
        avg_turns = round(turn_data["total_turns"] / turn_data["games"], 2) if turn_data["games"] else 0.0
        rows.append({
            "rank": rank,
            "trainer_key": t,
            "display_name": DISPLAY_NAMES.get(t, t),
            "class": class_title,
            "match_wins": data["match_wins"],
            "match_losses": data["match_losses"],
            "match_win_rate": win_rate,
            "game_wins": data["game_wins"],
            "game_losses": data["game_losses"],
            "elo": data["elo"],
            "tier": get_elo_tier(data["elo"], tier_table),
            "greatest_win": f"{bw['opponent']} (Elo {bw['opponent_elo']})" if bw["opponent"] else "None",
            "worst_loss": f"{wl['opponent']} (Elo {wl['opponent_elo']})" if wl["opponent"] else "None",
            "longest_match_vs": (f"{DISPLAY_NAMES.get(data['longest_match_opponent'], data['longest_match_opponent'])} "
                                  f"({data['longest_match_games']} games)") if data["longest_match_opponent"] else "None",
            "avg_turns": avg_turns,
            "team_and_movesets": format_team_and_movesets(TRAINERS_DB.get(t, {}).get("party", [])),
            "team_species": get_team_species(TRAINERS_DB.get(t, {}).get("party", [])),
        })
    return rows


def merge_game_analytics(cumulative, game_analytics):
    """Merge one game's in-memory analytics into tournament-wide tallies."""
    for ident, stats in game_analytics.items():
        if ident not in cumulative:
            cumulative[ident] = {
                "trainer_key": stats["trainer_key"],
                "species": stats["species"],
                "moves_known": stats["moves_known"],
                "move_usage": Counter(),
                "mimic_move_usage": Counter(),
                "kos": 0,
                "assists": 0,
                "assist_categories": Counter(),
                "deaths": 0,
                "crits": 0,
                "missed_attacks": 0,
                "dodged_attacks": 0,
                "secondary_procs": 0,
                "secondary_luck_delta": 0.0,
                "voluntary_switches": 0,
                "hits_taken": 0,
                "switch_in_casualties": 0,
                "total_turns_survived": 0,
                "games_seen": 0,
                "ko_against": Counter(),
                "killed_by": Counter(),
                "sweep_count": 0,
                "lead_appearances": 0,
                "lead_survived_opening": 0,
            }
        c = cumulative[ident]
        c["move_usage"].update(stats["move_usage"])
        c["mimic_move_usage"].update(stats.get("mimic_move_usage", {}))
        c["assist_categories"].update(stats.get("assist_categories", {}))
        c["ko_against"].update(stats.get("ko_against", {}))
        c["killed_by"].update(stats.get("killed_by", {}))
        for key in (
            "kos", "assists", "deaths", "crits", "missed_attacks", "dodged_attacks",
            "secondary_procs", "secondary_luck_delta", "voluntary_switches",
            "hits_taken", "switch_in_casualties", "sweep_count",
            "lead_appearances", "lead_survived_opening",
        ):
            c[key] += stats.get(key, 0)
        c["total_turns_survived"] += stats["turns_survived"]
        # A per-game slot only exists if the Pokemon actually appeared on the
        # field (including a same-turn hazard casualty), so games_seen is the
        # denominator for "per appearance" wall/lifespan metrics.
        c["games_seen"] += 1
    return cumulative


def _format_ranked_counter(counter, limit=None, species=False):
    if not counter:
        return "None"
    items = counter.most_common(limit)
    parts = []
    for name, count in items:
        if species:
            pretty = _analytics_species_name(name).title()
        else:
            pretty = str(name).replace("MOVE_", "").replace("ITEM_", "").replace("_", " ").title()
        parts.append(f"{pretty}: {count}")
    return ", ".join(parts)


def _format_move_usage(move_usage):
    """Format move usage with counts and percentages, busiest move first."""
    total = sum(move_usage.values())
    if total == 0:
        return "None"
    parts = []
    for move_name, count in move_usage.most_common():
        pretty = move_name.replace("MOVE_", "").replace("_", " ").title()
        parts.append(f"{pretty}: {count} ({100.0 * count / total:.1f}%)")
    return ", ".join(parts)


def _luck_score(crits, missed_attacks, dodged_attacks, secondary_luck_delta, total_moves_used):
    """Normalized luck signal combining attacker and defender fortune.

    Positive events: critical hits, attacks dodged as the defender, and the
    centered outcome of eligible secondary rolls. Negative events: the Pokemon's
    own accuracy misses plus the probability-weighted downside of an eligible
    secondary roll that fails. A failure is therefore -p, not a blanket -1.
    Defender-targeted KO secondaries contribute exactly zero because Gen 4 never
    rolls them; self-directed secondaries are still rolled on KO hits and their
    success/failure is scored normally.
    """
    opportunities = total_moves_used + dodged_attacks
    if opportunities <= 0:
        return 0.0
    net = crits + dodged_attacks + secondary_luck_delta - missed_attacks
    return round(100.0 * net / opportunities, 2)


# ------------------------------------------------------------
# KDA, the species tier list and combat roles
# ------------------------------------------------------------
# Pokemon is a team game, so KOs / Deaths alone rewards sweepers and punishes support: an assist is credited to every OTHER species
# that helped bring a fainted Pokemon down (see the ASSIST TRACKING section), and KDA = (KOs + Assists) / max(1, Deaths).
# Roles are RELATIVE TO THE FIELD: a species earns one by ranking in the top quarter of the species that could earn it (ties at the
# boundary qualify, the same rank rule as the tier table), not by clearing a fixed share - in real tournaments assists are only ~0.3
# per KO, so any fixed "KOs above 45%" line made ~95% of species Attackers.
ROLE_TOP_PERCENTILE = 0.75
ROLE_MIN_CONTRIBUTIONS = 30              # KOs + Assists a species needs to be rated Attacker (and to count in that field)
ROLE_MIN_CATEGORY_ASSISTS = 10           # assists of a role's categories a species needs for that role (and to count in that field)
# Each role's assist categories are summed together before being measured against ROLE_MIN_CATEGORY_ASSISTS/the field cutoff - Support
# is healing (Wish/Heal Bell/...) AND Reflect/Light Screen assists combined, since both are the same "kept a teammate alive to finish
# the job" contribution; every other role still maps to exactly one category.
ROLE_CATEGORIES = (("Disrupter", ("status",)), ("Hazards", ("hazard",)), ("Weather", ("weather",)),
                    ("Support", ("cleric", "screen", "debuff", "tailwind")), ("Passer", ("pass",)))
# A species with no role is a Defender if its average lifespan is in the top quarter of the field, else an All-Rounder.
ROLE_DEFENDER_LIFESPAN_PERCENTILE = ROLE_TOP_PERCENTILE


def compute_kda(kos, assists, deaths):
    return (kos + assists) / max(1, deaths)


def compute_species_tiers(kda_by_species):
    """{species: tier}: the very same 5% percentile tier table the trainers get (compute_tier_thresholds / get_elo_tier), built from
    the species' KDA instead of Elo."""
    if not kda_by_species:
        return {}
    table = compute_tier_thresholds(list(kda_by_species.values()))
    return {species: get_elo_tier(kda, table) for species, kda in kda_by_species.items()}


def compute_field_cutoff(values, percentile=ROLE_TOP_PERCENTILE):
    """The value a species needs to be in the top (1 - percentile) of `values`: the entry at that rank of the descending sort, with the
    same rank rule as compute_tier_thresholds (ties at the boundary qualify). Nothing qualifies in an empty field."""
    ordered = sorted(values, reverse=True)
    if not ordered:
        return float("inf")
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * (1.0 - percentile) + 1e-9)))]


compute_lifespan_cutoff = compute_field_cutoff


def _role_category_count(assist_categories, categories):
    """Total assists a role's (possibly several) categories account for, e.g. Support = cleric + screen."""
    return sum(assist_categories.get(c, 0) for c in categories)


def compute_role_cutoffs(field):
    """`field` is an iterable of (kos, assists, assist_categories, avg_lifespan), one per species. Returns the cutoffs compute_combat_role
    compares against: "Attacker" (KO share of KOs + Assists among species with at least ROLE_MIN_CONTRIBUTIONS), one per role in
    ROLE_CATEGORIES (that role's categories' combined share of Total_Assists among species with at least ROLE_MIN_CATEGORY_ASSISTS of
    it) and "lifespan"."""
    field = list(field)
    cutoffs = {"Attacker": compute_field_cutoff([k / (k + a) for k, a, _c, _l in field if k + a >= ROLE_MIN_CONTRIBUTIONS]),
               "lifespan": compute_field_cutoff([life for _k, _a, _c, life in field], ROLE_DEFENDER_LIFESPAN_PERCENTILE)}
    for role, categories in ROLE_CATEGORIES:
        cutoffs[role] = compute_field_cutoff([_role_category_count(c, categories) / a for _k, a, c, _l in field
                                              if _role_category_count(c, categories) >= ROLE_MIN_CATEGORY_ASSISTS])
    return cutoffs


def compute_combat_role(kos, assists, assist_categories, avg_lifespan, cutoffs):
    """The species' role(s), joined with " / " in a fixed order: Attacker (its KO share of KOs + Assists in the field's top quarter),
    then Disrupter / Hazards / Weather / Support / Passer (that role's categories' combined share of its Total_Assists in the top
    quarter of the species that have enough of them; an assist can carry several categories, so a species can earn several roles from
    one assist). With none of those: Defender for a long-lived species (top quarter of average lifespan), otherwise All-Rounder.
    `cutoffs` comes from compute_role_cutoffs."""
    roles = []
    if kos + assists >= ROLE_MIN_CONTRIBUTIONS and kos / (kos + assists) >= cutoffs["Attacker"]:
        roles.append("Attacker")
    for role, categories in ROLE_CATEGORIES:
        count = _role_category_count(assist_categories, categories)
        if count >= ROLE_MIN_CATEGORY_ASSISTS and count / assists >= cutoffs[role]:
            roles.append(role)
    if roles:
        return " / ".join(roles)
    return "Defender" if avg_lifespan >= cutoffs["lifespan"] else "All-Rounder"


def _format_assist_breakdown(assist_categories):
    return ", ".join(f"{category.title()}: {assist_categories.get(category, 0)}" for category in ASSIST_CATEGORIES)


def export_individual_analytics_csv(individual_analytics, filename="analytics_individuals.csv"):
    """Trainer-specific performance, emitted once after all matches finish."""
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Unique_Identifier", "Trainer_Key", "Species", "Move_Preference",
            "KOs", "Deaths", "KDR", "Total_Assists", "KDA", "AI_Switching_Frequency",
            "Average_Lifespan_Turns", "Average_Hits_Taken", "Critical_Hits",
            "Missed_Attacks", "Dodged_Attacks", "Secondary_Effect_Procs",
            "Luck_Score", "Games_Seen", "Most_KOs_Against", "Killed_Most_By",
            "Sweep_Count", "Lead_Win_Rate", "Switch_In_Casualties", "Assist_Breakdown",
            "Mimic_Move_Usage",
        ])
        for ident, c in sorted(individual_analytics.items()):
            total_moves_used = sum(c["move_usage"].values())
            kdr = round(c["kos"] / max(1, c["deaths"]), 2)
            assists = c.get("assists", 0)
            kda = round(compute_kda(c["kos"], assists, c["deaths"]), 2)
            appearances = max(1, c["games_seen"])
            avg_lifespan = round(c["total_turns_survived"] / appearances, 2)
            avg_hits_taken = round(c.get("hits_taken", 0) / appearances, 2)
            lead_rate = (round(100.0 * c["lead_survived_opening"] / c["lead_appearances"], 2)
                         if c.get("lead_appearances", 0) else "")
            writer.writerow([
                ident, c["trainer_key"], c["species"], _format_move_usage(c["move_usage"]),
                c["kos"], c["deaths"], kdr, assists, kda, c["voluntary_switches"], avg_lifespan,
                avg_hits_taken, c["crits"], c.get("missed_attacks", 0),
                c.get("dodged_attacks", 0), c["secondary_procs"],
                _luck_score(c["crits"], c.get("missed_attacks", 0),
                            c.get("dodged_attacks", 0), c.get("secondary_luck_delta", 0),
                            total_moves_used),
                c["games_seen"],
                _format_ranked_counter(c.get("ko_against", Counter()), 3, species=True),
                _format_ranked_counter(c.get("killed_by", Counter()), 3, species=True),
                c.get("sweep_count", 0), lead_rate, c.get("switch_in_casualties", 0),
                _format_assist_breakdown(c.get("assist_categories", {})),
                _format_move_usage(c.get("mimic_move_usage", Counter())),
            ])


def aggregate_species_analytics(individual_analytics):
    """Sums the per-trainer-Pokemon tallies into one dict per species."""
    species_totals = {}
    for c in individual_analytics.values():
        species = c["species"]
        if species not in species_totals:
            species_totals[species] = {
                "move_usage": Counter(),
                "mimic_move_usage": Counter(),
                "kos": 0,
                "assists": 0,
                "assist_categories": Counter(),
                "deaths": 0,
                "crits": 0,
                "missed_attacks": 0,
                "dodged_attacks": 0,
                "secondary_procs": 0,
                "secondary_luck_delta": 0.0,
                "hits_taken": 0,
                "switch_in_casualties": 0,
                "total_turns_survived": 0,
                "games_seen": 0,
                "ko_against": Counter(),
                "killed_by": Counter(),
            }
        s = species_totals[species]
        s["move_usage"].update(c["move_usage"])
        s["mimic_move_usage"].update(c.get("mimic_move_usage", {}))
        s["ko_against"].update(c.get("ko_against", {}))
        s["killed_by"].update(c.get("killed_by", {}))
        s["assist_categories"].update(c.get("assist_categories", {}))
        for key in (
            "kos", "assists", "deaths", "crits", "missed_attacks", "dodged_attacks",
            "secondary_procs", "secondary_luck_delta", "hits_taken",
            "switch_in_casualties",
        ):
            s[key] += c.get(key, 0)
        s["total_turns_survived"] += c["total_turns_survived"]
        s["games_seen"] += c["games_seen"]
    return species_totals


def export_species_analytics_csv(individual_analytics, filename="analytics_species.csv"):
    """Global species aggregation, emitted once after all matches finish. Tier ranks every species by KDA with the trainers' own
    percentile tier table; Role is worked out from each species' KO / assist mix relative to the field (compute_role_cutoffs / compute_combat_role)."""
    species_totals = aggregate_species_analytics(individual_analytics)
    kda_by_species = {sp: compute_kda(s["kos"], s["assists"], s["deaths"]) for sp, s in species_totals.items()}
    tiers = compute_species_tiers(kda_by_species)
    lifespans = {sp: s["total_turns_survived"] / max(1, s["games_seen"]) for sp, s in species_totals.items()}
    cutoffs = compute_role_cutoffs((s["kos"], s["assists"], s["assist_categories"], lifespans[sp]) for sp, s in species_totals.items())

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Species", "Tier", "Role", "Global_Move_Usage", "Total_KOs", "Total_Deaths",
            "Global_KDR", "Total_Assists", "KDA", "Global_Average_Lifespan_Turns", "Average_Hits_Taken",
            "Critical_Hits", "Missed_Attacks", "Dodged_Attacks",
            "Secondary_Effect_Procs", "Luck_Score", "Games_Seen",
            "Most_KOs_Against", "Killed_Most_By", "Switch_In_Casualties", "Assist_Breakdown",
            "Mimic_Move_Usage",
        ])
        for species, s in sorted(species_totals.items()):
            total_moves_used = sum(s["move_usage"].values())
            kdr = round(s["kos"] / max(1, s["deaths"]), 2)
            appearances = max(1, s["games_seen"])
            avg_lifespan = round(s["total_turns_survived"] / appearances, 2)
            avg_hits_taken = round(s["hits_taken"] / appearances, 2)
            writer.writerow([
                species, tiers[species],
                compute_combat_role(s["kos"], s["assists"], s["assist_categories"], lifespans[species], cutoffs),
                _format_move_usage(s["move_usage"]), s["kos"], s["deaths"],
                kdr, s["assists"], round(kda_by_species[species], 2), avg_lifespan, avg_hits_taken, s["crits"], s["missed_attacks"],
                s["dodged_attacks"], s["secondary_procs"],
                _luck_score(s["crits"], s["missed_attacks"], s["dodged_attacks"],
                            s["secondary_luck_delta"], total_moves_used),
                s["games_seen"], _format_ranked_counter(s["ko_against"], 3, species=True),
                _format_ranked_counter(s["killed_by"], 3, species=True),
                s["switch_in_casualties"], _format_assist_breakdown(s["assist_categories"]),
                _format_move_usage(s.get("mimic_move_usage", Counter())),
            ])


def merge_mimic_move_usage(original_filename, supplement_filename, key_column):
    """Folds ONLY the Mimic_Move_Usage column from a mimic_supplement run's analytics CSV (see run_tournament) into
    the main dataset's already-exported analytics CSV, matched by key_column ("Species" for analytics_species.csv,
    "Unique_Identifier" for analytics_individuals.csv - both are stable, deterministic keys built the same way in
    every run, see _analytics_ident). Every other column - KOs, Deaths, KDA, Games_Seen, Global_Move_Usage, all of it -
    is left byte-for-byte as the main run already computed it; only rows that also appear in the supplement get their
    Mimic_Move_Usage value replaced. A row the supplement never touched keeps whatever it already had, or "None" if
    the main file predates this column entirely (an older dataset re-exported through here gains the column for the
    first time, filled in wherever the supplement covers it). Does nothing (and returns False) if either file is
    missing, so a per-dataset driver can call this for every variant and skip the ones that don't exist yet."""
    if not os.path.exists(original_filename):
        print(f"merge_mimic_move_usage: skipping, missing '{original_filename}'.")
        return False
    if not os.path.exists(supplement_filename):
        print(f"merge_mimic_move_usage: skipping, missing '{supplement_filename}' (run_tournament(mimic_supplement=True) "
              f"for this dataset hasn't been done yet).")
        return False

    with open(supplement_filename, "r", newline="", encoding="utf-8") as f:
        supplement_rows = list(csv.DictReader(f))
    if supplement_rows and key_column not in supplement_rows[0]:
        print(f"merge_mimic_move_usage: '{supplement_filename}' has no '{key_column}' column - skipping.")
        return False
    supplement_by_key = {r[key_column]: r.get("Mimic_Move_Usage", "None") for r in supplement_rows}

    with open(original_filename, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        original_rows = list(reader)

    if key_column not in fieldnames:
        print(f"merge_mimic_move_usage: '{original_filename}' has no '{key_column}' column - skipping.")
        return False
    if "Mimic_Move_Usage" not in fieldnames:
        fieldnames = fieldnames + ["Mimic_Move_Usage"]

    updated = 0
    for row in original_rows:
        if not row.get("Mimic_Move_Usage"):
            row["Mimic_Move_Usage"] = "None"
        new_value = supplement_by_key.get(row[key_column])
        if new_value is not None:
            row["Mimic_Move_Usage"] = new_value
            updated += 1

    with open(original_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(original_rows)

    print(f"merge_mimic_move_usage: updated Mimic_Move_Usage for {updated}/{len(original_rows)} row(s) in '{original_filename}'.")
    return True


def export_tournament_analytics_csv(move_ko_counter, knockout_counter, item_activation_counter,
                                    total_games_played, total_turns_all, total_matches,
                                    filename="analytics_tournament.csv"):
    """Single-row global battle analytics, written once at tournament end.

    A "match" here is the full 2-7 game Tiebreak series between one pair
    of trainers; a "game" is a single battle within that series - this
    project's own established distinction (see run_match). The average
    game length is turns-per-game; the average MATCH length is turns
    summed across every game of a match, averaged per match - a
    genuinely different, larger number, not just a renamed copy of the
    per-game figure."""
    avg_game_length = round(total_turns_all / total_games_played, 2) if total_games_played else 0.0
    avg_match_length = round(total_turns_all / total_matches, 2) if total_matches else 0.0
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Deadliest_Moves", "Deadliest_Species", "Item_Activation_Counts",
                          "Average_Game_Length_Turns", "Average_Match_Length_Turns"])
        writer.writerow([
            _format_ranked_counter(move_ko_counter),
            _format_ranked_counter(knockout_counter, species=True),
            _format_ranked_counter(item_activation_counter),
            avg_game_length,
            avg_match_length,
        ])


def export_standings_csv(rows, filename="standings.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Trainer_Key", "Display_Name", "Class", "Match_Wins", "Match_Losses",
                          "Match_Win_Rate", "Game_Wins", "Game_Losses", "Elo", "Tier", "Greatest_Win",
                          "Worst_Loss", "Longest_Match_Vs", "Average_Turns", "Team_and_Movesets"])
        for r in rows:
            writer.writerow([r["rank"], r["trainer_key"], r["display_name"], r["class"], r["match_wins"],
                              r["match_losses"], r["match_win_rate"], r["game_wins"], r["game_losses"],
                              r["elo"], r["tier"], r["greatest_win"], r["worst_loss"], r["longest_match_vs"],
                              r["avg_turns"], r["team_and_movesets"]])


def export_matches_csv(match_records, filename="matches.csv"):
    """match_records entries come from run_tournament's per-match loop
    (see the fields it builds); Trainer_A/Trainer_B/Match_Winner are
    display names rather than internal keys, since this file is meant to
    be readable on its own."""
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Match_ID", "Trainer_A", "Trainer_B", "Score_A", "Score_B",
                          "Match_Winner", "Total_Turns", "Seed_Base"])
        for m in match_records:
            writer.writerow([m["match_id"], m["trainer_a_name"], m["trainer_b_name"], m["score_a"],
                              m["score_b"], m["match_winner_name"], m["total_turns"], m["seed_base"]])


def build_tournament_summary(rows, knockout_counter, individual_ko_counter, move_ko_counter,
                              total_games_played, total_turns_all, biggest_upset, longest_match,
                              longest_match_by_games, longest_battle, comeback_highest_elo,
                              comeback_biggest_gap, roster_keys, pairs):
    avg_len = round(total_turns_all / total_games_played, 2) if total_games_played else 0.0

    top_5_individual = [
        {"trainer": DISPLAY_NAMES.get(trainer_key, trainer_key), "species": species, "knockouts": n}
        for (trainer_key, species), n in individual_ko_counter.most_common(5)
    ]
    # Same underlying data, but capped at one entry per SPECIES (keeping
    # whichever trainer's copy of that species scored the most
    # knockouts) - otherwise a species that happens to appear on several
    # near-identical trainers (e.g. the same Rival's Staraptor across
    # three counter-pick variants, or a Rematch alongside its base
    # encounter) can crowd out every other species in the top 5.
    best_per_species = {}
    for (trainer_key, species), n in individual_ko_counter.items():
        if species not in best_per_species or n > best_per_species[species][1]:
            best_per_species[species] = (trainer_key, n)
    top_5_individual_by_species = [
        {"trainer": DISPLAY_NAMES.get(tk, tk), "species": sp, "knockouts": n}
        for sp, (tk, n) in sorted(best_per_species.items(), key=lambda kv: kv[1][1], reverse=True)[:5]
    ]
    top_5_moves = [{"move": mv, "knockouts": n} for mv, n in move_ko_counter.most_common(5)]

    boss_rows = [r for r in rows if is_boss_trainer(r["trainer_key"])]
    generic_rows = [r for r in rows if not is_boss_trainer(r["trainer_key"]) and not is_battleground_trainer(r["trainer_key"])]
    top_generic_npc = generic_rows[0] if generic_rows else None
    bottom_5 = rows[-5:] if len(rows) >= 5 else list(rows)

    # Starter Triangle: Rival Barry's 3 possible Survival Area teams.
    triangle_keys = find_starter_triangle_trainers(roster_keys)
    rows_by_key = {r["trainer_key"]: r for r in rows}
    starter_triangle = []
    for player_starter, trainer_key in triangle_keys.items():
        row = rows_by_key.get(trainer_key)
        if row:
            starter_triangle.append({
                "if_player_chose": player_starter.title(),
                "barry_starter": STARTER_FINAL_EVO[STARTER_COUNTER_PICK[player_starter]],
                "trainer_key": trainer_key,
                "display_name": row["display_name"],
                "rank": row["rank"],
                "elo": row["elo"],
                "tier": row["tier"],
            })
    starter_triangle.sort(key=lambda e: e["elo"], reverse=True)

    # Meta Analytics: average final Elo per trainer class.
    class_elos = defaultdict(list)
    for r in rows:
        class_elos[r["class"]].append(r["elo"])
    avg_elo_by_class = sorted(
        ({"class": c, "avg_elo": round(sum(v) / len(v), 1), "trainer_count": len(v)} for c, v in class_elos.items()),
        key=lambda e: e["avg_elo"], reverse=True,
    )

    # Top Staller / Glass Cannon: highest and lowest average turns-per-game.
    # Only trainers who actually played at least one game are eligible -
    # a 0-game trainer would otherwise show a meaningless avg_turns of 0.0
    # and falsely "win" the Glass Cannon title.
    played_rows = [r for r in rows if r["avg_turns"] > 0]
    top_staller = max(played_rows, key=lambda r: r["avg_turns"]) if played_rows else None
    glass_cannon = min(played_rows, key=lambda r: r["avg_turns"]) if played_rows else None

    # Overachiever / Underachiever: a full 6-Pokemon team that still
    # finished at the bottom of the standings (you'd expect a full roster
    # to at least be competitive), and a lone single-Pokemon trainer that
    # nonetheless finished at the top (succeeding with no bench at all to
    # fall back on).
    full_team_rows = [r for r in rows if len(r["team_species"]) == 6]
    lowest_full_team = max(full_team_rows, key=lambda r: r["rank"]) if full_team_rows else None
    single_mon_rows = [r for r in rows if len(r["team_species"]) == 1]
    highest_single_mon = min(single_mon_rows, key=lambda r: r["rank"]) if single_mon_rows else None

    return {
        "metadata": {
            "format": "Tiebreak (win by 2, capped at 7 games)",
            "total_trainers": len(roster_keys),
            "total_matches": len(pairs),
        },
        "total_games_played": total_games_played,
        "total_turns": total_turns_all,
        "average_game_length_turns": avg_len,
        "biggest_upset": biggest_upset,
        "longest_match": longest_match,
        "longest_match_by_games": longest_match_by_games,
        "longest_battle": longest_battle,
        "comeback_highest_elo": comeback_highest_elo,
        "comeback_biggest_gap": comeback_biggest_gap,
        "lowest_full_team": lowest_full_team,
        "highest_single_mon": highest_single_mon,
        "top_5_knockout_pokemon": [{"species": sp, "knockouts": n} for sp, n in knockout_counter.most_common(5)],
        "top_5_knockout_individual_pokemon": top_5_individual,
        "top_5_knockout_individual_pokemon_by_species": top_5_individual_by_species,
        "top_5_knockout_moves": top_5_moves,
        "boss_leaderboard": boss_rows,
        "top_generic_npc": top_generic_npc,
        "bottom_5": bottom_5,
        "starter_triangle": starter_triangle,
        "avg_elo_by_class": avg_elo_by_class,
        "top_staller": top_staller,
        "glass_cannon": glass_cannon,
        "standings": rows,
    }


def export_tournament_summary_json(summary, filename="tournament_summary.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


# ============================================================
# ELO HISTORY + ENGINE VERSION STAMP (for Elo-race videos and for re-playing a recorded match from its seed)
# ============================================================
def elo_snapshot_due(match_id, total_matches):
    """Which matches get an Elo snapshot in elo_history.csv: about 1200 evenly spaced ones, 4x denser during the first 5% of the schedule
    (where ratings leave the shared 1500 start and move the most), and always the final match."""
    late = max(1, total_matches // 1200)
    early = max(1, late // 4)
    if match_id == total_matches:
        return True
    return (match_id <= total_matches * 0.05 and match_id % early == 0) or match_id % late == 0


def export_elo_history_csv(elo_history, roster_keys, filename="elo_history.csv"):
    """Wide format: one row per snapshot (Match_ID 0 is the shared 1500 start), one column per trainer, headed by Trainer_Key (always
    unique, unlike a display name). The last row is the final Elo that standings.csv reports."""
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Match_ID"] + list(roster_keys))
        for match_id, elos in elo_history:
            writer.writerow([match_id] + elos)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_fingerprint(root, pattern):
    """One hash for every file matching `pattern` under `root` (relative path + content): a changed, added or removed file changes it."""
    h = hashlib.sha256()
    for path in sorted(glob.glob(os.path.join(root, pattern))):
        h.update(os.path.relpath(path, root).replace("\\", "/").encode("utf-8"))
        h.update(_sha256_file(path).encode("ascii"))
    return h.hexdigest()


def engine_version_info():
    """Everything a seeded battle's outcome depends on besides its seed: this source file, the move database, the HGSS trainer file and
    the Platinum trainer / species / item data (version_id is a hash of just those), plus the tournament settings that go with them.
    Re-playing a recorded match from its Seed_Base only reproduces it under the same version_id - see save_engine_snapshot."""
    def file_hash(path):
        return _sha256_file(path) if os.path.isfile(path) else None

    def tree_hash(root, pattern):
        return _tree_fingerprint(root, pattern) if os.path.isdir(root) else None

    info = {
        "engine_file": os.path.basename(__file__),
        "engine_sha256": _sha256_file(__file__),
        "moves_db_sha256": file_hash(MOVES_DB_FILE),
        "hgss_trainers_sha256": file_hash(HGSS_TRAINER_DATA_FILE),
        "platinum_trainers_fingerprint": tree_hash(TRAINER_DATA_DIR, "*.json"),
        "species_fingerprint": tree_hash(SPECIES_DATA_DIR, os.path.join("*", "data.json")),
        "items_fingerprint": tree_hash(ITEM_DATA_DIR, "*.json"),
    }
    info["version_id"] = hashlib.sha256(json.dumps(info, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    info["settings"] = {"set_level": SET_LEVEL, "moveset_level_source": MOVESET_LEVEL_SOURCE,
                        "battle_mode": TOURNAMENT_BATTLE_MODE, "trainer_items_enabled": TRAINER_ITEMS_ENABLED,
                        "trainer_personality_enabled": TRAINER_PERSONALITY_ENABLED, "max_battle_turns": MAX_BATTLE_TURNS}
    return info


def save_engine_snapshot(info, root="engine_snapshots"):
    """Keeps one copy of this source file, the move database and the HGSS trainer file per version_id, so a later replay can load exactly
    the code and data that produced a dataset even after the working copy has moved on. Never raises: a failed copy only costs that
    convenience."""
    try:
        import shutil
        dest = os.path.join(root, info["version_id"])
        if os.path.isdir(dest):
            return dest
        tmp = f"{dest}.tmp{os.getpid()}"
        os.makedirs(tmp, exist_ok=True)
        for path in (__file__, MOVES_DB_FILE, HGSS_TRAINER_DATA_FILE):
            if os.path.isfile(path):
                shutil.copy2(path, os.path.join(tmp, os.path.basename(path)))
        with open(os.path.join(tmp, "version.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
        try:
            os.rename(tmp, dest)
        except OSError:                        # a parallel run saved the same version first
            shutil.rmtree(tmp, ignore_errors=True)
        return dest
    except Exception as e:
        print(f"WARNING: could not save an engine snapshot ({type(e).__name__}: {e}).")
        return None


def _md_table_row(*cells):
    # Escape any literal "|" in cell content (format_team_and_movesets
    # uses "|" as its own Pokemon separator, which would otherwise be
    # misread as extra table columns) so every cell renders safely
    # regardless of what's inside it.
    escaped = [str(c).replace("|", "\\|") for c in cells]
    return "| " + " | ".join(escaped) + " |"


def export_reddit_post(summary, rows, filename="reddit_post.md"):
    """Pre-formatted Reddit Markdown, ready to paste as-is into a new post."""
    n = summary["metadata"]["total_trainers"]
    # One "Pokemon N" column per team slot, sized to the largest party in
    # the whole roster so every leaderboard table uses the same column
    # count consistently. Species only, no movesets - standings.csv's
    # Team_and_Movesets column already has that level of detail.
    max_team_size = max((len(r["team_species"]) for r in rows), default=1)
    pokemon_headers = [f"Pokemon {i + 1}" for i in range(max_team_size)]

    def team_cells(r):
        species = r["team_species"]
        return species + [""] * (max_team_size - len(species))

    lines = [
        f"# Pokemon Platinum AI Tournament: Ranking All {n} Trainers",
        "",
        "## Executive Summary",
        "",
        f"- **Format:** Tiebreak (win by 2, capped at 7 games), full round robin ({summary['metadata']['total_matches']} matches)",
        f"- **Total games played:** {summary['total_games_played']}",
        f"- **Total turns simulated:** {summary['total_turns']}",
        f"- **Average battle length:** {summary['average_game_length_turns']} turns",
        "",
        "## Top 10 Leaderboard (First Playthrough)",
        "",
        "*Rematches, Battleground, Survival Area, and Fight Area encounters are excluded so postgame-only "
        "fights don't crowd out the roster you'd actually meet on a first run.*",
        "",
        "| Rank | Trainer | Record | Game W/L | Elo | Tier | Notable Win | Notable Loss | " + " | ".join(pokemon_headers) + " |",
        "|---|---|---|---|---|---|---|---|" + "---|" * max_team_size,
    ]
    first_playthrough_rows = [r for r in rows if not is_postgame_trainer(r["trainer_key"])]
    for r in first_playthrough_rows[:10]:
        record = f"{r['match_wins']}-{r['match_losses']}"
        game_wl = f"{r['game_wins']}-{r['game_losses']}"
        lines.append(_md_table_row(r["rank"], r["display_name"], record, game_wl, r["elo"], r["tier"],
                                    r["greatest_win"], r["worst_loss"], *team_cells(r)))

    # --- Top 10 Leaderboard, every trainer including postgame content ---
    lines += ["", "## Top 10 Leaderboard (All Trainers)", "",
              "*Every trainer in this tournament, rematches and postgame encounters included.*", "",
              "| Rank | Trainer | Record | Game W/L | Elo | Tier | Notable Win | Notable Loss | " + " | ".join(pokemon_headers) + " |",
              "|---|---|---|---|---|---|---|---|" + "---|" * max_team_size]
    for r in rows[:10]:
        record = f"{r['match_wins']}-{r['match_losses']}"
        game_wl = f"{r['game_wins']}-{r['game_losses']}"
        lines.append(_md_table_row(r["rank"], r["display_name"], record, game_wl, r["elo"], r["tier"],
                                    r["greatest_win"], r["worst_loss"], *team_cells(r)))

    # --- Top 10 Leaderboard, boss trainers (Leaders/Elite Four/Champions/
    # Rivals/Battleground/Red/evil-team bosses) excluded entirely ---
    lines += ["", "## Top 10 Leaderboard (Non-Boss NPCs)", "",
              "*Gym Leaders, Elite Four, Champions, Rivals, Battleground trainers, Pokemon Trainer Red, and "
              "evil-team bosses are excluded, so this ranks generic trainers against each other.*", "",
              "| Rank | Trainer | Record | Game W/L | Elo | Tier | Notable Win | Notable Loss | " + " | ".join(pokemon_headers) + " |",
              "|---|---|---|---|---|---|---|---|" + "---|" * max_team_size]
    non_boss_rows = [r for r in rows if not is_excludable_boss_trainer(r["trainer_key"])]
    if non_boss_rows:
        for r in non_boss_rows[:10]:
            record = f"{r['match_wins']}-{r['match_losses']}"
            game_wl = f"{r['game_wins']}-{r['game_losses']}"
            lines.append(_md_table_row(r["rank"], r["display_name"], record, game_wl, r["elo"], r["tier"],
                                        r["greatest_win"], r["worst_loss"], *team_cells(r)))
    else:
        lines.append("No non-Boss trainers found in this roster.")

    # --- Top Performing Generic NPC ---
    lines += ["", "## Top Performing Generic NPC", ""]
    tg = summary["top_generic_npc"]
    if tg:
        lines.append(f"**{tg['display_name']}** - Rank #{tg['rank']}, Record {tg['match_wins']}-{tg['match_losses']}, "
                      f"Elo {tg['elo']} ({tg['tier']} Tier) - the strongest trainer in the tournament who isn't a "
                      f"Gym Leader, Elite Four member, Champion, or Rival.")
    else:
        lines.append("No non-Boss trainers found in this roster.")

    # --- The Wooden Spoon (Bottom 5) ---
    lines += ["", "## The Wooden Spoon (Bottom 5)", ""]
    bottom_5 = summary["bottom_5"]
    if bottom_5:
        lines.append("| Rank | Trainer | Record | Game W/L | Elo | Tier | " + " | ".join(pokemon_headers) + " |")
        lines.append("|---|---|---|---|---|---|" + "---|" * max_team_size)
        for r in reversed(bottom_5):
            record = f"{r['match_wins']}-{r['match_losses']}"
            game_wl = f"{r['game_wins']}-{r['game_losses']}"
            lines.append(_md_table_row(r["rank"], r["display_name"], record, game_wl, r["elo"], r["tier"],
                                        *team_cells(r)))
    else:
        lines.append("Not enough trainers to name a bottom 5.")

    # --- Tournament Highlights ---
    lines += ["", "## Tournament Highlights", ""]
    upset = summary["biggest_upset"]
    if upset:
        lines.append(f"**Biggest Upset:** {upset['underdog']} (Elo {upset['underdog_elo']}) defeated "
                      f"{upset['favorite']} (Elo {upset['favorite_elo']}) - a {upset['elo_diff']} Elo upset, "
                      f"winning the match {upset['score']}.")
    else:
        lines.append("**Biggest Upset:** None - every match went to the higher-rated trainer.")
    lines.append("")

    lm = summary["longest_match"]
    if lm:
        lines.append(f"**Longest Match:** {lm['trainer_a']} vs {lm['trainer_b']} - "
                      f"{lm['total_turns']} total turns across {lm['games_played']} games. "
                      f"(`{lm['log_reference']}`)")
    else:
        lines.append("**Longest Match:** No matches played.")
    lines.append("")

    lmg = summary["longest_match_by_games"]
    if lmg:
        lines.append(f"**Longest Match (by Games):** {lmg['trainer_a']} vs {lmg['trainer_b']} - "
                      f"went the distance at {lmg['games_played']} games (final score {lmg['score']}). "
                      f"(`{lmg['log_reference']}`)")
    else:
        lines.append("**Longest Match (by Games):** No matches played.")
    lines.append("")

    lb = summary["longest_battle"]
    if lb:
        lines.append(f"**Longest Battle:** {lb['trainer_a']} vs {lb['trainer_b']} (Game {lb['game_num']}) - "
                      f"{lb['turns']} turns in that single battle alone. (`{lb['log_reference']}`)")
    else:
        lines.append("**Longest Battle:** No games played.")
    lines.append("")

    staller = summary["top_staller"]
    if staller:
        lines.append(f"**Top Staller:** {staller['display_name']} - averaged **{staller['avg_turns']} turns per game**, "
                      f"the slowest grind in the tournament.")
    else:
        lines.append("**Top Staller:** No games played.")
    lines.append("")

    cannon = summary["glass_cannon"]
    if cannon:
        lines.append(f"**Glass Cannon:** {cannon['display_name']} - averaged just **{cannon['avg_turns']} turns per game**, "
                      f"ending fights faster than anyone else (for better or worse).")
    else:
        lines.append("**Glass Cannon:** No games played.")
    lines.append("")

    comeback_elo = summary["comeback_highest_elo"]
    if comeback_elo:
        lines.append(f"**Comeback Award (Highest Elo):** {comeback_elo['winner']} (Elo {comeback_elo['winner_elo']}) "
                      f"lost Game 1 but came back to beat {comeback_elo['loser']} (Elo {comeback_elo['loser_elo']}) "
                      f"{comeback_elo['score']} - the highest-rated trainer to pull off a comeback.")
    else:
        lines.append("**Comeback Award (Highest Elo):** No comebacks (a Game 1 loss followed by a match win) recorded.")
    lines.append("")

    comeback_gap = summary["comeback_biggest_gap"]
    if comeback_gap:
        lines.append(f"**Comeback Award (Biggest Elo Gap):** {comeback_gap['winner']} (Elo {comeback_gap['winner_elo']}) "
                      f"lost Game 1 but came back to beat {comeback_gap['loser']} (Elo {comeback_gap['loser_elo']}) "
                      f"{comeback_gap['score']} - a {comeback_gap['elo_diff']} Elo gap between the two, the widest of any comeback.")
    else:
        lines.append("**Comeback Award (Biggest Elo Gap):** No comebacks (a Game 1 loss followed by a match win) recorded.")
    lines.append("")

    lft = summary["lowest_full_team"]
    if lft:
        lines.append(f"**Overachiever's Nightmare (Lowest-Ranked Full Team):** {lft['display_name']} - Rank #{lft['rank']}, "
                      f"Elo {lft['elo']} ({lft['tier']} Tier) - a full 6-Pokemon roster that still finished at the bottom.")
    else:
        lines.append("**Overachiever's Nightmare (Lowest-Ranked Full Team):** No full 6-Pokemon teams found in this roster.")
    lines.append("")

    hsm = summary["highest_single_mon"]
    if hsm:
        lines.append(f"**Lone Wolf (Highest-Ranked Single Pokemon):** {hsm['display_name']} - Rank #{hsm['rank']}, "
                      f"Elo {hsm['elo']} ({hsm['tier']} Tier) - carried the whole tournament with just one Pokemon and no bench to fall back on.")
    else:
        lines.append("**Lone Wolf (Highest-Ranked Single Pokemon):** No single-Pokemon trainers found in this roster.")
    lines.append("")

    lines.append("**Top 5 Deadliest Pokemon (by species, total knockouts):**")
    lines.append("")
    if summary["top_5_knockout_pokemon"]:
        for i, entry in enumerate(summary["top_5_knockout_pokemon"], start=1):
            species_display = entry["species"].replace("SPECIES_", "").replace("_", " ").title()
            lines.append(f"{i}. **{species_display}** - {entry['knockouts']} knockouts")
    else:
        lines.append("No knockouts recorded.")
    lines.append("")

    lines.append("**Top 5 Deadliest INDIVIDUAL Pokemon (one specific trainer's Pokemon):**")
    lines.append("")
    if summary["top_5_knockout_individual_pokemon"]:
        for i, entry in enumerate(summary["top_5_knockout_individual_pokemon"], start=1):
            species_display = entry["species"].replace("SPECIES_", "").replace("_", " ").title()
            lines.append(f"{i}. **{entry['trainer']}'s {species_display}** - {entry['knockouts']} knockouts")
    else:
        lines.append("No knockouts recorded.")
    lines.append("")

    lines.append("**Top 5 Deadliest INDIVIDUAL Pokemon, one per species** "
                  "*(so near-identical trainers with the same species don't crowd the list)*:")
    lines.append("")
    if summary["top_5_knockout_individual_pokemon_by_species"]:
        for i, entry in enumerate(summary["top_5_knockout_individual_pokemon_by_species"], start=1):
            species_display = entry["species"].replace("SPECIES_", "").replace("_", " ").title()
            lines.append(f"{i}. **{entry['trainer']}'s {species_display}** - {entry['knockouts']} knockouts")
    else:
        lines.append("No knockouts recorded.")
    lines.append("")

    lines.append("**Top 5 Deadliest Moves (by knockouts):**")
    lines.append("")
    if summary["top_5_knockout_moves"]:
        for i, entry in enumerate(summary["top_5_knockout_moves"], start=1):
            move_display = entry["move"].replace("MOVE_", "").replace("_", " ").title()
            lines.append(f"{i}. **{move_display}** - {entry['knockouts']} knockouts")
    else:
        lines.append("No knockouts recorded.")

    # --- Meta Analytics ---
    lines += ["", "## Meta Analytics: Average Elo by Trainer Class", ""]
    avg_by_class = summary["avg_elo_by_class"]
    if avg_by_class:
        lines.append("| Trainer Class | Avg Elo | Trainer Count |")
        lines.append("|---|---|---|")
        for entry in avg_by_class:
            lines.append(_md_table_row(entry["class"], entry["avg_elo"], entry["trainer_count"]))
    else:
        lines.append("No class data available.")

    lines += ["", "## Tier List", ""]
    by_tier = defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r["display_name"])
    for tier_name in TIER_NAMES_DESCENDING:
        members = by_tier.get(tier_name)
        if not members:
            continue
        lines.append(f"**{tier_name} Tier**: {', '.join(members)}")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def is_dummy_trainer(key):
    """The repo's trainer data includes placeholder 'Dummy' slots (unused/
    reserved trainer IDs, not real encounters) - filenames like
    'dummy_1.json' or 'dummy_trainer.json'. Left in, a full round robin
    wastes a huge number of matches on meaningless Dummy-vs-Dummy (and
    Dummy-vs-everyone) pairings. Matched as a substring, case-insensitive,
    against the trainer KEY (the filename), not the display name, since
    it needs to apply before a display name is even relevant."""
    return "dummy" in key.lower()


def is_unused_trainer(key):
    """Distinct from is_dummy_trainer: an "unused" trainer (filenames like
    'guitarist_arturo_unused.json' or 'youngster_norman_unused_1.json')
    has completely legitimate, fully-formed trainer data - a real party,
    real battle messages, everything - it just never actually gets
    encountered in the shipped game (cut content, leftover duplicate
    encounter slots, etc.), unlike Dummy's placeholder junk. Because the
    data is genuinely valid, whether to include these is a real choice
    left to the person running the tournament (see prompt_for_unused_trainers
    in __main__) rather than an automatic exclusion."""
    return "unused" in key.lower()


# Evil-team final bosses (Cyrus leads Team Galactic in Platinum; Giovanni
# leads Team Rocket in HGSS) have no dedicated filename PREFIX the way
# Leaders/Elite Four/Champions/Rivals do (see BOSS_KEY_PREFIXES) - they're
# unique, named encounters, so they're matched by name instead. This is a
# best-effort list built from general knowledge of these games rather
# than the actual trainer data files, since neither could be inspected
# directly - if the real filenames differ from what's listed here (e.g.
# a different spelling, or additional evil-team bosses this list is
# missing), they'd need to be added.
EVIL_TEAM_BOSS_NAMES = ("cyrus", "giovanni")


def is_excludable_boss_trainer(key):
    """Used by the tournament's "exclude boss trainers" setting: Elite
    Four, Gym Leaders, Champions, and Rivals (all covered by
    is_boss_trainer's filename-prefix matching), Battleground trainers
    (is_battleground_trainer), Pokemon Trainer Red, and evil-team final
    bosses (EVIL_TEAM_BOSS_NAMES). Red and the evil-team bosses are
    matched as whole underscore-separated words in the key (not a plain
    substring test) specifically to avoid a false positive on some other
    word that merely CONTAINS "red" or one of the boss names."""
    if is_boss_trainer(key) or is_battleground_trainer(key):
        return True
    words = key.lower().split("_")
    if "red" in words:
        return True
    return any(name in words for name in EVIL_TEAM_BOSS_NAMES)


# ---- two-trainer battles ("duos") -----------------------------------------------------------------------------------------
# A few fights in the games are fought by TWO trainers side by side, each with their own team (Commander Jupiter & Mars at Spear Pillar,
# Bug Catcher Jack & Lass Briana, Clair & Lance in the Dragon's Den). The data files hold each trainer separately, so in a tournament that
# plays doubles (normal or forced doubles) each pair is fielded as ONE trainer whose party is both teams (interleaved, so the two leads
# are one from each trainer) and the two separate entries drop out of the roster. A forced-singles tournament keeps them separate.
# (base key A, base key B, display name); HGSS keys carry a "hgss_" prefix in a combined roster, and are matched either way.
DUO_TRAINER_PAIRS = (
    ("commander_jupiter_spear_pillar", "commander_mars_spear_pillar", "Commander Jupiter & Mars (Spear Pillar)"),
    ("bug_catcher_jack", "lass_briana", "Bug Catcher Jack & Lass Briana"),
    ("leader_clair_clair_dd", "champion_lance_dd", "Leader Clair & Champion Lance (DD)"),
)


def _strip_game_prefix(key):
    return key[len("hgss_"):] if key.startswith("hgss_") else key


def install_duo_trainers():
    """Registers each configured duo whose two members are both loaded as one merged entry in TRAINERS_DB / DISPLAY_NAMES (idempotent).
    The merged trainer keeps the first member's class, the union of both AI flags and item lists, is a double-battle trainer, and lists
    its members under "members". Returns the merged keys."""
    added = []
    for key_a, key_b, display in DUO_TRAINER_PAIRS:
        for prefix in ("", "hgss_"):
            ka, kb = prefix + key_a, prefix + key_b
            if ka not in TRAINERS_DB or kb not in TRAINERS_DB:
                continue
            duo_key = f"{ka}_and_{kb}"
            added.append(duo_key)
            if duo_key in TRAINERS_DB:
                continue
            a, b = TRAINERS_DB[ka], TRAINERS_DB[kb]
            party = []
            for i in range(max(len(a["party"]), len(b["party"]))):
                party.extend(t["party"][i] for t in (a, b) if i < len(t["party"]))
            flags = list(dict.fromkeys(list(a.get("ai_flags", [])) + list(b.get("ai_flags", []))))
            TRAINERS_DB[duo_key] = {"class": a.get("class"), "base_name": display, "ai_flags": flags or ["TRAINER_AI_BASIC"],
                                    "items": list(a.get("items", [])) + list(b.get("items", [])), "party": party,
                                    "double_battle": True, "members": [ka, kb]}
            DISPLAY_NAMES[duo_key] = display
    return added


def apply_duo_roster(roster_keys, battle_mode):
    """Swaps duo members for their merged trainer (a duo whose member OR merged key is in the roster appears once, at the first
    position) unless the tournament is forced to singles, where the merged entries are dropped and the members stay separate."""
    install_duo_trainers()
    duos = {k for k in roster_keys if TRAINERS_DB.get(k, {}).get("members")}
    if battle_mode == "singles":
        return [k for k in roster_keys if k not in duos]
    member_of = {m: k for k, t in TRAINERS_DB.items() for m in t.get("members", ())}
    out, seen = [], set()
    for k in roster_keys:
        duo = k if k in duos else member_of.get(k)
        if duo is None:
            out.append(k)
        elif duo not in seen:
            seen.add(duo)
            out.append(duo)
    return out


# ---- "Generic NPCs only" ----------------------------------------------------------------------------------------------------
# Story characters, gym / league bosses and the evil teams are not generic trainers. Matched on the trainer CLASS (with the game's
# TRAINER_CLASS_ / TRAINERCLASS_ prefix removed), on top of is_excludable_boss_trainer's key-based rules (Leaders, Elite Four, Champions,
# Rivals, Battleground, Red, Cyrus, Giovanni).
EVIL_TEAM_CLASS_PREFIXES = ("COMMANDER_", "GALACTIC_", "TEAM_ROCKET", "EXECUTIVE_", "ROCKET_BOSS")
STORY_CLASS_PREFIXES = ("LEADER_", "ELITE_FOUR_", "CHAMPION", "RIVAL", "DP_PLAYER_", "PKMN_TRAINER_", "TRAINER_")      # TRAINER_BUCK etc.
FRONTIER_BRAIN_CLASSES = ("TOWER_TYCOON", "FACTORY_HEAD", "HALL_MATRON", "ARCADE_STAR", "CASTLE_VALET")
EVIL_TEAM_KEY_PREFIXES = ("commander_", "galactic_", "team_rocket", "executive_", "rocket_boss")


def _class_stem(cls):
    return (cls or "").replace("TRAINER_CLASS_", "").replace("TRAINERCLASS_", "")


def is_evil_team_trainer(key):
    """A Commander, Grunt, Executive, Admin-level member or boss of Team Galactic / Team Rocket (by class, else by key)."""
    t = TRAINERS_DB.get(key) or {}
    if t.get("members"):
        return any(is_evil_team_trainer(m) for m in t["members"])
    stem = _class_stem(t.get("class"))
    return stem.startswith(EVIL_TEAM_CLASS_PREFIXES) or _strip_game_prefix(key.lower()).startswith(EVIL_TEAM_KEY_PREFIXES)


def is_generic_npc(key):
    """True for an ordinary trainer: not a boss, story character, Frontier Brain or evil-team member. A duo is generic only if both
    members are."""
    t = TRAINERS_DB.get(key) or {}
    if t.get("members"):
        return all(is_generic_npc(m) for m in t["members"])
    stem = _class_stem(t.get("class"))
    if stem.startswith(STORY_CLASS_PREFIXES) or stem in FRONTIER_BRAIN_CLASSES:
        return False
    return not (is_excludable_boss_trainer(_strip_game_prefix(key)) or is_evil_team_trainer(key))


def format_duration(seconds):
    """Plain H:MM:SS / M:SS formatting for the progress ETA - no extra
    imports beyond the stdlib `time` module already used to measure it."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def find_mimic_trainers(roster_keys):
    """Trainer keys (from an already-loaded, already-filtered roster_keys list) with at least one party member that
    knows Mimic. Reads TRAINERS_DB[key]["party"], so this only sees what THIS run actually loaded - a set-level or
    moveset-level override (SET_LEVEL / MOVESET_LEVEL_SOURCE) that changes a Pokemon's auto-derived learnset moves is
    reflected here exactly as it would be simulated. Used by run_tournament's mimic_supplement mode (see there)."""
    return [k for k in roster_keys if any("MOVE_MIMIC" in mon.get("moves", ()) for mon in TRAINERS_DB[k].get("party", ()))]


def run_tournament(target_names=None, exclude_dummies=True, exclude_unused=False, generic_only=False, exclude_bosses=None,
                    mimic_supplement=False):
    """target_names: optional list of display names (or trainer keys) to
    restrict the roster to, e.g. ["Champion Cynthia", "Elite Four Lucian"].
    Leave as None to run the FULL roster loaded from TRAINER_DATA_DIR -
    every trainer file, including every rematch tier, all playing each
    other once (Tiebreak format each - see run_match: a clean 2-0 sweep
    ends it in 2 games, otherwise up to 7). For a large roster this is a
    LOT of individual battles (C(n,2) matchups x up to 7 games each), so
    expect a long run for hundreds of trainers.
    exclude_dummies: drops any trainer whose key contains "dummy" (see
    is_dummy_trainer) from the roster before pairing anyone up - these
    are placeholder trainer slots in the repo's data, not real fights.
    Set to False if you deliberately want to include them (e.g. to sanity
    check that they load correctly at all).
    exclude_unused: drops any trainer whose key contains "unused" (see
    is_unused_trainer) - unlike Dummy trainers this data is completely
    legitimate, it just never comes up in the shipped game, so this
    defaults to False (included) unless asked to leave them out. The
    __main__ entry point below always asks the person running the
    tournament explicitly, regardless of test-run size, rather than
    relying on this default.
    generic_only: keeps only ordinary trainers (see is_generic_npc): drops
    Elite Four, Gym Leaders, Champions, Rivals, Battleground trainers, Red,
    Frontier Brains, story characters and every evil-team member (Commanders,
    Grunts, Executives, bosses). Defaults to False (included). exclude_bosses
    is the old name for this setting and is honoured if given.
    Two-trainer fights (DUO_TRAINER_PAIRS) are one merged trainer in a
    normal or doubles tournament and two separate ones in a singles one.
    mimic_supplement: instead of the full C(n,2) round robin, only plays a pair when AT LEAST ONE side knows Mimic
    (find_mimic_trainers) - every pair between two non-Mimic trainers is skipped outright. Lets a dataset that
    predates Mimic_Move_Usage tracking (see mimic_move_usage/mimic_active in parse_battle_log_for_analytics) get that
    one column filled in for its Mimic-using species, against a full spread of opponents, without re-simulating the
    huge majority of pairs that could never have touched a Mimic-copied move anyway. Standings/Elo/W-L from this mode
    are NOT representative of a real tournament (most trainers only play a handful of games here, not a full
    schedule) - see merge_mimic_move_usage, which is what actually folds this run's results back into the main
    dataset, and only touches the Mimic_Move_Usage column, nothing else."""
    if exclude_bosses is not None:
        generic_only = generic_only or exclude_bosses
    install_duo_trainers()
    print(f"Loaded {sum(1 for t in TRAINERS_DB.values() if not t.get('members'))} total trainers (including rematch tiers) from repository directory.")

    if target_names:
        wanted = set(target_names)
        roster_keys = [k for k in TRAINERS_DB if k in wanted or DISPLAY_NAMES.get(k) in wanted]
        if not roster_keys:
            print("WARNING: none of the requested target_names matched a loaded trainer.")
            print("Sample of available display names:", list(DISPLAY_NAMES.values())[:20])
            return
    else:
        roster_keys = list(TRAINERS_DB.keys())

    roster_keys = apply_duo_roster(roster_keys, TOURNAMENT_BATTLE_MODE)
    if TOURNAMENT_BATTLE_MODE != "singles":
        merged = [k for k in roster_keys if TRAINERS_DB[k].get("members")]
        if merged:
            print(f"Two-trainer fights fielded as one trainer: {', '.join(DISPLAY_NAMES.get(k, k) for k in merged)}.")

    if exclude_dummies:
        before = len(roster_keys)
        roster_keys = [k for k in roster_keys if not is_dummy_trainer(k)]
        n_excluded = before - len(roster_keys)
        if n_excluded:
            print(f"Excluded {n_excluded} placeholder 'Dummy' trainer(s) from the roster.")

    if exclude_unused:
        before = len(roster_keys)
        roster_keys = [k for k in roster_keys if not is_unused_trainer(k)]
        n_excluded = before - len(roster_keys)
        if n_excluded:
            print(f"Excluded {n_excluded} 'unused' trainer(s) from the roster.")

    if generic_only:
        before = len(roster_keys)
        roster_keys = [k for k in roster_keys if is_generic_npc(k)]
        n_excluded = before - len(roster_keys)
        if n_excluded:
            print(f"Excluded {n_excluded} non-generic trainer(s) (bosses, story characters, Frontier Brains, evil-team members) from the roster.")

    if not roster_keys:
        print("WARNING: no trainers loaded - check TRAINER_DATA_DIR.")
        return

    shared_names = sorted(n for n, c in Counter(DISPLAY_NAMES.get(k, k) for k in roster_keys).items() if c > 1)
    if shared_names:
        print(f"WARNING: {len(shared_names)} display name(s) belong to more than one trainer ({', '.join(shared_names[:8])}"
              f"{', ...' if len(shared_names) > 8 else ''}) - their battle-log files overwrite each other, and anything that looks "
              f"a trainer up by name can't tell them apart.")
    version_info = engine_version_info()
    save_engine_snapshot(version_info)
    print(f"Engine version {version_info['version_id']} (engine file {version_info['engine_sha256'][:12]}).")

    if mimic_supplement:
        mimic_keys = set(find_mimic_trainers(roster_keys))
        if not mimic_keys:
            print("WARNING: no trainer in this roster has a Pokemon that knows Mimic - nothing to do.")
            return
        print(f"mimic_supplement: {len(mimic_keys)} trainer(s) know Mimic: "
              f"{', '.join(sorted(DISPLAY_NAMES.get(k, k) for k in mimic_keys))}")
        pairs = [(a, b) for a, b in itertools.combinations(roster_keys, 2) if a in mimic_keys or b in mimic_keys]
    else:
        pairs = list(itertools.combinations(roster_keys, 2))
    # Randomize the order matches are played in. itertools.combinations
    # otherwise always plays every one of roster_keys[0]'s matches before
    # roster_keys[1] plays anyone but roster_keys[0], and so on - since
    # TRAINERS_DB (and so roster_keys) is built from alphabetically-sorted
    # filenames, that means trainers late in the alphabet always face
    # opponents who already have many more Elo updates under their belt
    # than early-alphabet trainers did at the same point in THEIR own
    # schedule. That schedule-order bias, not the K-factor itself, is what
    # let late-alphabet trainers farm inflated ratings. Shuffling breaks
    # the correlation between a trainer's position in the schedule and
    # its position in the alphabet.
    random.shuffle(pairs)
    total_pairs = len(pairs)
    print(f"Starting round robin (Tiebreak format) with {len(roster_keys)} combatants -> "
          f"{total_pairs} matchups, up to {total_pairs * 7} individual games.")

    standings = {k: new_standing_entry() for k in roster_keys}
    elo_history = [(0, [standings[k]["elo"] for k in roster_keys])]        # Elo snapshots, see elo_snapshot_due -> elo_history.csv

    # Tournament-wide telemetry for the CSV/JSON/Reddit export pipeline.
    match_records = []             # one row per match, feeds matches.csv
    knockout_counter = Counter()          # species -> total KOs landed
    individual_ko_counter = Counter()     # (trainer_key, species) -> total KOs landed by THAT specific trainer's Pokemon
    move_ko_counter = Counter()           # move name -> total KOs landed with it
    item_activation_counter = Counter()   # consumable held item -> actual in-battle activations
    individual_analytics = {}             # "trainer_species" -> merged move-usage/KO/lifespan/RNG stats (see merge_game_analytics)
    turns_by_trainer = defaultdict(lambda: {"total_turns": 0, "games": 0})  # for average-turns-per-game (Staller/Glass Cannon)
    total_games_played = 0
    total_turns_all = 0
    biggest_upset = None           # highest positive Elo gap where the lower-rated trainer won the MATCH
    comeback_highest_elo = None    # comeback (lost Game 1, won the match) with the highest pre-match WINNER Elo
    comeback_biggest_gap = None    # comeback with the largest pre-match Elo gap between the two trainers, either direction
    longest_match = None           # most total turns SUMMED across a single match's games (up to 7 now, Tiebreak format)
    longest_match_by_games = None  # the match that went the MOST GAMES (2-0/3-1/4-2/4-3 - see run_match)
    longest_battle = None          # most turns in a single INDIVIDUAL game, anywhere in the tournament
    start_time = time.time()       # for the live "matches done / ETA" progress line below

    for match_id, (t_a, t_b) in enumerate(pairs, start=1):
        seed_base = (hash(f"{t_a}_{t_b}") % 900000) * 10
        name_a, name_b = DISPLAY_NAMES.get(t_a, t_a), DISPLAY_NAMES.get(t_b, t_b)

        # Elo as it stood entering this match, captured before any of this
        # match's games touch it - both for standard per-game upset/best-win
        # tracking below (unchanged) and for the match-level upset check.
        elo_a_pre = standings[t_a]["elo"]
        elo_b_pre = standings[t_b]["elo"]

        match_winner, wins_a, wins_b, games_played, total_turns, game_results, game_stats_list = run_match(t_a, t_b, seed_base)
        match_loser = t_b if match_winner == t_a else t_a

        total_games_played += games_played
        total_turns_all += total_turns

        for t_this, t_opp in ((t_a, t_b), (t_b, t_a)):
            if games_played > standings[t_this]["longest_match_games"]:
                standings[t_this]["longest_match_games"] = games_played
                standings[t_this]["longest_match_opponent"] = t_opp

        # KOs are accumulated per MATCH as well as globally so Sweep_Count
        # means 3+ KOs by the same trainer/species across this tournament
        # match (not merely within one game of the set).
        match_ko_counter = Counter()
        for gstats in game_stats_list:
            for ko in gstats["knockouts"]:
                knockout_counter[ko["species"]] += 1
                individual_ko_counter[(ko["trainer"], ko["species"])] += 1
                move_ko_counter[ko["move"]] += 1
                match_ko_counter[(ko["trainer"], ko["species"])] += 1
            try:
                log_lines = gstats.pop("log_lines", ())
                item_activation_counter.update(count_item_activations(log_lines))
                game_analytics = parse_battle_log_for_analytics(log_lines, t_a, name_a, t_b, name_b)
                apply_knockout_relationships(game_analytics, gstats["knockouts"])
                apply_assist_events(game_analytics, gstats.get("assist_events", ()))
                apply_secondary_roll_events(game_analytics, gstats.get("secondary_roll_events", ()))
                if "damaging_hit_events" in gstats:
                    apply_damaging_hit_events(game_analytics, gstats["damaging_hit_events"])
                merge_game_analytics(individual_analytics, game_analytics)
            except Exception as e:
                print(f"WARNING: could not parse in-memory battle log for analytics ({gstats['log_file']}): {e}")
            # Every game involves exactly these two trainers, regardless of
            # who won - both get this game's turn count added toward their
            # own average-turns-per-game.
            turns_by_trainer[t_a]["total_turns"] += gstats["turns"]
            turns_by_trainer[t_a]["games"] += 1
            turns_by_trainer[t_b]["total_turns"] += gstats["turns"]
            turns_by_trainer[t_b]["games"] += 1

            if longest_battle is None or gstats["turns"] > longest_battle["turns"]:
                longest_battle = {
                    "trainer_a": name_a,
                    "trainer_b": name_b,
                    "game_num": gstats["game_num"],
                    "turns": gstats["turns"],
                    "log_reference": gstats["log_file"],
                }

        for (trainer_key, species), kos_in_match in match_ko_counter.items():
            if kos_in_match >= 3:
                ident = _analytics_ident(trainer_key, species)
                if ident in individual_analytics:
                    individual_analytics[ident]["sweep_count"] += 1

        standings[t_a]["game_wins"] += wins_a
        standings[t_a]["game_losses"] += wins_b
        standings[t_b]["game_wins"] += wins_b
        standings[t_b]["game_losses"] += wins_a
        standings[match_winner]["match_wins"] += 1
        standings[match_loser]["match_losses"] += 1

        # Record who beat/lost to whom as the tournament plays out - the
        # actual "greatest win"/"worst loss" comparison happens once at
        # the very end, using final Elo (see resolve_best_win_worst_loss),
        # not each opponent's rating at the moment this particular game
        # was played.
        for winner in game_results:
            loser = t_b if winner == t_a else t_a
            standings[winner]["beaten_opponents"].add(loser)
            standings[loser]["lost_to_opponents"].add(winner)

            standings[winner]["elo"], standings[loser]["elo"] = update_elo(
                standings[winner]["elo"], standings[loser]["elo"],
                k_w=compute_k_factor(standings[winner]["elo_games"]),
                k_l=compute_k_factor(standings[loser]["elo_games"]),
            )
            standings[winner]["elo_games"] += 1
            standings[loser]["elo_games"] += 1

        # Match-level upset tracker: whichever trainer had the higher Elo
        # BEFORE this match is the "favorite" - if the other trainer (the
        # "underdog") won the whole match anyway, that's an upset, sized by
        # how big the pre-match Elo gap was.
        if elo_a_pre >= elo_b_pre:
            favorite, favorite_elo, underdog, underdog_elo = t_a, elo_a_pre, t_b, elo_b_pre
        else:
            favorite, favorite_elo, underdog, underdog_elo = t_b, elo_b_pre, t_a, elo_a_pre
        if match_winner == underdog and favorite_elo > underdog_elo:
            elo_diff = round(favorite_elo - underdog_elo, 1)
            if biggest_upset is None or elo_diff > biggest_upset["elo_diff"]:
                biggest_upset = {
                    "underdog": DISPLAY_NAMES.get(underdog, underdog),
                    "underdog_elo": underdog_elo,
                    "favorite": DISPLAY_NAMES.get(favorite, favorite),
                    "favorite_elo": favorite_elo,
                    "elo_diff": elo_diff,
                    "score": f"{wins_a}-{wins_b}" if match_winner == t_a else f"{wins_b}-{wins_a}",
                }

        # Comeback Award: the match winner lost Game 1 but still took the
        # match overall. Tracked two ways - the comeback pulled off by the
        # highest pre-match-rated winner (the more "prestigious" the
        # trainer, the more impressive clawing back from an 0-1 hole), and
        # the comeback with the largest pre-match Elo gap between the two
        # trainers regardless of who was favored (the most surprising
        # result to see recover from a Game 1 loss at all).
        if game_results and game_results[0] != match_winner:
            winner_elo_pre = elo_a_pre if match_winner == t_a else elo_b_pre
            loser_elo_pre = elo_b_pre if match_winner == t_a else elo_a_pre
            comeback_entry = {
                "winner": DISPLAY_NAMES.get(match_winner, match_winner),
                "winner_elo": winner_elo_pre,
                "loser": DISPLAY_NAMES.get(match_loser, match_loser),
                "loser_elo": loser_elo_pre,
                "elo_diff": round(abs(winner_elo_pre - loser_elo_pre), 1),
                "score": f"{wins_a}-{wins_b}" if match_winner == t_a else f"{wins_b}-{wins_a}",
            }
            if comeback_highest_elo is None or winner_elo_pre > comeback_highest_elo["winner_elo"]:
                comeback_highest_elo = comeback_entry
            if comeback_biggest_gap is None or comeback_entry["elo_diff"] > comeback_biggest_gap["elo_diff"]:
                comeback_biggest_gap = comeback_entry

        if longest_match is None or total_turns > longest_match["total_turns"]:
            longest_match = {
                "trainer_a": name_a,
                "trainer_b": name_b,
                "total_turns": total_turns,
                "games_played": games_played,
                "log_reference": f"tournament_results{OUTPUT_SUFFIX}/{safe_filename(name_a)}_vs_{safe_filename(name_b)}_game*.txt",
            }

        if longest_match_by_games is None or games_played > longest_match_by_games["games_played"]:
            longest_match_by_games = {
                "trainer_a": name_a,
                "trainer_b": name_b,
                "total_turns": total_turns,
                "games_played": games_played,
                "score": f"{wins_a}-{wins_b}",
                "log_reference": f"tournament_results{OUTPUT_SUFFIX}/{safe_filename(name_a)}_vs_{safe_filename(name_b)}_game*.txt",
            }

        match_records.append({
            "match_id": match_id,
            "trainer_a_key": t_a, "trainer_b_key": t_b,
            "trainer_a_name": name_a, "trainer_b_name": name_b,
            "score_a": wins_a, "score_b": wins_b,
            "match_winner_key": match_winner,
            "match_winner_name": DISPLAY_NAMES.get(match_winner, match_winner),
            "total_turns": total_turns,
            "seed_base": seed_base,
            "games_played": games_played,
        })

        if elo_snapshot_due(match_id, total_pairs):
            elo_history.append((match_id, [standings[k]["elo"] for k in roster_keys]))

        elapsed = time.time() - start_time
        pct = 100.0 * match_id / total_pairs
        eta = (elapsed / match_id) * (total_pairs - match_id)
        print(f"[Match {match_id}/{total_pairs} ({pct:.1f}%) | elapsed {format_duration(elapsed)}, "
              f"ETA {format_duration(eta)}] "
              f"[{games_played} games, {total_turns} turns total] {name_a} {wins_a}-{wins_b} {name_b} "
              f"==> Match Winner: {DISPLAY_NAMES.get(match_winner, match_winner)}")

    # Tier thresholds can only be built now that every trainer's final Elo
    # is known - see compute_tier_thresholds for why this replaced the old
    # hardcoded-around-1500 table.
    tier_table = compute_tier_thresholds([standings[k]["elo"] for k in roster_keys])

    # Likewise, "greatest win"/"worst loss" can only be resolved now that
    # every trainer's final Elo is settled - see resolve_best_win_worst_loss.
    resolve_best_win_worst_loss(standings)

    standings_text = "--- ROUND ROBIN TOURNAMENT STANDINGS (Tiebreak format) ---\n\n"
    for t, data in sorted(standings.items(), key=lambda x: (x[1]["match_wins"], x[1]["elo"]), reverse=True):
        bw, wl = data["best_win"], data["worst_loss"]
        bw_text = f"{bw['opponent']} (Elo {bw['opponent_elo']})" if bw["opponent"] else "None"
        wl_text = f"{wl['opponent']} (Elo {wl['opponent_elo']})" if wl["opponent"] else "None"
        lm_text = (f"{DISPLAY_NAMES.get(data['longest_match_opponent'], data['longest_match_opponent'])} "
                   f"({data['longest_match_games']} games)") if data["longest_match_opponent"] else "None"
        standings_text += (
            f"Trainer: {DISPLAY_NAMES.get(t, t)}\n"
            f"  Match Record: {data['match_wins']}-{data['match_losses']}\n"
            f"  Game Record: {data['game_wins']}-{data['game_losses']} (W/L ratio: {format_wl_ratio(data['game_wins'], data['game_losses'])})\n"
            f"  Elo Rating: {data['elo']}\n"
            f"  Tier: {get_elo_tier(data['elo'], tier_table)}\n"
            f"  Greatest Win (highest-Elo opponent beaten): {bw_text}\n"
            f"  Worst Loss (lowest-Elo opponent lost to): {wl_text}\n"
            f"  Longest Match vs. (by game count): {lm_text}\n\n"
        )

    # A proper tier list too, since that's the fun part - every trainer
    # grouped under their tier, S+ at the top, F- at the bottom, sorted
    # by Elo within each tier. Tiers nobody landed in are skipped.
    standings_text += "--- TIER LIST ---\n\n"
    by_tier = defaultdict(list)
    for t, data in standings.items():
        by_tier[get_elo_tier(data["elo"], tier_table)].append((DISPLAY_NAMES.get(t, t), data["elo"]))
    for tier_name in TIER_NAMES_DESCENDING:
        members = by_tier.get(tier_name)
        if not members:
            continue
        members.sort(key=lambda m: m[1], reverse=True)
        standings_text += f"{tier_name}: " + ", ".join(f"{name} ({elo})" for name, elo in members) + "\n"

    with open(f"final_standings{OUTPUT_SUFFIX}.txt", "w", encoding="utf-8") as f:
        f.write(standings_text)

    print("\n--- FINAL STANDINGS ---")
    print(standings_text)

    # --- structured data exports ---
    rows = _standings_rows(standings, roster_keys, tier_table, turns_by_trainer)
    export_standings_csv(rows, f"standings{OUTPUT_SUFFIX}.csv")
    export_matches_csv(match_records, f"matches{OUTPUT_SUFFIX}.csv")
    export_elo_history_csv(elo_history, roster_keys, f"elo_history{OUTPUT_SUFFIX}.csv")
    export_individual_analytics_csv(individual_analytics, f"analytics_individuals{OUTPUT_SUFFIX}.csv")
    export_species_analytics_csv(individual_analytics, f"analytics_species{OUTPUT_SUFFIX}.csv")
    export_tournament_analytics_csv(move_ko_counter, knockout_counter, item_activation_counter,
                                    total_games_played, total_turns_all, len(pairs),
                                    f"analytics_tournament{OUTPUT_SUFFIX}.csv")
    summary = build_tournament_summary(rows, knockout_counter, individual_ko_counter, move_ko_counter,
                                        total_games_played, total_turns_all,
                                        biggest_upset, longest_match, longest_match_by_games, longest_battle,
                                        comeback_highest_elo, comeback_biggest_gap, roster_keys, pairs)
    summary["engine_version"] = version_info
    summary["display_names_unique"] = not shared_names
    summary["elo_history_file"] = f"elo_history{OUTPUT_SUFFIX}.csv"
    export_tournament_summary_json(summary, f"tournament_summary{OUTPUT_SUFFIX}.json")
    export_reddit_post(summary, rows, f"reddit_post{OUTPUT_SUFFIX}.md")

    print(f"Saved all match logs to 'tournament_results{OUTPUT_SUFFIX}/', final standings to "
          f"'final_standings{OUTPUT_SUFFIX}.txt', and structured exports to 'standings{OUTPUT_SUFFIX}.csv', "
          f"'matches{OUTPUT_SUFFIX}.csv', 'elo_history{OUTPUT_SUFFIX}.csv', 'analytics_tournament{OUTPUT_SUFFIX}.csv', "
          f"'analytics_species{OUTPUT_SUFFIX}.csv', 'analytics_individuals{OUTPUT_SUFFIX}.csv', "
          f"'tournament_summary{OUTPUT_SUFFIX}.json', and 'reddit_post{OUTPUT_SUFFIX}.md'.")
    print(f"Tournament complete: {total_pairs} matches, {total_games_played} games, "
          f"in {format_duration(time.time() - start_time)}.")


def eligible_roster_keys(include_unused=True, generic_only=False, battle_mode=None):
    """The trainer keys that will actually play: duos merged (or split in forced singles), dummy slots removed, unused trainers
    and non-generic ones left out as asked. Same rules run_tournament applies to the full roster."""
    install_duo_trainers()
    mode = TOURNAMENT_BATTLE_MODE if battle_mode is None else battle_mode
    return [k for k in apply_duo_roster(list(TRAINERS_DB.keys()), mode)
            if not is_dummy_trainer(k) and (include_unused or not is_unused_trainer(k)) and (not generic_only or is_generic_npc(k))]


def prompt_for_test_run():
    """Asks, before anything else runs, whether this should be a small TEST
    tournament (a random subset of the roster, 2-128 trainers) or the full
    ~700+ trainer round robin. Runs interactively via input() - only
    called from the __main__ entry point below, never from run_tournament()
    itself, so calling run_tournament() programmatically never blocks on
    a prompt."""
    answer = input("Run a TEST tournament with a limited trainer subset instead of the full roster? (y/n): ").strip().lower()
    if answer not in ("y", "yes"):
        return None

    while True:
        raw = input("How many trainers should the test tournament include? (2-128): ").strip()
        try:
            n = int(raw)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if 2 <= n <= 128:
            return n
        print("Please enter a number between 2 and 128.")


def prompt_for_unused_trainers():
    """Asked every time, whether this is a test run or the full
    tournament (see is_unused_trainer for what "unused" means here -
    it's complete, valid trainer data that just never comes up in the
    shipped game, not placeholder junk like Dummy trainers, so it's
    worth asking about explicitly rather than silently deciding either
    way). Returns True to include them, False to leave them out."""
    answer = input("Include 'unused' trainers (valid data, but never encountered in the shipped game) "
                    "in the tournament? (y/n): ").strip().lower()
    return answer in ("y", "yes")


def prompt_for_generic_only():
    """Asked every time, alongside the unused-trainers prompt. See is_generic_npc for exactly who is left out: bosses (Gym
    Leaders, Elite Four, Champions, Rivals, Battleground, Red), story characters, Frontier Brains and every evil-team member
    (Commanders, Grunts, Executives, Cyrus, Giovanni). Returns True for a "Generic NPCs only" roster, False to include everyone."""
    answer = input("Generic NPCs only? Leaves out bosses (Gym Leaders, Elite Four, Champions, Rivals, Battleground, Red), "
                    "story characters, Frontier Brains and all evil-team members (Commanders, Grunts, Executives...) (y/n): ").strip().lower()
    return answer in ("y", "yes")


def prompt_for_set_level():
    """Asks whether every Pokemon in the tournament should battle at one
    fixed level instead of its own in-game level - e.g. "what if every
    trainer's team was level 50?" Returns None (no override, the
    default/original behavior), 50, or 100."""
    while True:
        answer = input("Use a set level for every Pokemon in the tournament? (50/100/n): ").strip().lower()
        if answer in ("n", "no", ""):
            return None
        if answer == "50":
            return 50
        if answer == "100":
            return 100
        print("Please answer 50, 100, or n.")


def prompt_for_moveset_level_source():
    """Only asked when prompt_for_set_level() returned 50 or 100. Some
    trainer parties have "moves": null (e.g. Roman's level-26 Lickitung),
    meaning the game derives that Pokemon's moveset from its own level-up
    learnset rather than an explicit moveset - see moves_from_learnset.
    This is independent of the set-level override itself: a Pokemon can
    battle with level-50 stats while still only knowing the moves it
    would canonically have by its ORIGINAL level, or its moveset can be
    scaled up to match the set level too. Returns "original" or "set"."""
    while True:
        answer = input(
            "For trainers whose moveset comes from level-up (moves: null in the data), use their "
            "ORIGINAL level's moves, or the SET level's moves? (original/set): "
        ).strip().lower()
        if answer in ("original", "orig", "o"):
            return "original"
        if answer in ("set", "s"):
            return "set"
        print("Please answer 'original' or 'set'.")


def prompt_for_battle_mode():
    """Asks whether the whole tournament is forced to one battle format,
    or follows each matchup's own data - see determine_battle_format for
    exactly how the "normal" default decides singles vs doubles per
    matchup (a genuine mix, both landing in the same unsuffixed output).
    Forcing "singles" or "doubles" applies that format to every matchup
    in the tournament (except that a trainer with only one Pokemon can
    never field two, so it still battles 1-on-1 regardless - see
    determine_battle_format's own docstring). Returns "normal", "singles",
    or "doubles"."""
    while True:
        answer = input(
            "Battle format for the tournament - force everything to singles, force everything to "
            "doubles, or normal (each matchup follows the trainer data, a mix of both)? "
            "(singles/doubles/normal): "
        ).strip().lower()
        if answer in ("normal", "n", ""):
            return "normal"
        if answer in ("singles", "s"):
            return "singles"
        if answer in ("doubles", "d"):
            return "doubles"
        print("Please answer singles, doubles, or normal.")


def prompt_for_trainer_items():
    """Asks whether trainers may use the items in their data (Full Restore, potions, Full Heal, X items...) during battle.
    Returns True (enabled, the real games' behavior and the default) or False (nobody uses items). Only singles battles
    use items at all - see ai_should_use_item."""
    while True:
        answer = input("Allow trainers to use their items (Full Restore, Potions, Full Heal, X items) in battle? "
                       "(yes/no, default yes): ").strip().lower()
        if answer in ("y", "yes", "on", "enable", "enabled", ""):
            return True
        if answer in ("n", "no", "off", "disable", "disabled"):
            return False
        print("Please answer yes or no.")


def prompt_for_game_selection():
    """Asks which game's trainer roster to run the tournament against -
    Platinum's (the original, one-file-per-trainer data), HeartGold/
    SoulSilver's (one combined trainers.json - see
    load_hgss_trainers_from_repo for the format differences), or both
    combined into a single roster. Returns "platinum", "hgss", or
    "combined"."""
    while True:
        answer = input(
            "Which game's trainers should this tournament use - Platinum, HeartGold/SoulSilver, "
            "or both combined? (platinum/hgss/combined): "
        ).strip().lower()
        if answer in ("platinum", "plat", "p", ""):
            return "platinum"
        if answer in ("hgss", "heartgold", "soulsilver", "h"):
            return "hgss"
        if answer in ("combined", "combine", "both", "c"):
            return "combined"
        print("Please answer platinum, hgss, or combined.")


if __name__ == "__main__":
    game_mode = prompt_for_game_selection()

    SET_LEVEL = prompt_for_set_level()
    if SET_LEVEL is not None:
        MOVESET_LEVEL_SOURCE = prompt_for_moveset_level_source()

    TOURNAMENT_BATTLE_MODE = prompt_for_battle_mode()
    TRAINER_ITEMS_ENABLED = prompt_for_trainer_items()
    generic_only = prompt_for_generic_only()

    # Both settings contribute their own suffix piece independently, so a
    # forced-doubles run at set level 50 gets "_50_doubles", a plain
    # forced-doubles run at each Pokemon's own level gets "_doubles", and
    # so on - "normal" battle mode contributes nothing, since a genuine
    # mix of singles and doubles results belongs in the same folder as
    # any other unsuffixed run. The game choice contributes its own
    # piece the same way - Platinum alone (the original default) stays
    # unsuffixed for backward compatibility with existing output files.
    OUTPUT_SUFFIX = (f"_{SET_LEVEL}" if SET_LEVEL is not None else "") + \
                    (f"_{TOURNAMENT_BATTLE_MODE}" if TOURNAMENT_BATTLE_MODE != "normal" else "") + \
                    (f"_{game_mode}" if game_mode != "platinum" else "") + \
                    ("_generic" if generic_only else "") +                     ("" if TRAINER_ITEMS_ENABLED else "_noitems")

    # The roster was already built once at module-import time using
    # Platinum's own loader and default (no override) settings - always
    # rebuild now that the game choice and/or SET_LEVEL/
    # MOVESET_LEVEL_SOURCE reflect what was actually asked for, since
    # _build_party_mon reads them at construction time.
    if game_mode == "platinum":
        print("Loading Platinum's trainer roster...")
        TRAINERS_DB, DISPLAY_NAMES = load_trainers_from_repo()
    elif game_mode == "hgss":
        print("Loading HeartGold/SoulSilver's trainer roster...")
        TRAINERS_DB, DISPLAY_NAMES = load_hgss_trainers_from_repo()
    else:
        print("Loading and combining both games' trainer rosters...")
        # HGSS keys are prefixed (see load_combined_roster) and display names the two games share get a game tag.
        TRAINERS_DB, DISPLAY_NAMES = load_combined_roster()
        n_hgss = sum(1 for k in TRAINERS_DB if k.startswith("hgss_"))
        print(f"Combined roster: {len(TRAINERS_DB) - n_hgss} Platinum + {n_hgss} HGSS = {len(TRAINERS_DB)} total trainers.")

    include_unused = prompt_for_unused_trainers()
    eligible = eligible_roster_keys(include_unused, generic_only)
    n_duos = sum(1 for k in eligible if TRAINERS_DB[k].get("members"))
    notes = [f"{n_duos} two-trainer fight(s) merged into one" if n_duos else None,
             "dummy slots removed", None if include_unused else "unused trainers left out", "generic NPCs only" if generic_only else None]
    print(f"Trainers in this tournament: {len(eligible)} of the {len(TRAINERS_DB) - sum(1 for t in TRAINERS_DB.values() if t.get('members'))} loaded "
          f"({', '.join(n for n in notes if n)}).")
    test_size = prompt_for_test_run()

    if test_size is None:
        run_tournament(exclude_unused=not include_unused, generic_only=generic_only)
    else:
        # Sample from the already-Dummy-filtered (and, if requested,
        # Unused-filtered and/or Boss-filtered) roster so the requested
        # count is a literal count of trainers that will actually be in
        # the tournament, not inflated/deflated by slots run_tournament
        # would exclude anyway.
        sample_size = min(test_size, len(eligible))
        if sample_size < test_size:
            print(f"Only {sample_size} eligible trainers are loaded - running with all of them.")
        sample = random.sample(eligible, sample_size)
        print(f"Running a TEST tournament with {sample_size} randomly selected trainers...")
        run_tournament(target_names=sample, exclude_unused=not include_unused, generic_only=generic_only)
