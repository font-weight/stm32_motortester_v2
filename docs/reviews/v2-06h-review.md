# V2-06h — независимое программное ревью раннего USB grant

**PASS, 9,61/10**, только точный программный кандидат V2SB. Дата24.10.2026. Это не допуск Flash и не подтверждение физических100k. Критик `stream200_critic` не писал реализацию/runner/модель; ранее указал границы проверки и два исправленных замечания. COM/SWD и новые сборки не использовал.

## Состояние и область

Source `8243fb3224a1e24980848a8ce02431ec41f5bd9c`, base `4c8c14727bae8715279130b05c11f7e518fd8d9a`. Функциональная база — принятый программный V2SA, `build/v6g-fw-02`; его физический G2 остаётся FAIL. Применены task V2-06h и [quality-gate](../quality-gate.md): один обычный grant после ADC/TIME/stable/loss, прежний fallback при раннем return, повторная проверка после нового IRQ до RX, без изменения FIFO/очереди/DCD6/<500us/частоты/wire/write-commit.

| Точный артефакт | SHA256 |
|---|---|
| [Freeze](../verification/v2-usb-turnover/software/v6h-freeze.json) | `7928fb9d9b436faeb00b0b1ac3d772d93d8865b797fec017d4a126eaf7b2e715` |
| [Архив59пар](../verification/v2-usb-turnover/software-evidence.json) | `160ef0446afb0a30af31b4db1b802e4606b6b9855a56c2923d27d80b2b3ae9c6` |
| BIN37224, build0x56325342 | `e7f6f07fc6a43e6b109af6e5c652db1322a0e5023e328007b2c50d303f12536e` |
| ELF | `f129421a4dfb3baf3d30dbefc0923dcdfcf6ec4ddb0e02293c0ece78fb6d14ed` |
| Actual runtime | `efadedb84e304f0c31b5c5e9bf130753d8296ac14d462f65a2d5eea1a178cc46` |
| Native result | `ca06c0fc1b263d59728a94603f33af68876f50dce3f216385efe58f6a0ed2e84` |

## Лично проверено

Полностью прочитаны runtime delta, проект, модель, runner и изменения config/builder. `grant_irq` сохраняет прежнее тело проверки clock/epoch/task/lifecycle под lock. Локальный `grant_attempted` установлен **до** вызова helper, независимо от результата, включая FRES/refusal. Wrapper fallback выполняется только если ранняя точка не достигнута; второго обновления бюджета6/500 за проход нет. После раннего IRQ новые fresh TIME/stable/loss барьеры стоят до `tud_cdc_n_read`, его неявного RX rearm и потребления команды core. Scope оставляется перед прежним cleanup; actor восстанавливается. Старые TIME-проверки не удалены, на полном пути добавлено одно наблюдение. Изменённая возможность IRQ не ослабляет последующую проверку prepared TX ticket.

Нормализация в runner сравнивает весь runtime с SA после удаления только явного нового барьера/переноса grant; helper отдельно сопоставлен со старым телом. Новые ветви прочитаны критиком независимо от нормализации. Все46 остальных patched файлов лично сверены **побайтно** с SA; TIME backend также прежний. Core partial/unknown/write/commit и DCD budget не изменены, их прежние адресные модели повторять не требовалось.

Лично проверены81freeze pins,523receipt inputs,112compiler dependencies,32analysis inputs,30objects,106native inputs,59архивных пар/1065380байт. Exact hashes/размеры/копии совпали. Повторно вычислен `check_static.analyze()` без сборки — результат совпал с сохранённым. ELF PT_LOAD восстановлен в BIN и сравнен побайтно; MSP0x20005000/reset0x08008BA9. Text37096/data128/bss11212; с8192резервом стека19532/20480, запас948. Условная граница6044/aligned6048 ниже резерва; это не измеренный стек/WCET. Legacy136 по0x20002BC4, active profile отсутствует; нового static storage нет.

Модель с точными11runtime-функциями и actual `mt_usb_epoch.c` сверена с исходниками и generated model. Выполнен **один** повтор готового `build/v6h-native-01/model.exe`: exit0, три группы PASS, stderr пустой. Проверены порядок task→ADC→grant→freshTIME→RX→prepare→TX, разные положения final-event, grant-denied/false/health refusal, максимум одна попытка, lifecycle/epoch/TIME прямо на unlock нового grant без старого RX/core/TX, восстановление scope, ранний fallback, первая причина ADC и known-zero whole-fit. Стоп в модели — логический core seam; сериализация/commit действительного core здесь не воспроизводятся и покрыты неизменённым G core. Одноразовый health refusal явно искусственный способ проверить marker, не модель sticky TIME.

Native запускает actual runtime/epoch, но USB/ADC/core/clock остаются логическими seams. CFG_MT_STREAM_DIAGNOSTICS=0 выключает legacy hooks в этой модели; их неизменённые исходники и включение в реальный ARM сверены отдельно. Модель не измеряет USB/DMA/IRQ. Единственные авторские ARM01/native01 сохранены PASS; новых компиляций критик не делал. Среда личной проверки — Windows10.0.19045, Python3.14.7; авторские toolchains ARM GNU12.3.rel1 и Zig0.15.2. Точные команды закреплены freeze/receipts. [Личные проверки](../verification/v2-usb-turnover/critic-source-checks.json).

## Закрытые замечания и ограничения

До первой компиляции исправлены пропущенное локальное объявление key в вынесенном helper и несовпадение сырых prep-байт из-за CRCRLF. Оба исправления лично подтверждены; финальные model/ARM используют точные efaded… байты. Замечания по postIRQ RX-boundary, actor и одному attempt закрыты исходником/адресной моделью. Открытых P0/P1 в этой **программной области** нет.

Подтверждённая зависимость finalIN→task→следующий grant объясняет цель изменения, но доля этой задержки в F2/G2 и достаточность исправления для100k не измерены. Если нового transfer ещё нет, раннее окно6/<500us стареет во время RX/encode/TX; второго reset нет. README/plan честно ограничивают ускорение startup/первой передачи. TX max по-прежнему исключает prepare и не сравнивается напрямую с полным TX S8/S9. Ранний архивный DRAFT-план сохранён как исторический; final freeze включает актуальные pins. Никакая из этих проверок не пересматривает отрицательные физические результаты или неизвестный хвост.

## Рубрика

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 30% | 9,6 | Один перенос grant, точные прежние guards и новый барьер, неизменные данные |
| C2 | 20% | 9,6 | Отказы/lifecycle/RX/marker и bounded память; реальные сроки отдельно |
| C3 | 25% | 9,6 | Exact source/ARM/archive и личный actual-runtime replay с явными seams |
| C4 | 15% | 9,6 | Малый delta/helper/local marker без static storage, ограничения понятны |
| C5 | 10% | 9,7 | Exact source/base/freeze/команды и сохранённые ранние замечания |

Итог до округления **9,61**: **PASS только V2-06h software candidate**. Физические100k остаются незакрытым требованием. Для следующего опыта необходим отдельный точный план и независимый допуск; этот отчёт не разрешает Flash. [Машиночитаемый итог](../verification/v2-usb-turnover/critic-source.json).
