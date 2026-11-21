"""Import a local SQLite snapshot into a classroom PostgreSQL database."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from classroom import read_roster, valid_profile
from labs import LABS
from storage import Postgres, connect, execute, initialize, lock_lesson


def read_snapshot(path, selected=None, renamed=None):
    pairs = {}
    ignored = set()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source, source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        tables = {row["name"] for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "progress" not in tables:
            raise ValueError("В файле отсутствует таблица прогресса ОП01.")
        for table in ("progress", "machines"):
            if table not in tables:
                continue
            for row in source.execute(f"SELECT * FROM {table}"):
                profile, lesson = row["profile"], row["lesson"]
                if selected is not None and profile != selected:
                    continue
                if not valid_profile(profile) or lesson not in LABS:
                    ignored.add((profile, lesson))
                    continue
                if table == "machines":
                    state = json.loads(row["state"])
                    if not isinstance(state, dict):
                        raise ValueError("Некорректное состояние учебной машины.")
                    if not state:
                        continue
                else:
                    answers = json.loads(row["answers"])
                    results = json.loads(row["results"]) if row["results"] is not None else None
                    if (not isinstance(answers, dict) or not isinstance(row["attempts"], int)
                            or row["attempts"] < 0 or (results is not None and
                            (not isinstance(results, list) or any(
                                not isinstance(item, dict) or not isinstance(item.get("label"), str)
                                or type(item.get("passed")) is not bool for item in results)))):
                        raise ValueError("Некорректная запись прогресса.")
                pairs.setdefault((renamed or profile, lesson), {})[table] = dict(row)
    return pairs, len(ignored)


def existing_keys(db):
    keys = set()
    for table in ("progress", "machines"):
        if execute(db, "SELECT to_regclass(?) AS relation", (table,)).fetchone()["relation"] is not None:
            keys.update((row["profile"], row["lesson"]) for row in execute(db, f"SELECT profile, lesson FROM {table}"))
    return keys


def import_progress(target, pairs, *, apply=False):
    if not apply:
        with closing(connect(target)) as db:
            conflicts = pairs.keys() & existing_keys(db)
        return len(pairs) - len(conflicts), len(conflicts)
    if not pairs:
        return 0, 0
    initialize(target)
    imported = skipped = 0
    with closing(connect(target)) as db, db:
        for (profile, lesson), rows in sorted(pairs.items()):
            lock_lesson(db, profile, lesson)
            existing = execute(db, """
                SELECT 1 FROM progress WHERE profile = ? AND lesson = ?
                UNION ALL
                SELECT 1 FROM machines WHERE profile = ? AND lesson = ?
                LIMIT 1
                """, (profile, lesson, profile, lesson)).fetchone()
            if existing:
                skipped += 1
                continue
            if "progress" in rows:
                row = rows["progress"]
                execute(db, "INSERT INTO progress VALUES (?, ?, ?, ?, ?)",
                        (profile, lesson, row["answers"], row["results"], row["attempts"]))
            if "machines" in rows:
                execute(db, "INSERT INTO machines VALUES (?, ?, ?)",
                        (profile, lesson, rows["machines"]["state"]))
            imported += 1
    return imported, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="локальный файл progress.sqlite3")
    parser.add_argument("--profile", help="импортировать один локальный профиль")
    parser.add_argument("--login", help="имя этого ученика в списке класса")
    parser.add_argument("--roster", type=Path, help="проверить принадлежность профилей к классу")
    parser.add_argument("--apply", action="store_true", help="записать результат в PostgreSQL")
    args = parser.parse_args()
    if args.profile is not None and not valid_profile(args.profile):
        parser.error("Укажите имя существующего локального профиля.")
    if args.login is not None and (args.profile is None or not valid_profile(args.login)):
        parser.error("Для --login укажите --profile и корректное имя ученика.")
    dsn = os.environ.get("OP01_POSTGRES_DSN")
    if not dsn:
        parser.error("Укажите OP01_POSTGRES_DSN для нужной базы.")
    try:
        pairs, ignored = read_snapshot(args.source, args.profile, args.login)
        if args.profile is not None and not pairs:
            parser.error("У выбранного локального профиля нет результатов и сохранённого состояния.")
        if args.roster:
            students = {name for name, row in read_roster(args.roster).items() if row["role"] == "student"}
            unknown = {name for name, _ in pairs} - students
            if unknown:
                parser.error("Профили отсутствуют в списке учеников: " + ", ".join(sorted(unknown))
                             + ". Укажите соответствие через --profile и --login.")
        imported, skipped = import_progress(Postgres(dsn), pairs, apply=args.apply)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(f"{'Перенесено' if args.apply else 'Новых'}: {imported}. "
          f"Уже есть в PostgreSQL: {skipped}. Неактуальных записей: {ignored}.")


if __name__ == "__main__":
    main()
