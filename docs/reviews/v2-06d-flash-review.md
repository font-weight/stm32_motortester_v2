# V2-06d — допуск одного опыта V2S7 / 100 kS/s

23.10.2026. **PASS,9,605/10 только для допуска точного образа к одному10-секундному опыту.** Это не общий PASS V2-06d: фактический100k Record и завершённая проверка нового Windows-пакета ещё нужны. Неудачные200k результаты A/C сохраняются; уменьшение частоты разрешено пользователем и оформлено отдельной задачей до этого опыта.

## Версия, независимость и свидетельства

База плана и host-source `3665be41e80c8168ad97c61d64cb79b232091d03`; production-код `7e4b318164082c90e0b2c0e982936f6f0c786528`. Критик `stream200_critic` не автор firmware/host/плана, COM/SWD не использовал. Действуют V2 quality-gate, scope D в task/coordination. Пустой PA0, USB-питание прежней платы, ST-Link без3,3 В — подтверждения пользователя, не независимый осмотр. После возврата S4 пользователь подтвердил replug; изменение соединений не заявлено.

| Вход | Значение/SHA256 |
|---|---|
| Exact S7 BIN,36260 байт | `f3d5563139d4e5892273312996bd8b8486f222196e6cf3c25042d5c37c6a290b` |
| ELF | `5bc0eb99bf0490c3ef98ecea28e6d0dd3b006782d6719f02e59e3f858346aa25` |
| Свежий64KiB backup S4 | `95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e` |
| build/v6d-board-01/plan.json | `47b9e96388635f1f9cfc27fe8401cda5e0180c4d9adbda8ad90df1e62f7230d1` |
| CLI | `7fb012b5e26abf45342caa05c6bc33936f8a379b67797cc55658ffb8bf15e95f` |
| Build/Fs/DATA | `0x56325337` / `100000/1` /128 |
| Probe | Единственный ID0, connect SN `57005400120000393333574E` |

Критик лично сверил506 build inputs,112 dependencies,3 образа,32 analysis inputs;22 native inputs и15 host sources/evidence. Проверены неизменные11 файлов и12 тел функций S6→S7. Лично воспроизведён final native model100k и exact static analyzer: PASS, stack5924/aligned5928 из8192. Text36132/data128/bss11212; data+bss+stack19532/20480. Модель проверяет новый CEN10/11мкс, deadline5119/5120, CAPS100k, whole-fit zero/full и accepted-prefix. Неизменную USB burst/TinyUSB модель заново не запускали.

Whole-fit проверка выполняется под прежним core IRQ/epoch lock: при free<length возврат известного0 до вызова write; FIFO/prefix/sequence не меняются. При фактическом принятии возвращается actual accepted, положительное принятие после потери epoch не стирается. Это не измерение CPU/USB throughput. Увеличения raw-очереди и удаления fail-closed нет.

Host принимает50/100/200k из общего CAPS allow-list; навигационные окна сохраняют длительности, файл/CSV используют принятую identity. Прочитаны пять авторских адресных тестов (PASS4,793с), source Qt100k результат и лично просмотрены live/open PNG:100000/10мкс, synthetic origin и unknown tail читаемы. Synthetic537046 raw сравнены авторским helper целиком с fixture; CSV проверяет count/Fs/первые времена/receipt, не все значения CSV. Эти GUI данные не физические. Источники и личные проверки — [critic-source](../verification/v2-100ksps/critic-source.json), [critic-static](../verification/v2-100ksps/critic-static.json).

Для допуска лично восстановлен BIN из ELF PT_LOAD: byteequal. MSP0x20005000, reset0x080087E5, конецFlash0x08008DA4, diagnostics0x20002BC4/136. Свежийbackup полностью совпал с проверенным возвратом S4, prefix35384 с SHA04ba2853b6a964cd812bf555a32da7fb019bcd60ba9fda0bd586d71112b3143d. Логи fresh read: один probe, прежнийSN, ID0x410,3,2 В; список старогоCLI вместоSN показывает `Old ST-LINK firmware/ST-LINK already used`, конкретный connect сообщаетSN.128KiB из инструмента не подтверждают подлинность MCU и не расширяют проектные64KiB/20KiB.

Decoder S6→S7 меняет только версию/build/SHA/Fs/deadline5120;34 поля совпадают с exact header. Адрес прежний. План включает TIM3/RCC/ADC/DMA блоки, ADC_DR не читается. Подробности — [critic-flash-image](../verification/v2-100ksps/critic-flash-image.json); хеши входов — [critic-flash](../verification/v2-100ksps/critic-flash.json).

## Обязательные условия

1. Сохранить подтверждённые питание и пустой PA0. Единственный probe ID0 должен сообщить прежнийSN; при неоднозначности или смене соединений остановиться. Приложение/другие владельцыCOM закрыты. Backup и exactBIN неизменны.
2. Запись только exactBIN по0x08000000 с verify, без mass erase/option bytes. Отдельный Dump0x8DA4 байт, побайтное/SHA совпадение до START. Затем Reset/Run и подтверждённое USB-переподключение; фактический COM проверяется.
3. До одного START: build0x56325337,CAPS100000/1,CH1/12bit/DATA128. Объявленный build не заменяет Flash readback. Probe запускается exact argv плана с seconds10, новым каталогом `build/v6d-board-01/run` и source/image provenance. После отказа не повторять опыт скрыто.
4. Полные10с Record без source/host fault; темп90000…110000 полученных кодов/с по host monotonic — только грубая оценка темпа. Normal END reason0 и соответствующий STOP_ACK; fresh Open и равенство всех выбранных raw соответствующим wire DATA без gaps/overlap. Неизвестный произведённый хвост не считать нулевым.
5. Во время записи SWD не используется. После остановки/закрытияCOM — два frozen record0x20002BC4/136, build/nonce/generation, flags0, ошибки0, ADC stopped/owned0/hardware_off1; observed poll/copy строго<5120мкс. Если Stop не подтверждён, последующее SWD диагностическое и не доказывает нормальные сроки.
6. Плановые блоки: TIM3 0x40000400/48, ADC0x40012408/12, DMA0x40020008/16, RCC0x4002100C/20. После Stop ожидаются TIM3 CEN0/PSC71/ARR9, ADC_CR2=0/SMPR2 sample4, DMA EN0, нужные clocks enabled/reset released. Не читать ADC_DR. Frozen shape отдельно не означает normal Stop.
7. При любом отказе сохранить все traffic/raw/логи/dumps, закрыть владельца и вернуть свежие64KiB S4 с verify/readback и READY без нового START. Успех10с не означает долговременной устойчивости, точности частоты, аналоговой полосы или измерения зажигания.

## Оценка допуска

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% | 9,7 | ExactS7, Fs/сроки/память и изменённый whole-fit проверены, один опыт имеет явные критерии. |
| C2,20% | 9,6 | Freshbackup/verify/readback/rollback, прежний fail-closed сохранён; успех исполнения не предполагается. |
| C3,25% | 9,5 | Личный native/static/hash/ELF контроль и freshread; GUI/test evidence с честными synthetic границами. Монтаж подтверждён пользователем. |
| C4,15% | 9,6 | Функция, допуск, физический результат и пакет разделены; нет новых аналоговых соединений. |
| C5,10% | 9,6 | План/образ/инструменты/backup закреплены; сохранение неудачи и дальнейшая приёмка определены. |

`0,30×9,7 + 0,20×9,6 + 0,25×9,5 + 0,15×9,6 + 0,10×9,6 = 9,605`.

**PASS только этого допуска.** Общий V2-06d остаётся без итогового заключения до физического опыта и завершённого Windows-пакета. QCore physical probe не проверяет видимый GUI с платой. Предыдущие200k REWORK не превращаются в PASS.
