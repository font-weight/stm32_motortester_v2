# N: compact first-close progress record v1

Draft27.10.2026;64 bytes, little-endian, one foreground writer, no ISR writer,
no second static/private/scratch bank. Native timestamps are synthetic seams;
the target reads DWT_CYCCNT directly, never adds TIME health loops.

| Offset | Type | Field |
|---:|---|---|
|0 |u32 |magic/version `0x4d544e31` |
|4 |u32 |flags: state low3bits, validity/history bits3..15; primary reason high16 |
|8 |u32 |generation |
|12,16 |u32,u32 |nonce low/high |
|20,24 |u32,u32 |begin/end modulo DWT cycles |
|28 |u32 |sum of completed prepare spans, inclusive of IRQ |
|32 |u32 |known DATA bytes accepted by FIFO callback |
|36 |u32 |latest positive DATA acceptance DWT; begin if none |
|40 |u32 |max interval without positive DATA acceptance, including close tail |
|44,46 |u16,u16 |completed prepare count / positive DATA callback count |
|48,50 |u16,u16 |zero due to actual insufficient FIFO space / other known zero |
|52,54 |u16,u16 |core TX offset/length at close |
|56,58 |u16,u16 |staging sample count / available FIFO bytes at close |
|60,61 |u8,u8 |staging phase / queue used slots |
|62,63 |u8,u8 |USB snapshot bits / close kind |

Normative masks/enums are in `mt_stream_progress.h`. Build is deliberately
not repeated in64B: require the companion136B record matching nonce/generation,
the generated target build, exact image/ELF/source pins and two identical frozen copies.
An unpaired record cannot authenticate build or hardware. Core snapshot flag
is independent of USB_VALID bit. Invalid/unavailable snapshot fields use
tx_offset/tx_length/stage_count/fifo_free=65535 and phase/queue=255. No valid
FIFO snapshot must be presented as zero free bytes. USB bits other than0..3
are invalid.

SI build binding: `config.json.firmware_build` generates the sole shared
`mt_firmware_build.h` used by board.c and this observer. With the observer
enabled, missing header/macro is a compilation error; no SG/default fallback.
`MT_N_BUILD` is an alias of that generated value, not a second independent id.
Record layout, counters, first-close/late-write and one-attempt-per-boot rules
are unchanged. Saved SG/SH sources/images remain immutable: SH's compiled
SG build gate rejected binding, so its zero64 cannot be decoded as valid data.

Typed close kinds distinguish queue/source/local recovery/Stop/cap/transport/
ADC/HELLO/no-start/unavailable; high16 is the passed primary reason in that
kind's domain, not a universal fault enum:

| Kind | Primary domain and admitted values |
|---|---|
|1 QUEUE |acquisition reason1 |
|2 SOURCE |acquisition reason1..6 |
|3 RECOVERY |local MT_LIVE_ERR1..7; CLOCK2 is normally classified TIME |
|4 STOP,5 CAP,8 HELLO |0 |
|6 TRANSPORT |local MT_LIVE_ERR_TRANSPORT3 |
|7 ADC |actual driver fault1..8, before driver quiesce; not acquisition-reason enum |
|9 NO_START |0 for refused start |
|10 UNAVAILABLE |0, legacy DWT/setup not usable for this trace |
|11 TIME |local MT_LIVE_ERR_CLOCK2 |

START_ACK_PENDING is a close-time `core.want_start` snapshot only when
CORE_SNAPSHOT is present; otherwise it is unavailable regardless of bit value.

Begin occurs immediately after successful `io.start`, before the following
core `now`/queue initialization and before START_ACK acceptance. Thus a later
clock failure cannot hide an already successful hardware start.
START_ACK_PENDING explicitly records that initial condition until close.
A failed attempt may freeze NO_START with the attempted identity and no
active duration. NO_ACTIVE_START means no ACTIVE observation window, not a
claim that ADC hardware never started: UNAVAILABLE can follow successful ADC
start while telemetry setup failed. An ARMED close preserves its original
typed kind/primary (for example TIME/CLOCK2), with NO_ACTIVE_START; it is never
rewritten into another primary domain. Every NO_ACTIVE_START record has zero raw begin,
end,prepare sum/count,positive bytes/count,last-positive,gap,zero counts and no
HAVE_POSITIVE/PREPARE_OPEN/PARTIAL_PREPARE. Snapshot fields may still be valid.
First close changes ACTIVE→CLOSING before any snapshot,
then publishes FROZEN last; no later callback, epilogue or checkpoint writes.
One attempt per boot, no HELLO rearm. Core close is before terminate/recover/
transport cleanup; an ACTIVE ADC driver fail closes before quiesce, with
unavailable core metadata if that hook cannot safely identify a device.
Before begin, a driver failure inside start has no bound device/active window:
the NULL-device ADC hook leaves EMPTY unchanged, and the later refused-start
hook freezes NO_START. The original first ADC cause then remains in legacy136;
N does not claim to preserve that pre-ACTIVE driver event or its timing.

Prepare includes all actual prepare calls, cached fast returns and EMPTY
collection alike; it excludes guarded submit. An open prepare at close sets
PARTIAL_PREPARE/PREPARE_OPEN and is excluded from completed sum/count. Its
duration is unavailable; late prepare_end cannot publish it. Completed sums
are inclusive wall-cycle observations, not disjoint CPU time or percentages.

Write measurements apply only to DATA callbacks. known accepted bytes include
positive partial results; PARTIAL_WRITE remembers any 0<accepted<offered.
SIZE_MAX/over-acceptance sets UNKNOWN_WRITE without adding bytes. Actual
space-short return in live_write marks the current call; write_end classifies
one known zero as space or other and never double-counts it. This transient
marker also lives in the64B flags; late exits do not clear a frozen marker.
No positive is represented by absence of HAVE_POSITIVE, not a zero duration:
the initial and unfinished gap begins at begin_cycle and is included at close.
FIFO acceptance is neither USB delivery nor committed sample prefix; control
frames/drain after close are excluded. Saturated counters/sums set SATURATED.

250ms is a target observation checkpoint (18,000,000 nominal72MHz cycles),
not a hard limit or command stopping ADC. end is actual observed close time;
positive cap overshoot is explicit. CAP_OVERSHOOT is set only for kind CAP
when actual elapsed>CAP; valid CAP has elapsed>=CAP. A different first cause
can close after the target without this flag; its actual elapsed is retained.
Other first faults win if observed before
the next cap checkpoint. A single modulo difference requires externally
verified absence of DWT halt/reset and <one full2^32-cycle wrap. Legacy DWT
unavailable/invalid flags invalidate cycle interpretation; no correction is
subtracted for observer overhead. The actual observer still changes timing.

Snapshot uses the existing save/restore guard and safe application actor scope
for read-only FIFO/task/held observations; no dispatch, flush, ADC_DR access or
USB transfer submission. Snapshot work occurs only after the first cause is
latched, before cleanup, and does not turn that failure into an accepted run.
Final layout/ELF/stack/hooks and one targeted native witness remain to verify.
