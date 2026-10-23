# V2-06e — промежуточное независимое заключение

**BLOCKED_EVIDENCE, score:null для общего E.** Критик `stream200_critic` не автор реализации и не использует COM/SWD/Flash. Программный кандидат S8 проверен; [Отдельный допуск точного образа и плана](v2-06e-flash-review.md) выдан с оценкой 9,605; обязательный физический опыт пока не завершён. Прежние A/C/D остаются REWORK.

Область task/coordination — точное расписание S4 с транспортом S7, 100000 отсчётов/с, один реальный Record 10 с с normal END/ACK, fresh Open/raw-wire равенством, наблюдаемым темпом 90…110k/с и frozen diagnostics flags0/poll/copy<5120 мкс. Эта физическая часть не исключена из приёмки.

Source commit `bab09184455a41ac9f552565c825ce83f029c40f`, предшествующая фиксация D `fb7a9c7`. Exact BIN S8 — 36120 байт, SHA256 `80a5ed8d064a2d0559f063d6650fb4edab078de4c233ea66ef2cb0e1ac62cf20`; ELF SHA256 `65d477b3cfae09d3bc9c05fe7a2fa2c498445b22dac9f79a2c89b1b0e5e6330e`. Образ заново восстановлен из ELF load segments и полностью совпал с BIN. MSP0x20005000, Reset0x08008759, Flash end0x08008D18; diagnostics0x20002BC4/136.

Личные результаты — [critic-source](../verification/v2-100ksps-schedule/critic-source.json), [critic-static](../verification/v2-100ksps-schedule/critic-static.json). Сверены 508 входов сборки, 112 dependencies, 32 analysis inputs, 30 objects, 3 образа, 66 freeze pins и 106 native inputs. Exact S4 step подтверждён; 21 тело runtime, whole-fit и 46 остальных patched файлов S7 сохранены. Проверен точный состав извлечённых runtime bodies в native-модели, повторно выполнен `build/v6e-native-schedule-02/model.exe`, повторён exact static analyzer в Python `-I -B`.

Модель исполняет реальные тела runtime и epoch metadata с явно логическими ADC/core/USB callbacks. Подтверждены одно ADC обслуживание, RX Stop перед TX, ADC fault вместе с pending Stop, epoch loss внутри ADC/task/TX/flush, failed Stop без cleanup receipt/CTR, шесть TIME barriers, known-zero whole-fit и сохранение уже принятых байтов. Это не полное исполнение ADC/USB/core и не измерение времени. Промежуточный native-schedule-01 отказ сохранён: precheck ошибочно требовал неиспользуемый скопированный header в compiler receipt; C-код тогда ещё не запускался.

Static stack bound 5924/aligned5928 при резерве8192; data128+bss11212+reserve8192=19532 из20480 байт. Реальный high-water/WCET не измерен. Свежий64KiB backup лично совпал с восстановленным S4 из D, SHA256 `95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e`.

Уменьшение числа TIME/MMIO операций — обоснование гипотезы, не доказательство устранения queue-full. Реже выполняемое ADC обслуживание сохраняет driver deadline/ownership/flags и исходные TIME/epoch/lifecycle барьеры, но фактическая достаточность расписания ещё неизвестна. Host и пакет v6dw2 не менялись; их повторные проверки не требовались. Следующий шаг — один опыт по допущенному точному плану и заранее закреплённым критериям. До его результата общий E не принят.
