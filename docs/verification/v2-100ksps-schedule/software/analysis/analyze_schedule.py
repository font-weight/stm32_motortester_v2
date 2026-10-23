"""Read-only source accounting and failed-run comparison; no device I/O."""
from pathlib import Path
import difflib, hashlib, json, re

root = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
images = {"S4": root / "build/v5-fw-10", "S7": root / "build/v6d-fw-01"}
boards = {"S4": root / "build/v5-board-stream-04", "S7": root / "build/v6d-board-01"}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def function(source, name):
    # These exact reviewed sources use a brace-delimited function definition.
    match = re.search(r"(?:^|\n)(?:static )?[^\n;{}]*\b" + name + r"\([^;{}]*\)\s*\{", source)
    if not match:
        raise ValueError(name)
    begin = source.index("{", match.start())
    level = 1
    pos = begin + 1
    while level:
        level += (source[pos] == "{") - (source[pos] == "}")
        pos += 1
    return source[begin:pos]

sources = {}
pins = {}
for tag, image in images.items():
    for short, relative in {
        "runtime": "patched/v2/app/mt_live_runtime.c",
        "adc_adapter": "patched/v2/app/mt_live_adc.c",
        "adc_driver": "patched/v2/platform/adc_timer_dma.c",
        "core": "patched/v2/protocol/mt_live_device.c",
        "time": "source/firmware/platform/mt_timebase.c",
        "live_clock": "source/firmware/platform/mt_live_clock.c",
    }.items():
        path = image / relative
        sources[tag, short] = path.read_text("utf8")
        pins[str(path.relative_to(root))] = sha(path)
    for name in ("MotortesterV2-stream-candidate.elf", "MotortesterV2-stream-candidate.bin"):
        pins[str((image / name).relative_to(root))] = sha(image / name)

s4step = function(sources["S4", "runtime"], "step")
s7step = function(sources["S7", "runtime"], "step")
extra_before = """    if(!synchronize_loss(r))return loss_result(r);
    if(adc_checkpoint(r)==-2)return MT_LIVE_RUNTIME_ARGUMENT;
    if(live_time(r)==UINT64_MAX)return time_fault(r);
"""
extra_after = """    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(adc_checkpoint(r)==-2)return MT_LIVE_RUNTIME_ARGUMENT;
"""
assert s7step.count(extra_before) == 2 and s7step.count(extra_after) == 1
proposed_step = s7step.replace(extra_before, "", 1).replace(extra_after, "", 1)
assert proposed_step == s4step, "Proposed schedule must be exact S4 step, not a redesign"
assert len(re.findall(r"\blive_time\(r\)", s4step)) == 6
assert len(re.findall(r"\blive_time\(r\)", s7step)) == 8

unchanged_runtime = {}
for name in ("adc_read", "adc_write", "adc_time", "live_time", "stable", "usable",
             "commit_enter", "commit_leave", "commit_allowed", "commit_timed",
             "commit_timer", "live_start", "live_stop", "live_isolate", "prepare_adc",
             "mt_live_runtime_init", "quiescent", "loss_result", "synchronize_loss",
             "time_fault", "mt_live_runtime_step"):
    a, b = function(sources["S4", "runtime"], name), function(sources["S7", "runtime"], name)
    unchanged_runtime[name] = {"identical": a == b, "S4_sha256": hashlib.sha256(a.encode()).hexdigest(),
                               "S7_sha256": hashlib.sha256(b.encode()).hexdigest()}

rows = []
for case, core_now, ready in (("empty_DMA_with_DATA_offer_or_known_zero", 5, False),
                              ("one_ready_DMA_half_with_DATA_offer", 5, True),
                              ("empty_DMA_no_TX_pending", 2, False)):
    for profile, runtime_now, services, chunks in (("S4_50k", 6, 1, 1), ("S7_100k", 8, 3, 4),
                                                   ("proposed_S8_100k_S4_schedule", 6, 1, 4)):
        offers = chunks if ready else 0
        driver_times = services + int(ready)
        updates = runtime_now + core_now + offers + 2 * services + driver_times
        rows.append({"case": case, "profile": profile,
                     "runtime_live_time_snapshots": runtime_now, "core_now_snapshots": core_now,
                     "offer_now_snapshots": offers, "adapter_clock_ok_updates": 2 * services,
                     "driver_now_us_updates": driver_times,
                     "total_full_TIME_updates": updates, "TIME_MMIO_reads": 27 * updates,
                     "direct_driver_MMIO_reads": 10 * services + 2 * int(ready),
                     "direct_driver_MMIO_writes": int(ready),
                     "scope": "Healthy streaming, open actor, no RX, no ISR/task callback additional work; not CPU timing."})

facts = {}
for tag, board in boards.items():
    diag = json.loads((board / "diagnostics-decoded.json").read_text("utf8"))["raw"]
    elapsed = (diag["freeze_cycle"] - diag["start_cycle"]) & 0xffffffff
    facts[tag] = {"diagnostics": diag, "whole_protocol_interval_us_at_nominal_72MHz": elapsed / 72,
                  "whole_protocol_mean_step_us_not_active_only": elapsed / 72 / diag["step_count"],
                  "tx_max_us_at_nominal_72MHz": diag["tx_max_cycles"] / 72,
                  "scope": "Includes START, source-stop and queued-data drain; not steady throughput or WCET."}
    pins[str((board / "diagnostics-first.bin").relative_to(root))] = sha(board / "diagnostics-first.bin")

report = {"schema": "v2s7-schedule-causal-review-1", "source_pins": pins,
          "exact_S4_schedule_reconstruction_from_S7": proposed_step == s4step,
          "unchanged_runtime_functions": unchanged_runtime,
          "full_TIME_update": {"clock_matches_before_after": 4 * 2,
                               "timer_matches_before_after": 9 * 2, "counter": 1,
                               "MMIO_reads": 27, "healthy_cached_predicate_MMIO": 0},
          "healthy_loop_accounting": rows, "physical_comparison": facts,
          "S7_first_queue_full_inference": {
              "successfully_copied_DMA_halves": 6, "copied_samples": 3072,
              "retained_samples_after_drain": 2944, "retained_DATA_blocks": 23,
              "queue_slots_at_rejected_push": 8,
              "DATA_blocks_popped_before_rejected_push": 15,
              "samples_popped_before_rejected_push": 1920,
              "derivation": "23 successful pushes - 8 still queued at first full = 15 full DATA commits before fault; later drain preserves the queued prefix.",
              "limit": "Full DATA commit means accepted by device transport, not necessarily already received by PC. Frozen diagnostics do not timestamp first full."},
          "removed_in_S4_schedule": [
              "Two extra ADC opportunities (before tud_task, after TX).",
              "Two additional live_time+synchronize_loss barriers paired with those opportunities.",
              "Earlier observation at those two sites; detection can move to the next retained barrier."],
          "preserved_in_S4_schedule": [
              "Complete original S4 step function; time_fault/synchronize_loss/stable/usable functions are unchanged.",
              "TIME/loss before and after tud_task, after RX, after TX, after flush; ADC service+clock checks before RX/TX.",
              "ADC deadline/clock/gates/sticky DMA flags/ownership before and after copy; S7 5120us deadline remains.",
              "Stop input handling before TX, lifecycle/epoch checks for app and FIFO operations, final IRQ fairness gate.",
              "Core full transaction IRQ guard and all five timing observations, irreversible accepted-prefix semantics.",
              "S7 whole-fit, FIFO384, bounded USB IN continuation, Stop tail and fail-closed source stop are unchanged."],
          "judgment": {
              "result": "Evidence supports testing exact S4 schedule with S7 transport at 100k; not a guarantee of 100k throughput.",
              "reason": "Removes measured-by-source redundant ADC/TIME work instead of a fourth rate reduction. Existing physical failure is queue-full, not ADC deadline or transport CRC loss.",
              "counter_evidence": "S7 TX max638.7us and whole-step max3221.4us cannot establish active-only execution cost or WCET. IRQ grant expiry frequency remains unknown.",
              "if_new_candidate_fails": "Do not lower rate again blindly. First add active phase/zero-write/first-full/IRQ hold-cause counters and freeze onset, then choose a measured optimization.",
              "not_proved": ["fraction of CPU spent in TIME versus CRC/COBS/USB", "active-only mean DATA service rate", "historical IN burst grant expiry", "physical 100k qualification"]}}
(out / "schedule-analysis.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
(out / "step-S4-S7.diff").write_text("".join(difflib.unified_diff(s4step.splitlines(True), s7step.splitlines(True), fromfile="S4 exact step", tofile="S7 exact step")), encoding="utf8")
print(json.dumps({"exact_S4_schedule": report["exact_S4_schedule_reconstruction_from_S7"],
                  "changed_runtime_functions": [n for n, v in unchanged_runtime.items() if not v["identical"]],
                  "accounting": rows, "S7_first_queue_full_inference": report["S7_first_queue_full_inference"]}, indent=2))
