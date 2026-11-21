"""Read-only progress summaries for the local classroom."""
import csv
from io import StringIO
import json

from storage import execute


STATUS = {"passed": "Пройдена", "started": "В работе", "new": "Не начата"}

ACTIVITY = """
    WITH active AS (
        SELECT profile, lesson FROM progress
        UNION
        SELECT profile, lesson FROM machines WHERE state != '{}'
    )
    SELECT a.profile, a.lesson, p.answers, p.results, COALESCE(p.attempts, 0) AS attempts
      FROM active AS a
      LEFT JOIN progress AS p ON p.profile = a.profile AND p.lesson = a.lesson
"""


def records(db, profile):
    rows = execute(db, ACTIVITY + " WHERE a.profile = ?", (profile,)).fetchall()
    return {
        row["lesson"]: {
            "answers": json.loads(row["answers"]) if row["answers"] is not None else {},
            "results": json.loads(row["results"]) if row["results"] is not None else None,
            "attempts": row["attempts"],
            **({"activity_only": True} if row["answers"] is None else {}),
        }
        for row in rows
    }


def summary(db, lessons, students=None):
    work = {} if students is None else {name: {} for name in students}
    for row in execute(db, ACTIVITY).fetchall():
        if row["lesson"] not in lessons or (students is not None and row["profile"] not in students):
            continue
        checks = json.loads(row["results"]) if row["results"] is not None else []
        passed = sum(item["passed"] for item in checks)
        work.setdefault(row["profile"], {})[row["lesson"]] = {
            "status": "passed" if checks and passed == len(checks) else "started",
            "passed": passed,
            "total": len(checks),
            "attempts": row["attempts"],
        }
    return {
        "lessons": [{"id": identifier, "title": title} for identifier, title in lessons.items()],
        "profiles": [
            {"name": profile, "work": entries}
            for profile, entries in sorted(work.items(), key=lambda item: (item[0].casefold(), item[0]))
        ],
    }


def csv_cell(value):
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export_csv(data):
    stream = StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(["Профиль", "Практическая работа", "Статус", "Зачтено критериев", "Всего критериев", "Попыток"])
    for profile in data["profiles"]:
        for lesson in data["lessons"]:
            entry = profile["work"].get(lesson["id"])
            writer.writerow([
                csv_cell(profile["name"]), csv_cell(lesson["title"]),
                STATUS[entry["status"] if entry else "new"],
                entry["passed"] if entry and entry["total"] else "",
                entry["total"] if entry and entry["total"] else "",
                entry["attempts"] if entry else 0,
            ])
    return stream.getvalue().encode("utf-8-sig")
