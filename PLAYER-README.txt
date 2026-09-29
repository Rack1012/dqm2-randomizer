DRAGON QUEST MONSTERS 2 (3DS) - RANDOMIZER
==========================================

A randomizer built into the game itself. When you start a New Adventure you
pick which parts of the game to shuffle, and every new save gets its own
random layout. There's no separate program to run: patch the ROM once and
every new game is different.

If you run into anything weird (crashes, frozen screens, monsters that look
or behave broken), please report it along with where you were and which
options you had on.


WHAT YOU NEED
-------------
The English fan translation of the game, v1.2 by Dackst & Ich73:

  Dragon Quest Monsters 2 - Cobi and Tara's Marvelous Mysterious Key (Japan)
  [T-En by Dackst & Ich73 v1.2] [n].3ds

  Size:    1,936,310,272 bytes
  CRC32:   20B5C689
  MD5:     f37f2a19c68deea8e9bf2e1eaaa5b599
  SHA-256: b21d42b7fe643b72787bad18e1768a12b42173e6b4cbf571e3e84baa2575ce70

The patch only works on this exact file. If your checksum is different, the
patcher will refuse it or produce a broken ROM.

You have to supply your own ROM. This patch doesn't include the game.


HOW TO PATCH
------------
Windows: use Delta Patcher (or xdelta UI).
  1. "Original file": your translated .3ds
  2. "XDelta patch":  DQM2-Randomizer.xdelta
  3. Click Apply patch. Keep a copy of the original ROM somewhere safe.

Command line (any OS, xdelta3):
  xdelta3 -d -s "<translated rom>.3ds" DQM2-Randomizer.xdelta DQM2-Randomizer.3ds

The patched ROM should come out as:
  Size:    1,936,982,016 bytes
  CRC32:   DBDE985D
  MD5:     a1fdada8a1e2a083c811c3086492d004
  SHA-256: 54374c6852ff69a5eab928f24d786c661a7069ae9d12ca29608c4cdfef2cf5cb

Tested on the Azahar emulator. It hasn't been tried on real 3DS hardware yet.


STARTING A RANDOMIZED GAME
--------------------------
On the title screen, choose New Adventure. The menu then turns into the
randomizer options:

  Random Roaming Monsters : ON/OFF
  Random Skillsets        : ON/OFF
  Random Bosses           : ON/OFF
  Random Fusions          : ON/OFF
  Start Game
  Cancel

Press A on an option to switch it ON or OFF. Pick Start Game when you're done,
or Cancel to go back to the normal title menu.

A random seed is picked when you press Start Game, and your options and seed
are stored in your save file. When you load that save later, you get exactly
the same randomization back, so nothing reshuffles between sessions.

Saves made before patching still load fine and play as the normal,
unrandomized game.


THE OPTIONS
-----------

RANDOM ROAMING MONSTERS
  The wild monster groups you meet in the worlds are swapped for random
  monsters.
  - Replacements keep their normal size (1 to 4 slots). If a group no longer
    fits in 4 slots, followers are dropped. The leader never is.
  - Each encounter keeps its original level. EXP, gold and stats are scaled by
    how strong the new monster is compared with the one it replaced, so a
    Metal Slime-type replacement can be worth a LOT of EXP. That's
    intentional.
  - Super G monsters are never used as replacements, and the story-world
    Super G bosses are never changed.
  - The monster list for each world on the Mysterious Key screen (the pages
    you flip through with W at the Great Log's gate) shows the randomized
    monsters that really live there. Monsters you haven't met yet show as
    "???", same as in the normal game.
  - Monsters in the Key worlds aren't randomized (for now).

RANDOM SKILLSETS
  Every species' signature skillset is shuffled among all the named species.
  - Wild and enemy monsters use their species' new skillset.
  - Their extra Boost/Ward skillsets are re-rolled within the same tier
    (regular or Uber). Other extra skillsets are left alone.
  - A monster never gets the same skillset twice.

RANDOM BOSSES
  Story boss fights (including their minions), Estark, and the Gryphynx,
  King Squid and Slime Blaster fights get random monsters.
  - Each replacement takes up the same number of slots as the monster it
    replaces. The one exception: a 4-slot boss becomes a 3-slot monster.
  - The fight keeps the original boss's level, stats, EXP and gold, so it
    should be about as hard as usual.
  - Cutscenes and map sprites still show the original boss. The monster you
    actually fight is the random one.
  - The Super G fights are never changed.

RANDOM FUSIONS
  Fusion results are scrambled. Every possible fusion outcome is mapped to a
  different monster through one fixed shuffle for your save.
  - This covers recipe fusions, the normal family/rank fusions, and the
    card-suit fusions. Results can be ANY rank, Super G included.
  - Same-species fusions and the Montner result are unchanged.
  - The fusion screen and fusion search show the NEW results, so what the
    game tells you is always accurate. Normal fusion charts won't help you!


CREDITS
-------
English translation: Dackst & Ich73. This patch is built on their v1.2
translation, and none of it would be playable without their work.
Randomizer: Duquan1337.

Dragon Quest Monsters 2 is (c) Square Enix / Nintendo. This is an unofficial,
free fan project. Please don't sell it or distribute patched ROMs.
