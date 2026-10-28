# R2/SK: publication до queue-full — одна функциональная гипотеза

28.10.2026. Только offline чтение сохранённого R2 и exact SK. Автор не менял
firmware/тесты, не собирал и не запускал проверки, COM/SWD/Reset/Flash не использовал.
Предложение ниже не является уже принятым fix или новым аппаратным планом.

## Факты и пределы нового снимка

Вход `build/v6r-board-01/150000/`: `run/result.json`, `physical-analysis.json`,
`diagnostics-decoded.json`, `progress-decoded.json`, `gate-decoded.json`.
SK/0x5632534B image SHA256
`dd6e8322488a1d4ada50c2c722820f971b4b4782c303bdafb1410180e2efc8f1`,
ELF `fa7307ac6a6c30a58e8fd54223bfa7692b8cf65417288d99e51a45b85030593f`;
source `bc851d6ee7b16663db95acb32733cacff7a50f36`.
Пары136/64/24 пригодны, nonce `7266eaaa454327da`, generation3.
G24 SHA256 `1857ff62ab1e8fb96b5fe27ca6f24584c6f75a3851fc5b19a2fc2d1eddc22fb6`.

Единственный150k START закончился source queue-full:21 DATA/21504кода,
ENDreason1 до host Stop. Final wire включает последующий drain; его нельзя
считать объёмом, переданным до first-close. Offline raw/индексы/CRC/Open
проверены root отдельно; это не приёмка устойчивого150k.

Первый close64: q8, READY1024, tx1152/1335; FIFO free64, held/deferred=true,
task_ready=false. Positive26517bytes — known DATA acceptance в FIFO, не USB
delivery; zero-space45, other0. Elapsed10580665cycles≈146,954мс номинально72MHz.
Prepare4203334cycles/158 — inclusive span, не CPU share. LegacyADCfault0,
maxpoll2907мкс, copy166мкс; step229954cycles≈3,194мс. Maxpoll ниже3413 означает
лишь отсутствие пойманного driver deadline, не достаточную разгрузку очереди.

G24: flags15, serial82, **PUBLISHED**, total384/queued64, age/budget unknown,
TRANSFER_ACTIVE1/APPLICABLE0. Event→Nclose18497cycles≈256,903мкс. Это новая
наблюдённая публикация, не HOLD_TIME, не HOLD_FINAL и не исчерпанный бюджет.
После неё до N CLOSING нет сохранённого применимого CDC-IN decision. Queued64
означает первый PMA load, а не64байта, доставленные ПК. FIFO64 совместим с
320байтами, ещё находящимися в FIFO. Из24 нельзя узнать, был ли уже ACK этого
PMA packet или pending CTR, и нельзя приписать поздний held64 тому же episode.

Статистика21 кадров против18 Q2 или12 P2 — отдельные неконтролируемые опыты;
это не causal improvement measurement. Номинальный wire load≈195,56kB/s
(1335/1024×150000), а accepted/elapsed включает startup/queue buildup и не
является измеренным устойчивым bandwidth.500мкс — continuation predicate,
не WCET всей IRQ; наблюдавшийся maxpoll нельзя использовать как hard headroom.

## Точная возможная цепочка в SK

Anchors — `build/v6r-fw-02/`:

1. `patched/v2/app/mt_live_runtime.c:299`: `tud_task_ext` обрабатывает прежний
   completion. `patched/usbd.c:850` снимает BUSY, затем CDC callback
   (`source/.../tinyusb/src/class/cdc/cdc_device.c:515–525`) может опубликовать
   следующие FIFO bytes. `tusb.c:401–421` → DCD FIFO submit первоначально
   загружает до64 в PMA (`patched/dcd_stm32_fsdev.c:937–962,1036–1052`).
2. Runtime317 вызывает `mt_live_adc_service` **до** единственной ordinary
   grant opportunity324–325. Service (`app/mt_live_adc.c:83–124`) сначала
   получает и валидирует private DMAhalf512, затем сразу делает четыре offer128.
3. Driver (`platform/adc_timer_dma.c:590–620`) уже скопировал полную половину
   в `driver.snapshot`, повторно проверил safe_half/events/elapsed, снял только
   expected DMA flag, обновил next_half/index и выдал block. Его sample pointer
   указывает в private snapshot, не в перезаписываемую DMA half.
4. Если queue уже8, первый `mt_live_device_offer` получает FULL и делает
   first-close до terminate. Текущий runtime ещё не дошёл до grant/guarded TX.
   Таким образом существующий код допускает: **новый USB transfer опубликован,
   но ADC queue publication отказывает раньше release/последнего TX/prefetch**.
5. `live_write` runtime111 требует whole-fit. Для оставшихся183 при free64
   не хватает119байт. Q prefetch235/400 требует actual final commit+flush;
   READY кадр не позволяет перезаписать staging ради разгрузки queue. После
   successful final write тот же buffer уже может принять до512 новых samples.

Это source-supported route и точное место отказа, но не полная измеренная
хронология: G24 не записывает callsite publication. Она могла прийти из task
callback, automatic write flush или explicit flush предыдущего прохода.
В частности факт event спустя≈257мкс до close не доказывает, какой именно
из этих вызовов сработал. Снимок всё же обосновывает взаимодействие между
валидной private ADC copy, очередью и ещё не завершённой USB publication.

## Одна предлагаемая корректировка: handoff после validated copy, до queue offers

Более простые варианты хуже обоснованы. Безусловный pre-ADC grant задерживает
ещё не выполненный критический poll:2907+500=3407 оставляет лишь6мкс даже в
неправомерном сложении observed maximum и не-WCET500; fresh TIME/guard и
последний IRQ handler в такой расчёт не помещены. Уменьшение offer до free64
меняет whole-fit publication semantics: всё равно нужно принять весь остаток183
до prefix commit/staging release, а дополнительных guarded passes станет больше.
Это не устраняет119байт дефицита и требует отдельного транспортного контракта.
Рост queue/FIFO увеличил бы лишь latency storage при неподтверждённом drain rate;
spare4 и reserve8192 также не дают такого простого расширения. Поэтому выбран
handoff после уже безопасного ADC copy, а не эти три подмены цели.

Не выдавать grant перед критическим ADC poll. Разделить существующую ADC
операцию на **acquire/validate private block** и **publish четыре chunks**.
Только на узком mode5 cached-final пути вставить между ними существующие
grant и один cached TX attempt, затем уже существующий Q collect-only при
подтверждённом final commit. После освобождения четырёх queue slots публиковать
private512. Это переупорядочивание одной операции внутри прохода, не новый
grant/второй TX/дополнительный buffer/снижение Fs или скрытая оконная пауза.

Eligibility: STREAMING/mode5, hardware owned/running; actual acquired BLOCK512
со всеми прежними descriptor/rate20/3us/indices проверками; current queue free<4;
cached DATA1024 READY, offset>0 и remaining1..384 (R2 —183), matching nonce/gen/
revision/epoch/soft; нет control/Stop/HELLO/error/sealed/budget/RESERVE intent.
Hint не заменяет real ticket. Остальные режимы/uncached encode/EMPTY сохраняют
прежний порядок. Pending RX/carry/task/control — консервативная отмена fast TX,
а не обход обработки Stop/HELLO. Bytes могут прийти асинхронно позже, поэтому
окончательное admission остаётся прежним guarded usable/ticket/epoch check.

Порядок подходящего прохода:

1. Сохранить epoch/soft и core identity, выполнить прежний ADC poll/copy и
   полную post-copy ownership validation. Пока никаких queue offers.
2. Fresh TIME/loss/stable/scope; capture cached ticket без collect/encode.
   Использовать **ту же одну** grant-попытку, marker consumes её даже при отказе;
   свежие TIME/epoch/lifecycle после IRQ. Не ждать/spin до прихода IN/места FIFO.
3. Один прежний guarded `step_prepared`, со всеми before/after/final TIME и
   constant prefix/CRC publication. Затем прежние flush/barriers. Если final
   commit действительно опубликован — вызвать Q prefetch по actual certificate,
   ≤512 вне PRIMASK; старый принятый prefix не откатывается.
4. Восстановить outer actor на каждом выходе. Повторно проверить private block
   ownership/session/clock и строгий deadline относительно saved driver poll
   stamp **до queue publication**; post-copy работа не должна незаметно вынести
   следующий service за3413. После проверки — прежние contiguous offer128.
5. Local `grant_attempted/tx_attempted` запрещают второй grant/обычный TX ниже
   в этом же runtime pass. Обычная RX работа не разрешает второй encode/TX;
   следующий pass обслужит её обычным способом. EMPTY/ERROR не превращаются
   во второй DATA submit. Нового task dispatch в промежутке нет.

Driver уже имеет private snapshot512; block descriptor и attempt markers
помещаются только в локальный контекст/существующий ticket, **0new static RAM**.
Текущий spare4 нельзя расходовать на pending-state bank. Pending private block
не переносится между runtime calls: запрещены второй `read_block` или любой
overwrite этого private snapshot до завершения/отмены его publication. Если RX
уже обработал Stop/HELLO либо изменились epoch/TIME/core identity, **ни одного
offer** от старого block после этого не допускается. State проверяется снова
перед offers; отменённый block не превращается в данные новой сессии. Лучше
разделить acquire/publish API без callback/reentrant ADC service, чем вызывать
общий runtime из queue.offer. Exact stack новой ветви требуется проверить.

`last_poll_us` обязан остаться прежним **stamp начала read_block**, как
`adc_timer_dma.c:618`, а не концом copy/USB/prefetch. Copy и вставленная работа
входят в следующий строгий интервал<3413. Запрещено освежать этот timestamp
ради прохождения deadline; fresh elapsed checks не перезапускают срок. Старый
наблюдённый maxpoll2907 никак не квалифицирует новое расписание.

Отмена только fast-path hint (например, pending RX, scope denial или no-IN)
при ещё здоровой прежней STREAMING identity **не разрешает return IDLE с
забытым block**: driver уже продвинул first_sample_index. В этом случае остаются
прежние contiguous offers либо честный queue-full; нельзя перейти к следующему
read_block, перескочив copied512. RX не dispatch/consume между acquire и
разрешением судьбы этого pending block: plain Stop bytes могут ждать, но не
должны сначала выполнить normal Stop и потерять уже copied-but-unpublished512.
Если Stop/HELLO всё же уже исполнен или произошли epoch/TIME/driver loss,
старый pending диапазон не публикуется: он явно относится к прерванной старой
сессии/unknown tail. Нельзя выдавать clean normal END/ACK, как будто этот
интервал вошёл в accepted prefix; HELLO replacement не переносит его в новую
nonce. Нужен явный existing fail-closed/recovery disposition, если нормальный
Stop не может учесть pending interval. В модели этот край проверяется отдельно
от простой отмены оптимизации; восстановление/скрытый skip индексов запрещены.

## Отказные границы и ожидаемый эффект

Grant не гарантирует два нужных дополнительных PMA loads и освобождение119байт.
Если host/USB ещё не готов, единственный write даёт known0; без spin/retry queue
может законно переполниться как прежде. Если final accepted и Q prefetch смог
перенести4×128, queue8→4, и следующие4 offers могут быть приняты с прежними
индексами. Это конкретный проверяемый эффект расписания, не обещание средней
пропускной способности и не доказательство, что очередь была8 в прежний момент.

Поле3000/500 или сумма observed maxima не являются admission. Fresh elapsed
после вставленной работы должен fail-closed на прежнем3413; budget6/<500
не увеличивается. Дополнительная задержка может всё равно вызвать deadline
fault, что будет честным отрицательным результатом, не пропуском samples.

При TIME/epoch/lifecycle/Stop/error между copy и offers private block больше
не публикуется под старой или новой identity; прежние quiesce/cleanup могут
изменить driver snapshot. Нельзя восстановить popped queue slots или скрыть
неопубликованный интервал за clean END. Guarded write с unknown/late positive
сохраняет прежний fail-closed/delimiter/unknown-tail контракт. Q error обрабатывается
только matching guarded recovery, first-close до cleanup; другой DATA не пишется.
Валидность copied block не означает валидность следующей DMA half после паузы.

## Ограниченный следующий результат, без ещё одного profiler

После отдельного scope/review: один actual-C acquire→cached final→prefetch→publish
model с successful q8→4→8, no-IN/known0, partial/unknown/finalTIME, stale epoch/
scope/RX cancellation и сохранением pending block indices. Actual core/queue/
serializer и новая adapter/runtime boundary нужны в одной модели; USB/MMIO
seams раскрыть. Детерминированно проверить оба случая: существующая IRQ
opportunity освобождает FIFO и final/prefetch/publish проходят; либо не
освобождает, единственная known0 попытка не крутится в ожидании и прежний
queue-full/fail-closed сохраняется. Source proof прежних driver/DCD/MMIO/CRC/Stop guards плюс
одна ARM/resource/stack проверка; не повторять GUI/старые широкие suites.

Только затем один exact аппаратный опыт с теми же пригодными64/24/136. Критерий
успеха — весь запрошенный непрерывный150k интервал без source fault/gap,
с raw/CRC/END/ACK/остановкой, не просто больше кадров. Если no-IN повторяется
до освобождения staging либо новый elapsed fault возникает, single-pass pipeline
не получает гарантированный запас: это основание отдельно пересмотреть
архитектуру передачи, а не бесконечно двигать точки или увеличивать очередь.
SK на плате и все прежние данные остаются нетронутыми этим предложением.
