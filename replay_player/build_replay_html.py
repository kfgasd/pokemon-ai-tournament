# -*- coding: utf-8 -*-
"""Builds one self-contained replay page (HTML + embedded sprites + the parsed battle) from a battle log .txt.

Usage:  python build_replay_html.py <log.txt> [out.html]
As a module:  build_html(log_text, source_name) -> str   (this is what a Streamlit page would call)

Sprites come from the Platinum decomp (res/pokemon/<slug>/male_front.png + male_back.png: 160x80 = two 80x80 idle frames,
palette index 0 = background). They are shipped inline as base64 PNGs with the bg colour made transparent, plus how many
transparent rows sit under the feet so the player can stand every species on the same ground line.
"""
import base64
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import battle_log_parser as blp

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "player_template.html")
SPRITE_ROOTS = [
    os.path.join(HERE, "..", "pokeplatinum-main", "pokeplatinum-main", "res", "pokemon"),
    os.path.join(HERE, "sprites", "pokemon"),          # a deployment can ship just the battle sprites here
]
TERRAIN_ROOTS = [
    os.path.join(HERE, "..", "pokeplatinum-main", "pokeplatinum-main", "res", "graphics", "battle", "terrain"),
    os.path.join(HERE, "sprites", "terrain"),
]
_cache = {}
_terrain_cache = {}

# trainer-name keywords -> the decomp's own battle terrain (platform art). Checked against the second trainer first ("home ground").
_LEAGUE = {"aaron": "league_aaron", "bertha": "league_bertha", "flint": "league_flint", "lucian": "league_lucian", "cynthia": "league_cynthia"}
_TERRAIN_KEYWORDS = [
    (("distortion world", "galactic boss cyrus"), "distortion_world"),
    (("swimmer", "fisherman", "sailor", "tuber", "lake"), "water"),
    (("skier", "snowpoint", "snow"), "snow"),
    (("hiker", "ruin maniac", "miner", "cave", "tunnel", "underground"), "cave"),
    (("black belt", "battle girl", "veteran"), "rocky"),
    (("beauty", "gentleman", "lady", "rich boy", "socialite", "idol", "artist", "collector", "twins"), "path"),
    (("leader", "galactic", "commander", "team rocket", "executive", "scientist", "interviewer", "reporter", "cameraman", "sage",
      "elite four", "champion", "ace trainer", "psychic", "medium", "kimono", "guitarist", "juggler", "clown", "cyclist", "biker"), "indoors"),
]


def terrain_for(name_a, name_b=""):
    """Picks a battle terrain from the trainers' names: league rooms for the Sinnoh Elite Four / Cynthia, otherwise by trainer type, with
    grass as the default. The tournament has no real location, so this is flavour only."""
    for name in (name_b, name_a):
        low = (name or "").lower()
        for who, terr in _LEAGUE.items():
            if who in low and ("elite four" in low or "champion" in low):
                return terr
    for name in (name_b, name_a):
        low = (name or "").lower()
        for words, terr in _TERRAIN_KEYWORDS:
            if any(w in low for w in words):
                return terr
    return "grass"


def slug(species):
    return re.sub(r"[.']", "", species.lower().replace(" ", "_"))


def _find_sprite(sl, name):
    for root in SPRITE_ROOTS:
        for gender in ("male", "female"):
            p = os.path.join(root, sl, f"{gender}_{name}.png")
            if os.path.exists(p):
                return p
    return None


def sprite_entry(species):
    sl = slug(species)
    if sl in _cache:
        return _cache[sl]
    from PIL import Image
    entry = None
    out = {}
    for key, name, gkey in (("f", "front", "fg"), ("b", "back", "bg")):
        path = _find_sprite(sl, name)
        if not path:
            continue
        im = Image.open(path).convert("RGBA")
        px = im.load()
        key_color = px[0, 0]
        w, h = im.size
        for y in range(h):
            for x in range(w):
                if px[x, y] == key_color:
                    px[x, y] = (0, 0, 0, 0)
        # transparent rows under the feet of frame 0
        bottom = -1
        for y in range(h - 1, -1, -1):
            if any(px[x, y][3] for x in range(min(80, w))):
                bottom = y
                break
        out[gkey] = max(0, h - (bottom + 1)) if bottom >= 0 else 0
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        out[key] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    entry = out or None
    _cache[sl] = entry
    return entry


def terrain_entry(name):
    """{'e': data-url of the foe platform, 'p': of the player strip} with the 'day' palette applied and palette index 0 transparent."""
    if name in _terrain_cache:
        return _terrain_cache[name]
    from PIL import Image
    out = None
    for root in TERRAIN_ROOTS:
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        pal_path = next((os.path.join(d, n) for n in ("day.pal", "all.pal") if os.path.exists(os.path.join(d, n))), None)
        pal = None
        if pal_path:
            tok = open(pal_path).read().split()
            pal = list(map(int, tok[3:3 + 3 * int(tok[2])]))
        res = {}
        for key, fn in (("e", "enemy.png"), ("p", "player.png")):
            fp = os.path.join(d, fn)
            if not os.path.exists(fp):
                continue
            im = Image.open(fp)
            if pal:
                im.putpalette((pal + [0] * 768)[:768])
            rgba = im.convert("RGBA")
            import numpy as np                      # palette index 0 is the sprite-transparent colour
            rgba.putalpha(Image.fromarray(np.where(np.array(im) == 0, 0, 255).astype("uint8"), "L"))
            buf = io.BytesIO()
            rgba.save(buf, format="PNG", optimize=True)
            res[key] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        if res:
            out = res
            break
    _terrain_cache[name] = out
    return out


def species_in(replay):
    names = set()
    for side in "ab":
        for m in replay["teams"][side]:
            names.add(m["sp"])
    for e in replay["events"]:
        if e["k"] == "transform":
            names.add(e["to"])
    return names


def build_html(log_text, source_name=None, extra_meta=None, trainer_images=None, terrain=None):
    parser = blp.ReplayParser(log_text, source_name)
    rp = parser.parse()
    rp["log"] = [ln.rstrip() for ln in log_text.replace("\r\n", "\n").split("\n")]
    if extra_meta:
        rp["meta"].update(extra_meta)
    for side in (trainer_images or {}):
        if trainer_images[side]:
            rp["meta"][side + "_img"] = trainer_images[side]
    terrain = terrain or terrain_for(rp["meta"]["a"], rp["meta"]["b"])
    rp["meta"]["terrain"] = terrain
    terr_data = terrain_entry(terrain) or {}
    sprites = {}
    for sp in species_in(rp):
        e = sprite_entry(sp)
        if e:
            sprites[slug(sp)] = e
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read()
    data = json.dumps(rp, separators=(",", ":")).replace("</", "<\\/")
    spr = json.dumps(sprites, separators=(",", ":")).replace("</", "<\\/")
    terr = json.dumps(terr_data, separators=(",", ":"))
    return tpl.replace("/*__REPLAY__*/", data).replace("/*__SPRITES__*/", spr).replace("/*__TERRAIN__*/", terr)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(os.path.basename(src))[0] + ".html"
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    html = build_html(text, os.path.basename(src))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {out} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
