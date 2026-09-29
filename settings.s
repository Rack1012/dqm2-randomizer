@ New Game randomizer options menu and per-save settings storage.
@
@ Runtime state (STATE, in the BSS extension):
@   +0 u16 settings  (seed << 3) | options; 0 = randomizer off
@   +2 u8  option bits toggled in the options menu (bit n = row n)
@   +3 u8  1 while the title menu shows our options instead of its own rows
@   +5 u8  STATE_FUSION: 1 = random fusions (option bit 3, kept out of +0)
@   +6 u8  STATE_KEY_WORLD: world of the Mysterious Key being listed (roaming.s)
@   STATE_TEXT: the option label last handed to the text lookup
@
@ Save header (plaintext, inside the region the game encrypts/MACs):
@   +0xa8 u16 SAVE_MAGIC + fusion flag (never written by the original game)
@   +0xae u16 settings    (never written by the original game)
@ Existing saves hold stale ciphertext in both fields, so settings are only
@ accepted when the magic matches. Saves from before the fusion option carry
@ SAVE_MAGIC itself, i.e. fusions off.
@
@ The title menu (vtable 0x6a2aec) lists up to six bar rows of layout
@ bar_select_010 (0x21ed4c): row i gets msg_menu group 10 text via 0x217398
@ and is greyed via 0x216a0c; rows 4-5 are hidden (0x581b40 / 0x581c94)
@ unless the Transfer App entries are available. New Adventure relabels all
@ six rows as the four options (items OPT_ITEM..+3), Start Game and Cancel;
@ the A handler (0x21f0e4) toggles an option, starts the game, or puts the
@ game's own rows back.

@ Title menu, "New Adventure" with no save file (replaces strb r5,[r4,#0x5a]).
settings_start_nosave:
    mov     r0, r4
    bl      settings_open
    mov     r5, #1
    b       0x21f244

@ Title menu, after the overwrite warning closes (replaces mov r1,#2).
@ r4 = menu, r6 = 1 (callback result).
settings_start_warning:
    mov     r0, #0
    strb    r0, [r4, #0x58]         @ menu idle again: it takes input
    mov     r0, r4
    bl      settings_open
    b       0x21eccc

@ r0 = title menu. All options off, six rows showing the options.
settings_open:
    push    {r4-r6, lr}
    mov     r4, r0
    ldr     r5, =STATE
    mov     r0, #0
    strb    r0, [r5, #2]
    mov     r0, #1
    strb    r0, [r5, #3]
    mov     r0, #6
    bl      settings_rows
    mov     r6, #0
settings_open_loop:
    mov     r0, r6
    add     r1, r6, #OPT_ITEM
    mov     r2, #0
    bl      settings_row
    add     r6, r6, #1
    cmp     r6, #6
    blo     settings_open_loop
    ldr     r0, [r4, #0x50]
    mov     r1, #0
    bl      0x217e40                @ cursor to the first option
    pop     {r4-r6, pc}

@ r4 = menu. The game's own rows again, as 0x21ed4c builds them.
settings_close:
    push    {r5-r7, lr}
    ldr     r0, =STATE
    mov     r1, #0
    strb    r1, [r0, #3]
    ldrb    r0, [r4, #0x5e]
    cmp     r0, #0
    moveq   r0, #4
    movne   r0, #6
    bl      settings_rows
    ldr     r5, =0x66b7f4           @ per row: u16 item, u8 enabled, pad
    adr     r6, settings_row_flags
    mov     r7, #0
settings_close_loop:
    ldrb    r0, [r6, r7]            @ menu byte holding the row's enable flag
    cmp     r0, #0
    ldrbne  r2, [r4, r0]
    ldrbeq  r2, [r5, #2]
    cmp     r2, #0
    moveq   r2, #1                  @ greyed = not enabled
    movne   r2, #0
    ldrh    r1, [r5], #4
    mov     r0, r7
    bl      settings_row
    add     r7, r7, #1
    cmp     r7, #6
    blo     settings_close_loop
    ldr     r0, [r4, #0x50]
    mov     r1, #1
    bl      0x217e40                @ cursor back on New Adventure
    pop     {r5-r7, pc}
settings_row_flags:
    .byte   0x5b, 0, 0x5d, 0x5c, 0x5e, 0x5e
.align 2

@ r4 = menu, r0 = rows to show (4 or 6): frame size and rows 4-5.
settings_rows:
    push    {r5, r6, lr}
    mov     r5, r0
    mov     r0, r4
    mov     r1, #0
    bl      0x58223c                @ row group
    mov     r6, r0
    mov     r0, r4
    mov     r1, #6
    bl      0x5821e4                @ frame pane
    mov     r2, r0
    mov     r3, r6
    mov     r1, r5
    mov     r0, r4
    bl      0x581b40
    cmp     r5, #4
    movhi   r5, #1
    movls   r5, #0
    mov     r0, r4
    mov     r1, #4
    mov     r2, r5
    bl      0x581c94
    mov     r0, r4
    mov     r1, #5
    mov     r2, r5
    bl      0x581c94
    pop     {r5, r6, pc}

@ r4 = menu, r0 = row, r1 = msg_menu group 10 item, r2 = 1 to grey it out.
settings_row:
    push    {r5-r7, lr}
    mov     r5, r1
    mov     r6, r2
    mov     r1, r0
    mov     r0, r4
    bl      0x5821e4
    mov     r7, r0
    mov     r1, #4
    mov     r2, #10
    mov     r3, r5
    bl      0x217398
    mov     r0, r7
    mov     r1, r6
    bl      0x216a0c
    pop     {r5-r7, pc}

@ Replaces push {r4-r6,lr} of the title menu's A handler 0x21f0e4.
settings_select:
    ldr     r1, =STATE
    ldrb    r2, [r1, #3]
    cmp     r2, #1
    ldrbeq  r2, [r0, #0x58]
    cmpeq   r2, #0
    bne     settings_select_original
    push    {r4-r6, lr}
    mov     r4, r0
    mov     r5, r1
    ldr     r0, [r4, #0x50]
    ldr     r6, [r0, #4]            @ cursor row
    cmp     r6, #4
    blo     settings_select_toggle
    bne     settings_select_cancel
    ldrb    r0, [r5, #2]            @ Start Game
    bl      settings_new
    mov     r0, #0
    strb    r0, [r5, #3]
    mov     r0, #2
    strb    r0, [r4, #0x5a]
    mov     r0, #5
    strb    r0, [r4, #0x58]
    bl      0x5853ac                @ same call the original New Adventure path makes
    b       settings_select_done
settings_select_toggle:
    mov     r0, #1
    ldrb    r1, [r5, #2]
    eor     r1, r1, r0, lsl r6
    strb    r1, [r5, #2]
    mov     r0, r6
    add     r1, r6, #OPT_ITEM
    mov     r2, #0
    bl      settings_row            @ relabel: ON/OFF
    b       settings_select_done
settings_select_cancel:
    bl      settings_close
settings_select_done:
    mov     r0, #1
    pop     {r4-r6, pc}
settings_select_original:
    push    {r4-r6, lr}
    b       0x21f0e8

@ r0 = option bits. Rolls a seed 1..8191 from the system tick and stores
@ the packed settings (0 when no option was chosen) and the fusion flag.
settings_new:
    push    {r4, lr}
    ldr     r2, =STATE
    lsr     r1, r0, #3
    and     r1, r1, #1
    strb    r1, [r2, #STATE_FUSION]
    ands    r4, r0, #(OPT_ROAMING | OPT_SKILLSETS | OPT_BOSSES | OPT_FUSION)
    beq     settings_new_store
    and     r4, r4, #7
    svc     #0x28                   @ GetSystemTick -> r0:r1
    eor     r0, r0, r1
    ldr     r1, =0x9e3779b9
    mul     r0, r0, r1
    eor     r0, r0, r0, lsr #15
    ldr     r1, =8191
    umull   r2, r3, r0, r1          @ r3 = r0 * 8191 >> 32, 0..8190
    add     r3, r3, #1
    orr     r4, r4, r3, lsl #3
settings_new_store:
    ldr     r0, =STATE
    strh    r4, [r0]
    bl      tables_apply
    pop     {r4, pc}

@ Save loader (replaces add r4,r0,#0xd0). r0 = decrypted save image.
@ Only r4 is live afterwards (r0-r3 are reloaded by the caller).
settings_load:
    push    {r0, lr}
    ldrh    r2, [r0, #0xa8]
    ldr     r1, =SAVE_MAGIC
    sub     r2, r2, r1              @ 0 or 1 (fusion flag) for our saves
    cmp     r2, #1
    ldrhls  r3, [r0, #0xae]
    movhi   r3, #0
    movhi   r2, #0
    ldr     r1, =STATE
    strh    r3, [r1]
    strb    r2, [r1, #STATE_FUSION]
    bl      tables_apply
    pop     {r0, lr}
    add     r4, r0, #0xd0
    bx      lr

@ Save writer (replaces mov r1,r7). r6 = plaintext save header being built.
settings_save:
    ldr     r0, =STATE
    ldrh    r1, [r0]
    strh    r1, [r6, #0xae]
    ldrb    r1, [r0, #STATE_FUSION]
    ldr     r0, =SAVE_MAGIC
    add     r0, r0, r1
    strh    r0, [r6, #0xa8]
    mov     r1, r7
    bx      lr

@ Replaces the first instruction of get_msg(file r0, group r1, item r2):
@ msg_menu group 10 items OPT_ITEM..+5 are the options menu's rows.
settings_text_lookup:
    cmp     r0, #4
    cmpeq   r1, #10
    bne     settings_text_original
    subs    r3, r2, #OPT_ITEM
    blo     settings_text_original
    cmp     r3, #5
    bhi     settings_text_original
    ldr     r0, =TEXT_START_VA      @ row 4: Start Game
    addeq   r0, r0, #(TEXT_CANCEL_VA - TEXT_START_VA)   @ row 5: Cancel
    cmpne   r3, #4
    bxeq    lr
    push    {r4, lr}                @ option row r3: "Random <name>: ON/OFF"
    add     r1, r0, #(TEXT_RANDOM_VA - TEXT_START_VA)
    ldr     r4, =STATE
    ldrb    r4, [r4, #2]
    lsr     r4, r4, r3
    ldr     r0, =STATE_TEXT
    bl      text_append             @ leaves r1 at the names, which follow
text_skip:
    subs    r3, r3, #1              @ skip to the r3-th name
    bmi     text_skip_done
text_skip_loop:
    ldrb    r2, [r1], #1
    cmp     r2, #0
    bne     text_skip_loop
    b       text_skip
text_skip_done:
    bl      text_append
    tst     r4, #1
    ldr     r1, =TEXT_ON_VA
    addeq   r1, r1, #(TEXT_OFF_VA - TEXT_ON_VA)             @ ": OFF" follows ": ON"
    bl      text_append
    ldr     r1, =0x1be3             @ E3 1B: end of message
    strh    r1, [r0]
    ldr     r0, =STATE_TEXT
    pop     {r4, pc}
settings_text_original:
    ldr     r3, =0x6fd000
    b       0x1e1124

@ r0 = destination, r1 = zero-terminated piece -> both advanced past it.
text_append:
    ldrb    r2, [r1], #1
    cmp     r2, #0
    strbne  r2, [r0], #1
    bne     text_append
    bx      lr
.ltorg
