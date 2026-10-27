"""V2 build assumptions, deliberately distinct from historical attestations."""
import json


def generate(raw):
    config = json.loads(raw)
    expected = {
        "schema", "firmware_build", "flash_bytes", "ram_bytes", "stack_reserve_bytes",
        "assumed_hse_hz", "assumed_hse_mode", "assumed_fixed_usb_pullup",
        "board_assumptions_verified", "clock_poll_budget", "usb_irq_priority",
        "require_dtr", "provisional_transaction_bound_ms",
        "transaction_bound_measured", "diagnostics", "active_profile_enabled", "usb",
        "nominal_sample_rate_hz", "adc_sample_cycles_x2", "dma_samples",
        "data_samples", "queue_slots", "acquisition_modes",
        "cdc_tx_fifo_bytes", "cdc_tx_transfer_bytes", "usb_tx_burst_packets", "usb_tx_burst_limit_us",
    }
    if set(config) != expected or config["schema"] != "motortester-v2-stream-build-1":
        raise ValueError("Unsupported V2 build configuration")
    fixed = {
        "firmware_build": 0x56325348, "flash_bytes": 65536, "ram_bytes": 20480,
        "cdc_tx_fifo_bytes": 384, "cdc_tx_transfer_bytes": 384,
        "usb_tx_burst_packets": 6, "usb_tx_burst_limit_us": 500,
        "nominal_sample_rate_hz": 100000, "adc_sample_cycles_x2": 83, "acquisition_modes": [1,2,3,4,5],
        "dma_samples": 1024, "data_samples": 128, "queue_slots": 8,
        "stack_reserve_bytes": 8192, "assumed_hse_hz": 8000000,
        "assumed_hse_mode": "crystal", "assumed_fixed_usb_pullup": True,
        "board_assumptions_verified": False, "clock_poll_budget": 1000000,
        "usb_irq_priority": 0, "require_dtr": True,
        "provisional_transaction_bound_ms": 1, "transaction_bound_measured": False,
        "diagnostics": True, "active_profile_enabled": False,
    }
    for name, value in fixed.items():
        if type(config[name]) is not type(value) or config[name] != value:
            raise ValueError("Review required before changing configuration: " + name)
    usb = config["usb"]
    if set(usb) != {"vid", "pid", "bcd_device", "bus_power_ma",
                    "manufacturer", "product", "serial"}:
        raise ValueError("Unexpected USB configuration")
    for name, expected in {"vid": 0x1209, "pid": 1, "bcd_device": 0x0200,
                            "bus_power_ma": 100}.items():
        if type(usb[name]) is not int or usb[name] != expected:
            raise ValueError("Review required before changing USB: " + name)
    for name in ("manufacturer", "product", "serial"):
        if (type(usb[name]) is not str or not 1 <= len(usb[name]) <= 31
                or any(ord(c) < 32 or ord(c) > 126 for c in usb[name])):
            raise ValueError("Invalid USB ASCII string: " + name)
    if not usb["serial"].isascii() or not usb["serial"].isalnum():
        raise ValueError("Serial must be ASCII alphanumeric")
    # Legacy struct member names are ABI, NOT evidence. No caller attestations
    # are generated. A hardware experiment requires a separate reviewed receipt.
    lines = [
        "/* V2 transport candidate. Board/clock assumptions NOT VERIFIED. */",
        "/* Legacy verified_* names below carry configuration, not measurements. */",
        '#include "mt_board_inputs.h"',
    ]
    for name in ("manufacturer", "product", "serial"):
        values = ", ".join(str(ord(c)) for c in usb[name]) + ", 0"
        lines.append(f"static const char v2_{name}[] = {{{values}}};")
    lines.extend([
        "const mt_board_inputs mt_board = {",
        " .verified_hse_hz = 8000000u, .hse_mode = MT_CLOCK_CRYSTAL,",
        " .clock_poll_budget = 1000000u, .usb_irq_priority = 0u,",
        " .firmware_build = 0x56325348u, .require_dtr = 1u,",
        " .verified_fixed_pullup = 1u,",
        " .usb = {.vid = 0x1209u, .pid = 1u, .bcd_device = 0x0200u,",
        " .bus_power_ma = 100u, .manufacturer = v2_manufacturer,",
        " .product = v2_product, .serial = v2_serial}",
        "};",
    ])
    timing = (
        "/* Provisional 1 ms scheduling estimate; NOT measured WCET. */\n"
        '#include "mt_stream_timing.h"\n'
        "const mt_stream_timing_inputs mt_stream_timing = {1u, 1u, 1u};\n"
    )
    return config, "\n".join(lines) + "\n", timing
