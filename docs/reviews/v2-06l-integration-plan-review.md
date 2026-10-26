# V2-06l L1: допуск к реализации проекта интеграции r2

26.10.2026. **PASS — 9,56/10 как проект ограниченной реализации.** Допускается разработка mode5 по exact r2. Это не приёмка ещё не существующего интегрированного кода, образа или аппаратного результата; Flash не допускается этим документом.

Независимый критик `/root/stream200_critic` прочитал `build/v6l-analysis/integration-plan-r2.md`, SHA256 `f77b39f2c639ad28e3b58a3bf7eb51fe94212cd35557d67fe7359b14f6f13d65`, и фактические SD `step_tx`, `completed`, `terminate`, `snapshot_valid`, `begin_hello`, recovery/transport loss и runtime prepare/submit. Исходная r1 `7dcdfa05d14912bc3e23b1781ce2c55f9e2c87cd9f326fb2817574ec4329a6f8` сохраняется. Функциональная база SD/source `cb4757940b3ee9968f953becfbc3ca8caea102d7`; изолированный результат сохранён checkpoint `0786259` и закреплён manifests из [предыдущего ревью](v2-06l-prototype-review.md). Новых тестов, аппаратных действий или изменений реализации критик не выполнял.

## Существенная дельта r2

Root обнаружил в прежнем SD порядок: `completed()` вызывается перед последним core `now`. Поэтому публикация нового cached CRC внутри обычного `completed()` не удовлетворяла бы заявленному для mode5 условию final guards.

R2 разделяет pure preparation результата и публикацию. После полного known acceptance сохраняются byte evidence/offset и sequence semantics; локально проверяются old-frame identity, READY, длина/count, first и seed. Затем выполняется исходный последний `now` и bound. Только после успеха идут constant-size stores prefix/CRC/lastseq и сброс staging/TX, без callbacks, CRC, queue pop или новой fallible операции. IRQ guard остаётся до этих stores.

При последнем TIME/bound failure уже вышедшие байты не считаются отзываемыми: глобальный prefix не продвигается, включается recovery/isolation/delimiter и сеанс неполон. Нормальный END со старым prefix после escaped полного кадра запрещён. Это согласуется с host, который мог уже принять целый CRC-valid кадр. Успешный прошлый commit не обещает отсутствия новых ошибок после unlock.

## Границы, обязательные при реализации

- Queue→staging переносит владение до IRQ guard, сохраняя source indices; prefix доставки не изменяется. Все borrowed views проверяются до одного pop-many и публикации work-state. Единственный foreground owner исключает вмешательство других core callbacks внутри prepare; изменившийся USB epoch отклоняет submit и вызывает старый loss cleanup.
- Staging и очередь учитываются отдельно. END mode5 возможен лишь после подтверждённого hardware-off, пустой очереди и отсутствия staging/незавершённого TX. Source queue fault не склеивает поздний хвост через разрыв и не теряет первую причину.
- Stop сохраняет текущий пакет и дочитывает только удержанный после quiesce хвост. HELLO при offset0 отбрасывает старый непереданный staging; при partial offset завершает старый immutable DATA под old identity до нового ACK. Unconditional batch clear внутри общего raw_barrier запрещён.
- Destructive CRC/COBS cursor не откатывается отдельно от storage. Stale epoch/TIME требует discard/recovery, а не повторной упаковки по старому cursor. Unknown acceptance сохраняет необходимость изоляции.
- В pure completion буквально сверяются `batch.length == tx_length` и `batch.count == tx_count`, а также полная длина offset, old nonce/mode/revision/generation, first и seed. Предусмотренная в плане проверка READY/length/count должна охватывать обе структуры, а не только внутреннюю корректность одной.
- Actual-core модель исполняет production-пару `prepare_tx → step_prepared`; legacy `step(NULL)` не заменяет доказательство нового порядка. Epoch case использует извлечённый actual runtime prepared-submit helper с явно обозначенными seams.

Последние два уточнения переданы автору; они конкретизируют r2 и не добавляют новую функциональность или группы тестов.

## Ресурсы и пределы доказательства

Модель памяти остаётся `19564+792+32=20388/20480`,92 свободных байта после резерва8192. Локальные ticket/четыре descriptors/pending completion обязаны войти в **новый полный** ARM stack census; прежний предел ticket224 нельзя молча сохранить. Рост RX/previous/generic message или нового статического массива не допускается. Пока это проектный расчёт; exact linked image/map/stack — обязательный следующий gate.

Начальный prepare объединяет до512 samples collection и не более1324 CRC+1328 COBS входных байт. Это конечная граница работы, не WCET и не гарантия deadline3413 мкс. Старые TIME, ADC/DMA, DCD, FIFO384, burst6/<500 мкс и early-grant остаются без ослаблений. Если квант слишком долгий, это требует отдельного изменения планировщика с новым order proof; увеличивать deadline или ждать USB при остановленном DMA нельзя. Старение раннего grant явно остаётся ограничением.

Одна proposed actual-core модель с четырьмя группами достаточна по проекту: ownership/wrap/stale fourth view и старые modes; Stop/tails/gap; HELLO и epoch; partial/unknown/TIME/final-guard failure. В четвёртой группе обязателен случай, где post-write now успешен, full bytes escaped, но **последний** core now/bound отказал: prefix/CRC/lastseq неизменны, normal END/ACK отсутствуют. Затем точный ARM/static и один C→host fixture; широкое повторение legacy набора не требуется. Нативные seams не заменяют физическую проверку.

## Оценка проекта

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% | 9,6 | Разделены ownership, byte acceptance и итоговый commit; сохранены старые modes и negotiated mode5. |
| C2,20% | 9,5 | Конкретные Stop/HELLO/fault/epoch пути и deferred final commit; resource/throughput условия оставлены обязательными. |
| C3,25% | 9,55 | План сопоставлен с actual SD, исправлен реальный completed-before-now край; указан достаточный адресный набор будущих доказательств. |
| C4,15% | 9,55 | Ограниченный overlay без параллельного TIME/DMA/FIFO рефактора; ownership семантика описана явно. |
| C5,10% | 9,6 | Exact r2/prototype pins и сохранённая r1 позволяют продолжить независимо от истории чата. |

Итог: **9,56/10, PASS проекта; открытых P0/P1 на этом уровне нет**. Разрешена реализация, после неё нужны отдельные exact source/image review, GUI/package и hardware admission. Цель stable150k остаётся незавершённой, K2 physical FAIL не переоценён.
