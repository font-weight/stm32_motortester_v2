# V2-06s / S2 — допуск точного плана SL

28.10.2026. **PASS — 9,60/10 для ограниченного аппаратного плана**, при
соблюдении условий ниже. Независимый критик `stream200_critic` не автор
helpers/firmware и не аппаратный оператор. Это допуск одного опыта,
**не результат опыта и не приёмка устойчивых150k**. P1-M2-01 остаётся OPEN.

## Точные входы

- Source commit: `695efd95e7c4ba72bfa6fb5fb511b85186be6266`.
- [План](../verification/v2-postcopy-handoff/plan-01/build/v6s-board-01/plan.json):
  SHA `477b133fe1a2e7924e7414f2a7a9b38f469b70ebdee19650b0193df7a616bf0e`.
- [Архив плана](../verification/v2-postcopy-handoff/plan-01/manifest.json):
  SHA `cd5ad2a9bc4cce46d548ba7ce5acff682b54dfde3ad9b6dfdcb49349a4c2a149`.
- Принятый [S1](v2-06s-source-review.md):9,60; critic-source SHA
  `be611e772c391319df1fcd123a4784ca981d78db67e82ec6e5e3a57fcfdc0bc7`.
- SL/0x5632534c: BIN49532/0xc17c,
  SHA `f82311cde2ce0a3e735543006b2bc7890e8761434c73e7adc7fa332f86cb8cb2`.
  ELF `3034a77fa007f872f32ff145b58f39f21e2e3d62d79919eb7505d05d3c1313db`.
- Резерв текущей SK:65536 байт,
  SHA `7aca301f54bddd10fb711152fc636c22b8dda1823ac71f116f8902387d6fde50`;
  первые46820 байт равны известному SK/BIN
  `dd6e8322488a1d4ada50c2c722820f971b4b4782c303bdafb1410180e2efc8f1`.

## Проверенная дельта

Лично прочитаны plan, program/run/read-closed helpers, их изменения отR,
decoder/register-check delta и сохранённые backup/preflight logs. Пассивно
сверены **17 архивных пар /152250 байт**, все28 execution_inputs, CLI SHA,
helper origin/final pins, candidate size/readback range и резервный префикс.
Все совпали. Source/native/ARM/host tests не повторялись; COM/SWD не выполнялись.

Пакет Windows изL остаётся прежним: [его отдельная приёмка](v2-06l-flash-review.md)
package9,62 сохраняется. Повторно проверены только хеши ZIP
`436cdaf1f27322e8ff7e90809f6c091950edcf7a599a97766c128c6e19a6dbfe`,
EXE `582cb37eb508746953b7200c2955aff5fb62b4263b6c734fdb7495e09a404e37`
и build report `6f9f22d27664d5a0a726c240eeaff751eb1f7d6b57cd7e3afea47752a3f729ac`.
Pinned capture/wire/storage не изменились; S добавляет только offline
диагностическую identity. Пакет не объявляется повторно испытанным с платойSL.

Root обновил свежесть перед исполнением: inventory17:18:53UTC показывает
ожидаемый COM6/code0, оба USB-устройства и owners=[]; HOTPLUG-only read
17:19:40UTC сохранил `flash-ready-64k.bin`, лично побайтно сверенный с резервом.
Лог подтверждает SN57005400120000393333574E, ID0x410,3,2В. Фактические argv
содержат только Dump, без Reset/Flash/COM. Verified receipt SHA
`055ac030113a5b805d4814ffe5d433243161af5b555195e43025d2d388710703`;
его `identity_log_sha256` относится к raw `flash-ready-probe.stdout.bin`
(`c01e871731343b7b2ff53efcef9f8bf3d0e910f9fe60589dd5729138561fa28c`),
а не к декодированному текстовому `.log`. Эти новые операторские свидетельства
добавляют свежесть, не меняют закреплённый17-file plan archive.

## Условия исполнения

1. Root — единственный аппаратный владелец. До записи сохранить актуальные
   expected COM/probe и отсутствие владельцев захвата; PA0 пуст, плата питается
   только своим USB, согласованная проводка неизменна. При изменении устройств
   или pins остановить исполнение этого плана.
2. Ровно одна запись SL с verify, затем независимый Dump всех49532 байт и
   полное равенство; только после него один Reset/Run. Helper требует этот
   plan SHA и PASS>=9,5, проверяет все execution_inputs и запрещает повтор.
   Ошибка/неоднозначный исход не разрешает автоматический повтор.
3. **После SL Reset нужен новый фактический ответ пользователя** о холодном
   цикле обоих USB: отключены10с, сначала USB платы, через5с ST-Link. Старое
   SK «готово» не подходит. Root сохраняет хронологию и запись ответа с hash
   нового reset.log; перед COM снова ожидаемый PNP/code0 и owners=[].
   Timestamp/физическое выполнение подтверждает оператор, одного boolean
   `actual_user_reply` в helper для этого недостаточно.
4. Единственный START: mode5/150000/retained10/DATA1024, запрос Record30с,
   exact SL/CAPS и fresh nonce после discovery. Нет50/100, дополнительных
   START/Reset, автоматического rollback или «исправления» неудачного префикса.
5. Пока COM активен — никакого SWD/halt. Только после явного owner-close и
   offline coherent END/STOP/ACK с правильными identity/CRC разрешены две
   независимые копии136/64/24 и stopped TIM3/ADC/DMA/RCC. ADC_DR исключён:
   ADC block начинается0x40012408, длина12. Адреса136/64/24 точно
   `0x20002f1c /0x20002fa4 /0x20002fe4`. При отсутствии terminal evidence
   автоматический read-closed путь не применять.
6. Сохранить все отказы и исходные байты. Диагностический VALID_WITH_LIMITS,
   historical/APPLICABLE0/CAP и поздний64 не доказывают причину отказа или
   same episode. Для физического PASS нужны полные30с без fault/gap и
   согласованные wire/raw/Open/END/ACK/stopped; software score это не заменяет.

Ручные условия свежести, отсутствия SWD в активном сеансе и реального
переподключения должны подтверждаться журналом root; helpers не наблюдают
проводку и не могут доказать эти факты сами. Новый аппаратный результат
подлежит отдельному независимому ревью.

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% | 9,70 | Exact image/plan/identity и единственный нужный режим согласованы. |
| C2,20% | 9,50 | Полный резерв/readback, fail-stop, owner-close gates; ручные физические условия явно обязательны. |
| C3,25% | 9,60 | Личная byte/hash сверка, свежий read-only резерв и прошлые приёмки; нового опыта ещё нет. |
| C4,15% | 9,40 | Компактная дельта проверенных helpers; часть гарантий зависит от операторской хронологии. |
| C5,10% | 9,80 | Exact argv/pins/архив/отдельный ответ пользователя и сохранение всех отказов. |

Взвешенный итог **9,60**. Блокеров точного плана не найдено; условия выше
не являются утверждениями об уже выполненных Flash/START.
