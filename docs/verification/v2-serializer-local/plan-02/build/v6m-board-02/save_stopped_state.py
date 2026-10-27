"""Offline SF stopped-register check from saved local files; never accesses hardware.

Fs/mode is an explicit expectation. These registers and legacy136 do not prove
analogue accuracy, sustained throughput, or that SWD was absent during acquisition.
Do not read ADC_DR. This program creates no procedure-facts certificate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct

ROOT = Path(__file__).resolve().parent
PROFILES = {50000: (1, 10240, 71, 19), 100000: (2, 5120, 71, 9),
            150000: (5, 3413, 47, 9)}


def saved(path, maximum):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Only saved regular files are allowed: ' + str(path))
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Saved file exceeds bound: ' + str(path))
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--session-dir', type=Path, required=True,
                    help='Saved mode directory below build/v6m-board-02')
    ap.add_argument('--sample-rate', type=int, choices=tuple(PROFILES), required=True)
    ap.add_argument('--output', type=Path, help='New JSON file; defaults to session-dir/registers-decoded.json')
    a = ap.parse_args()
    directory = a.session_dir.resolve()
    if not directory.is_relative_to(ROOT):
        ap.error('Session directory must stay inside ' + str(ROOT))
    output = a.output.resolve() if a.output else directory / 'registers-decoded.json'
    if not output.is_relative_to(directory):
        ap.error('Output must stay inside the selected session directory')
    mode, deadline, psc, arr = PROFILES[a.sample_rate]
    inputs = {}

    def data(name, maximum):
        raw = saved(directory / name, maximum)
        inputs[name] = hashlib.sha256(raw).hexdigest()
        return raw

    try:
        trial = json.loads(data('run/result.json', 4 * 1024 * 1024))
        owner_closed = (trial.get('owners_closed') is True if trial.get('status') == 'PASS'
                        else trial.get('cleanup_finished') is True and
                        trial.get('final_state', {}).get('phase') == 'closed')
        if not owner_closed:
            raise ValueError('Saved trial result does not confirm the COM owner-close gate')
        if trial.get('expected_sample_rate_hz') != a.sample_rate:
            raise ValueError('Saved trial expected Fs differs from caller-selected Fs')

        def words(name, count):
            raw = data(name + '.bin', 4 * count)
            if len(raw) != 4 * count:
                raise ValueError(name + ' dump has incorrect length')
            return struct.unpack('<' + 'I' * count, raw)

        t, adc, dma, rcc = words('tim3', 12), words('adc', 3), words('dma', 4), words('rcc', 5)
        registers = dict(TIM3_CR1=t[0], TIM3_PSC=t[10], TIM3_ARR=t[11],
                         ADC_CR2=adc[0], ADC_SMPR1=adc[1], ADC_SMPR2=adc[2],
                         DMA_CCR=dma[0], RCC_APB2RSTR=rcc[0], RCC_APB1RSTR=rcc[1],
                         RCC_AHBENR=rcc[2], RCC_APB2ENR=rcc[3], RCC_APB1ENR=rcc[4])
        checks = dict(TIM3_CEN_off=not bool(t[0] & 1), TIM3_rate_registers=t[10:12] == (psc, arr),
                      ADC_off=adc[0] == 0, ADC_sample_PA0=(adc[2] & 7) == 4,
                      DMA_off=not bool(dma[0] & 1), DMA_clock=bool(rcc[2] & 1),
                      ADC_GPIOA_clocks=(rcc[3] & 516) == 516, TIM3_clock=bool(rcc[4] & 2),
                      ADC_reset_released=not bool(rcc[0] & 512), TIM3_reset_released=not bool(rcc[1] & 2))
        first, second = data('diagnostics-first.bin', 136), data('diagnostics-second.bin', 136)
        checks['legacy136_pair_equal'] = len(first) == len(second) == 136 and first == second
        result = dict(scope='Offline post-owner-close stopped state only; no hardware access',
                      sample_rate_hz_expected=a.sample_rate, acquisition_mode_expected=mode,
                      deadline_us_exclusive=deadline, expected_psc_arr=[psc, arr],
                      registers=registers, checks=checks, all_checks=all(checks.values()),
                      owner_closed_asserted_by_saved_result=owner_closed, inputs_sha256=inputs,
                      hardware_procedure_facts_generated=False,
                      limitations=['Nominal mode expectation; not physical rate or ADC settling calibration.',
                                   'Legacy136 build/nonce/generation/fault/deadline validation is a separate decoder step.',
                                   'Saved owner-close evidence does not establish when SWD was used; root records actual procedure separately.',
                                   'No ADC_DR read and no claim that equal dumps authenticate the physical image.'])
        with output.open('x', encoding='utf8') as stream:
            stream.write(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'all_checks': result['all_checks'], 'output': str(output)}))
        return 0 if result['all_checks'] else 2
    except (OSError, ValueError, TypeError, KeyError, struct.error) as exc:
        ap.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
