# V2-06s / S1 — независимое ревью post-copy handoff SL

28.10.2026. **PASS — 9,60/10 в программной области S1.** Критик
`stream200_critic` не участвовал в реализации firmware, модели или decoder.
Приняты точные исходники SL, ARM-кандидат, сохранённая actual-C проверка
ownership/dispatch и offline SK/SL identity. Это **не допуск Flash** и не
подтверждение устойчивых150k, физического времени, GUI или Windows-пакета.
**P1-M2-01 остаётся OPEN; отрицательный R2 не переоценивается.**

## Привязка результата

Рабочая Git-база: `eaee791141c5541ce863d1cfecad854885fc680c`.
Функциональная база SK: `bc851d6ee7b16663db95acb32733cacff7a50f36`,
сохранённый `build/v6r-fw-02`. Приёмка текущего ещё не закоммиченного
результата связана с exact freeze/архивом, а не с будущим SHA коммита.

| Вход или результат | SHA-256 |
|---|---|
| [Контракт S](../streaming-postcopy-handoff.md) | `521e91d88b8234be6f8db7cbecfd79b6f4bd4c47dbb38dd871242a0d97b1b149` |
| [Freeze](../verification/v2-postcopy-handoff/production-01/build/v6s-freeze.json) | `0a0f0124e6e597791ab7f525981c12432ebf8229cf00d9ad4b8aad0f72c7bb8c` |
| [Production manifest](../verification/v2-postcopy-handoff/production-01/manifest.json) | `52d9583a07114eb7e9afb2de632a84701ffb2bab8efe1484006b933896ed7bb7` |
| BIN SL/0x5632534c, 49532 байта | `f82311cde2ce0a3e735543006b2bc7890e8761434c73e7adc7fa332f86cb8cb2` |
| ELF SL | `3034a77fa007f872f32ff145b58f39f21e2e3d62d79919eb7505d05d3c1313db` |
| ARM02 receipt | `8cbc2b57d83e8b610277de5bf41dfb6ff32a538905862481ed11f9b19fced5a9` |
| Static bound | `a5343755b375b8ead8dc6926c4ef6111680affbe2fef28efda5ca1a5371fad49` |
| Native01 result | `08bc8e0460fa4c5c5ed58fa767313bd25c2853374406de7db35bbc0c330af919` |
| Source equivalence | `8d8023083bbf47f32f8f43ba0481fdec5fce12f1cc82adf4ad629b991651be01` |
| Host identity01 result | `a9f9146a59c4e88eab9a9112d16050c9d6e6467e4a054a82dc3b81a8f27b4012` |

Область следует [task](../../task.md), [quality gate](../quality-gate.md) и
[принятому контракту](v2-06s-contract-review.md). Для V2-STR13/15/17 проверяются
явный отказ, исходные индексы, ограниченные ресурсы и сохранение протокола;
заявление о непрерывном физическом150k в S1 не входит.

## Личная проверка и вывод по коду

Выполнено только пассивное чтение C/H/patches, builder/config/diff, модели,
runner, decoder/checker, сохранённых JSON/stdout, `.su`, disassembly и ELF;
локальные Python `json/hashlib/struct` использовались для чтения/сверки.
Ни модель, ни тесты, ни сборка, ни decoder повторно не исполнялись; COM/SWD
не открывались. Все **631 пары / 5378882 байта** архива равны источникам,
размерам и SHA. Совпали62 freeze-пина,131 native input и17 host input.
Ранее в этом же ревью лично сверены34 ARM objects,121 dependency и36 analysis
inputs. Несовпадений нет.

Три strict patches связывают исходный SK с точными adapter H/C и runtime C.
Builder применяет этот слой после прежних overlays; config/common generated
header/board word/observer bind согласованы наSL. Изменение host decoder —
явный SL allowlist; старый SG default progress и обязательный gate `--build-id`
сохранены. Прежние два firmware gate-теста не повреждены.

Новый путь выбирается только для mode5/STREAMING/cached-final DATA1024 при
недостатке queue slots, без pending control/RX. Hint не заменяет actual view
или TX ticket. `acquire` получает один проверенный private512; stack receipt
связывает owner/profile/session/epoch/soft/actor, source index, half и исходный
poll stamp. До PUBLISHED или ABORTED нет RX/task/повторного ADC read.

После cached commit выполняются прежние flush и Q certificate/collect-only,
затем не более четырёх `publish_next128`. Fresh TIME/identity проверяются до
и после каждого chunk, включая последний. Deadline считается от исходного
poll origin, не обновляется во время handoff. Healthy cancellation возвращает
обычные offers; source failure сохраняет первую причину. Raw lifecycle при
ещё неизменном epoch явно запускает pending2 hard quarantine. CLOCK и
DEADLINE не подменяются transport-stale.

`handoff_consumed` и wrapper grant marker устанавливаются до fallible
barriers: выбранная возможность может дать ноль actual calls, но не разрешает
второй grant/TX в этом проходе. После разрешения pending half допускается
прежний RX, затем consumed-проход заканчивается. Следующий проход сохраняет
lifecycle fallback. Старые guarded prepared TX/final TIME/commit, N prepare,
legacy TX и Q spans сохранены. Scope восстанавливается и при отказах.

Контракт намеренно допускает store в старую очередь между precheck и
асинхронной потерей; postcheck затем закрывает владение до следующей команды,
TX или нормального END. Это observed-loss гарантия, не атомарный запрет IRQ
во время всех offers. Большой новый PRIMASK вокруг512 или fault/quiesce не введён.

## Проверенные свидетельства

**ARM02.** `.data128 + .bss12156 = 12284` байта; с reserve8192 —
20476/20480, запас4 байта, static growth0. По ELF все56 data/BSS symbols
сохранили адреса/размеры относительно SK. Адреса136/64/24:
`0x20002f1c / 0x20002fa4 / 0x20002fe4`. Board build word по offset12,
generated-header dependencies и фактическое сравнение в observer bind
подтверждаютSL. Receipt занимает **88 байт ARM stack** (block40), что
соответствует ограничению<=96; compiled memset/copy88 проверены.

Условная linked stack bound:5952 root +288 IRQ +108 exception =6348,
aligned6352 при reserve8192. Прежние предпосылки callback graph, MSP,
приоритетов/невложенности USB IRQ и exception сохраняются. Это не измеренный
stack watermark/WCET. Запас4 байта относится к static+зарезервированному
стеку; внутри stack reserve условный запас1840 байт. Новые статические
добавления без нового полного ресурсного ревью недопустимы.

**Native01 — один сохранённый запуск PASS.** Прочитаны actual model и runner:
исполняются adapter, driver read/stop, core/queue/serializer/wire/N64/G24,
извлечённые actual runtime helpers, `step` и wrapper. Три группы проверяют
q8→4→8, единственный cached final commit/flush/Q/публикацию исходных samples,
независимый packed decode/CRC, EMPTY и обычный mode1, zero/partial/oversized
unknown acceptance, late final clock, Q scope refusal/ERROR, loss после1..4
offers,3412/3413/wrap и запрет replay receipt. Проверен raw lifecycle после
consumed до actual grant и следующий fallback. 52 прочих patched sources
и30 objects сохранены; old adapter bodies и runtime после точного удаления
нового слоя совпадают сSK. Native compile/model stdout/stderr сохранены,
input_drift=[]; output не является измерением скорости.

TIME/register bus/USB/FIFO/IRQ/actor stimuli в модели логические, legacy136
и diagnostic API — synthetic setup. Actual legacy diagnostic module и PHY
не исполняются. Модель не охватывает все произвольные IRQ interleavings;
сохранённые source boundaries ограничивают вывод до заявленного контракта.

**Offline identity01 — один запуск PASS,11 адресных проверок.** Actual C24/64
SL и synthetic C136 gen3/nonce503 связаны с этим BIN/common header; archivedSK
также принят без изменения его fixture. Отвергнуты crossed SK/SL, чужие
image/nonce/generation, будущийSM и неявное использование SG default дляSL;
CLI требует build. SK decoded SHA `072d1f5f7223797101d99a12a67b62a346378eb5855f8e1e2652332f6e6b63af`
сохранён. Оба результата `VALID_WITH_LIMITS`: physical identity/timing,
same-episode и current64 causal attribution остаются false. Повтор одной
fixture в API не выдаётся за две независимые RAM-копии.

Полные команды и compiler/environment pins находятся в ARM receipt,
native result/runner и host result/argv внутри архива. У native Zig0.15.2;
host Python3.14.7 Windows. Критик не выполнял эти команды повторно.
ARM01 preflight failure сохранён: expected-build SK при configSL остановил
builder до compiler; исправление validator pin дало отдельный ARM02.
Мой первый пассивный ELF-reader ошибочно ожидал board build по offset16;
после чтения actual struct подтверждён offset12. Это исправление аудита,
не неудачная проверка продукта или изменение артефактов.

## Замечания, ограничения и оценка

Открытых P0/P1 **в принятой программной области S1** не обнаружено.
Пределы: новые TIME/USB затраты не измерены;3413мкс,6/<500 и transaction
bound1мс не расширены,500мкс не WCET; физический режим150k, ADC settling,
точность времени/напряжения и аналоговый вход не проверены. Source equality
обычных50/100 не является новым аппаратным испытанием этих профилей.
P1-M2-01 остаётся открытым для отдельного аппаратного результата.

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% | 9,70 | Ownership/disposition, source identity и consumed dispatch согласованы с exact контрактом; wire сохранён. |
| C2,20% | 9,50 | Проверены критические отказы и resource bounds; static запас4B и стоимость новых barriers требуют строгой дальнейшей дисциплины. |
| C3,25% | 9,60 | Actual C включает caller/adapter/core и отрицательные границы; logical seams и отсутствие физического времени явно ограничены. |
| C4,15% | 9,40 | Строгий отдельный слой и явный receipt; дополнительный scheduler/дублированная валидация усложняют сопровождение. |
| C5,10% | 9,80 | Exact freeze/631 byte-equal пары, команды, failure preservation, общий build ID и сохранённые SK fixtures. |

Итог без округления: `0.30*9.70 + 0.20*9.50 + 0.25*9.60 + 0.15*9.40 + 0.10*9.80 = 9.60`.
**PASS S1.** Для следующего физического действия нужен отдельный точный план
и его независимый допуск; этот отчёт сам по себе не разрешает Flash/START.
