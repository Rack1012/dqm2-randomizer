"""Build the DQM2 per-save randomizer ROM from the untouched translated image.

The source .3ds is only read. The output is a copy whose ExeFS .code carries
the injected ARM code (in the unused text-segment padding) and guarded hook
branches; ExHeader, ExeFS and NCCH hashes are recomputed.

Requires Keystone (assembler) and Capstone (verification); pass their
install directories with --libs if they are not importable.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import struct
import sys
from pathlib import Path

import model

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DEFAULT_ROM = PROJECT / ("Dragon Quest Monsters 2 - Cobi and Tara's Marvelous Mysterious Key "
                         "(Japan) [T-En by Dackst & Ich73 v1.2] [n].3ds")
SOURCE_SHA256 = "b21d42b7fe643b72787bad18e1768a12b42173e6b4cbf571e3e84baa2575ce70"

# Cartridge layout of the supplied image (verified against the headers below).
NCCH = 0x4000
EXHEADER = NCCH + 0x200
EXEFS = 0x6C00
CODE_FILE = EXEFS + 0x200
CODE_SIZE = 0x62B000
CODE_VA = 0x100000

# Injected code lives in the text segment's page padding.
INJECT_VA = 0x6600BC
INJECT_END = 0x661000

# Lookup tables live in the read-only data segment's page padding; the code
# loads their addresses (<NAME>_VA constants).
RODATA_VA = 0x6E9CB0
RODATA_END = 0x6EA000
RODATA_TABLES: dict[str, bytes] = {}

# Runtime state appended to BSS (original BSS ends exactly at 0x7bd300).
DATA_VA = 0x6EA000
BSS_START = 0x72A4F0
BSS_ORIGINAL_END = 0x7BD300
STATE = 0x7BD300

# More tables go right after STATE. The data segment is extended over the old
# BSS and STATE (stored as zeros in .code) so these load from the file; BSS
# becomes empty. The ExeFS grows, so everything after .code in the ROM shifts.
EXT_TABLES: dict[str, bytes] = {}
# Pristine copies of everything tables_apply rewrites, then scratch.
STATE_TEXT_OFFSET = 0x10                                                # options menu label (<= 0x30 B)
STATE_EKT_BACKUP_OFFSET = 0x40                                          # u16 signature per species
STATE_SKILL_BACKUP_OFFSET = STATE_EKT_BACKUP_OFFSET + 2 * model.SPECIES_COUNT  # BEPT +0x52..+0x57 per row
STATE_SHUFFLE_OFFSET = STATE_SKILL_BACKUP_OFFSET + 6 * model.BEPT_COUNT        # skills_shuffle scratch
STATE_FUSION_MAP_OFFSET = STATE_SHUFFLE_OFFSET + 2 * model.SPECIES_COUNT        # u16 map, then inverse
STATE_BACKUP_OFFSET = STATE_FUSION_MAP_OFFSET + 4 * model.SPECIES_COUNT         # whole re-rollable rows
STATE_SIZE = STATE_BACKUP_OFFSET  # grows by 96 bytes per backed-up row (rom_tables)

MODULES = ["settings.s", "roaming.s", "skills.s", "fusion.s"]
LEGACY = HERE / "legacy"          # recovered romtool/xbbtool bytecode
TEXT_INDEX = PROJECT / "analysis" / "text-index.jsonl"


def encode_text(s: str) -> bytes:
    """Encode ASCII menu text in the game's character set (E3 1B terminated)."""
    out = bytearray()
    for ch in s:
        if "A" <= ch <= "Z":
            out.append(0x0D + ord(ch) - ord("A"))
        elif "a" <= ch <= "z":
            out.append(0x27 + ord(ch) - ord("a"))
        elif ch == " ":
            out.append(0x0B)
        elif ch == "?":
            out += b"\xe1\x08"
        elif ch == ".":
            out += b"\xe1\x3b"
        elif ch == ":":
            out += b"\xe1\x3e"
        elif ch == "\n":
            out += b"\xe3\x15"
        else:
            raise ValueError(f"no encoding for {ch!r}")
    return bytes(out + b"\xe3\x1b")


def encode_piece(s: str) -> bytes:
    """Game-encoded text without the end-of-message code (label pieces)."""
    return encode_text(s)[:-2]


def byte_list(b: bytes) -> str:
    return ", ".join(f"0x{x:02x}" for x in b)


# Options menu rows, in option-bit order (1 roaming, 2 skills, 4 bosses, 8 fusions).
OPTION_NAMES = ("Roaming Monsters", "Skillsets", "Bosses", "Fusions")

CONSTANTS = {
    "STATE": STATE,
    "STATE_BACKED_UP": 4,
    "STATE_FUSION": 5,
    "STATE_KEY_WORLD": 6,
    "KEY_WORLDS": len(model.KEY_WORLDS),
    "STATE_FUSION_LR": 8,
    "STATE_FUSION_TYPE": 12,
    "STATE_TEXT": STATE + STATE_TEXT_OFFSET,
    "STATE_FUSION_MAP": STATE + STATE_FUSION_MAP_OFFSET,
    "STATE_BACKUP": STATE + STATE_BACKUP_OFFSET,
    "STATE_EKT_BACKUP": STATE + STATE_EKT_BACKUP_OFFSET,
    "STATE_SKILL_BACKUP": STATE + STATE_SKILL_BACKUP_OFFSET,
    "STATE_SHUFFLE": STATE + STATE_SHUFFLE_OFFSET,
    "BEPT_COUNT": model.BEPT_COUNT,
    "SPECIES_COUNT": model.SPECIES_COUNT,
    "BATTLE_SLOTS": model.BATTLE_SLOTS,
    "OPT_ROAMING": model.OPTION_ROAMING,
    "OPT_SKILLSETS": model.OPTION_SKILLSETS,
    "OPT_BOSSES": model.OPTION_BOSSES,
    "OPT_FUSION": model.OPTION_FUSION,
    "DOMAIN_ROAMING": model.DOMAIN_ROAMING,
    "DOMAIN_BOSS": model.DOMAIN_BOSS,
    "DOMAIN_SKILL": model.DOMAIN_SKILL,
    "DOMAIN_EXTRA": model.DOMAIN_EXTRA,
    "DOMAIN_FUSION": model.DOMAIN_FUSION,
    "MAX_TRIES": model.MAX_TRIES,
    "SAVE_MAGIC": 0x5A52,
    # msg_menu group 10 ends at item 22; items 23-28 are the options menu rows:
    # the four options (bit n = row n), Start Game, Cancel.
    "OPT_ITEM": 23,
}

# MENU_TEXT pieces, in order: settings_text_lookup relies on "Random " being
# followed by the names and ": ON" by ": OFF".
MENU_TEXT = (
    ("START", encode_text("Start Game")),
    ("CANCEL", encode_text("Cancel")),
    ("RANDOM", encode_piece("Random ") + b"\0"),
    ("NAMES", b"".join(encode_piece(n) + b"\0" for n in OPTION_NAMES)),
    ("ON", encode_piece(": ON") + b"\0"),
    ("OFF", encode_piece(": OFF") + b"\0"),
)

# (address, original instruction word, "b"/"bl", label)
HOOKS = [
    (0x21F188, 0xE5C4505A, "b", "settings_start_nosave"),    # strb r5,[r4,#0x5a]
    (0x21EC60, 0xE3A01002, "b", "settings_start_warning"),   # mov r1,#2
    (0x21F0E4, 0xE92D4070, "b", "settings_select"),          # push {r4-r6,lr}
    (0x26C8B8, 0xE28040D0, "bl", "settings_load"),           # add r4,r0,#0xd0
    (0x26CBE8, 0xE1A01007, "bl", "settings_save"),           # mov r1,r7
    (0x1E1120, 0xE59F3010, "b", "settings_text_lookup"),     # ldr r3,[pc,#0x10]
    (0x2A3C58, 0xE2870044, "bl", "roaming_apply"),           # add r0,r7,#0x44 (dead)
    (0x1F725C, 0xEBFF6EBB, "bl", "enemy_party_fit"),         # bl 0x1d2d50
    (0x2150AC, 0xE5D44010, "bl", "keylist_world"),           # ldrb r4,[r4,#0x10]
    (0x2150FC, 0xE3560000, "bl", "keylist_species"),         # cmp r6,#0
    (0x5790A0, 0xE92D4FFF, "b", "fusion_candidate"),         # push {r0-r11,lr}
    (0x578900, 0xE1A0C000, "b", "fusion_rev_kind"),          # mov ip,r0
    (0x579E68, 0xE1A0C000, "b", "fusion_rev_kind_type"),     # mov ip,r0
    (0x579FC0, 0xE92D5FF0, "b", "fusion_rev_rank_a"),        # push {r4-r12,lr}
    (0x57A0CC, 0xE92D4FFF, "b", "fusion_rev_rank_b"),        # push {r0-r11,lr}
    (0x57A490, 0xE92D4FFF, "b", "fusion_rev_rank_c"),        # push {r0-r11,lr}
]


def rom_tables(rom: Path) -> None:
    """Derive the data tables embedded in the injection from the source ROM."""
    global STATE_SIZE
    data = model.RomData(rom, LEGACY, TEXT_INDEX)
    RODATA_TABLES.clear()
    # stat_fields: u8 row offset, u8 cap index * 2, u16 limit; zero entry ends
    RODATA_TABLES["STAT_FIELDS"] = b"".join(struct.pack("<BBH", off, 2 * k, limit)
                                            for off, _, k, limit in model.STAT_FIELDS) + bytes(4)
    RODATA_TABLES["SPECIES_TABLE"] = data.species_table()
    CONSTANTS["MAX_POOL_SLOTS"] = model.max_pool_slots(RODATA_TABLES["SPECIES_TABLE"])
    RODATA_TABLES["SHUFFLE_BITMAP"] = data.shuffle_bitmap()
    for name, pool in zip(("REGULAR", "UBER"), data.extra_pools()):
        RODATA_TABLES[f"POOL_{name}"] = struct.pack(f"<{len(pool)}H", *pool)
        CONSTANTS[f"POOL_{name}_COUNT"] = len(pool)
    va = RODATA_VA
    for name, blob in RODATA_TABLES.items():
        CONSTANTS[f"{name}_VA"] = va
        va = (va + len(blob) + 3) & ~3
    if va > RODATA_END:
        raise SystemExit(f"rodata tables need {va - RODATA_VA:#x} bytes; only "
                         f"{RODATA_END - RODATA_VA:#x} bytes of padding are available")
    rows = data.randomized_bept_ids() | data.boss_bept_ids()
    STATE_SIZE = (STATE_BACKUP_OFFSET + 96 * len(rows) + 0xFF) & ~0xFF

    EXT_TABLES.clear()
    # reroll_bit range-checks against 0x1000 (an ARM immediate), so pad to it
    assert model.BEPT_COUNT < 0x1000
    EXT_TABLES["REROLL_BITMAP"] = data.reroll_bitmap().ljust(0x200, b"\0")
    first, bits = data.boss_bitmap()
    CONSTANTS["BOSS_FIRST"] = first
    CONSTANTS["BOSS_SPAN"] = 8 * len(bits)
    EXT_TABLES["BOSS_BITMAP"] = bits
    EXT_TABLES["FUSION_BITMAP"] = data.fusion_bitmap()
    EXT_TABLES["MENU_TEXT"] = b"".join(piece for _, piece in MENU_TEXT)
    # Key screen monster pages: u16 start index into KEYLIST_IDS per world plus
    # the end; KEYLIST_BUF is keylist_species' output (one species per id).
    world_ids = data.key_world_ids()
    starts = [sum(len(ids) for ids in world_ids[:w]) for w in range(len(world_ids) + 1)]
    EXT_TABLES["KEYLIST_INDEX"] = struct.pack(f"<{len(starts)}H", *starts)
    EXT_TABLES["KEYLIST_IDS"] = b"".join(struct.pack(f"<{len(ids)}H", *ids) for ids in world_ids)
    EXT_TABLES["KEYLIST_BUF"] = bytes(2 * max(len(ids) for ids in world_ids))
    va = STATE + STATE_SIZE
    for name, blob in EXT_TABLES.items():
        CONSTANTS[f"{name}_VA"] = va
        va = (va + len(blob) + 3) & ~3
    va = CONSTANTS["MENU_TEXT_VA"]
    for name, piece in MENU_TEXT:
        CONSTANTS[f"TEXT_{name}_VA"] = va
        va += len(piece)
    return data


def ext_blob() -> bytes:
    out = bytearray()
    for name, blob in EXT_TABLES.items():
        assert STATE + STATE_SIZE + len(out) == CONSTANTS[f"{name}_VA"]
        out += blob + bytes(-len(blob) % 4)
    return bytes(out)


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def preprocess(src: str) -> str:
    src = re.sub(r"@.*", "", src)
    for name, value in CONSTANTS.items():
        text = value if isinstance(value, str) else hex(value)
        src = re.sub(rf"\b{name}\b", text, src)
    return src


CONDITIONS = {"eq": 0, "ne": 1, "hs": 2, "cs": 2, "lo": 3, "cc": 3, "mi": 4, "pl": 5, "vs": 6,
              "vc": 7, "hi": 8, "ls": 9, "ge": 10, "lt": 11, "gt": 12, "le": 13, "": 14, "al": 14}
BRANCH = re.compile(r"^(\s*)(bl|b)(eq|ne|hs|cs|lo|cc|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al|)"
                    r"\s+(0x[0-9a-fA-F]+|[A-Za-z_]\w*)\s*$", re.M)


def assemble() -> tuple[bytes, dict[str, int]]:
    """Assemble all modules at INJECT_VA.

    Keystone mis-resolves branches to absolute addresses that follow data
    directives, and conditional BLs to forward labels (it emits a branch to
    itself), so every direct branch gets a site label and is re-encoded here.
    """
    import keystone
    source = "\n".join(preprocess((HERE / m).read_text(encoding="utf-8")) for m in MODULES)
    sites = []

    def label_site(m):
        sites.append((m.group(2) == "bl", CONDITIONS[m.group(3)], m.group(4)))
        return f"{m.group(1)}__br{len(sites) - 1}: {m.group(2)}{m.group(3)} {m.group(4)}"
    source = BRANCH.sub(label_site, source)
    labels = re.findall(r"^\s*([A-Za-z_]\w*):", source, re.M)
    ks = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_ARM)
    encoding, _ = ks.asm(source, INJECT_VA)
    blob = bytearray(encoding)
    # Probe each label's address (Keystone has no symbol dump).
    symbols = {}
    for label in labels:
        probe, _ = ks.asm(source + f"\n.word {label}\n", INJECT_VA)
        symbols[label] = u32(bytes(probe), len(blob))
    placed = []
    for i, (link, cond, target) in enumerate(sites):
        at = symbols.pop(f"__br{i}")
        target = int(target, 16) if target.startswith("0x") else symbols[target]
        struct.pack_into("<I", blob, at - INJECT_VA, branch(at, target, link, cond))
        placed.append((at, target))
    if INJECT_VA + len(blob) > INJECT_END:
        raise SystemExit(f"injection is {len(blob):#x} bytes; only "
                         f"{INJECT_END - INJECT_VA:#x} bytes of padding are available")
    check_sites(bytes(blob), placed)
    return bytes(blob), symbols


def check_sites(blob: bytes, placed: list[tuple[int, int]]) -> None:
    """Each absolute branch must disassemble to its intended target."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    for at, target in placed:
        insn = next(md.disasm(blob[at - INJECT_VA:at - INJECT_VA + 4], at))
        if int(insn.op_str.lstrip("#"), 16) != target:
            raise SystemExit(f"branch at {at:#x} decodes to {insn.op_str}, wanted {target:#x}")


def branch(src: int, dst: int, link: bool, cond: int = 14) -> int:
    off = dst - (src + 8)
    assert off % 4 == 0 and -(1 << 25) <= off < (1 << 25)
    return cond << 28 | (0x0B000000 if link else 0x0A000000) | ((off >> 2) & 0xFFFFFF)


def rodata_blob() -> bytes:
    out = bytearray()
    for name, blob in RODATA_TABLES.items():
        assert RODATA_VA + len(out) == CONSTANTS[f"{name}_VA"]
        out += blob + bytes(-len(blob) % 4)
    return bytes(out)


def patch_code(code: bytearray) -> dict:
    """Patch .code in place; it grows to hold the extended data segment."""
    assert len(code) == CODE_SIZE
    if any(code[BSS_START - CODE_VA:]):
        raise SystemExit("data segment padding is not empty in the source .code")
    ext = ext_blob()
    data_end = STATE + STATE_SIZE + len(ext)
    code += bytes(((data_end - CODE_VA + 0xFFF) & ~0xFFF) - len(code))
    code[STATE + STATE_SIZE - CODE_VA:data_end - CODE_VA] = ext
    tables = rodata_blob()
    off = RODATA_VA - CODE_VA
    if any(code[off:RODATA_END - CODE_VA]):
        raise SystemExit("rodata padding is not empty in the source .code")
    code[off:off + len(tables)] = tables
    blob, symbols = assemble()
    pad = INJECT_VA - CODE_VA
    if any(code[pad:pad + len(blob)]):
        raise SystemExit("text padding is not empty in the source .code")
    code[pad:pad + len(blob)] = blob
    for va, original, kind, label in HOOKS:
        off = va - CODE_VA
        found = u32(code, off)
        if found != original:
            raise SystemExit(f"hook {va:#x}: expected {original:#010x}, found {found:#010x}")
        struct.pack_into("<I", code, off, branch(va, symbols[label], kind == "bl"))
    return {"bytes": len(blob), "rodata": len(tables), "ext": len(ext), "data_end": data_end,
            "symbols": symbols}


def sha(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def build(source: Path, output: Path, check_source: bool) -> dict:
    if source.resolve() == output.resolve():
        raise SystemExit("output must differ from the source ROM")
    with source.open("rb") as f:
        head = bytearray(f.read(NCCH))
        ncch = bytearray(f.read(0x200))
        exheader = bytearray(f.read(0x800))
        gap = f.read(EXEFS - f.tell())
        exefs_header = bytearray(f.read(0x200))
        code = bytearray(f.read(CODE_SIZE))
        f.seek(0, 2)
        source_size = f.tell()
    assert head[0x100:0x104] == b"NCSD" and ncch[0x100:0x104] == b"NCCH"
    assert u32(head, 0x300) == source_size and u32(head, 0x120) * 0x200 == NCCH
    assert NCCH + u32(ncch, 0x1A0) * 0x200 == EXEFS
    assert exefs_header[0:8].rstrip(b"\0") == b".code" and u32(exefs_header, 8) == 0
    assert u32(exefs_header, 12) == CODE_SIZE
    assert sha(code) == exefs_header[0x1E0:0x200], ".code hash mismatch in source"
    assert u32(exheader, 0x10) == CODE_VA and exheader[0x0D] & 1 == 0   # uncompressed
    assert u32(exheader, 0x30) == DATA_VA and DATA_VA + u32(exheader, 0x38) == BSS_START
    assert BSS_START + u32(exheader, 0x3C) == BSS_ORIGINAL_END
    if check_source:
        print("hashing source ROM...", flush=True)
        h = hashlib.sha256()
        with source.open("rb") as f:
            while chunk := f.read(1 << 24):
                h.update(chunk)
        if h.hexdigest() != SOURCE_SHA256:
            raise SystemExit("source ROM is not the expected v1.2 translated image")

    info = patch_code(code)

    # Data segment now runs to the end of the tables; nothing is left in BSS.
    data_size = info["data_end"] - DATA_VA
    struct.pack_into("<III", exheader, 0x34, (data_size + 0xFFF) >> 12, data_size, 0)
    assert CODE_VA + len(code) == DATA_VA + ((data_size + 0xFFF) & ~0xFFF)
    ncch[0x160:0x180] = sha(exheader[:u32(ncch, 0x180)])

    # .code grew by delta: shift the other ExeFS files, the RomFS and the
    # later partitions (everything after .code moves down unchanged).
    delta = len(code) - CODE_SIZE
    assert delta % 0x1000 == 0
    units = delta // 0x200
    struct.pack_into("<I", exefs_header, 12, len(code))
    for i in range(1, 10):
        if exefs_header[i * 16:i * 16 + 8].strip(b"\0"):
            struct.pack_into("<I", exefs_header, i * 16 + 8, u32(exefs_header, i * 16 + 8) + delta)
    exefs_header[0x1E0:0x200] = sha(code)
    for off in (0x104, 0x1A4, 0x1B0):          # content size, ExeFS size, RomFS offset
        struct.pack_into("<I", ncch, off, u32(ncch, off) + units)
    ncch[0x1C0:0x1E0] = sha(exefs_header[:u32(ncch, 0x1A8) * 0x200])
    struct.pack_into("<I", head, 0x124, u32(head, 0x124) + units)           # partition 0 size
    for i in range(1, 8):
        if u32(head, 0x124 + 8 * i):
            struct.pack_into("<I", head, 0x120 + 8 * i, u32(head, 0x120 + 8 * i) + units)
    struct.pack_into("<I", head, 0x300, source_size + delta)                 # filled size
    assert source_size + delta <= u32(head, 0x104) * 0x200

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"writing ROM to {output} ...", flush=True)
    with source.open("rb") as src, output.open("wb") as f:
        f.write(head)
        f.write(ncch)
        f.write(exheader)
        f.write(gap)
        f.write(exefs_header)
        f.write(code)
        src.seek(CODE_FILE + CODE_SIZE)
        shutil.copyfileobj(src, f, 1 << 24)
        assert f.tell() == source_size + delta
    verify(output, info)
    return info


def verify(output: Path, info: dict) -> None:
    import capstone
    with output.open("rb") as f:
        f.seek(NCCH)
        ncch = f.read(0x200)
        exheader = f.read(0x800)
        f.seek(EXEFS)
        exefs_header = f.read(0x200)
        code = f.read(u32(exefs_header, 12))
    assert u32(exheader, 0x38) == info["data_end"] - DATA_VA and u32(exheader, 0x3C) == 0
    ext = ext_blob()
    at = STATE + STATE_SIZE - CODE_VA
    assert code[at:at + len(ext)] == ext and not any(code[BSS_START - CODE_VA:at])
    assert sha(exheader[:u32(ncch, 0x180)]) == ncch[0x160:0x180]
    assert sha(exefs_header[:u32(ncch, 0x1A8) * 0x200]) == ncch[0x1C0:0x1E0]
    assert sha(code) == exefs_header[0x1E0:0x200]
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    for va, _, kind, label in HOOKS:
        insn = next(md.disasm(code[va - CODE_VA:va - CODE_VA + 4], va))
        assert int(insn.op_str.lstrip("#"), 16) == info["symbols"][label], (hex(va), insn.op_str)
        print(f"  hook {va:#08x}: {insn.mnemonic} {insn.op_str}  ({label})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--out", type=Path, default=HERE / "out" / "DQM2-Randomizer.3ds")
    parser.add_argument("--libs", action="append", default=[],
                        help="extra import path for keystone/capstone (repeatable)")
    parser.add_argument("--skip-source-hash", action="store_true")
    parser.add_argument("--asm-only", action="store_true", help="assemble and list symbols only")
    args = parser.parse_args()
    sys.path[:0] = args.libs
    rom_tables(args.rom)
    if args.asm_only:
        blob, symbols = assemble()
        print(f"{len(blob):#x} of {INJECT_END - INJECT_VA:#x} bytes at {INJECT_VA:#x}; "
              f"tables {len(rodata_blob()):#x} of {RODATA_END - RODATA_VA:#x} bytes at {RODATA_VA:#x}, "
              f"{len(ext_blob()):#x} at {STATE + STATE_SIZE:#x}")
        for k, v in symbols.items():
            print(f"  {v:#010x} {k}")
        return
    info = build(args.rom, args.out, not args.skip_source_hash)
    print(f"injected {info['bytes']:#x} bytes of code at {INJECT_VA:#x}, {info['rodata']:#x} "
          f"bytes of tables at {RODATA_VA:#x} and {info['ext']:#x} at {STATE + STATE_SIZE:#x}; "
          f"wrote {args.out}")


if __name__ == "__main__":
    main()
