# S/SL: read-only implementation map

28.10.2026. Только план будущих изменений; production/тесты не редактировались,
сборки/запуски/аппаратура не выполнялись. Основа — canonical
`docs/streaming-postcopy-handoff.md`: author contract + root §8. Реализация
допустима только после отдельного contract gate и root scope.

## Минимальный strict overlay

Новый слой `firmware/v2-stream/overlays/postcopy-handoff.json`, применяемый
`build_windows.py` **после** usb-gate. Ровно три patched targets:

| Target | Изменение | Что сравнивается exact с SK |
|---|---|---|
| `v2/app/mt_live_adc.h` | split enums, stack-only receipt, acquire/publish_next declarations | persistent mt_live_adc layout и все старые declarations |
| `v2/app/mt_live_adc.c` | новые acquire/publish_next/source/elapsed helpers | каждое старое тело, включая mt_live_adc_service/start/quiesce, без factoring |
| `v2/app/mt_live_runtime.c` | pre-copy eligibility, pending handoff/publish/quarantine helpers, callsite/consumed-marker/RX-only finish | старые guard/write/grant/Q helpers целиком; original noneligible route после точного удаления вставок |

Имена patch-файлов: `v2-postcopy-app-mt_live_adc.h.patch`,
`v2-postcopy-app-mt_live_adc.c.patch`,
`v2-postcopy-app-mt_live_runtime.c.patch`. Строгие source/patch/result SHA и
exact-hunk/count правила прежнего builder обязательны; никакого normalization
input bytes ради обхода drift. Новый слой не переписывает старые overlays.

Исходные targets берутся из `build/v6r-fw-02/patched`:

- adapter C `49e7048249d6fa4053e7504ce4657f7819878dc2c61c027cbdc3c596e812b6cf`;
- runtime C `91f3ffc157f853eb9bb7fdc0ced747b177e6906d1b13e611d3dc4c14a7407294`.

Config меняет только общий build `0x5632534c` и product на SL. Builder добавляет
загрузку нового слоя, не новый object/component. README получает актуальное
назначение/команду S без фактически выполненных результатов. Generated
`mt_firmware_build.h`, board/N64 dependencies и ARM word проверяются как P/R.

Никаких изменений driver/DCD/bridge/IRQ/TIME/core/queue/wire/serializer,
136/64/24 C/H, linker layout/stack reserve, FIFO/гранулярности/USB descriptor.
Static рост=0 проверяется whole-link, а не только sizeof нового receipt.

## Helper boundaries, которые не расширяют state machine

Рабочие имена runtime helper при реализации (final source pin обязателен):

- `postcopy_hint`: pure conservative selector before read; mode5 cached final,
  queue free<4, no controls/RX/task. Не валидатор всей ownership metadata.
- `postcopy_identity`: read-only comparison receipt↔current runtime/source
  identity после fresh TIME; никаких cleanup/epoch update из этого helper.
- `postcopy_abort`: помечает local receipt ABORTED, затем existing pending2
  hard-loss cleanup либо existing time_fault. Raw lifecycle без нового epoch
  обязан попасть сюда; no source ADMISSION error.
- `postcopy_publish`: fixed<=4 loop actual publish_next, fresh pre/post runtime
  TIME/stable/epoch/soft/actor; no RX/TX внутри цикла, partial failure terminal.
- `postcopy_handoff`: acquire → actual cached ticket → one consumed opportunity
  → old guarded TX/flush/Q → publish/abort. Отдельный helper позволяет не держать
  дополнительный receipt и большой ticket на самом глубоком обычном TX пути.

`handoff_consumed` ставится до новых fallible barriers и запрещает ordinary
prepare/TX даже при нуле фактических writes/grants. Existing wrapper marker
запрещает второй grant. Healthy cancellation до selection — old offers+old path;
после selection с PUBLISHED — fresh RX-only и конец pass. Если early selected
path не дал actual grant из-за raw lifecycle, следующий pass сохраняет ordinary
fallback; не нужен новый IRQ loop.

Copy и handoff остаются под outer app scope. Nested write/flush/Q scope имеют
разные locals, LIFO restore; новое leave/reenter не требуется. Existing N64
prepare span окружает moved cached prepare, legacy TX stamp — moved guarded
submit; Q span остаётся actual old helper. Это сохранение прежних spans, не
новые periodic metrics/изменение ABI. Их duration по новому расписанию не
считается измерением CPU-only или доказательством throughput.

## Одна integrated native модель

Новые уникальные paths: `tests/v2-stream-firmware/postcopy_handoff_model.c` и
`check_postcopy_handoff.py`. Не перезаписывать legacy usb_gate_model/checker
или модели прошлых узлов. Один новый output `build/v6s-native-01`, один запуск
одного executable. Baseline `build/v6r-fw-02`, image будущий `build/v6s-fw-01`.

Reuse как **scaffold**, без запуска прежних suites:

1. `check_prefetch.py`/`prefetch_model.c`: actual core/queue/serializer/wire,
   before_final fixture, prepared_tx_step, Q certificate/collect и active64
   с generated identity. Нельзя заменить их ручным decrement queue.used.
2. `check_deferred_grant.py`/`deferred_grant_model.c`: extraction actual runtime
   helper bodies и actual step/wrapper, logical CDC task/FIFO/IRQ/actor seams,
   consumed markers/raw-lifecycle next-pass fallback. Старые SG-disabled
   observer flags **не** копировать: в S active N64+G24 обязательны.
3. Из rate/CEN scaffolds допустимо взять только logical register bus и
   initialized mode5 driver fixture. В native подключить actual adc_timer_dma.c
   и adapter, чтобы acquire реально вызвал read_block/copy/advance ровно один
   раз. Не запускать прежний CEN/start regression main. Driver startup и
   аппаратные задержки не цель этой модели; initial driver state/MMIO/clock
   stimuli пометить synthetic. Вызванные driver read/stop тела actual.
4. Из R runner — actual gate/progress sources и запись24/64/136 fixture,
   common generated-header/ELF dependency/bind проверки. Не повторять R
   extracted-DCD read-order suite: DCD object/source exact SK.

Runtime extraction должна включить actual new helpers, live_write,
prepared_tx_step, grant_irq, старый Q helper и actual modified step/wrapper.
Clock/USB ingress/PMA/host readiness и bridge lock/scope — явные logical seams;
source comparison отдельно подтверждает отсутствие task/RX/второго read внутри
pending lifetime. Если часть clock/driver bus требуется stub, это перечисляется
в receipt, а не выдаётся за полную аппаратную модель.

В одном model три группы canonical contract: actual q8→4→8 final/certificate/
Q/contiguous source data; known0/no-IN/partial/unknown/finalTIME/Q ERROR и
single opportunity; cancellation/epoch/soft/raw lifecycle/scope/между-chunk
loss/3412–3413/wrap/partial offers/no next TX или normal END. Новая identity
может появиться только synthetic fault injection: production не dispatch RX
при pending. Не расширять до repeat всех historic mode/timer/serializer tests.

## Fixture и проверка ресурсов

В этом же C запуске сохранить `actual-gate.bin`24,
`actual-progress.bin`64, `actual-legacy.bin`136 + `companion.json`, с exact SL
generated build, generation7/nonce0123456789abcdef. N64 должен реально быть
ACTIVE до close, не zero bank. G24 заполняется actual mt_gate API; legacy136
identity setup synthetic, явно так обозначается. Known close tuple можно
сохранить R-compatible: HOLD_TIME serial1/total384/queued64/age501/left5,
N begin1000/end5000. Это offline ABI witness, не физическая аутентификация
образа и не второй DCD test. Final fields/SHAs сообщить root до его узкой
decoder проверки; никаких отдельных native повторов для host.

Runner source proof: adapter old functions exact; runtime old helpers exact и
whole original step/wrapper после удаления только explicit new blocks; все
прочие patched/source/compiler inputs exact SK. Unchanged objects ожидаются
для driver/DCD/core/queue/wire/TIME/serializer/bridge; board+N bind отличаются
только common build/product. Gate C object должен быть прежним. Identity
literal machine-code normalization только там, где она уже доказана P.

Один ARM `build/v6s-fw-01` после стабильного кода (repair только при реальном
отказе, old output сохранить). Whole data+bss <=12288 при reserve8192 и RAM20k;
в SK128+12156=12284, остаётся4B, никакой hidden private growth не разрешён.
Размер stack receipt96B ожидаем, но actual sizeof/alignment и linked maximum
stack/ISR reserve<=8192 подтверждаются exact ELF/static analyzer. Не считать
сумму stack local sizes полным call-chain proof. Реальное время новых TIME
snapshots/IRQ/prefetch и устойчивый150k не подтверждаются native/ARM.

Freeze будущего source должен включить contract и все changed sources,
strict overlay pins, native/sourceeq, BIN/ELF/maps/stack, адреса24/64/136,
fixture/decoder receipt root, failed attempts. Никакого hardware gate по этому
плану нет; аппаратура остаётся исключительно у root после отдельного допуска.
