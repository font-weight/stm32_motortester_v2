# S2/SL: поздний свободный FIFO и возможный порядок отправки

28.10.2026. Только offline чтение сохранённых S2 данных и exact SL source.
Новых правок firmware/тестов/сборок/COM/SWD/Reset/Flash не выполнялось.
Это разбор отрицательного опыта и одна гипотеза следующего изменения;
source/software9,60 не превращается в physical150k PASS.

## Пригодные факты

Вход: `build/v6s-board-01/150000/{physical-analysis,diagnostics-decoded,
progress-decoded,gate-decoded}.json`. Source
`695efd95e7c4ba72bfa6fb5fb511b85186be6266`, exact image
`f82311cde2ce0a3e735543006b2bc7890e8761434c73e7adc7fa332f86cb8cb2`,
ELF `3034a77fa007f872f32ff145b58f39f21e2e3d62d79919eb7505d05d3c1313db`.
Nonce `bdfc52fdf5a8dab9`, generation3, mode5/150k/10 retained bits.
Пары136/64/24 пригодны, errors=[]:

| Банк | SHA256 | Существенные поля |
|---|---|---|
|136|`a106ae43651f3436cc4ed785f6df7cf6fcaa4a0ad6146e27b125f72b2e54fbda`|firstreason1, ADCfault0, queuepeak8, pollmax2939us/copy167us; step166, TX166, copy43|
|64|`c0c04191fb9f6dba4f6d2b50ef84ec6d0036e89bc357a18e8da252589c33c553`|q8, stage READY1024, tx1152/1335; FIFO free384, held0/deferred0/task_ready0|
|24|`bb02bf65875e0a453bb025c6811aca258b08fb6f8bee684158bab9951838323c`|RESUMED serial82, PREtotal384/queued320, evaluated age460us, remaining budget1; ACTIVE1/APPLICABLE0|

Один START150k/30s завершился source queue-full:21 full DATA1024/21504кода,
END25 reason1/flags3/unknown produced_end до host STOP4, затем ACK26. Raw,
индексы, CRC1998538068 и повторное открытие сохранённого диапазона root
проверил offline; это корректный сохранённый префикс **с отказом**, не30s
непрерывного потока. Полученный wire включает drain после first-close.

N64: elapsed10615933cycles≈147,443514ms номинально72MHz; completed prepare
4207931cycles/count159≈58,4435ms inclusive, **не CPU share**. DATA acceptance
в FIFO26517B/79, zero-space45/other0. Last positive→close67486cycles≈937,306us;
max positive gap698606cycles≈9,703ms включает стартовую сборку1024. Эти величины
не являются измеренным устойчивым bandwidth или USB delivery.

Сравнение R2 и S2 ограничено: число полных wire DATA, accepted bytes/count и
zero-space в этих двух опытах совпало; FIFO/последний gate существенно разные.
Это два отдельных неконтролируемых опыта. Ни улучшение, ни полное отсутствие
эффекта S, ни вход в `postcopy_hint` из этого совпадения не доказываются.

## Почему FIFO384 не означает, что write ранее мог принять183

Exact anchors — `build/v6s-fw-02`:

1. `patched/v2/app/mt_live_runtime.c:111–127`: `live_write` делает whole-fit
   check **внутри** guarded core transaction. При free<offered возвращает
   known0 без `tud_cdc_n_write`; позднейшее освобождение FIFO этот исход не
   меняет. Текущий остаток1335−1152=183.
2. `patched/dcd_stm32_fsdev.c:625–666`: G24 записывает tuple **до** IN handler.
   PREqueued320<total384 означает intermediate ACK; handler загружает следующий
   min(64,384−320)=64 в PMA. Стабильность backing/total/POSTqueued384 проверяется
   actual candidate logic. RESUMED означает, что существующий predicate
   разрешил продолжение; это не HOLD_TIME, не FINAL и не доказанное истощение
   budget. Budget1/age460 — operand того решения, не новое500us WCET.
3. На FIFO path эти последние64 извлекаются из FIFO при PMA load. Поэтому
   свободно384 при следующем snapshot совместимо с тем, что **только что**
   закончилась передача FIFO→PMA текущих384. Последний64 ещё может ждать ACK;
   queued384 не равно доставлено384. FIFO уже может принять следующую183,
   хотя class transfer BUSY и его completion ещё не обработан task.
4. G event3120308730 → N end3120308954 =224cycles≈3,111us. Это очень поздняя
   наблюдённая IN progress относительно first-close, не время предыдущего
   whole-fit check. Между last positive и event было67262cycles≈934,194us;
   время последней zero-space попытки в64 не записано.
5. `mt_live_device_offer:828–835` получает queue FULL **до** вызова close.
   `mt_progress_close:146` сначала публикует CLOSING, затем берёт DWT end:156,
   и только `snapshot:127–130` получает IRQ lock и читает FIFO/held/task.
   ISR может оказаться между уже решённым FULL и CLOSING, либо между CLOSING
   и поздним USB snapshot. Поэтому новый свободный FIFO не опровергает
   прежний FULL/known0 и не разрешает ретроспективный commit.

24/64 не синхронный снимок одного эпизода. RESUMED/APPLICABLE0 историчен;
held0 в64 лишь совместим с возобновлённой IRQ обработкой. Он не доказывает
причину предыдущего held, отсутствие новых событий или выполнение S handoff.

## Два source-допустимых маршрута отказа S

`postcopy_hint:295–313` — консервативная проверка mode5/cached-final/lowroom,
включающая отсутствие carry/partial RX/controls/task work. В N64 нет ни результата
hint, ни handoff_consumed, ни private-receipt phase, ни последнего write stamp.
Нельзя утверждать, что именно эта новая ветвь исполнилась или не исполнилась.

- **Ordinary/cancel-before-selection.** Hintfalse оставляет прежний service,
  который copy512 и четыре offers выполняет до ordinary grant/TX. Healthy
  cancellation после acquire также идёт к original offers. Queue8 может
  отказать раньше, чем current pass вообще достигнет своей TX opportunity.
  ISR от предыдущей grant opportunity в это время всё ещё может освободить
  FIFO. Pending task/control мог отменить fastpath, но это не измерено.
- **Selected handoff + позднее место.** `postcopy_handoff:400–427` расходует
  одну opportunity, даёт grant, делает свежие проверки и один guarded cached
  TX. Если тот увидел недостаток FIFO и дал known0, затем **безусловно**
  выполняется existing flush, свежие barriers и pending offers. Final commit
  не произошёл → Q certificate не допускает collect → stage остаётся READY,
  queue8 не разгружена. IN progress может освободить FIFO уже во время этих
  barriers/offers или close. Второго TX в этом pass намеренно нет.

В обоих маршрутах q8+READY означает заняты существующие независимые queue и
staging; ADCfault0 не означает способность своевременно освобождать их.
Полный validated private copy и driver poll2939<3413 — другая обязанность,
чем sustained queue→staging→FIFO drain. Верхняя observed величина не WCET.

## Что реально делает existing flush

`source/.../tinyusb/src/class/cdc/cdc_device.c:221–224` вызывает
`tu_edpt_stream_write_xfer`, даже если предшествующий whole-fit write вернул0.
`source/.../tinyusb/src/tusb.c:401–421`:

- проверяет уже имеющиеся FIFO bytes и пытается claim endpoint;
- если BUSY/claim отказал, возвращает0, не ждёт и не dispatch task;
- при успешном FIFO submit берёт current FIFO count и запускает DCD transfer;
  первый PMA64 может освободить часть FIFO немедленно, остальные — при IN IRQ.

Там нет необходимости сначала принять новые183. Значит source допускает
невыгодный порядок: grant window уже стартовало → write ещё видит мало места
и возвращает0 → **лишь post-write flush** запускает buffered transfer → IRQ
продвигает его во время последующих проверок → место появляется к first-close.
Gate serial82/age460/RESUMED согласуется с таким маршрутом, но не фиксирует
publication callsite/BUSY в момент flush и не доказывает его как единственную
причину S2. Старый transfer мог быть BUSY уже до handoff, либо hint отменился.

`tu_edpt_stream_write:425–434` также пытается auto-flush после accepted write,
если FIFO>=MPS. Успешная запись183 могла бы сделать это сама, однако known0
ветвь `live_write` туда вообще не заходит. Existing explicit postflush поэтому
особенно важен после zero acceptance. Убирать его без отдельного доказательства
для partial/small/control paths не следует.

## Один следующий bounded вариант: preflush buffered bytes до sole grant

Предложение для отдельного контракта, **без реализации в этом разборе**:
только после actual private BLOCK512 и проверки cached-final ticket в selected
handoff добавить **одну** попытку existing CDC flush перед sole grant/sole
guarded DATA attempt. Preserve old post-write flush/Q ordering. Цель — запустить
старые FIFO bytes до fresh grant window и до whole-fit admission, а не узнать
позже, что FIFO успело опустеть.

Новый порядок: selected marker → fresh TIME/loss/stable/original identity →
nested same-actor preflush → fresh TIME/epoch/lifecycle → прежний sole grant →
fresh admission → прежний sole cached TX → existing postflush/barriers → actual
final certificate/Q → fixed publish_next loop. Preflush ничего не добавляет в
FIFO, не advance prefix/sequence, не делает task/RX/encode/collect и не выдаёт
ещё один grant. Если endpoint BUSY/нет данных/нет host IN, он просто0; spin,
ожидание и вторая DATA попытка не разрешаются. Postflush остаётся для прежнего
частичного/нулевого/положительного исхода и сохранения Q boundary.

Все сохранённые S ограничения обязательны: private512 только на стеке; никакого
повторного read/overwrite или RX до disposition; original poll origin/strict
3413; fresh barriers до/после USB boundary; no offers после **наблюдённого**
loss, raw lifecycle quarantine при прежнем epoch, matching ticket и guarded
final TIME/CRC/prefix commit; one consumed TX/grant opportunity даже при refusal.
Нового static/private state, банка или queue slots нет. Добавится только один
bounded existing API call и его required barriers в узкой ветви. Actual cost
не измерен,500us не становится whole IRQ bound; возможен честный новый deadline
failure. Это может помочь, **только если** preflush смог запустить buffered
transfer раньше. Если он уже BUSY или fastpath не выбран, эффект может быть0.

Это предпочтительнее трёх альтернатив в текущем evidence:

- Pre-ADC grant снова отнимает время до критического poll;2939+500=3439>3413
  даже при неправомерном использовании observed maximum и admission500 как
  WCET. Такое изменение не обосновано ресурсом времени.
- Второй last-chance DATA write после queue failure/known0 потребовал бы нового
  retry/accepted-byte/ticket контракта и изменения one-attempt дисциплины.
  Actual FULL уже seals queue/закрывает first cause; откатывать его нельзя.
  Частичная публикация по free bytes также меняет whole-fit contract.
- Дополнительная очередь/статический buffer не устраняют неподтверждённый drain
  rate; после reserve8192 физически остаются только4B.

## Минимальное необходимое следующее свидетельство

Не включать ещё один profiler по умолчанию. Если root/critic допускают этот
вариант, один focused actual-runtime/core + existing FIFO/xfer boundary model
должен различить: free<183, endpoint claimable, buffered transfer запущен
preflush и существующая IRQ opportunity освобождает FIFO → sole write/final/
Q/publish; против BUSY/no-IN, где результат остаётся honest known0/qfull без
spin/второго grant. Нельзя ограничиться seam, который магически ставит384
после любого flush: claim/initial64/дальнейшие IN должны быть явными стадиями.
Те же saved identity/lifecycle/TIME/partial/final-error проверки нужны только
в затронутой границе, не старый общий suite. Source/DCD/MMIO/CRC algorithms
сохраняются; одна exact ARM/resource/stack проверка при реализации.

Дальше только отдельный точный root hardware plan и критерий полного150k
интервала. Если и этот узкий порядок не обеспечивает запас, нельзя выбирать
следующую микроправку лишь по числу кадров; потребуется пересмотр whole-fit/
turnover архитектуры с явным новым контрактом. SL и все отрицательные данные
этим разбором не изменены. Текущий результат остаётся queue-full/physical FAIL.
