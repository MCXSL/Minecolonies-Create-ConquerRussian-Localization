# Перевод квестов FTB Quests

Скрипт `translate_ftb_quests.py` автоматически переводит текст квестов сборки **MineColonies - Create & Conquer** с английского на русский через [Google Translate](https://pypi.org/project/deep-translator/) (библиотека `deep-translator`).

Работает с файлами SNBT в папке `config/ftbquests/quests/`.

## Что переводится

Скрипт обрабатывает **все `.snbt` файлы** в каталоге квестов:

- главы (`chapters/`) — 35 файлов;
- таблицы наград (`reward_tables/`) — 44 файла;
- `chapter_groups.snbt`, `data.snbt`.

Переводятся поля:

| Поле | Где встречается |
|------|-----------------|
| `title` | квесты, главы, задачи, награды, таблицы наград |
| `subtitle` | квесты |
| `lock_message` | настройки |
| `description` | все строки внутри массива описания |

## Что сохраняется без перевода

- Minecraft-форматирование: `&l`, `&r`, `&#D2691E` и т.д.;
- служебные токены FTB: `{@pagebreak}`;
- названия модов и сборки (MineColonies, Create and Conquer, Ars Nouveau, JEI и др.);
- ники разработчиков в титрах;
- строки без букв (пробелы, декоративные линии);
- строки, состоящие только из ников.

## Требования

- **Python 3.10+**
- доступ в интернет (запросы к Google Translate)
- зависимости из `requirements-translate.txt`

## Установка
Закинуть `translate_ftb_quests.py` и `requirements-translate.txt` в `.\MineColonies - Create & Conquer\scripts`

Из корня папки сборки:

```powershell
cd "d:\work\MineColonies - Create & Conquer"
pip install -r scripts/requirements-translate.txt
```

## Быстрый старт

```powershell
# 1. Посмотреть статистику без изменений
python scripts/translate_ftb_quests.py --dry-run

# 2. Полный перевод (создаст резервную копию)
python scripts/translate_ftb_quests.py

# 3. Перевести только одну главу (для проверки)
python scripts/translate_ftb_quests.py --only getting_started
```

Полный перевод занимает **~15–25 минут** (~4700 уникальных строк).

## Резервная копия и кэш

| Файл / папка | Назначение |
|--------------|------------|
| `config/ftbquests/quests_backup_en/` | Оригинальные английские SNBT (создаётся один раз перед первым переводом) |
| `scripts/ftb_quests_translation_cache.json` | Кэш переводов — повторный запуск не переводит уже известные строки |

Резервная копия **не перезаписывается**, если папка уже существует. Чтобы сделать новый бэкап, удалите `quests_backup_en` вручную перед запуском.

## Все параметры

```
python scripts/translate_ftb_quests.py [опции]
```

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `--quests-dir` | `config/ftbquests/quests` | Папка с квестами |
| `--source-lang` | `en` | Исходный язык |
| `--target-lang` | `ru` | Целевой язык |
| `--cache-file` | `scripts/ftb_quests_translation_cache.json` | Файл кэша |
| `--backup-dir` | `config/ftbquests/quests_backup_en` | Папка резервной копии |
| `--no-backup` | — | Не создавать бэкап |
| `--dry-run` | — | Только статистика, файлы не меняются |
| `--verify-only` | — | Проверить, что все строки переведены (через кэш) |
| `--only TEXT` | — | Обработать только файлы, в имени которых есть `TEXT` |
| `--repair` | — | Исправить битые плейсхолдеры `⟦...⟧` из бэкапа |
| `--refresh-from-backup` | — | Доперевести строки, совпадающие с английским бэкапом |
| `--delay` | `0.15` | Пауза между запросами к переводчику (сек) |
| `--max-retries` | `5` | Число повторов при сетевой ошибке |

## Примеры

```powershell
# Перевести только главу MineColonies
python scripts/translate_ftb_quests.py --only minecolonies

# Перевод без создания бэкапа (если он уже есть)
python scripts/translate_ftb_quests.py --no-backup

# Проверка покрытия перевода
python scripts/translate_ftb_quests.py --verify-only

# Исправить строки с битыми ⟦ТОК0⟧ после сбоя
python scripts/translate_ftb_quests.py --repair

# Доперевести строки, которые остались на английском
python scripts/translate_ftb_quests.py --refresh-from-backup

# Медленнее, но стабильнее при блокировках Google
python scripts/translate_ftb_quests.py --delay 0.5 --max-retries 8
```

## Как работает перевод

1. Скрипт находит все строковые значения в SNBT-файлах.
2. Текст разбивается на сегменты: коды форматирования и названия модов **не отправляются** в переводчик.
3. Каждый сегмент переводится отдельно и собирается обратно.
4. Результат записывается в исходные файлы с сохранением структуры SNBT.

Автоматический перевод **не идеален**: возможны смешанные EN/RU фразы, особенно в длинных описаниях. Для финальной вычитки используйте `--only` по главам.

## Восстановление и откат

### Вернуть английский полностью

Скопируйте содержимое `config/ftbquests/quests_backup_en/` обратно в `config/ftbquests/quests/`.

### Исправить битые плейсхолдеры

Если в тексте квестов появились артефакты вида `⟦ТОК0⟧` (ошибка старых версий скрипта):

```powershell
python scripts/translate_ftb_quests.py --repair
python scripts/translate_ftb_quests.py --refresh-from-backup
```

Для `--repair` и `--refresh-from-backup` нужна папка `quests_backup_en`.

### Сбросить кэш

Удалите `scripts/ftb_quests_translation_cache.json` — при следующем запуске все строки будут переведены заново.

## Структура файлов

```
scripts/
├── translate_ftb_quests.py          # основной скрипт
├── requirements-translate.txt       # зависимости Python
├── ftb_quests_translation_cache.json   # кэш (создаётся автоматически)
└── README-translate-ftb-quests.md   # эта инструкция

config/ftbquests/
├── quests/                          # переводимые файлы
└── quests_backup_en/                # резервная копия (создаётся автоматически)
```

## Возможные проблемы

| Проблема | Решение |
|----------|---------|
| `pip install` не находит пакет | Обновите pip: `python -m pip install --upgrade pip` |
| Ошибки сети / пустой ответ переводчика | Увеличьте `--delay` и `--max-retries`, запустите снова |
| Часть строк осталась на английском | `--refresh-from-backup` |
| В тексте `⟦ТОК...⟧` | `--repair` |
| Нужен только один файл | `--only имя_файла` |
| Скрипт не меняет файлы | Убедитесь, что не указан `--dry-run` |

## Ограничения

- Перевод через бесплатный Google Translate: возможны лимиты и блокировки при частых запросах.
- ID квестов, предметов, команды и технические поля SNBT **не изменяются**.
- Качество перевода зависит от контекста; названия боссов и предметов могут переводиться частично.

## Лицензия и использование

Скрипт предназначен для локализации квестов этой сборки. При использовании в других модпаках проверьте структуру SNBT — она может отличаться.
