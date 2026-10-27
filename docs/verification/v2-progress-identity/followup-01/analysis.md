# P2: пустой staging после завершения DATA и переполнение очереди

27.10.2026. Offline-предложение одного следующего изменения; production,
сборки, тесты и COM/SWD/Reset/Flash/START не выполнялись. На входе exact SI
`build/v6p-fw-01` и сохранённый P2. Исправление observer сработало, но150k
по-прежнему не прошли физическую проверку.

## Факты и допустимые выводы

Входы `build/v6p-board-01/150000/{progress-decoded,diagnostics-decoded,
physical-analysis,registers-decoded}.json`. Одинаковые64/136, build SI,
nonce`b028756735517057`, generation3; errors нет. SHA64
`deaf04c7eb5a82f9d2b2280d0d7a7be50e7bc968679761fa50df95c553f0cfda`.

Первый close — QUEUE/1, до terminate/drain. В этот момент:

| Поле | Значение | Ограничение |
|---|---:|---|
| elapsed | 6184077cycles ≈85,890мс | Номинальные72МГц, inclusive IRQ/observer |
| prepare | 96 / 2246855cycles ≈31,206мс | Не CPU share; не только encode |
| DATA positive acceptance | 44 / 14685байт | FIFO acceptance, не USB delivery |
| zero-space / other | 27 / 0 | Реальная нехватка FIFO в прошлом, не снимок текущей записи |
| TX / staging / queue | 0/0; EMPTY/count0; 8/8 | Старый frame завершён, новая сборка ещё не началась |
| FIFO free / IRQ / task | 201; held+deferred; ready=true | Есть183занятых байта; событие и причина hold не типизированы |
| Последний positive→close | 34124cycles ≈473,944мкс | Включает дальнейшие операции, не чистый USB gap |
| Legacy ADCfault / maxpoll / copy | 0 / 2953мкс / 184мкс | Poll ниже3413, но drain недостаточен в этой попытке |

Нет unknown/partial/open-prepare/saturation/DWT-invalid flags. Арифметика
14685=11×1335,44=11×4 согласуется с11полностью FIFO-принятыми DATA1024
по384+384+384+183. Пустой staging соответствует завершённому core commit
после последнего TIME guard. Финальные12DATA/12288 и ENDprefix12288,
CRC2018795817 включают drain; двенадцатый кадр не переносится в first-close.
ENDreason1 был до host STOP, offline wire/raw/Open проверка прошла.
Остановка TIM3/ADC/DMA и PSC47/ARR9 подтверждена отдельно сохранённым decoder.

Queue8×128=1024samples — номинальные6,827мс ёмкости, а очередной DMA half512
порождает четыре последовательныхoffer128 каждые≈3,413мс. Освободить четыре
слота в подходящей фазе может быть существенно даже при своевременном poll.
Снимок не сообщает occupancy перед первым offer этого half: очередь могла
уже быть полной либо заполниться несколькими успешными offer перед отказом.
Неизвестны точное произведённое число и потерянный хвост.

P2 доказывает конкретный неблагоприятный порядок, **не единственную причину
неустойчивости**. Maxpoll2953<3413 не является достаточным темпом транспорта.
Короткий host-slope≈116355samples/s и31,206/85,890 нельзя выдавать за
устойчивыйFs или долю CPU. Сравнение12кадров SI с20SH неконтролируемо:
в SH observer не работал, в SI его overhead снова присутствует.

## Exact order, который оставляет пустой staging перед ADC

Все пути ниже — в `build/v6p-fw-01`.

1. `patched/v2/protocol/mt_live_device.c:705–774`, `step_tx`: последний
   положительный write старого mode5 frame готовит completion; глобальный
   prefix/CRC и batchEMPTY публикуются **после последнего now/bound**, только
   затем управление возвращается в runtime. Queue этого следующего frame
   не собирается внутри commit — и не должна тяжело собираться под PRIMASK.
2. `patched/v2/app/mt_live_runtime.c:347–358`: unlock → fresh TIME/loss →
   app scope/usable + explicit `tud_cdc_n_write_flush` → leave → freshTIME/loss
   → return. Здесь нет collection нового batch.
3. Следующий проход `:258–280`: task → freshTIME/loss/stable → app scope →
   **ADC service**, и лишь позже `:319` вызывается обычный prepare.
   `mt_live_adc.c:115–119` после validated private512 вызывает четыре offer128.
   При FULL core offer`:785–787` фиксирует N first-close до terminate.
   Поэтому пустой TX буфер не спасает full queue: collection находится позже.
4. `mt_live_device.c:478–485`: cached TX возвращается из build_tx до collection.
   `batch_prepare:399–445` в обычном prepare забирает≤4queue blocks/512samples,
   затем при полноте может выполнить seal/frameCRC/COBS. Нельзя просто вызвать
   его целиком перед ADC: это добавит тяжёлую работу на критическую границу.
5. `source/firmware/third_party/usb/vendor/tinyusb/src/tusb.c:401–437`:
   CDC write сам пытается flush при FIFO≥64, а explicit runtime flush ещё
   пытается claim/arm transfer. Claim может не пройти из-за BUSY; final-IN
   callback из `cdc_device.c:516–523` запускается через task. Поэтому183FIFO
   bytes и task-ready не доказывают, что новый tail уже идёт по USB.

## Один выбранный шаг: collect-only после успешного последнего TX commit и flush

Предлагается bounded **prefetch queue→existing empty staging** в конце прохода,
который полностью завершил старый STREAMING mode5 DATA1024. Точка — ПОСЛЕ
существующих explicit flush, freshTIME/loss и подтверждения актуальности,
перед return. Не перед ADC, не внутри PRIMASK completion и не в DMA publish.

Это более узкая область, чем новый pre-ADC/publish512 schedule. Последний
cached write проход не собирал/кодировал batch: full1024 frame>384, поэтому
не может закончиться в первом write. Его existing prepare лишь вернул cached
bytes. Значит дополнительный collect≤512 не увеличивает прежний максимум
collection512 на один проход и не требует второго общего budget/state.
Следующий обычный prepare использует уже COLLECT512 и завершает batch по
прежним правилам. O hint/grant budget сохраняются.

Eligibility должна подтвердить именно успешный переход:

- Старый actual ticket PREPARED/DATA/mode5, count1024/READY, cached offset>0.
  Сохранённые nonce/generation/revision/sequence относятся к тому же core.
- Guarded step успешен, после последнего TIME completion действительно
  опубликован: stateSTREAMING/mode5, tx0/0, batchEMPTY/count0,
  prefix_end==old_first+1024, last_data_sequence==old_sequence и новый
  prefixCRC==old_batch.prefix_crc. Это проверка результата, не вывод из tx_ok.
- Нет Stop/HELLO/control/error/start/end/ack intent, sealed queue, смены
  session/epoch, clock fault или hardware-off. Иначе нового prefetch нет.
  Modes1–4, zero/partial/unknown/late write, stale ticket и recovery не меняются.

Prefetch — только общий с existing prepare **collect-only helper**:
инициализировать существующие TX metadata/state32, проверить текущие queue
views/индексы/counts/коды, перенести максимум4×128 в packed staging и атомарно
проверить/pop_many. Применять прежний work-copy/shared-byte retry контракт.
Не вызывать seal, frameCRC, COBS, write, quiesce или другие callbacks; не
продвигать глобальные accepted prefix/CRC, sequence либо produced_end. При нехватке
queue брать только доступное; никакого padding или ожидания/остановки ADC.

Минимальный предлагаемый API: `mt_live_device_prefetch_tx(d, ticket)` с прежним
`mt_live_prepare_result`. На входе ticket — actual завершённого old frame;
helper сам проверяет eligibility до новых ownership stores. На SKIP/успешный
collect возвращает EMPTY (это не готовый frame), на ошибку — ERROR с текущим
matching ticket для прежнего guarded error path. Старый локальный ticket
можно переиспользовать только после полной проверки всех old-result полей;
дополнительный persistent state не нужен. На положительном пути вызывающий
код не запускает step_prepared второй раз и не пытается отправить COLLECT.
Не начинать новый batch при sequence exhaustion/RESERVE или active control
budgets; сохранить прежний sequence-limit путь следующего обычного step.

Packing и **локальный canonical prefixCRC** при collect всё равно стоят CPU:
это не memcpy. За512 samples существующий collect обновляет1024CRC bytes.
Вынос после last-write/flush выбирает cached проход, но не доказывает WCET.
Сначала сохраняются обе существующие flush-попытки. Если endpoint удалось
armить, восстановленная interrupt mask допускает overlap tail-IN с collection.
Если BUSY/event held, overlap не гарантирован, а next task будет задержан.
Не добавлять task dispatch, второй grant или reset6/500 ради этой возможности.

## Отказные границы и ownership

Перед helper нужны freshTIME+synchronize_loss+usable/stable и свежий app
scope/actor. Он работает с восстановленной interrupt mask, не под write guard.
ISR не может менять core/queue, но может инвалидировать transport epoch.
После copy снова freshTIME/epoch/lifecycle. Потеря актуальности — прежний
abort/cleanup staging+queue; не откатывать popped slots и не маскировать gap.
Никакого следующего ADC/RX/TX по старой identity.

Deferred collect error должен получить текущий actual ticket/error и прежнюю
guarded recovery без DATA-публикации. Можно переиспользовать существующий
локальный ticket после проверки успешного old completion. Ошибка не отменяет
уже принятый старый префикс. Первый N close остаётся до cleanup; поздние
эпилоги не изменяют frozen64. Новую подготовительную работу учитывать тем же
prepare-span механизмом с явным уточнением, что spans теперь включают prefetch;
новые диагностические поля/ABI не нужны, CPU share из суммы не выводится.

Stop после prefetch сохраняет непринятый диапазон в batchCOLLECT: обычный drain
добавляет contiguous certified queue/tail, seal выдаёт actual short1..1023,
END ждёт queue+stageempty. HELLO при zero offset использует существующий
`begin_hello:171–194` discard old unpublished staging; при stale epoch cleanup
также не переносит old bytes в новую сессию. Новая sequence не расходуется до
первой реально принятой DATA-записи. Эти правила необходимо адресно проверить.

Контрфактическая польза P2 ограничена: если в last-completion проходе имелись
четыре старых блока, prefetch мог освободить четыре места до следующего512
offer. Снимок не фиксирует occupancy тогда или точный pending DMA phase,
поэтому это **проверяемая гипотеза**, а не доказательство предотвращения P2.

## Ресурсы и минимальный следующий допуск

Новый buffer/state запрещён: тот же TX1336, batch32, queue8×128. Цель0новых
static bytes; существующий запас28B сверх8192reserve не расходовать.
Views/work-copy и переиспользуемый ticket требуют exact ARM stack audit.
Дополнительное collect-время входит в интервал до следующего ADC poll;
deadline3413мкс и проверки истории/последовательности не расширять. По числу
итераций нельзя обещать, что remaining deadline выдержан.

После отдельного scope достаточно одной адресной actual-core/runtime-boundary
модели: known final commit→flush→collect, q8→q4→четыре contiguousoffer без
prefix advance, ring wrap и byte/CRC identity; отсутствие prefetch на
zero/partial/unknown/post-TIME failure/stale/Stop/HELLO; epoch/TIME во время
copy; Stop/HELLO с новым owned-but-unpublished диапазоном. Остальные DMA/
wire/USB/TIME алгоритмы сохранить source-pinned, не повторять широкие suite.
Затем exact ARM/RAM/stack и независимый review; отдельный root-план решает
одну аппаратную попытку. Ни устойчивые150k, ни возврат прежней прошивки этим
offline-предложением не объявляются и не разрешаются.
