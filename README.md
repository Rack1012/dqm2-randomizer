# Dragon Quest Monsters 2 (3DS) Randomizer

A randomizer built into the game itself, for the English fan translation of
*Dragon Quest Monsters 2: Cobi and Tara's Marvelous Mysterious Key* (3DS).
Start a New Adventure, pick your options from the title menu, and every save
gets its own random layout:

- **Random Roaming Monsters**: wild encounters become random monsters, with
  EXP, gold and stats scaled to match. The Mysterious Key screen's monster
  pages list the new monsters too.
- **Random Skillsets**: signature skillsets are shuffled between species.
- **Random Bosses**: story bosses (and their minions) become random monsters
  of the same size, keeping the original fight's numbers.
- **Random Fusions**: every fusion result is remapped through one shuffle for
  your save. The fusion screen and search show the new results.

The seed and options live in your save file, so a save always loads with the
same randomization. Saves from before patching still play as the normal game.

## Download and play

Get `DQM2-Randomizer.zip` from the [Releases](../../releases) page. It
contains an xdelta patch and a player readme ([PLAYER-README.txt](PLAYER-README.txt))
with the patching steps, what each option does, and the checksums.

You need the English translation v1.2 by Dackst & Ich73
(`... (Japan) [T-En by Dackst & Ich73 v1.2] [n].3ds`, SHA-256
`b21d42b7fe643b72787bad18e1768a12b42173e6b4cbf571e3e84baa2575ce70`).
This project doesn't include or distribute any game files.

Tested on the Azahar emulator.

## How it works

`build.py` copies the translated ROM and injects ARM code into unused padding
in the game's executable (`.code`). The code hooks the New Game menu, save
loading and saving, the encounter and party setup, the Key screen's monster
list, and the fusion engine. It then fixes up the ExHeader, ExeFS and NCCH
hashes. The randomization runs on the 3DS at New Game and on every save load,
starting from a seed stored in the save header.

| File | Contents |
| --- | --- |
| `settings.s` | options menu, seed, save load/save hooks |
| `roaming.s` | roaming monster and boss re-rolls, stat/EXP/gold rescale, party trimming, Key screen lists |
| `skills.s` | skillset shuffle |
| `fusion.s` | fusion remap and the reverse lookups used by fusion search |
| `model.py` | reference model of every rule, and the tables embedded in the ROM |
| `build.py` | table generation, assembly, hook patching, ROM rebuild |
| `test_arm.py` | runs the injected code in Unicorn and checks it against `model.py` |
| `legacy/*.pyc` | ROM/RomFS/XBB readers and text dumper (compiled Python 3.14; the sources are lost) |

## Building from source

Requirements: Python 3.14 (the `legacy` tools are 3.14 bytecode),
[Keystone](https://www.keystone-engine.org/) and
[Capstone](https://www.capstone-engine.org/), plus
[Unicorn](https://www.unicorn-engine.org/) for the tests.

`build.py` expects this repository to sit in a folder next to the translated
ROM, with a text index of the game's messages in `analysis/`:

```
some-folder/
  Dragon Quest Monsters 2 - ... [T-En by Dackst & Ich73 v1.2] [n].3ds
  analysis/text-index.jsonl
  dqm2-randomizer/        <- this repository
```

Generate the text index from your own ROM once:

```
python3.14 legacy/textdump.pyc --rom "../<translated rom>.3ds" --all --out ../analysis/text-index.jsonl
```

Then build, and optionally run the tests:

```
python3.14 build.py --libs <keystone dir> --libs <capstone dir> --out out/DQM2-Randomizer.3ds
python3.14 test_arm.py --libs <keystone dir> --libs <capstone dir> --libs <unicorn dir>
```

The build checks the source ROM's hash and never modifies it.

## Credits

- English translation: Dackst & Ich73. This project is built on their v1.2
  translation.
- Randomizer: Grant.

Dragon Quest Monsters 2 is © Square Enix / Nintendo. This is an unofficial,
free fan project. Please don't sell it or distribute patched ROMs.
