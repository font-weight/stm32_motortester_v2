# S/SL — авторский аудит ограниченной реализации

28.10.2026. Авторская запись software candidate; независимый балл
автор не выставляет. Этот документ не является разрешением аппаратного опыта.

## Изменение и сохранённые границы

Canonical contract `docs/streaming-postcopy-handoff.md` SHA
`521e91d88b8234be6f8db7cbecfd79b6f4bd4c47dbb38dd871242a0d97b1b149`.
Новый strict слой после usb-gate меняет только adapter H/C и runtime C.
Старые adapter/service/start/quiesce тела не факторизованы; driver/DCD/core/
TIME/queue/serializer/bridge/wire и136/64/24 ABI не редактировались.

Mode5 cached-final/low-room hint выбирает actual acquire private512, затем
existing grant/cached TX/flush/Q и fixed publish_next128 loop. Source ownership
и исходный poll stamp сохранены. Healthy refusal не забывает private block;
raw lifecycle даже до epoch advancement вызывает existing pending2 hard-loss
cleanup. Никакого RX/task/нового read до disposition. Observed-loss admission
не является обещанием атомарного отсутствия queue stores после IRQ; postcheck
quarantine запрещает их последующую wire/новую-session публикацию.

handoff_consumed и wrapper grant marker расходуются до fallible barriers;
поэтому ноль actual writes/grants не позволяет второй ordinary TX opportunity.
Existing N prepare и legacy TX spans стоят на перенесённых callsites; Q span
остаётся в старом helper. Новых metrics нет. Суммы и длительности inclusive,
не CPU share/WCET. Source timings и actual устойчивость150k остаются открыты.

## ARM и ресурсы

`build/v6s-fw-01` — сохранённый preflight failure, compiler не запускался:
config SL уже обновлён, expected-build pin board_inputs.py ещё был SK.
Сохранены attempt.json/полный stderr. Исправлен только validator pin SK→SL.

`build/v6s-fw-02` — `BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE`:

- BIN49 532B SHA `f82311cde2ce0a3e735543006b2bc7890e8761434c73e7adc7fa332f86cb8cb2`.
- ELF SHA `3034a77fa007f872f32ff145b58f39f21e2e3d62d79919eb7505d05d3c1313db`.
- text49 404/data128/bss12 156; whole static12 284B, рост0 относительно SK.
  С reserve8192 использовано20 476/20 480B, свободно4B. Нет нового hidden bank.
- Conditional exact-image stack upper6348B/aligned6352B при reserve8192.
  Это linked static bound с прежними предпосылками ISR/exception, не физический
  stack watermark. Step392B, wrapper96B по `.su` не заменяют whole-chain audit.
- Receipt исходно оценивался96B при ошибочной промежуточной оценке block48B.
  Actual ARM block40B, receipt88B; compiled memset/copy88 видны в
  `disassembly-21-mt_live_runtime.stdout` и `disassembly-22-mt_live_adc.stdout`.
  Header ограничивает receipt<=96 на32-bit; static памяти он не занимает.
-136 `mt_stream_diagnostics`=0x20002f1c,64 `mt_stream_progress`=0x20002fa4,
  24 `mt_usb_gate`=0x20002fe4, адреса и размеры прежние.

Фактические new snapshot/IRQ/USB costs не измерены. Deadline3413, grant6/<500
и old configured1ms transaction bound не расширены;500 не WCET. Предыдущий
maxpoll2907 не квалифицирует этот schedule. Static build не закрывает150k.

## Native и source preservation

Один integrated actual-C executable: new adapter, actual driver read/
stop, core/queue/serializer/wire/N64/G24 и extracted modified runtime. Native
MMIO/TIME/USB/actor stimuli synthetic; legacy136 module не исполняется, его
common-SL pairing и diagnostic functions явно synthetic C setup/seams.
Fixture24/64/136 и companion сохранены этим же запуском для host checker.

`build/v6s-native-01/result.json` PASS с первого и единственного исполнения,
SHA `08bc8e0460fa4c5c5ed58fa767313bd25c2853374406de7db35bbc0c330af919`,
input_drift=[]; source-equivalence SHA
`8d8023083bbf47f32f8f43ba0481fdec5fce12f1cc82adf4ad629b991651be01`.
Модель source SHA
`15180d4ae4bcd3a5c6122add5bca2d1af4c7333b5c069970eacc0b6622b296b3`.

Проверено actual q8→4→8/cached commit/flush/Q/contiguous publish, packed DATA
и независимый canonical CRC; EMPTY/обычный mode1, zero/partial/oversized unknown,
late final clock, Q scope refusal/ERROR; loss после1..4 offers, strict3412/3413/
wrap, no receipt replay, Stop/HELLO/quarantine, raw lifecycle после consumed
до actual grant и следующий pass fallback. Oversized UINT32 acceptance в
native64 — unknown/invalid acceptance, не буквально SIZE_MAX от TinyUSB API.

Source proof отдельно сохраняет old adapter/service bodies, old runtime helpers
и original step после точного удаления new blocks; остальные SK sources и
compiled objects (driver/DCD/core/queue/TIME/serializer/bridge/gate и др.)
совпали. N bind machine-code отличается только generated SK→SL ID. Logical
native seams и source equality совместно проверяют порядок; ни один из них
не выдаётся за USB/DMA wall-time/WCET или physical150k.

Fixture gen3/nonce503, common SL:24 SHA `2aa983d6c2c8ea8951b39a27274486f9cf62c7edc2b139854978ab04e64898b3`,
64 `37d17b307bd058f31e0c1aff577b316dd3bc4d6830e32e3f4d3a0cf3535f48f8`,
136 `0713c47cf0e29c538fa6c3c0fe44735c6fd3e6d96fd6e46d440f396da42241f1`.
Пара136 setup/diag functions synthetic, это не физическая аутентификация.
Host выполняет только согласованную offline identity проверку, её receipt
будет отдельно pinned в freeze. Старые GUI/host/DCD/ADC suites не повторялись.
Hardware не использовалось; SK на плате не менялась автором. Independent
source verdict и аппаратная приёмка остаются отдельными gate.
