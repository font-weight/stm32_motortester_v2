# V2-06q — независимое ревью collect-only после DATA1024

27.10.2026. **PASS, 9,605/10** в ограниченной программной области Q/SJ. Критик `/root/stream200_critic` не автор реализации, модели, сборщика или декодера. Допуск Flash и физическая приёмка в этот вывод не входят. **P1-M2-01 — устойчивый поток150k — остаётся открытым.**

## Точное состояние

- База Git: `36d264600a6433d3343cc27e9ce8ce9f41520a62`; функциональная база SI — `0ca687eadd1f5c7b96ffd95796e8d03f01a4f1a1`.
- [Freeze Q](../verification/v2-postcommit-prefetch/production-01/build/v6q-freeze.json), SHA256 `fd3aa369a3f87655411de1c391d989182af82df7b89610f86566f5a803ad0504`.
- [Архив](../verification/v2-postcommit-prefetch/production-01/manifest.json), SHA256 `ce5c0f87f650b10ff7bf399962be4dcc1ae361e5c32c512e141bfd25e17aa25d`:571 source/archive пара,4 643 591 байт.
- SJ/build `0x5632534A`: BIN45 372 байта, SHA256 `5041ae67ccc25eda8d0003121370baed1120b025399099d4c3f42abfee61ca88`; ELF `55afde847a5629fd573c92d5b9d61eeaa267d8236edb2f43088ac65a015fd4d6`.
- Основания: [quality-gate](../quality-gate.md), Q в task/coordination, [контракт Q](../streaming-postcommit-prefetch.md), требования V2-STR14–17 и сохранённый [результат P2](v2-06p-physical-review.md).

Принимается bounded collect-only после подтверждённого final commit cached полного mode5 DATA1024 и прежнего USB flush. Формат, частоты, ADC/DCD/TIME, очередь8, FIFO384, grant6/<500мкс, staging и правила принятого префикса не расширяются. GUI/Windows-пакет не изменены и заново не проверялись.

## Лично проверенные свидетельства

Прочитаны три strict patch, exact core/runtime, общий collector, certificate/ERROR paths, модель и runner, builder/config, методика, ABI64, decoder/checker и итоговый author audit. Пассивно сверены571 пара архива,47 freeze pins,570 ARM inputs,119 compiler dependencies,33 object pins,35 analysis inputs,3 артефакта и125 native input pins: расхождений нет.50 незатронутых patched файлов и29 неизменных объектов совпали с SI побайтно.

Проверка критика — чтение файлов, Git/rg и Python `pathlib/hashlib/json/struct`; сборки, модели, декодеры, COM/SWD не запускались. Точные выполненные авторами команды, toolchain и exit codes сохранены в [ARM receipt](../verification/v2-postcommit-prefetch/production-01/build/v6q-fw-01/receipt.json) и [native result](../verification/v2-postcommit-prefetch/production-01/build/v6q-native-01/result.json). ARM использует GCC12.3 Cortex-M3/Thumb, `-Os`, строгие предупреждения; native — Zig0.15.2 C11/O1/Wall/Wextra/Werror. Обе проверки выполнены один раз, PASS; неудачных ARM/native запусков Q нет. Первое пассивное чтение критиком секции ELF искало неверное имя `.text.mt_progress_bind`; после чтения фактического `.text.bind` проверка завершена. Это не запуск/отказ продукта.

В exact ELF `mt_board` расположен по `0x0800B048`, его build word `+12` равен SJ. Общий generated header входит в зависимости board и observer; actual `.text.bind` отличается от SI только единственным config-derived literal SI→SJ. Native модель отдельно исполняет actual observer с этим же SJ header, проверяет ACTIVE и ненулевые prepare counters. Таким образом ограниченное доказательство не опирается лишь на синтетическую метку декодера, как в неудачном O.

## Корректность новой границы

`prefetch_ready` проверяет точный старый ticket и результат его принятия: mode5/STREAMING/DATA1024, cached offset, known accepted remainder, nonce/generation/revision, prefix+CRC/last sequence/next sequence, EMPTY staging, отсутствие Stop/control/fault и RESERVE, неизменную queue identity. Одного `tx_ok` недостаточно; coarse dispatch повторно проходит этот certificate до мутации.

Выделенный `batch_collect` сохраняет старый алгоритм ordinary prepare. Он проверяет все views/коды до atomic pop, переносит максимум4×128 в существующий packed staging и не выполняет seal, frameCRC/COBS, write, callback или global prefix commit. Queue0 не начинает новый пакет. Cached final pass прежде ничего не собирал, поэтому предел512 за проход сохраняется. Это ограничение количества работы, не доказательство времени выполнения.

Runtime вызывает новый helper после прежних flush/TIME/loss. Перед scope и после копирования он проверяет **исходные сохранённые** prepared epoch/soft serial, свежие TIME/stable/usable. Новый здоровый, но другой сеанс не принимается за старый. При stale cleanup нет восстановления уже освобождённых слотов или переноса старого staging в новый сеанс. Только новый matching ERROR ticket допускает второй guarded step для recovery; EMPTY/COLLECT не отправляет второй DATA. Existing final-time commit, принятые prefix/CRC/sequence, Stop drain и HELLO discard сохранены.

[Source equivalence](../verification/v2-postcommit-prefetch/production-01/build/v6q-native-01/source-equivalence.json), SHA256 `5956f558cc97d09a4278f6fc6485cdcbad3b829c048e3a16730f4916c4e41637`, возвращает все SI core tokens точным reinlining collector и удалением двух новых API; удаление helper/dispatch возвращает весь SI runtime. Preceding flush и отсутствие нового grant/task подтверждены чтением и этим source proof.

## Модель, декодер и ресурсы

[Native01](../verification/v2-postcommit-prefetch/production-01/build/v6q-native-01/result.json), SHA256 `f566548e4a2692b3e75c90698f90a524da98bb8eae24191014cfab1a35816eab`, исполняет actual core/queue/serializer/wire/progress и **два извлечённых runtime helper**. Три группы проверяют completion→collect0/128/512, q8→4+4offers, wrapped views, следующий wire/CRC/END; certificate/zero/partial/unknown/finalTIME/control/RESERVE/old modes; Stop/HELLO, saved identity, scope refusal, TIME/epoch/soft/lifecycle до и после collection, current/stale ERROR и immutable first close.

Полный runtime step, ADC, USB/DMA/MMIO/IRQ timing не исполняются. Preceding flush, actor/epoch/TIME/DWT и legacy136 setup — логические seams; инъекции в prepare происходят на synthetic DWT begin/end, не на каждом байте копирования. Source proof и actual-helper proof дополняют друг друга, не подменяются утверждением полной аппаратной симуляции.

[Decoder01](../verification/v2-postcommit-prefetch/production-01/build/v6q-decoder-01/result.json), SHA256 `bb724066fac594405e2e7ae78c7eb70e3597d285b88558cf41ace00aed908d58`, — один PASS/20 отрицательных случаев. Повторно использован P actual-C64 и synthetic legacy136 SI; SJ allowlist проверена **синтетической metadata**, не новым Q frozen dump. Actual SJ binding отдельно закрыт Q native. Старые SG/SH/SI/default semantics сохранены, неподходящий build/nonce/gen/image и zero64 отклоняются. ABI уточняет: prepare sum/count теперь включает также post-flush collect-only; это inclusive время, не CPU share и не сопоставимая без оговорки длительность одного полного encode.

Exact resources: text45 244, data128, bss12 132; BIN45 372. `128+12132+8192=20452/20480`, static growth0, запас28байт сверх stack reserve. Условная stack upper6164/aligned6168 против SI6156/6160; runtime frame336 против328. Collector frame176, certificate36, prefetch entry24. Legacy136 `0x20002F1C`, progress64 `0x20002FA4` сохранены. [Static bound](../verification/v2-postcommit-prefetch/production-01/build/v6q-fw-01/static-bound.json), SHA256 `5b03b2b99ec72176619e113dbe9d005d42c548d9f1b24a3567fd8587ebb13e06`, условен относительно закреплённых callbacks/IRQ/MSP/reset; это не измеренный high-water или WCET.

## Замечания и вывод

Открытых P0/P1 **в ограниченной программной области Q** не найдено. Три предварительных обязательства — completion certificate, original epoch/soft и matching ERROR recovery, общий ограниченный collector/Stop/HELLO — выполнены и имеют адресные свидетельства.

Неблокирующие границы приёмки: новая packing/CRC работа увеличивает cached-final latency и может задержать следующий USB task/ADC poll; возможность overlap после flush не гарантирована. Deadline3413мкс и grant6/<500мкс неизменны, их достаточность на SJ не измерена.28байт static запаса не позволяют добавлять состояние без нового resource review. **P2 FAIL и P1-M2-01 сохраняются; никакой оценки физической устойчивости из этого PASS не следует.**

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% |9,7|Точное eligibility/ownership, принятый префикс и прежние modes/Stop/HELLO сохранены.|
| C2,20% |9,5|Свежие barriers и отрицательные cases; малый RAM-запас и увеличение latency явно ограничивают вывод.|
| C3,25% |9,6|Exact ARM, actual C/helper model, active SJ binding и пассивная byte-проверка; полная аппаратная временная модель отсутствует и не заявлена.|
| C4,15% |9,5|Один общий collector и узкий helper; сложный certificate явно описан, а не спрятан за `tx_ok`.|
| C5,10% |9,7|Закреплённые inputs/команды/архив и воспроизводимые границы продолжения.|

Итог без округления: `0.30×9.7+0.20×9.5+0.25×9.6+0.15×9.5+0.10×9.7 = 9.605`. **PASS только Q1 software.** Следующий аппаратный узел требует отдельного exact-plan допуска; этот отчёт не разрешает Flash/Reset/START и не меняет фактическое состояние платы.
