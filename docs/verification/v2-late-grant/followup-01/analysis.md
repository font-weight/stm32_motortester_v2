# O2/SH: доказанная причина zero64 и предел разбора очереди

27.10.2026. Только offline-разбор сохранённых файлов. Production, тесты,
сборки, COM/SWD/Reset/Flash/START не менялись и не запускались. SG/SH evidence
не переписывается. Исходная цель устойчивых150k остаётся открытой.

## Что подтверждено O2

Входы: `build/v6o-board-01/150000/{physical-analysis,diagnostics-decoded,
progress-decoded,registers-decoded}.json`, raw64/136, invocation/log первого
64B-чтения и exact source/ARM `build/v6o-fw-01`.

- Единственный запрос150k/mode5/30с завершился source reason1/queue-full.
  Сохранены20полныхDATA1024, contiguous prefix20480, CRC1933017381; END
  до host STOP, matching ACK и offline wire/raw/Open validation PASS.
  Это неполный префикс с неизвестным произведённым хвостом, а не успешные30с.
- Legacy136 валидна: SH`0x56325348`, nonce`6fd5a5c6c60ddaad`, generation3,
  first acquisition reason1, ADCfault0, queue8/8, step172, poll148, copy41.
  Максимумы poll2952мкс, copy184мкс, step230706cycles, tx14616cycles.
  Поля legacy могут включать cleanup/drain; не подменяют first-close snapshot.
- Две64B копии по ожидаемому ELF-адресу`0x20002FA4` полностью нулевые,
  SHA256`f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b`.
  Лог чтения подтверждает адрес/размер64 и успешное сохранение. Decoder верно
  выдаёт INVALID, в том числе wrong magic/nonce/generation/not-frozen, и
  `nominal_timing=null`. Это **не валидная запись с нулём событий**.
- `registers-decoded.json`: TIM3 CEN0/PSC47/ARR9, ADC_CR2=0, DMA EN0,
  sample setting4, clocks/reset checks PASS. Root сообщил закрытие владельца
  и END/ACK до чтения. Этот разбор не выполняет аппаратную процедуру.

## Zero64: причина установлена по исходнику И скомпилированному образу

`firmware/v2-stream/progress/mt_stream_progress.h:14` и exact compiler input
`build/v6o-fw-01/patched/v2/platform/mt_stream_progress.h:14` сохранили:

```c
#define MT_N_BUILD UINT32_C(0x56325347) /* SG, не SH */
```

В `mt_stream_progress.c:39–44` функция `paired(d)` требует
`legacy.firmware_build == MT_N_BUILD` вместе с session identity.
`bind()` (`:46–53`) возвращает0 ДО первого присваивания64B, если это условие
не выполнено. `mt_progress_begin()` (`:55–58`) сразу возвращается при отказе.
В SH legacy поле равно`0x56325348`, поэтому `0x56325348 !=0x56325347`:
после boot BSS остаётся EMPTY/zero. Prepare/write/checkpoint работают только
для ACTIVE. Close при EMPTY также не создаёт историю завершившегося START.

Это не предположение о stale адресе или повреждении SRAM:

- Final ELF `image.nm`: legacy136`0x20002F1C`, progress64`0x20002FA4`,
  ровно эти адреса использованы root. Data128+bss12132+stack reserve8192
  укладываются в20480, запас28; conditional stack6156/aligned6160.
  Zero64 сама по себе не доказывает stack corruption; явное rejected bind
  объясняет наблюдение без такой гипотезы.
- `image.dis`, `bind@0x0800A234`: в`0x0800A262` читается legacy build
  по offset12, `0x0800A264` compare, `0x0800A266` mismatch-branch уходит
  к возврату без stores. Literal по`0x0800A2D0` равен`0x56325347`.
- Hooks не выключены в target: ARM recipe задаёт CFG_MT_PROGRESS_TRACE=1;
  actual core`:266` и final linked code вызывают `mt_progress_begin`.
  Скомпилированный объект progress присутствует. Ошибка именно в identity
  admission, а не в отсутствии кода/флага или неправильном decoder build.

Автор перенёс observer C/header как «неизменные» и не обновил отдельную
build-привязку. Это P1 пропуск совместимости диагностики. O native исполнял
actual runtime с CFG_MT_PROGRESS_TRACE=0; он проверил расписание, но не
совместную работу SH legacy+actual observer. Root decoder-check использовал
сохранённый C fixture N с синтетическими expected build/image bindings;
это проверка decoder, не исполнение target `paired()`. Source-equality и
успешный ARM layout не проверили этот missing cross-build invariant.
Прежний O1 PASS не стирается и не выдаётся за подтверждение этой совместимости;
O2 диагностический результат по64B — INVALID.

## Что известно и неизвестно о queue-full

Poll2952<3413мкс означает лишь, что наблюдавшийся интервал обслуживания DMA
не превысил software deadline. ADCfault0 не означает доказанную безошибочность
всего ADC. Для устойчивого потока отдельно нужен достаточный темп освобождения
очереди и FIFO: half512/150k≈3,413мс, очередь1024/150k≈6,827мс.
Cached TX не собирает следующий batch, а1335B frame требует минимум4 write≤384.
Final completion всё ещё требует task, а IRQ continuation ограничен6/<500;
перенос одного grant не устраняет все эти зависимости.

Без валидных64B неизвестны first-fault TX offset/length, staging, FIFO free,
zero-space, positive acceptance, prepare intervals и причина held. По legacy
нельзя выбрать между устойчивым дефицитом, transient USB backpressure,
остаточным completion turnover и иными задержками. Конкретная первичная
причина queue-full этой попыткой не установлена.

20DATA SH против3DATA SG не доказывают эффект O: в SH active observer фактически
не запустился, его hot paths были дешевле; изменились условия опыта. Host-slope
≈138894samples/s относится к короткому принятому префиксу с буферизацией и
drain, не устойчивой частоте/темпу АЦП или измеренному пределу USB. Нельзя
экстраполировать его в30с и объявлять целевой150k полученным.

## Следующий один bounded repair P: единая build-привязка observer

До следующей scheduling-оптимизации сначала исправить именно измеритель,
сохранив functional SH,64B layout/136B, RAM, Fs, wire, queue/ADC/TIME/DCD и O grant.
Не заменять один ручной literal следующим ручным literal в observer.

Предлагаемый минимальный путь от **единственного принятого config build id**:

1. Builder из проверенного `config.json.firmware_build` генерирует общий
   `generated/mt_firmware_build.h` с одним `MT_FIRMWARE_BUILD` constant. Этот
   файл входит в receipt dependency/hash manifest. Allowlist кандидата может
   оставаться review-gate, но не второй независимо компилируемой константой.
2. Генерируемый board.c использует этот constant для `mt_board.firmware_build`;
   progress pairing включает тот же header и использует тот же constant.
   Старый самостоятельный `MT_N_BUILD=SG` удалить. Missing shared header/macro
   при включённом observer — compile error, без SG/default fallback.
   Для выключенного observer logical runtime harness не обязан получать
   отдельную build-привязку.
3. Новому кандидату назначается отдельный build по решению root. Не менять
   сохранённые SG/SH BIN/header/receipts и не переобозначать их задним числом.
   На этапе exact ARM проверить board word==config и bind constant==тот же id,
   а также compiler dependency на общий generated header у обоих consumers.

Это не новый telemetry bank: целевой дополнительный static RAM0, ABI64 тот же;
фактические RAM/stack/flash определяются одной новой ARM/resource сборкой.
Не тратить28B остатка на дополнительные счётчики.

Достаточна одна адресная actual-C binding проверка с **generated header точного
кандидата**: matching candidate legacy/gen/nonce → ACTIVE → first-close FROZEN
fixture64; прежний SG build и чужой build при тех же gen/nonce → отказ bind,
банк остаётся EMPTY; mismatched nonce/gen тоже не принимаются. Проверка должна
исполнять actual `paired/bind/begin/close`, а не подставлять готовый bank или
отключать observer. Существующий decoder может один раз прочитать этот actual
C fixture с новым явным expected build; это синтетический C↔decoder witness,
не аппаратная идентичность или throughput.

Полный старый runtime/serializer/GUI suite не нужен: functional SH остаётся
source-identical, адресно меняется только build admission observer и генерация
единого id. После независимого review/root-плана — отдельное решение об одном
аппаратном опыте для получения валидного first-fault snapshot. Этот документ
не разрешает повтор START, Reset, Flash или rollback и не объявляет repair
исправлением queue-full/устойчивости150k.
