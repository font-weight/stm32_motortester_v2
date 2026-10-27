# V2-06p — независимое ревью общей build identity SI

27.10.2026. **PASS, 9,625/10** для ограниченного программного исправления P. Критик `/root/stream200_critic` не автор прошивки, модели или декодера. Это не допуск Flash, не физическое подтверждение работы наблюдателя и не приёмка устойчивых150k.

## Точное состояние и область

- База Git: `34a3f827db5362fac4d8f85abfa89b79756b17f1`; функциональная база SH — `08196d8c0db477c2b567262eb01e56af3663a79e`.
- [Freeze](../verification/v2-progress-identity/production-01/build/v6p-freeze.json): SHA256 `c68906cc65fc7e4216443c90dab030da198058bd811ec038d474d9630446c4d9`.
- [Архив](../verification/v2-progress-identity/production-01/manifest.json): SHA256 `18912ebad03af71c4c24dc718c1407c38c46fde9dc1d057544251c7fe60191b0`;551 пара,4 384 338 байт.
- SI/build `0x56325349`: BIN44 216 байт, SHA256 `aeccdce0a5c2705e5fc77338595655a1f8d20367de486cbc83250f85a3a2d9c7`; ELF `2f6d507f0629407d2f79f04dceff1bf45bbd69226327c3909f57b4347a4e5613`.
- Основания: [quality-gate](../quality-gate.md), P в task, [методика P](../streaming-progress-identity.md), V2-STR14–17 и сохранённый [отказ O2](v2-06o-physical-review.md).

Принимается устранение независимой константы observer, build-dependent интеграция board/observer в exact ARM, адресные native и offline-свидетельства. Runtime late grant, ADC/USB/wire, ownership/очередь и ABI не изменяются. Host GUI/Windows-пакет, аппаратное исполнение SI и пропускная способность не входят в этот узел.

## Личная проверка

Прочитаны diff builder/board generator/header, actual observer C, модель/runner и адресное исправление runner, decoder/checker, методика и авторский audit. Пассивно проверены551 source/archive пары и46 freeze pins;566 ARM inputs,119 compiler dependencies,33 object pins,35 analysis inputs,3 артефакта. Дрейфа нет. Native01 имеет120 исходных pins с явной заменой изменённого runner на сохранённый r1; completion02 —134 совпавших pins.

Побайтно сверены52 неизменных patched файла и31 неизменный nonbinding object с SH. Независимое чтение ELF/объектов подтвердило:

- `mt_board` находится по `0x0800ABC0`; build word `+12` равен SI.
- Literal в actual `.text.bind` равен SI; вся секция совпадает с SH после единственной замены прежнего SG literal. В итоговом ELF этот literal — `0x0800A2D0`.
- Общий generated header входит в зависимости **обоих** объектов board и observer. Он получается из уже проверенного config, а не из отдельного observer ID. Число SI в allowlist генератора является ограничением допустимой конфигурации, не вторым скомпилированным источником identity.
- `.data128 + .bss12132 + reserve8192 = 20452/20480`; запас28 байт. Нового static RAM нет. Условная граница стека6156, выровненная6160; это не физический high-water/WCET.
- Legacy136 — `0x20002F1C`, progress64 — `0x20002FA4`; ABI и freeze semantics сохранены.

Критик выполнял только чтение Git/файлов, `rg`, Python `pathlib/hashlib/json/struct`. Сборки, executable модели, decoder tests, COM/SWD/Reset/Flash/START не запускал. Представленные инструменты: GNU ARM12.3.1 и Zig0.15.2 на Windows; точные команды и инструментальные hashes сохранены в receipts.

## Необходимые свидетельства и их пределы

1. [ARM01](../verification/v2-progress-identity/production-01/build/v6p-fw-01/receipt.json) — единственная сборка PASS. Receipt SHA256 `5263fe24b1e6329e10d51e2c0d4eb50aef0ab66bcf9f30035f860cdf20b57791`, static-bound `81ef578619db02f57a3cec9949c5360ec096d26ffe902dcf78e5262883d77a62`. Generated header SHA256 `7676635e6914927df4650c0ddfc0b30c6e417326702aa91a2534b197adbe9676`.
2. [Native01](../verification/v2-progress-identity/production-01/build/v6p-native-01/result.json) **сохраняет aggregate FAILED**. Actual C модель исполнилась один раз с exit0: exact SI достигает ACTIVE/FROZEN; SG,SH,foreign build, чужие nonce/generation отвергаются без записи; известный partial учитывается один раз, unknown не превращается в bytes; CLOSING/FROZEN неизменны при поздних API. Затем команда expected-negative компиляции ошиблась: Zig отверг `-fsyntax-only` из-за implicit `-c`/Werror до нужного `#error`. Это была ошибка проверочной команды, её исходный runner и stderr сохранены.
3. [Completion02](../verification/v2-progress-identity/production-01/build/v6p-native-02/result.json), SHA256 `4a981e572cab5e6246ef382467c9c8e73fec1369adcf16794142cd29b7b6461e`, повторяет **только** исправленную отрицательную компиляцию с `-c/-o`. Stderr содержит требуемое `Progress trace requires generated target build identity`, object не создан. Composition связывает неизменные native01 model/fixtures/inputs и единственную дельту команды runner. C-модель и ARM не повторялись. Успех02 не переписывает неуспех01.
4. [Source-equivalence](../verification/v2-progress-identity/production-01/build/v6p-native-01/source-equivalence.json), SHA256 `0e7349160cda43687b652ca68ac4254d27909d1e87799de02e4b55b9415b9f09`, подтверждает неизменность остальных functional bodies/objects. Actual observer C SHA256 `eada6c8ee4996e96bf7e3749ce1ab7604d8d700fdedf356beed5f35293f10e77` сохранён.
5. [Decoder01](../verification/v2-progress-identity/production-01/build/v6p-decoder-01/result.json), SHA256 `70ee37ea565a3c808d9b9fb85dcc0e98b1d3968a31e372a793a3301ea185f284`, — один PASS: actual C64 `f5e6178675f0a43733c099abb4c0c85504536d7e70e5f5dc9692d754ee1c75aa` и C-written **synthetic** legacy136 `98d55e3cb60310e4a990cc7b1c159c48c803bd60d777a68986c80433688446f9`, clean fixture и19 отрицательных случаев. Проверены явный SI, отказ SH вместо SI/default SG, неизвестный build и нулевой банк; malformed данные не получают nominal timing. Полный legacy decoder/module здесь не исполнялся, identity setup синтетический. Результат64 `VALID_WITH_LIMITS`, `physical_identity_verified=false`, `timing_qualified=false`.

## Замечания и сохраняемые ограничения

Открытых P0/P1 **в ограниченной программной области P** не найдено. Причина **P1-O2-02** устранена для точного SI на программном уровне: нет отдельного observer literal, отсутствие macro не имеет fallback, exact C и ARM используют одно значение. Физическое заполнение64B в SI ещё нужно проверить по отдельному плану.

O2 REWORK5,80, INVALID zero64 и отмена соответствующей части O1-приёмки остаются неизменными. Новый PASS не восстанавливает приёмку старой SH. **P1-M2-01 — устойчивые150k — остаётся открытым.** SI снова включает observer work, отсутствовавшую в O2; её стоимость нельзя вычитать или игнорировать при сравнении.28байт поверх stack reserve — конкретный предел текущего образа, не разрешение расширять static state без нового расчёта. Модель не измеряет реальный DWT, USB/DMA/IRQ, stack high-water или работу legacy collector на плате.

## Оценка

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% | 9,8 | Доказанная причина исправлена общим ID; actual binding и linked board подтверждены. |
| C2,20% | 9,5 | Нет fallback; mismatches и поздние записи отвергаются, ресурсы не выросли; аппаратные и stack условия остаются явными. |
| C3,25% | 9,5 | Адресные actual C/ARM/decoder подтверждают именно изменение; неудачная команда сохранена и восстановлена узко, модельные seams оговорены. |
| C4,15% | 9,6 | Один generated header, неизменные functional bodies и явные границы observer. |
| C5,10% | 9,7 | Exact manifest, generated inputs, original failure и composition позволяют воспроизвести состояние без истории чата. |

`0.30×9.8 + 0.20×9.5 + 0.25×9.5 + 0.15×9.6 + 0.10×9.7 = 9.625`.

**PASS только software P/SI. Flash/START требует отдельного exact-plan допуска; устойчивые150k и физический observer этим отчётом не приняты.**
