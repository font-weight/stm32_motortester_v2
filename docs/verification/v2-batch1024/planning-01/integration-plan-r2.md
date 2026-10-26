# L1 r2: отложенный mode5 commit после последнего core TIME

26.10.2026, редакция2. Исходный integration-plan.md/SHA7dcdfa05d14912bc3e23b1781ce2c55f9e2c87cd9f326fb2817574ec4329a6f8 сохраняется неизменным.

Уточнение r2: SD completed() выполняется до последнего now в step_tx.
Поэтому mode5 не может публиковать глобальный prefix внутри обычного completed.
Эта редакция заменяет только эту границу и необходимые свидетели проверки.

Основание: SD/cb475794, canonical
`docs/streaming-batch1024.md` (DRAFT), frozen isolated prototype
`build/v6l-prototype-freeze.json` SHA
`3b4e3493ffd548d23c00888018e8354e4f65b25547fd9672c67dc561c14fcf0b`.
Native01 и C1153→host прошли, но production lifecycle ими не проверен.
Этот файл не меняет SD, не разрешает Flash и не объявляет stable150k.

## 1. Точные изменения и бюджет

Добавить новый strict overlay ПОСЛЕ SD batch256, старые слои не переписывать.

| Файл | Изменение |
|---|---|
| protocol/mt_live_device.h | Отдельный `MT_LIVE_TX_CAPACITY=1336`, только tx увеличивается; caller-owned batch state32; расширение foreground ticket32 |
| protocol/mt_live_device.c | Mode5 prepare/ownership/stages, final cached-CRC commit, END guard, явный cleanup в recover/HELLO/transport loss |
| acquisition/mt_sample_queue.h/.c | Новый bounded peek/pop-many1..4, validate-all до одной head/used мутации; прежние peek/pop/pop_span1..2 сохраняются |
| selectable/mt_acquisition_profile.c | Mode5:150000,PSC47/ARR9,period20/3,deadline3413,CEN5,retained10/encoding2,max1024 |
| batch1024/mt_batch1024.c/.h | Frozen prototype подключается без изменения, либо новая явно pinned delta при найденной интеграционной необходимости |
| config/board_inputs/build_windows | Отдельный root-assigned build (TBD до сборки), modes1..5, strict overlay+module object |

`mt_wire.h/.c` остаются общими control/legacy codec512/544. Не расширять
`rx[543]`, `previous[543]`, `mt_wire_message` или `raw[540]`. Большой DATA5
готовит отдельный serializer; generic control encoder использует свой прежний
лимит даже при большей capacity выходного tx. Runtime source, TIME, ADC/DMA,
DCD, FIFO384/MPS64/burst6/<500мкс и H early grant планируется оставить
побайтно неизменными. Реальное source-equivalence подтвердить после overlay.

Статический расчёт:19564+792TX+32state=20388/20480 с8192stack reserve,
остаток92. Это небольшой, но явно ограниченный остаток; новые static buffers
запрещены. Ticket32 и до4 borrowed descriptors находятся на foreground stack,
а не добавляются в SRAM второй копией. Старый ticket limit224 потребуется
явно заменить на подтверждённый ARM bound (цель≤256). Нужны exact final map,
полный callback/IRQ stack analyzer; module `.su`36bytes этого не заменяет.

## 2. Согласование и неизменные старые режимы

Discovery0.2: cap15/global maxblock1024/maxpayload1300. Fresh другая nonce
HELLO0.3(mode1/2/5). Selected ACK cap1: payload512/max128 для1..3,
payload512/max256 для4, payload1300/max1024 для5. CAPS5 точно
`(5,5,0,12,150000,1,1024,1,10,2)`. Старые modes1..4/markers/CAPS сохраняются.
Публичный150k требует5; START до точного ACK/CAPS/config5 не допускается.
Host intrinsic mode5/`0.3-batch1024-20261025`, canonical stored u16le/adc12.
Действующие nonce/revision/generation/reserved/CRC/stale-envelope правила
остаются. Ни timeout fallback, ни автопонижения частоты.

## 3. Три разных границы данных

- `prefix_end/prefix_crc_state`: только полностью известные принятые frames.
- `[tx_first_index, tx_first_index+batch.count)`: in-flight staging, уже
  исключённый из queue, но ещё НЕ wire prefix. В state32 rolling candidateCRC.
- Queue: следующий непрерывный диапазон до queue.next_index. При активном
  staging queue.head_index равен staging exclusive end, при пустом staging
  — prefix_end. До gap последовательно; никакого склеивания через fault.

Identity staging использует существующие tx_nonce/tx_mode/tx_revision/
tx_first_index/tx_sequence плюс текущую generation (меняется только после
HELLO commit). Отдельный статический identity struct не добавляется.
Сбрасывать staging — потерять этот непереданный диапазон, а не принять его.
При loss/Abort он остаётся incomplete/unknown в старом сеансе.

## 4. Prepare до IRQ guard: перенос владения, не prefix commit

Предлагаемые private helper names:
`batch_idle`, `batch_discard`, `batch_prepare`, `batch_completion_prepare`,
`batch_completion_publish`. Последние два — pure validation/local result и
последующие безотказные constant-size stores соответственно.
Prepare остаётся единственным foreground owner, без callbacks/TIME/clock;
ISR меняет только USB epoch/lifecycle, не samples/queue/core storage.

1. Старые START_ACK/CAPS/HELLO/control готовятся прежде нового staging.
   Уже активный staging имеет приоритет над нефатальными pending controls,
   иначе control encoder перезаписал бы занятый tx. Stop обрабатывается
   сразу в RX, без ожидания передачи; ответ END отложен.
2. При EMPTY и доступной queue начать identity на текущем prefix/tx_next.
   Не начинать collection при sequence exhaustion/RESERVE во время STREAMING:
   старый guarded `step_tx` сначала выполнит terminate reason4.
3. При COLLECT взять до4 соседних блоков и не более512samples/1024total.
   Все indices/counts/pointers/codes проверить до первой queue мутации.
   Переданные mode5 queue codes уже canonical; повторное low2 masking
   идемпотентно, исходный ADC validation остаётся на ingress.
4. Work-copy32 + copies в свободную TX область; новый peek-many фиксирует
   все views. Новый pop-many validate-all, затем одна head/index/used mutation.
   После успешного pop publish work state. Никакого первого pop с возможным
   отказом проверки четвёртого. Никакого CRC под IRQ guard.
5. Это намеренная queue→staging ownership publication ДО IRQ guard. Ticket
   захватывается ПОСЛЕ неё. При stale USB epoch всё staging/queue старого
   сеанса идёт в прежний loss cleanup; старые raw не возвращаются в queue,
   accepted prefix не продвигается. Это не old-G «только byte staging».
6. Pure prepare error остаётся deferred до старого guarded match/error path.
   За scope prepare нет других foreground core calls. При внутреннем abort
   не публиковать незавершённые descriptor state/bytes.

Collection shared-byte retry безопасен исправленным mask owned low bits,
но это не rollback всей стадии. CRC/COBS destructive: монотонно публикуются
cursor/state либо весь frame discard/recovery. Старый state не повторяется
поверх изменённого raw после stale epoch/TIME.

## 5. Scheduler и write guard

Один существующий runtime prepare на проход; не добавлять12 полных loops
на пакет. Предлагаемый начальный bounded режим:

```
ADC service512 → прежний early grant → RX/Stop/HELLO
prepare:
  collect до512 (до4 source slots), если COLLECT
  если count1024 или (DRAINING && sealed && queue.empty): seal
  если CRC/COBS: до6 вызовов serializer.step(budget512),
               суммарно≤1324CRC+1328COBS inputbytes для full frame
  ticket_capture; никаких callbacks/внутренних waits
original IRQ lock → prepared_tx_step → original unlock/cleanup/flush
```

Это объединяет последний collection, late header, CRC/COBS и первый write
в том же runtime проходе. Общее prepare ограничено512samples+2652 wire-input
bytes и фиксированными transition stores; это НЕ измеренный временной bound.
По сравнению с K отсутствие полного message/raw memcpy уменьшает часть
работы, но TIME/IRQ costs остаются. Последний ADC poll обязан поймать реальный
пропуск3413мкс: не ослаблять deadline, не выдавать арифметику за WCET.
Если такой quantum не укладывается, следующий отдельный шаг — ограниченный
work scheduler с промежуточным ADC service и новым order proof, не скрыто
увеличить deadline или заставить DMA ждать USB. Сейчас этого ещё не писать.

Под old `step_tx` использовать d.tx_length/tx_offset как источник принятого
byte prefix, offer=min(remaining,384). `whole-fit` каждого неизменяемого
фрагмента, pre/post TIME/epoch/usable и known0/partial/SIZE_MAX правила прежние.
State32.offset синхронизируется с окончательным tx_offset в batch_complete;
не требуется отдельная mutation после каждого fragment. Не добавлять второй
IRQ grant и не обновлять budget после long prepare: его старение остаётся риском.

Ticket fieldwise содержит весь state32 и прежнюю identity/prefix/queue/TX
информацию. Нельзя `memcmp` padding. Сталый ticket не вызывает I/O или
deferred recovery новой identity. Глобальные bytes mutable только одним FG.

Sequence расходуется, как в SD, на ПЕРВОМ known-positive byte, чтобы не
переиспользовать partially emitted sequence. Collection/known0 не расходуют
sequence. Prefix/count/CRC публикуются только на завершении всего frame.
Не менять sequence semantics на «только в самом конце».

### Deferred completion именно для mode5

Существующий `step_tx` сначала делает post-write now/expire, затем обновляет
известный tx_offset и вызывает completed(d), а ПОСЛЕ этого ещё выполняет
now/after>=bound. Исторические modes1..4 здесь не переосмысливаются, но для5
глобальный prefix НЕ публикуется в этом раннем completed.

На полном known acceptance mode5:

1. Обновить только byte-acceptance evidence и d.tx_offset, как SD. Sequence
   уже расходован первым positive write; повторного продвижения нет.
2. Вместо `completed(d)` выполнить `batch_completion_prepare(d,&pending)`:
   проверить READY/length/count, old tx nonce/mode/revision/generation,
   first_index==prefix_end, prefix_seed==prefix_crc_state и полную tx_offset.
   Это ещё НЕ глобальное завершение. Допустимые состояния — STREAMING,
   DRAINING либо cached old DATA в HELLO_PENDING, но не новая committed
   identity. Queue повторно не pop.
3. В локальную копию state32 перенести tx_offset. Frozen module commit можно
   вызвать ТОЛЬКО на этой копии и локальных end/CRC — проверка/вычисление
   результата без публикации d.prefix_end/d.prefix_crc_state. Либо выполнить
   эквивалентные pure checks и подготовить end/cachedCRC напрямую. При отказе
   — recover до последнего TIME; никакого частичного global completion.
4. Выполнить существующий последний `now(d,&after)` и проверку bound, не
   добавляя обходов или ослаблений. Если now/clock или bound отказал, recover
   прекращает frame/staging. Pending локальные значения отбрасываются.
5. Только ПОСЛЕ успешного последнего core TIME выполнить
   `batch_completion_publish(d,&pending)`: прямые constant-size stores end,
   cachedCRC,last_data_sequence; phaseEMPTY/count0/length0/offset0, txlen0/
   txoffset0. Для old frame в HELLO_PENDING очистить inherited_budget как SD;
   pending nonce и HELLO budget сохранить. Ни callbacks, ни queue pop, ни CRC
   по2048байтам, ни новой validation/recovery после этой точки нет.

Скелет изменённой только mode5 ветви:

```
post_write_now_and_expire_or_recover()
record_known_accepted_bytes_and_offset()
if (frame_complete && mode5_DATA) {
    if (!batch_completion_prepare(d,&pending)) recover_before_final_now()
    mode5_publish_pending = true
} else if (frame_complete) completed(d)  // прежние controls/modes1..4
last_now_or_recover()
if (bound_exceeded) recover_and_return()
if (mode5_publish_pending) batch_completion_publish(d,&pending) // no fail
if (hello_complete) commit_hello(d)                         // прежняя ветвь
```

`pending` локальный, содержит staged end/CRC/lastseq и необходимые уже
проверенные флаги; статическая SRAM не растёт. Полный ARM stack census обязан
учесть дополнительный локальный32-byte state/publish result; предел8192 не
меняется. IRQ guard сохраняется до stores. Caller не может вмешаться между
pure checks, последним TIME и publish: единственный FG owner, IRQ masked.

При отказе последнего TIME после escaped FULL frame host уже может получить
CRC-valid DATA, но device НЕ должен принять этот frame как committed prefix.
Сохраняются last_write_known/accepted и факт irreversibility, выполняются
abort/recovery/isolation/delimiter правила, нормального END/STOP_ACK нет.
Не отправлять END со старым prefix как будто полный escaped frame не был:
это было бы несогласованностью с host. Такой сеанс остаётся incomplete с
явной ошибкой/неизвестным хвостом, а не cleanStop и не PASS без потерь.

Это последняя TIME-проверка ВНУТРИ guarded core step_tx. Последующие runtime
наблюдения времени/epoch после unlock могут обнаружить новую ошибку, но не
отменяют уже завершённый и корректно подтверждённый прошлый commit. Нельзя
обещать отсутствие всех будущих отказов времени.

## 6. Exact lifecycle

| Событие/стадия | Обязательное поведение |
|---|---|
| Stop в COLLECT | Старый terminate сразу quiesce/snapshot/tailappend/seal. Staging сохраняется. Собрать retained queue до1024, последний short только когда queue исчерпана. |
| Stop в CRC/COBS | Уже sealed current count не меняется; закончить его, затем retained queue следующим frame. CRC/COBS cursor монотонный, без перепаковки старого frame. |
| Stop в READY/SEND | Тот же cached immutable frame и offset; завершить, затем queue. Никакой перезаписи буфера END. |
| Queue full/source reason1 | Cause сохраняется; поздний snapshot через gap не append. Сначала staging prefix перед gap, затем имеющаяся sealed queue, затем fault END/ACK. Не превращать в cleanStop. |
| Fresh HELLO, accepted offset0 | `begin_hello` дополнительно batch_discard до нового control encoding. raw_barrier старого сеанса, discarded popped staging не попадает в новый nonce; prefix не объявляется принятым. |
| Fresh HELLO, accepted offset>0 | Как SD cached partial: закончить неизменяемый DATA под tx old nonce/mode5, даже в HELLO_PENDING; deferred completion проверяет old identity, допускает HELLO_PENDING,
но публикует old prefix только после последнего core TIME. Только затем новый HELLO_ACK и commit_hello сбрасывает queue/batch. |
| USB epoch/lifecycle loss | Старый runtime usable отклоняет submit; synchronize_loss→transport_lost/recover немедленно batch_abort/discard. Никакой повтор COBS старого cursor, ни DATA старой identity после нового HELLO. При escaped bytes needs_delimiter/isolation прежние. |
| TIME/unknown acceptance | Старый recover, hardware barrier и first cause; incomplete frame не commit. Offset/known accepted evidence сохраняются для delimiter/barrier. Ошибка часов не выдаётся за source queue-full. |

`raw_barrier`, `abandon_tx`, `recover`, `transport_lost`, `commit_hello` получают
явный batch cleanup ровно в соответствующем пути. Не полагаться только на
tx_length==0: COLLECT/CRC/COBS имеют занятое staging без готового tx_length.
Begin_hello partial>0 сохраняет batch до завершения; общий unconditional
batch clear в raw_barrier был бы ошибкой.

Mode5 END допускается только при hardware_off==1, queue.empty, batch idle,
нет незавершённого TX. Если stop barrier не подтверждён — recovery/неполный
сеанс, никакого нормального END/ACK. Этот дополнительный mode5 guard не
переопределяет исторический flags4 behavior modes1..4. Stop/HELLO500мс и
transaction_bound1мс остаются прежними неподтверждёнными бюджетами, не
растягиваются из-за размера кадра. При истечении — explicit failure.

## 7. Одна actual-core модель после контракта

Один новый harness/runner против actual patched core+queue+serializer+wire,
с явными логическими I/O/TIME seams. Четыре компактные группы:

1. До512 collection/ownership на wrap7→0; queue slots освобождены раньше
   wire prefix; invalid/stale fourth view до любой мутации; full1024/old1..4.
2. Stop во всех4 стадиях COLLECT/CRC/COBS/SEND, tails1/2/3/127/128/129/1023,
   остаток1025→1024+1; queuefault staging+queue drain без bridge и без раннего END.
3. HELLO accepted0 discard и partial>0 oldDATA completion перед новым ACK;
   epoch mismatch в actual runtime prepared-submit helper после destructive
   prepare: zero stale writes, confirmed cleanup, никакой повтор старого cursor.
4. Wholefit384known0, exactpartial, SIZE_MAX, TIME до/после final write,
   false seed/identity: не commit staged prefix. Отдельный край В ТОЙ ЖЕ
   группе: post-write now проходит, локальный pending result готов, но
   последний core now даёт clock failure либо after>=bound. Full bytes уже
   escaped, global prefix/CRC/lastseq не меняются, staging abort, нормального
   END/ACK нет; успешный контрольный путь публикует только после этого now. Реальный C1024+129+END fixture
   для одного host crossdecode; byte/canonical equivalence old modes по pin/model.

Нативная модель не доказывает аппаратный interval или Stop MCU. Exact ARM
image/map/callback stack и independent critic≥9.5 отдельно. GUI/package после
интеграции; физические50/100/150 по одному отдельно допущенному плану,
без автоматического возврата SD/SC. Source implementation до review этого
проекта не начиналась.
