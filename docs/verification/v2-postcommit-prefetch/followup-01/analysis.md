# Q2: backpressure последней части DATA1024 — offline proposal

27.10.2026. Только чтение сохранённых данных/исходников. Код, сборки, тесты,
COM/SWD/Reset/Flash не выполнялись и не изменялись. Это предложение следующего
ограниченного замера, не принятый fix или аппаратный допуск.

## Что подтверждено

Exact SJ image `5041ae67ccc25eda8d0003121370baed1120b025399099d4c3f42abfee61ca88`,
ELF `55afde847a5629fd573c92d5b9d61eeaa267d8236edb2f43088ac65a015fd4d6`.
Вход: `build/v6q-board-01/150000/{progress-decoded,diagnostics-decoded,
physical-analysis,registers-decoded}.json`; physical archive manifest SHA256
`ced3b2e6bae7c310404b1c6eea5ee8b9d4cf227f910383046ac2195c1e282013` сообщён root.
Обе пары64/136 равны, nonce `71d28b8a72c1f51a`, generation3, buildSJ совпали.
Valid64 SHA256 `a2b33237f8b7458fde2dd8a2fc5e06fd9fb4653c28a72815712a75690d429419`.

Первый close — QUEUE/reason1 ДО terminate/drain: elapsed9119434cycles,
номинально126,658806мс при72MHz; READY1024, tx1152/1335, q8/8, FIFO free64,
held/deferred=true, task_ready=false. Positive DATA FIFO acceptance22512bytes/
67callbacks, actual zero-space47, other-zero0. Последний positive был29403cycles
(408,375мкс номинально) до close. Завершённые prepare spans3483366cycles/145
включают cached/обычный prepare и Q-prefetch, IRQ/observer; это не CPU share.
Max no-positive9,725мс включает начальную сборку1024, не является USB stall.

Legacy: ADCfault0, acquisition reason1, max poll2952мкс, copy184мкс,
step229004cycles. Max poll ниже3413 показывает лишь отсутствие пойманного
service-deadline в этом опыте. Это не достаточная средняя разгрузка очереди
и не доказательство исправности/полноты ADC. Legacy включает более поздний drain.

На wire18 полных DATA/18432, ENDseq22 reason1/CRC3873357665 до hostSTOP4,
ACKseq23. Record14336 `[4096,18432)` согласован с сохранёнными данными; offline
проверка PASS, physical sustained150k FAIL. Final wire включает drain после
first-close, не равен числу переданных/committed до fault. Один Q2 против
одного P2 (18 против12 кадров) не является контролируемой оценкой эффекта Q.

## Точная цепочка, которая объясняет место отказа

Source anchors далее — `build/v6q-fw-01/`:

- `patched/v2/app/mt_live_runtime.c:299,317,324`: task сначала обрабатывает
  прежние completion events; ADC service стоит ДО единственного ordinary
  grant. В cached проходе hint не откладывает его. Внутри ADC service четыре
  offer128 идут после проверки private DMAhalf512 (`app/mt_live_adc.c:83–124`).
- `protocol/mt_live_device.c`, `mt_live_device_offer`: queue push FULL вызывает
  first-close, затем terminate. Поэтому отказ этого прохода наступает раньше,
  чем его normal grant/TX/prefetch. N snapshot не фиксирует будущее состояние
  после возможного grant.
- `app/mt_live_runtime.c:111`: whole-fit `available < length` даёт known0 без
  FIFO mutation. `protocol/mt_live_device.c`, `step_tx`: offer=min(remaining,384).
  Здесь remaining=183, свободно64: для whole-fit не хватает119байт. Это прямой
  backpressure уже готового кадра, не повторная тяжёлая подготовка и не EMPTY
  staging случая P2. Partial admission64 не освободит1024 staging до принятия
  всех183; добавит ещё guarded pass, поэтому само по себе не обоснованный fix.
- Prefetch (`app/mt_live_runtime.c:235,400`) допускается после actual final-time
  full commit+flush. При1152/1335 сертификата ещё нет; выполнять Q collection
  поверх READY было бы перезаписью непереданных bytes. Сохранность очереди и
  честный queue-full здесь предпочтительнее скрытого overwrite/gap.
- `source/.../tinyusb/src/tusb.c:401–442`: CDC FIFO route публикует count из
  FIFO; `dcd_transmit_packet` (`patched/dcd_stm32_fsdev.c:894–919`) снимает
  из FIFO до64 при загрузке PMA, до физического USB completion. Free64 означает
 320байт остаются в FIFO; это не количество байт уже доставленных host.
- `patched/dcd_stm32_fsdev.c:180–194,355–387,582–625`: grant открывает максимум
  шесть обслуживаний; continuation только для того же intermediate CDC IN,
  с проверками endpoint/FIFO/lifecycle/error и TIM2 elapsed<500. Final IN
  остаётся held и ставит task event. CDC callback (`source/.../cdc_device.c:515`)
  после следующего task может опубликовать новый FIFO transfer, который ещё
  ждёт runtime grant. Held/taskfalse также возможен при intermediate hold
  после старения окна или budget/прочего отказа. По64B нельзя выбрать один путь.

## Capacity и сроки — расчёт, не измеренные доли

При150000 samples/s один1024 период —6,826667мс, DMA512 —3,413333мс.
Для full frame1335 требуется195556,64 wire bytes/s и146,484 full DATA/s.
При отдельной передаче фрагментов384+384+384+183 это21 data-IN packet/frame,
приблизительно3076,17packet/s, четыре publications/frame. Реальные CDC FIFO
границы, ZLP/control/short transfers могут отличаться; это не абсолютный
IN/ISR максимум. Номинальные12Mbit/s USB FS сами по себе не гарантируют темп:
нужны своевременные PMA/CTR, task rearm и foreground publication.

Queue8×128 содержит6,827мс ADC-данных, READY1024 ещё6,827мс; конечный размер
хранилища покрывает задержку, но не исправляет устойчивый дефицит разгрузки.
Для нынешнего deficit119bytes нужно освободить как минимум ещё119байт FIFO;
если активный transfer полный и FIFO снимается пакетами64, это не менее двух
дополнительных PMA loads. Неизвестны xfer.total_len/queued_len и pending CTR,
поэтому время до них и количество grant-проходов из этого снимка не следуют.

**Не переносить grant безусловно перед ADC.** 2952+500=3452мкс >3413 даже как
грубый контрпример на наблюдавшихся числах. Причём500 — проверка разрешения
продолжить ПОСЛЕ packet handler, а не WCET всей скобки/последнего handler.
Остальные fresh TIME/scope/ISR затраты ненулевые. Само правило вида «age<2913»
не даёт доказанного запаса и не заменяет ADC ownership/post-copy checks.
Pre-ADC opportunity с доказанным динамическим deadline admission потребовала бы
отдельного контракта; saved maxima для него недостаточны.

## Одно рекомендуемое следующее ограниченное действие

**Сначала один минимальный per-transfer gate-observation кандидат, не очередной
неподтверждённый scheduling fix.** Нынешние данные обосновывают место backpressure,
но не различают last-IN intermediate-time/budget hold, final/task turnover
и transfer, который опубликован, но ещё не получил IN. Выбрать correction
между ними по held/taskfalse означало бы угадать причину.

Предложение для отдельного review: маленький last-transition bank **не более
24байт ВСЕЙ добавленной static памяти**, существующие64/136 сохраняются.
Его обновляет только фактическая CDC-IN публикация/hold с точной привязкой к
текущему transfer. Нужны именно: publication serial (с явной saturation),
последняя transition/cause, DWT timestamp, total/queued, remaining packet
budget и TIM2 age **в момент решения**, validity/frozen. Начало нового transfer
должно инвалидировать cause прошлого: stale FINAL не означает нынешний FINAL.
ISR/foreground writer serialization и first-close до drain обязательны.
Свежесть нельзя восстанавливать просто по одинаковым total384/queued64.
Полный ABI пока TBD до независимого согласования; это не разрешение24B layout.

Лучше один bank без второй frozen копии/private counter: запись publication
происходит под существующим IRQ guard; ISR обновляет ту же current-transfer
историю; N ACTIVE→CLOSING запрещает все поздние обновления, а paired dump
сохраняется до terminate/drain. Unknown/saturated/old-transfer должны быть
явными. Снимок не должен dispatch task, flush, grant, читать ADC_DR или добавлять
TIME-health loops. Результат связан с exact image и matching64/136 identity.
Инструментировать evaluated hold reason, а не повторно вызывать volatile/TIME
предикаты в ином порядке ради диагностики. При невозможности доказать это
в24байтах scope остановить и выбрать replacement ABI, не выделять512B profile.

Сейчас data128+bss12132+reserve8192=20452/20480, осталось28байт. При росте≤24
остаётся минимум4байта сверх reserve; реальный linker alignment, ВСЕ private
поля и stack/ISR paths требуется проверить exact ARM. Это допустимый потолок
проекта замера, не уже подтверждённый ресурс. Hot stores/branch/DWT reads имеют
observer effect; не вычитать их как точную поправку и не принимать такой опыт
за qualification неизмерительного образа.

Bounded следующий результат: один actual-C transition/freeze/transfer-freshness
model плюс source guard equivalence и одна ARM/resource проверка, затем только
после независимого exact-plan допуска один150k опыт с first-close. Широкие GUI,
старые serializer/ADC suites и новая серия вариантов не нужны. Критерий полезности
— валидно различённый gate path текущего transfer, а не большее число кадров.
Если last reason TIME/budget — исследовать возраст/разрешение continuation без
расширения6/<500. Если FINAL/publication — исследовать event/task/grant turnover.
Если transfer waiting/IRQ permit без completion — отдельно проверять USB/host
service. Ни один исход заранее не означает изменение host или увеличение буфера.

## Можно ли закрыть пробел прежними traces

S9/F2 сохраняет именно нужный **вид** instrumentation: `firmware/v2-stream/
profile/mt_stream_profile.c`, `mt_profile_transfer/in_packet/guard`, и frozen
`build/v6f-fw-03/patched/dcd_stm32_fsdev.c:631` записывают первый фактически
вычисленный false в исходном short-circuit выражении. В сохранённом F2
`build/v6f-board-01/profile-time-analysis.json` есть grant allowed26/denied15,
IN transfers16,76packets, resume59, hold-final16, hold-time1, budget0. Это
показывает пригодный технический приём, но не причину нынешнего Q2.

F2 — S9/100k, DATA128,512B observer, без поздней подготовки mode5/1024 и Q
prefetch. В Q2 те же базовые6/<500 и FIFO384, но иное расписание, размер
staging/кадра, путь final-time commit и иная нагрузка. SA также предшествует
этим изменениям. Переносить измеренные proportions/вывод «timer не важен» из F2
в Q нельзя. Даже F2 cumulative counters не дают current-transfer total/queued
и age/cause на момент именно Q2 fault. В точном SJ никакой S9 bank/скрытой
истории нет: current136 содержит только maxima и итоги,64 не хранит grant age,
budget, IN transfer identity или evaluated hold branch. Сохранённые Q2 raw
64/136/остановленные регистры этого не восстанавливают; после drain живые
DCD/FIFO поля уже относятся к более поздней передаче. Дополнительный offline
пересчёт старого файла не заменит отсутствующее наблюдение.

Конкретный следующий draft — только `gate-contract.md` рядом с этим разбором:
24B transition/current-transfer record с first-close freeze, без phase profiling,
новых периодических TIME loops или переноса рабочих endpoint/MMIO reads.
Статическая граница и source/native/ARM обязательства остаются проектными.

Независимый critic в пассивной переписке также не нашёл единственной correction
из snapshot; отметил ISR→FG/freeze race и current-transfer freshness. Это не
formal admission предложенной диагностики. Production и SJ на плате сохранены.
