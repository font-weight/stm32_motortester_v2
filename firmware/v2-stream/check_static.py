"""Conditional linked-image stack/ABI census; no hardware or timing certificate.

The callback target unions come from the pinned upstream constructors and CDC
registration, not a heuristic that an unobserved function pointer cannot execute.
Unrecognised indirect calls, PC/SP writes, non-static frames and recursion fail.
"""
import argparse
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normal(name):
    return re.sub(r"\.(isra|constprop)\.\d+", r".\1", name.removeprefix("startup."))


# Conservative unions for every indirect site in an owner function. Choosing a
# larger union may inflate the bound; it never drops a legitimate constructor.
# Fixed source: mt_stream_main, mt_live_runtime, mt_live_adc, mt_usb_bridge,
# mt_timebase, patched TinyUSB usbd.c, foreground-only mt_stream_diag.
CALLBACKS = {
    "rd": ["adc_read", "mt_clock_mmio_read32"],
    "wr": ["adc_write", "mt_clock_mmio_write32"],
    "now": ["adc_time", "live_time"],
    "start": ["commit_allowed", "commit_enter", "commit_leave", "commit_timed", "commit_timer"],
    "commit_timer": ["mt_clock_mmio_read32"],
    "write_reg": ["mt_clock_mmio_write32"],
    "read_reg": ["mt_clock_mmio_read32"],
    "update": ["mt_clock_mmio_write32"],
    "mt_timebase_update": ["mt_clock_mmio_read32"],
    "mt_timebase_init": ["mt_clock_mmio_read32"],
    "mt_timebase_stop": ["mt_clock_mmio_read32"],
    "mt_usb_bridge_lock": ["mt_irq_guard_enter"],
    "mt_usb_bridge_unlock": ["mt_irq_guard_leave"],
    "configuration_reset": ["cdcd_reset"],
    "invoke_class_control.constprop.isra": ["cdcd_control_xfer_cb"],
    "queue_event_epoch.isra": ["usbd_int_set"],
    "tud_rhport_init": ["cdcd_init"],
    "tud_deinit": ["cdcd_deinit"],
    "usbd_spin_lock": ["usbd_int_set"],
    "usbd_spin_unlock": ["usbd_int_set"],
    "tud_task_ext": ["cdcd_control_xfer_cb", "cdcd_open", "cdcd_xfer_cb",
                     "tud_vendor_control_xfer_cb", "usbd_int_set"],
    "mt_boot_time_start": ["mt_clock_mmio_write32"],
    "adc_read": ["mt_clock_mmio_read32"],
    "adc_write": ["mt_clock_mmio_write32"],
    "raw_barrier": ["live_stop"],
    "terminate": ["live_stop"],
    "accept_frame": ["live_isolate", "live_start", "live_stop"],
    "mt_live_device_step": ["live_write"],
    "mt_stream_diag_cycle": ["mt_clock_mmio_read32"],
    "mt_stream_diag_init": ["mt_clock_mmio_read32", "mt_clock_mmio_write32"],
}
ROOTS = ("Reset_Handler", "USB_HP_CAN1_TX_IRQHandler", "USB_LP_CAN1_RX0_IRQHandler",
         "Default_Handler")
BRANCH = r"b(?:eq|ne|cs|cc|hs|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)?(?:\.[nw])?"
INSTRUCTION = re.compile(
    r"^\s*([0-9a-f]+):\s+((?:(?:[0-9a-f]{4}|[0-9a-f]{8})\s+)+)\s*([^\s]+)\s*(.*)$")


def analyze(out):
    core_path = out / "source/tests/boot-link/tools/run_boot_link_tests.py"
    spec = importlib.util.spec_from_file_location("v2_boot_core", core_path)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    elf_path = out / "MotortesterV2-stream-candidate.elf"
    elf = core.ELF(elf_path)
    receipt = json.loads((out / "receipt.json").read_text("utf-8"))
    require(sha(elf_path) == receipt["artifacts"][elf_path.name], "Receipt ELF mismatch")
    for row in receipt["objects"]:
        require(sha(out / row["path"]) == row["sha256"], "Object changed: " + row["path"])
    for path, expected in receipt["inputs_before"].items():
        require(sha(Path(path)) == expected, "Build input changed: " + path)
    required_analysis = {"image.map", "image.dis", "image.nm"}
    required_analysis.update(p.relative_to(out).as_posix() for p in (out / "objects").glob("*.su"))
    require(set(receipt["analysis_inputs"]) == required_analysis, "Incomplete analysis manifest")
    for path, expected in receipt["analysis_inputs"].items():
        require(sha(out / path) == expected, "Analysis input changed: " + path)
    # Input section ranges include anonymous retained weak bodies which nm or
    # objdump function labels alone omit. No GC means every such body is checked.
    functions, pending = {}, None
    for line in (out / "image.map").read_text("utf-8").splitlines():
        match = re.match(r"^ (\.text(?:\.\S+)?)\s*$", line)
        if match:
            pending = match[1]
            continue
        match = re.match(r"^ (\.text(?:\.\S+)?)\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+\.o)$", line)
        if match:
            section, address, size, obj = match.groups()
        else:
            match = re.match(r"^\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+\.o)$", line)
            if not (match and pending):
                continue
            address, size, obj = match.groups()
            section = pending
        pending = None
        if int(size, 16):
            address = int(address, 16)
            require(address not in functions, "Overlapping function starts")
            functions[address] = {"name": section[6:].removeprefix("startup."),
                                  "size": int(size, 16), "object": obj, "ins": {}}
    require(functions, "No map code ranges")
    frames = {}
    for path in (out / "objects").glob("*.su"):
        rows = {}
        for line in path.read_text("utf-8").splitlines():
            loc, size, kind = line.split("\t")
            require(kind in ("static", "static,ignoring_inline_asm"), "Non-static frame: " + line)
            rows[normal(loc.rsplit(":", 1)[1])] = int(size)
        obj = path.relative_to(out).with_suffix(".o").as_posix()
        for address, function in functions.items():
            if function["object"] == obj:
                name = normal(function["name"])
                require(name in rows, "Missing .su frame: " + function["name"])
                frames[address] = rows[name]
    for address, function in functions.items():
        if function["object"] == "objects/reset.o":
            require(function["name"] in ("Reset_Handler", "Default_Handler"), "Unexpected assembly")
            frames[address] = 0
        require(address in frames, "Unmapped stack frame: " + function["name"])
    disassembly = (out / "image.dis").read_text("utf-8")
    for line in disassembly.splitlines():
        match = INSTRUCTION.match(line)
        if not match or match[3].startswith("."):
            continue
        address = int(match[1], 16)
        owners = [start for start, f in functions.items() if start <= address < start + f["size"]]
        require(len(owners) <= 1, "Overlapping function sections")
        if owners:
            functions[owners[0]]["ins"][address] = (
                match[3], match[4], len("".join(match[2].split())) // 2)
    byname = collections.defaultdict(list)
    for address, function in functions.items():
        byname[function["name"]].append(address)
    def target(name):
        require(len(byname[name]) == 1, "Ambiguous/missing callback target: " + name)
        return byname[name][0]
    # Check actual linked driver data and the only OSAL lock registrations.
    driver = elf.symbols["_usbd_driver"]
    names = ("cdcd_init", "cdcd_deinit", "cdcd_reset", "cdcd_open",
             "cdcd_control_xfer_cb", "cdcd_xfer_cb")
    expected_words = [0, *(target(name) | 1 for name in names), 0, 0]
    require(driver["size"] == 36, "Unexpected class driver count/ABI")
    driver_words = [elf.word(driver["value"] + 4 * i) for i in range(9)]
    require(driver_words == expected_words, "Class driver callbacks differ")
    for name in ("_usbd_qdef", "_usbd_spin"):
        require(elf.word(elf.value(name)) == target("usbd_int_set") | 1, "OSAL lock callback")
    require(elf.symbols["mt_board"]["size"] == 48, "Board ABI size")
    board_build = elf.word(elf.value("mt_board") + 12)
    require(board_build == receipt["config"]["firmware_build"], "ELF/config build ID differs")
    require([elf.word(elf.value("mt_board") + i * 4) for i in range(7)] ==
            [8000000, 1000000, 0, board_build, 0, 1, 1], "Board scalar configuration")
    require([elf.word(elf.value("mt_stream_timing") + i * 4) for i in range(3)] ==
            [1, 1, 1], "Provisional timing declaration")
    crc_table = elf.symbols["mt_v2_crc32_table"]
    crc_section = elf.sections[crc_table["ndx"]]
    require(crc_table["size"] == 1024 and
            0x08000000 <= crc_table["value"] <= 0x08010000 - 1024 and
            crc_section["flags"] & 2 and not crc_section["flags"] & 1,
            "CRC table must be immutable Flash data")
    for byte in range(256):
        expected = byte
        for _ in range(8):
            expected = (expected >> 1) ^ (0xedb88320 if expected & 1 else 0)
        require(elf.word(crc_table["value"] + byte * 4) == expected,
                "CRC table entry differs")
    # The deferred-function producer is retained but unreachable. No code/data
    # reference to its address may exist in this image, and no graph edge may call
    # it. Incoming USB packets do not populate this internal event kind.
    defer = target("usbd_defer_func")
    needle = struct.pack("<I", defer | 1)
    for section in elf.sections:
        if section["flags"] & 2 and section["type"] != 8:
            require(needle not in elf.bytes(section), "Deferred producer address referenced")
    callback_sites, edges, cfg_results = [], [], []
    excluded_counts = collections.Counter()
    for start, function in functions.items():
        ins = function["ins"]
        # Static census covers unreachable retained instructions as well as CFG.
        for site, (op, args, size) in ins.items():
            if op == "blx" or (op == "bx" and args.strip() not in ("lr", "r14")):
                name = normal(function["name"])
                excluded = None
                if name == "dcd_event_handler":
                    excluded = "CDC xfer_isr/sof pointers are zero; no application driver"
                    excluded_counts["dcd_event_handler"] += 1
                    targets = []
                elif name == "tud_task_ext" and re.search(
                        r"\bldr\s+r3, \[sp, #32\].*\n.*cmp\s+r3, #0.*\n"
                        r".*beq\.w.*\n.*mov\s+r0, r6.*\n"
                        + rf"\s*{site:x}:\s+4798\s+blx\s+r3", disassembly):
                    excluded = "USBD_EVENT_FUNC_CALL has no reachable producer"
                    excluded_counts["defer"] += 1
                    targets = []
                else:
                    require(name in CALLBACKS, "Unresolved indirect call: " + name)
                    targets = [target(n) for n in CALLBACKS[name]]
                callback_sites.append({"owner": start, "site": site, "name": name,
                                       "targets": targets, "excluded_reason": excluded})
        indirect = {row["site"]: row for row in callback_sites if row["owner"] == start}
        queue, seen, maxdepth = [(start, 0)], {}, 0
        def regs(args):
            found = re.search(r"\{([^}]+)\}", args)
            require(found is not None, "Missing register list")
            require("-" not in found[1], "Unsupported compact register range")
            return len(found[1].split(","))
        while queue:
            address, depth = queue.pop()
            if address in seen:
                require(seen[address] == depth, f"Inconsistent SP at {address:x}")
                continue
            seen[address] = depth
            require(address in ins, f"CFG reaches non-instruction {function['name']} {address:x}")
            op, args, size = ins[address]
            next_address, after, returning = address + size, depth, False
            successors = []
            if op == "push" or op == "stmdb" and args.startswith("sp!"):
                after += 4 * regs(args)
            elif op == "pop" or op == "ldmia.w" and args.startswith("sp!"):
                after -= 4 * regs(args)
                returning = bool(re.search(r"\bpc\b", args))
            elif op in ("sub", "sub.w", "subw", "add", "add.w", "addw") and args.startswith("sp,"):
                immediate = re.search(r"#(\d+)", args)
                require(immediate, "Nonconstant SP change")
                after += int(immediate[1]) * (1 if op.startswith("sub") else -1)
            elif op in ("ldr", "ldr.w") and re.match(r"\w+, \[sp\], #\d+", args):
                after -= int(re.search(r"#(\d+)", args)[1])
                returning = args.startswith("pc,")
            elif re.search(r"\[sp[^]]*\]!|\[sp\],", args):
                raise ValueError("Unsupported SP writeback " + hex(address))
            elif args.startswith(("sp,", "sp!")) and op != "stmia.w":
                raise ValueError("Unsupported SP write " + hex(address))
            require(after >= 0, "SP restored above entry")
            maxdepth = max(maxdepth, after)
            if op in ("bl", "blx"):
                require(depth % 8 == 0, "Unaligned call SP")
                targets = ([int(re.match(r"([0-9a-f]+)", args)[1], 16)] if op == "bl"
                           else indirect[address]["targets"])
                for destination in targets:
                    require(destination in functions, "Call target outside function entries")
                    edges.append((start, destination, address, depth))
                successors = [next_address]
            elif op == "bx":
                require(after == 0, "BX with retained frame")
                if args.strip() not in ("lr", "r14"):
                    edges.extend((start, d, address, 0) for d in indirect[address]["targets"])
            elif returning:
                require(after == 0, "Return with retained frame")
            elif re.fullmatch(BRANCH, op) or op in ("cbz", "cbnz"):
                found = re.search(r"([0-9a-f]+) <", args)
                require(found, "Unknown branch")
                destination = int(found[1], 16)
                if destination in ins:
                    successors.append(destination)
                elif destination in functions:
                    require(after == 0, "Tail branch retains frame")
                    edges.append((start, destination, address, 0))
                else:
                    raise ValueError("Invalid branch target " + hex(destination))
                if op not in ("b", "b.n", "b.w"):
                    successors.append(next_address)
            else:
                require(op not in ("tbb", "tbh") and not args.startswith("pc,")
                        and not re.search(r"\bpc\}", args), "Unclassified PC write")
                successors = [next_address]
            queue.extend((n, after) for n in successors)
        require(maxdepth == frames[start], f"CFG/.su disagreement for {function['name']}: {maxdepth}/{frames[start]}")
        cfg_results.append({"address": start, "name": function["name"], "frame": maxdepth,
                            "visited_instructions": len(seen), "object": function["object"]})
    require(excluded_counts == {"dcd_event_handler": 2, "defer": 1}, "Excluded callback census changed")
    require(not any(edge[1] == defer for edge in edges), "Deferred producer has caller")
    outgoing = collections.defaultdict(list)
    for edge in edges:
        outgoing[edge[0]].append(edge)
    memo = {}
    def maximum(address, active=()):
        require(address not in active, "Recursive stack graph")
        if address in memo:
            return memo[address]
        best = {"bytes": frames[address], "path": [functions[address]["name"]]}
        for _, child, site, depth in outgoing[address]:
            result = maximum(child, active + (address,))
            if depth + result["bytes"] > best["bytes"]:
                best = {"bytes": depth + result["bytes"],
                        "path": [functions[address]["name"]] + result["path"]}
        memo[address] = best
        return best
    for address in functions:
        maximum(address)
    roots = {name: maximum(target(name)) for name in (*ROOTS, "mt_live_runtime_step")}
    require(roots["Default_Handler"]["bytes"] == 0, "Fault handler stack changed")
    total = roots["Reset_Handler"]["bytes"] + max(
        roots["USB_HP_CAN1_TX_IRQHandler"]["bytes"], roots["USB_LP_CAN1_RX0_IRQHandler"]["bytes"]) + 3 * 36
    rounded = (total + 7) // 8 * 8
    require(rounded <= 8192, "Insufficient stack reservation")
    return {
        "status": "CONDITIONAL_EXACT_IMAGE_STATIC_BOUND",
        "elf_sha256": sha(elf_path), "analyzer_sha256": sha(Path(__file__)),
        "firmware_build": f"0x{board_build:08x}", "roots": roots,
        "crc_table": {"address": hex(crc_table["value"]), "bytes": 1024,
                      "immutable_flash": True, "all_entries_verified": True},
        "exception_allowance_bytes": 108, "upper_bound_bytes": total,
        "aligned_minimum_bytes": rounded, "reserved_bytes": 8192,
        "functions": cfg_results, "call_edges": edges, "callback_sites": callback_sites,
        "driver_words": driver_words, "hardware_verified": False, "timing_qualified": False,
        "assumptions": [
            "Pinned source and constructor bindings; unions intentionally overapproximate callbacks",
            "Cold system reset, privileged Thread/MSP, STKALIGN; no bootloader/RTOS",
            "Only equal-priority USB HP/LP configurable IRQ roots; both cannot nest each other",
            "NMI and HardFault terminate in zero-frame Default_Handler; three hardware frames allow 36 bytes each",
            "Valid SRAM and successful exception stacking; no corruption, debugger interrupts or foreign DMA",
        ],
        "not_established": ["Physical stack high-water mark", "Worst-case execution or IRQ timing",
                            "Board identity, sample fidelity, no-loss or flash approval"],
    }


def main():
    require(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,
            "Run python -I -B")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = analyze(args.output.resolve())
    (args.output / "static-bound.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "upper_bound_bytes", "aligned_minimum_bytes")}))


if __name__ == "__main__":
    main()
