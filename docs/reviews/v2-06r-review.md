# V2-06r / R1 — независимое ревью SK USB gate observer

27.10.2026. **PASS — 9,60/10 только для программной диагностики R1.**
Критик `stream200_critic` не автор firmware, native-модели или decoder.
Проверены точные исходники, ARM-образ, сохранённая адресная native-проверка
и offline decoder. Flash, физическая работа USB, GUI/Windows-пакет,
устойчивость150k и аналоговый вход в эту приёмку не входят.
**P1-M2-01 остаётся OPEN.** Отрицательный Q2 не переоценивается.

## Точное состояние и область

Рабочая база Git: `7bd10422091e529b1e652061207aec9a6fb6b791`.
Функциональная база SJ: `b8d72a76f623a53cea5f3fa308965ea48f852799`;
сравнение выполняется с сохранённой сборкой `build/v6q-fw-01`.
Новый результат закреплён manifest, а не незаписанным будущим commit:

| Свидетельство | SHA-256 |
|---|---|
| [Freeze R](../verification/v2-usb-gate/production-01/build/v6r-freeze.json) | `d972b9eb046abe64bcccc221319a390e3c3d225c58a16ff3885ef06d4af362cc` |
| [Production archive](../verification/v2-usb-gate/production-01/manifest.json) | `5c9fc2b9d42f4c8fce9bdd7fcd4a5721427e883acf1c064dcdb9732b41701e4f` |
| [Контракт R3](../streaming-usb-gate.md) | `c543d4adaaa2cdf9b609722ca5cb514c520ab6f71d9e539ef8f88329f8c49995` |
| BIN SK, 46820 байт | `dd6e8322488a1d4ada50c2c722820f971b4b4782c303bdafb1410180e2efc8f1` |
| ELF SK | `fa7307ac6a6c30a58e8fd54223bfa7692b8cf65417288d99e51a45b85030593f` |
| Native01 result | `d9112d935c2c54f9ab39b4160937edaa5c4a225eeebac33fed66f3ac347f72d0` |
| Decoder01 result | `4b839f20c3cd3f2963534373e4b2f21664d0248765e63dd9a0fca890a199b9d0` |

Приёмка следует текущему [task](../../task.md), [quality gate](../quality-gate.md)
и принятому [contract review](v2-06r-contract-review.md). Цель — одна24B запись
последнего наблюдавшегося перехода EP0x82 с явной историчностью/unknown,
привязка к прежним64/136 и строгий decoder. V2-STR15/17 требуют не подменять
разрывы/исходные данные и не называть диагностический результат устойчивостью.

## Что проверено лично

Выполнено только пассивное чтение исходников, diff, JSON, сохранённых журналов,
SHA-256/побайтное сравнение, разбор ELF32 и сохранённого call graph. Не запускались
компилятор, модель, decoder/checker, старые suites или аппаратные интерфейсы.

Сверены все890 пар production archive, 6442600байт; расхождений нет. Совпали
61 pin freeze, 576 ARM inputs, 121 compiler dependency, 36 analysis pins,
122 native inputs и10 decoder inputs. Лично подтверждена побайтная сохранность
51 прежнего patched source и30 compiled objects SJ. Старые
`usb_gate_model.c` и `check_usb_gate.py` побайтно равны Git HEAD; новые R-файлы
имеют отдельные имена `usb_gate_trace_model.c`/`check_usb_gate_trace.py`.

Прочитаны итоговые module/header, DCD overlay, две вставки в N64, builder,
common build binding, source-normalizer, модель и strict decoder/checker.
Проверены следующие существенные границы:

- Gate инициализируется до N ACTIVE; все поздние записи банка запрещаются
  N CLOSING. Freeze выполняется под прежним snapshot lock даже при отказе
  app scope. ISR не пишет64B bank.
- Перед overwrite xfer fields снимается старая association; serial увеличивается
  лишь после успешной публикации. Новая публикация не стирает sticky saturation,
  metadata/lifecycle invalidity. Failed submit оставляет только историю.
- Grant и другой ISR снимают applicability. Pure FINAL требует прежней
  EP82/bulk64 metadata, отсутствия RX/SETUP и неизменного backing/tuple;
  mixed handler не выдаётся за pure FINAL. ZLP и sentinel не смешиваются.
- Первая фактически вычисленная ложная ветвь отмечается прозрачным bool-helper.
  Порядок short-circuit MMIO-предикатов и прежний gated CNT read сохранён;
  age появляется только при фактическом чтении. Дополнительные metadata reads
  относятся к RAM и не перемещают endpoint selection или RX handler.
- Полный DCD и N64 восстанавливаются до прежних tokens удалением только
  перечисленных диагностических вставок. Runtime/ADC/TIME/core/queue/serializer
  сохранены. Прежние FG guards и PRIMASK полного ISR не расширяются.
  В сохранённом exact-image graph329 достижимых адресов; unguarded
  deinit/disconnect не достижимы из Reset/USB roots. Условие FSDEV ISO_ALLOC
  исключает отдельный незащищённый close path в этом образе.
- SK `0x5632534B` получен из единого generated header; board/N/gate dependencies
  включают его. Личное чтение ELF board word подтвердило SK. Actual-C binding
  включает положительный SK и отрицательный прежний SJ.

## Доказательства и пределы

[ARM02 receipt](../verification/v2-usb-gate/production-01/build/v6r-fw-02/receipt.json)
содержит exact argv/inputs GCC ARM12.3. Final status —
`BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE`. ARM01 сохранён как FAILED compile13:
новый helper обращался к lifecycle function до её объявления. Сравнение patch
01→02 подтверждает только добавление forward declaration и смещение hunk lines.
Предыдущий отказ не скрыт и не называется успешной первой сборкой.

[Native01](../verification/v2-usb-gate/production-01/build/v6r-native-01/result.json)
— один запуск Zig0.15.2 executable, три группы PASS. Исполняются actual N64/G24
и извлечённые publisher/grant/timer/continuation/PRE/POST source blocks.
Есть unknown/failed/new publication, ZLP/mixed/backing mutation, saturation,
499/500/modulo, skipped predicates, refused scope, late write suppression,
CAP/no-active и24/64 skew. PMA/register storage, DWT и legacy136 setup
синтетические; полный DCD ISR, DMA и runtime не исполняются. Native USB journal
различает общий USB base, но не отдельные ISTR/CNTR/DADDR: точные поля/порядок
закрыты отдельно прочитанной source equivalence, а не приписаны этой модели.

[Decoder01](../verification/v2-usb-gate/production-01/build/v6r-decoder-01/result.json)
— один запуск Python3.14.7,40 адресных cases PASS. Сначала использованы actual-C
24/64/136 fixtures и companion, затем явные synthetic mutations. Legacy136
сформирован моделью: legacy module не исполнялся, физическая identity не доказана.
Проверены пары/nonce/gen/build/image, невозможные tuples, sticky/sentinel/CAP,
timestamp/age65535 и отсутствие текущей причинной атрибуции. Старые progress
builds сохраняются, SK требует явной привязки; unknown future build отклоняется.

Decoder не связывает24B episode и поздний USB64 в одно атомарное событие:
HELD0 отражает возможный skew, HELD1 лишь совместим. И
`current64_causal_attribution_available`, и `same_episode_as_later64_proven`
остаются false. При invalid нет derived timing/history. CAP ограничивает
наблюдение и не объясняет последующий отказ; serial не является DATA sequence,
queued означает PMA staging, а не доставку на ПК.

## Ресурсы

Личный ELF-разбор: `.data=128`, `.bss=12156`; gate symbol ровно24байта,
object allocation NOBITS тоже24. С reserve8192 всего20476/20480байт —
**4байта свободно вне сохранённого резерва стека**, не4байта всего для стека.
Gate24 — `0x20002FE4`; прежние N64/legacy136 — `0x20002FA4`/`0x20002F1C`.
Новых private/static banks нет.

[Static bound](../verification/v2-usb-gate/production-01/build/v6r-fw-02/static-bound.json):
6196байт, aligned6200 при reserve8192; Reset5800 + USB288 + exception allowance108.
Это условный exact-image анализ при записанных interrupt/callback/boot assumptions,
не physical high-water или WCET. DWT reads, вызовы и volatile stores наблюдателя
добавляют время, включая работу вокруг frozen bank. 500мкс остаётся условием
continuation, не пределом всей IRQ. После R нет бюджета на ещё один статический
буфер без нового ресурсного решения.

## Замечания и рубрика

Открытых P0/P1 внутри программной области R1 не обнаружено. До итогового
состояния исправлены forward declaration, collision с именем старой модели,
decoder rejection невозможного OTHER PRE tuple; все фактические попытки сохранены.
Ограничения динамической модели, тесный static budget и observer effect явны,
не компенсируются количеством checks и не принимаются за аппаратный успех.

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 0,30 | 9,70 | Контракт выполнен: явная history/unknown, unchanged working predicates и identity |
| C2 | 0,20 | 9,55 | Freeze/invalidators/fail-closed и ресурсы подтверждены;4байта вне stack reserve требуют сохранения exact scope |
| C3 | 0,25 | 9,60 | Actual-C плюс source/ELF и strict decoder; synthetic boundaries отделены от отсутствующего hardware proof |
| C4 | 0,15 | 9,40 | Один небольшой bank и отдельный decoder; DCD annotations остаются сложной областью для сопровождения |
| C5 | 0,10 | 9,70 | Exact freeze/archive/argv, исходный failure и старые tests сохранены побайтно |

`0,30×9,70 + 0,20×9,55 + 0,25×9,60 + 0,15×9,40 + 0,10×9,70 = 9,60`.
Принят ограниченный программный измеритель SK. Новая установка/опыт требуют
отдельного exact-plan допуска и новой физической identity/paired evidence.
**Flash approval=false; stable150k acceptance=false; P1-M2-01 OPEN.**
