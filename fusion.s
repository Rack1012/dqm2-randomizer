@ Random fusions.
@
@ The fusion object (built by 0x57a93c whenever a fusion screen opens) asks
@ 0x5790a0 for each candidate result of two parents; it returns the species
@ and writes a type code. Types 4-8 are fusion outcomes (4-grandparent,
@ pair recipe, card suit, family/rank rule, species+family recipe), 1-3 hand
@ back a parent. So every outcome in FUSION_BITMAP (all the species vanilla
@ fusion can produce) goes through a seeded permutation of that pool:
@ FUSION_MAP[species], 0 = unchanged. The fusion search's reverse lookups
@ (target -> parents: 0x578900, 0x579e68, 0x579fc0, 0x57a0cc, 0x57a490, all
@ with the target in r1) look for FUSION_INV[target] instead, so the pairs
@ they list give the target under the permutation.

@ r0 = seed, or 0 when the option is off. Called by tables_apply; uses
@ STATE_SHUFFLE as scratch (skills_shuffle is done with it). Same as
@ model.shuffle_fusion.
fusion_apply:
    push    {r4-r8, lr}
    mov     r8, r0
    ldr     r5, =STATE_FUSION_MAP   @ map, then inverse at +2 * SPECIES_COUNT
    mov     r0, #0
    mov     r1, #0
fusion_clear:
    str     r0, [r5, r1]
    add     r1, r1, #4
    cmp     r1, #(4 * SPECIES_COUNT)
    blo     fusion_clear
    cmp     r8, #0
    popeq   {r4-r8, pc}
    ldr     r6, =STATE_SHUFFLE
    mov     r7, #0                  @ pool count
    mov     r4, #0
fusion_gather:
    mov     r0, r4
    bl      fusion_bit
    lslne   r1, r7, #1
    strhne  r4, [r6, r1]
    addne   r7, r7, #1
    add     r4, r4, #1
    cmp     r4, #SPECIES_COUNT
    blo     fusion_gather
    subs    r4, r7, #1              @ i = n - 1
fusion_swap:
    ble     fusion_scatter          @ until i == 0
    mov     r0, r8
    mov     r1, #DOMAIN_FUSION
    mov     r2, r4
    mov     r3, #0
    bl      roll32
    add     r1, r4, #1
    umull   r2, r3, r0, r1          @ j = roll * (i + 1) >> 32
    lsl     r2, r4, #1
    lsl     r3, r3, #1
    ldrh    r0, [r6, r2]
    ldrh    r1, [r6, r3]
    strh    r1, [r6, r2]
    strh    r0, [r6, r3]
    subs    r4, r4, #1
    b       fusion_swap
fusion_scatter:
    mov     r4, #0
    mov     r7, r6
fusion_scatter_loop:
    mov     r0, r4
    bl      fusion_bit
    beq     fusion_scatter_next
    ldrh    r0, [r7], #2            @ the k-th pool species becomes this one
    lsl     r1, r4, #1
    strh    r0, [r5, r1]            @ map[old] = new
    add     r1, r5, #(2 * SPECIES_COUNT)
    lsl     r0, r0, #1
    strh    r4, [r1, r0]            @ inverse[new] = old
fusion_scatter_next:
    add     r4, r4, #1
    cmp     r4, #SPECIES_COUNT
    blo     fusion_scatter_loop
    pop     {r4-r8, pc}

@ r0 = species -> Z clear when it is in the fusion pool. Clobbers r0-r1.
fusion_bit:
    ldr     r1, =FUSION_BITMAP_VA
    ldrb    r1, [r1, r0, lsr #3]
    and     r0, r0, #7
    lsr     r1, r1, r0
    tst     r1, #1
    bx      lr

@ Replaces push {r0-r11, lr} at 0x5790a0. The candidate's type pointer is
@ the first stack argument; the return comes back to fusion_candidate_done.
@ 0x5790a0 never re-enters itself, so one saved return address is enough.
fusion_candidate:
    ldr     ip, =STATE
    str     lr, [ip, #STATE_FUSION_LR]
    ldr     lr, [sp]
    str     lr, [ip, #STATE_FUSION_TYPE]
    adr     lr, fusion_candidate_done
    push    {r0-r11, lr}
    b       0x5790a4
fusion_candidate_done:
    ldr     ip, =STATE
    ldr     lr, [ip, #STATE_FUSION_LR]
    ldr     r1, [ip, #STATE_FUSION_TYPE]
    ldrb    r1, [r1]
    sub     r1, r1, #4
    cmp     r1, #4                  @ types 4-8 only
    bxhi    lr
    cmp     r0, #SPECIES_COUNT      @ -1 = no candidate
    bxhs    lr
    ldr     r1, =STATE_FUSION_MAP
    lsl     ip, r0, #1
    ldrh    r1, [r1, ip]
    cmp     r1, #0
    movne   r0, r1
    bx      lr

@ Reverse lookups: r1 = target species. Each replaces the function's first
@ instruction, re-runs it and continues.
fusion_rev_kind:
    push    {lr}
    bl      fusion_inverse
    pop     {lr}
    mov     ip, r0
    b       0x578904
fusion_rev_kind_type:
    push    {lr}
    bl      fusion_inverse
    pop     {lr}
    mov     ip, r0
    b       0x579e6c
fusion_rev_rank_a:
    push    {lr}
    bl      fusion_inverse
    pop     {lr}
    push    {r4-r12, lr}
    b       0x579fc4
fusion_rev_rank_b:
    push    {lr}
    bl      fusion_inverse
    pop     {lr}
    push    {r0-r11, lr}
    b       0x57a0d0
fusion_rev_rank_c:
    push    {lr}
    bl      fusion_inverse
    pop     {lr}
    push    {r0-r11, lr}
    b       0x57a494

@ r1 = species -> FUSION_INV[r1] when set. Clobbers ip only.
fusion_inverse:
    cmp     r1, #SPECIES_COUNT
    bxhs    lr
    ldr     ip, =(STATE_FUSION_MAP + 2 * SPECIES_COUNT)
    add     ip, ip, r1, lsl #1
    ldrh    ip, [ip]
    cmp     ip, #0
    movne   r1, ip
    bx      lr
.ltorg
