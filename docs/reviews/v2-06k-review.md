# V2-06k — независимое ревью DATA256

**PASS, 9,60/10 — программная логика, exact ARM/static и source GUI на
Windows 10 с синтетическим источником.** Дата 24.10.2026. Критик
`stream200_critic` не автор реализации. Frozen Windows-пакет принимается
отдельно; Flash и физические 150k этим отчётом не разрешены и не подтверждены.

## Проверенное состояние

Source commit **`cb4757940b3ee9968f953becfbc3ca8caea102d7`**,
base contract commit `dfc89131f2be5481428217206c59dc0cbaeee08d`.
Функциональная база SC — `310d53b10c79a48ddc45357ff65d88c686aef883`.
Требования V2-STR16 и сохранение V2-STR14/15; task K;
[контракт](../streaming-batch256.md) SHA256
`e62983a12054f427c6eaa83aad7cadbef9aaf65a216cf8abb0d65aa318904595`;
[правила приёмки](../quality-gate.md). Образ V2SD/build `0x56325344`.

| Артефакт | SHA256 |
|---|---|
| Firmware freeze | `469cf4e3e50caf263259f9092de0d4f27f6b80442e4dfd65a63c7a4bbe358459` |
| Host freeze | `c78318bb867d18dff0e56a3ea155e7b1e9c6243975e6ad2194473416fd2a81f3` |
| BIN 39448 байт | `244c3af19647ffa24d43973c1d55d24e3b5ce70c494bf781067e13aa60a2daa5` |
| ELF | `95f201f615b6eae9ce356246acd43e70564a00b46331be10e428a9b01d9dfc80` |
| Native result | `4e3b9a13f42c7334da480180a16009e21b8dc8d5a2c346fe5176ea76ac94260d` |
| Source equivalence | `759d2e7e852edd01ba04f29fdd6bcb0ad9fe77299828bca8193438b1e9c59a3d` |
| C→Python crosscheck | `a666df9172164bfbd22b15d6755d1268e31b860ac3644bd42785715cffe9b265` |

Побайтно/SHA лично сверены 44 архивные пары,13539162 байта:
[firmware28](../verification/v2-batch256/firmware-01/manifest.json),
[host6](../verification/v2-batch256/host-01/manifest.json),
[GUI10](../verification/v2-batch256/gui-01/manifest.json).
Manifest SHA соответственно `5e5e275cf100574d4ebef49464f97f8a9ad18e599a4b2a3a7d9d6b10252485cf`,
`2b5e88ac3b643f0a67927bcb0b0d3f2feec607c564b88fa09c184fdc410f7ce3`,
`0169d18baa8a585fec308b68dcd7cc52e3c10f50bea8fa1da70b918743d924e9`.
Дополнительно сверены 650 уникальных pinned файлов из freezes,542 ARM recipe
inputs и 106 native inputs:229966077 байт, без conflicts/mismatch/drift.

## Что изменилось и что лично проверено в коде

Новый mode4 объединяет два соседних queue128 в один packed DATA256 при
непрерывном ADC150k. Modes1/2/3 сохраняют 128. Discovery7/global256 отделён
от selected ACK/CAPS128 или 256. Host требует новый mode4 для UI150k и
отклоняет старую SC150 до START; SC50/100 и legacy fixed-Fs остаются явными.
Номер build не заменяет negotiation или проверку образа.

Критик прочитал actual patched core/queue и конечные overlays, host diff,
модель/runner, crosscheck и GUI receipt producer. `stage_data` применяет
eligibility только к новому кадру; `build_tx` сохраняет cached partial DATA.
`completed_data` допускает завершение старого принятого кадра при
HELLO_PENDING, проверяя оба сохранённых span. CRC считается локально после
их проверки; `pop_span` сначала проверяет все pointers/counts/indices и
overflow, затем изменяет queue одним нефаллибельным участком. Stale второго
слота не приводит к частичному pop или публикации нового CRC.

STREAMING ждёт полную пару без блокировки foreground. После синхронного
quiesce/tail/seal DRAINING отдаёт последний 1…255; остаток 257 —256+1.
Пакеты не дополняются нулями. Prefix считает реальные canonical samples,
sequence — wire frames. Known0/partial/unknown, deferred error, TIME/epoch
и post-write ограничения сохранены. Byte-aligned packing двух 128-блоков
использует прежний staging, без второго массива 256 кодов и роста очереди.

Host проверяет count/short_seen по выбранному mode, а не общей 128. Новый
intrinsic marker и mode4 сохраняют 10-bit quantization без companion;
mode3/старый marker не переопределены. Journal chunk8192 остаётся независимым
от DATA maximum256. Codec, provenance, bridge и companion связывают точную
identity/CAPS. Единственное раннее замечание — размещение дополнительного
count guard после prefix mutation — исправлено автором до проверок; guard
теперь перед CRC/index. Ранее эта ветвь была недостижима через strict codec,
но новая последовательность сохраняет очевидную fail-closed границу.

## Представленные проверки и их реальные пределы

Авторы выполнили один ARM/static build и один адресный native run; критик
прочитал исходники проверок, результаты и сверил pins, **не повторял прогоны**.
Native использует actual core/queue/wire/profile и actual runtime `live_write`
с логическими FIFO/IO callbacks. Три группы подтвердили:

- queue API wrap7→0 и отказ stale второго count/index/pointer без изменения
  очереди; stale caller ticket/mode без write/CRC/pop;
- фактический C-encoded frame371; whole-fit370 свободных байт→known0 без
  вызова writer,371→полный кадр; tails1/2/3/127/128/129/255/257, старые modes128;
- cached partial DATA→Stop с tail129 и→replacement HELLO, корректный порядок
  старой/новой identity, pre/post TIME и unknown acceptance.

Generic queue wrap проверяется отдельно от достижимости head7 через mode4;
горячая искусственная смена mode не моделировалась. MMIO/USB timing этим
не проверяется. Source proof содержит 43 побайтно неизменных patched файла,
23 проверки сохранённых функций; для ingress/terminate допускается только
замена выражения выбора discarded bits на descriptor. Runtime H, TIME,
ADC/DMA/DCD/FIFO не изменены и не перепроверялись широким набором.

Actual C fixture652 байта (DATA256+DATA129+END, nonce503/gen3/config4,
sequences4/5/6) прочитан Python: все 385 canonical кодов равны независимой
формуле; raw SHA256 `571a7e507516b931386e44affb0b67196b8c36e416ef4cab39efd6a32a460880`,
END CRC3917915003 совпадает. Frame sizes370/212/70; produced_end остаётся
unknown. Fixture SHA `8c5fc12a70ee3ad3bf9dccbe6212705dd683bd6fb2b77b4d069d21b6e146c5b1`.

Четыре адресные host-группы прошли с первой попытки за 0,114 с: literal packing
и padding, строгая compatibility/selected ACK/CAPS, new mode4 journal
without companion, старый mode3 и прежние схемы. Нет автоматического START
на несовместимой SC150. Сохранились пределы исходных данных и файлов.

Source Windows GUI прошёл с первой попытки:9 checks,1693 полных DATA256 и
final239, максимальный frame370, COM0, owners_closed=true, callbacks/errors
пусты. Smoke декодирует сформированные wire bytes и проверяет sequence,
index, terminal-short и END CRC. После fresh Open все 380911 выбранных raw
кодов сравниваются с synthetic source; копия без companion совпадает.
CSV проверены по числу строк, названию столбца, identity, SHA и первым двум
временам 20/3 мкс; **каждый ADCcode CSV не сравнивался**. Критик лично просмотрел
live/open/SC150-mismatch PNG: Fs,10MSB, синтетическое происхождение и полный
текст несовместимости читаемы. Это source GUI на Windows 10, не frozen пакет.

## ARM и ресурсы

BIN 39448 <65536 байт. Data 128 + BSS 11244+stack reserve 8192=19564 <20480,
остаётся 916 байт. Exact-image static bound 6116, aligned minimum 6120 при
резерве 8192; это **условный статический результат**, не измеренный stack
high-water и не WCET. Сохраняются предположения cold reset/Thread MSP,
STKALIGN, равноприоритетных USB HP/LP без взаимного nesting, заданных callbacks,
валидной SRAM и отсутствия чужого DMA/debugger interrupts.

Проверены receipt с 113 успешными шагами и compiler dependencies actual
core/queue C/H. Legacy symbol `mt_stream_diagnostics` — **0x20002BE4,136 байт**;
старый адрес SC использовать нельзя. Активного 512-байтного профилировщика нет.
Диагностика по-прежнему one-attempt-per-boot. Единственный предсборочный
generator assert уточнения неоднозначного шаблона сохранён во freeze;
неудачных ARM/native/host/GUI запусков не было.

## Воспроизводимость и ограничения

Exact recipe/argv/input hashes сохранены в firmware receipt, native result
и двух freezes в архивах. Source launch — по [README](../../README.md) и
[host README](../../host/README.md); firmware recipe —
`python -I -B firmware/v2-stream/build_windows.py --output <новая папка build>`.
Адресные команды host unit/GUI/C crosscheck находятся в host freeze.
Критик использовал только чтение diff/исходников/JSON, проверку SHA/копий
через Python3.14.7/PowerShell и просмотр PNG, Windows 10.0.19045.

Новый waveform/ADC сигнал не измерялся. Больший guarded CRC и старение
early-grant могут ограничить реальную скорость: меньшие frames/s не
доказывают устойчивые 150k. Неизвестный tail не назван отсутствием потерь.
I3 physical150k REWORK сохраняется; SC/SB50/100 evidence не переносится
автоматически на SD. Не подтверждены напряжения, аналоговая полоса,
калибровка, зажигание и автомобиль. Нужны отдельный frozen package verdict,
план/допуск exact Flash и физический опыт с новым boot для каждого сеанса.

## Итоговая рубрика

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 |30%|9,6|Реализация явного mode4, canonical данных и совместимости соответствует контракту|
| C2 |20%|9,55|Проверены atomic pair, partial/Stop/HELLO/TIME; ресурсы укладываются при явных статических условиях|
| C3 |25%|9,6|Exact ARM/native/C→Python, адресные host и source Windows evidence связаны pins без вымышленной физической приёмки|
| C4 |15%|9,6|Ограниченная дельта, без роста буферов или одновременного J TIME изменения|
| C5 |10%|9,7|Точный commit, архивы, команды, версии и аппаратные ограничения сохраняют возможность продолжения|

Взвешенный итог **9,60/10**. Открытых P0/P1 внутри заявленного программного
scope нет. **PASS** не является разрешением Flash или приёмкой 150k.
[JSON-вердикт](../verification/v2-batch256/critic-source.json).
