# V2-06k — раннее независимое чтение реализации

24.10.2026, `stream200_critic`. **INTERIM / не итоговый вердикт.**
Контракт принят отдельно: canonical SHA256
`e62983a12054f427c6eaa83aad7cadbef9aaf65a216cf8abb0d65aa318904595`.
Авторы ещё готовят модель, host fixtures, GUI и ARM. Ни один их промежуточный
результат здесь не называется software/package/physical PASS.
Критик не менял production и не запускал модели, тесты или аппаратуру.

## Прочитанные контрольные точки

Firmware overlay `firmware/v2-stream/overlays/batch256.json`:
`ab0a6e65dac9623580b3a2aecdafc39e83b66419fdcad80039c6909885bbc786`.
Actual draft расположен в `build/v6k-fw-draft/v2`, diff прочитан против
`build/v6i-fw-01/patched/v2`.

| Файл | SHA256 при чтении |
|---|---|
| protocol/mt_live_device.c | `8d3eb0a816e56bb95c7ec5fd7a11fca2a934a6f6fd7ce3103587ee14931ff7a4` |
| protocol/mt_live_device.h | `93f338b4284bb808a6331df1ef5a91003472d6893a248d18116439fbf9791b8d` |
| acquisition/mt_sample_queue.c | `d54355f863ae9ff5812944bdb935810e9b57f4f698c7098c32b01b04961bc981` |
| acquisition/mt_sample_queue.h | `177597c2291c9893fce54d5a78761c5f188a39d09e0aae2a2f48b9d5c9934d3a` |

Дополнительно прочитан diff profile table/header: четвёртый descriptor,
прежние ADC/timer параметры, max_block_samples добавлен в конец структуры;
packer по-прежнему обрабатывает отдельные queue chunks1…128.

Host checkpoint и packaging (изменения продолжаются):

| Файл | SHA256 при чтении |
|---|---|
| host/motortester/stream_wire.py | `5e04530c5051e9b936f255e38a80aa4788c74faddddcbf561c9fe44be7472ceb` |
| host/motortester/stream_endpoint.py | `5105fb99c2f6ea0810e982dffdee2a502aced5c1882e6144875752c2aecdc416` |
| host/motortester/stream_model.py | `73bfb3dec0aa2ecefd192627a462ac439c67b98d8bc881897e2e884557a7c209` |
| host/motortester/stream_provenance.py | `77a2752e767d1ee6b78d0bd2e3cf4373f629fea76b283337bac1bdeb5d28c954` |
| host/packaging/v2/profiles_package_check.py | `c377da568251247ee1f1065ecf4ae54ee4fc4dfd153c9d5b6fc16dcbf2c465a1` |

Также прочитаны diff bridge, recording, v2/stream_device и offline verifier.
Это прочитанные снимки, не объявление авторского freeze.

## Firmware: существенных замечаний в этом checkpoint не найдено

- `stage_data` применяет требование full256/terminal short только к новой
  подготовке. `build_tx` прежде возвращает уже закэшированный frame.
  `completed_data` не отвергает его только из-за HELLO_PENDING; это сохраняет
  уже принятую часть старого DATA при replacement HELLO.
- Обе выбранные части проверяются до изменения prefix CRC и очереди.
  CRC вычисляется локально; `pop_span` проверяет все expected pointers,
  indices/counts/overflow и только затем одной нефаллибельной секцией
  изменяет head/index/used. Переход7→0 выражен modulo8.
- При full pair первый128 упаковывается в160байт, второй начинается на
  байтовой границе. Нового массива256 кодов не добавлено. Ingress/Stop-tail
  выбирают discard bits из descriptor, поэтому mode4 не теряет правило10бит.
- Ticket сравнивает новые tx span и второй queue slot fieldwise.
  Stale ticket не обходит прежние deferred-error/epoch/TIME guards.
  New prepare lone128 в STREAMING возвращает EMPTY без ожидания в цикле;
  sealed DRAINING разрешает последний остаток без несуществующего партнёра.
- ACK/CAPS используют selected max из descriptor; discovery2 отдельно
  объявляет7/256. Прежние layouts и max frame не расширены.

Эти выводы получены чтением. Не утверждаются фактические SRAM/stack,
компиляция или корректность всех ветвей без адресной actual-core модели.

## Host и package: раннее чтение

Закрытая таблица MODE_MAX_BLOCK связывает старые1/2/3 с128, новый4 с256.
Discovery pair admission строгий; endpoint выбирает150→4 только при
capability7 и связывает selected ACK maximum с CAPS до START. Data decoder
проверяет count по config, endpoint — по выбранным CAPS, short_seen также
режимный. Session raw/END CRC остаются canonical u16le.

Intrinsic marker нового режима допускается отдельно от старого. Mode4 со
старым marker и mode1/2/3 с новым отклоняются. Canonical0…4092/multiple4
проверяется для обоих10-bit режимов. Journal cap8192, старые raw layouts и
лимиты storage не увеличены. Bridge и companion connection связывают
observed config с соответствующим marker.

Package helper требует exact mode4/marker/CAPS256, три новых batch checks
и decoded wire-count receipt, а не только selector150k. Одновременно
сохраняет raw/journal/CSV hashes, счётчик CSV и первый дробный шаг времени.
Достоверность самого receipt будет проверена чтением окончательного smoke
и его фактических артефактов, когда автор объявит готовность.

## Единственное переданное точечное замечание — закрыто

В первом host diff новый `len(samples)>CAPS.max_block` guard стоял после
изменения received_end/CRC. При действующем strict codec+config+CAPS
превышение было недостижимо; воспроизводимый P1 не заявлялся. Для ясного
fail-closed порядка автор перенёс guard до любой prefix mutation.
Исправление лично прочитано в endpoint SHA5105fb99…cdc416.

Старый synthetic GUI checkpoint ещё использовал mode3/128; автор явно
переписывает его. Это незавершённая работа, не скрытый PASS и не новый дефект
предъявленного финального результата. Дополнительные прогоны не запускались.

## Остаток до финального ревью

Нужны immutable source/overlay pins, одна actual-core модель (включая
partial cached DATA→HELLO_PENDING, Stop257→256+1, stale второго slot без
CRC/pop), exact ARM/static RAM/stack/новый адрес136 и сравнение неизменённых
guards. Затем окончательные адресные host evidence, actual C→Python fixture,
готовый synthetic GUI и отдельно exact Windows package.

При final review необходимо проверить, что ошибки peer negotiation не
отправляют START, receipt действительно декодирует DATA256/terminal short,
mode3/старые journal остаются читаемыми, а более крупный guarded CRC и
early-grant aging не названы доказанным ускорением. Новых P0/P1 по прочитанным
снимкам нет; итоговая оценка до этих свидетельств не назначается.

## Дополнение: представленные host evidence и текст native-модели

Позднее24.10.2026 автор host предъявил первый адресный прогон четырёх групп:
`build/v6k-host-unit-01/tests.log`, SHA256
`434857a28b58dd372383a740e7f870288bca6d82fe307c668476ececdaa571e2`:
4 PASS за0,114с. Лично прочитан diff групп, включая independent literal
packing129/255/256/padding, strict discovery и отказ SC150 до START,
DATA256+short129 и запрет следующего DATA, mode4 journal без companion,
старый mode3 и прежние версии файлов. Критик прогон не повторял.

Source GUI `build/v6k-host-gui-01/result.json`, SHA256
`1a32e02efd140f61458aeafc8dff27cdfd9bdd8ebafffcab9b8496e90cbde37c`:
первый авторский PASS,9 checks; Windows10/Qt windows, frozen=false,
COM0, owners_closed=true, callbacks/errors пусты. Receipt сообщает1693 полных
DATA256 и final239, maximum frame370. Лично прочитан код smoke: сведения
получены декодированием сформированных frame bytes, с проверкой index,
sequence, mode/generation, отсутствия DATA после short и END canonical CRC.
Это synthetic evidence, не физическая пропускная способность STM32.

380911 выбранных raw кодов проверяются по каждому исходному synthetic
значению при fresh Open; отдельная копия без companion сохраняет identity
и все raw. CSV проверяет число строк, имя столбца, identity и первые два
времени; равенство каждого ADCcode в CSV **не проверяется и не заявляется**.
Все9 файлов receipt (12468467байт) лично сверены по size/SHA без повторного
Open/экспорта. Три PNG live/open/SC150 mismatch лично просмотрены: тексты,
Fs150000, fractional step, предупреждение10MSB и synthetic label читаемы,
сообщение об отсутствии mode4 полностью видно.

Дополнительные source pins при этом чтении:

- `host/tests/test_stream_modes.py`:
  `e090cc5f3c2a360095f9f72f2f4b7c4659129fd704c384a9e3e4c90b7e039779`;
- `host/motortester/v2/stream_profiles_smoke.py`:
  `9e4d0ca46e8cef06ace69bb3bbbaeb5a9b775bcd08c00ee31c0206c7fdd774f7`;
- `host/motortester/stream_wire.py`:
  `8b4d5ad42644738c7c03c06f51cf492775548027fb78d948194716c1ebf08912`
  (после первого checkpoint уточнён docstring ссылками на I/K);
- `host/docs/stream-modes.md`:
  `3e94e88f1e8ad4851d39239c6a6f1a3bbe20d31672655a465617ac3ed20a0ea1`.

Прочитаны до исполнения `tests/v2-stream-firmware/batch256_model.c`
SHA256 `53d8a3b8b95da7208ee2f41eb0d12ede9d00800b67bf912c3ac1a8aa5425b81e`
и runner `check_batch256.py`
SHA256 `f155142dbda4bd543e13909690347993537948e363d37914888ff0351b112808`.
Три группы используют actual core/queue/wire с logical IO, отдельный
generic queue wrap7→0, actual runtime whole-fit extraction, partial cached
DATA→Stop/HELLO и хвост257. Это достаточный адресный план; дополнительных
моделей/широкого прогона не потребовано. Actual C385 crosscheck, завершённый
ARM/native, immutable freezes и Windows package по-прежнему ожидаются.
