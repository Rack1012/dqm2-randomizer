"""Reference model of the in-game randomizer rules, and the tables it needs.

The ARM hooks implement exactly these rules; build.py embeds the tables and
tests can compare emulator memory against these predictions. Reading the ROM
uses the recovered romtool/xbbtool modules (sourceless .pyc).
"""
from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

MASK32 = 0xFFFFFFFF
OPTION_ROAMING = 1
OPTION_SKILLSETS = 2
OPTION_BOSSES = 4
OPTION_FUSION = 8                  # kept out of the settings u16: save magic | 1 (settings.s)
DOMAIN_ROAMING = 1
DOMAIN_BOSS = 2
DOMAIN_SKILL = 3
DOMAIN_EXTRA = 4
DOMAIN_FUSION = 5
MAX_TRIES = 256

# Fusion engine (object built by 0x57a93c each time a fusion screen opens).
# 0x5790a0 returns candidate k's species for two parents and a type code;
# types 4-8 are fusion outcomes (4 = four-grandparent 4GTbl, 5 = KindTbl
# pair, 6 = card-suit rule, 7 = family/rank rule 0x57832c, 8 = KindTypeTbl
# species + family); 1-3 hand back a parent (Montner, same species).
CODE_FILE = 0x6E00                 # .code in the cartridge image; VA = 0x100000 + offset
MIX_FAMILY_VA = 0x666278           # s16 (family a, family b, result family), -1 ends
SUIT_RESULTS = range(336, 344)     # 0x5779f0: Wulfspade..Diamagon and their Aces
ORDER_MASK = 0x1FFF                # EKT +0x0a: fusion order of the species

# Super G species with battle data and icons that KEY01 omits. They roam the
# story worlds' maps as bosses (BEPT 2201-2203), so they are neither re-rolled
# nor used as replacements.
SUPER_G = frozenset((797, 798, 799, 800, 801, 806, 807, 808, 809, 810, 811, 888, 896))
BATTLE_SLOTS = 4

# EnemyPartyTbl party ids of the scripted boss fights the bosses option
# re-rolls (every BEPT row in them, minions included): the story bosses,
# Estark, and Gryphynx / King Squid / Slime Blaster. Parties 39-41 are the
# Super G fights; 38 (Skeleton Soldiers) uses a roaming row.
BOSS_PARTIES = tuple(range(1, 38)) + (42, 90, 91, 92)
PARTY_RECORD = 34                  # u16 id, u16 BEPT ids[4] (9999 = none), ...
PARTY_EMPTY = 9999

EKT_RECORD = 114
BEPT_RECORD = 96
BEPT_COUNT = 3600
SKILL_RECORD = 132
SPECIES_COUNT = 1024
EXTRA_OFFSETS = (0x54, 0x56)       # BEPT encounter extras after the signature at +0x52

# Mysterious Key screen (Great Log): the monster pages of a world key list
# data/Param/WorldMonsterList/<world>.xbb.gz, indexed by the key's world
# (0x668fe4 order). Each world's encounter maps start with these prefixes.
KEY_WORLDS = (("Maruta", ("MAA",)), ("Desert", ("A",)), ("Water", ("B",)), ("Snow_Ice", ("C",)),
              ("Sky", ("D",)), ("Gap", ("E",)), ("Mistletoe", ("F",)), ("Last", ("G",)))
KEY_LIST_DEFAULT = -1              # 0x668fbc: pushed when a list comes out empty


def roll32(seed: int, domain: int, key: int, ordinal: int = 0) -> int:
    x = (seed * 0x9E3779B9 ^ domain * 0x85EBCA6B ^ key * 0xC2B2AE35 ^ ordinal * 0x27D4EB2D) & MASK32
    x ^= (x << 13) & MASK32
    x ^= x >> 17
    x ^= (x << 5) & MASK32
    return x


def size_slots(code: int) -> int:
    n = code & 15
    return 1 if n <= 3 else 2 if n <= 7 else 3 if n == 8 else 4 if n <= 10 else 0


class RomData:
    """The subset of ROM tables the randomizer rules depend on."""

    def __init__(self, rom: Path, pyc_dir: Path, text_index: Path):
        import sys
        sys.path.insert(0, str(pyc_dir))
        from romtool import Cartridge, read_at
        from xbbtool import parse_xbb
        cart = Cartridge(rom)
        files = {f.path: f for f in cart.romfs(0).files()}

        def raw(path):
            f = files[path]
            return read_at(cart.stream, f.offset, f.size)

        self.ekt = raw("data/Param/EnmyKindTbl.bin")[8:]
        self.bept = raw("data/Param/BtlEnmyPrm.bin")[8:]
        self.skill = raw("data/Param/SkillTbl.bin")[8:]
        self.key_monster = raw("data/Param/KeyMonsterTbl.bin")
        self.parties = raw("data/Param/EnemyPartyTbl.bin")
        self.fusion_files = {name: raw(f"data/Param/Combination{name}Tbl.bin")
                             for name in ("Kind", "KindType", "4G", "NotRank", "RankTopMons")}
        mix = read_at(cart.stream, CODE_FILE + MIX_FAMILY_VA - 0x100000, 6 * 64)
        self.mix_family = []
        for i in range(0, len(mix), 6):
            entry = struct.unpack_from("<3h", mix, i)
            if entry[0] == -1:
                break
            self.mix_family.append(entry)
        self.key01_species = set()
        self.roaming_bept_ids = set()
        self.map_primary_ids: dict[str, list[int]] = {}     # Encount map -> SingleMonster +2 ids
        for path in files:
            if "/EncountData/" not in path:
                continue
            xbb = gzip.decompress(raw(path))
            single = next(m for m in parse_xbb(xbb) if m["name"] == "SingleMonster.bin")
            body = xbb[single["offset"]:single["offset"] + single["size"]]
            name = path.rsplit("Encount_", 1)[1].removesuffix(".xbb.gz")
            self.map_primary_ids[name] = [struct.unpack_from("<H", body, i + 2)[0]
                                          for i in range(0, len(body), 80)]
            for i in range(0, len(body), 80):
                # +2 primary BEPT id; +0x1e/+0x24/+0x2a rare-swap BEPT ids
                # (loaded at +0x22/+0x28/+0x2e, gathered by the loader at 0x2a39b0)
                for off in (2, 0x1E, 0x24, 0x2A):
                    bid = struct.unpack_from("<H", body, i + off)[0]
                    if bid:
                        self.roaming_bept_ids.add(bid)
                if path.endswith("Encount_KEY01.xbb.gz"):
                    self.key01_species.add(struct.unpack_from("<H", body, i + 4)[0])
        self.world_lists = []                               # u16 species per KEY_WORLDS entry
        for world, _ in KEY_WORLDS:
            xbb = gzip.decompress(raw(f"data/Param/WorldMonsterList/{world}.xbb.gz"))
            m = parse_xbb(xbb)[0]
            self.world_lists.append(list(struct.unpack(f"<{m['size'] // 2}H",
                                                       xbb[m["offset"]:m["offset"] + m["size"]])))
        self.names = {}
        self.skill_names = {}
        for line in text_index.open(encoding="utf-8"):
            r = json.loads(line)
            if r["path"].endswith("msg_monstername.binJ") and r["group"] == 0:
                self.names[r["item"]] = r["text"]
            elif r["path"].endswith("msg_skillname.binJ") and r["group"] == 0:
                self.skill_names[r["item"]] = r["text"]

    def slots(self, species: int) -> int:
        return size_slots(self.ekt[species * EKT_RECORD + 9])

    def stat_caps(self, species: int) -> tuple[int, ...]:
        """HP, MP, Attack, Defense, Agility, Wisdom caps (EKT +0x12)."""
        return struct.unpack_from("<6H", self.ekt, species * EKT_RECORD + 0x12)

    def innate(self, species: int) -> int:
        return struct.unpack_from("<H", self.ekt, species * EKT_RECORD + 0x66)[0]

    def roaming_pool(self) -> list[int]:
        pool = []
        for sp in sorted(self.key01_species - SUPER_G):
            exp = struct.unpack_from("<I", self.key_monster, sp * 12 + 4)[0]
            if self.names.get(sp) and exp and self.slots(sp):
                pool.append(sp)
        return pool

    def bept_species(self, bept_id: int) -> int:
        return struct.unpack_from("<H", self.bept, (bept_id - 1) * BEPT_RECORD)[0]

    def boss_bept_ids(self) -> set[int]:
        """Rows of the BOSS_PARTIES fights (never Super G ones)."""
        ids = set()
        for party in BOSS_PARTIES:
            o = (party - 1) * PARTY_RECORD
            assert struct.unpack_from("<H", self.parties, o)[0] == party
            ids.update(i for i in struct.unpack_from("<4H", self.parties, o + 2)
                       if i not in (0, PARTY_EMPTY) and self.bept_species(i) not in SUPER_G)
        return ids

    def randomized_bept_ids(self) -> set[int]:
        """Roaming rows that get re-rolled: all but the world maps' Super G bosses
        and the rows the bosses option owns (King Squid, Slime Blaster)."""
        return {i for i in self.roaming_bept_ids
                if self.bept_species(i) not in SUPER_G} - self.boss_bept_ids()

    def reroll_bitmap(self) -> bytes:
        """Bit i set when either option can re-roll BEPT id i (backed-up rows)."""
        bits = bytearray(BEPT_COUNT // 8 + 1)
        for i in self.randomized_bept_ids() | self.boss_bept_ids():
            bits[i >> 3] |= 1 << (i & 7)
        return bytes(bits)

    def reroll_runs(self) -> bytes:
        """reroll_bitmap's ids as runs: u8 gap after the previous run's end,
        u8 run length; gaps over 255 take (255, 0) fillers; gap 0 ends it."""
        ids = sorted(self.randomized_bept_ids() | self.boss_bept_ids())
        out, end, i = bytearray(), 0, 0
        while i < len(ids):
            j = i
            while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
                j += 1
            gap = ids[i] - end
            while gap > 255:
                out += bytes((255, 0))
                gap -= 255
            out += bytes((gap, j - i + 1))
            end, i = ids[j] + 1, j + 1
        return bytes(out + b"\0")

    def boss_bitmap(self) -> tuple[int, bytes]:
        """(first id, bitmap) of boss rows over a window starting at first id."""
        ids = self.boss_bept_ids()
        first = min(ids) & ~7
        bits = bytearray((max(ids) - first) // 8 + 1)
        for i in ids:
            bits[(i - first) >> 3] |= 1 << ((i - first) & 7)
        return first, bytes(bits)

    def has_actions(self, skill: int) -> bool:
        """SkillTbl record: ten 10-byte reward slots from +0x0a, u16 action ID first."""
        o = skill * SKILL_RECORD + 0x0A
        return any(struct.unpack_from("<H", self.skill, o + 10 * k)[0] for k in range(10))

    def shuffle_species(self) -> list[int]:
        """Species whose signature skillset joins the skillset shuffle: named ones
        with a skill-teaching signature (drops two unnamed dummy species)."""
        return [sp for sp in range(SPECIES_COUNT)
                if self.innate(sp) and self.names.get(sp) and self.has_actions(self.innate(sp))]

    def shuffle_bitmap(self) -> bytes:
        bits = bytearray(SPECIES_COUNT // 8)
        for sp in self.shuffle_species():
            bits[sp >> 3] |= 1 << (sp & 7)
        return bytes(bits)

    def extra_pools(self) -> tuple[list[int], list[int]]:
        """Boost/Ward sets used as encounter extras, split into (regular, Uber)
        tiers; an extra is re-rolled only within its own tier."""
        used = {struct.unpack_from("<H", self.bept, i * BEPT_RECORD + off)[0]
                for i in range(BEPT_COUNT) for off in EXTRA_OFFSETS} - {0}
        regular, uber = [], []
        for sk in sorted(used):
            name = self.skill_names.get(sk, "")
            if self.has_actions(sk) or not ("Boost" in name or "Ward" in name):
                continue
            (uber if name.startswith("Uber") else regular).append(sk)
        return regular, uber

    # --- fusion -----------------------------------------------------------

    def ekt_u16(self, species: int, off: int) -> int:
        return struct.unpack_from("<H", self.ekt, species * EKT_RECORD + off)[0]

    def family(self, species: int) -> int:
        return self.ekt[species * EKT_RECORD + 8] >> 4

    def rank(self, species: int) -> int:
        return self.ekt[species * EKT_RECORD + 8] & 15

    def order(self, species: int) -> int:
        return self.ekt_u16(species, 0x0A) & ORDER_MASK

    def recipe_results(self) -> set[int]:
        """Results of the pair (8 B), species+family (8 B) and 4-grandparent
        (16 B: result, 6 zero bytes, 4 parents) recipe tables."""
        out = set()
        for name, size in (("Kind", 8), ("KindType", 8), ("4G", 16)):
            b = self.fusion_files[name]
            for i in range(0, len(b) - 1, size):
                result = struct.unpack_from("<h", b, i)[0]
                if result == -1:        # every table ends with an all-0xffff row
                    break
                out.add(result)
        return out

    def fusion_engine(self) -> "GenericFusion":
        return GenericFusion(self)

    def fusion_pool(self) -> list[int]:
        """Every species vanilla fusion can hand out as a new monster (types 4-8
        of 0x5790a0): recipe results, the suit rule's results and whatever the
        family/rank rule reaches from any parent pair in any start state.
        Parents are handed back only when they are already in this pool."""
        pool = self.recipe_results() | set(SUIT_RESULTS)
        pool |= self.fusion_engine().reachable()
        return sorted(sp for sp in pool if 0 < sp < SPECIES_COUNT)

    def fusion_bitmap(self) -> bytes:
        bits = bytearray(SPECIES_COUNT // 8)
        for sp in self.fusion_pool():
            bits[sp >> 3] |= 1 << (sp & 7)
        return bytes(bits)

    def key_world_ids(self) -> list[list[int]]:
        """Per KEY_WORLDS entry, the BEPT rows behind its monster list: for each
        listed species (list order), the primary rows of that species in the
        world's maps, ascending. The lists leave out chest monsters, metals and
        Super G / bosses, so rows of those never enter; every listed species has
        at least one row."""
        out = []
        for (world, prefixes), listed in zip(KEY_WORLDS, self.world_lists):
            rows = {bid for name, ids in self.map_primary_ids.items() if name.startswith(prefixes)
                    for bid in ids if bid}
            ids = []
            for sp in dict.fromkeys(v for v in listed if v):
                found = sorted(b for b in rows if self.bept_species(b) == sp)
                assert found, (world, sp)
                ids += found
            out.append(ids)
        return out

    def key_list_species(self, world: int, rows: bytes, settings: int) -> list[int]:
        """Species vector 0x214f58 builds (before its sort by family/order): the
        file list, or with roaming on the current species of the world's rows;
        species with no fusion order skipped, duplicates dropped."""
        ids = self.key_world_ids()[world] if settings & OPTION_ROAMING else []
        if ids:
            source = [struct.unpack_from("<H", rows, (b - 1) * BEPT_RECORD)[0] for b in ids]
        else:
            source = self.world_lists[world]
        out = []
        for sp in source:
            if self.order(sp) and sp not in out:
                out.append(sp)
        return out or [KEY_LIST_DEFAULT]

    def species_table(self) -> bytes:
        """1024 nibbles: bits 0-2 slot count (0 = unknown), bit 3 = in roaming pool."""
        pool = set(self.roaming_pool())
        nib = [(self.slots(sp) if sp else 0) | (8 if sp in pool else 0) for sp in range(1024)]
        return bytes(nib[i] | nib[i + 1] << 4 for i in range(0, 1024, 2))


class GenericFusion:
    """The family/rank fusion rule (0x57832c) with the lookup tables the
    fusion object's constructor (0x57a93c) derives from the EKT."""

    def __init__(self, data: RomData):
        self.data = data
        # +0xf0: species by fusion order (later species win ties), 0x401 entries
        # (index 0x400 reads the zeroed word after the table)
        self.by_order = [-1] * 0x400 + [0]
        for sp in range(SPECIES_COUNT):
            if data.order(sp):
                self.by_order[data.order(sp)] = sp
        # +0x8fc: lowest fusion order per rank 0-8 (0x400 if none); [9] = [8]
        self.min_order = [0x400] * 10
        for r in range(9):
            for sp in range(SPECIES_COUNT):
                if data.rank(sp) == r and data.order(sp):
                    self.min_order[r] = min(self.min_order[r], data.order(sp))
        self.min_order[9] = self.min_order[8]
        nr = data.fusion_files["NotRank"]
        self.not_rank = set(struct.unpack(f"<{len(nr) // 2}h", nr[:len(nr) // 2 * 2])) - {-1}
        self.top = struct.unpack("<9H", data.fusion_files["RankTopMons"])

    def rank_class(self, sp: int, flag22: int, plus: int) -> int:
        """0x1cc58c: rank used for the start order; +25 / +50 lift ranks 1-5."""
        if flag22 == 1:
            return 9
        r = self.data.rank(sp)
        lifted = r
        if 1 <= r <= 5:
            lifted = 6 if plus >= 50 else 4 if plus >= 25 else r
        return max(r, lifted)

    def start(self, sp: int, flag22: int = 0, plus: int = 0) -> int:
        """Per-parent start order computed by 0x5790a0 before calling the rule."""
        return max(self.data.order(sp), (self.min_order[self.rank_class(sp, flag22, plus)] - 1) & 0xFFFF)

    def mix(self, fa: int, fb: int) -> int:
        for a, b, r in self.data.mix_family:
            if (a, b) in ((fa, fb), (fb, fa)):
                return r
        return 1

    def next_in_family(self, family: int, after: int) -> int:
        order = self.data.order
        top = self.top[family] if family < len(self.top) else 0
        if order(top) <= after:
            return top
        for o in range(after + 1, 0x401):
            sp = self.by_order[o]
            if sp == -1 or self.data.family(sp) != family or sp in self.not_rank:
                continue
            return sp if order(top) > order(sp) else top
        return -1

    def result(self, a: int, b: int, start_a: int, start_b: int, k: int) -> int:
        """Candidate k (0: A's family, 1: B's family, 2: mixed) of 0x57832c."""
        fam = self.data.family
        fa, fb = fam(a), fam(b)
        if k == 0 and fa == 8:
            return a
        if k == 1 and fb == 8:
            return b
        if k == 2 and 8 in (fa, fb):
            return -1
        if fa == fb:
            if k:
                return -1
            after = max(start_a, start_b)
        else:
            after = max(start_a, start_b) if k < 2 else min(start_a, start_b)
        family = (fa, fb, self.mix(fa, fb))[k] if k < 3 else 0
        return self.next_in_family(family, after)

    def parents(self) -> list[int]:
        """Species that reach the rule: named, with a fusion order, and neither
        Super G (0x1e082c) nor a card suit (0x1eed30), which take other paths."""
        d = self.data
        return [sp for sp in range(1, SPECIES_COUNT)
                if d.names.get(sp) and d.order(sp) and (d.ekt[sp * EKT_RECORD + 9] & 15) // 3 != 3
                and not d.ekt_u16(sp, 8) >> 13 & 1]

    def reachable(self) -> set[int]:
        fam = self.data.family
        starts: dict[int, set[int]] = {}      # family -> start orders of its parents
        for sp in self.parents():
            for plus in (0, 25, 50):
                starts.setdefault(fam(sp), set()).add(self.start(sp, 0, plus))
        every = set().union(*starts.values())
        out = set()
        for fa, sa in starts.items():
            if fa == 8:
                continue
            # candidate 0/1: the parent's own family, after max(start A, start B)
            afters = {max(x, y) for x in sa for y in every}
            out |= {self.next_in_family(fa, x) for x in afters}
            for fb, sb in starts.items():
                if fb in (fa, 8):
                    continue
                afters = {min(x, y) for x in sa for y in sb}
                out |= {self.next_in_family(self.mix(fa, fb), x) for x in afters}
        return out - {-1, 0}


def nibble(table: bytes, sp: int) -> int:
    return table[sp >> 1] >> (4 * (sp & 1)) & 15 if sp < 1024 else 0


def max_pool_slots(table: bytes) -> int:
    return max(nibble(table, sp) & 7 for sp in range(1024) if nibble(table, sp) & 8)


def pick_species(table: bytes, seed: int, domain: int, key: int, original: int) -> int:
    """Uniform pool species by rejection sampling (mirrors pick_species in ARM):
    any size for roaming; for bosses the original's size, or the largest pool
    size when the original is bigger (no 4-slot species is in the pool)."""
    size = nibble(table, original) & 7
    if not size:
        return original
    size = min(size, max_pool_slots(table))
    for ordinal in range(MAX_TRIES):
        cand = roll32(seed, domain, key, ordinal) >> 22
        n = nibble(table, cand)
        if n & 8 and (domain != DOMAIN_BOSS or n & 7 == size):
            return cand
    return original


def fit_party(table: bytes, species: list[int | None]) -> list[bool]:
    """Which enemy positions stay: the leader always, later ones while slots fit
    (mirrors enemy_party_fit). None marks an empty position."""
    used, keep = 0, []
    for i, sp in enumerate(species):
        if sp is None:
            keep.append(False)
            continue
        size = nibble(table, sp) & 7 or 1
        if i and used + size > BATTLE_SLOTS:
            keep.append(False)
            continue
        used += size
        keep.append(True)
    return keep


# Authored roaming-row fields re-proportioned to the replacement species:
# (offset, width, stat-cap index or None, normal limit).
STAT_FIELDS = ((0x32, 2, 0, 9999), (0x34, 2, 1, 9999), (0x36, 2, 2, 999), (0x38, 2, 3, 999),
               (0x3A, 2, 4, 999), (0x3C, 2, 5, 999), (0x3E, 2, 0, 9999))


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def scale(value: int, new: int, old: int, limit: int) -> int:
    """round(value * new / old) in single precision, as scale_core does with VFP;
    at most max(limit, value), at least 1 when value was nonzero."""
    if not value or not old:
        return value
    x = f32(f32(f32(value) * f32(new)) / f32(old))
    x = f32(x + 0.5)
    r = int(x) if x < 2 ** 32 else MASK32
    return min(r, max(limit, value)) or 1


def rescale_row(data: "RomData", row: bytearray, o: int, orig: int, new: int) -> None:
    """EXP, gold and stats of a re-rolled row keep the original monster's
    level-appropriate size but follow the replacement species' proportions."""
    old_exp, old_gold = struct.unpack_from("<II", data.key_monster, orig * 12 + 4)
    new_exp, new_gold = struct.unpack_from("<II", data.key_monster, new * 12 + 4)
    for off, base_new, base_old in ((0x28, new_exp, old_exp), (0x24, new_gold, old_gold)):
        v = struct.unpack_from("<I", row, o + off)[0]
        struct.pack_into("<I", row, o + off, scale(v, base_new, base_old, MASK32))
    old_caps = data.stat_caps(orig)
    new_caps = data.stat_caps(new)
    for off, _, k, limit in STAT_FIELDS:
        v = struct.unpack_from("<H", row, o + off)[0]
        struct.pack_into("<H", row, o + off, scale(v, new_caps[k], old_caps[k], limit))


def shuffle_signatures(seed: int, signatures: list[int]) -> list[int]:
    """Fisher-Yates keyed by position (mirrors skills_shuffle)."""
    a = list(signatures)
    for i in range(len(a) - 1, 0, -1):
        j = roll32(seed, DOMAIN_SKILL, i) * (i + 1) >> 32
        a[i], a[j] = a[j], a[i]
    return a


def shuffle_fusion(seed: int, pool: list[int]) -> tuple[list[int], list[int]]:
    """(map, inverse) as fusion_apply leaves them: u16 per species, 0 = keep.
    Fisher-Yates over the pool in species order, keyed by position."""
    a = list(pool)
    for i in range(len(a) - 1, 0, -1):
        j = roll32(seed, DOMAIN_FUSION, i) * (i + 1) >> 32
        a[i], a[j] = a[j], a[i]
    forward, inverse = [0] * SPECIES_COUNT, [0] * SPECIES_COUNT
    for old, new in zip(pool, a):
        forward[old] = new
        inverse[new] = old
    return forward, inverse


def fuse(forward: list[int], kind: int, species: int) -> int:
    """What the hooked 0x5790a0 returns for an original candidate."""
    if 4 <= kind <= 8 and 0 <= species < SPECIES_COUNT and forward[species]:
        return forward[species]
    return species


def pick_extra(seed: int, key: int, row: bytearray, k: int, pools: tuple[list[int], list[int]]) -> None:
    """Re-roll extra k of a BEPT row within its Boost/Ward tier, never matching
    the row's signature or other extra (mirrors pick_extra)."""
    off = EXTRA_OFFSETS[k]
    value = struct.unpack_from("<H", row, off)[0]
    pool = next((p for p in pools if value in p), None)
    if pool is None:
        return
    avoid = {struct.unpack_from("<H", row, 0x52)[0], struct.unpack_from("<H", row, EXTRA_OFFSETS[1 - k])[0]}
    for ordinal in range(MAX_TRIES):
        cand = pool[roll32(seed, DOMAIN_EXTRA, key, ordinal) * len(pool) >> 32]
        if cand not in avoid:
            struct.pack_into("<H", row, off, cand)
            return


def apply_settings(data: RomData, table: bytes, settings: int) -> tuple[list[int], bytes]:
    """Signature skillset per species and the global BEPT rows after tables_apply."""
    signatures = [data.innate(sp) for sp in range(SPECIES_COUNT)]
    rows = bytearray(data.bept)
    seed, options = settings >> 3, settings & 7
    if options & OPTION_SKILLSETS:
        shuffled = data.shuffle_species()
        for sp, sig in zip(shuffled, shuffle_signatures(seed, [signatures[sp] for sp in shuffled])):
            signatures[sp] = sig
    bosses = data.boss_bept_ids()
    for i in sorted(data.randomized_bept_ids() | bosses):
        domain, option = (DOMAIN_BOSS, OPTION_BOSSES) if i in bosses else (DOMAIN_ROAMING, OPTION_ROAMING)
        if not options & option:
            continue
        o = (i - 1) * BEPT_RECORD
        orig = struct.unpack_from("<H", rows, o)[0]
        sp = pick_species(table, seed, domain, i, orig)
        if sp == orig:
            continue
        struct.pack_into("<H", rows, o, sp)
        struct.pack_into("<H", rows, o + 0x52, signatures[sp])
        for w in (8, 12, 16, 20, 24, 28):
            struct.pack_into("<H", rows, o + w, 0)
        if domain == DOMAIN_ROAMING:
            rescale_row(data, rows, o, orig, sp)   # bosses keep their authored numbers
    if options & (OPTION_ROAMING | OPTION_SKILLSETS | OPTION_BOSSES):
        pools = data.extra_pools()
        for i in range(1, BEPT_COUNT + 1):
            o = (i - 1) * BEPT_RECORD
            row = rows[o:o + BEPT_RECORD]
            if not struct.unpack_from("<H", row, 0x52)[0]:
                continue
            if options & OPTION_SKILLSETS:
                struct.pack_into("<H", row, 0x52, signatures[struct.unpack_from("<H", row, 0)[0]])
                pick_extra(seed, i * 2, row, 0, pools)
                pick_extra(seed, i * 2 + 1, row, 1, pools)
            # A new signature equal to a kept extra would install the same set
            # twice; that extra takes the row's original signature instead.
            sig = struct.unpack_from("<H", row, 0x52)[0]
            pristine = struct.unpack_from("<H", data.bept, o + 0x52)[0]
            if sig != pristine:
                for off in EXTRA_OFFSETS:
                    if struct.unpack_from("<H", row, off)[0] == sig:
                        struct.pack_into("<H", row, off, pristine)
            rows[o:o + BEPT_RECORD] = row
    return signatures, bytes(rows)
