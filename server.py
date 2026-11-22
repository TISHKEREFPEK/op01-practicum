"""Local OP01 classroom prototype."""
import argparse
import json
import os
import shlex
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from classroom import Classroom, cookie_header, read_roster, token_from_cookie, valid_profile
from custom_tasks import TaskConflict, available_checks, load_task, save_task, stored_tasks, task_lab, validate_task
from labs import LABS, check_answers, public_labs, run_command
from reports import export_csv, records, summary
from storage import Postgres, StorageUnavailable, execute, initialize, lock_lesson, request_database


ROOT = Path(__file__).resolve().parent
COURSE = json.loads((ROOT / "course.json").read_text(encoding="utf-8"))
WINDOWS_LATER = {"far-manager", "windows-workspace", "windows-network", "desktop-settings"}
ACTIVE_LESSONS = {
    item["id"]: item["title"] for section in COURSE["sections"] for item in section["lessons"]
    if item["id"] in LABS
}
FILES = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
    "/progress": ("progress.html", "text/html"),
    "/progress.js": ("progress.js", "text/javascript"),
    "/tasks": ("tasks.html", "text/html"),
    "/tasks.js": ("tasks.js", "text/javascript"),
    "/tasks/example.json": ("example-task.json", "application/json"),
}
TASK_POSTS = {"/api/tasks", "/api/tasks/preview"}


class ClassroomHTTPServer(ThreadingHTTPServer):
    request_queue_size = 64


def machine_state(db, profile, lesson):
    row = execute(db, "SELECT state FROM machines WHERE profile = ? AND lesson = ?",
                  (profile, lesson)).fetchone()
    return json.loads(row["state"]) if row else {}


def save_machine_state(db, profile, lesson, state):
    execute(db, """
        INSERT INTO machines(profile, lesson, state) VALUES (?, ?, ?)
        ON CONFLICT(profile, lesson) DO UPDATE SET state = excluded.state
        """, (profile, lesson, json.dumps(state)))


class Handler(BaseHTTPRequestHandler):
    def handle_one_request(self):
        try:
            super().handle_one_request()
        except StorageUnavailable as error:
            self.close_connection = True
            self.log_error("Storage request failed: %s", type(error.__cause__).__name__)
            self.reply(503, {"error": "Хранилище прогресса временно недоступно. Повторите действие через несколько секунд."})

    @property
    def classroom(self):
        return getattr(self.server, "classroom", None)

    def token(self):
        return token_from_cookie(self.headers.get("Cookie"))

    def identity(self):
        return self.classroom.identity(self.token()) if self.classroom else None

    def teacher_allowed(self):
        if not self.classroom:
            return True
        identity = self.identity()
        if identity and identity["teacher"]:
            return True
        self.reply(403, {"error": "Этот раздел доступен преподавателю."})
        return False

    def profile_for_request(self, requested):
        if not self.classroom:
            if valid_profile(requested):
                return requested
            self.reply(400, {"error": "Укажите имя учебного профиля."})
            return None
        identity = self.identity()
        if identity is None:
            self.reply(401, {"error": "Войдите в учётную запись."})
        elif requested is not None and requested != identity["profile"]:
            self.reply(403, {"error": "Доступен только ваш учебный профиль."})
        else:
            return identity["profile"]
        return None

    def reply(self, status, value, cookie=None):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_bytes(status, data, "application/json", cookie=cookie)

    def send_bytes(self, status, data, mime, attachment=None, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        if cookie is not None:
            self.send_header("Set-Cookie", cookie_header(cookie))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in ("/progress", "/api/summary", "/progress.csv", "/tasks", "/tasks/example.json", "/api/tasks") and not self.teacher_allowed():
            return
        if url.path in FILES:
            file, mime = FILES[url.path]
            self.send_bytes(200, (ROOT / file).read_bytes(), mime)
        elif url.path == "/api/course":
            with request_database(self.server.database) as db:
                tasks = [entry["task"] for entry in stored_tasks(db)]
            labs = {**LABS, **{task["id"]: task_lab(task) for task in tasks}}
            sections = list(COURSE["sections"])
            if tasks:
                lessons = [{key: task[key] for key in ("id", "title", "steps", "hours")} for task in tasks]
                sections.append({"id": "custom", "title": "Задания преподавателя", "topics": [], "lessons": lessons})
            self.reply(200, {"course": {**COURSE, "sections": sections}, "labs": public_labs(labs), "later": sorted(WINDOWS_LATER)})
        elif url.path == "/api/tasks":
            with request_database(self.server.database) as db:
                tasks = stored_tasks(db)
            templates = [{"id": key, "title": title, "checks": available_checks(key)} for key, title in ACTIVE_LESSONS.items()]
            self.reply(200, {"tasks": tasks, "templates": templates})
        elif url.path == "/api/session":
            self.reply(200, {"classroom": bool(self.classroom), "identity": self.identity()})
        elif url.path == "/api/progress":
            profile = self.profile_for_request(parse_qs(url.query).get("profile", [None])[0])
            if profile is None:
                return
            with request_database(self.server.database) as db:
                data = records(db, profile)
            self.reply(200, data)
        elif url.path in ("/api/summary", "/progress.csv"):
            with request_database(self.server.database) as db:
                custom = {entry["task"]["id"]: entry["task"]["title"] for entry in stored_tasks(db)}
                data = summary(db, {**ACTIVE_LESSONS, **custom}, self.classroom.students if self.classroom else None)
            if url.path == "/progress.csv":
                self.send_bytes(200, export_csv(data), "text/csv", attachment="op01-progress.csv")
            else:
                self.reply(200, data)
        else:
            self.reply(404, {"error": "Страница не найдена."})

    def do_POST(self):
        if self.path not in TASK_POSTS and self.path not in ("/api/terminal", "/api/draft", "/api/check", "/api/document", "/api/login", "/api/logout"):
            self.reply(404, {"error": "Страница не найдена."})
            return
        if self.path in TASK_POSTS and not self.teacher_allowed():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = 65_536 if self.path in TASK_POSTS else 16_384
            if not 0 < length <= limit or self.headers.get_content_type() != "application/json":
                raise ValueError
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError
            if self.path in TASK_POSTS:
                self.modify_task(payload)
                return
            if self.path == "/api/login":
                self.login(payload)
                return
            if self.path == "/api/logout":
                if self.classroom:
                    self.classroom.sign_out(self.token())
                self.reply(200, {"ok": True}, cookie="")
                return
            profile = self.profile_for_request(payload.get("profile"))
            if profile is None:
                return
            lesson = payload.get("lesson")
            if not isinstance(lesson, str) or len(lesson) > 71:
                raise ValueError
            lab = LABS.get(lesson)
            if lab is None and lesson.startswith("custom-"):
                with request_database(self.server.database) as db:
                    entry = load_task(db, lesson)
                if entry:
                    lab = task_lab(entry["task"])
            if lab is None:
                raise ValueError
            if self.path == "/api/terminal":
                command = payload.get("command")
                if not isinstance(command, str) or len(command) > 160:
                    raise ValueError
                command = " ".join(shlex.split(command))
                self.terminal(profile, lesson, lab, command)
                return
            if self.path == "/api/document":
                if "editor" not in lab:
                    raise ValueError
                document = payload.get("text", "")
                if not isinstance(document, str) or len(document) > 4096 or "\x00" in document:
                    raise ValueError
                with request_database(self.server.database, write="text" in payload) as db:
                    if "text" in payload:
                        lock_lesson(db, profile, lesson)
                    state = machine_state(db, profile, lesson)
                    if "text" in payload:
                        state["document"] = document
                        save_machine_state(db, profile, lesson, state)
                self.reply(200, {"text": state.get("document", "")})
                return
            answers = payload.get("answers")
            if not isinstance(answers, dict) or not set(answers) <= lab["fields"].keys():
                raise ValueError
            if any(not isinstance(value, str) or len(value) > 150 for value in answers.values()):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            self.reply(400, {"error": "Не удалось обработать запрос."})
            return
        checking = self.path == "/api/check"
        with request_database(self.server.database, write=True) as db:
            lock_lesson(db, profile, lesson)
            state = machine_state(db, profile, lesson) if checking else {}
            results = check_answers(lab, answers, state) if checking else None
            execute(db, """
                INSERT INTO progress(profile, lesson, answers, results, attempts)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile, lesson) DO UPDATE SET
                    answers = excluded.answers,
                    results = CASE WHEN excluded.attempts > 0 THEN excluded.results ELSE progress.results END,
                    attempts = progress.attempts + excluded.attempts
                """, (profile, lesson, json.dumps(answers), json.dumps(results) if checking else None, int(checking)))
            attempts = execute(db, "SELECT attempts FROM progress WHERE profile=? AND lesson=?",
                               (profile, lesson)).fetchone()["attempts"]
        self.reply(200, {"results": results, "attempts": attempts})

    def modify_task(self, payload):
        revision = payload.get("revision", 0)
        try:
            if type(revision) is not int or not 0 <= revision < 2_000_000_000:
                raise ValueError("Неверная версия задания.")
            task = validate_task(payload.get("task"))
            if self.path == "/api/tasks/preview":
                self.reply(200, {"task": task})
                return
            with request_database(self.server.database, write=True) as db:
                entry = save_task(db, task, revision)
        except TaskConflict as error:
            self.reply(409, {"error": str(error)})
        except UnicodeError:
            self.reply(400, {"error": "В задании есть недопустимые символы."})
        except ValueError as error:
            self.reply(400, {"error": str(error)})
        else:
            self.reply(200, entry)

    def login(self, payload):
        if not self.classroom:
            self.reply(404, {"error": "Для локального режима выберите имя профиля."})
            return
        try:
            token = self.classroom.sign_in(payload.get("login"), payload.get("password"))
        except TimeoutError:
            self.reply(503, {"error": "Слишком много запросов на вход. Попробуйте ещё раз через несколько секунд."})
            return
        if token is None:
            self.reply(401, {"error": "Не удалось войти. Проверьте имя и пароль."})
            return
        self.classroom.sign_out(self.token())
        self.reply(200, self.classroom.identity(token), cookie=token)

    def terminal(self, profile, lesson, lab, command):
        with request_database(self.server.database, write=True) as db:
            lock_lesson(db, profile, lesson)
            previous = machine_state(db, profile, lesson)
            current = dict(previous)
            output = run_command(lab, command, current)
            if previous != current:
                save_machine_state(db, profile, lesson, current)
        result = {"output": output, "started": bool(current)}
        if "wizard" in lab:
            result["wizard"] = lab["wizard"](current)
        self.reply(200, result)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8174)
    parser.add_argument("--database", type=Path, help="путь к локальной SQLite")
    parser.add_argument("--roster", type=Path, help="список учётных записей для режима класса")
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("OP01_POSTGRES_DSN")
    if dsn and args.database:
        parser.error("Выберите OP01_POSTGRES_DSN или --database.")
    database = Postgres(dsn) if dsn else (args.database or ROOT / "progress.sqlite3")
    try:
        classroom = Classroom(read_roster(args.roster)) if args.roster else None
    except (OSError, ValueError) as error:
        parser.error(str(error))
    initialize(database)
    with ClassroomHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.database = database
        server.classroom = classroom
        url = f"http://127.0.0.1:{server.server_port}"
        print(url, flush=True)
        if args.open_browser:
            webbrowser.open(url)
        server.serve_forever()


if __name__ == "__main__":
    main()
