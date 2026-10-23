# V2-06g — независимое ревью программного TX prepare

**PASS, 9,595/10**, только программный кандидат V2SA. Это не допуск Flash и не приёмка непрерывных 100/200 kS/s. Прежние аппаратные отказы остаются в силе. Дата: 24.10.2026.

Критик `stream200_critic` не писал реализацию, runner или модель. Он читал исходники, проверял сохранённые свидетельства и один раз повторил готовый candidate native executable. COM/SWD, прошивка, новые ARM/native сборки и GUI не использовались.

## Точное состояние и требования

Репозиторий `font-weight/stm32_motortester_v2`; source commit `a7b45bccf54f3155de03389aa5e49b237905c994`, base `ae2cf9c7f5653d9c258dcba5a89efcc16a64ed3a`. Функциональная база сравнения — S8/100k, `build/v6e-fw-01`. Применены текущие критерии V2-06g из task и рубрика [quality-gate](../quality-gate.md): pure prepare существующего staging до IRQ guard, повторная проверка ticket/epoch, прежние write/commit/TIME/Stop/unknown semantics, неизменные Fs/ADC/DATA/queue/FIFO/burst, profile off при сохранённом legacy136; одна адресная actual-core модель и точный ARM/static 64 KiB/20 KiB со стеком 8192.

| Артефакт | SHA256 |
|---|---|
| [Freeze](../verification/v2-tx-prepare/software/v6g-freeze.json) | `63734e85f0bc27032955f0f4863b1946a2b5ee228a228e12b1f565af6db3100c` |
| [Архив](../verification/v2-tx-prepare/software-evidence.json) | `f76746591cab18b3c8bae9efe1cef9e2ebab0eaec79b272486df1a77fcb00d9a` |
| BIN, 37132 байта, build `0x56325341` | `8e8a5f2597a573ffaecfc054b01de726975ec5de07a33b06c4e56f5de75b3558` |
| ELF | `e8a9574fa7374492bdbe258685005b45f7230faf64276755e39c732693359946` |
| [Native result](../verification/v2-tx-prepare/software/v6g-native-01/result.json) | `4089797e9dd38822eeae1b93aca63f85692f239536f373f344b79b47c44a6c91` |

## Лично проверено

Исходники трёх overlays, действительные core/runtime/header, builder/config/static checker, модель и runner прочитаны. Prepare изменяет только существующий TX staging и ticket, не вызывает clock/recover/write и не продвигает sequence/prefix/очередь. Cached кадр повторно не кодируется. Ticket сравнивается по полям, без padding/memcmp. Его контракт требует отдельной памяти и единственного foreground-владельца. Runtime повторно проверяет epoch, soft_serial и usable под прежним guard; core проверяет соответствие перед deferred error и непосредственно перед write. После необратимого write исходные проверки принятого количества, времени и публикации результата сохранены; completed CRC/pop остаются под guard. Stale ticket не уничтожает действующий partial/cached кадр. Подготовка не выдаёт нового разрешения IRQ: она позволяет уже разрешённому обслуживанию прерываний выполняться до прежнего защищённого участка.

Проверены 78 pins freeze, 521 вход receipt, 112 compiler dependencies, 32 analysis inputs, 30 objects и 42 native inputs. G01/G02 имеют одинаковые зависимости компиляции, объекты, BIN/ELF/static; README — единственное изменение между ними. Повторная ARM-сборка G02 ради README была избыточна, но сохранена и честно отмечена; она не послужила основанием расширять тесты. Нормализация неизменённых core/runtime/guards проверена чтением runner и соответствующих исходников; новая ветвь прочитана отдельно, а не признана корректной только по удалению её из сравнения.

Лично повторно вычислен `check_static.analyze()` для финального ELF: результат совпадает с сохранённым static-bound. PT_LOAD ELF восстановлен и побайтно сопоставлен с BIN. Векторы: MSP `0x20005000`, reset `0x08008B4D`. Text 37004, data 128, bss 11212; вместе с резервом стека 8192 получается **19532/20480 байта**, запас 948. Условная граница стека 6044, после выравнивания 6048, меньше резерва. Это статическое условное свидетельство, не измерение стека или WCET. Символ legacy136 — `0x20002BC4`; активного `mt_stream_profile` в образе нет. Исходники и прежние артефакты S9 сохранены.

Actual-core модель использует действительные core/wire/queue S8 и кандидата, без копирования алгоритма сериализации, и извлечённый настоящий runtime admission helper. Лично сопоставлены эти исходные копии, generated model и оба сохранённых transcript: **2649 байт равны**, SHA256 `6336b049ad72f348152b59382e6d70a3b55c1ac11ea8976d01674db7ce7a15d9`. Общий synthetic build `0x56325338` нужен только для сравнения wire; реальный V2SA build закреплён ARM recipe. Usable/IRQ/IO/time callbacks — логические seams, не модель реального прерывания MCU.

Лично выполнена только команда `build/v6g-native-01/candidate/model.exe NUL`: exit 0, три группы PASS, stderr пустой, сохранённый transcript не перезаписан. В группах проверены normal/known-zero/partial/unknown; pure/new/cached/empty; stale core и runtime epoch; фактические Stop/HELLO между prepare и submit с последующим fresh-проходом; stale deferred error; deadline во время подготовки; TIME до write, после write и после completed. Baseline-сборка/запуск подтверждены авторским receipt и сохранёнными байтами, критик их заново не выполнял. Среда — Windows 10.0.19045, Python 3.14.7; native toolchain Zig 0.15.2, ARM GNU 12.3.rel1. Точные compiler argv находятся в receipts.

Все 43 пары программного архива, всего 1616485 байт, лично сверены с оригиналами по байтам, размеру и SHA. Детали: [exact checks](../verification/v2-tx-prepare/critic-exact-checks.json), [archive checks](../verification/v2-tx-prepare/critic-archive-checks.json).

## Замечания и пределы

Открытых P0/P1 в заявленной программной области нет. Ранние вопросы по non-aliasing/ticket, stale Stop/HELLO/deferred error и истёкшему за время подготовки deadline закрыты кодом и моделью. Подозрение о различии return для ERROR закрыто чтением `recover`: он всегда переводит core в FAULT, дополнительное исправление не требуется. Исторический checkpoint с отсутствующими тогда native/freeze сохранён и заменён этим итогом только для точного указанного состояния.

Legacy `tx_max_cycles` теперь исключает prepare/encode; README и progress прямо запрещают сравнивать его с прежним S8/S9 TX максимумом. Общий step/poll по-прежнему включает подготовку. Новая схема не устраняет стоимость кодирования, а меняет участок, в котором оно выполняется. Ускорение, причина queue-full и устойчивость USB ещё не измерены. Модель не доказывает физический throughput; статическая память не доказывает WCET. Ticket добавляет перечень связанных полей, который потребуется согласованно обновлять при дальнейшем изменении core. Новая проверка Windows-пакета не нужна: host/wire/Fs admission не менялись.

## Рубрика и итог

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 30% | 9,6 | Pure staging, повторные guards, сохранённые wire/commit и адресные сценарии |
| C2 | 20% | 9,6 | Stale/partial/unknown/TIME, bounded RAM/stack; физические IRQ сроки отдельно |
| C3 | 25% | 9,6 | Exact ARM/source/байты и личный native replay; логические seams явно ограничены |
| C4 | 15% | 9,5 | Один staging, совместимый API; явный ticket требует сопровождения списка полей |
| C5 | 10% | 9,7 | Exact commit/base/freeze/archive, воспроизводимые receipts, документирован новый смысл TX |

Итог до округления: **9,595**. **PASS для V2-06g software candidate**. Допуск Flash отсутствует; физические 100/200k остаются неподтверждёнными. Следующий возможный шаг — отдельный точный план одной аппаратной проверки и его независимый допуск; текущий PASS автоматически на этот этап не распространяется. Возврат прежней прошивки в будущих опытах — по конкретной необходимости согласно новому указанию пользователя.

Машиночитаемый итог: [critic-source.json](../verification/v2-tx-prepare/critic-source.json).
