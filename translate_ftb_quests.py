#!/usr/bin/env python3
"""
Перевод квестов FTB Quests (SNBT) для сборки MineColonies - Create & Conquer.

Переводит поля: title, subtitle, lock_message, description, а также title внутри tasks/rewards.
Сохраняет Minecraft-форматирование (&, &#RRGGBB, &l и т.д.) и токены FTB ({@pagebreak}).

Пример:
    pip install -r scripts/requirements-translate.txt
    python scripts/translate_ftb_quests.py
    python scripts/translate_ftb_quests.py --dry-run
    python scripts/translate_ftb_quests.py --repair
    python scripts/translate_ftb_quests.py --refresh-from-backup
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None  # type: ignore[misc, assignment]


TRANSLATABLE_KEYS = ("title", "subtitle", "lock_message")
DESCRIPTION_KEY = "description"
QUESTS_SUBDIR = Path("config/ftbquests/quests")
DEFAULT_CACHE = Path("scripts/ftb_quests_translation_cache.json")
DEFAULT_BACKUP = Path("config/ftbquests/quests_backup_en")

# Minecraft / FTB форматирование, которое нельзя отправлять в переводчик
FORMAT_TOKEN_RE = re.compile(
    r"(\{@[^}]+\}"  # {@pagebreak} и др.
    r"|&#[0-9A-Fa-f]{6}"  # hex-цвета
    r"|&[0-9a-zA-Z]"  # legacy-цвета и модификаторы
    r"|\n)"
)

LETTER_RE = re.compile(r"[A-Za-z\u0400-\u04FF]")
USERNAME_ONLY_RE = re.compile(r"^[A-Za-z0-9_]+$")
ENGLISH_HINT_RE = re.compile(
    r"\b(the|and|you|your|this|that|with|from|quest|chapter|craft|build)\b",
    re.IGNORECASE,
)
BROKEN_PLACEHOLDER_RE = re.compile(r"⟦[^⟧]*⟧")


@dataclass(frozen=True)
class StringSpan:
    file_path: Path
    line_index: int
    start: int
    end: int
    original: str


def parse_quoted_strings(line: str) -> list[tuple[int, int, str]]:
    """Возвращает (start, end, text) для всех SNBT-строк в строке файла."""
    results: list[tuple[int, int, str]] = []
    i = 0
    length = len(line)
    while i < length:
        if line[i] != '"':
            i += 1
            continue
        start = i
        i += 1
        chars: list[str] = []
        while i < length:
            ch = line[i]
            if ch == "\\" and i + 1 < length:
                chars.append(ch)
                chars.append(line[i + 1])
                i += 2
                continue
            if ch == '"':
                results.append((start, i + 1, "".join(chars)))
                i += 1
                break
            chars.append(ch)
            i += 1
    return results


def line_has_key(line: str, key: str) -> bool:
    return re.search(rf"(?:^|\s){re.escape(key)}:\s*", line) is not None


def extract_spans_from_file(path: Path) -> list[StringSpan]:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    spans: list[StringSpan] = []
    in_description = False

    for line_index, line in enumerate(lines):
        stripped = line.strip()

        if line_has_key(line, DESCRIPTION_KEY):
            in_description = "[" in line.split(":", 1)[1]
            for start, end, text in parse_quoted_strings(line):
                spans.append(StringSpan(path, line_index, start, end, text))
            if in_description and "]" in line.split("[", 1)[-1]:
                in_description = False
            continue

        if in_description:
            if stripped == "]":
                in_description = False
                continue
            for start, end, text in parse_quoted_strings(line):
                spans.append(StringSpan(path, line_index, start, end, text))
            continue

        if any(line_has_key(line, key) for key in TRANSLATABLE_KEYS):
            for start, end, text in parse_quoted_strings(line):
                spans.append(StringSpan(path, line_index, start, end, text))

    return spans


def discover_snbt_files(quests_dir: Path) -> list[Path]:
    if not quests_dir.exists():
        raise FileNotFoundError(f"Папка квестов не найдена: {quests_dir}")
    return sorted(quests_dir.rglob("*.snbt"))


KNOWN_DEV_MARKERS = (
    "Cuetsu",
    "Iskariot053",
    "Ogredude",
    "grimmspark123",
    "ZBGT",
    "FailoFishy",
    "GrooveypenguinX",
)

# Названия модов/сборки, которые не должны переводиться
PROTECTED_TERMS = (
    "MineColonies - Create and Conquer",
    "Minecolonies - Create and Conquer",
    "Create and Conquer",
    "MineColonies",
    "Minecolonies",
    "Create Numismatics",
    "FTB Quests",
    "Quest Shop",
    "Industrial Foregoing",
    "Applied Energistics 2",
    "Ars Nouveau",
    "Twilight Forest",
    "Blood Magic",
    "Bosses of Mass Destruction",
    "Hostile Neural Networks",
    "Sophisticated Backpacks",
    "Tom's Simple Storage",
    "Dimensional Dungeons",
    "Productive Bees",
    "Iron Chests",
    "Simple Hats",
    "Ender Dragon",
    "Nether",
    "The Nether",
    "The End",
    "GUI",
    "JEI",
    "Curio",
)

PROTECTED_TERM_RE = re.compile(
    "(" + "|".join(re.escape(term) for term in sorted(PROTECTED_TERMS, key=len, reverse=True)) + ")"
)


def has_broken_placeholders(text: str) -> bool:
    return bool(BROKEN_PLACEHOLDER_RE.search(text))


def plain_translatable_text(text: str) -> str:
    plain = FORMAT_TOKEN_RE.sub("", text)
    plain = PROTECTED_TERM_RE.sub("", plain)
    return plain.strip()


def has_translatable_letters(text: str) -> bool:
    return bool(LETTER_RE.search(text))


def is_developer_credits_line(text: str) -> bool:
    return sum(1 for marker in KNOWN_DEV_MARKERS if marker in text) >= 2


def should_translate(text: str) -> bool:
    if not text:
        return False
    if is_developer_credits_line(text):
        return False
    plain = plain_translatable_text(text)
    if not plain:
        return False
    if USERNAME_ONLY_RE.fullmatch(plain):
        return False
    return bool(LETTER_RE.search(plain))


def translatable_fragment(text: str) -> bool:
    letters_only = re.sub(r"[^A-Za-z\u0400-\u04FF]", "", text)
    return len(letters_only) >= 4


def translate_text_segment(segment: str, translate_plain) -> str:
    if not segment or not has_translatable_letters(segment):
        return segment

    parts = PROTECTED_TERM_RE.split(segment)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if part in PROTECTED_TERMS:
            out.append(part)
        elif has_translatable_letters(part) and translatable_fragment(part):
            out.append(translate_plain(part))
        else:
            out.append(part)
    return "".join(out)


def translate_preserving(text: str, translate_plain) -> str:
    if not FORMAT_TOKEN_RE.search(text):
        return translate_text_segment(text, translate_plain)

    result: list[str] = []
    last = 0
    for match in FORMAT_TOKEN_RE.finditer(text):
        if match.start() > last:
            result.append(translate_text_segment(text[last : match.start()], translate_plain))
        result.append(match.group(0))
        last = match.end()
    if last < len(text):
        result.append(translate_text_segment(text[last:], translate_plain))
    return "".join(result)


def sanitize_cache(cache: dict[str, str]) -> int:
    bad_keys = [key for key, value in cache.items() if has_broken_placeholders(value)]
    for key in bad_keys:
        del cache[key]
    return len(bad_keys)


def cache_key(text: str, source_lang: str, target_lang: str) -> str:
    payload = f"{source_lang}|{target_lang}|{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        cache = json.load(fh)
    removed = sanitize_cache(cache)
    if removed:
        save_cache(path, cache)
        print(f"Удалено битых записей из кэша: {removed}")
    return cache


def save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)


class TranslationEngine:
    def __init__(
        self,
        source_lang: str,
        target_lang: str,
        cache_path: Path,
        delay: float,
        max_retries: int,
    ) -> None:
        if GoogleTranslator is None:
            raise RuntimeError(
                "Установите зависимости: pip install -r scripts/requirements-translate.txt"
            )
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.cache_path = cache_path
        self.delay = delay
        self.max_retries = max_retries
        self.cache = load_cache(cache_path)
        self.translator = GoogleTranslator(source=source_lang, target=target_lang)
        self.failures: list[str] = []

    def translate_text(self, text: str) -> str:
        if not should_translate(text):
            return text

        key = cache_key(text, self.source_lang, self.target_lang)
        if key in self.cache:
            cached = self.cache[key]
            if has_broken_placeholders(cached):
                del self.cache[key]
            else:
                return cached

        translated = translate_preserving(text, self._translate_plain)
        self.cache[key] = translated
        return translated

    def _translate_plain(self, text: str) -> str:
        if not text.strip() or not translatable_fragment(text):
            return text
        return self._translate_with_retries(text)

    def _translate_with_retries(self, text: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = self.translator.translate(text)
                if self.delay:
                    time.sleep(self.delay)
                if not result:
                    raise RuntimeError("пустой ответ переводчика")
                return result
            except Exception as exc:  # noqa: BLE001 - хотим пережить сетевые сбои
                last_error = exc
                time.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"не удалось перевести: {text[:80]!r}") from last_error

    def translate_many(self, texts: list[str]) -> dict[str, str]:
        unique = []
        seen = set()
        for text in texts:
            if text in seen or not should_translate(text):
                continue
            seen.add(text)
            unique.append(text)

        mapping: dict[str, str] = {}
        batch_size = 25
        for offset in range(0, len(unique), batch_size):
            batch = unique[offset : offset + batch_size]
            for text in batch:
                key = cache_key(text, self.source_lang, self.target_lang)
                if key in self.cache:
                    cached = self.cache[key]
                    if has_broken_placeholders(cached):
                        del self.cache[key]
                    else:
                        mapping[text] = cached
                        continue
                try:
                    mapping[text] = self.translate_text(text)
                except Exception:
                    self.failures.append(text)
            save_cache(self.cache_path, self.cache)
            print(
                f"  переведено {min(offset + batch_size, len(unique))}/{len(unique)} уникальных строк",
                flush=True,
            )
        return mapping

    def finalize(self) -> None:
        save_cache(self.cache_path, self.cache)


def apply_translations(path: Path, spans: list[StringSpan], mapping: dict[str, str]) -> int:
    if not spans:
        return 0

    lines = path.read_text(encoding="utf-8").splitlines()
    changed = 0
    by_line: dict[int, list[StringSpan]] = {}
    for span in spans:
        by_line.setdefault(span.line_index, []).append(span)

    for line_index in sorted(by_line):
        line = lines[line_index]
        for span in sorted(by_line[line_index], key=lambda s: s.start, reverse=True):
            new_text = mapping.get(span.original, span.original)
            if new_text == span.original:
                continue
            escaped = new_text.replace("\\", "\\\\").replace('"', '\\"')
            line = line[: span.start] + '"' + escaped + '"' + line[span.end :]
            changed += 1
        lines[line_index] = line

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def backup_quests(quests_dir: Path, backup_dir: Path) -> None:
    if backup_dir.exists():
        print(f"Резервная копия уже существует: {backup_dir}")
        return
    print(f"Создаю резервную копию: {backup_dir}")
    shutil.copytree(quests_dir, backup_dir)


def verify_coverage(files: Iterable[Path]) -> list[str]:
    problems: list[str] = []
    for path in files:
        for span in extract_spans_from_file(path):
            if has_broken_placeholders(span.original):
                problems.append(f"{path}: битый плейсхолдер: {span.original[:100]}")
                continue
            if not should_translate(span.original):
                continue
            if ENGLISH_HINT_RE.search(span.original):
                problems.append(f"{path}: {span.original[:100]}")
    return problems


def repair_file(current: Path, backup: Path, engine: TranslationEngine) -> int:
    current_lines = current.read_text(encoding="utf-8").splitlines()
    backup_lines = backup.read_text(encoding="utf-8").splitlines()
    fixed = 0

    for line_index in range(min(len(current_lines), len(backup_lines))):
        if not has_broken_placeholders(current_lines[line_index]):
            continue

        cur_strings = parse_quoted_strings(current_lines[line_index])
        bak_strings = parse_quoted_strings(backup_lines[line_index])
        if not cur_strings or not bak_strings:
            continue

        line = current_lines[line_index]
        pairs = list(zip(cur_strings, bak_strings))
        if len(cur_strings) != len(bak_strings):
            pairs = [(cur_strings[0], bak_strings[0])]

        for (cstart, cend, ctext), (_, _, btext) in sorted(pairs, key=lambda item: item[0][0], reverse=True):
            if not has_broken_placeholders(ctext):
                continue
            new_text = btext
            try:
                new_text = engine.translate_text(btext)
            except Exception as exc:
                print(f"  не удалось перевести в {current.name}:{line_index + 1}: {exc}", file=sys.stderr)
            if new_text == ctext:
                continue
            escaped = new_text.replace("\\", "\\\\").replace('"', '\\"')
            line = line[:cstart] + '"' + escaped + '"' + line[cend:]
            fixed += 1

        current_lines[line_index] = line

    if fixed:
        current.write_text("\n".join(current_lines) + "\n", encoding="utf-8")
    return fixed


def repair_broken_files(
    quests_dir: Path,
    backup_dir: Path,
    engine: TranslationEngine,
) -> tuple[int, list[tuple[Path, int]]]:
    total = 0
    files_fixed: list[tuple[Path, int]] = []

    for path in discover_snbt_files(quests_dir):
        if not has_broken_placeholders(path.read_text(encoding="utf-8")):
            continue

        rel = path.relative_to(quests_dir)
        backup = backup_dir / rel
        if not backup.exists():
            print(f"Нет бэкапа для {rel}", file=sys.stderr)
            continue

        count = repair_file(path, backup, engine)
        if count:
            files_fixed.append((rel, count))
            total += count

    return total, files_fixed


def refresh_untranslated_from_backup(
    quests_dir: Path,
    backup_dir: Path,
    engine: TranslationEngine,
) -> tuple[int, list[tuple[Path, int]]]:
    """Переводит строки, которые после сбоя всё ещё совпадают с английским бэкапом."""
    total = 0
    files_fixed: list[tuple[Path, int]] = []

    for path in discover_snbt_files(quests_dir):
        rel = path.relative_to(quests_dir)
        backup = backup_dir / rel
        if not backup.exists():
            continue

        current_spans = extract_spans_from_file(path)
        backup_spans = extract_spans_from_file(backup)
        backup_by_pos = {(span.line_index, span.start): span for span in backup_spans}

        by_line: dict[int, list[StringSpan]] = {}
        replacements: dict[tuple[int, int], str] = {}

        for span in current_spans:
            key = (span.line_index, span.start)
            backup_span = backup_by_pos.get(key)
            if backup_span is None:
                continue
            if span.original != backup_span.original:
                continue
            if not should_translate(backup_span.original):
                continue
            try:
                translated = engine.translate_text(backup_span.original)
            except Exception as exc:
                print(f"  пропуск {rel}:{span.line_index + 1}: {exc}", file=sys.stderr)
                continue
            if translated == span.original:
                continue
            replacements[key] = translated
            by_line.setdefault(span.line_index, []).append(span)

        if not replacements:
            continue

        lines = path.read_text(encoding="utf-8").splitlines()
        changed = 0
        for line_index, spans in by_line.items():
            line = lines[line_index]
            for span in sorted(spans, key=lambda item: item.start, reverse=True):
                new_text = replacements[(span.line_index, span.start)]
                escaped = new_text.replace("\\", "\\\\").replace('"', '\\"')
                line = line[: span.start] + '"' + escaped + '"' + line[span.end :]
                changed += 1
            lines[line_index] = line

        if changed:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            files_fixed.append((rel, changed))
            total += changed

    return total, files_fixed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Перевод FTB Quests SNBT на русский")
    parser.add_argument(
        "--quests-dir",
        type=Path,
        default=QUESTS_SUBDIR,
        help="Папка с квестами (по умолчанию config/ftbquests/quests)",
    )
    parser.add_argument(
        "--source-lang",
        default="en",
        help="Исходный язык для Google Translate (по умолчанию en)",
    )
    parser.add_argument(
        "--target-lang",
        default="ru",
        help="Целевой язык (по умолчанию ru)",
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        default=DEFAULT_CACHE,
        help="JSON-кэш переводов",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=DEFAULT_BACKUP,
        help="Куда сохранить оригинальные SNBT перед изменением",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Не создавать резервную копию",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать статистику, файлы не менять",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Проверить, что все переводимые строки есть в кэше / переведены",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Обрабатывать только файлы, чьё имя содержит эту подстроку",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Исправить строки с битыми ⟦...⟧, переведя заново из quests_backup_en",
    )
    parser.add_argument(
        "--refresh-from-backup",
        action="store_true",
        help="Перевести строки, которые всё ещё совпадают с английским бэкапом",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Пауза между запросами к переводчику, сек",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Число повторов при ошибке перевода",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    root = Path(__file__).resolve().parent.parent
    quests_dir = (root / args.quests_dir).resolve()

    try:
        files = discover_snbt_files(quests_dir)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.only:
        files = [path for path in files if args.only in path.name]
        if not files:
            print(f"Нет файлов по фильтру --only={args.only!r}", file=sys.stderr)
            return 1

    all_spans: list[StringSpan] = []
    for path in files:
        all_spans.extend(extract_spans_from_file(path))

    translatable = [span for span in all_spans if should_translate(span.original)]
    unique_texts = sorted({span.original for span in translatable})

    print(f"Файлов SNBT: {len(files)}")
    print(f"Всего строковых полей: {len(all_spans)}")
    print(f"К переводу: {len(translatable)} вхождений, {len(unique_texts)} уникальных")

    if args.dry_run:
        print("Режим dry-run: изменения не записываются.")
        for sample in unique_texts[:5]:
            print(f"  - {sample[:120]}")
        return 0

    engine = TranslationEngine(
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        cache_path=root / args.cache_file,
        delay=args.delay,
        max_retries=args.max_retries,
    )

    if args.repair:
        backup_dir = (root / args.backup_dir).resolve()
        if not backup_dir.exists():
            print(f"Резервная копия не найдена: {backup_dir}", file=sys.stderr)
            return 1
        total, files_fixed = repair_broken_files(quests_dir, backup_dir, engine)
        engine.finalize()
        print(f"Исправлено вхождений: {total} в {len(files_fixed)} файлах")
        for rel, count in files_fixed:
            print(f"  - {rel}: {count}")
        problems = [p for p in verify_coverage(files) if "битый плейсхолдер" in p]
        if problems:
            print(f"Остались битые плейсхолдеры: {len(problems)}", file=sys.stderr)
            for item in problems[:15]:
                print(f"  - {item}", file=sys.stderr)
            return 1
        print("Все битые плейсхолдеры исправлены.")
        return 0

    if args.refresh_from_backup:
        backup_dir = (root / args.backup_dir).resolve()
        if not backup_dir.exists():
            print(f"Резервная копия не найдена: {backup_dir}", file=sys.stderr)
            return 1
        total, files_fixed = refresh_untranslated_from_backup(quests_dir, backup_dir, engine)
        engine.finalize()
        print(f"Допереведено вхождений: {total} в {len(files_fixed)} файлах")
        for rel, count in files_fixed:
            print(f"  - {rel}: {count}")
        return 0

    mapping = engine.translate_many(unique_texts)

    if args.verify_only:
        missing = [text for text in unique_texts if mapping.get(text, text) == text]
        print(f"Не переведено уникальных строк: {len(missing)}")
        for item in missing[:20]:
            print(f"  - {item[:120]}")
        engine.finalize()
        return 1 if missing else 0

    if engine.failures:
        print("Ошибки перевода:", len(engine.failures), file=sys.stderr)
        for item in engine.failures[:10]:
            print(f"  - {item[:120]}", file=sys.stderr)
        engine.finalize()
        return 1

    # Заполняем mapping для пропущенных строк
    for span in all_spans:
        mapping.setdefault(span.original, span.original)

    if not args.no_backup:
        backup_quests(quests_dir, root / args.backup_dir)

    total_changed = 0
    spans_by_file: dict[Path, list[StringSpan]] = {}
    for span in all_spans:
        spans_by_file.setdefault(span.file_path, []).append(span)

    for path in files:
        changed = apply_translations(path, spans_by_file.get(path, []), mapping)
        total_changed += changed

    problems = verify_coverage(files)
    engine.finalize()

    print(f"Изменено вхождений: {total_changed}")
    if problems:
        print(f"Предупреждение: возможно непереведённых строк: {len(problems)}", file=sys.stderr)
        for item in problems[:15]:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print("Готово: все квестовые строки обработаны.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
