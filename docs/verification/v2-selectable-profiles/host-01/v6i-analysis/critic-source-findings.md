# V2-06i: промежуточное независимое чтение исходников

24.10.2026. Критик stream200_critic не автор реализации. Это список замечаний
к черновику host/packaging и уже замороженному firmware-кандидату; не итоговая
приёмка ПО, пакета, Flash или физических режимов. COM/SWD не использовались.

## Замечания, переданные одним списком

1. **P1 для приёмки пакета, открыто на момент чтения.**
   Первоначальный `host/motortester/v2/stream_profiles_smoke.py:113` записывал
   `platform.platform()`, тогда как
   `host/packaging/v2/profiles_package_check.py:22` требует `win32`.
   В source GUI01 фактически сохранено `Windows-10-10.0.19045-SP0`.
   Успешный замороженный GUI будет отвергнут упаковщиком. Согласовать явное
   системное поле, сохранив отдельную подробную строку версии Windows.
2. **P1 соответствия nonce/revision-контракту, открыто на момент чтения.**
   `stream_wire.decode_frame` отвергает неизвестную revision до передачи
   проверенного nonce в `stream_endpoint.Endpoint._frame`; последний
   вызывает recovery по `version` до фильтра чужой nonce. CRC-valid envelope
   обычного device-kind с revision0.4/nonce11 прервёт текущую0.3/nonce22.
   Канонический контракт требует сначала bounded envelope/CRC/header,
   затем stale nonce ignore и лишь затем current revision fail-closed.
   Firmware checked-envelope реализует этот порядок. Нужна согласованная
   host-граница без декодирования payload неизвестной revision. Достаточно
   добавить stale/current unknown revision и повреждённый envelope в уже
   существующую адресную группу handshake.
3. **Пробел свидетельства совместимости, до финальной приёмки.**
   Новые независимые legacy fixtures проверяют companion1, GUI — companion3.
   Для companion2 предложен один offline Open сохранённого H2 с проверкой
   неизменности файла/companion; новый большой набор проверок не нужен.

## Проверенная область без найденного существенного дефекта

- Текущий/pending/tx mode и revision связаны с nonce; полный HELLO_ACK
  коммитит новую конфигурацию. Partial old ACK и stale prepare ticket не
  публикуют новый режим. Guarded completed/CRC/pop остаётся прежним.
- Оба пути поступления отсчётов, включая Stop tail, сначала проверяют ADC12,
  затем сохраняют канонический `code & 4092` для mode3. Wire packed10 и
  END CRC относятся соответственно к wire bytes и canonical u16le.
- Descriptor задаёт 50/100/150k, PSC/ARR71/19,71/9,47/9; рациональный
  период150k20/3 мкс не заменён округлёнными6 или7. Deadline3413 и CEN5/6
  отделены от номинального периода. Выбор descriptor запрещён работающему
  или владеющему периферией драйверу.
- Journal magic3/4 содержит полный intrinsic identity; legacy1/2 читает
  строго прежние8полей. При recovery каждый B создаёт StreamBlock и
  проверяет допустимый диапазон/кратность4. Companion не нужен для
  восстановления retained10. CSV считает время по sample index/Fs.
- UI выбирает режим до Connect, блокирует изменение при владении сеансом;
  на экране и при Open явно показывает потерю2LSB. Edge bins не названы
  доказанным насыщением исходного ADC.

## Лично проверенные фиксации

Firmware freeze `build/v6i-freeze.json`:
`ae1d2ab6b741cbfd76baf7557c656477c7c7c17646ea143bdc8a189c6681c7cc`.
Только чтением/хешированием проверены91pins production/image/native,
ошибок0. Все38пар из `source-equivalence.json` побайтно совпали с H/SB,
включая runtime, DCD и связанные USB-заголовки. Подробные token-normalized
proofs автора прочитаны отдельно; это не повтор ARM или аппаратного опыта.

SC BIN38188байт:
`a36f72a772c03c5cbfd85767e5f07f0abc3ad2f2ffd7d1ee1c43143d20ca1c90`.
ARM/native01 PASS — свидетельства автора; собственный новый прогон модели
на данном промежуточном этапе не выполнялся. Host unit/GUI ещё не являются
финальным замороженным набором, пакет не собран. Итоговый балл пока не задан.

## Адресная перепроверка исправлений

Все три замечания выше сохраняются как история раннего чтения; на текущей
контрольной точке они **устранены**. `decode_frame` имеет отдельный режим
bounded envelope для endpoint, фильтр nonce предшествует active revision,
а `decode_payload` самостоятельно запрещает неизвестную revision. В прежнюю
handshake-группу включены stale/current0.4 и повреждённый foreign envelope;
`build/v6i-host-unit-03/tests.log` сообщает4PASS за0.048с. Это прогон автора,
не повтор критика. Синтетический actual C transcript131код декодирован Python
с проверкой исходных canonical samples/END CRC (`c-producer-crosscheck.json`).

`legacy2-open.json` подтверждает один offline Open исторического H2 magic2 и
companion2, диапазон[1536,3003339),3001803отсчёта, хеши до/после совпали.
Smoke теперь пишет `sys.platform` и отдельно `windows_host`.
Окончательное отображение/согласованность platform ожидает frozen-пакета.

Лично просмотрены GUI01 `profiles-live.png`, `profiles-open.png`,
`profiles-legacy-mismatch.png`: частота150000, номинальные6.66667мкс,
10сохранённых/2потерянных бита и неизвестный хвост различимы, перекрытий нет.
Последний текст подсказки о повторном открытии окна изменён после GUI01 и
будет проверен в frozen; старый PNG не выдаётся за свидетельство нового текста.
