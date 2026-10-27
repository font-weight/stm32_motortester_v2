# Q/SJ — авторская граница свидетельств

27.10.2026. Черновик программного кандидата; независимое ревью и аппаратный
допуск отдельные. Ни COM/SWD, ни Reset/Flash/START автор не выполнял.

Вход: frozen SI/P2 и proposal `build/v6p-followup/analysis.md`. Новый strict
prefetch overlay применяется после late-grant. Единственное функциональное
изменение — collect-only после actual final commit cached полного mode5
DATA1024, старого flush и его TIME/loss barrier. До повторного использования
старого ticket проверяются post-completion identity, accepted remainder,
prefix/CRC/sequence, EMPTY staging, очередь, intents/budgets и RESERVE.
Непустая очередь переносится максимум4×128 в существующий packed staging;
accepted prefix повторно не продвигается. Нет seal/frameCRC/COBS/второго DATA
write/grant. Обычный prepare использует тот же выделенный collector.

Новый helper получает сохранённые epoch/soft именно исходного prepare данного
прохода. Fresh TIME/loss/usable/scope до копирования и TIME/stable/epoch после
него сохраняют ownership. Copy/pop вне PRIMASK; stale cleanup не восстанавливает
старые слоты. ERROR получает новый текущий ticket и только matching guarded
recovery; EMPTY/COLLECT не могут вызвать второй submit. First-close и поздние
эпилоги используют прежний actual64 модуль, ABI без изменений.

`build/v6q-fw-01` — единственная ARM сборка, PASS. text45244/data128/bss12132.
Static growth0; с reserve8192 занято20452 из20480, остаток28байт. Условный
stack upper6164, aligned6168, reserve8192. Collector frame176, pure certificate36,
prefetch entry24; runtime root frame336. Legacy136@0x20002F1C и progress64@
0x20002FA4. Generated SJ header использован board и observer; linked board word
и observer bind machine bytes проверены. Static bound не WCET/high-water.

`build/v6q-native-01` — один executable/один запуск, PASS трёх групп. Actual
core/queue/serializer/wire/observer и два извлечённых runtime helper исполнены.
Проверены0/1/4блока и q8→4+4offer, ring wrap, wire/CRC/Stop-tail/HELLO, exact
completion certificate, zero/partial/unknown/finalTIME/RESERVE/old modes,
fresh identity до/после copy, scope denial, current ERROR и stale ERROR,
ACTIVE64 с exact generated SJ id и immutable first-close. Legacy136 setup,
DWT/USB/TIME/epoch/actor — явно synthetic seams. Preceding flush/full runtime
step/один grant подтверждены source equality, не динамической USB моделью.

Source proof re-inlines collector и удаляет ровно два новых API: остальные SI
core tokens идентичны. Удаление нового helper/dispatch возвращает весь прежний
runtime. Незатронутые patched файлы и объекты идентичны; ADC/TIME/DCD/FIFO/queue/
serializer/wire не менялись. Модель не является полной USB/MMIO/DMA симуляцией.

Root decoder01 отдельно проверил сохранённый P actual-C fixture; SJ allowlist
ветвь там synthetic. Actual SJ observer binding здесь исполняется в модели.
Старые P/O проверки, GUI/package и аппаратные опыты не повторялись. Неудачных
ARM/native попыток Q нет. Ошибки точного сопоставления apply_patch при подготовке
не изменяли рабочие файлы и не были запуском сборки/модели.

Предел512 samples на проход сохраняется: old cached offset>0 означает, что
обычный prepare только вернул уже готовый frame и не собирал новый диапазон.
Однако packing/local CRC увеличивают время cached-final прохода, могут задержать
следующий ADC poll/USB task; deadline3413мкс и6/<500мкс не расширены. Snapshot P2
не сообщает occupancy/pendingDMA на прежнем completion. Возможность USB-overlap
после flush не гарантирована. Единственная гипотеза не доказывает устранение
queue-full или устойчивые150k; это проверяется отдельным exact физическим планом.
