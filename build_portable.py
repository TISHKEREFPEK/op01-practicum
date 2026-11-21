"""Build a local Windows x64 demo from the pinned official CPython archive."""
import argparse
import hashlib
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
RUNTIME_URL = "https://www.python.org/ftp/python/3.14.9/python-3.14.9-embed-amd64.zip"
RUNTIME_SHA256 = "3c01d7cfc666f746a6f064f60fb2156ab0ec464d3d738ab796371a46a9bb24a2"
SOURCE_FILES = (
    "Start.cmd", "README.md", "course.json", "index.html", "app.js", "style.css",
    "progress.html", "progress.js", "server.py", "storage.py", "reports.py", "classroom.py", "roster.py",
    "requirements-postgres.txt", "migrate_progress.py", "Caddyfile.example",
    "labs.py", "linux_sim.py", "system_labs.py", "archive_labs.py", "installer_lab.py", "bash_lab.py",
)
START_TEXT = """Практикум ОП01 для Windows x64

1. Распакуйте весь архив в папку, в которую можете записывать файлы.
2. Дважды щёлкните Start.cmd. В браузере откроется практикум.
3. Укажите имя учебного профиля. Слева выберите практическую работу.
4. Для проверки результатов откройте «Сводка преподавателя».
5. После занятия закройте окно Start.cmd. При следующем запуске
   откройте тот же учебный профиль.

Для запуска подходят установленный браузер и файлы из этого архива.
Прогресс хранится в файле progress.sqlite3 в папке приложения.
Чтобы перенести прогресс, закройте приложение и скопируйте этот файл.
Сценарий первого показа преподавателю описан в README.md.
"""


def build(output, downloaded=None):
    if downloaded:
        payload = downloaded.read_bytes()
    else:
        with urlopen(RUNTIME_URL, timeout=60) as response:
            payload = response.read(20 * 1024 * 1024)
    if hashlib.sha256(payload).hexdigest() != RUNTIME_SHA256:
        raise ValueError("Контрольная сумма архива Python отличается от опубликованной.")
    with ZipFile(BytesIO(payload)) as runtime, NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            with ZipFile(stream, "w", compression=ZIP_DEFLATED) as bundle:
                for name in SOURCE_FILES:
                    bundle.write(ROOT / name, name)
                bundle.writestr("Запуск.txt", START_TEXT.encode("utf-8-sig"))
                for name in runtime.namelist():
                    if name.endswith("/"):
                        continue
                    data = runtime.read(name)
                    if name == "python314._pth":
                        data += b"\r\n..\r\n"
                    bundle.writestr(f"runtime/{name}", data)
            stream.close()
            pending.replace(output)
        finally:
            pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT.parent / "OP01-Windows-x64.zip")
    parser.add_argument("--python-archive", type=Path)
    args = parser.parse_args()
    build(args.output.resolve(), args.python_archive)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
