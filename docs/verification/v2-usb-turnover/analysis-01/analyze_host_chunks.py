"""Offline host-delivery grouping only; never opens a device or decodes wire/CRC."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import statistics
import struct

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
HEADER = struct.Struct("<BdI")
sources = {}


def read(relative):
    data = (ROOT / relative).read_bytes()
    sources[relative] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
    return data


def document(relative):
    return json.loads(read(relative))


def chunks(relative):
    raw = read(relative)
    offset, rows = 0, []
    while offset < len(raw):
        direction, stamp, count = HEADER.unpack_from(raw, offset)
        assert direction in (0, 1) and count > 0
        offset += HEADER.size
        assert offset + count <= len(raw)
        # Deliberately skip payload; previous evidence owns frame/CRC validation.
        offset += count
        rows.append({"direction": direction, "host_monotonic": stamp, "bytes": count})
    assert offset == len(raw)
    origin = rows[0]["host_monotonic"]
    for row in rows:
        row["host_relative_seconds"] = row["host_monotonic"] - origin
    return rows


def gap_summary(rows):
    gaps = [(b["host_monotonic"] - a["host_monotonic"]) * 1000
            for a, b in zip(rows, rows[1:])]
    assert all(g >= 0 for g in gaps)
    return {"read_count": len(rows), "wire_bytes": sum(r["bytes"] for r in rows),
            "length_histogram": dict(sorted(Counter(r["bytes"] for r in rows).items())),
            "full_544_reads": sum(r["bytes"] == 544 for r in rows),
            "gap_max_ms": max(gaps), "gap_median_ms": statistics.median(gaps),
            "span_ms": (rows[-1]["host_monotonic"] - rows[0]["host_monotonic"]) * 1000}


trials = {}
for name in ("v6f-board-01", "v6g-board-01"):
    prefix = "build/" + name
    rows = chunks(prefix + "/run/traffic.bin")
    prior = document(prefix + "/wire-failure-analysis.json")
    result = document(prefix + "/run/result.json")
    assert sources[prefix + "/run/traffic.bin"]["sha256"] == prior["traffic_sha256"]
    timeline = prior["timeline"]
    first = next(e for e in timeline if e["kind"] == "DATA")["host_relative_seconds"]
    end = next(e for e in timeline if e["kind"] == "END")["host_relative_seconds"]
    rx = [r for r in rows if r["direction"] == 1]
    data_window = [r for r in rx if first <= r["host_relative_seconds"] <= end]
    largest_pair = max(zip(rx, rx[1:]), key=lambda ab: ab[1]["host_monotonic"] - ab[0]["host_monotonic"])
    trials[name] = {
        "physical_status": result["status"], "nonce_hex": prior["nonce_hex"],
        "build_id": prior["observed_build_id"], "generation": prior["generation"],
        "all_nonempty_reads": gap_summary(rx),
        "first_DATA_to_END_nonempty_reads": gap_summary(data_window),
        "largest_all_reads_gap_pair": largest_pair,
        "largest_gap_is_before_first_DATA": largest_pair[1]["host_relative_seconds"] < first,
        "first_DATA_host_seconds": first, "END_host_seconds": end,
        "reported_max_owner_service_gap_ms": result["before_stop"]["max_service_gap_ms"],
        "reported_peak_disk_queue_items": result["before_stop"]["peak_raw_items"],
        "chunks": rows,
        "limit": "Nonempty backend.read completion stamps, including Stop drain; not ADC, USB transaction, URB, host-stall or sustained-throughput timestamps. Empty reads and call durations were not logged.",
    }

profile = document("build/v6f-board-01/profile-decoded.json")
gdiag = document("build/v6g-board-01/diagnostics-decoded.json")
header, private, counters = profile["header"], profile["private_raw"], profile["counters"]
delta = lambda a, b: (a - b) & 0xffffffff
last_in_after_adc = delta(private["last_IN_cycle"], private["phase_start"])
last_in_before_close = delta(header["end_before"], private["last_IN_cycle"])
assert private["phase_id"] == 2 and private["phase_open"] == 1
assert last_in_after_adc + last_in_before_close == profile["partial_intervals_at_close"]["phase"]["cycles_to_close"]

code_paths = [
    "host/motortester/stream_serial.py", "host/motortester/transport.py",
    "host/motortester/stream_controller.py", "host/motortester/v2/stream_device.py",
    "host/tools/v2_stream_probe.py", ".venv/Lib/site-packages/serial/serialwin32.py",
    "build/v6g-fw-02/config.json", "build/v6g-fw-02/patched/v2/app/mt_live_runtime.c",
    "build/v6g-fw-02/patched/v2/boot/tusb_config.h",
    "build/v6g-fw-02/patched/usbd.c", "build/v6g-fw-02/patched/dcd_stm32_fsdev.c",
    "build/v6f-fw-03/patched/dcd_stm32_fsdev.c",
    "build/v6g-fw-02/source/firmware/third_party/usb/vendor/tinyusb/src/class/cdc/cdc_device.c",
    "build/v6g-fw-02/source/firmware/third_party/usb/vendor/tinyusb/src/tusb.c",
]
for path in code_paths:
    read(path)
receipt = document("build/v6g-fw-02/receipt.json")
dependency_matches = {}
for path in code_paths:
    expected = receipt["dependencies"].get(str(ROOT / path))
    if expected is not None:
        dependency_matches[path] = expected == sources[path]["sha256"]
assert all(dependency_matches.values())

report = {
    "schema": "v2-06h-host-usb-offline-findings-1",
    "scope": "Read-only saved F2/G2 host grouping and source analysis; no device, no new trial, no production changes, no repeated raw/CRC/fresh-open verification.",
    "physical_100ksps_status": "FAIL_UNRESOLVED",
    "hypothesis": {
        "id": "foreground_final_IN_turnover",
        "statement_ru": "Основная рабочая гипотеза: стоимость полного foreground-прохода между завершением короткой CDC IN-передачи и запуском следующей удерживает средний темп выгрузки ниже поступления DATA128; частые ZERO_SPACE — следствие этого обслуживания. Она согласуется с F2, но причина всех задержек USB и применимость к G2 ещё не доказаны.",
        "confidence": "source-backed plausible mechanism, not isolated physical root cause",
        "host_read_change_recommended_now": False,
        "why_not_host_stall_claim": "Python read completions do not expose USB IN/NAK, outstanding usbser URBs, queue fill or scheduler stalls.",
    },
    "trials": trials,
    "host_source_facts": {
        "read_timeout_seconds": 0, "maximum_read_bytes": 544,
        "partial_read_wait_target_seconds": 0.001, "full_reads_before_yield": 8,
        "pyserial_readfile": "ClearCommError cbInQue; n=min(cbInQue,544); n=0 skips ReadFile; n>0 calls ReadFile and waits GetOverlappedResult before returning. No application ReadFile remains pending between owner iterations.",
        "driver_URBs_between_application_reads": "TBD; absence of application ReadFile is not absence of driver-owned USB requests.",
        "SetupComm_recommended_input_bytes": 4096,
        "SetupComm_actual_driver_buffer_bytes": None,
        "probe_audit": "Two buffered local-file writes run in receiver after each nonempty backend.read. Neither duration nor empty polls is logged. Normal GUI does not use this audit wrapper.",
        "disk_UI": "Separate workers; Qt20ms is not acquisition polling. Saved peak raw disk queue=4 in both trials, not an observed disk-backlog overflow.",
    },
    "nominal_budget_arithmetic": {
        "samples_per_second": 100000, "samples_per_DATA": 128,
        "DATA_interval_ms": 1.28, "DATA_frames_per_second": 781.25,
        "observed_DATA_frame_bytes": 307, "wire_bytes_per_second_at_307": 239843.75,
        "raw_bytes_per_second": 200000, "queue_8_DATA_duration_ms": 10.24,
        "qualification": "Arithmetic, not measured sustained throughput, ADC timing or USB guarantee; queue slots do not include all transport/ADC staging.",
    },
    "F2_existing_diagnostic_evidence": {
        "window_nominal_us": profile["window"]["elapsed_us_nominal"],
        "counters": counters, "first_event": profile["first_event"],
        "last_IN_in_open_ADC_phase": True,
        "last_IN_after_ADC_phase_begin_cycles": last_in_after_adc,
        "last_IN_after_ADC_phase_begin_nominal_us": last_in_after_adc / 72,
        "last_IN_before_first_close_cycles": last_in_before_close,
        "last_IN_before_first_close_nominal_us": last_in_before_close / 72,
        "inference": "At first close, published/completed bytes match and the last packet completion hook lies inside the still-open ADC phase. This fits a final-IN event awaiting the next foreground task turn while core DATA remains queued. Neither FIFO occupancy nor every completion/republication interval was directly recorded.",
        "qualification": "S9 instrumented nominal DWT evidence; retain observer cost/overlap caveats. No CPU percentage summation and no equivalence with uninstrumented SA timing.",
    },
    "G2_existing_diagnostic_limits": {
        "active_512byte_profile": False,
        "queue_high_water": gdiag["raw"]["queue_high_water"],
        "first_acquisition_reason": gdiag["raw"]["first_acquisition_reason"],
        "tx_max_excludes_prepare_encode": True,
        "limit": "Legacy136 maxima extend through drain; no first-close time series. Longer prefix is not measured acceleration.",
    },
    "next_discriminator_not_executed": "A future authorized bounded observation would distinguish final-IN→task callback→next publication latency from host URB/NAK availability. Do not change host polling, driver buffers, queue depth and firmware scheduling together. Current evidence supports examining firmware foreground turnover first; it does not authorize a new trial.",
    "primary_web_sources": [
        {"url": "https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-commtimeouts", "supports": "MAXDWORD/0/0 read returns already buffered bytes immediately."},
        {"url": "https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setupcomm", "supports": "4096 is a requested recommendation; driver buffering implementation is not established by SetupComm."},
        {"url": "https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-bulk-and-interrupt-transfer", "supports": "A driver may initiate USB requests itself; application read timing alone cannot locate bus scheduling delays."},
    ],
    "build_dependency_hash_matches": dependency_matches,
    "sources": sources,
}
report["originals_unchanged"] = all(
    sha256((ROOT / path).read_bytes()).hexdigest() == info["sha256"]
    for path, info in sources.items())
assert report["originals_unchanged"]
report["analysis_script_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
(OUT / "host-findings.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"trials": {k: v["first_DATA_to_END_nonempty_reads"] for k, v in trials.items()},
                  "last_IN_before_close_us": last_in_before_close / 72,
                  "originals_unchanged": report["originals_unchanged"]}, indent=2))
