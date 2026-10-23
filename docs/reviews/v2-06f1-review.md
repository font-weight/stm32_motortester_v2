# V2-06f1 — независимое ревью точной S9

**PASS, 9,595/10 — только диагностический программный кандидат.** Этот отчёт не разрешает Flash и не подтверждает физические100/200k. Критик `stream200_critic` не автор firmware, native-модели или decoder; изменял только собственные свидетельства/отчёт.

## Проверенное состояние

База `49cf581f1e2f53f2c5f848138fbf5e63c0c2e271`, source commit `195fbcd2f9921acab1926f7940df9e446c02c392`. Scope соответствует F1 в task: сохранённые Fs100000, ADC/transport/wire S8 и legacy ABI136; новый single-bank profile512, active-only/first-close, partials, целевой250мс с actual overshoot, без аппаратного действия.

- Freeze SHA256 `ef15775d2de9df33cb7670c0ce068a5314af778dae0e9065fb147462ce05292a`.
- BIN38924: `a28db0890aaf971895286ccfc042c883563b73a6938751267f54ff262739cab1`.
- ELF: `e27789b1bf312beab58d624d51a1fcd6182cbde189d24112ff894dac39c23ee9`.
- [Архив](../verification/v2-stream-profile/software-evidence.json): `f5947ba4dd370a4e8028abbfccbf5ded8a5666db2994ab816f65f617b31b711c`,35 пар/1735760байт.
- [Машиночитаемый итог](../verification/v2-stream-profile/critic-source.json) и [личные проверки](../verification/v2-stream-profile/critic-source-checks.json) фиксируют точные входы.

## Что проверено лично

Прочитаны profiler C/header/ABI, пять overlay hooks, normalization/order runner, actual C native модель и независимый decoder. Перепроверены финальные исправления относительно раннего [checkpoint](../verification/v2-stream-profile/critic-source-checkpoint.json); старый BLOCKED_EVIDENCE оставлен как история.

В Windows10.0.19045/Python3.14.7 выполнена read-only SHA/byte сверка60 source pins,18 freeze artifacts,520 receipt inputs,118 dependencies,31 objects,33 analysis inputs и всех35 архивных пар. Текущий `check_static.analyze(build/v6f-fw-03)` дал точное равенство сохранённому static report. Из ELF PT_LOAD восстановлен BIN, совпали все38924байта. MSP0x20005000, reset vector0x0800924D в образе; профиль0x20002C4C/512 и legacy0x20002BC4/136 подтверждены exact nm.

text38796/data128/bss11724: дополнительный static RAM ровно512; вместе с8192 резервом20044/20480, запас436байт. Условная статическая граница5996, выравнивание6000. Она не является физическим измерением стека или WCET.

Лично повторена C-token equivalence пяти изменённых S8-модулей после удаления только observer-blocks/обратного переименования wrappers/снятия boolean guard observer, сверены прочие неизменённые patched-файлы. Удаляемые блоки прочитаны отдельно: это сохраняет рабочие операции и guard order, но не их длительность. First-close order проверен в driver/core/runtime, включая fault до now и ADC fault до quiesce.

Один запуск `build/v6f-native-profile-02/model.exe NUL` дал PASS трёх групп; авторский fixture не перезаписан. Это actual profiler C с логическими seam-сценариями, не исполнение полного MCU/ADC/USB и не IRQ timing. Покрыты CLOSING/FROZEN поздние эпилоги, NO_START identity/partials, uint32 wrap/cap, FG/ISR saturation/ownership, IN invalid/final/ZLP, TX positive/zero/unknown и смена классификации.

Лично выполнен независимый decode реального512-байтного C-output в памяти с build/nonce/gen/epoch: VALID_FROZEN, issues пусты; отсутствие legacy/hardware timing facts и boundary/observer policy корректно оставили attribution=false. Две копии fixture искусственно одинаковы, не независимые SWD-чтения. Представленные decoder check-03 (четыре группы) и cross-02 связаны хешами с тем же final ABI; повтор компиляции/широкого набора не выполнялся.

## Замечания и исправления

- **F1-01 (P2), закрыто:** NO_START без ложного active elapsed/partial. Очистка ARMED tickets до CLOSING; actual C NO_START и decoder unavailable.
- **F1-02 (P2), закрыто:** Невозможная промежуточная IN geometry. Проверка кратности64/total<=384; native invalid packet и короткий final/ZLP.
- **F1-03 (P1), закрыто:** Первая ADC причина до driver quiesce. Typed ADC close после invalidate_history и до quiesce; лично прочитан hook, exact source-order witness.
- **F1-04 (P1), закрыто:** Source cause до последующего now/recovery. FAULT close после исходного cause и до now; исходные операции сохранены normalized comparison.
- **F1-05 (P2), закрыто:** Identity неудачного start. ARMED attempt сохраняет generation/nonce/epoch без ACTIVE; actual C fixture.
- **F1-06 (P2), закрыто:** Decoder отвергает неизвестные reason/state. Typed domain bounds и существующая отрицательная synthetic группа; отдельно NO_START и legacy DWT gating.

Открытых P0/P1/P2 по заявленному программному результату нет. fw01 compile failure на sign conversion/misleading indentation сохранён; fw02 был промежуточным до последних исправлений identity/cause/grant. Финальным является только fw03.

## Рубрика и пределы

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 30% | 9.6 | 512B ABI, отдельные владельцы, первичное закрытие и неизменённые рабочие операции подтверждены точными исходниками/моделью. |
| C2 | 20% | 9.6 | Поздние записи, частичные интервалы, wrap/cap, saturation и TX/IN ошибки проверены; stack остаётся условной границей, не измерением. |
| C3 | 25% | 9.6 | Exact ARM/ELF/static, адресная actual C модель, независимый decoder и лично повторённая сверка; физическое время вне области. |
| C4 | 15% | 9.5 | ABI и hooks отделены; сложность учёта времени требует сохранять описанные owner/partial ограничения. |
| C5 | 10% | 9.7 | Точные source/artifact pins, команды, byte-equal архив и сохранённые неудачные промежуточные сборки. |

Итог до округления **9,595**. Нет обязательного недостающего программного свидетельства. Отдельный физический опыт требует нового допуска точного плана/образа, readback, двух frozen records, legacy DWT и обязательного возвратаS4. Действительные observer cost, IRQ interference, реальный oscillator/stack/устойчивый темп не установлены; поэтому суммы TIME/ISR/STEP нельзя складывать как независимые долиCPU, а calibration нельзя вычитать из измерений. Надпись decoder `PINNED_DRAFT_NOT_FINAL_FREEZE` остаётся исторической; окончательная привязка ABI выполнена настоящим exact-source review, адреса не выводятся самим decoder.

Прежние отрицательные физические A/C/D/E остаются REWORK. Успешный диагностический software candidate не меняет их итог и не объявляет прибор готовым к повышенной частоте.
