# V2-06i — независимое ревью контракта выбираемых режимов

**PASS, 9,60/10 — только контракт.** Дата24.10.2026. Критик `stream200_critic` независим от реализации. Проверены согласованность документов, прежние границы и расчёты. Черновой код, ARM/Windows-пакет и физические режимы этим отчётом не принимаются; Flash не разрешается.

## Точное состояние

Base `c3407c1bbc2bd152a2e9ae193eb0628aa421ec0a` — завершённый H2. Сохранённая V2SB: source `8243fb3224a1e24980848a8ce02431ec41f5bd9c`, BIN `e7f6f07fc6a43e6b109af6e5c652db1322a0e5023e328007b2c50d303f12536e`. Её физический PASS ограничен одним30с опытом и не переносится автоматически на V2SC/build0x56325343. Применены task V2-06i, требования **V2-STR14/15** и [quality-gate](../quality-gate.md).

| Нормативный вход | SHA256 |
|---|---|
| [Канонический контракт](../streaming-selectable-profiles.md) | `eb84ef5fea2c36da9de397f7a17a0c4d3671a4da8748834a4b09b5b6e14b62f1` |
| [Manifest трёх исходных документов](../verification/v2-selectable-profiles/contracts/manifest.json) | `51d6262a0f9c82a22478edb753cf15e0249c8325612acc6b7582094e14f10bb1` |
| Firmware draft, сохранённый без изменения | `02b04b6c8e14abe422f495de0cc2191f882eb51a3d311614934524f68ef208b5` |
| Host rationale | `ac2ecb2b13b29e7452959d04f55fca0ee5f33d6287a529e42bf25be06849088a` |
| [Точная файловая схема](../../host/docs/stream-modes.md) | `b322c4ec09174bd2b8e7cf7ae20a450c2ab77f96072c5edb077f3fb3b184838c` |

Три исходные копии42361байт лично сверены по размеру/SHA и побайтно. Каноническая версия уточняет статус, актуальный SHA файловой схемы и условность расчёта USB-пакетов; старый draft сохранён как исходный материал, а не альтернативный нормативный текст. Текущий рабочий код меняется авторами независимо и не входит в этот pin. [Личные расчёты/проверки](../verification/v2-selectable-profiles/critic-contract-checks.json).

## Что принимается

Выбор **50k/12,100k/12,150k/10сохраняемых бит** делается до Connect и неизменяем до закрытия сеанса. Это профили захвата, отдельные от «Осциллографа»/«Зажигания». Новый host сначала делает HELLO0.2: exact capability1 означает прежний fixed-Fs путь, capability3 — явный переход через fresh nonce к HELLO0.3 с выбранным mode1/2/3. Legacy Fs mismatch блокирует подключение/START до нового явного выбора; timeout/malformed/revision mismatch не дают скрытого downgrade. Новая прошивка не запускает ADC по discovery0.2START. По исходному base проверено, что старый decoder действительно требует capability1 и отвергает marker3 до START.

HELLO0.3 `<QHH>`=12байт, ACK `<BBBBHHII>`=16, CAPS `<IHBBIIHBBI>`=24. Mode/config/Fs/adc12/retained/encoding проверяются по точной таблице. Весь полный сеанс имеет revision0.3. Pending/current/tx revision+mode+nonce раздельны; новый mode публикуется только при completed ACK, а не parse/prepare/partial write. Ticket проверяет их fieldwise. После bounded framing/CRC/header старый nonce игнорируется; неверная revision текущего nonce — failclosed. Не требуется выдуманный ledger всех исторических nonce; сохраняются прежние current/attempted freshness и isolation/deadline правила.

АЦП физически остаётся12-битным. Единственная точка усечения после безопасной копии DMA и проверки0…4095 преобразует mode3 в `c12=(code>>2)<<2`; одинаково для обычных blocks и Stop-tail. Borrowed snapshot/DMA ring не мутируются. Canonical queue позволяет сохранить guarded completed CRC/pop/sequence без ложного подтверждения после zero/partial/unknown/stale/TIME. Передаётся `q10=c12>>2` в little-endian битовом потоке: четыре10-битных кода в5байтах; `ceil(10N/8)` строго, последние неиспользованные биты0. DATA metadata20байт и count1…128 остаются. Frame CRC защищает wire; END CRC — **canonical u16le**, не уже утраченные исходные LSB.

Journal magic3/direct и4/attempt содержит девять новых intrinsic полей identity, включая retained/discarded bits, wire/storage encoding, normalization и quantization. Для mode3 запись/чтение обязаны проверять0…4092 и кратность4 без companion. Companion3 связывает полный identity/CAPS и SHA. Старые magic1/2 и companion1/2 читаются строгими прежними схемами с миграцией только в памяти; старые50/100/200k bytes/hash не меняются. Пропавшая metadata не превращает10-bit данные в полные12-bit. CSV/JSON явно называют сохранённые биты. Шкала остаётся `a*c12+b`, но исходный код лежал в `[c12,c12+3]`; границы при отрицательном gain упорядочиваются. Крайние0/4092 — корзины квантования, не доказанный точный ADC rail. Неизвестный физический вход остаётся unconfigured.

## Время и ресурсы

Лично проверены `72MHz/((PSC+1)*(ARR+1))`:71/19→50k,71/9→100k,47/9→150k. Периоды20/1,10/1,20/3мкс сохраняются рационально; график/CSV используют index/Fs, без накопления6/7мкс. Half512 при150k равен10240/3мкс. Reject `delta_us>=3413` консервативен при исправном номинальном1MHz TIME: принятое delta≤3412 означает физический интервал<3413мкс. CEN150 имеет отдельный observed bound5ticks; accepted5/reject6 означает bracket<6мкс, меньше20/3. Это не измерение апертуры; прежние20/10 bounds не переобъявляются точными длительностями.

ADC41,5+12,5cycles при12MHz даёт4,5мкс без дополнительной trigger latency. Это расчёт совместимости, не подтверждение установления аналогового сигнала. DATA128/packed10 имеет208decoded/210framed максимум;12-bit —304/307. DATA-only нагрузка150k≈246094B/s против100k≈239844B/s, **+2,605863%**, но frame/encode/commit операций на50% больше и deadline короче. Оценка4 против5USB-пакетов относится к отдельной передаче полного DATA; фактические CDC384 boundaries/ISR могут отличаться. Пропускная способность150k пока неизвестна.

DMA1024/queue8/FIFO384/MPS64/burst6/<500мкс и runtime SB не увеличиваются. Нового sample/staging буфера нет. Оставшиеся948байт сверх8192резерва стека в SB не гарантируют вместимость нового кода: exact ARM/static/SRAM/stack обязателен для реализации.

## Замечания и необходимая проверка реализации

Закрыты: повторное использование ID требований (новые14/15); неоднозначная legacy Fs подмена; недостающий строгий canonical10 domain; неопределённые file versions/enum names; порядок bounded decode→nonce→revision; CEN1505/6; необоснованное слово max у оценки IN-пакетов. Открытых P0/P1 в контракте нет.

Достаточный план проверки ограничен изменёнными путями:

- Одна адресная native-модель actual core/queue/driver: discovery/выбор/partial HELLO и stale ticket, full128 и остатки1/2/3, canonical CRC обычных данных и Stop-tail, invalidADC>4095; zero/partial/unknown/write-commit сохраняются.
- Таблица timer/deadline всех трёх режимов;150k3412/3413, CEN5/6/wrap, rational20/3; equality неизменённых runtime/DCD/guards. Один итоговый ARM/static, без полного старого suite.
- Несколько host fixtures: независимые packing1/2/3/4 и padding negatives, legacy/mismatch/current-revision, один packed journal/CSV roundtrip без companion, строгая invalid/missing metadata, чтение прежних50/100/200k.
- Один короткий injected Windows GUI выбор/Record/Open и проверка соответствующего Windows-пакета. Реальные режимы, включая изменённый100k, затем подтверждать отдельно по exact образу/плану/допуску.

Это будущие свидетельства; ни один PASS реализации, пакета или150k здесь не заявлен. Расчёт и проверка документов выполнены локально в Python/PowerShell без аппаратуры и без запуска implementation tests.

## Рубрика

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 |30%|9,6|Точные режимы/версия/данные и сохранение прежних записей|
| C2 |20%|9,55|Явные immutable identity/guards/timing; реальная вместимость и скорость остаются отдельной проверкой|
| C3 |25%|9,6|Документы/pins/размеры/расчёты сверены, выполнение не выдумано|
| C4 |15%|9,6|Один descriptor и одна точка потери LSB, явные discovery и миграция|
| C5 |10%|9,7|Уникальные требования, точный формат и ограниченный план свидетельств|

Итог **9,60/10, PASS контракта**. Он разрешает использовать этот согласованный контракт при реализации, но не заменяет её независимое ревью или аппаратный допуск. [JSON-вердикт](../verification/v2-selectable-profiles/critic-contract.json).
