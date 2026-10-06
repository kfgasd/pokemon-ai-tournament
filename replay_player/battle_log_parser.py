# -*- coding: utf-8 -*-
"""Turns one engine battle log (the .txt files in tournament_results*/) into a replay: both teams plus a flat list of
events that carry ABSOLUTE state (hp after the event, who is on the field), so a player can render or scrub to any
event without re-simulating anything.

Why parse text instead of re-running the engine: the logs already exist for every match ever played (hundreds of
thousands of them) and are what the Streamlit app shows today. The text carries almost everything a player needs; the
few HP changes it does not annotate (Leftovers, Recover, ...) are reconciled against the "(HP: x/y)" turn headers, which
are exact. Anything unexplained is recorded in replay["diag"] instead of being hidden, so the parser's accuracy is
measurable (see validate_parser.py).

Event kinds (every event also has i = 0-based source line, n = turn number):
  start   {text}
  turn    {n}
  sync    {act: {a: [idx|None, ...], b: [...]}, hp: [[side, idx, hp, max], ...]}   exact state from a turn header
  send    {side, slot, idx, why: lead|replace|switch|drag|baton|pivot, from: idx|None, text}
  move    {side, slot, idx, move, type?, cls?, text}      type / cls (physical|special|status) come from move_types.json
  hp      {side, slot, idx, hp, max, d, cause, amt?, crit?, eff?, hits?, text}      d = signed change actually applied
  miss    {side, slot, idx, text}      (the mon that dodged)
  status  {side, slot, idx, st: par|psn|tox|brn|slp|frz|None, text}
  vol     {side, slot, idx, flag, on, text}      volatile condition (cnf, seed, ...)
  stat    {side, slot, idx, stat, dir, text}      dir = +1 / -1 (the log does not say how many stages)
  faint   {side, slot, idx, text}
  vanish  {side, slot, idx, on, text}            two-turn moves (Fly, Dig, Dive, Bounce)
  transform {side, slot, idx, to, text}
  field   {what, val, side?, text}               weather / trickroom / gravity / reflect / lightscreen / ...
  msg     {text}
  end     {winner: a|b|None, text}
"""
import collections
import json
import os
import re
import sys

STATUS_BY_NAME = {
    "PARALYSIS": "par", "PARALYZE": "par", "PARALYZED": "par", "POISON": "psn", "POISONED": "psn",
    "TOXIC": "tox", "BADLY POISONED": "tox", "BURN": "brn", "BURNED": "brn", "SLEEP": "slp", "FREEZE": "frz",
    "FROZEN": "frz",
}
WEATHER_BY_NAME = {"SUN": "sun", "RAIN": "rain", "SANDSTORM": "sand", "HAIL": "hail"}
STAT_NAMES = {"ATK": "Attack", "DEF": "Defense", "SPA": "Sp. Atk", "SPD": "Sp. Def", "SPE": "Speed",
              "ACC": "Accuracy", "EVA": "Evasion"}
SPECIAL_DISPLAY = {"MR MIME": "Mr. Mime", "MIME JR": "Mime Jr.", "PORYGON Z": "Porygon-Z", "HO OH": "Ho-Oh",
                   "NIDORAN F": "Nidoran♀", "NIDORAN M": "Nidoran♂", "FARFETCHD": "Farfetch'd"}


def _load_move_types():
    """move name (lower-case letters/digits only) -> [type, class] from move_types.json (made from the engine's moves_db.json)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "move_types.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


MOVE_TYPES = _load_move_types()


def display_species(sp):
    return SPECIAL_DISPLAY.get(sp, sp.title())


TEAM_RE = re.compile(r"^(.+?)'s team:$")
ROSTER_RE = re.compile(r"^  Lv\. (\d+) (.+?) \((.+?)\)(?: @ (.+?))?: (.+)$")
GAME_RE = re.compile(r"^=== GAME (\d+): (.+)$")
TURN_RE = re.compile(r"^--- Turn (\d+) ---$")
MON_IN_SIDE_RE = re.compile(r"Lv\. (\d+) (.+?) \(HP: (\d+)/(\d+)\)")
MOVE_RE = re.compile(r"^  > (.+?) uses (.+?)!$")
FAINT_RE = re.compile(r"^  X (.+?) fainted!$")
SENDOUT_RE = re.compile(r"^  -> (.+?) sends out (.+?)!$")
WITHDRAW_RE = re.compile(r"^  (.+?) withdraws (.+?) and sends out (.+?)!$")

# --- 4-space message rules, tried in order against the stripped text -----------------------------------------------
R = re.compile
RULES = [
    (R(r"^Dealt (\d+) damage(?: to (.+?))?!(.*)$"), "dealt"),
    (R(r"^Hit (\d+) times?! Dealt (\d+) damage total(?: to (.+?))?!(.*)$"), "multi"),
    (R(r"^(.+?) unleashed its energy! Dealt (\d+) damage(?: to (.+?))?!$"), "bide"),
    (R(r"^(?:.+? unleashed its energy! )?The Substitute took (\d+) damage!$"), "msg_sub"),
    (R(r"^(.+?)'s Substitute took (\d+) damage!$"), "msg_sub2"),
    (R(r"^Attack missed!$"), "miss_plain"),
    (R(r"^Attack on (.+?) missed!$"), "miss_target"),
    (R(r"^(.+?) is confused! It hurt itself in its confusion! \(-(\d+) HP\)$"), "confusion_hit"),
    (R(r"^(.+?)'s HP was cut down to match (.+?)'s! \(-(\d+) HP\)$"), "endeavor"),
    (R(r"^(.+?)'s health is sapped by Leech Seed! \(-(\d+) HP\)$"), "leech"),
    (R(r"^(.+?) is hurt by poison! \(-(\d+) HP\)$"), "poison_tick"),
    (R(r"^(.+?) is hurt by its burn! \(-(\d+) HP\)$"), "burn_tick"),
    (R(r"^(.+?) is buffeted by the sandstorm! \(-(\d+) HP\)$"), "sand_tick"),
    (R(r"^(.+?) is pelted by hail! \(-(\d+) HP\)$"), "hail_tick"),
    (R(r"^(.+?) was hurt by recoil! \(-(\d+) HP\)$"), "recoil"),
    (R(r"^(.+?) kept going and crashed! \(-(\d+) HP\)$"), "crash"),
    (R(r"^(.+?) is hurt by (.+?)'s binding move! \(-(\d+) HP\)$"), "bind_tick"),
    (R(r"^(.+?) is afflicted by the curse! \(-(\d+) HP\)$"), "curse_tick"),
    (R(r"^(.+?) is tormented by a nightmare! \(-(\d+) HP\)$"), "nightmare_tick"),
    (R(r"^(.+?)(?: is| was|'s| kept)\b.*\(-(\d+) HP\)!?$"), "generic_loss"),
    (R(r"^(.+?)'s wish came true! \(\+(\d+) HP\)$"), "wish"),
    (R(r"^(.+?)(?: was|'s)\b.*\(\+(\d+) HP\)!?$"), "heal_ann"),
    (R(r"^(.+?) drained (\d+) HP!$"), "drain"),
    (R(r"^(.+?) recovered (\d+) HP!$"), "recovered"),
    (R(r"^(.+?) restored a little HP using its (Leftovers|Black Sludge)!$"), "leftovers"),
    (R(r"^(.+?) went to sleep and restored its HP!$"), "rest"),
    (R(r"^(.+?) swallowed its stockpiled energy and recovered HP!$"), "swallow"),
    (R(r"^(.+?)'s (.+?) restored its HP!$"), "ability_heal"),
    (R(r"^(.+?) restored its HP!$"), "recover"),
    (R(r"^(.+?) cut its own HP and maximized its Attack!$"), "belly_drum"),
    (R(r"^(.+?) cut its own HP and laid a curse on (.+?)!$"), "curse_cast"),
    (R(r"^(.+?) put up a Substitute!$"), "substitute"),
    (R(r"^(.+?) exploded!$"), "self_ko"),
    (R(r"^(.+?) cut its own HP to hurt the opposing Pokemon!$"), "self_ko"),
    (R(r"^(.+?) fainted so its replacement can be healed!$"), "self_ko"),
    (R(r"^(.+?)'s perish count hit zero!$"), "perish_zero"),
    (R(r"^(.+?) was hurt by (.+?)'s Aftermath!$"), "aftermath"),
    (R(r"^(.+?) sucked up the liquid ooze!$"), "liquid_ooze"),
    (R(r"^(.+?) shared its pain with (.+?)!$"), "pain_split"),
    (R(r"^(.+?) transformed into (?!the .+ type!$)(.+?)!$"), "transform"),
    (R(r"^(.+?) was afflicted with ([A-Z ]+)!$"), "afflicted"),
    (R(r"^(.+?) was (?:badly )?(poisoned|burned) by its (Toxic|Flame) Orb!$"), "orb_status"),
    (R(r"^(.+?) was (paralyzed|burned|poisoned) by (Static|Flame Body|Poison Point)!$"), "contact_status"),
    (R(r"^(.+?) was afflicted with ([A-Z ]+) by Effect Spore!$"), "afflicted"),
    (R(r"^(.+?) fell asleep from drowsiness!$"), "drowsy_sleep"),
    (R(r"^(.+?) is fast asleep\.$"), "ev_sleep"),
    (R(r"^(.+?) is paralyzed! It can't move!$"), "ev_par"),
    (R(r"^(.+?) is frozen solid!$"), "ev_frz"),
    (R(r"^(.+?) woke up!$"), "cure_slp"),
    (R(r"^(.+?) thawed out!$"), "cure_frz"),
    (R(r"^(.+?) was defrosted by .+?!$"), "cure_frz"),
    (R(r"^(.+?)'s (?:Shed Skin cured its|Natural Cure healed its) .+?!$"), "cure_any"),
    (R(r"^(.+?)'s .+? cured its status!$"), "cure_any"),
    (R(r"^(.+?)'s status (?:was cured|returned to normal)!$"), "cure_any"),
    (R(r"^A (?:bell chimed|soothing aroma wafted through the area)!$"), "party_cure"),
    (R(r"^(.+?) became confused(?: due to fatigue)?!$"), "confused"),
    (R(r"^(.+?) is confused!$"), "ev_confused"),
    (R(r"^(.+?) snapped out of confusion!$"), "unconfused"),
    (R(r"^(.+?) fell in love(?: with .+?)?(?: \(Cute Charm\))?!$"), "love"),
    (R(r"^(.+?) was seeded!$"), "seeded"),
    (R(r"^(.+?)'s (ATK|DEF|SPA|SPD|SPE|ACC|EVA) (rose|fell)!$"), "stat"),
    (R(r"^(.+?)'s (ATK|DEF|SPA|SPD|SPE|ACC|EVA) fell from Intimidate!$"), "stat_fell_intimidate"),
    (R(r"^(.+?)'s Intimidate lowered (.+?)'s ATK!$"), "intimidate"),
    (R(r"^(.+?)'s Download raised its (Attack|Special Attack)!$"), "download"),
    (R(r"^(.+?)'s Steadfast raised its Speed!$"), "steadfast"),
    (R(r"^(.+?)'s Anger Point maxed its Attack!$"), "anger_point"),
    (R(r"^(.+?)'s stats all rose!$"), "all_stats_up"),
    (R(r"^All stat changes were eliminated!$"), "haze"),
    (R(r"^(.+?) flew up high!$"), "vanish_on"),
    (R(r"^(.+?) burrowed underground!$"), "vanish_on"),
    (R(r"^(.+?) hid underwater!$"), "vanish_on"),
    (R(r"^(.+?) sprang up!$"), "vanish_on"),
    (R(r"^The weather became ([A-Z]+)!$"), "weather_set"),
    (R(r"^(.+?)'s (Drought|Drizzle|Sand Stream|Snow Warning) - .*$"), "weather_ability"),
    (R(r"^The sunlight faded!$"), "weather_end"),
    (R(r"^The rain stopped!$"), "weather_end"),
    (R(r"^The sandstorm subsided!$"), "weather_end"),
    (R(r"^The hail stopped!$"), "weather_end"),
    (R(r"^(.+?)'s side gained a (Reflect|Light Screen) barrier!$"), "screen_on"),
    (R(r"^(.+?) became cloaked in a mystical veil!$"), "safeguard_on"),
    (R(r"^A tailwind blew behind (.+?)'s side!$"), "tailwind_on"),
    (R(r"^(.+?)'s side became shrouded in mist!$"), "mist_on"),
    (R(r"^(.+?)'s side is shielded by the Lucky Chant!$"), "luckychant_on"),
    (R(r"^(.+?)'s team is no longer protected by Mist!$"), "mist_off"),
    (R(r"^(.+?)'s Lucky Chant wore off!$"), "luckychant_off"),
    (R(r"^(.+?) twisted the dimensions!$"), "trickroom_on"),
    (R(r"^The twisted dimensions returned to normal!$"), "trickroom_off"),
    (R(r"^Gravity intensified!$"), "gravity_on"),
    (R(r"^Gravity returned to normal!$"), "gravity_off"),
    (R(r"^(.+?)'s (.+?) called (.+?)!$"), "called"),
    (R(r"^(.+?)'s (Future Sight|Doom Desire) struck (.+?)!$"), "delayed_strike"),
    (R(r"^(.+?) foresaw an attack with (.+?)!$"), "delayed_setup"),
    (R(r"^(.+?) consumed/used its (.+?)!$"), "consumed"),
    (R(r"^(.+?) learned (.+?)!$"), "msg_generic"),
]

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class ReplayParser:
    def __init__(self, text, source=None):
        self.source = source
        self.lines = text.replace("\r\n", "\n").split("\n")
        self.ev = []
        self.diag = collections.Counter()
        self.unexplained = []          # [(turn, side, species, predicted hp, actual hp, last event texts, tag)]
        self.unclassified = collections.Counter()
        self.names = {"a": None, "b": None}
        self.double = False
        self.game = None
        self.turn = 0
        self.party = {"a": [], "b": []}
        self.act = {"a": [], "b": []}
        self.max_table = {}
        self.hdr = {"a": [], "b": []}      # side -> [(line index, [(lv, species, hp, max), ...])] for every turn header
        self.actor = None              # (side, slot, idx) of the mon whose "uses" line we are inside
        self.delayed_target = None     # (side, slot, idx) while inside a Future Sight / Doom Desire resolution
        self.last_dealt = 0
        self.winner = None
        self.ended = False
        self.field = {"weather": None}
        self._pending_sync = {}
        self.timers = []               # silent expiries: {what, side, until}  (active through turn `until`)
        self._serial = 0
        self.amb = []                  # hp events whose target was ambiguous (same species twice on one side)
        self.acted = set()             # (side, idx) that already used a move this turn
        self.ticked = set()            # (side, idx, cause): end-of-turn effects already applied this turn (mirror matches)
        self.amb_faints = []           # faint events whose mon (one of two twins) is only known after the next header
        self.seg_start_ev = 0          # index into self.ev where the current header-to-header segment began
        self.seg_act0 = {"a": [], "b": []}

    # ------------------------------------------------------------------ setup
    def parse(self):
        start = self._read_teams()
        self._prescan_headers()
        self._init_state()
        for i in range(start, len(self.lines)):
            try:
                self._line(i, self.lines[i].rstrip())
            except Exception as exc:    # a parser bug must never lose the whole replay
                self.diag["errors"] += 1
                self.diag["error:" + type(exc).__name__ + ":" + str(exc)[:60]] += 1
        self._finalize()
        return self.replay()

    def _read_teams(self):
        """Reads the header + both roster blocks. Returns the index of the first line after the last roster row (the
        pre-battle ability messages, if any, and then "--- Turn 1 ---" follow)."""
        side = None
        count = 0
        last = 0
        for i, raw in enumerate(self.lines):
            line = raw.rstrip()
            if TURN_RE.match(line):
                break
            m = GAME_RE.match(line)
            if m and self.game is None:
                self.game = int(m.group(1))
                self.double = "(DOUBLE BATTLE)" in line
                continue
            m = TEAM_RE.match(line)
            if m and count < 2:
                count += 1
                side = "a" if count == 1 else "b"
                self.names[side] = m.group(1)
                continue
            m = ROSTER_RE.match(line)
            if m and side:
                lv, sp, ab, item, moves = m.groups()
                self.party[side].append({
                    "sp": sp, "lv": int(lv), "ab": ab, "item": item, "moves": [x.strip() for x in moves.split("/")],
                    "max": None, "hp": None, "st": None, "f": False, "disp": sp, "vol": set(), "seg": [],
                    "hidden": False,
                })
                last = i + 1
        return last

    def _prescan_headers(self):
        """Max HP per (side, species, level), straight from every turn header - exact, so a pass can fill max HP up front."""
        a, b = self.names["a"], self.names["b"]
        if not a or not b:
            return
        if self.double:
            side_a = a + "'s side: "
            side_b = b + "'s side: "
            for li, raw in enumerate(self.lines):
                for side, prefix in (("a", side_a), ("b", side_b)):
                    if raw.startswith(prefix):
                        found = MON_IN_SIDE_RE.findall(raw[len(prefix):])
                        self.hdr[side].append((li, [(int(lv), sp, int(hp), int(mx)) for lv, sp, hp, mx in found]))
                        for lv, sp, hp, mx in found:
                            self.max_table.setdefault((side, sp, int(lv)), set()).add(int(mx))
        else:
            pat = re.compile(r"^" + re.escape(a) + r"'s Lv\. (\d+) (.+?) \(HP: (\d+)/(\d+)\) vs " + re.escape(b)
                             + r"'s Lv\. (\d+) (.+?) \(HP: (\d+)/(\d+)\)$")
            for li, raw in enumerate(self.lines):
                if "(HP: " in raw and " vs " in raw:
                    m = pat.match(raw.rstrip())
                    if m:
                        self.hdr["a"].append((li, [(int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)))]))
                        self.hdr["b"].append((li, [(int(m.group(5)), m.group(6), int(m.group(7)), int(m.group(8)))]))
                        self.max_table.setdefault(("a", m.group(2), int(m.group(1))), set()).add(int(m.group(4)))
                        self.max_table.setdefault(("b", m.group(6), int(m.group(5))), set()).add(int(m.group(8)))

    def _init_state(self):
        for side in "ab":
            for idx, mon in enumerate(self.party[side]):
                vals = self.max_table.get((side, mon["sp"], mon["lv"]))
                same = [m2 for m2 in self.party[side] if m2["sp"] == mon["sp"] and m2["lv"] == mon["lv"]]
                # twins with different max hp (different IVs) can't be told apart until a header shows which is which
                mx = next(iter(vals)) if vals and (len(vals) == 1 or len(same) == 1) else None
                mon["max"] = mx
                mon["hp"] = mx
                mon["seg_hp0"] = mx
                mon["idx"] = idx
                mon["side"] = side
            n = 2 if self.double else 1
            self.act[side] = [i if i < len(self.party[side]) else None for i in range(n)]
        self.seg_act0 = {sd: list(self.act[sd]) for sd in "ab"}
        self._emit("start", 0, text=f"{self.names['a']} vs {self.names['b']}")
        for side in "ab":
            for slot, idx in enumerate(self.act[side]):
                if idx is not None:
                    mon = self.party[side][idx]
                    self._emit("send", 0, side=side, slot=slot, idx=idx, why="lead", **{"from": None},
                               text=f"{self.names[side]} sent out {display_species(mon['disp'])}!")

    # ------------------------------------------------------------------ helpers
    def _emit(self, kind, i, **kw):
        e = {"k": kind, "i": i, "n": self.turn, "_s": self._serial}
        self._serial += 1
        e.update(kw)
        self.ev.append(e)
        return e

    def _split_owner(self, text):
        """'Name's REST' -> (side, REST) using the two known trainer names (longest first - one can prefix the other)."""
        for side in sorted("ab", key=lambda s: -len(self.names[s] or "")):
            name = self.names[side]
            if name and text.startswith(name + "'s "):
                return side, text[len(name) + 3:]
        return None, text

    def _find_active(self, species, prefer=None, only=None):
        """-> (side, slot, idx) of an ACTIVE mon currently displayed as `species`."""
        found = []
        for side in "ab":
            if only and side != only:
                continue
            for slot, idx in enumerate(self.act[side]):
                if idx is not None and self.party[side][idx]["disp"] == species:
                    found.append((side, slot, idx))
        if not found:
            return None
        if len(found) > 1 and prefer:
            pref = [f for f in found if f[0] == prefer]
            if pref:
                return pref[0]
        return found[0]

    def _find_any(self, species, prefer=None):
        ref = self._find_active(species, prefer)
        if ref:
            return ref
        for side in ("a", "b") if prefer != "b" else ("b", "a"):
            for idx, mon in enumerate(self.party[side]):
                if mon["disp"] == species and not mon["f"]:
                    return (side, None, idx)
        return None

    @staticmethod
    def _opp(side):
        return "b" if side == "a" else "a"

    def _actor_side(self):
        return self.actor[0] if self.actor else None

    def _resolve(self, species, role):
        """role: 'self' (message is about the acting mon), 'foe' (about its target), None (no preference)."""
        asd = self._actor_side()
        if role == "self" and asd:
            return self._find_active(species, prefer=asd)
        if role == "foe" and asd:
            return self._find_active(species, prefer=self._opp(asd))
        return self._find_active(species)

    # --- hp bookkeeping
    def _resolve_ctx(self, species, role, cause=None, filt=None):
        """Like _resolve, but for lines that can hit any mon showing `species` (end-of-turn effects, confusion ...): a state
        filter (e.g. "is poisoned") narrows the candidates, and effects that every mon suffers once a turn are dealt out
        to a mon that has not had it yet (a mirror match has the same species on both sides)."""
        cands = [(sd, sl, c) for sd in "ab" for sl, c in enumerate(self.act[sd])
                 if c is not None and self.party[sd][c]["disp"] == species]
        if not cands:
            return None
        if filt:
            f = [c for c in cands if filt(self.party[c[0]][c[2]])]
            if f:
                cands = f
        if len(cands) > 1 and cause:
            fresh = [c for c in cands if (c[0], c[2], cause) not in self.ticked]
            if fresh:
                cands = fresh
        if len(cands) > 1:
            asd = self._actor_side()
            if asd and role in ("self", "foe"):
                want = asd if role == "self" else self._opp(asd)
                pref = [c for c in cands if c[0] == want]
                if pref:
                    cands = pref
        ref = cands[0]
        if cause:
            self.ticked.add((ref[0], ref[2], cause))
        return ref

    def _same_species_active(self, side, idx):
        sp = self.party[side][idx]["disp"]
        return [c for c in self.act[side] if c is not None and self.party[side][c]["disp"] == sp]

    def _hp_change(self, i, ref, delta=None, set_to=None, cause="", uncertain=False, certain=False, filt=None, **extra):
        """Applies an HP change to the tracked mon and emits an hp event. Returns the event (or None if ref is None).
        When the same species is on the field twice on that side the log cannot say which one it was: the event is
        attributed provisionally and registered in self.amb; the next turn header settles it (see _solve_ambiguity)."""
        if ref is None:
            return None
        side, slot, idx = ref
        amb = None
        cands = self._same_species_active(side, idx) if idx in self.act[side] else [idx]
        if len(cands) > 1 and not certain:
            if filt:
                narrowed = [c for c in cands if filt(self.party[side][c])]
                if narrowed:
                    cands = narrowed
            if len(cands) == 1:
                idx = cands[0]
                slot = self.act[side].index(idx)
            else:
                amb = cands
                idx = cands[0]
                slot = self.act[side].index(idx)
        mon = self.party[side][idx]
        mx = mon["max"]
        old = mon["hp"]
        if mx is None or old is None:
            new = None
            applied = delta
        else:
            new = set_to if set_to is not None else old + delta
            new = _clamp(new, 0, mx)
            applied = new - old
        mon["hp"] = new
        e = self._emit("hp", i, side=side, slot=slot, idx=idx, hp=new, max=mx, d=applied, cause=cause, **extra)
        e["_raw"] = ("set", set_to) if set_to is not None else ("d", delta)
        if uncertain:
            e["_u"] = True
        if amb:
            e["_amb"] = amb
            self.amb.append(e)
        mon["seg"].append(e)
        return e

    def _heal_frac(self, ref, denom):
        side, slot, idx = ref
        mx = self.party[side][idx]["max"]
        return max(1, mx // denom) if mx else 0

    def _set_status(self, i, ref, st, text=None):
        if ref is None:
            return
        side, slot, idx = ref
        mon = self.party[side][idx]
        if mon["st"] == st:
            return
        mon["st"] = st
        self._emit("status", i, side=side, slot=slot, idx=idx, st=st, text=text)

    def _set_vol(self, i, ref, flag, on, text=None):
        if ref is None:
            return
        side, slot, idx = ref
        mon = self.party[side][idx]
        if on and flag in mon["vol"]:
            return
        if not on and flag not in mon["vol"]:
            return
        (mon["vol"].add if on else mon["vol"].discard)(flag)
        self._emit("vol", i, side=side, slot=slot, idx=idx, flag=flag, on=on, text=text)

    def _clear_switch_state(self, mon):
        mon["vol"] = set()
        mon["disp"] = mon["sp"]
        mon["hidden"] = False

    # ------------------------------------------------------------------ dispatch
    def _line(self, i, s):
        if not s.strip():
            return
        if self.ended:
            return
        if s.startswith("=== "):
            return self._banner(i, s)
        m = TURN_RE.match(s)
        if m:
            new_turn = int(m.group(1))
            keep = []
            for tm in self.timers:
                if new_turn > tm["until"]:
                    label = {"reflect": "Reflect", "lightscreen": "Light Screen", "tailwind": "The tailwind",
                             "safeguard": "Safeguard"}[tm["what"]]
                    self._emit("field", i, what=tm["what"], side=tm["side"], val=False, synthetic=True,
                               text=f"{self.names[tm['side']]}'s {label} wore off!" if tm["what"] != "tailwind" else "The tailwind petered out!")
                else:
                    keep.append(tm)
            self.timers = keep
            self.turn = new_turn
            self.actor = None
            self.acted = set()
            self.ticked = set()
            self.delayed_target = None
            self._emit("turn", i, n=self.turn)
            return
        if s.startswith("  > "):
            return self._move_line(i, s)
        if s.startswith("  X "):
            return self._faint_line(i, s)
        if s.startswith("  -> "):
            return self._sendout_line(i, s)
        if s.startswith("  ") and not s.startswith("    ") and " withdraws " in s:
            m = WITHDRAW_RE.match(s)
            if m:
                return self._voluntary_switch(i, m)
        if not s.startswith(" "):
            if self._header_line(i, s):
                return
        if s.startswith("    "):
            return self._msg_line(i, s.strip())
        self._emit("msg", i, text=s.strip())

    # ------------------------------------------------------------------ headers / sync
    def _header_line(self, i, s):
        a, b = self.names["a"], self.names["b"]
        if self.double:
            for side in "ab":
                prefix = self.names[side] + "'s side: "
                if s.startswith(prefix):
                    entries = [(int(lv), sp, int(hp), int(mx)) for lv, sp, hp, mx in MON_IN_SIDE_RE.findall(s[len(prefix):])]
                    self._pending_sync[side] = entries
                    if len(self._pending_sync) == 2:
                        self._do_sync(i, self._pending_sync)
                        self._pending_sync = {}
                    return True
            return False
        if "(HP: " in s and " vs " in s and s.startswith(a + "'s Lv. "):
            m = re.match(r"^" + re.escape(a) + r"'s Lv\. (\d+) (.+?) \(HP: (\d+)/(\d+)\) vs " + re.escape(b)
                         + r"'s Lv\. (\d+) (.+?) \(HP: (\d+)/(\d+)\)$", s)
            if m:
                self._do_sync(i, {"a": [(int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)))],
                                  "b": [(int(m.group(5)), m.group(6), int(m.group(7)), int(m.group(8)))]})
                return True
        return False

    def _do_sync(self, i, entries_by_side):
        """Exact state from a turn header: who is on the field (and in which slot), and each one's hp / max hp."""
        self._solve_ambiguity(entries_by_side)
        synced = []
        for side in "ab":
            entries = entries_by_side.get(side, [])
            party = self.party[side]
            n = len(self.act[side])
            new_act = [None] * n
            used = set()
            bound = []                                   # (idx, slot-it-already-held or None, hp, max)
            for (lv, sp, hp, mx) in entries:
                best = None
                for ai, mon in enumerate(party):
                    if ai in used or mon["disp"] != sp:
                        continue
                    if mon["lv"] != lv:
                        score = 0
                    elif mon["max"] is None:
                        score = 3
                    elif mon["max"] == mx:
                        score = 4
                    else:
                        score = 1
                    if mon["f"]:
                        score -= 2
                    held = ai in self.act[side]
                    key = (score, 1 if held else 0, -(self.act[side].index(ai) if held else ai))
                    if best is None or key > best[0]:
                        best = (key, ai, held)
                if best is None:
                    self.diag["sync_unbound"] += 1
                    continue
                idx = best[1]
                keep = self.act[side].index(idx) if best[2] else None
                used.add(idx)
                bound.append((idx, keep, hp, mx))
            for idx, keep, hp, mx in bound:
                if keep is not None:
                    new_act[keep] = idx
            for idx, keep, hp, mx in bound:
                if keep is None:
                    slot = next((sl for sl in range(n) if new_act[sl] is None), 0)
                    new_act[slot] = idx
            for idx, keep, hp, mx in bound:
                mon = party[idx]
                if mon["f"]:                                                       # the header says it is alive
                    mon["f"] = False
                    self.diag["sync_revived"] += 1
                if mon["max"] is None:
                    mon["max"] = mx
                    self._rehydrate(mon)
                synced.append((side, idx, hp, mx))
            if new_act != self.act[side]:
                self.diag["sync_act_changed"] += 1
            self.act[side] = new_act
        for (side, idx, hp, mx) in synced:
            self._reconcile(i, self.party[side][idx], hp)
        self._emit("sync", i, act={s: list(self.act[s]) for s in "ab"},
                   hp=[[s, idx, hp, mx] for (s, idx, hp, mx) in synced])
        self.actor = None
        self.seg_start_ev = len(self.ev)
        self.seg_act0 = {sd: list(self.act[sd]) for sd in "ab"}


    # ------------------------------------------------------------------ twins: settle ambiguous targets
    def _solve_ambiguity(self, entries_by_side=None, final=False):
        """Two same-species mons on one side (Twins, Double Teams ...): a log line like "Dealt 51 damage to QUAGSIRE!" does
        not say which. Everything in the segment since the last header is attributed provisionally; here the next header's
        exact hp values pick the assignment that explains them (brute force over the few ambiguous events)."""
        if not self.amb and not self.amb_faints:
            return
        groups = {}
        for e in self.amb:
            groups.setdefault((e["side"], tuple(sorted(e["_amb"]))), []).append(e)
        for fe in self.amb_faints:
            side = fe["side"]
            cands = tuple(sorted(c for c in self.seg_act0[side] if c is not None and
                                 self.party[side][c]["sp"] == self.party[side][fe["idx"]]["sp"]))
            if len(cands) > 1:
                groups.setdefault((side, cands), [])
        self.amb, self.amb_faints = [], []
        touched = set()
        for (side, cands), amb_events in groups.items():
            if self._solve_group(side, list(cands), amb_events, entries_by_side, final):
                touched.add(side)
        for side in touched:
            self._rederive_slots(side)

    def _solve_group(self, side, cands, amb_events, entries_by_side, final):
        import itertools
        party = self.party[side]
        if len(amb_events) > 11:
            self.diag["amb_too_many"] += 1
            return False
        evs = {}
        for c in cands:
            for e in party[c]["seg"]:
                if e["k"] == "hp" and e.get("cause") != "faint":
                    evs[e["_s"]] = e
        evs = [evs[k] for k in sorted(evs)]
        start = {c: party[c]["seg_hp0"] for c in cands}
        mx = {c: party[c]["max"] for c in cands}
        if any(start[c] is None or mx[c] is None for c in cands):
            self.diag["amb_nomax"] += 1
            return False
        order = [c for c in self.seg_act0[side] if c in cands]
        if len(order) != len(cands):
            order = list(cands)
        faint_evs = sorted([f for f in self.ev[self.seg_start_ev:] if f["k"] == "faint" and f["side"] == side
                            and f["idx"] in cands], key=lambda f: f["_s"])
        n_faint = len(faint_evs)
        ambs = sorted(amb_events, key=lambda e: e["_s"])
        amb_ids = [e["_s"] for e in ambs]
        unc_tol = sum(abs(e["_raw"][1]) for e in evs if e.get("_u") and e["_raw"][0] == "d")
        disp = party[cands[0]]["disp"]
        expect = None
        if entries_by_side is not None:
            expect = [hp for (lv, sp, hp, m) in entries_by_side.get(side, []) if sp == disp]

        def simulate(choice):
            hp = dict(start)
            traj = []
            for e in evs:
                c = choice.get(e["_s"], e["idx"])
                kind, v = e["_raw"]
                old = hp[c]
                new = _clamp(v if kind == "set" else old + v, 0, mx[c])
                hp[c] = new
                traj.append((e, c, new, new - old))
            return hp, traj

        def cost(hp):
            alive = [c for c in order if hp[c] > 0]
            died = len([c for c in cands if start[c] > 0 and hp[c] == 0])
            tot = abs(died - n_faint) * 1000
            if expect is not None:
                if len(alive) != len(expect):
                    return tot + 10 ** 6
                tot += sum(abs(hp[c] - h) for c, h in zip(alive, expect))
            elif final and self.winner is not None and self.winner != side:
                tot += sum(hp[c] for c in cands) * 10
            return tot

        best = None
        for combo in itertools.product(cands, repeat=len(ambs)):
            choice = dict(zip(amb_ids, combo))
            hp, traj = simulate(choice)
            c_ = cost(hp)
            if best is None or c_ < best[0]:
                best = (c_, choice, hp, traj)
                if c_ == 0:
                    break
        c_, choice, hp, traj = best
        if c_ > unc_tol:
            self.diag["amb_unsolved"] += 1
            return False
        # ---- apply: re-home events, rewrite hp/d, fix who fainted
        for (e, c, new, applied) in traj:
            if e["idx"] != c:
                party[e["idx"]]["seg"].remove(e)
                party[c]["seg"].append(e)
                e["idx"] = c
            e["hp"], e["d"] = new, applied
        for c in cands:
            party[c]["seg"].sort(key=lambda e: e["_s"])
            party[c]["hp"] = hp[c]
        death = {}
        for (e, c, new, applied) in traj:
            if new == 0 and c not in death and start[c] > 0:
                death[c] = e["_s"]
        dead = sorted(death, key=lambda c: death[c])
        if len(faint_evs) == len(dead):
            for fe, c in zip(faint_evs, dead):
                fe["idx"] = c
        for c in cands:
            party[c]["f"] = (hp[c] == 0 and start[c] > 0) or (party[c]["f"] and hp[c] == 0)
        self.diag["amb_solved"] += 1
        return True

    def _rederive_slots(self, side):
        act = list(self.seg_act0[side])
        for e in self.ev[self.seg_start_ev:]:
            if e.get("side") != side or "idx" not in e:
                continue
            k = e["k"]
            if k == "send":
                if e.get("from") is not None and e["from"] in act:
                    sl = act.index(e["from"])
                else:
                    sl = next((x for x in range(len(act)) if act[x] is None), e["slot"])
                act[sl] = e["idx"]
                e["slot"] = sl
            elif k == "faint":
                if e["idx"] in act:
                    e["slot"] = act.index(e["idx"])
                    act[e["slot"]] = None
            else:
                e["slot"] = act.index(e["idx"]) if e["idx"] in act else None

    def _rehydrate(self, mon):
        """Max hp just became known for a mon that was tracked without it: assume it entered at full hp and replay its
        events so they carry real hp values."""
        mx = mon["max"]
        hp = mx
        mon["seg_hp0"] = hp
        for e in mon["seg"]:
            if e["k"] != "hp":
                continue
            kind, v = e["_raw"]
            new = _clamp(v if kind == "set" else hp + v, 0, mx)
            e["hp"], e["max"], e["d"] = new, mx, new - hp
            hp = new
        mon["hp"] = hp

    def _reconcile(self, i, mon, actual):
        pred = mon["hp"]
        mx = mon["max"]
        if pred is None:
            mon["hp"] = actual
            mon["seg"] = []
            mon["seg_hp0"] = actual
            return
        if pred != actual:
            resid = actual - pred
            unc = [e for e in mon["seg"] if e.get("_u")]
            if unc:
                e0 = unc[-1]
                started = False
                for e in mon["seg"]:
                    if e is e0:
                        started = True
                        e0["d"] = (e0["d"] or 0) + resid
                    if started and e["hp"] is not None:
                        e["hp"] = _clamp(e["hp"] + resid, 0, mx)
                self.diag["reconciled"] += 1
            elif resid < 0 and mon.get("sent_ev") is not None and mon["sent_ev"] in self.ev and abs(resid) <= mx:
                # silent entry-hazard damage on switch-in: place it right after the send-out and shift later events
                at = self.ev.index(mon["sent_ev"]) + 1
                for e in mon["seg"]:
                    if e["hp"] is not None:
                        e["hp"] = _clamp(e["hp"] + resid, 0, mx)
                before = mon["seg_hp0"] if mon.get("seg_hp0") is not None else pred
                slot = self.act[mon["side"]].index(mon["idx"]) if mon["idx"] in self.act[mon["side"]] else None
                self.ev.insert(at, {"k": "hp", "i": mon["sent_ev"]["i"], "n": mon["sent_ev"]["n"], "side": mon["side"],
                                    "slot": slot, "idx": mon["idx"], "hp": _clamp(before + resid, 0, mx), "max": mx,
                                    "d": resid, "cause": "hazard"})
                self.diag["hazard_inferred"] += 1
            else:
                self.diag["unexplained"] += 1
                side = mon["side"]
                dup_same = [ai for ai in self.act[side] if ai is not None and ai != mon["idx"] and self.party[side][ai]["disp"] == mon["disp"]]
                dup_foe = [ai for ai in self.act[self._opp(side)] if ai is not None and self.party[self._opp(side)][ai]["disp"] == mon["disp"]]
                tag = "dup_same_side" if dup_same else "dup_other_side" if dup_foe else "other"
                self.diag["unexplained:" + tag] += 1
                recent = [e.get("text") or e.get("cause") or e["k"] for e in self.ev[-6:]]
                self.unexplained.append((self.turn, mon["side"], mon["disp"], pred, actual, recent, tag))
                if mon["idx"] in self.act[mon["side"]]:
                    slot = self.act[mon["side"]].index(mon["idx"])
                else:
                    slot = None
                self._emit("hp", i, side=mon["side"], slot=slot, idx=mon["idx"], hp=actual, max=mx, d=resid,
                           cause="unlogged")
            mon["hp"] = actual
        mon["seg"] = []
        mon["seg_hp0"] = actual
        mon["sent_ev"] = None

    # ------------------------------------------------------------------ structural lines
    def _banner(self, i, s):
        m = re.match(r"^=== WINNER: (.+) ===$", s)
        if m:
            name = m.group(1)
            w = "a" if name == self.names["a"] else "b" if name == self.names["b"] else None
            self.winner = w
            self.ended = True
            self._emit("end", i, winner=w, text=f"{name} wins!")
            return
        if s.startswith("=== GAME"):
            return
        self._emit("msg", i, text=s.strip("= ").strip())

    def _move_line(self, i, s):
        side, rest = self._split_owner(s[4:])
        m = re.match(r"^(.+?) uses (.+?)!$", rest)
        if not m or side is None:
            self.diag["move_unparsed"] += 1
            self._emit("msg", i, text=s.strip())
            return
        species, move = m.groups()
        cands = [(side, sl, c) for sl, c in enumerate(self.act[side]) if c is not None and self.party[side][c]["disp"] == species]
        ref = None
        if len(cands) > 1:
            # twins on one side: the move set tells them apart; failing that, whoever has not acted yet this turn
            pool = [r for r in cands if move in self.party[side][r[2]]["moves"]] or cands
            fresh = [r for r in pool if (side, r[2]) not in self.acted]
            ref = (fresh or pool)[0]
        elif cands:
            ref = cands[0]
        if ref is None:
            ref = self._find_any(species, prefer=side)
            if ref is None or ref[0] != side:
                self.diag["actor_unbound"] += 1
                self.actor = None
                self._emit("msg", i, text=f"{display_species(species)} used {move}!")
                return
        self.actor = ref
        self.acted.add((ref[0], ref[2]))
        self.delayed_target = None
        mon = self.party[ref[0]][ref[2]]
        mon["hidden"] = False
        info = MOVE_TYPES.get(re.sub(r"[^a-z0-9]", "", move.lower()))
        extra = {"type": info[0], "cls": info[1]} if info else {}
        self._emit("move", i, side=ref[0], slot=ref[1], idx=ref[2], move=move,
                   text=f"{display_species(species)} used {move}!", **extra)

    def _faint_line(self, i, s):
        m = FAINT_RE.match(s)
        species = m.group(1)
        asd = self._actor_side()
        cands = []
        for side in "ab":
            for slot, idx in enumerate(self.act[side]):
                if idx is not None and self.party[side][idx]["disp"] == species:
                    cands.append((side, slot, idx))
        ref = None
        ambiguous = False
        if len(cands) == 1:
            ref = cands[0]
        elif cands:
            sides = {c[0] for c in cands}
            if len(sides) > 1:                                    # same species on both sides: the foe of the actor, or hp 0
                zero = [c for c in cands if self.party[c[0]][c[2]]["hp"] == 0]
                pool = zero or [c for c in cands if asd and c[0] != asd] or cands
                cands = pool
            if len(cands) == 1:
                ref = cands[0]
            else:
                zero = [c for c in cands if self.party[c[0]][c[2]]["hp"] == 0]
                if len(zero) == 1:
                    ref = zero[0]
                else:
                    ambiguous = True       # twins on one side: the next turn header decides which one it was
                    ref = min(cands, key=lambda c: (self.party[c[0]][c[2]]["hp"] if self.party[c[0]][c[2]]["hp"] is not None else 10 ** 9))
        if ref is None:
            ref = self._find_any(species, prefer=self._opp(asd) if asd else None)
        if ref is None:
            self.diag["faint_unbound"] += 1
            self._emit("msg", i, text=f"{display_species(species)} fainted!")
            return
        side, slot, idx = ref
        mon = self.party[side][idx]
        if mon["hp"] not in (0, None) and not ambiguous:
            self._hp_change(i, ref, set_to=0, cause="faint", certain=True)
        elif mon["hp"] is None:
            mon["hp"] = 0
        mon["f"] = True
        mon["hp"] = 0
        if slot is not None:
            self.act[side][slot] = None
        self._clear_switch_state(mon)
        fe = self._emit("faint", i, side=side, slot=slot, idx=idx, text=f"{display_species(species)} fainted!")
        if ambiguous:
            fe["_ambf"] = True
            self.amb_faints.append(fe)

    def _pick_bench(self, side, species, exclude=(), at=None):
        """The bench mon that `species` refers to. With several of the same species (Snover x3, Clefairy x3 ...) the log does
        not say which; the next turn header shows who is out, so look ahead and prefer the one whose level / max hp is there."""
        cands = [idx for idx, mon in enumerate(self.party[side])
                 if not mon["f"] and idx not in self.act[side] and idx not in exclude
                 and (mon["sp"] == species or mon["disp"] == species)]
        if len(cands) <= 1 or at is None:
            return cands[0] if cands else None
        nxt = next(((li, ents) for li, ents in self.hdr[side] if li > at), None)
        if nxt:
            ents = [(lv, hp, mx) for (lv, sp, hp, mx) in nxt[1] if sp == species]
            def score(idx):
                mon = self.party[side][idx]
                best = 0
                for lv, hp, mx in ents:
                    if mon["lv"] == lv:
                        best = max(best, 2 if mon["max"] == mx else 1.5 if mon["max"] is None else 1)
                return best
            ranked = sorted(cands, key=lambda c: (-score(c), c))
            return ranked[0]
        return cands[0]

    def _place(self, i, side, slot, idx, why, text, from_idx=None):
        n = len(self.act[side])
        if slot is None or slot >= n:
            slot = next((s for s in range(n) if self.act[side][s] is None), 0)
        self.act[side][slot] = idx
        ev = self._emit("send", i, side=side, slot=slot, idx=idx, why=why, text=text, **{"from": from_idx})
        self.party[side][idx]["sent_ev"] = ev
        self.party[side][idx]["seg_hp0"] = self.party[side][idx]["hp"]

    def _sendout_line(self, i, s):
        m = SENDOUT_RE.match(s)
        name, species = m.groups()
        side = "a" if name == self.names["a"] else "b" if name == self.names["b"] else None
        if side is None:
            self.diag["sendout_side_unknown"] += 1
            self._emit("msg", i, text=s.strip())
            return
        idx = self._pick_bench(side, species, at=i)
        if idx is None:
            self.diag["sendout_unbound"] += 1
            self._emit("msg", i, text=s.strip("- >").strip())
            return
        slot = next((sl for sl in range(len(self.act[side])) if self.act[side][sl] is None), None)
        self._place(i, side, slot, idx, "replace", f"{name} sent out {display_species(species)}!")

    def _voluntary_switch(self, i, m):
        name, old_sp, new_sp = m.groups()
        side = "a" if name == self.names["a"] else "b" if name == self.names["b"] else None
        if side is None:
            self.diag["switch_side_unknown"] += 1
            return
        self._do_switch(i, side, old_sp, new_sp, "switch",
                        f"{name} withdrew {display_species(old_sp)} and sent out {display_species(new_sp)}!")

    def _do_switch(self, i, side, old_sp, new_sp, why, text):
        old = self._find_active(old_sp, prefer=side, only=side)
        old_idx = None
        slot = None
        if old:
            slot, old_idx = old[1], old[2]
            self._clear_switch_state(self.party[side][old_idx])
        idx = self._pick_bench(side, new_sp, at=i)
        if idx is None:
            self.diag["switch_unbound"] += 1
            self._emit("msg", i, text=text)
            return
        if slot is None:
            slot = next((sl for sl in range(len(self.act[side])) if self.act[side][sl] is None), 0)
        self._place(i, side, slot, idx, why, text, from_idx=old_idx)

    # ------------------------------------------------------------------ message lines
    def _msg_line(self, i, t):
        for rx, name in RULES:
            m = rx.match(t)
            if m:
                handler = getattr(self, "_r_" + name, None)
                if handler is None:
                    break
                if handler(i, m, t) is not False:
                    return
        # the three switch variants carry a trainer name / no leading species rule
        m = re.match(r"^(.+?) was blown away! (.+?) sent out (.+?)!$", t)
        if m:
            old_sp, tname, new_sp = m.groups()
            side = "a" if tname == self.names["a"] else "b" if tname == self.names["b"] else None
            if side:
                return self._do_switch(i, side, old_sp, new_sp, "drag",
                                       f"{display_species(old_sp)} was blown away! {tname} sent out {display_species(new_sp)}!")
        m = re.match(r"^(.+?) came back! (.+?) sent out (.+?)!$", t)
        if m:
            old_sp, tname, new_sp = m.groups()
            side = "a" if tname == self.names["a"] else "b" if tname == self.names["b"] else None
            if side:
                return self._do_switch(i, side, old_sp, new_sp, "pivot",
                                       f"{display_species(old_sp)} came back! {tname} sent out {display_species(new_sp)}!")
        m = re.match(r"^(.+?) passed the baton to (.+?)!$", t)
        if m:
            old_sp, new_sp = m.groups()
            ref = self._find_active(old_sp, prefer=self._actor_side())
            if ref:
                return self._do_switch(i, ref[0], old_sp, new_sp, "baton",
                                       f"{display_species(old_sp)} passed the baton to {display_species(new_sp)}!")
        self._msg_generic(i, None, t)

    def _msg_generic(self, i, m, t):
        key = re.sub(r"\d+", "#", t)
        key = re.sub(r"\b[A-Z][A-Z0-9'.\-]+(?: [A-Z0-9]+)*\b", "SP", key)
        self.unclassified[key[:90]] += 1
        self._emit("msg", i, text=t)

    # --- rule handlers (return False to fall through to the next rule) --------------------------------------------
    def _target_of_damage(self, explicit):
        asd = self._actor_side()
        if explicit:
            return self._find_active(explicit, prefer=self._opp(asd) if asd else None)
        if self.delayed_target:
            return self.delayed_target
        if asd:
            opp = [(asd2, slot, idx) for asd2 in [self._opp(asd)] for slot, idx in enumerate(self.act[asd2]) if idx is not None]
            if len(opp) == 1:
                return opp[0]
            if len(opp) > 1:
                return opp[0]
        return None

    @staticmethod
    def _eff_flags(tail):
        tail = tail or ""
        crit = "Critical hit" in tail
        eff = "se" if "Super effective" in tail else "nve" if "Not very effective" in tail else None
        texts = []
        if crit:
            texts.append("A critical hit!")
        if eff == "se":
            texts.append("It's super effective!")
        elif eff == "nve":
            texts.append("It's not very effective...")
        return crit, eff, texts

    def _r_dealt(self, i, m, t):
        n, explicit, tail = int(m.group(1)), m.group(2), m.group(3)
        ref = self._target_of_damage(explicit)
        crit, eff, texts = self._eff_flags(tail)
        self.last_dealt = n
        self.delayed_target = None
        if ref is None:
            self.diag["dealt_unbound"] += 1
            return False
        self._hp_change(i, ref, delta=-n, cause="hit", amt=n, crit=crit, eff=eff, text=texts)

    def _r_multi(self, i, m, t):
        hits, n, explicit, tail = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        ref = self._target_of_damage(explicit)
        crit, eff, texts = self._eff_flags(tail)
        if "At least one critical hit" in (tail or ""):
            crit = True
            texts = ["A critical hit!"] + [x for x in texts if x != "A critical hit!"]
        self.last_dealt = n
        self.delayed_target = None
        if ref is None:
            self.diag["dealt_unbound"] += 1
            return False
        self._hp_change(i, ref, delta=-n, cause="hit", amt=n, hits=hits, crit=crit, eff=eff,
                        text=[f"Hit {hits} time{'s' if hits != 1 else ''}!"] + texts)

    def _r_bide(self, i, m, t):
        _user, n, explicit = m.group(1), int(m.group(2)), m.group(3)
        ref = self._target_of_damage(explicit)
        self.last_dealt = n
        if ref is None:
            return False
        self._hp_change(i, ref, delta=-n, cause="hit", amt=n, text=[t])

    def _r_msg_sub(self, i, m, t):
        self._emit("msg", i, text=t)

    _r_msg_sub2 = _r_msg_sub

    def _r_miss_plain(self, i, m, t):
        asd = self._actor_side()
        ref = None
        if self.delayed_target:
            ref = self.delayed_target
            self.delayed_target = None
        elif asd:
            opp = [(self._opp(asd), slot, idx) for slot, idx in enumerate(self.act[self._opp(asd)]) if idx is not None]
            ref = opp[0] if opp else None
        if ref:
            self._emit("miss", i, side=ref[0], slot=ref[1], idx=ref[2], text="The attack missed!")
        else:
            self._emit("msg", i, text="The attack missed!")

    def _r_miss_target(self, i, m, t):
        ref = self._find_active(m.group(1), prefer=self._opp(self._actor_side()) if self.actor else None)
        if ref:
            self._emit("miss", i, side=ref[0], slot=ref[1], idx=ref[2], text=f"The attack on {display_species(m.group(1))} missed!")
        else:
            self._emit("msg", i, text=t)

    def _lose(self, i, species, n, cause, text=None, role="self", filt=None):
        ref = self._resolve_ctx(species, role, cause if role is None else None, filt)
        if ref is None:
            self.diag["loss_unbound"] += 1
            return False
        self._hp_change(i, ref, delta=-n, cause=cause, amt=n, text=[text] if text else [], filt=filt)
        return ref

    def _r_confusion_hit(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "confusion", "It hurt itself in its confusion!", role=None,
                          filt=lambda mon: "cnf" in mon["vol"])

    def _r_endeavor(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(3)), "endeavor", role="foe")

    def _r_leech(self, i, m, t):
        ref = self._lose(i, m.group(1), int(m.group(2)), "leech", f"{display_species(m.group(1))}'s health is sapped by Leech Seed!",
                         role=None, filt=lambda mon: "seed" in mon["vol"])
        if ref is False:
            return False
        # the seeder (the opposing active mon) is healed by the same amount; capped by its max HP, so flag uncertain
        opp = self._opp(ref[0])
        for slot, idx in enumerate(self.act[opp]):
            if idx is not None:
                self._hp_change(i, (opp, slot, idx), delta=int(m.group(2)), cause="leech_heal", uncertain=True)
                break

    def _r_poison_tick(self, i, m, t):
        ref = self._lose(i, m.group(1), int(m.group(2)), "poison", f"{display_species(m.group(1))} is hurt by poison!",
                         role=None, filt=lambda mon: mon["st"] in ("psn", "tox"))
        if ref and ref is not False:
            mon = self.party[ref[0]][ref[2]]
            if mon["st"] not in ("psn", "tox"):
                self._set_status(i, ref, "psn")
        return ref

    def _r_burn_tick(self, i, m, t):
        ref = self._lose(i, m.group(1), int(m.group(2)), "burn", f"{display_species(m.group(1))} is hurt by its burn!",
                         role=None, filt=lambda mon: mon["st"] == "brn")
        if ref and ref is not False:
            self._set_status(i, ref, "brn")
        return ref

    def _r_sand_tick(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "sand", f"{display_species(m.group(1))} is buffeted by the sandstorm!", role=None)

    def _r_hail_tick(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "hail", f"{display_species(m.group(1))} is pelted by hail!", role=None)

    def _r_recoil(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "recoil", f"{display_species(m.group(1))} was hurt by recoil!")

    def _r_crash(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "crash", f"{display_species(m.group(1))} kept going and crashed!")

    def _r_bind_tick(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(3)), "bind", t, role="foe")

    def _r_curse_tick(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "curse", t, role=None)

    def _r_nightmare_tick(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "nightmare", t, role=None)

    def _r_generic_loss(self, i, m, t):
        return self._lose(i, m.group(1), int(m.group(2)), "loss", re.sub(r" \(-\d+ HP\)", "", t), role=None)

    def _gain(self, i, species, n, cause, text=None, role=None, uncertain=False):
        ref = self._resolve_ctx(species, role, cause if role is None else None)
        if ref is None:
            self.diag["gain_unbound"] += 1
            return False
        self._hp_change(i, ref, delta=n, cause=cause, amt=n, uncertain=uncertain, text=[text] if text else [])
        return ref

    def _r_wish(self, i, m, t):
        # the mon that receives it is whatever sits in the wisher's slot - usually the named species itself
        ref = self._find_active(m.group(1))
        if ref is None:
            self.diag["gain_unbound"] += 1
            return False
        self._hp_change(i, ref, delta=int(m.group(2)), cause="heal", amt=int(m.group(2)), text=[t])

    def _r_heal_ann(self, i, m, t):
        return self._gain(i, m.group(1), int(m.group(2)), "heal", re.sub(r" \(\+\d+ HP\)", "", t))

    def _r_drain(self, i, m, t):
        return self._gain(i, m.group(1), int(m.group(2)), "drain", t, role="self")

    def _r_recovered(self, i, m, t):
        return self._gain(i, m.group(1), int(m.group(2)), "heal", t, role="self")

    def _r_leftovers(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._hp_change(i, ref, delta=self._heal_frac(ref, 16), cause="heal", uncertain=True, text=[t])

    def _r_rest(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        mon = self.party[ref[0]][ref[2]]
        self._set_status(i, ref, "slp")
        self._hp_change(i, ref, set_to=mon["max"], cause="heal", text=[t])

    def _r_swallow(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=self._heal_frac(ref, 2), cause="heal", uncertain=True, text=[t])

    def _r_ability_heal(self, i, m, t):
        ref = self._resolve(m.group(1), "foe")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=self._heal_frac(ref, 4), cause="heal", uncertain=True, text=[t])

    def _r_recover(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=self._heal_frac(ref, 2), cause="heal", uncertain=True, text=[t])

    def _r_belly_drum(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=-self._heal_frac(ref, 2), cause="cost", text=[t])
        self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat="ATK", dir=6, text=None)

    def _r_curse_cast(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=-self._heal_frac(ref, 2), cause="cost", text=[t])

    def _r_substitute(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=-self._heal_frac(ref, 4), cause="cost", uncertain=True, text=[t])
        self._set_vol(i, ref, "sub", True)

    def _r_self_ko(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._hp_change(i, ref, set_to=0, cause="selfko", text=[t])

    def _r_perish_zero(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._hp_change(i, ref, set_to=0, cause="perish", text=[t])

    def _r_aftermath(self, i, m, t):
        ref = self._resolve(m.group(1), "foe")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=-self._heal_frac(ref, 4), cause="aftermath", uncertain=True, text=[t])

    def _r_liquid_ooze(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._hp_change(i, ref, delta=-max(1, self.last_dealt // 2), cause="ooze", uncertain=True, text=[t])

    def _r_pain_split(self, i, m, t):
        r1 = self._resolve(m.group(1), "self")
        r2 = self._resolve(m.group(2), "foe")
        if r1 is None or r2 is None:
            return False
        h1, h2 = self.party[r1[0]][r1[2]]["hp"], self.party[r2[0]][r2[2]]["hp"]
        if h1 is None or h2 is None:
            return False
        shared = (h1 + h2) // 2
        self._hp_change(i, r1, set_to=shared, cause="split", text=[t])
        self._hp_change(i, r2, set_to=shared, cause="split")

    def _r_transform(self, i, m, t):
        # the engine renames the user BEFORE printing, so group(1) is already the new species: take the actor instead
        ref = self.actor if self.actor else self._resolve(m.group(1), "self")
        if ref is None:
            return False
        mon = self.party[ref[0]][ref[2]]
        mon["disp"] = m.group(2)
        self._emit("transform", i, side=ref[0], slot=ref[1], idx=ref[2], to=m.group(2),
                   text=f"{display_species(m.group(1))} transformed into {display_species(m.group(2))}!")

    def _r_afflicted(self, i, m, t):
        st = STATUS_BY_NAME.get(m.group(2).strip().upper())
        ref = self._resolve(m.group(1), "foe")
        if ref is None or st is None:
            return False
        self._set_status(i, ref, st, text=t)

    def _r_orb_status(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self._set_status(i, ref, "tox" if "poison" in t else "brn", text=t)

    def _r_contact_status(self, i, m, t):
        ref = self._resolve(m.group(1), "foe")
        if ref is None:
            return False
        st = {"paralyzed": "par", "burned": "brn", "poisoned": "psn"}[m.group(2)]
        self._set_status(i, ref, st, text=t)

    def _r_drowsy_sleep(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._set_status(i, ref, "slp", text=t)

    def _evidence(self, i, m, t, st):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._set_status(i, ref, st)
        self._emit("msg", i, text=t)

    def _r_ev_sleep(self, i, m, t):
        return self._evidence(i, m, t, "slp")

    def _r_ev_par(self, i, m, t):
        return self._evidence(i, m, t, "par")

    def _r_ev_frz(self, i, m, t):
        return self._evidence(i, m, t, "frz")

    def _cure(self, i, m, t, only=None):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        mon = self.party[ref[0]][ref[2]]
        if only and mon["st"] not in (None, only):
            # keep an unrelated status; the line still shows
            self._emit("msg", i, text=t)
            return
        self._set_status(i, ref, None, text=t)

    def _r_cure_slp(self, i, m, t):
        return self._cure(i, m, t)

    def _r_cure_frz(self, i, m, t):
        return self._cure(i, m, t)

    def _r_cure_any(self, i, m, t):
        return self._cure(i, m, t)

    def _r_party_cure(self, i, m, t):
        asd = self._actor_side()
        if asd is None:
            return False
        for idx, mon in enumerate(self.party[asd]):
            if mon["st"]:
                ref = (asd, self.act[asd].index(idx) if idx in self.act[asd] else None, idx)
                self._set_status(i, ref, None)
        self._emit("msg", i, text=t)

    def _r_confused(self, i, m, t):
        ref = self._resolve(m.group(1), "self" if "due to fatigue" in t else "foe")
        if ref is None:
            return False
        self._set_vol(i, ref, "cnf", True, text=t)

    def _r_ev_confused(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._set_vol(i, ref, "cnf", True)
        self._emit("msg", i, text=t)

    def _r_unconfused(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._set_vol(i, ref, "cnf", False, text=t)

    def _r_love(self, i, m, t):
        self._emit("msg", i, text=t)

    def _r_seeded(self, i, m, t):
        ref = self._resolve(m.group(1), "foe")
        if ref is None:
            return False
        self._set_vol(i, ref, "seed", True, text=t)

    def _r_stat(self, i, m, t):
        ref = self._resolve(m.group(1), "self" if m.group(3) == "rose" else "foe")
        if ref is None:
            return False
        stat = m.group(2)
        self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat=stat, dir=1 if m.group(3) == "rose" else -1,
                   text=f"{display_species(m.group(1))}'s {STAT_NAMES[stat]} {m.group(3)}!")

    def _r_stat_fell_intimidate(self, i, m, t):
        ref = self._resolve(m.group(1), "foe")
        if ref is None:
            return False
        self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat=m.group(2), dir=-1,
                   text=f"{display_species(m.group(1))}'s {STAT_NAMES[m.group(2)]} fell!")

    def _r_intimidate(self, i, m, t):
        ref = self._resolve(m.group(2), None)
        self._emit("msg", i, text=f"{display_species(m.group(1))}'s Intimidate!")
        if ref:
            self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat="ATK", dir=-1,
                       text=f"{display_species(m.group(2))}'s Attack fell!")

    def _r_download(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        stat = "ATK" if m.group(2) == "Attack" else "SPA"
        self._emit("msg", i, text=f"{display_species(m.group(1))}'s Download!")
        if ref:
            self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat=stat, dir=1,
                       text=f"{display_species(m.group(1))}'s {STAT_NAMES[stat]} rose!")

    def _r_steadfast(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat="SPE", dir=1, text=t)

    def _r_anger_point(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        if ref is None:
            return False
        self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat="ATK", dir=6, text=t)

    def _r_all_stats_up(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        for stat in ("ATK", "DEF", "SPA", "SPD", "SPE"):
            self._emit("stat", i, side=ref[0], slot=ref[1], idx=ref[2], stat=stat, dir=1, text=t if stat == "ATK" else None)

    def _r_haze(self, i, m, t):
        self._emit("field", i, what="haze", val=True, text=t)

    def _r_vanish_on(self, i, m, t):
        ref = self._resolve(m.group(1), "self")
        if ref is None:
            return False
        self.party[ref[0]][ref[2]]["hidden"] = True
        self._emit("vanish", i, side=ref[0], slot=ref[1], idx=ref[2], on=True, text=t)

    def _r_weather_set(self, i, m, t):
        w = WEATHER_BY_NAME.get(m.group(1))
        if w is None:
            return False
        self.field["weather"] = w
        self._emit("field", i, what="weather", val=w, text=t)

    def _r_weather_ability(self, i, m, t):
        w = {"Drought": "sun", "Drizzle": "rain", "Sand Stream": "sand", "Snow Warning": "hail"}[m.group(2)]
        self.field["weather"] = w
        self._emit("field", i, what="weather", val=w, text=t)

    def _r_weather_end(self, i, m, t):
        self.field["weather"] = None
        self._emit("field", i, what="weather", val=None, text=t)

    def _side_of_species(self, species, role="self"):
        ref = self._resolve(species, role)
        return ref[0] if ref else (self._actor_side() or "a")

    def _start_timer(self, what, side, duration):
        self.timers = [tm for tm in self.timers if not (tm["what"] == what and tm["side"] == side)]
        self.timers.append({"what": what, "side": side, "until": self.turn + duration - 1})

    def _actor_item(self):
        if not self.actor:
            return None
        return self.party[self.actor[0]][self.actor[2]]["item"]

    def _r_screen_on(self, i, m, t):
        side = self._side_of_species(m.group(1))
        what = "reflect" if m.group(2) == "Reflect" else "lightscreen"
        self._emit("field", i, what=what, side=side, val=True, text=t)
        self._start_timer(what, side, 8 if self._actor_item() == "Light Clay" else 5)

    def _r_safeguard_on(self, i, m, t):
        side = self._side_of_species(m.group(1))
        self._emit("field", i, what="safeguard", side=side, val=True, text=t)
        self._start_timer("safeguard", side, 5)

    def _r_tailwind_on(self, i, m, t):
        side = self._side_of_species(m.group(1))
        self._emit("field", i, what="tailwind", side=side, val=True, text=t)
        self._start_timer("tailwind", side, 4)

    def _r_mist_off(self, i, m, t):
        side = "a" if m.group(1) == self.names["a"] else "b" if m.group(1) == self.names["b"] else None
        if side is None:
            return False
        self._emit("field", i, what="mist", side=side, val=False, text=t)

    def _r_luckychant_off(self, i, m, t):
        side = "a" if m.group(1) == self.names["a"] else "b" if m.group(1) == self.names["b"] else None
        if side is None:
            return False
        self._emit("field", i, what="luckychant", side=side, val=False, text=t)

    def _r_mist_on(self, i, m, t):
        self._emit("field", i, what="mist", side=self._side_of_species(m.group(1)), val=True, text=t)

    def _r_luckychant_on(self, i, m, t):
        self._emit("field", i, what="luckychant", side=self._side_of_species(m.group(1)), val=True, text=t)

    def _r_trickroom_on(self, i, m, t):
        self._emit("field", i, what="trickroom", val=True, text=t)

    def _r_trickroom_off(self, i, m, t):
        self._emit("field", i, what="trickroom", val=False, text=t)

    def _r_gravity_on(self, i, m, t):
        self._emit("field", i, what="gravity", val=True, text=t)

    def _r_gravity_off(self, i, m, t):
        self._emit("field", i, what="gravity", val=False, text=t)

    def _r_called(self, i, m, t):
        self._emit("msg", i, text=t)

    def _r_delayed_setup(self, i, m, t):
        self._emit("msg", i, text=t)

    def _r_delayed_strike(self, i, m, t):
        ref = self._find_active(m.group(3))
        self.delayed_target = ref
        self._emit("msg", i, text=t)

    HEAL_BERRY_DIV = {"Sitrus Berry": 4, "Figy Berry": 8, "Wiki Berry": 8, "Mago Berry": 8, "Aguav Berry": 8,
                      "Iapapa Berry": 8}

    def _r_consumed(self, i, m, t):
        ref = self._resolve(m.group(1), None)
        item = m.group(2)
        if ref is not None and (item in self.HEAL_BERRY_DIV or item == "Oran Berry" or item == "Berry Juice"):
            side, slot, idx = ref
            mx = self.party[side][idx]["max"] or 0
            amount = 10 if item == "Oran Berry" else 20 if item == "Berry Juice" else max(1, mx // self.HEAL_BERRY_DIV[item])
            self._emit("msg", i, text=t)
            self._hp_change(i, ref, delta=amount, cause="heal", uncertain=True)
            return
        return False

    def _r_msg_generic(self, i, m, t):
        self._emit("msg", i, text=t)

    # ------------------------------------------------------------------ finish
    def _finalize(self):
        # mons whose max HP was never printed in a header (sent out and gone inside one turn): estimate it from the
        # damage they took, then rewrite their events' hp so the bar still drains consistently.
        for side in "ab":
            for mon in self.party[side]:
                if mon["max"] is not None:
                    continue
                evs = [e for e in self.ev if e["k"] == "hp" and e["side"] == side and e["idx"] == mon["idx"]]
                if not evs:
                    continue
                taken = sum(-(e["d"] or 0) for e in evs if (e["d"] or 0) < 0)
                mx = max(1, taken)
                hp = mx
                for e in evs:
                    hp = _clamp(hp + (e["d"] or 0), 0, mx)
                    e["hp"], e["max"] = hp, mx
                mon["max"] = mx
                self.diag["max_estimated"] += 1
        self._solve_ambiguity(None, final=True)
        for e in self.ev:
            for key in ("_u", "_s", "_raw", "_amb", "_ambf"):
                e.pop(key, None)
        if not self.ended:
            self.diag["no_end_banner"] += 1

    def replay(self):
        teams = {s: [{"sp": m["sp"], "lv": m["lv"], "ab": m["ab"], "item": m["item"], "moves": m["moves"],
                      "max": m["max"]} for m in self.party[s]] for s in "ab"}
        turns = max((e["n"] for e in self.ev), default=0)
        d = self.diag
        # anything the parser could not account for from the text alone (see validate_parser.py): 0 = every hp change was explained
        issues = sum(d.get(k, 0) for k in ("unexplained", "amb_unsolved", "sync_revived", "sync_unbound", "errors", "actor_unbound",
                                           "dealt_unbound", "loss_unbound", "gain_unbound", "faint_unbound", "switch_unbound", "sendout_unbound"))
        return {
            "v": 1,
            "meta": {"game": self.game, "a": self.names["a"], "b": self.names["b"], "double": self.double,
                     "winner": self.winner, "turns": turns, "source": self.source, "issues": issues},
            "teams": teams,
            "events": self.ev,
            "diag": dict(self.diag),
        }


def parse_text(text, source=None):
    return ReplayParser(text, source).parse()


def parse_file(path):
    with open(path, encoding="utf-8") as fh:
        return parse_text(fh.read(), source=os.path.basename(path))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python battle_log_parser.py <log.txt> [out.json]")
        sys.exit(1)
    rp = parse_file(sys.argv[1])
    out = json.dumps(rp, separators=(",", ":"))
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"{len(rp['events'])} events, {len(out)} bytes, diag={rp['diag']}")
    else:
        print(out)
