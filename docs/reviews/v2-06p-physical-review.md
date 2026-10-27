# V2-06p/P2 — независимый итог единственного физического опыта SI

27.10.2026. **Физическая устойчивость150k: REWORK, 6,375/10.** Отдельный ограниченный результат — исправление build binding и пригодность полученной диагностики — **PASS, 9,60/10**. Второй вывод не заменяет первый. Критик `/root/stream200_critic` не автор реализации и не оператор платы; новых испытаний не выполнял.

## Точное состояние

- Source `0ca687eadd1f5c7b96ffd95796e8d03f01a4f1a1`; SI/build `0x56325349`, BIN44 216 байт SHA256 `aeccdce0a5c2705e5fc77338595655a1f8d20367de486cbc83250f85a3a2d9c7`.
- [Допущенный план](../verification/v2-progress-identity/plan-01/build/v6p-board-01/plan.json): SHA256 `cf69f5573213e661cd9647d14ba32a635d6e242064d8cd4615db04044e36c095`; [отдельный допуск](v2-06p-flash-review.md).
- [Физический архив](../verification/v2-progress-identity/physical-01/manifest.json): SHA256 `d6353288cc66512b613a54813ec8328019808d27385bebd1820f47ae6c4ebbec`;79 source/archive пар,290 672 байта.
- Лично пересчитаны все79 пары, полный readback, обе пары136/64, их identity/флаги/поля и пять before/after pins исходного опыта. Совпадение подтверждено пассивным чтением `pathlib/hashlib/json/struct`. Новый replay wire/journal, decoder/model, сборка и аппаратура не запускались; offline raw/Open вывод проверен по сохранённому точному отчёту и его исходникам, принятым в плане.

## Процедура выполнена один раз

Один program27.10 в11:09:02UTC, independent full readback44 216 байт побайтно равен SI, один Reset/Run11:09:06UTC. Новый фактический ответ «готово»13:07:59.807UTC связан с reset log; trial13:07:59.941–13:08:00.535UTC, whole command0,5940756с. Wire содержит ровно один START. Owner закрыт с `cleanup_finished=true`, phaseclosed; первое SWD-чтение началось13:08:22.568UTC, после закрытия и offline END/ACK проверки.

Root отдельно фиксирует отсутствие SWD/halt во время активного COM, два независимых чтения каждого банка и отсутствие ADC_DR. Эти внешние процедурные факты не выводятся из байтов RAM. После START новых Reset/START/Flash/rollback не было. На плате оставлена **остановленная SI**.50/100 — **NOT_RUN** по scope этого плана.

## Поток не прошёл30с

[Сохранённый probe result](../verification/v2-progress-identity/physical-01/build/v6p-board-01/150000/run/result.json) — FAIL `device_1`; actual Record wall `0.07040500012226403`с. Discovery nonce `4b8c75616c27029d`, выбранный nonce `b028756735517057`, generation3. CAPS подтверждают SI/mode5/150000/12бит ADC/10 сохранённых бит/max1024; это номинальная конфигурация, не измеренная Fs.

[Offline analysis](../verification/v2-progress-identity/physical-01/build/v6p-board-01/150000/physical-analysis.json) — PASS без issues **для сохранённого префикса**:

- Получено12 полных DATA1024, всего12 288 канонических кодов; непрерывный prefix `[0,12288)`, CRC32 `2018795817` (`0x78546129`). Full raw SHA256 `eef651d943660a796257c55d84f296f147873d281c8c975f7627ddd63143bfe2`.
- END sequence16/reason1/flags3/prefix12288 пришёл **раньше** STOP request4. STOP_ACK sequence17 подтверждает именно END16, generation3 и prefix12288. Это согласованное аварийное завершение, не normalStop.
- Record сохранила9 216 кодов `[3072,12288)`. Wire и fresh Open/companion побайтно согласованы; raw SHA256 `3906712a467e6f3c7a05abd6bbb6fa7c54efe050487b01170ef3b09360e2dd17`. Recovery issue отсутствует, discarded journal tail0.
- Wire partial tail/ошибки декодирования отсутствуют, но `produced_end` и количество потерянных ADC отсчётов **неизвестны**. Это не свидетельство отсутствия потерь. Два младших ADC бита в mode5 отброшены штатно; retained raw не является исходным полным ADC12.

Короткий host interval и его rough slope не подтверждают устойчивую частоту. Обязательные30с и отсутствие sourcefault не выполнены. **P1-M2-01 остаётся открытым.**

## Observer SI теперь действительно записал данные

Обе136B копии совпали, SHA256 `dd5a8d40bd521e106d7ea61ae85ac5da80830beabad4d5ca15a05edc7e7f54e7`: SI, generation3, тот же nonce; frozen phase3, flags4, queue high-water8, first acquisition reason1, ADCfault0. Max observed poll2953мкс, copy184мкс. `2953<3413` не доказывает достаточную скорость освобождения очереди. Stopped TIM3 CEN0/PSC47/ARR9, ADC_CR2=0, DMA EN0 и clock/reset checks — все true.

Обе64B копии непустые и одинаковые, SHA256 `deaf04c7eb5a82f9d2b2280d0d7a7be50e7bc968679761fa50df95c553f0cfda`. [Decoder](../verification/v2-progress-identity/physical-01/build/v6p-board-01/150000/progress-decoded.json) — **VALID_WITH_LIMITS**, errors/warnings пусты. Raw64 имеет FROZEN, generation3/тот же nonce, close kindQUEUE/primary1. Значения:

| Поле первого закрытия | Сохранённое значение |
|---|---:|
| Active elapsed | 6 184 077 cycles, номинально85,889958мс при72MHz |
| Завершённые prepare | 96 вызовов;2 246 855 cycles, номинально31,206319мс |
| Известное положительное принятие DATA в FIFO | 14 685 байт,44 callback |
| Zero-space / zero-other | 27 / 0 |
| Max no-positive interval | 699 918 cycles, номинально9,721083мс |
| TX offset/length; stage | 0/0; EMPTY, count0 |
| Queue; FIFO free | 8;201 байт |
| USB snapshot | bits15: snapshot valid, held/deferred/task-ready |

Связка readback+wire+legacy136+непустой frozen64 подтверждает устранение **P1-O2-02 для этого SI опыта на физическом уровне**. Исторические SH/O2 zero64/REWORK и отмена части O1-приёмки не изменяются.

Номинальные cycle intervals условны: опираются на source contract, root nohalt/reset факты и длительность активного опыта меньше одного оборота DWT; это не калиброванное время/WCET. Decoder закономерно сохраняет `physical_identity_verified=false` и `timing_qualified=false`: физическую цепочку свидетельств рассматривает этот review, сам decoder её не удостоверяет. Prepare включает IRQ/observer work; положительные FIFO bytes не равны доставленным sample/frame/prefix.64 закрывается до drain, поэтому не следует приписывать ему финальный wire prefix. Сочетание q8/EMPTY/FIFO201 не выделяет единственную причину переполнения. Сравнение12 DATA SI с20 DATA SH не является тестом эффективности late grant: в SH observer ошибочно не работал.

## Оценка по quality-gate

| Критерий | Физические150k | Диагностическое исправление | Основание |
|---|---:|---:|---|
| C1,30% | 3,0 | 9,7 |30с не достигнуты; exact SI observer впервые физически связан и заполнен. |
| C2,20% | 4,0 | 9,5 | Queue-full прерывает поток; при этом firstcause, сохранение префикса и остановка явные. |
| C3,25% | 9,5 | 9,6 | Один точный опыт, отрицательный результат сохранён, byte/identity/chronology согласованы; физические/номинальные границы явные. |
| C4,15% | 9,0 | 9,5 | FAIL потока отделён от пригодности диагностики; наследованные подписи helper не подменяют SI/SHA-256 в выводах. |
| C5,10% | 9,5 | 9,65 | Точный архив/source/plan/readback/сырые записи позволяют продолжить без повторного опыта. |

Физический итог: `0.30×3 + 0.20×4 + 0.25×9.5 + 0.15×9 + 0.10×9.5 = 6.375`, **REWORK**. Диагностический итог: `0.30×9.7 + 0.20×9.5 + 0.25×9.6 + 0.15×9.5 + 0.10×9.65 = 9.60`, **PASS только для полученного измерительного свидетельства и исправления binding**. Новых аппаратных действий этот отчёт не разрешает.
