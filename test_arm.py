"""Run the injected ARM routines in Unicorn and compare them with model.py.

    python3.14 test_arm.py --libs C:/ks --libs C:/cs --libs C:/uc
"""
from __future__ import annotations

import argparse
import random
import struct
import sys

import build
import model

SENTINEL = 0x0FFF0000
KEY_MONSTER_AT = 0x78DD64           # loaded at boot; 0x50a1e8 indexes it
STACK_TOP = 0x0FF00000


class Arm:
    def __init__(self, code: bytes):
        import unicorn as uc
        import unicorn.arm_const as a
        self.uc, self.a = uc, a
        self.mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
        size = (len(code) + 0xFFF) & ~0xFFF
        self.mu.mem_map(build.CODE_VA, size)
        self.mu.mem_write(build.CODE_VA, code)                     # data segment covers BSS + STATE
        self.mu.mem_map(STACK_TOP - 0x10000, 0x10000)
        self.mu.mem_map(SENTINEL, 0x1000)
        self.mu.mem_map(0x20000000, 0x200000)                      # scratch heap
        a = self.a                                                  # enable VFP
        self.mu.reg_write(a.UC_ARM_REG_C1_C0_2, self.mu.reg_read(a.UC_ARM_REG_C1_C0_2) | 0xF << 20)
        self.mu.reg_write(a.UC_ARM_REG_FPEXC, 0x40000000)

        def fault(mu, access, addr, size, value, _):
            pc = mu.reg_read(self.a.UC_ARM_REG_PC)
            print(f"fault: access={access} addr={addr:#x} pc={pc:#x}")
            return False
        self.mu.hook_add(uc.UC_HOOK_MEM_INVALID, fault)

    def call(self, addr: int, *args: int, r7: int | None = None) -> int:
        a = self.a
        regs = [a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3]
        for r, v in zip(regs, args):
            self.mu.reg_write(r, v & 0xFFFFFFFF)
        if r7 is not None:
            self.mu.reg_write(a.UC_ARM_REG_R7, r7)
        self.mu.reg_write(a.UC_ARM_REG_SP, STACK_TOP)
        self.mu.reg_write(a.UC_ARM_REG_LR, SENTINEL)
        self.mu.emu_start(addr, SENTINEL, count=10_000_000)
        return self.mu.reg_read(a.UC_ARM_REG_R0)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", default=str(build.DEFAULT_ROM))
    p.add_argument("--libs", action="append", default=[])
    args = p.parse_args()
    sys.path[:0] = args.libs
    from pathlib import Path
    build.rom_tables(Path(args.rom))
    with open(args.rom, "rb") as f:
        f.seek(build.CODE_FILE)
        code = bytearray(f.read(build.CODE_SIZE))
    info = build.patch_code(code)
    sym = info["symbols"]
    cpu = Arm(bytes(code))
    rng = random.Random(1)

    for _ in range(2000):
        s, d, k, o = rng.randrange(1, 8192), rng.randrange(4), rng.randrange(1 << 16), rng.randrange(256)
        assert cpu.call(sym["roll32"], s, d, k, o) == model.roll32(s, d, k, o), (s, d, k, o)
    print("roll32: 2000 cases match")

    table = build.RODATA_TABLES["SPECIES_TABLE"]
    for sp in range(1024):
        n = cpu.call(sym["species_nibble"], sp)
        assert n == table[sp >> 1] >> (4 * (sp & 1)) & 15, sp
    print("species_nibble: all 1024 species match")

    data = model.RomData(Path(args.rom), build.LEGACY, build.TEXT_INDEX)
    rerolled = data.randomized_bept_ids() | data.boss_bept_ids()
    for bid in range(0, model.BEPT_COUNT + 2):
        cpu.call(sym["reroll_bit"], bid)
        z = cpu.mu.reg_read(cpu.a.UC_ARM_REG_CPSR) >> 30 & 1
        assert (not z) == (bid in rerolled), bid
    print(f"reroll_bit: all {model.BEPT_COUNT + 2} ids match ({len(rerolled)} re-rollable)")

    for domain in (model.DOMAIN_ROAMING, model.DOMAIN_BOSS):
        mismatches = 0
        for _ in range(3000):
            s, k, orig = rng.randrange(1, 8192), rng.randrange(1, 3601), rng.randrange(1, 1024)
            got = cpu.call(sym["pick_species"], s, domain, k, orig)
            want = model.pick_species(table, s, domain, k, orig)
            mismatches += got != want
        assert not mismatches, mismatches
        print(f"pick_species domain {domain}: 3000 cases match")

    test_menu_text(cpu, sym)
    test_roaming_apply(cpu, sym, table, Path(args.rom))


def test_menu_text(cpu: Arm, sym: dict) -> None:
    """Options menu labels come from the get_msg hook (msg_menu 4, group 10)."""
    item = build.CONSTANTS["OPT_ITEM"]
    for bits in range(16):
        cpu.mu.mem_write(build.STATE + 2, bytes([bits]))
        for row in range(6):
            ptr = cpu.call(sym["settings_text_lookup"], 4, 10, item + row)
            raw = bytes(cpu.mu.mem_read(ptr, 64))
            raw = raw[:raw.index(b"\xe3\x1b") + 2]
            if row < 4:
                want = f"Random {build.OPTION_NAMES[row]}: {'ON' if bits >> row & 1 else 'OFF'}"
            else:
                want = ("Start Game", "Cancel")[row - 4]
            assert raw == build.encode_text(want), (bits, row, raw)
    cpu.mu.mem_write(build.STATE + 2, b"\0")
    print("options menu labels: 6 rows x 16 option states match")


HEAP = 0x20000000
EKT_AT = HEAP
BEPT_AT = HEAP + 0x40000            # BEPT file image (8-byte header + rows)
OBJ_AT = HEAP + 0xA0000             # fake file-buffer object chain for 0x1c2dfc
AREA_AT = HEAP + 0xA1000
ROWS_AT = HEAP + 0xA2000
SINGLES_AT = HEAP + 0xB0000


def fake_tables(cpu: Arm, data: model.RomData) -> None:
    """Mirror the game's EKT pointer and the BEPT file-buffer handle chain."""
    mu = cpu.mu
    mu.mem_write(EKT_AT, data.ekt)
    mu.mem_write(KEY_MONSTER_AT, data.key_monster)
    mu.mem_write(0x6FD108 + 4, struct.pack("<I", EKT_AT))
    mu.mem_write(BEPT_AT, b"BEPT" + struct.pack("<I", model.BEPT_COUNT) + data.bept)
    h, o, vt, stub = OBJ_AT, OBJ_AT + 0x20, OBJ_AT + 0x40, OBJ_AT + 0x80
    mu.mem_write(0x6FA658, struct.pack("<I", h))
    mu.mem_write(h + 8, struct.pack("<I", o))
    mu.mem_write(o, struct.pack("<I", vt))
    mu.mem_write(vt + 0x10, struct.pack("<I", stub))
    mu.mem_write(stub, struct.pack("<III", 0xE59F0000, 0xE12FFF1E, BEPT_AT))  # ldr r0,[pc]; bx lr


def global_rows(cpu: Arm) -> bytes:
    return bytes(cpu.mu.mem_read(BEPT_AT + 8, model.BEPT_COUNT * 96))


def test_roaming_apply(cpu: Arm, sym: dict, table: bytes, rom) -> None:
    data = model.RomData(rom, build.LEGACY, build.TEXT_INDEX)
    fake_tables(cpu, data)
    pristine = data.bept
    rerolled = data.randomized_bept_ids()
    bosses = data.boss_bept_ids()
    assert not {2201, 2202, 2203} & (rerolled | bosses) and {2201, 2202, 2203} <= data.roaming_bept_ids
    assert {2101, 2182, 2183, 2191} <= bosses and not rerolled & bosses

    def settings(seed, opts):
        cpu.mu.mem_write(build.STATE, struct.pack("<H", seed << 3 | opts if opts else 0))
        cpu.call(sym["tables_apply"])
        return global_rows(cpu)

    def signatures():
        ekt = bytes(cpu.mu.mem_read(EKT_AT, len(data.ekt)))
        return [struct.unpack_from("<H", ekt, sp * model.EKT_RECORD + 0x66)[0]
                for sp in range(model.SPECIES_COUNT)]

    vanilla = [data.innate(sp) for sp in range(model.SPECIES_COUNT)]
    assert settings(0, 0) == pristine and signatures() == vanilla
    print("tables_apply off: global BEPT and signatures untouched")
    R, S, B = model.OPTION_ROAMING, model.OPTION_SKILLSETS, model.OPTION_BOSSES
    for opts in (R, S, R | S, B, R | B, S | B, R | S | B):
        for seed in (1990, 77, 4321):
            rows = settings(seed, opts)
            want_sig, want_rows = model.apply_settings(data, table, seed << 3 | opts)
            assert signatures() == want_sig, (opts, seed)
            bad = [i for i in range(1, model.BEPT_COUNT + 1)
                   if rows[(i - 1) * 96:i * 96] != want_rows[(i - 1) * 96:i * 96]]
            assert not bad, (opts, seed, bad[:10])
            check_rows(data, table, pristine, rows, want_sig, seed, opts)
            assert settings(0, 0) == pristine and signatures() == vanilla
        print(f"tables_apply options {opts}: 3 seeds match model.apply_settings; off restores pristine")
    rerolled_seed = 1990

    # Loader hook: local rows are copies of the (randomized) global ones.
    import gzip
    from romtool import Cartridge, read_at
    from xbbtool import parse_xbb
    cart = Cartridge(rom)
    f = next(x for x in cart.romfs(0).files() if x.path.endswith("Encount_ADA01.xbb.gz"))
    xbb = gzip.decompress(read_at(cart.stream, f.offset, f.size))
    single = next(m for m in parse_xbb(xbb) if m["name"] == "SingleMonster.bin")
    singles = xbb[single["offset"]:single["offset"] + single["size"]]
    rows = settings(rerolled_seed, model.OPTION_ROAMING)
    bids = sorted({struct.unpack_from("<H", singles, i + 2)[0] for i in range(0, len(singles), 80)})
    local = b"".join(struct.pack("<I", i) + rows[(i - 1) * 96:i * 96] for i in bids)
    cpu.mu.mem_write(ROWS_AT, local)
    cpu.mu.mem_write(SINGLES_AT, singles)
    vec = bytearray(0x40)
    struct.pack_into("<II", vec, 0x1C, SINGLES_AT, SINGLES_AT + len(singles))
    struct.pack_into("<II", vec, 0x28, ROWS_AT, ROWS_AT + len(local))
    cpu.mu.mem_write(AREA_AT, bytes(vec))
    cpu.call(sym["roaming_apply"], r7=AREA_AT)
    got = cpu.mu.mem_read(SINGLES_AT, len(singles))
    names = []
    for o in range(0, len(singles), 80):
        bid, sp = struct.unpack_from("<HH", got, o + 2)
        assert sp == struct.unpack_from("<H", rows, (bid - 1) * 96)[0], (o, bid, sp)
        names.append(data.names.get(sp))
    print(f"roaming_apply: field symbols follow their rows -> {names}")

    test_keylist(cpu, sym, data)
    test_enemy_party_fit(cpu, sym, table, data)


KEY_AT = HEAP + 0xC8000
LIST_OBJ = HEAP + 0xC9000
FILE_AT = HEAP + 0xCA000
VEC_AT = HEAP + 0xCB000


def test_keylist(cpu: Arm, sym: dict, data: model.RomData) -> None:
    """Key screen pages: run the game's own loop (0x2150fc..0x2151bc) of
    0x214f58 through both hooks and compare the vector with the model."""
    a = cpu.a
    ids = data.key_world_ids()
    assert [len(x) for x in ids] == [4, 43, 67, 73, 65, 6, 55, 0], [len(x) for x in ids]
    checked = 0
    for opts in (model.OPTION_ROAMING, 0, model.OPTION_BOSSES | model.OPTION_SKILLSETS,
                 model.OPTION_ROAMING | model.OPTION_BOSSES):
        for seed in (1990, 6673, 8191):
            settings = seed << 3 | opts
            cpu.mu.mem_write(build.STATE, struct.pack("<H", settings))
            cpu.call(sym["tables_apply"])
            rows = global_rows(cpu)
            for world in range(len(model.KEY_WORLDS)):
                cpu.mu.mem_write(KEY_AT, bytes(0x10) + bytes([world]))
                cpu.mu.reg_write(a.UC_ARM_REG_R4, KEY_AT)
                cpu.call(sym["keylist_world"])
                assert cpu.mu.reg_read(a.UC_ARM_REG_R4) == world
                listed = data.world_lists[world]
                cpu.mu.mem_write(FILE_AT, struct.pack(f"<{len(listed)}H", *listed))
                obj = bytearray(0x100)
                struct.pack_into("<III", obj, 0x6C, VEC_AT, VEC_AT, VEC_AT + 0x200)   # no regrowth
                cpu.mu.mem_write(LIST_OBJ, bytes(obj))
                for r, v in ((a.UC_ARM_REG_R4, 0x1234), (a.UC_ARM_REG_R5, LIST_OBJ),
                             (a.UC_ARM_REG_R6, len(listed)), (a.UC_ARM_REG_R7, FILE_AT),
                             (a.UC_ARM_REG_R8, 0), (a.UC_ARM_REG_SP, CALLER_SP)):
                    cpu.mu.reg_write(r, v)
                cpu.mu.emu_start(0x2150FC, 0x2151BC, count=1_000_000)
                assert cpu.mu.reg_read(a.UC_ARM_REG_PC) == 0x2151BC
                assert cpu.mu.reg_read(a.UC_ARM_REG_R5) == LIST_OBJ and cpu.mu.reg_read(a.UC_ARM_REG_R8) == 0
                assert cpu.mu.reg_read(a.UC_ARM_REG_SP) == CALLER_SP
                begin, end = struct.unpack("<II", cpu.mu.mem_read(LIST_OBJ + 0x6C, 8))
                got = list(struct.unpack(f"<{(end - begin) // 2}h", cpu.mu.mem_read(begin, end - begin)))
                want = data.key_list_species(world, rows, settings)
                assert got == [x for x in want if x != model.KEY_LIST_DEFAULT], (opts, seed, world, got, want)
                assert len(got) <= 80, (world, len(got))      # 4 pages x 20 rows
                if not opts & model.OPTION_ROAMING:
                    assert got == [x for x in dict.fromkeys(listed) if x and data.order(x)], world
                checked += 1
    cpu.mu.mem_write(build.STATE, struct.pack("<H", 6673 << 3 | model.OPTION_ROAMING))
    cpu.call(sym["tables_apply"])
    desert = data.key_list_species(1, global_rows(cpu), 6673 << 3 | model.OPTION_ROAMING)
    print(f"keylist hooks: {checked} world lists match model.key_list_species; "
          f"seed 6673 Desert -> {len(desert)} species, e.g. {[data.names.get(s) for s in desert[:6]]}")
    cpu.mu.mem_write(build.STATE, struct.pack("<H", 1990 << 3 | model.OPTION_ROAMING))
    cpu.call(sym["tables_apply"])           # the state test_enemy_party_fit expects


def check_rows(data, table, pristine, rows, sig, seed, opts) -> None:
    """Rule checks that do not rely on apply_settings agreeing with itself."""
    rerolled = data.randomized_bept_ids()
    bosses = data.boss_bept_ids()
    top = model.max_pool_slots(table)
    regular, uber = data.extra_pools()
    shuffled = data.shuffle_species()
    assert sorted(sig[sp] for sp in shuffled) == sorted(data.innate(sp) for sp in shuffled)
    for i in range(1, model.BEPT_COUNT + 1):
        got, orig = rows[(i - 1) * 96:i * 96], pristine[(i - 1) * 96:i * 96]
        if i in bosses and opts & model.OPTION_BOSSES:
            old, new = struct.unpack_from("<H", orig, 0)[0], struct.unpack_from("<H", got, 0)[0]
            if new == old:
                assert got[:0x52] == orig[:0x52] and got[0x58:] == orig[0x58:], i
            else:              # same size (capped), from the pool; level/stats/EXP/gold kept
                ai = (8, 12, 16, 20, 24, 28)
                assert model.nibble(table, new) & 8, (i, new)
                assert model.nibble(table, new) & 7 == min(model.nibble(table, old) & 7, top), (i, old, new)
                assert all(struct.unpack_from("<H", got, w)[0] == 0 for w in ai), i
                keep = [k for k in range(2, 0x52) if not any(w <= k < w + 2 for w in ai)]
                assert all(got[k] == orig[k] for k in keep + list(range(0x58, 96))), i
        elif not opts & model.OPTION_ROAMING or i not in rerolled:
            assert got[:0x52] == orig[:0x52] and got[0x58:] == orig[0x58:], i
        elif struct.unpack_from("<H", got, 0)[0] != struct.unpack_from("<H", orig, 0)[0]:
            old, new = struct.unpack_from("<H", orig, 0)[0], struct.unpack_from("<H", got, 0)[0]
            km = lambda sp, k: struct.unpack_from("<I", data.key_monster, sp * 12 + 4 + 4 * k)[0]
            fields = [(0x28, "<I", km(new, 0), km(old, 0), model.MASK32),
                      (0x24, "<I", km(new, 1), km(old, 1), model.MASK32)]
            fields += [(off, "<H", data.stat_caps(new)[k], data.stat_caps(old)[k], limit)
                       for off, _, k, limit in model.STAT_FIELDS]
            for off, fmt, nb, ob, limit in fields:
                v, w = struct.unpack_from(fmt, orig, off)[0], struct.unpack_from(fmt, got, off)[0]
                if not v or not ob:
                    assert w == v, (i, hex(off))
                    continue
                exact = min(v * nb / ob, max(limit, v))
                assert abs(w - max(exact, 1)) <= 1 + exact * 1e-6, (i, hex(off), v, w, exact)
        sp = struct.unpack_from("<H", got, 0)[0]
        s52, e1, e2 = struct.unpack_from("<3H", got, 0x52)
        o52, o1, o2 = struct.unpack_from("<3H", orig, 0x52)
        if not o52:
            assert got == orig
            continue
        assert s52 == sig[sp] and len({s52, e1, e2} - {0}) == 3 - (not e1) - (not e2), (i, s52, e1, e2)
        assert bool(e1) == bool(o1) and bool(e2) == bool(o2)
        for new, old in ((e1, o1), (e2, o2)):
            for pool in (regular, uber):
                if old in pool and opts & model.OPTION_SKILLSETS:
                    assert new in pool, (i, old, new)
            if not opts & model.OPTION_SKILLSETS or not any(old in p for p in (regular, uber)):
                assert new in (old, o52), (i, old, new)


SLOTS_AT = HEAP + 0xC0000
CALLER_SP = STACK_TOP - 0x100


def test_enemy_party_fit(cpu: Arm, sym: dict, table: bytes, data: model.RomData) -> None:
    """Call through the hook site's convention; 0x1d2d50 is stubbed to record its args."""
    a = cpu.a
    stub = HEAP + 0xD0000
    cpu.mu.mem_write(stub, struct.pack("<I", 0xE12FFF1E))              # bx lr
    code = bytearray(cpu.mu.mem_read(0x1D2D50, 8))
    cpu.mu.mem_write(0x1D2D50, struct.pack("<II", 0xE51FF004, stub))   # ldr pc,[pc,#-4]; .word stub
    rows = global_rows(cpu)
    by_size = {}
    for i in sorted(data.randomized_bept_ids()):
        by_size.setdefault(model.nibble(table, struct.unpack_from("<H", rows, (i - 1) * 96)[0]) & 7, i)
    rng = random.Random(7)
    choices = list(by_size.values()) + [-1, 0]
    checked = trimmed = 0
    for opts in (model.OPTION_ROAMING, 0):
        cpu.mu.mem_write(build.STATE, struct.pack("<H", 1990 << 3 | opts))
        for _ in range(300):
            ids = [rng.choice(choices[:-2])] + [rng.choice(choices) for _ in range(3)]
            slots = bytearray(4 * 0x340)
            for k, v in enumerate(ids):
                struct.pack_into("<i", slots, k * 0x340, v)
            cpu.mu.mem_write(SLOTS_AT, bytes(slots))
            cpu.mu.mem_write(CALLER_SP + 0x10, struct.pack("<4i", *ids))
            for r, v in zip((a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3), ids):
                cpu.mu.reg_write(r, v & 0xFFFFFFFF)
            cpu.mu.reg_write(a.UC_ARM_REG_R4, SLOTS_AT)
            cpu.mu.reg_write(a.UC_ARM_REG_SP, CALLER_SP)
            cpu.mu.reg_write(a.UC_ARM_REG_LR, SENTINEL)
            cpu.mu.emu_start(sym["enemy_party_fit"], SENTINEL, count=1_000_000)
            args = [cpu.mu.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)]
            args = [x - (1 << 32) if x >= 1 << 31 else x for x in args]
            species = [struct.unpack_from("<H", rows, (v - 1) * 96)[0] if v > 0 else None for v in ids]
            keep = model.fit_party(table, species) if opts else [v > 0 for v in ids]
            want = [v if k else (v if v <= 0 else -1) for v, k in zip(ids, keep)]
            assert args == want, (opts, ids, args, want)
            assert list(struct.unpack("<4i", cpu.mu.mem_read(CALLER_SP + 0x10, 16))) == want
            assert [struct.unpack_from("<i", cpu.mu.mem_read(SLOTS_AT + k * 0x340, 4))[0] for k in range(4)] == want
            assert cpu.mu.reg_read(a.UC_ARM_REG_R4) == SLOTS_AT and cpu.mu.reg_read(a.UC_ARM_REG_SP) == CALLER_SP
            used = sum(model.nibble(table, s) & 7 for s, v in zip(species, want) if v > 0)
            assert not opts or used <= model.BATTLE_SLOTS or sum(v > 0 for v in want) == 1
            trimmed += want != ids
            checked += 1
    cpu.mu.mem_write(0x1D2D50, bytes(code))
    print(f"enemy_party_fit: {checked} parties match model.fit_party ({trimmed} trimmed); off = untouched")

    test_fusion(cpu, sym, data)


FUSION_OBJ = HEAP + 0xE0000
STUB_AT = HEAP + 0xF0000


def call_stack(cpu: Arm, addr: int, regs: list[int], stack: list[int], keep=(4, 12)) -> int:
    """Call with stack arguments; asserts sp and r4-r11 survive."""
    a = cpu.a
    rr = [getattr(a, f"UC_ARM_REG_R{i}") for i in range(13)]
    for r, v in zip(rr, regs):
        cpu.mu.reg_write(r, v & 0xFFFFFFFF)
    marks = {i: 0x1000 + i for i in range(*keep)}
    for i, v in marks.items():
        cpu.mu.reg_write(rr[i], v)
    cpu.mu.mem_write(CALLER_SP, struct.pack(f"<{len(stack)}I", *(v & 0xFFFFFFFF for v in stack)))
    cpu.mu.reg_write(a.UC_ARM_REG_SP, CALLER_SP)
    cpu.mu.reg_write(a.UC_ARM_REG_LR, SENTINEL)
    cpu.mu.emu_start(addr, SENTINEL, count=5_000_000)
    assert cpu.mu.reg_read(a.UC_ARM_REG_SP) == CALLER_SP
    assert all(cpu.mu.reg_read(rr[i]) == v for i, v in marks.items())
    r0 = cpu.mu.reg_read(a.UC_ARM_REG_R0)
    return r0 - (1 << 32) if r0 >= 1 << 31 else r0


def patch(cpu: Arm, va: int, words: list[int]) -> bytes:
    old = bytes(cpu.mu.mem_read(va, 4 * len(words)))
    cpu.mu.mem_write(va, struct.pack(f"<{len(words)}I", *words))
    return old


def test_fusion(cpu: Arm, sym: dict, data: model.RomData) -> None:
    # 1. The family/rank rule model against the game's own 0x57832c.
    g = data.fusion_engine()
    obj = bytearray(0x900)
    nr, top = FUSION_OBJ + 0x1000, FUSION_OBJ + 0x2000
    struct.pack_into("<II", obj, 0x10, nr, top)
    struct.pack_into(f"<{len(g.by_order)}h", obj, 0xF0, *g.by_order)
    cpu.mu.mem_write(FUSION_OBJ, bytes(obj))
    cpu.mu.mem_write(nr, data.fusion_files["NotRank"])
    cpu.mu.mem_write(top, data.fusion_files["RankTopMons"])
    parents = g.parents() + [sp for sp in range(1, 1024) if data.family(sp) == 8 and data.order(sp)][:40]
    rng = random.Random(11)
    for _ in range(4000):
        a, b = rng.choice(parents), rng.choice(parents)
        sa = g.start(a, 0, rng.choice((0, 0, 25, 50)))
        sb = g.start(b, 0, rng.choice((0, 0, 25, 50)))
        count, k = rng.randrange(3), rng.randrange(3)
        got = call_stack(cpu, 0x57832C, [FUSION_OBJ, a, b, sa], [sb, count + k, count])
        assert got == g.result(a, b, sa, sb, k), (a, b, sa, sb, k, got)
    print("0x57832c (family/rank rule): 4000 parent pairs match model.GenericFusion")

    pool = data.fusion_pool()
    assert data.recipe_results() <= set(pool) and set(model.SUIT_RESULTS) <= set(pool)
    bits = bytes(cpu.mu.mem_read(build.CONSTANTS["FUSION_BITMAP_VA"], 128))
    assert bits == data.fusion_bitmap()

    # 2. tables_apply builds the permutation (seed from +0, flag at STATE_FUSION).
    maps = build.STATE + build.STATE_FUSION_MAP_OFFSET

    def apply(settings, fusion):
        cpu.mu.mem_write(build.STATE, struct.pack("<H", settings))
        cpu.mu.mem_write(build.STATE + 5, bytes([fusion]))
        cpu.call(sym["tables_apply"])
        raw = bytes(cpu.mu.mem_read(maps, 4 * model.SPECIES_COUNT))
        return (list(struct.unpack("<1024H", raw[:2048])), list(struct.unpack("<1024H", raw[2048:])))

    zero = [0] * model.SPECIES_COUNT
    for settings in (1990 << 3 | model.OPTION_ROAMING, 77 << 3, 4321 << 3 | 7, 1 << 3, 8191 << 3 | 2):
        fwd, inv = apply(settings, 1)
        want = model.shuffle_fusion(settings >> 3, pool)
        assert (fwd, inv) == want, settings
        assert sorted(fwd[sp] for sp in pool) == pool and all(fwd[sp] == 0 for sp in range(1024) if sp not in pool)
        assert all(inv[fwd[sp]] == sp for sp in pool)
        moved = sum(fwd[sp] != sp for sp in pool)
        assert moved > len(pool) * 0.9, moved
        assert apply(settings, 0) == (zero, zero)
    print(f"tables_apply fusions: 5 seeds match model.shuffle_fusion over {len(pool)} species; off clears")
    fwd, inv = apply(1990 << 3, 1)

    # 3. Hooks. 0x5790a0's body is stubbed to "type = r3, return r2" with its
    # real epilogue; the reverse lookups' bodies to "return r1".
    body = patch(cpu, 0x5790A4, [0xE59D4034,   # ldr r4,[sp,#0x34]  (type pointer arg)
                                 0xE5C43000,   # strb r3,[r4]
                                 0xE1A00002,   # mov r0,r2
                                 0xE28DD010,   # add sp,sp,#0x10
                                 0xE8BD8FF0])  # pop {r4-r11,pc}
    type_at = STUB_AT
    cases = 0
    for kind in range(1, 10):
        for sp in rng.sample(range(1024), 60) + [-1, 0, 336, 797]:
            got = call_stack(cpu, 0x5790A0, [FUSION_OBJ, 0, sp, kind], [type_at, 0, 0])
            assert got == model.fuse(fwd, kind, sp), (kind, sp, got)
            assert cpu.mu.mem_read(type_at, 1)[0] == kind
            cases += 1
    cpu.mu.mem_write(0x5790A4, body)
    print(f"fusion_candidate: {cases} candidates match model.fuse (types 4-8 remapped)")

    reverse = {0x578900: [0xE1A00001, 0xE12FFF1E],                 # mov r0,r1; bx lr
               0x579E68: [0xE1A00001, 0xE12FFF1E],
               0x579FC0: [0xE1A00001, 0xE8BD9FF0],                 # pop {r4-r12,pc}
               0x57A0CC: [0xE1A00001, 0xE28DD010, 0xE8BD8FF0],     # add sp,#0x10; pop {r4-r11,pc}
               0x57A490: [0xE1A00001, 0xE28DD010, 0xE8BD8FF0]}
    for va, words in reverse.items():
        old = patch(cpu, va + 4, words)
        for sp in rng.sample(range(1024), 80) + [-1, 0x400]:
            got = call_stack(cpu, va, [FUSION_OBJ, sp, 0, 0], [0, 0, 0])
            want = inv[sp] if 0 <= sp < 1024 and inv[sp] else sp
            assert got == want, (hex(va), sp, got, want)
        cpu.mu.mem_write(va + 4, old)
    print("reverse lookups: all five search for the inverse target")

    # 4. Save header: SAVE_MAGIC (older saves) = fusions off, +1 = on.
    image = HEAP + 0x100000
    magic = build.CONSTANTS["SAVE_MAGIC"]
    for header, want in ((magic, (1990 << 3 | 1, 0)), (magic + 1, (1990 << 3 | 1, 1)),
                         (magic + 2, (0, 0)), (magic - 1, (0, 0)), (0, (0, 0))):
        hdr = bytearray(0x100)
        struct.pack_into("<H", hdr, 0xA8, header)
        struct.pack_into("<H", hdr, 0xAE, 1990 << 3 | 1)
        cpu.mu.mem_write(image, bytes(hdr))
        cpu.mu.mem_write(build.STATE + 5, b"\x07")
        cpu.call(sym["settings_load"], image)
        assert cpu.mu.reg_read(cpu.a.UC_ARM_REG_R4) == image + 0xD0
        st = cpu.mu.mem_read(build.STATE, 6)
        got = (struct.unpack_from("<H", st)[0], st[5])
        assert got == want, (hex(header), got, want)
        fwd, _ = apply(*got)
        assert any(fwd) == bool(want[1])
        out = HEAP + 0x101000
        cpu.mu.mem_write(out, bytes(0x100))
        cpu.mu.reg_write(cpu.a.UC_ARM_REG_R6, out)
        cpu.call(sym["settings_save"], r7=0x1234)
        saved = cpu.mu.mem_read(out, 0x100)
        assert struct.unpack_from("<HH", saved, 0xA8)[0] == magic + want[1]
        assert struct.unpack_from("<H", saved, 0xAE)[0] == want[0]
        assert cpu.mu.reg_read(cpu.a.UC_ARM_REG_R1) == 0x1234
    print("settings_load/save: old magic = fusions off, magic + 1 = on, others = randomizer off")
    apply(0, 0)


if __name__ == "__main__":
    main()
