@ Random roaming monsters.
@
@ Battles, scouting, recruits and name lookups all read species from the
@ global BtlEnmyPrm (BEPT) table (0x1c2dfc, e.g. via the field symbol at
@ 0x5ad4d4), and area loads copy their rows from it. So the replacement is
@ written into the global table itself, for every BEPT id any area's
@ SingleMonster list references. tables_apply runs whenever the settings
@ change (new game, save load): the first call backs up every row either
@ option can re-roll (REROLL_RUNS) into BSS, every call restores them and
@ re-rolls from the current seed.
@
@ Random bosses: scripted fights (0x3111c0) take the four BEPT ids of an
@ EnemyPartyTbl party and gather the global rows too (0x2a2df8, via
@ 0x1c2dfc), so the boss parties' rows (BOSS_BITMAP, minions included) are
@ re-rolled the same way, under their own domain. There is no party trim on
@ that path, so a boss replacement has the original's size (3 slots for the
@ 4-slot bosses; the pool has none bigger), and it keeps the row's level,
@ stats, EXP and gold.
@ Replacements keep their own size; enemy_party_fit trims followers that
@ would overflow a battle. Field battles (0x1f7228 -> 0x1fdee4) copy the
@ row's authored level, stats, EXP (+0x28) and gold (+0x24); rescale_row
@ re-proportions those to the replacement species at the same level. The world maps'
@ Super G bosses are never re-rolled and never appear as replacements.

@ Settings changed: restore the pristine rows (and skillsets, skills.s), then
@ apply the options; fusion_apply (fusion.s) rebuilds the fusion permutation.
tables_apply:
    push    {r4-r11, lr}
    ldr     r11, =STATE
    mov     r0, #0
    bl      0x1c2dfc                @ row for BEPT id 1
    mov     r10, r0
    ldrb    r0, [r11, #STATE_BACKED_UP]
    cmp     r0, #0
    moveq   r9, #1                  @ first call: rows -> backup
    movne   r9, #0                  @ later calls: backup -> rows
    mov     r0, #1
    strb    r0, [r11, #STATE_BACKED_UP]
    ldr     r8, =STATE_BACKUP
    mov     r4, #1                  @ BEPT id
tables_copy_loop:
    mov     r0, r4
    bl      reroll_bit
    beq     tables_copy_next
    sub     r0, r4, #1
    mov     r1, #96
    mla     r0, r1, r0, r10         @ row address
    cmp     r9, #0
    movne   r1, r0                  @ backup <- row
    movne   r0, r8
    moveq   r1, r8                  @ row <- backup
    bl      copy96
    add     r8, r8, #96
tables_copy_next:
    add     r4, r4, #1
    ldr     r0, =BEPT_COUNT
    cmp     r4, r0
    bls     tables_copy_loop
    mov     r0, r10
    mov     r1, r9
    bl      skills_sync             @ signatures and BEPT skillsets likewise

    ldrh    r5, [r11]
    tst     r5, #OPT_SKILLSETS
    lsrne   r0, r5, #3
    blne    skills_shuffle          @ before roaming, which reads signatures
    tst     r5, #(OPT_ROAMING | OPT_BOSSES)
    beq     tables_rows
    mov     r4, #1
tables_roam_loop:
    mov     r0, r4
    bl      reroll_bit
    beq     tables_roam_next
    mov     r0, r4
    bl      boss_bit
    movne   r8, #DOMAIN_BOSS
    movne   r0, #OPT_BOSSES
    moveq   r8, #DOMAIN_ROAMING
    moveq   r0, #OPT_ROAMING
    tst     r5, r0
    beq     tables_roam_next        @ that row's option is off
    sub     r0, r4, #1
    mov     r1, #96
    mla     r6, r1, r0, r10         @ row
    ldrh    r7, [r6]                @ original species
    lsr     r0, r5, #3              @ seed
    mov     r1, r8
    mov     r2, r4
    mov     r3, r7
    bl      pick_species
    cmp     r0, r7
    beq     tables_roam_next
    strh    r0, [r6]
    bl      0x1f3640                @ EKT row of the replacement
    ldrh    r0, [r0, #0x66]         @ its signature skillset
    strh    r0, [r6, #0x52]
    mov     r0, #0                  @ drop the original's scripted AI weights
    strh    r0, [r6, #0x08]
    strh    r0, [r6, #0x0c]
    strh    r0, [r6, #0x10]
    strh    r0, [r6, #0x14]
    strh    r0, [r6, #0x18]
    strh    r0, [r6, #0x1c]
    cmp     r8, #DOMAIN_BOSS        @ bosses keep their authored numbers
    beq     tables_roam_next
    mov     r0, r6
    mov     r1, r7
    bl      rescale_row
tables_roam_next:
    add     r4, r4, #1
    ldr     r0, =BEPT_COUNT
    cmp     r4, r0
    bls     tables_roam_loop
tables_rows:
    ldrh    r0, [r11]
    tst     r0, #(OPT_ROAMING | OPT_SKILLSETS | OPT_BOSSES)
    movne   r1, r10
    blne    skills_rows
    ldrb    r0, [r11, #STATE_FUSION]
    cmp     r0, #0
    ldrhne  r0, [r11]
    lsrne   r0, r0, #3              @ seed, or 0 = fusions off
    bl      fusion_apply
    pop     {r4-r11, pc}

@ r0 = re-rolled BEPT row (replacement species already stored), r1 = the
@ original species. The authored EXP, gold and stats fit the original at
@ this row's level; scale each by replacement/original of the species' base
@ EXP and gold (KeyMonsterTbl, 0x50a1e8) and stat caps (EKT +0x12).
@ Same as model.rescale_row.
rescale_row:
    push    {r4-r8, lr}
    mov     r4, r0
    mov     r5, r1
    ldrh    r0, [r4]
    bl      0x50a1e8
    mov     r6, r0                  @ replacement's KeyMonsterTbl row
    mov     r0, r5
    bl      0x50a1e8
    mov     r7, r0                  @ original's
    ldr     r0, [r4, #0x28]         @ EXP
    ldr     r1, [r6, #4]
    ldr     r2, [r7, #4]
    mvn     r3, #0
    bl      scale_core
    str     r0, [r4, #0x28]
    ldr     r0, [r4, #0x24]         @ gold
    ldr     r1, [r6, #8]
    ldr     r2, [r7, #8]
    mvn     r3, #0
    bl      scale_core
    str     r0, [r4, #0x24]
    ldrh    r0, [r4]
    bl      0x1f3640
    add     r6, r0, #0x12           @ replacement's stat caps
    mov     r0, r5
    bl      0x1f3640
    add     r7, r0, #0x12           @ original's
    ldr     r8, =STAT_FIELDS_VA
rescale_loop:
    ldrb    r0, [r8]                @ row offset, 0 ends
    cmp     r0, #0
    beq     rescale_done
    ldrh    r0, [r4, r0]
    ldrb    r2, [r8, #1]            @ cap index * 2
    ldrh    r1, [r6, r2]
    ldrh    r2, [r7, r2]
    ldrh    r3, [r8, #2]            @ limit
    bl      scale_core
    ldrb    r1, [r8]
    strh    r0, [r4, r1]
    add     r8, r8, #4
    b       rescale_loop
rescale_done:
    pop     {r4-r8, pc}

@ r0 value, r1 new base, r2 old base, r3 limit -> r0 = round(value * new /
@ old) in single precision, at most max(limit, value) and at least 1; value
@ unchanged when it or old is 0. Uses s0-s2. Clobbers r1-r3, r12.
scale_core:
    cmp     r0, #0
    cmpne   r2, #0
    bxeq    lr
    cmp     r3, r0
    movlo   r3, r0
    vmov    s0, r0
    vcvt.f32.u32 s0, s0
    vmov    s1, r1
    vcvt.f32.u32 s1, s1
    vmov    s2, r2
    vcvt.f32.u32 s2, s2
    vmul.f32 s0, s0, s1
    vdiv.f32 s0, s0, s2
    ldr     r12, =0x3f000000        @ 0.5
    vmov    s1, r12
    vadd.f32 s0, s0, s1
    vcvt.u32.f32 s0, s0             @ truncates; saturates at 0xffffffff
    vmov    r0, s0
    cmp     r0, r3
    movhi   r0, r3
    cmp     r0, #0
    moveq   r0, #1
    bx      lr

@ r0 = BEPT id -> Z clear when the id is in REROLL_BITMAP (model.reroll_bitmap,
@ padded to 0x1000 ids). Clobbers r1, ip.
reroll_bit:
    cmp     r0, #0x1000             @ unsigned: negative ids are out of range too
    bhs     boss_bit_none
    ldr     r1, =REROLL_BITMAP_VA
    ldrb    r1, [r1, r0, lsr #3]
    and     ip, r0, #7
    lsr     r1, r1, ip
    tst     r1, #1
    bx      lr

@ r0 = BEPT id -> Z clear when the id is a boss party row. Clobbers r0-r1.
boss_bit:
    sub     r0, r0, #BOSS_FIRST
    cmp     r0, #BOSS_SPAN          @ unsigned: ids below the window wrap high
    bhs     boss_bit_none
    ldr     r1, =BOSS_BITMAP_VA
    ldrb    r1, [r1, r0, lsr #3]
    and     r0, r0, #7
    lsr     r1, r1, r0
    tst     r1, #1
    bx      lr
boss_bit_none:
    cmp     r0, r0                  @ Z set
    bx      lr

@ copy 96 bytes r1 -> r0. Clobbers r0-r3, r12.
copy96:
    push    {r4-r7}
    mov     r12, #4
copy96_loop:
    ldmia   r1!, {r2-r7}
    stmia   r0!, {r2-r7}
    subs    r12, r12, #1
    bne     copy96_loop
    pop     {r4-r7}
    bx      lr

@ Area encounter loader hook (0x2a3c58, a dead add r0,r7,#0x44); r7 = area.
@ Field symbols show the species cached in each SingleMonster (+4); make it
@ agree with the (already randomized) local copy of its primary BEPT row.
roaming_apply:
    push    {r4-r6, lr}
    ldr     r0, =STATE
    ldrh    r0, [r0]
    tst     r0, #(OPT_ROAMING | OPT_BOSSES)
    beq     roaming_done
    ldr     r4, [r7, #0x1c]
    ldr     r5, [r7, #0x20]
roaming_single_loop:
    cmp     r4, r5
    bhs     roaming_done
    ldrh    r1, [r4, #2]
    cmp     r1, #0                  @ KEY01 singles name species directly
    beq     roaming_single_next
    mov     r0, r7
    bl      0x2a287c                @ local BEPT row by id, or 0
    cmp     r0, #0
    ldrhne  r0, [r0]
    strhne  r0, [r4, #4]
roaming_single_next:
    add     r4, r4, #80
    b       roaming_single_loop
roaming_done:
    pop     {r4-r6, pc}

@ Mysterious Key screen: 0x214f58 builds a world key's monster pages from
@ data/Param/WorldMonsterList/<world> (world = key +0x10, 0x668fe4 order):
@ it loops over the file's u16 species (r7 = data, r6 = count at 0x2150fc),
@ skips species without a fusion order, drops duplicates, then sorts. With
@ roaming on, hand that loop the current species of the world's BEPT rows
@ instead (KEYLIST_IDS, model.key_world_ids), so the pages name the monsters
@ that really roam there.
@ Hook 0x2150ac (replaces ldrb r4,[r4,#0x10]; r4 = key): remember the world.
keylist_world:
    ldrb    r4, [r4, #0x10]
    ldr     r12, =STATE
    strb    r4, [r12, #STATE_KEY_WORLD]
    bx      lr

@ Hook 0x2150fc (replaces cmp r6,#0): may replace r7/r6, then redoes the cmp.
@ r5 and r8 are live in the caller; r4 is reset right after.
keylist_species:
    push    {r4, r5, r8, lr}
    ldr     r8, =STATE
    ldrh    r0, [r8]
    tst     r0, #OPT_ROAMING
    beq     keylist_done
    ldrb    r0, [r8, #STATE_KEY_WORLD]
    cmp     r0, #KEY_WORLDS
    bhs     keylist_done
    ldr     r1, =KEYLIST_INDEX_VA   @ u16 first id index per world, then the end
    add     r1, r1, r0, lsl #1
    ldrh    r2, [r1]
    ldrh    r3, [r1, #2]
    subs    r5, r3, r2
    beq     keylist_done            @ no rows (Last): keep the file's list
    ldr     r4, =KEYLIST_IDS_VA
    add     r4, r4, r2, lsl #1
    ldr     r7, =KEYLIST_BUF_VA
    mov     r6, r5
    mov     r8, r7
keylist_loop:
    ldrh    r0, [r4], #2
    sub     r0, r0, #1
    bl      0x1c2dfc                @ global row (already randomized)
    ldrh    r0, [r0]
    strh    r0, [r8], #2
    subs    r5, r5, #1
    bne     keylist_loop
keylist_done:
    cmp     r6, #0
    pop     {r4, r5, r8, pc}

@ Enemy party setup (0x1f7228) calls 0x1d2d50(id0..id3) at 0x1f725c with the
@ four battle slots' BEPT ids; r4 = slot 0 (slots are 0x340 apart) and the
@ caller keeps its own copy of the ids at [sp+0x10]. Replacements keep their
@ real size, so drop followers (never the leader) that would overflow the
@ four battle slots; an id of -1 is how the game marks an empty slot.
enemy_party_fit:
    push    {r4-r8, lr}
    add     r5, sp, #(24 + 0x10)    @ caller's id copy
    ldr     r0, =STATE
    ldrh    r0, [r0]
    tst     r0, #OPT_ROAMING
    beq     fit_call
    mov     r6, #0                  @ slots used
    mov     r7, #0                  @ position
fit_loop:
    ldr     r0, [r5, r7, lsl #2]
    cmp     r0, #0
    ble     fit_next
    sub     r0, r0, #1
    bl      0x1c2dfc                @ global row (already randomized)
    ldrh    r0, [r0]
    bl      species_nibble
    ands    r0, r0, #7
    moveq   r0, #1
    add     r1, r6, r0
    cmp     r7, #0
    beq     fit_keep
    cmp     r1, #BATTLE_SLOTS
    bls     fit_keep
    mvn     r0, #0
    str     r0, [r5, r7, lsl #2]
    mov     r1, #0x340
    mla     r1, r7, r1, r4
    str     r0, [r1]                @ slot id
    b       fit_next
fit_keep:
    mov     r6, r1
fit_next:
    add     r7, r7, #1
    cmp     r7, #4
    blo     fit_loop
fit_call:
    ldm     r5, {r0-r3}
    pop     {r4-r8, lr}
    b       0x1d2d50

@ r0 seed, r1 domain, r2 key, r3 original species -> r0 species.
@ Rejection-samples a pool species (MAX_TRIES): any size, or for DOMAIN_BOSS
@ the original's size capped at MAX_POOL_SLOTS; species the table does not
@ know are left alone.
pick_species:
    push    {r4-r9, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    mov     r7, r3
    mov     r0, r3
    bl      species_nibble
    ands    r9, r0, #7              @ original's slots
    beq     pick_fail
    cmp     r9, #MAX_POOL_SLOTS
    movhi   r9, #MAX_POOL_SLOTS
    mov     r8, #0                  @ ordinal
pick_loop:
    mov     r0, r4
    mov     r1, r5
    mov     r2, r6
    mov     r3, r8
    bl      roll32
    lsr     r0, r0, #22
    mov     r1, r0
    bl      species_nibble
    tst     r0, #8
    beq     pick_retry
    cmp     r5, #DOMAIN_BOSS
    bne     pick_found
    and     r0, r0, #7
    cmp     r0, r9
    bne     pick_retry
pick_found:
    mov     r0, r1
    pop     {r4-r9, pc}
pick_retry:
    add     r8, r8, #1
    cmp     r8, #MAX_TRIES
    blo     pick_loop
pick_fail:
    mov     r0, r7
    pop     {r4-r9, pc}

@ r0 species -> r0 nibble (bits 0-2 slots, bit 3 pool). Preserves r1-r3.
species_nibble:
    cmp     r0, #1024
    movhs   r0, #0
    bxhs    lr
    ldr     r12, =SPECIES_TABLE_VA
    ldrb    r12, [r12, r0, lsr #1]
    tst     r0, #1
    lsrne   r12, r12, #4
    and     r0, r12, #15
    bx      lr

@ roll32(seed r0, domain r1, key r2, ordinal r3) -> r0; same as model.roll32.
@ Clobbers r1-r3, r12.
roll32:
    ldr     r12, =0x9e3779b9
    mul     r0, r12, r0
    ldr     r12, =0x85ebca6b
    mul     r1, r12, r1
    eor     r0, r0, r1
    ldr     r12, =0xc2b2ae35
    mul     r2, r12, r2
    eor     r0, r0, r2
    ldr     r12, =0x27d4eb2d
    mul     r3, r12, r3
    eor     r0, r0, r3
    eor     r0, r0, r0, lsl #13
    eor     r0, r0, r0, lsr #17
    eor     r0, r0, r0, lsl #5
    bx      lr
.ltorg
