# V2-06o/O1 — независимое ревью позднего grant SH

27.10.2026. **PASS, 9,625/10** для ограниченного программного кандидата O1. Это не допуск Flash и не подтверждение устойчивых150k. Критик `/root/stream200_critic` не автор реализации, модели или декодера; аппаратных действий не выполнял.

## Точное состояние

- База Git: `56e712e6830c34cbbac1d2e674fc2e8a74696eaf`; функциональная база — проверенный SG из `f4c40c2f13be098f24bff069916bbb13dd7973a5`.
- [Freeze O](../verification/v2-late-grant/production-01/build/v6o-freeze.json): SHA256 `ba50e3b452c5f2184d61112de8026398c07717da1f7c104a0ad70db02c2875fa`.
- [Архив](../verification/v2-late-grant/production-01/manifest.json): SHA256 `ce67de43572509c5b9fb159a2475879ed3d172efd906ea7a8cbf6feb00cb1acb`;555 побайтно одинаковых пар,4 386 470 байт.
- SH/build `0x56325348`: BIN44 212 байт, SHA256 `99fcd38af9ac4e4feb8b7b4fa0bd577a77d8103773c0951e6b6a433e22deddf2`; ELF `29c12600228c367f440dbfab09761c8572f342cf5f96e5c20336e3fbb24b0cb3`.
- Runtime SHA256 `31db9f366c635082cb80540e5f0028323c779a132e1fbf5e5aece8519be4f55d`; strict patch `16aacb238ed362328e3c0af7529ae49967feec8e83dd7a8b00ccbf093592ddc6`.
- Основания: [quality-gate](../quality-gate.md), O1 из task, V2-STR14–17 и [методика O](../streaming-late-grant.md), SHA256 `cf56b3f5314f6ba9cc5b883802d4e401267be4d76a7303466960b1b90ebd69c6`.

Принимается перенос одной прежней grant-попытки за подготовку нового полного mode5 DATA1024, его отказные границы, exact ARM/resources и явная привязка offline-декодера к SG/SH. Host acquisition/storage/GUI/Windows-пакет, физические USB/DMA задержки, WCET, аналоговые измерения и stable150k в эту оценку не входят.

## Личная проверка и сохранённые свидетельства

Прочитаны actual runtime, strict overlay/recipe, связанные неизменные core/TIME/DCD/scope границы, модель/runner, decoder/checker, методика и авторский audit. Пассивно пересчитаны33 строки freeze,565 ARM inputs,118 compiler dependencies,33 object pins,35 analysis inputs,3 образа и122 native inputs. Дрейфа нет. Все555 source/archive пар совпали;52 остальных patched файла лично сверены с SG побайтно. ELF-таблица секций независимо подтверждает `.data128` и `.bss12132`; symbol map — адреса136/64. В `.su` runtime frame328, как у SG.

Команды критика ограничены чтением Git/файлов, `rg`, Python `pathlib/hashlib/json/struct`. Критик не запускал сборку, executable модели, decoder tests, COM/SWD/Reset/Flash/START. Представленная среда: Windows, GNU ARM12.3.1 и native Zig0.15.2. Exact argv, инструментальные хеши и зависимости находятся в receipt/result.

1. [ARM01 receipt](../verification/v2-late-grant/production-01/build/v6o-fw-01/receipt.json) — первая сборка PASS. `.data128 + .bss12132 + reserve8192 = 20452/20480`, остаток28 байт; нового static RAM нет. Условная полная граница стека6156, выровненная6160 при резерве8192; не измеренный high-water/WCET. Legacy136 — `0x20002F1C`, progress64 — `0x20002FA4`. Static-bound SHA256 `e9317b4704e4a38b74e9e65ac0d7d8f68a2409e354f49988f11b9c5c8351c5bc`.
2. [Native01](../verification/v2-late-grant/production-01/build/v6o-native-01/result.json) — единственный запуск PASS трёх групп, SHA256 `016fb84d3292f139e69608110b3967118add3413875136ba987017755bc2d633`. Исполняются извлечённые actual runtime bodies и actual epoch. ADC/core/USB/MMIO/TIME/scope представлены логическими границами; observer выключен только в этой модели. Проверены выбор раннего/позднего пути, fresh TIME/epoch/soft/lifecycle до и после grant, scope/actor, отмена Stop/HELLO/EMPTY/ERROR, сохранение cached bytes, known-zero, отказ grant/health, единственность попытки и fallback следующего прохода при raw lifecycle. Модель SHA256 `96ece4a0ab642fbab7fc5bb5b364113d03e79a2c927b97d625d59e39f32c1a1a`.
3. [Source-equivalence](../verification/v2-late-grant/production-01/build/v6o-native-01/source-equivalence.json), SHA256 `6ad33e002164b0c0ad2d0a71d630492929709d8ee721701a3484bdae0ecf203a`: весь runtime token-identical SG после удаления только двух новых предикатов, selector и выделенного позднего блока. `grant_irq` и `prepared_tx_step` неизменны. Остальные52 patched файла равны SG, включая core/queue/serializer/ADC/DCD/136/64; canonical TIME/USB также закреплены.
4. [DecoderO01](../verification/v2-late-grant/production-01/build/v6o-decoder-01/result.json) — один сохранённый PASS, SHA256 `4a430ff22c582535c4bdabee7ca682d0491ff57be878b4026ac3328984edb1d5`. Прежний actual C64 fixture N повторно использован с синтетическими legacy identity;16 отрицательных случаев включают SH без явного build, SG вместо SH и неизвестный build. SG остаётся default; SH требует явного `0x56325348`, image SHA и согласованных136/64/nonce/generation. Это не новый physical SH trace.

## Существенные границы

Hint проверяет mode/state/phase/count/queue-used/intents и только выбирает расписание. Он не валидирует всю очередь или ownership и не разрешает write. Авторитетными остаются actual prepare и полный guarded ticket.

На выбранном позднем пути marker расходуется до новой admission: fresh `live_time`, `synchronize_loss`, `usable`, app scope/actor, затем прежний grant. После IRQ снова выполняются TIME/stable и scope leave; исходный guarded submit повторно проверяет epoch/soft serial/ticket. Неудачная admission может дать ноль фактических grant, но не второй reset бюджета в том же проходе.

Отменённый hint с PREPARED DATA, не соответствующей STREAMING/full READY1024, сохраняет cached bytes и откладывает submit до следующего обычного прохода. EMPTY/control/ERROR идут через прежнюю guarded обработку. Это не уничтожает уже принятый partial prefix. Pending raw lifecycle может воспрепятствовать позднему scope; следующая ordinary fallback сохраняется без RX/TX. В модели `allow_ctr` — аргумент runtime, не доказательство фактического разрешения CTR: raw flags дополнительно проверяет неизменный actual DCD.

До первой native-проверки добавлен узкий witness raw lifecycle → next-pass fallback. Первоначальное замечание проекта о необходимости **fresh TIME до grant**, а не только cached `healthy()`, реализовано. Открытых P0/P1 в ограниченной программной области O1 не найдено.

## Пределы приёмки

- Перенос может задержать старый in-flight IN; отсутствие cached core TX не означает пустой USB. Дополнительные TIME/scope проверки имеют стоимость. Модель не измеряет фактические IRQ/USB/ADC задержки.
- Очередь может переполниться ещё внутри ADC service, до grant. Snapshot N2 не различает все причины hold; исправление единственной первопричины и рост throughput не доказаны.
- Предел6/<500мкс, FIFO384, queue8×128, ADC deadline3413мкс для150k и алгоритмы принятия CRC/индексов не изменены. Сохранение guards само по себе не подтверждает физическую устойчивость.
- Static spare28 байт и stack bound условны; любой рост RAM/изменение call graph требуют нового exact resource review. Высокая оценка не означает измеренный запас или безопасность прибора.
- Диагностика64/136 сохраняет прежние ограничения: FIFO acceptance не USB delivery/committed prefix, inclusive cycles не CPU-share, один attempt/boot; cap останавливает наблюдение, не захват. Новый decoder не удостоверяет физическую идентичность сам.
- **P1-M2-01 stable150k остаётся открытой**. N2 физически REWORK; O1 её не переоценивает. Новый образ пока не допущен к Flash или START этим отчётом.

## Оценка

| Критерий | Балл | Основание |
|---|---:|---|
| C1 | 9,75 | Узкий выбор точки grant, новый hint не подменяет ticket, существующие данные/commit и обычные пути сохранены. |
| C2 | 9,50 | Проверены новые отказные границы и single-attempt; RAM не вырос, физические timing-риски явно вынесены в следующий этап. |
| C3 | 9,60 | Exact ARM, actual-runtime/epoch модель, source-equivalence и decoder negatives покрывают изменённое поведение; логические seams честно ограничены. |
| C4 | 9,50 | Два малых предиката и локальный блок, явный canceled-cache путь; дополнительные admission ветви требуют внимательного сопровождения. |
| C5 | 9,75 | Exact freeze/inputs/копии/команды и неизменная история SG/N2 позволяют продолжить без чата. |

`0,30×9,75 + 0,20×9,50 + 0,25×9,60 + 0,15×9,50 + 0,10×9,75 = 9,625`.

**Итог: PASS O1/software.** Для аппаратного действия нужен отдельный допуск точного плана; для stable150k — отдельное успешное физическое свидетельство.
