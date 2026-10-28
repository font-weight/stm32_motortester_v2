# S/SL: private ADC block → cached TX opportunity → publication

28.10.2026. Черновой implementation contract, **не принятый fix**. Build identity
SL/`0x5632534c` поступает только из config → общего generated header. База —
exact SK (`build/v6r-fw-02`); frozen R2 proposal
`8c8a9bac2f18de6a89845e0135fdd6d0183f0b3ccb64ebc99be86e778b7cee63`
не изменяется. Здесь нет результатов нового C/ARM/аппаратного запуска.

## 1. Единственное изменение расписания и границы

Только для mode5 STREAMING с cached final DATA1024 и недостатком queue slots:
сначала получить и полностью проверить existing private DMA512 copy, затем
дать **существующую одну** grant/cached-write opportunity, прежний flush и Q
collect-only при actual final commit, после этого предложить четыре DATA128.
Никакого нового FIFO, frame buffer, queue capacity, task dispatch, RX consume,
spin/retry или grant budget. DCD6/<500, Fs150k и deadline3413 не меняются.

Консервативный hint **до copy** выбирает split path. Если hint=false, runtime
вызывает прежний `mt_live_adc_service` без рефакторинга его тела: modes1–4,
50/100k, control, uncached encode и обычные проходы остаются прежними.
Hint не разрешает TX и не заменяет проверки actual BLOCK/ticket после copy.
При EMPTY split acquire возвращается к обычному порядку без pending view.

Static growth=0. Сохраняются common build identity, ABI136/64/24 и их first-close
до cleanup; нового observer/частотного режима/wire/host формата нет. Цель —
проверить одну причинную гипотезу расписания, а не объявить sustainable150k.

## 2. Adapter API и владение

Новые имена и результаты предназначены только для split path; старый service
остаётся compatibility/ordinary path. Все объекты non-aliasing, один foreground
owner, никаких ISR users и reentrant callbacks в adapter/runtime.

```c
typedef enum {
    MT_LIVE_ADC_SPLIT_BAD_ARGUMENT = -2,
    MT_LIVE_ADC_SPLIT_FAILED = -1,
    MT_LIVE_ADC_SPLIT_EMPTY = 0,
    MT_LIVE_ADC_SPLIT_OWNED = 1,
    MT_LIVE_ADC_SPLIT_PUBLISHED = 2,
    MT_LIVE_ADC_SPLIT_STALE = -3,
    MT_LIVE_ADC_SPLIT_DEADLINE = -4
} mt_live_adc_split_result;

typedef enum {
    MT_LIVE_ADC_PENDING_NONE,
    MT_LIVE_ADC_PENDING_OWNED,
    MT_LIVE_ADC_PENDING_PUBLISHED,
    MT_LIVE_ADC_PENDING_ABORTED
} mt_live_adc_pending_phase;

mt_live_adc_split_result mt_live_adc_acquire(
    mt_live_adc *binding, mt_live_adc_pending *pending,
    uint32_t epoch, uint32_t soft_serial, uint32_t actor);
mt_live_adc_split_result mt_live_adc_publish_next(
    mt_live_adc *binding, mt_live_adc_pending *pending);
```

`mt_live_adc_pending` — stack-only receipt, не второй sample buffer и не
дополнение к persistent binding. После acquire он неизменяем, кроме phase и
числа уже успешно предложенных samples. Предлагаемый layout на ARM:

| Поле | Назначение |
|---|---|
| `uint64_t nonce` | identity старой сессии |
| `mt_adc_dma_block_t block` | actual samples pointer/index/count/rate/CEN/period metadata, без копии512 |
| `mt_live_adc *owner` | точный исходный binding, его driver/device/clock неизменяемы в данном lifetime |
| `const mt_acquisition_profile *profile` | точный выбранный immutable descriptor |
| `uint32_t generation, epoch, soft_serial, actor` | исходная core/transport identity |
| `uint32_t poll_origin_us, deadline_us` | исходный driver stamp и выбранный deadline |
| `uint16_t mode` | исходный acquisition mode |
| `uint8_t revision, entry_state, expected_next_half, phase` | исходные revision/state, post-read half, local lifetime |
| `uint16_t published` | 0/128/256/384/512; растёт только после offer1 |

При текущем ARM layout block48B ожидается receipt96B (alignment8). Это расчёт,
не уже измеренный `sizeof`; exact compile/stack report обязан подтвердить размер
и вместимость в reserve8192. Native pointer size может дать другой размер.
Сравнение identity fieldwise, не `memcmp` padding. Не вводить `restrict`.

### acquire

1. Выходной receipt до вызова NONE; BAD_ARGUMENT не читает периферию и не
   создаёт view. Нельзя вызвать acquire/read/start/stop второй раз при OWNED.
2. Прежние `valid`, state, pre-clock, **один** actual
   `mt_adc_dma_read_block`, post-clock и descriptor/count/rational metadata
   проверки применяются в прежнем порядке. Тело driver read_block и его
   MMIO/copy/flag/readback sequence не меняются.
3. EMPTY означает driver не выдал block, receipt NONE, ownership отсутствует.
   FAILED означает прежний fault/cleanup уже запущен, view не выдаётся.
4. OWNED выдаётся только после всех проверок BLOCK512, pointer равен именно
   `binding->driver->snapshot`, queue.next_index равен block.first_index,
   driver.first_sample_index равен block.first_index+512 без overflow.
   Сохранить source/profile/clock/transport identity и post-read next_half.
   `poll_origin_us` — actual `driver.last_poll_us` после read: stamp **начала**
   этого read, не время выдачи receipt. Advance driver index уже произошёл.
5. Acquire ничего не offer/collect/commit/serialize и не вызывает RX/task.
   Прежний adapter validation failure остаётся source reason2, clock — reason3.

### publish_next

Единственный потребитель OWNED receipt. **Один вызов — максимум один128** через
actual `mt_live_device_offer`, в исходном порядке и с original ADC12 input;
quantization/queue validation остаются в core. Runtime выполняет фиксированный
цикл максимум4 вызова с fresh TIME/transport admission до и после каждого.
Никакого callback из adapter в runtime и никакого управления USB из adapter.

До первого и каждого следующего offer проверяются: owner/profile/source view,
same nonce/gen/mode/revision и активное STREAMING состояние, hardware_off0,
driver RUNNING/owned/history-valid/first_fault0, expected next_half,
driver.first_sample_index==block.first_index+512, неизменный last_poll_us,
queue.next_index==block.first_index+published, queue не sealed. Queue head/used
и accepted prefix **не** должны равняться исходным: разрешённые cached commit
и Q prefetch законно изменяют их. Их преобразования проверяются actual core
ticket/certificate; source next_index при prefetch не изменяется.

Внутри publish_next до и после его единственного offer нужна новая validated us
observation (`mt_timebase_snapshot`, отдельные us/ms outputs). Admission:
`(uint32_t)(observed_us - poll_origin_us) < deadline_us`; mode5 deadline=3413.
Этот же origin обязателен для следующего read; **никакого timestamp refresh**.
Новый service guard не заменяет исходные post-copy safe_half/events checks.

Результаты publish_next:

| Return | Что уже сделано и что обязан сделать runtime |
|---|---|
| OWNED | Один128 принят, published=128/256/384, post-offer elapsed проходит; runtime делает fresh post-admission, затем может следующий вызов |
| PUBLISHED | Все512 приняты, final fresh elapsed проходит, phase PUBLISHED; pointer больше не используется |
| FAILED | Actual offer0 либо clock/source validation fault: исходный core fault/cleanup выполнен; phase ABORTED, никаких следующих offers/read в этом pass |
| DEADLINE | Новый fresh delta>=deadline, phase ABORTED **до** cleanup; mapping ниже, никакого последующего offer |
| STALE | Owner/session/source identity не соответствует receipt; не применять source error к чужой новой identity; runtime обязан hard-loss quarantine, затем phase ABORTED |
| BAD_ARGUMENT | Неверные параметры/phase; при возможном pending runtime не продолжает service: explicit fail-closed, а не EMPTY/IDLE |

Любой offer0 может синхронно quiesce и завершить договорённый lifetime view.
Private bytes в exact SK при stop обычно остаются целыми: stop_snapshot копирует
tail в отдельный stop_scratch, а не переписывает driver.snapshot. Запрет
последующей публикации основан на потере session/history/ownership, не на
предполагаемой порче bytes. После offer0 нельзя читать старый snapshot для
следующих offers; разрешено менять local receipt phase/published. Уже принятые
chunks/prefix не откатывать. Повтор publish_next после terminal phase запрещён.

Deadline mapping: использовать существующий
`mt_adc_dma_invalidate_stream_history(driver, MT_ADC_DMA_FAULT_DEADLINE)`,
затем existing `mt_live_device_fault(device, 2u)` при matching старой identity.
Legacy first ADC fault=DEADLINE, wire acquisition reason2, N first-close SOURCE2
до quiesce; это adapter-origin deadline, не поддельный вызов driver fail().
Нового wire/local error enum нет. При snapshot TIME failure аналогично CLOCK
history invalidation и source3; runtime завершает существующим time_fault.
Уже установленная первичная причина не заменяется поздним STOP/clock failure.

## 3. Runtime eligibility и единственная попытка

Pre-copy hint: mode5/STREAMING, hardware owned/running, unsealed queue.used0..8
и free<4; cached READY1024 DATA с offset>0 и remaining1..384, source continuity;
нет want_start/caps/error/end/ack, stop_seen/stop/hello/inherited budget,
tx exhaustion/RESERVE, clock/local/source fault. Также нет carry bytes,
partial core RX/discard state, `tud_cdc_n_available(0)` bytes либо queued task
work. Stable/usable и actor должны быть исходными. Это консервативный hint,
не окончательная проверка bytes или гарантированного final acceptance.

После actual OWNED revalidate hint, receipt и current identity. Получить
actual `prepare_tx` ticket **только cached path**: old staging уже READY,
prepare не собирает/не seal/не CRC/COBS и не pop queue. Затем fieldwise actual
ticket обязан подтверждать mode5 DATA1024, offset>0, remaining<=384, READY
length/count совпадают tx metadata, same nonce/gen/revision/source indices,
без control/error intent. При несовпадении — без попытки fast TX к ordinary
publication; если transport/source identity потеряна — quarantine, см. §5.

Для выбранного fast cached path:

1. После actual cached-ticket eligibility, **до** следующих fallible barriers,
   установить local `handoff_consumed=1` и existing `grant_attempted=1`.
   `handoff_consumed` означает, что TX opportunity этого pass уже потрачена;
   он **не** утверждает, что prepared_tx_step/write фактически вызван.
   `grant_attempted` здесь аналогично запрещает второй opportunity/reset,
   даже если фактический grant не случится. Markers никогда не сбрасываются
   при refusal/error. Затем fresh live_time, synchronize_loss и stable/usable с **saved** epoch/soft/
   actor/nonce/gen. Без нового чтения RX и без task dispatch.
2. Вызвать прежний grant_irq не более одного раза. Ровно та же locked
   admission и6/<500 budget; отказ false всё равно расходует попытку. Fresh
   live_time/loss/stable/identity после IRQ обязательны.
3. При пригодном admission — прежний guarded prepared_tx_step с actual ticket.
   Вся whole-fit/partial/unknown/pre/post/final TIME/deferred prefix commit
   логика остаётся actual core. Не использовать tx_ok как proof завершения.
4. Existing flush под scope и существующие fresh post-flush barriers. Если
   certificate `mt_live_device_prefetch_ready` проходит, прежний Q helper
   collect-only<=512; никакого нового DATA или дополнительного grant.
5. **Не return helper IDLE при OWNED**. После любого helper result проверяется
   пригодность pending receipt и принимается ровно одно решение §5. До его
   разрешения обычный RX/late prepare/TX ниже не исполняется.

Само разрешение pending — фиксированный runtime loop не более4 iterations:
fresh live_time → stable/usable и fieldwise saved epoch/soft/actor/session →
publish_next → fresh live_time и те же transport проверки. Не вызывать следующий
publish_next после любого наблюдённого loss. Adapter проверяет source/elapsed,
runtime — transport; отрицательный result разбирается до чтения следующего
sample. После terminal result loop заканчивается, не poll/retry на OWNED.
Последний post-admission обязателен и для PUBLISHED; при loss после четвёртого
offer уже принятые chunks карантинируются existing hard-loss cleanup до RX/TX.

Это **observed-loss** гарантия, как у existing service. ISR не меняет core
nonce/gen, но способен изменить USB epoch между check и queue store внутри
actual offer. Без большой новой mask невозможно обещать ноль внутренних
old-session stores после любого асинхронного события. Такие accepted queue
chunks не считаются wire/prefix acceptance: ближайший post-check немедленно
карантинирует их; до новой TX/команды/normal END обязательно fresh admission.
Ни один chunk не переносится в новую сессию. Не добавлять PRIMASK вокруг
now/offer/fault/quiesce ради более сильной, несуществующей атомарности.

**Единое правило выхода:** healthy cancellation **до** handoff_consumed означает
immediate original publication, затем неизменённый ordinary grant/RX/prepare/TX.
После handoff_consumed=1 исходный pending block всё равно разрешается по §5;
при PUBLISHED разрешён только прежний RX consume (с fresh admission), после
которого pass заканчивается. Ordinary grant, prepare, TX, flush и Q ниже
пропускаются **даже если prepared_tx_step ни разу не вызывался**. Возврат после
RX — OK при пригодной сессии, либо существующий recovery/TIME исход; команды
Stop/HELLO могут породить ответ только в следующем runtime pass. При ABORTED —
выход cleanup/recovery без RX. Это не второй collect512 или wrapper grant.
Recovery-only matching deferred ERROR остаётся прежним разрешённым
исключением Q, не вторым DATA. Никакой loop до свободного FIFO.

## 4. Scope/actor: вложение без лишнего unlock/re-enter

Copy уже находится в outer app scope runtime. Он сохраняется во время split
path; не вводить leave/re-enter только ради Q. Bridge `app_enter` поддерживает
same-actor nesting через `scope.previous`. `live_write`, existing flush и Q
используют **отдельные** local scopes и оставляют их в LIFO-порядке. Ни один
helper не переиспользует outer scope storage. Реальная USB ISR может пройти
на восстановлении PRIMASK; внешний actor не заменяет fresh epoch admission.

Отказ nested scope — не автоматическая потеря уже acquired512. После отказа
нужно заново наблюдать TIME и transport/source identity. Если они пригодны,
перейти к ordinary offers; не распространять существующий Q return IDLE как
готовый результат всего runtime. Если непригодны — §5. Every exit восстанавливает
все реально entered scopes, даже когда cleanup уже завершил сессию.

## 5. Полная disposition pending и причины отказов

Нормальный выход из split branch разрешён только при terminal receipt phase:
PUBLISHED либо ABORTED после явной disposition. Ни один OWNED не переживает
runtime call; второго ordinary read/start/reinit до такого решения нет.
Синхронный fault→quiesce внутри actual offer0 является самим abort решением;
при возврате phase становится ABORTED и следующий source sample не читается.
`published` фиксирует **queue acceptance**, не accepted wire prefix.

| Событие после acquire | Действие |
|---|---|
| Post-copy hint/ticket не подходит, появились необработанные RX bytes, nested scope отказал, grantfalse, known0 или cached partial; original TIME/identity пригодны | Не обрабатывать RX. Выполнить actual publish исходного блока; при qfull исходный честный queue fault. Уже consumed markers не сбрасывать |
| Actual cached final commit+flush+Q успешно освободил slots | Проверить receipt/elapsed, publish; q8→4→8 — допустимый успешный witness, не обещание |
| Q helper вернул IDLE, но старая identity/clock/driver всё ещё пригодны | Это cancellation оптимизации, не блока: original publish либо честный queue fault |
| Unknown/partial acceptance с actual core recovery, final TIME rejection, Q ERROR recovery | Не продолжать offers после recovery; phase ABORTED, сохранить actual first cause/escaped bytes, не откатывать committed prefix/pop |
| Fresh TIME snapshot/live_time отказал | phase ABORTED до cleanup; existing time_fault, CLOCK/причина3. Не переименовывать lifecycle в clock fault |
| Fresh us delta>=3413 | Adapter DEADLINE по §2; no late offer, источник first fault DEADLINE/reason2, не CLOCK |
| Epoch/soft/actor/session/source state потеряны, hardware-off/sealed/Stop/HELLO уже исполнены | Нет offer из старого receipt ни в старую, ни в новую identity; explicit hard-loss quarantine ниже |
| Raw lifecycle pending, epoch ещё тот же | Тот же explicit quarantine. `stable()==0` плюс `synchronize_loss()==1` **не** означает cleanup! |

Конкретный runtime quarantine для OWNED, непригодного не из-за TIME:

1. Скопировать только нужные scalar identity/phase из local receipt; пометить
   ABORTED **до** вызовов cleanup. Не читать snapshot после этого.
2. Установить existing `r->pending=2` (hard transport quarantine, не новый
   epoch), вызвать существующий `synchronize_loss`. Он закрывает `r->open`,
   очищает carry, вызывает `mt_live_device_transport_lost`, делает physical
   quiesce и очищает TX FIFO по существующей hard-loss ветви. Если cleanup
   обнаружил TIME fault — существующий time_fault имеет своё отличие.
3. Вернуть RECOVERY/TIME_FAULT как actual результат; no normal Stop ACK/clean
   END из этого abandoned interval. Не выдавать deferred source error новой
   nonce. Требуется существующее fresh HELLO/recovery, не продолжение после gap.
4. Если actual core recovery уже произошёл, не выполнять вторую source fault
   транзакцию. Проверить old session off/quarantined; при необходимости только
   existing runtime loss cleanup. Никакой попытки повторно offer pending512.

Это **новое явное место вызова существующей hard-loss процедуры**, а не ложное
утверждение, что нынешний synchronize_loss сам распознает raw RESET до ISR.
`pending=2` не fabricates epoch/soft serial и не разрешает dispatch RESET как
уже обработанного; bridge cleaned receipt по-прежнему требует actual off.
Живой pending raw RESET получает прежний wrapper lifecycle opportunity, если
grant ещё не attempted. Runtime allow_ctr — только запрос, DCD raw filter
остаётся прежним и решает фактическую допустимость CTR.

Для source/transport STALE не добавлять отдельный ADMISSION source fault:
выбран ровно существующий hard-loss quarantine. Даже при matching core
nonce/gen это не выдуманный CLOCK или wire source2. При уже изменённой
identity тем более не выдавать новому core source2 от старого receipt:
quarantine/новый HELLO только. CLOCK и DEADLINE сохраняют отдельные mapping §2.

Не вызывать `mt_live_device_receive`, `tud_cdc_n_read`, новый task либо никакой
command callback между acquire и disposition. Просто пришедшие Stop/HELLO
bytes могут ждать, как при прежнем ADC-before-RX; они не означают выполненную
команду. Если же команда уже выполнена вследствие нарушения границы/инъекции,
нельзя дописать old512 или подтвердить успешный Stop, пропустив этот диапазон.
В актуальном single-owner пути такой interleaving должен быть недостижим.

## 6. Сроки и функциональные инварианты

`read_block` без изменений уже advance source index и flip half до возврата.
Receipt — единственное доказательство обязательства разрешить этот диапазон;
это не дополнительная очередь. `driver.last_poll_us`/`last_progress_us` не
переписывать в runtime/publish. Следующий driver poll обязан увидеть весь
copy+IRQ+write+flush+prefetch+offers+RX interval от исходного poll origin.

Новые pre-offer/post-offer checks выявляют уже истёкший срок, но не доказывают
WCET следующего offer/IRQ либо последующего RX. Grant500 — predicate продолжения,
не длительность всего handler. Maxpoll2907 и copy166 — один старый observed
результат, не квалификация нового расписания. Все дополнительные snapshot
costs, stack и задержка старого IN здесь **не измерены**. При delta3413 ровно
отказ; modulo32 wrap вычисляется unsigned, многократный wrap не поддержан,
как в существующем TIME/driver contract. Никакого расширения deadline.

Old cached ticket должен оставаться intact до actual post-final certificate;
Q может заменить его только после проверки readiness. Не reuse receipt как
ticket либо scope scratch. Никакой staging encode/CRC/COBS или тяжёлый collect
под write PRIMASK. Q collect<=512 вне guard; если он состоялся, normal prepare
в этом pass пропускается, чтобы не получить второй512 collect. Partial/final
known acceptance, unknown acceptance, CRC domain и deferred final commit
сохраняют existing core поведение; source/queue индексы не перенумеровываются.

Новые driver register reads/повторный read_block, второй task, расширение
FIFO/queue/IRQ window, partial whole-fit publication и новый observer вне scope.
Нулевой дополнительный static bank обязателен: SK свободно только4B сверх
reserve8192. Stack-only receipt/local markers могут увеличить call depth;
ARM linked stack bound с существующим ISR reserve должен оставаться<=8192.

## 7. Изменяемые места и один необходимый программный результат

После отдельного допуска реализации:

- Новый strict layer после R, generated SL identity из единственного config.
- `mt_live_adc.h/.c`: новые stack receipt/acquire/publish и source/time helpers;
  original `mt_live_adc_service` body сохраняется exact. Driver read/start/stop,
  DCD/bridge/IRQ/TIME/queue/serializer/wire bodies не меняются.
- `mt_live_runtime.c`: pre-copy hint, split-owned branch, однократные markers и
  explicit pending quarantine. Original modes1–4/noneligible branch и guard/
  flush/Q implementations сохраняются; extraction/source comparison фиксирует
  изменённые callsites, не выдаёт токен-равенство за физический timing proof.
- Сохраняются active64/G24/136, лишь common build SL; first-close BEFORE cleanup.

Один integrated runner actual new adapter/runtime boundary + actual
core/queue/serializer/wire и active common-SL observer. Driver/MMIO/USB/native
seams раскрываются, не заменяются ручным if очереди вместо actual publication.
Компактные группы внутри **одного** executable:

1. Actual acquire/publish source receipt и positive cached final/certificate/
   Q: q8→4→8, next_index неизменен при prefetch, four contiguous offers и CRC/
   prefix независимы; не второй read/collect/TX/grant. Матрица EMPTY/noneligible
   подтверждает прежний ordinary path, не требует старого полного suite.
2. Grant свободил FIFO vs не свободил: full final либо единственный known0/
   partial и прежний queue-full; no spin. Final TIME/unknown/Q ERROR не дают
   новых offers или rollback уже accepted bytes/prefix.
3. Scope refusal при пригодном старом owner → original publish; raw lifecycle
   без смены epoch, actual epoch/soft, session/Stop/HELLO/time loss → quarantine
   до выхода. No RX/core command между acquire/publish. Проверить delta3412/
   3413/wrap, отказ до первого и после частичных offers, повторный consume
   receipt запрещён. Причины CLOCK/DEADLINE/TRANSPORT различаются.

Фактический single test pass и ARM build только после accepted contract.
Exact C fixture/observer binding можно сохранить внутри этого же запуска,
не создавать отдельный profiler suite. Одна успешная ARM/resource/stack
проверка, failed attempts сохраняются. Старые GUI/host/широкие firmware suites
не повторяются, wire bytes не переопределены.

Программная приёмка требует независимого exact-source review>=9,5 и всех
свидетельств. Только отдельный root hardware plan затем может проверить один
непрерывный150k интервал. Полезный отрицательный исход — прежний qfull без
искажения prefix либо честный новый deadline fault; это не успех sustainable
150k. Этот черновик и R2 observation не гарантируют, что INSERT path успеет
или увеличит средний drain rate.


## 8. Явная идентификация в offline-инструментах ПК

Прежние форматы 136/64/24, wire и Windows GUI не меняются. Offline-декодеры
принимают SL только по явно переданному ожидаемому build, с теми же проверками
image/nonce/gen и всеми ограничениями R. Поддержка старой SK сохраняется;
SL не становится молчаливым legacy default. Unsupported future build SM и
несовпадения SK/SL отклоняются. Старые negative fixtures, где SL ещё считался
неподдержанным, переводятся на SM без ослабления остальных проверок.
Одна узкая проверка identity использует actual-C SL fixture из общего native
запуска S и сохранённый actual-C SK fixture; повтор полного decoder/GUI suite
не нужен. Root сохраняет exact hashes и независимое заключение.
