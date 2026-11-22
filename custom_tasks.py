"""Validated portable tasks that reuse the built-in teaching environments."""
import json
import re

from labs import LABS, field
from storage import execute, lock_lesson


def checked_text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{label}. Допустимо от 1 до {limit} символов.")
    value.encode("utf-8")
    return value.strip()


def available_checks(template):
    lab = LABS[template]
    return {
        **{f"field:{key}": spec["label"] for key, spec in lab["fields"].items()},
        **{f"state:{key}": label for key, label in lab.get("criteria", {}).items()},
    }


def validate_task(value):
    keys = {"version", "id", "title", "hours", "template", "steps", "checks", "questions"}
    if not isinstance(value, dict) or set(value) != keys or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Ожидается задание ОП.01 формата версии 1.")

    task_id, template, hours = value["id"], value["template"], value["hours"]
    if not isinstance(task_id, str) or not re.fullmatch(r"custom-[a-z0-9][a-z0-9-]{7,63}", task_id):
        raise ValueError("Неверный идентификатор задания.")
    if not isinstance(template, str) or template not in LABS:
        raise ValueError("Выберите доступную учебную среду.")
    if type(hours) is not int or not 1 <= hours <= 16:
        raise ValueError("Введите целое число академических часов от 1 до 16.")

    steps, checks, questions = value["steps"], value["checks"], value["questions"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise ValueError("Добавьте от 1 до 12 шагов задания.")
    steps = [checked_text(step, "Заполните шаг задания", 500) for step in steps]
    if any("\r" in step or "\n" in step for step in steps):
        raise ValueError("Укажите каждый шаг отдельным элементом списка.")
    if not isinstance(checks, list) or len(checks) > 24:
        raise ValueError("Допустимо до 24 проверок учебной среды.")
    options = available_checks(template)
    if any(not isinstance(key, str) or key not in options for key in checks) or len(set(checks)) != len(checks):
        raise ValueError("Используйте уникальные проверки выбранной среды.")
    if not isinstance(questions, list) or len(questions) > 10 or not (checks or questions):
        raise ValueError("Добавьте хотя бы одну проверку или вопрос. Допустимо до 10 вопросов.")

    clean_questions = []
    question_ids = set()
    for question in questions:
        if not isinstance(question, dict) or set(question) != {"id", "label", "answer"}:
            raise ValueError("В каждом вопросе нужны id, label и answer.")
        key = question["id"]
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", key) or key in question_ids:
            raise ValueError("Идентификаторы вопросов должны быть уникальны.")
        question_ids.add(key)
        clean_questions.append({
            "id": key,
            "label": checked_text(question["label"], "Введите текст вопроса", 150),
            "answer": checked_text(question["answer"], "Введите эталонный ответ", 150),
        })
    return {
        **value,
        "title": checked_text(value["title"], "Введите название работы", 120),
        "steps": steps,
        "questions": clean_questions,
    }


def task_lab(task):
    lab = LABS[task["template"]]
    selected = set(task["checks"])
    fields = {key: spec for key, spec in lab["fields"].items() if f"field:{key}" in selected}
    for question in task["questions"]:
        expected = " ".join(question["answer"].casefold().split())
        fields[f"question-{question['id']}"] = field(question["label"], expected)
    return {
        **lab,
        "title": "Проверка работы",
        "prompt": "Заполните ответы и проверьте результат.",
        "fields": fields,
        "criteria": {key: label for key, label in lab.get("criteria", {}).items() if f"state:{key}" in selected},
    }


def task_entry(row):
    return {"task": json.loads(row["definition"]), "revision": row["revision"]}


def stored_tasks(db):
    rows = execute(db, "SELECT definition, revision FROM custom_tasks ORDER BY id").fetchall()
    return [task_entry(row) for row in rows]


def load_task(db, task_id):
    row = execute(db, "SELECT definition, revision FROM custom_tasks WHERE id = ?", (task_id,)).fetchone()
    return task_entry(row) if row else None


class TaskConflict(ValueError):
    pass


def save_task(db, task, revision):
    task_id = task["id"]
    lock_lesson(db, "", task_id)
    previous = load_task(db, task_id)
    if previous and previous["task"] == task:
        return previous
    if revision != (previous["revision"] if previous else 0):
        raise TaskConflict("Задание уже существует или изменилось. Откройте актуальную версию перед сохранением.")
    if previous and previous["task"]["template"] != task["template"]:
        raise TaskConflict("Для смены учебной среды создайте отдельное задание.")
    revision += 1
    execute(db, """
        INSERT INTO custom_tasks(id, definition, revision) VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET definition = excluded.definition, revision = excluded.revision
        """, (task_id, json.dumps(task, ensure_ascii=False), revision))
    return {"task": task, "revision": revision}
