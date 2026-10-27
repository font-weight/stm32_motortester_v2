# R1/SK — авторский audit и пределы

27.10.2026. Exact accepted R3 contract — `docs/streaming-usb-gate.md`, SHA256
`c543d4adaaa2cdf9b609722ca5cb514c520ab6f71d9e539ef8f88329f8c49995`.
Это диагностический программный кандидат, не queue-full fix/150k acceptance.
Автор не открывал COM/SWD, не делал Reset/Flash/START. Q/SJ archive не изменён.

Добавлен ровно один volatile24B `mt_usb_gate`; вся persistent/private state
находится в нём. Exact static growth24, data128+bss12156+reserve8192=20476 из
20480, остаток4байта. Никаких вторых frozen/scratch banks/counters нет.
Legacy136@0x20002F1C и N64@0x20002FA4 прежние; G24@0x20002FE4. Init выполняется
перед N ACTIVE; freeze — в прежнем snapshot lock вне успешного app scope.
ISR не пишет64 flags; N CLOSING блокирует любые новые gate stores. SK board/N/
gate используют единый config-generated header, actual-C positive и priorSJ
negative binding исполнены. N64/136 layouts и functional SJ не изменены.

DCD hook invalidates association до overwrite xfer fields, success publisher
увеличивает serial под прежним guard. Grant/другой ISR делают причину только
historical; lifecycle/cancel/metadata/saturation явные. First evaluated false
исходного short-circuit выражения сохраняется без повторных MMIO. Time helper
выдаёт только уже прочитанный CNT age; skipped TIME unknown, age65535 допустим
при valid-bit. Pure FINAL отличён от mixedRX/SETUP, stable pointer/tuple и ZLP
проверены. Extra diagnostic metadata reads — RAM, working endpoint/MMIO
selection остаётся после прежнего RX handler. R не расширяет6/<500 или3413.

`build/v6r-fw-01` сохранён FAILED compile13: новый continuation helper был
расположен до определения existing `mt_usb_fsdev_lifecycle_pending`, поэтому
требовалось предварительное объявление. Добавлен только prototype; никакого
изменения алгоритма/условий. `build/v6r-fw-02` — единственный исправленный ARM,
PASS static; BIN46820bytes dd6e8322…fc8f1, ELFfa7307ac…30593f. Text46692.
Conditional exact-image stack6196/aligned6200 при reserve8192; gate init40,
freeze48, publisher/note24 stack bytes, не physical high-water/WCET.

`build/v6r-native-01` — один executable/один запуск, PASS трёх адресных групп.
Исполняются actual N64/G24 C, извлечённые DCD publisher/grant/timer/continue
functions и исходные PRE/POST metadata blocks. PMA submit, register storage,
legacy136 pairing и DWT synthetic. Проверены initial unknown, new/failed submit,
ZLP buffer/FIFO routes, pureFINAL/mixedRX/backing mutation, saturation/sticky
invalidity, skipped predicates и499/500/modulo boundary, refused app scope,
N CLOSING late ISR/FG no-write, CAP/noactive и post-CLOSING24/64 skew. Actual
fixtures24/64/136 имеют exact shared SK identity; legacy module не исполнялся.

Native read_usb() журналирует общий USB base, не различает адреса ISTR/CNTR/
DADDR сам по себе. Exact выбор полей/порядок дополнительно доказан source
normalization всего DCD и отдельно очищенного continuation expression.
Нормализация удаляет только перечисленные hooks/metadata blocks и восстанавливает
старый exposed timer call; все остальные SJ DCD tokens прежние. N64 body tokens
прежние после удаления include/init/freeze. Другие SJ patched sources/compiled
objects (runtime/ADC/TIME/core/queue/wire/serializer) идентичны. Complete DCD
ISR PRIMASK и FG bridge guards сохранены; unguarded deinit/disconnect недостижимы
из exact roots в сохранённом call graph. Это source/resource proof, не полная
динамическая USB/DMA/runtime модель.

При подготовке обнаружено совпадение имени со старым `usb_gate_model.c`.
Новый код до любых native запусков сохранён как `usb_gate_trace_model.c`;
старый файл восстановлен byte-exact из HEAD. `check_usb_gate.py` не менялся:
используется только прежний function extractor. Старый suite не запускался.

GateAPPLICABLE относится к последнему episode до N CLOSING. Даже совпавший
поздний HELD64=1 не доказывает тот же episode. CAP и NO_ACTIVE ограничивают
окно. DWT/volatile stores/annotation calls имеют observer effect; фактическое
время DCD/ADC может измениться.500us — проверка continuation, не WCET всей IRQ.
Источник package/Flash/один новый физический план требуют отдельного root/
независимого допуска. Доказательство instrumentation не принимает stable150k.
