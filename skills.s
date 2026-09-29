@ Random skillsets.
@
@ Every new monster (scouted, synthesized, gifted, starter) takes its
@ signature skillset from the loaded EnmyKindTbl row (+0x66, via 0x1f3640),
@ and scouted/battle monsters add the BEPT row's extras (+0x54, +0x56). So
@ the option rewrites those loaded tables: signatures are shuffled among the
@ eligible species (SHUFFLE_BITMAP), each BEPT row's +0x52 follows its
@ species' new signature, and Boost/Ward extras are re-rolled within their
@ tier. tables_apply calls these with the pristine values restored first.

@ r0 = BEPT row for id 1, r1 = nonzero to save the pristine values into
@ STATE_EKT_BACKUP/STATE_SKILL_BACKUP, zero to restore them from there.
skills_sync:
    push    {r4-r7, lr}
    mov     r5, r0
    mov     r6, r1
    ldr     r7, =STATE_EKT_BACKUP
    mov     r4, #0                  @ species
sync_ekt_loop:
    mov     r0, r4
    bl      0x1f3640
    cmp     r6, #0
    ldrhne  r1, [r0, #0x66]
    strhne  r1, [r7]
    ldrheq  r1, [r7]
    strheq  r1, [r0, #0x66]
    add     r7, r7, #2
    add     r4, r4, #1
    cmp     r4, #SPECIES_COUNT
    blo     sync_ekt_loop
    ldr     r7, =STATE_SKILL_BACKUP
    ldr     r4, =BEPT_COUNT
sync_rows_loop:
    add     r0, r5, #0x52
    cmp     r6, #0
    movne   r1, r0                  @ backup <- row
    movne   r0, r7
    moveq   r1, r7                  @ row <- backup
    ldrh    r2, [r1]
    strh    r2, [r0]
    ldrh    r2, [r1, #2]
    strh    r2, [r0, #2]
    ldrh    r2, [r1, #4]
    strh    r2, [r0, #4]
    add     r5, r5, #96
    add     r7, r7, #6
    subs    r4, r4, #1
    bne     sync_rows_loop
    pop     {r4-r7, pc}

@ r0 = seed. Fisher-Yates over the eligible species' signatures, in species
@ order, using STATE_SHUFFLE as scratch; same as model.shuffle_signatures.
skills_shuffle:
    push    {r4-r8, lr}
    mov     r8, r0
    ldr     r5, =STATE_SHUFFLE
    mov     r6, #0                  @ eligible count
    mov     r4, #0
shuffle_gather:
    mov     r0, r4
    bl      shuffle_bit
    beq     shuffle_gather_next
    mov     r0, r4
    bl      0x1f3640
    ldrh    r0, [r0, #0x66]
    lsl     r1, r6, #1
    strh    r0, [r5, r1]
    add     r6, r6, #1
shuffle_gather_next:
    add     r4, r4, #1
    cmp     r4, #SPECIES_COUNT
    blo     shuffle_gather
    subs    r4, r6, #1              @ i = n - 1
shuffle_swap:
    ble     shuffle_scatter         @ until i == 0
    mov     r0, r8
    mov     r1, #DOMAIN_SKILL
    mov     r2, r4
    mov     r3, #0
    bl      roll32
    add     r1, r4, #1
    umull   r2, r3, r0, r1          @ j = roll * (i + 1) >> 32
    lsl     r2, r4, #1
    lsl     r3, r3, #1
    ldrh    r0, [r5, r2]
    ldrh    r1, [r5, r3]
    strh    r1, [r5, r2]
    strh    r0, [r5, r3]
    subs    r4, r4, #1
    b       shuffle_swap
shuffle_scatter:
    mov     r4, #0
    mov     r6, #0
shuffle_scatter_loop:
    mov     r0, r4
    bl      shuffle_bit
    beq     shuffle_scatter_next
    mov     r0, r4
    bl      0x1f3640
    lsl     r1, r6, #1
    ldrh    r1, [r5, r1]
    strh    r1, [r0, #0x66]
    add     r6, r6, #1
shuffle_scatter_next:
    add     r4, r4, #1
    cmp     r4, #SPECIES_COUNT
    blo     shuffle_scatter_loop
    pop     {r4-r8, pc}

@ r0 = settings, r1 = BEPT row for id 1. Runs after the roaming pass.
@ Skillsets on: +0x52 follows the (shuffled) species signature and the
@ Boost/Ward extras are re-rolled. Either option: an extra equal to a changed
@ signature would be installed twice, so it takes the original signature.
skills_rows:
    push    {r4-r8, lr}
    lsr     r6, r0, #3              @ seed
    and     r7, r0, #7              @ options
    mov     r5, r1
    ldr     r8, =STATE_SKILL_BACKUP @ pristine +0x52/+0x54/+0x56 per row
    mov     r4, #1                  @ BEPT id
rows_loop:
    ldrh    r0, [r5, #0x52]
    cmp     r0, #0
    beq     rows_next               @ empty row
    tst     r7, #OPT_SKILLSETS
    beq     rows_dedup
    ldrh    r0, [r5]
    bl      0x1f3640
    ldrh    r0, [r0, #0x66]
    strh    r0, [r5, #0x52]
    mov     r0, r6
    lsl     r1, r4, #1
    mov     r2, r5
    mov     r3, #0
    bl      pick_extra
    mov     r0, r6
    lsl     r1, r4, #1
    add     r1, r1, #1
    mov     r2, r5
    mov     r3, #1
    bl      pick_extra
rows_dedup:
    ldrh    r0, [r5, #0x52]
    ldrh    r1, [r8]
    cmp     r0, r1
    beq     rows_next
    ldrh    r2, [r5, #0x54]
    cmp     r2, r0
    strheq  r1, [r5, #0x54]
    ldrh    r2, [r5, #0x56]
    cmp     r2, r0
    strheq  r1, [r5, #0x56]
rows_next:
    add     r4, r4, #1
    add     r5, r5, #96
    add     r8, r8, #6
    ldr     r0, =BEPT_COUNT
    cmp     r4, r0
    bls     rows_loop
    pop     {r4-r8, pc}

@ r0 seed, r1 key, r2 BEPT row, r3 extra index (0: +0x54, 1: +0x56).
@ Re-rolls a Boost/Ward extra within its tier, avoiding the row's signature
@ and other extra (MAX_TRIES); other extras are left alone.
pick_extra:
    push    {r4-r11, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    add     r7, r2, r3, lsl #1      @ [r7, #0x54] = this extra
    rsb     r3, r3, #1
    add     r8, r2, r3, lsl #1      @ [r8, #0x54] = the other extra
    ldrh    r0, [r7, #0x54]
    ldr     r9, =POOL_REGULAR_VA
    mov     r10, #POOL_REGULAR_COUNT
    bl      pool_find
    beq     extra_roll
    ldrh    r0, [r7, #0x54]
    ldr     r9, =POOL_UBER_VA
    mov     r10, #POOL_UBER_COUNT
    bl      pool_find
    bne     extra_done
extra_roll:
    mov     r11, #0                 @ ordinal
extra_loop:
    mov     r0, r4
    mov     r1, #DOMAIN_EXTRA
    mov     r2, r5
    mov     r3, r11
    bl      roll32
    umull   r1, r2, r0, r10         @ index = roll * count >> 32
    lsl     r2, r2, #1
    ldrh    r0, [r9, r2]
    ldrh    r1, [r6, #0x52]
    cmp     r0, r1
    ldrhne  r1, [r8, #0x54]
    cmpne   r0, r1
    strhne  r0, [r7, #0x54]
    bne     extra_done
    add     r11, r11, #1
    cmp     r11, #MAX_TRIES
    blo     extra_loop
extra_done:
    pop     {r4-r11, pc}

@ r0 value, r9 halfword list, r10 count -> Z set when found. Clobbers r1-r2.
pool_find:
    mov     r1, #0
pool_find_loop:
    cmp     r1, r10
    beq     pool_find_miss
    lsl     r2, r1, #1
    ldrh    r2, [r9, r2]
    cmp     r2, r0
    bxeq    lr
    add     r1, r1, #1
    b       pool_find_loop
pool_find_miss:
    movs    r1, #1                  @ clear Z
    bx      lr

@ r0 = species -> Z clear when its signature joins the shuffle. Clobbers r0-r1.
shuffle_bit:
    ldr     r1, =SHUFFLE_BITMAP_VA
    ldrb    r1, [r1, r0, lsr #3]
    and     r0, r0, #7
    lsr     r1, r1, r0
    tst     r1, #1
    bx      lr
.ltorg
.align 2
