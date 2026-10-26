"""Derive SE offline analyzers from preserved SD witnesses. No hardware access."""
from pathlib import Path

here = Path(__file__).resolve().parent
old = here.parent / 'v6k-board-01'

def derive(name, replacements):
    text = (old / name).read_text(encoding='utf-8')
    for source, target, count in replacements:
        assert text.count(source) == count, (name, source, text.count(source), count)
        text = text.replace(source, target)
    target = here / name
    if target.exists():
        assert target.read_text(encoding='utf-8') == text, 'Refusing to replace evidence'
    else:
        with target.open('x', encoding='utf-8', newline='\n') as output:
            output.write(text)

derive('analyze_physical.py', [
    ('Offline SD trial', 'Offline SE trial', 1),
    ('150000: 4', '150000: 5', 1),
    ('(256 if frame.revision == "0.2"', '(1024 if frame.revision == "0.2"', 1),
    ('expected_marker = 7', 'expected_marker = 15', 1),
    ('mode == 4', 'mode == 5', 3),
    ('v2-06k-physical-offline-analysis-1', 'v2-06l-physical-offline-analysis-1', 1),
    ('# V2-06k:', '# V2-06l:', 1),
    ('- SD/build', '- SE/build', 1),
    ('check(payload.capabilities == expected_marker, "HELLO_capability_marker")',
     'check(payload.capabilities == expected_marker, "HELLO_capability_marker")\n'
     '            check(payload.max_payload == (1300 if frame.revision == "0.2" or mode == 5 else 512), "HELLO_max_payload")', 1),
])
derive('decode_diagnostics.py', [
    ('V2SD', 'V2SE', 4),
    ('0x56325344', '0x56325345', 4),
    ('expected_build_not_v2sd', 'expected_build_not_v2se', 1),
    ('150000: (4,', '150000: (5,', 1),
    ('Maximum observed queue128 slot use (DATA256 consumes two slots) out of 8; no proof of zero ADC loss.',
     'Maximum observed queue128 slot use out of 8. DATA1024 gradually transfers up to four slots per preparation into separate staging; this count excludes staging and does not prove zero ADC loss.', 1),
])
derive('save_stopped_state.py', [('build/v6k-board-01', 'build/v6l-board-01', 1)])
print('SE offline helpers prepared; plan/image/diagnostic address still required; no device access')
