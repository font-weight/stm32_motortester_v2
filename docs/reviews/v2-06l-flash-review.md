# V2-06l2 — Windows-пакет и допуск точного аппаратного плана

26.10.2026. Независимый критик `stream200_critic`, не автор реализации и
не оператор платы. **Пакет: PASS9,62/10. План: PASS9,5825/10**, только в
границах ниже. Физический результат V2SE ещё отсутствует. Итоговый JSON
[critic-flash.json](../verification/v2-batch1024/critic-flash.json) содержит
`status=PASS`, `score=9.5825`, точный `plan_sha256`; программирующий wrapper
проверяет эту привязку перед действием.

## Закреплённые входы

Source `67b57bfaabbf7cf9290225058f2e8bca3b0964d8`, принятый
[source verdict](v2-06l-review.md)9,6025; его JSON SHA
`64273a46b448c3d0ae92ffca849e3900da53d7f15fc53a8ac13dede057594a21`.
Здесь не повторялись source/ARM/native проверки; проверена новая дельта
пакета, плана, helpers и свежей резервной копии.

| Объект | SHA256 |
|---|---|
| `build/v6l-board-01/plan.json` |`9835d9cb1527301600e26f7f9644609c875d5188d0f08cd3279a99e880d3fdde`|
| ZIP,61201355 байт |`436cdaf1f27322e8ff7e90809f6c091950edcf7a599a97766c128c6e19a6dbfe`|
| MotortesterV2.exe |`582cb37eb508746953b7200c2955aff5fb62b4263b6c734fdb7495e09a404e37`|
| Build report |`6f9f22d27664d5a0a726c240eeaff751eb1f7d6b57cd7e3afea47752a3f729ac`|
| Source ZIP |`9fa1ce85e6677919b9d105583c317031a64f5e5276d17f3e7a035d23bf297d71`|
| V2SE BIN,42444 байта |`c1d2c5909341b010d0869f6f7a818d8dd46525bd18d6075e0dda780a9e23b9df`|
| Свежий SD backup,65536 байт |`944b29b6ab730eda7a0f3418146d5590edb1e7717c99a12fa74a0fd8bf6ba19e`|

Лично проверены26 execution pins плана и SHA CLI; backup полностью совпал
с pin, его первые39448 байт — с принятым SD
`244c3af19647ffa24d43973c1d55d24e3b5ce70c494bf781067e13aa60a2daa5`.
Прочитаны лог read-only backup, список одного probe и COM6
VID1209/PID0001, пустой список процессов. List не показывает нормальный SN
(старый ST-Link), но свежий успешный Dump явно показывает ожидаемый
`57005400120000393333574E`. Из сообщения CLI о128КиБ не делается допуск к
этой ёмкости: образ/backup ограничены принятой64КиБ областью.

Побайтно сверены15 package пар/11941253 байта
[package manifest](../verification/v2-batch1024/package-01/manifest.json),
SHA `258d7bb535556a7e88ea75d01b022dd200ea349a42140b3a5816b908ebe50c8d`,
и9 backup пар/70963 байта
[backup manifest](../verification/v2-batch1024/backup-01/manifest.json),
SHA `5acebe949aa64a215b6efee5488080d21cad074a3271d818b282301458839053`.

## Подтверждённый пакет

Один frozen запуск из перемещённой папки с кириллицей, другим cwd и
PATH=System32 завершился успешно в Windows10.0.19045/Qt windows. Лог
подтверждает clean source check, создание source ZIP и выполнение
`MotortesterV2.exe --verify-profiles`; новых прогонов критик не делал.
Лично проверены ZIP CRC, все475 ZIP файлов против relocated tree,
хеши EXE в dist/relocated, source ZIP и каждый smoke artifact.

Девять checks PASS: явный mode5/1024, discovery15/1300, exact CAPS,
блокировка выбора при подключении, запись/Stop/fresh Open/bare Open/CSV,
отказ SC/SD150 и fixed-Fs mismatch до START. Decoded wire содержит399
полных DATA1024 и последний563,largest frame1330; canonical count/CRC
проверены producer helper. Все361011 сохранённых кодов после fresh Open
сверены с синтетическим источником. CSV — count/metadata/hash и первый
шаг1/150000; не заявляется сравнение каждого CSV-кода в этом smoke.
Owners closed, real COM opens0, errors/callback errors пусты.

Критик лично просмотрел новые frozen live/open PNG: тексты, графики,
номинальные150000/6,66667мкс, квантизация и synthetic обозначение читаемы.
Остальные три PNG ошибок побайтно совпадают с ранее лично просмотренными.
Пакет принят как локальный технический Windows-кандидат. Clean-machine,
неизменённый полный legacy-suite, публичный выпуск и физический USB этим
свидетельством не подтверждены.

## Ограниченный допуск будущих действий

Разрешён **только exact plan SHA выше**: один program V2SE/build0x56325345
по0x08000000 с verify, независимый readback всех42444 байт (`0xA5CC`) и
побайтным равенством, затем Reset/Run и новый реальный ответ пользователя
о USB-переподключении перед START. Wrapper проверяет pins, размер, CLI и
отсутствие прежнего program-invocation; успешный Reset распознаёт по
`MCU Reset.`/`Application started.`. Повтор по ошибке parser не разрешён.

Первый сеанс —150k/mode5, Record30с после Preview. Только при полном PASS
допустимы50k/mode1/5с, затем100k/mode2/5с. Перед **каждым** сеансом отдельные
успешные Reset/Run и actual user replug: frozen136 одноразовый на boot.
Один START на сеанс, свежие nonce discovery/selected, точные build/CAPS.
Прежний ответ «готово» нельзя переносить на следующий сеанс.

Обязательны сохранение wire/raw/journal, полный целевой Record, грубый
темп по ПК в пределах±10%, нормальный END/STOP_ACK, индексы/sequence/CRC,
fresh Open и отсутствие source errors. Это грубая согласованность, не
калибровка часов. Для150k полный logical frame≤1335 получается из нескольких
порций read544/USB-передач;30с payload порядка5,87МБ плюс headers помещается
в16МиБ wire log. Actual длительность должна быть сохранена; DWT modulo
не даёт достоверного elapsed для интервала больше одного wrap.

До SWD root обязан подтвердить закрытие владельца: для PASS
`owners_closed=true`, для FAIL — `cleanup_finished=true` и phase closed.
Прочитаны оба reader helper: нормальный путь требует offline normal Stop;
специальный fault путь допускает чтение после reason1 END и matching ACK,
сохраняя физический FAIL. Другие ошибки не дают автоматического допуска
к диагностике через этот helper. Во время активного COM SWD/halt запрещены.

После закрытия: два136 по`0x20002F1C`, совпадающие build/nonce/generation;
для PASS flags0 и poll/copy строго меньше3413/10240/5120мкс по режиму.
Отдельные TIM3/ADC/DMA/RCC dumps подтверждают остановку и PSC/ARR47/9,
71/19 или71/9. Адреса/размеры прочитаны, ADC_DR не входит. Decoder не
приписывает136 хранение Fs: Fs подтверждается CAPS и регистрами отдельно.

При любом FAIL вся последовательность останавливается; сохраняются
неудачные данные, неизвестный произведённый хвост и установленная SE.
Автоматический retry/rollback не разрешён. Свежая SD64КиБ сохранена для
возврата только при конкретной проблеме boot/связи/остановки. Неудачный
throughput сам по себе не повод для отката. Условия пользователя — пустой
PA0, питание платы только от USB, ST-Link без питания3,3В — остаются
предпосылками опыта, не измеренным свойством по software отчёту.

Root сохраняет фактическую хронологию Reset/replug/START/close/SWD.
Сгенерированные helper поля `hardware-procedure-facts` являются заявлением
оператора; их нельзя использовать вместо реального подтверждения
пользователя и логов. При изменении условий или любого exact pin нужен
пересмотр допуска, а не применение этого PASS к другому образу.

## Рубрика и итог

| Критерий | Пакет | Допуск плана | Основание |
|---|---:|---:|---|
| C1,30% |9,65|9,60|Exact source/image/package и согласованная последовательность режимов.|
| C2,20% |9,60|9,55|Закрытие, mismatch, backup, one-shot limits и прекращение при ошибке; процедурные условия ещё предстоит исполнить.|
| C3,25% |9,60|9,60|Один frozen run с точными артефактами; явные per-session wire/diag/register критерии.|
| C4,15% |9,60|9,55|Читаемые PNG; простой порядок150→50→100, отдельный boot и конкретные operator gates.|
| C5,10% |9,65|9,60|ZIP/source/archive pins; exact plan hash проверяет wrapper.|

**Пакет PASS9,62; допуск exact плана PASS9,5825.** Общий top-level score
равен меньшему из них. P0/P1 не найдено. Критик не выполнял COM/SWD,
Flash, Reset, START, модель, GUI или повторную ARM-сборку.
Физический150k результат всё ещё **NOT_RUN на момент допуска**; после
испытания требуется отдельное фактическое ревью, без подмены FAIL этим PASS.
