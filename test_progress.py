from concurrent.futures import ThreadPoolExecutor
import csv
from io import StringIO
import json
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from classroom import Classroom, account, read_roster, write_roster
from server import COURSE, LABS, WINDOWS_LATER, ClassroomHTTPServer, Handler, connect, initialize


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "progress.sqlite3"
        self.start_server()
        self.addCleanup(self.stop_server)

    def start_server(self):
        initialize(self.database)
        self.server = ClassroomHTTPServer(("127.0.0.1", 0), Handler)
        self.server.database = self.database
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, path, data=None):
        address = f"http://127.0.0.1:{self.server.server_port}{path}"
        if data is not None:
            address = Request(address, json.dumps(data).encode(), {"Content-Type": "application/json"})
        with urlopen(address, timeout=5) as response:
            return json.load(response)

    def test_classroom_rejects_other_profiles_and_protects_teacher_report(self):
        secret = secrets.token_urlsafe()
        roster = {
            "student-a": account(secret, "student"),
            "student-b": account(secret, "student"),
            "teacher": account(secret, "teacher"),
        }
        file = Path(self.temp.name) / "roster.json"
        write_roster(file, roster)
        self.assertNotIn(secret, file.read_text(encoding="utf-8"))
        self.server.classroom = Classroom(read_roster(file))
        base = f"http://127.0.0.1:{self.server.server_port}"

        def call(path, data=None, cookie=None):
            headers = {"Content-Type": "application/json"} if data is not None else {}
            if cookie:
                headers["Cookie"] = cookie
            target = Request(base + path, None if data is None else json.dumps(data).encode(), headers)
            with urlopen(target, timeout=5) as response:
                return json.load(response), response.headers

        def login(name):
            body, headers = call("/api/login", {"login": name, "password": secret})
            self.assertEqual(body["profile"], name)
            cookie = headers["Set-Cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn("Secure", cookie)
            return cookie.split(";")[0]

        with self.assertRaises(HTTPError) as error:
            call("/api/progress?profile=student-a")
        self.assertEqual(error.exception.code, 401)
        with self.assertRaises(HTTPError) as error:
            call("/api/login", {"login": "student-a", "password": "wrong"})
        self.assertEqual(error.exception.code, 401)
        student = login("student-a")
        lesson = "machine-inventory"
        call("/api/draft", {"lesson": lesson, "answers": {"ram": "16"}}, student)
        self.assertEqual(call("/api/progress", cookie=student)[0][lesson]["answers"], {"ram": "16"})
        with self.assertRaises(HTTPError) as error:
            call("/api/progress?profile=student-b", cookie=student)
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            call("/api/draft", {"profile": "student-b", "lesson": lesson, "answers": {}}, student)
        self.assertEqual(error.exception.code, 403)
        for report in ("/progress", "/api/summary", "/progress.csv"):
            with self.assertRaises(HTTPError) as error:
                call(report, cookie=student)
            self.assertEqual(error.exception.code, 403)
        teacher = login("teacher")
        result = call("/api/summary", cookie=teacher)[0]
        self.assertEqual([item["name"] for item in result["profiles"]], ["student-a", "student-b"])
        self.assertEqual(result["profiles"][1]["work"], {})
        call("/api/logout", {}, student)
        with self.assertRaises(HTTPError) as error:
            call("/api/progress", cookie=student)
        self.assertEqual(error.exception.code, 401)

    def test_classroom_accepts_simultaneous_valid_logins(self):
        password = secrets.token_urlsafe()
        roster = {f"student-{number}": account(password, "student") for number in range(12)}
        classroom = Classroom(roster)
        ready = threading.Barrier(len(roster), timeout=5)

        def sign_in(name):
            ready.wait()
            return classroom.identity(classroom.sign_in(name, password))

        with ThreadPoolExecutor(max_workers=len(roster)) as pool:
            identities = list(pool.map(sign_in, roster))
        self.assertEqual([item["profile"] for item in identities], list(roster))

    def test_teacher_summary_combines_drafts_machine_activity_and_checks(self):
        self.assertEqual(self.request("/api/summary")["profiles"], [])
        lab = "machine-inventory"
        active = {"lesson": lab, "profile": "-student-b"}
        self.assertTrue(self.request("/api/terminal", {**active, "command": "lscpu"})["started"])
        self.assertEqual(self.request("/api/progress?profile=-student-b")[lab]["attempts"], 0)
        saved = {"lesson": lab, "profile": "student-a", "answers": {"ram": "16"}}
        self.request("/api/draft", saved)
        self.request("/api/check", saved)
        saved["answers"].update(model="Intel Core i5-10400", threads="8", disk="512",
                                gpu="Intel UHD Graphics 630", bottleneck="ram")
        self.request("/api/check", saved)
        self.stop_server()
        self.start_server()
        data = self.request("/api/summary")
        self.assertEqual(len(data["lessons"]), 12)
        profiles = {item["name"]: item["work"] for item in data["profiles"]}
        self.assertEqual(profiles["student-a"][lab], {"status": "passed", "passed": 6, "total": 6, "attempts": 2})
        self.assertEqual(profiles["-student-b"][lab], {"status": "started", "passed": 0, "total": 0, "attempts": 0})
        uri = f"http://127.0.0.1:{self.server.server_port}/progress.csv"
        with urlopen(uri, timeout=5) as response:
            self.assertIn("attachment", response.headers["Content-Disposition"])
            rows = list(csv.DictReader(StringIO(response.read().decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(rows), 24)
        self.assertTrue(any(r["Профиль"] == "'-student-b" and r["Статус"] == "В работе" for r in rows))
        self.assertTrue(any(r["Профиль"] == "student-a" and r["Попыток"] == "2" for r in rows))

    def test_catalogue_covers_all_active_linux_work_and_inventory_still_checks(self):
        lessons = [lesson for section in COURSE["sections"] for lesson in section["lessons"]]
        self.assertEqual(len(lessons), 16)
        self.assertEqual(sum(lesson["hours"] for lesson in lessons), 34)
        self.assertEqual(set(LABS), {lesson["id"] for lesson in lessons} - WINDOWS_LATER)
        scenario = {"lesson": "machine-inventory", "profile": "student-a"}
        for cmd in ("lscpu", "free -h", "lsblk", "lspci"):
            output = self.request("/api/terminal", {**scenario, "command": cmd})["output"]
            self.assertNotIn("недоступна", output)
        answers = {
            "model": "Intel Core i5-10400", "threads": "8", "ram": "16",
            "disk": "512", "gpu": "Intel UHD Graphics 630", "bottleneck": "ram",
        }
        self.assertTrue(all(r["passed"] for r in self.request("/api/check", {**scenario, "answers": answers})["results"]))

    def test_hardware_measurements_stay_with_the_lesson_and_profile(self):
        lesson = "os-and-hardware"
        request = {"lesson": lesson, "profile": "student-a"}
        answers = {
            "driver": "virtio-pci", "before": "13", "after": "9",
            "disk_read": "2048", "buffer": "smooth", "irq": "up",
        }
        # A saved result from the first exercise keeps its original key and format.
        db = connect(self.database)
        with db:
            db.execute("INSERT INTO progress VALUES (?, ?, ?, ?, ?)",
                       ("student-a", "machine-inventory", '{"ram":"16"}', None, 0))
        db.close()
        early = self.request("/api/check", {**request, "answers": answers})
        self.assertEqual(sum(result["passed"] for result in early["results"]), 1)

        def command(value, profile="student-a"):
            return self.request("/api/terminal", {**request, "profile": profile, "command": value})["output"]

        self.assertIn("virtio-pci", command("lspci -k"))
        self.assertIn("13Gi", command("free -h"))
        self.assertIn("40", command("cat /proc/interrupts"))
        command("lab-load start")
        self.request("/api/draft", {**request, "answers": answers})
        self.stop_server()
        self.start_server()
        self.assertIn("9Gi", command("free -h"))
        self.assertIn("2048", command("vmstat 1 2"))
        command("ping -c 3 192.168.10.1")
        self.assertIn("43", command("cat /proc/interrupts"))
        result = self.request("/api/check", {**request, "answers": answers})
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(all(item["passed"] for item in result["results"]))
        progress = self.request("/api/progress?profile=student-a")
        self.assertEqual(progress[lesson], {**result, "answers": answers})
        self.assertEqual(progress["machine-inventory"]["answers"], {"ram": "16"})
        self.assertEqual(self.request("/api/progress?profile=student-b"), {})
        self.assertIn("13Gi", command("free -h", profile="student-b"))
        command("lab-reset")
        self.assertIn("13Gi", command("free -h"))
        self.assertEqual(self.request("/api/progress?profile=student-a"), progress)

    def test_resource_sharing_requires_read_write_proof_for_current_permissions(self):
        request = {"lesson": "resource-sharing", "profile": "student-a"}
        answers = {**request, "answers": {"device": "/dev/sdb", "size": "8", "cause": "full"}}
        path = "/srv/course/report.txt"

        def command(value):
            return self.request("/api/terminal", {**request, "command": value})["output"]

        self.assertIn("/mnt/media", command("lsblk"))
        self.assertIn("100%", command("df -h /mnt/media"))
        self.assertEqual(command(f"sudo setfacl -m u:editor:rw,u:reader:rw {path}"), "")
        self.assertIn("0", command(f"sudo -u reader test -w {path}"))
        self.assertEqual(command(f"sudo setfacl -m u:reader:r {path}"), "")
        self.assertIn("0", command(f"sudo -u editor test -w {path}"))
        self.assertIn("0", command(f"sudo -u reader test -r {path}"))
        self.assertIn("1", command(f"sudo -u reader test -w {path}"))
        result = self.request("/api/check", answers)
        self.assertTrue(all(item["passed"] for item in result["results"]))
        command(f"sudo setfacl -m u:reader:rw {path}")
        after_change = self.request("/api/check", answers)
        self.assertFalse(after_change["results"][-1]["passed"])

    def test_accounts_require_access_tests_and_group_check_after_removal(self):
        request = {"lesson": "accounts-and-permissions", "profile": "student-a"}

        def command(value):
            return self.request("/api/terminal", {**request, "command": value})["output"]

        for value in ("sudo groupadd project", "sudo useradd -m alex", "sudo useradd -m tempuser",
                      "sudo usermod -aG project alex", "sudo chgrp project /srv/project",
                      "sudo chmod 770 /srv/project"):
            self.assertEqual(command(value), "")
        self.assertEqual(command("sudo -u alex test -w /srv/project"), "Код завершения: 0")
        self.assertEqual(command("sudo -u tempuser test -w /srv/project"), "Код завершения: 1")
        command("getent group project")
        command("sudo userdel -r tempuser")
        checked = self.request("/api/check", {**request, "answers": {}})
        self.assertEqual([r["passed"] for r in checked["results"]], [True, True, True, True, False])
        self.stop_server()
        self.start_server()
        self.assertIn(":alex", command("getent group project"))
        checked = self.request("/api/check", {**request, "answers": {}})
        self.assertTrue(all(item["passed"] for item in checked["results"]))
        command("sudo chmod 777 /srv/project")
        checked = self.request("/api/check", {**request, "answers": {}})
        self.assertFalse(checked["results"][1]["passed"])
        self.assertFalse(checked["results"][2]["passed"])

    def test_shell_checks_copy_lineage_and_process_examination(self):
        request = {"lesson": "shell-basics", "profile": "student-a"}

        def command(value):
            return self.request("/api/terminal", {**request, "command": value})["output"]

        answers = {**request, "answers": {"ip": "192.168.10.50", "package": "9.7-3"}}
        self.assertEqual(command("mkdir workspace"), "")
        self.assertEqual(command("cd workspace"), "")
        self.assertEqual(command("pwd"), "/home/student/workspace")
        command("touch source.txt")
        command("touch report.txt")
        command("sleep 300 &")
        command("kill 2048")
        checked = self.request("/api/check", answers)
        self.assertEqual([r["passed"] for r in checked["results"]],
                         [False, False, True, False, False, False])
        self.assertEqual(command("cp source.txt copy.txt"), "")
        self.assertEqual(command("mv copy.txt report.txt"), "")
        command("sleep 300 &")
        self.assertIn("2048 sleep", command("ps -o pid,comm"))
        command("kill 2048")
        command("ip -4 addr show")
        command("ping -c 3 192.168.10.1")
        command("dpkg -s coreutils")
        checked = self.request("/api/check", answers)
        self.assertTrue(all(item["passed"] for item in checked["results"]))
    def test_incident_checks_diagnosis_first_and_http_after_latest_restart(self):
        lesson = {"lesson": "incident-diagnostics", "profile": "student-a"}
        answers = {**lesson, "answers": {"cause": "port", "memory": "5"}}

        def command(value):
            return self.request("/api/terminal", {**lesson, "command": value})["output"]

        probe = "curl -I http://127.0.0.1:8080/health"
        edit = "sudo sed -i s/PORT=abc/PORT=8080/ /etc/lab-report.conf"
        restart = "sudo systemctl restart lab-report.service"
        self.assertIn("Connection refused", command(probe))
        command(edit)
        command("journalctl -u lab-report.service -n 10")
        command("free -h")
        command(restart)
        self.assertIn("200 OK", command(probe))
        result = self.request("/api/check", answers)
        self.assertEqual([r["passed"] for r in result["results"]],
                         [False, False, True, True, True, True])
        command("lab-reset")
        self.assertIn("Connection refused", command(probe))
        self.assertIn("invalid PORT", command("journalctl -u lab-report.service -n 10"))
        command("free -h")
        command(edit)
        self.assertIn("Connection refused", command(probe))
        command(restart)
        self.assertIn("200 OK", command(probe))
        self.stop_server()
        self.start_server()
        result = self.request("/api/check", answers)
        self.assertTrue(all(item["passed"] for item in result["results"]))
        command(restart)
        result = self.request("/api/check", answers)
        self.assertFalse(result["results"][-1]["passed"])

    def test_performance_checks_free_space_and_current_autostart(self):
        lesson = {"lesson": "performance", "profile": "student-a"}
        answers = {**lesson, "answers": {"before": "4", "after": "6", "method": "trim"}}

        def command(value):
            return self.request("/api/terminal", {**lesson, "command": value})["output"]

        enabled_units = "systemctl list-unit-files --state=enabled"
        self.assertIn("lab-indexer.service", command(enabled_units))
        self.assertIn("4G", command("df -h /"))
        command("sudo systemctl disable lab-indexer.service")
        self.assertNotIn("lab-indexer.service", command(enabled_units))
        self.assertIn("2.0G", command("du -sh /var/tmp/op01-cache"))
        command("rm -- /var/tmp/op01-cache/index.tmp")
        self.assertIn("6G", command("df -h /"))
        self.assertIn("ROTA", command("lsblk -d -o NAME,ROTA"))
        result = self.request("/api/check", answers)
        self.assertTrue(all(item["passed"] for item in result["results"]))
        command("sudo systemctl enable lab-indexer.service")
        result = self.request("/api/check", answers)
        self.assertFalse(result["results"][3]["passed"])
        self.assertFalse(result["results"][4]["passed"])

    def test_safety_requires_restored_file_to_be_compared(self):
        lesson = {"lesson": "system-safety", "profile": "student-a"}
        answers = {**lesson, "answers": {"pid": "742", "cause": "cache"}}

        def command(value):
            return self.request("/api/terminal", {**lesson, "command": value})["output"]

        self.assertIn("No such file", command("tar -xzf ~/backup.tar.gz -C ~/restore"))
        self.assertIn("742", command("ps -eo pid,comm,%cpu --sort=-%cpu"))
        self.assertIn("cache is full", command("journalctl -p warning -n 10"))
        self.assertIn("0", command("sudo -u analyst test -r /srv/lab/notes.txt"))
        self.assertIn("1", command("sudo -u visitor test -r /srv/lab/notes.txt"))
        command("tar -czf ~/backup.tar.gz -C /srv/lab notes.txt")
        self.assertEqual(command("tar -tzf ~/backup.tar.gz"), "notes.txt")
        command("mkdir -p ~/restore")
        command("tar -xzf ~/backup.tar.gz -C ~/restore")
        checked = self.request("/api/check", answers)
        self.assertEqual([r["passed"] for r in checked["results"]], [True, True, True, True, False])
        self.assertEqual(command("cmp /srv/lab/notes.txt ~/restore/notes.txt"), "Код завершения: 0")
        checked = self.request("/api/check", answers)
        self.assertTrue(all(r["passed"] for r in checked["results"]))


    def test_utilities_scan_log_and_archive_verification(self):
        lesson = {"lesson": "system-utilities", "profile": "student-a"}
        answers = {"alerts": "1", "used": "97", "conclusion": "disk"}

        def command(value):
            return self.request("/api/terminal", {**lesson, "command": value})["output"]

        self.assertIn("No such file", command("gzip -t ~/course.tar.gz"))
        self.assertEqual(command("tar -czf ~/course.tar.gz -C ~ materials"), "")
        self.assertIn("0", command("gzip -t ~/course.tar.gz"))
        command("mkdir -p ~/unpacked")
        command("tar -xzf ~/course.tar.gz -C ~/unpacked")
        self.assertEqual(command("diff -r ~/materials ~/unpacked/materials"), "Код завершения: 0")
        self.assertIn("FOUND", command("clamscan -r -l /home/student/scan.log /home/student/materials"))
        command("df -h /")
        result = self.request("/api/check", {**lesson, "answers": answers})
        self.assertFalse(result["results"][-1]["passed"])
        self.assertIn("Infected files: 1", command("cat ~/scan.log"))
        result = self.request("/api/check", {**lesson, "answers": answers})
        self.assertTrue(all(item["passed"] for item in result["results"]))

    def test_document_update_makes_older_archives_outdated(self):
        lesson = {"lesson": "built-in-apps", "profile": "student-a"}
        answers = {"recovery": "keep"}

        def command(value):
            return self.request("/api/terminal", {**lesson, "command": value})["output"]

        def save(text):
            return self.request("/api/document", {**lesson, "text": text})

        notes = "ОП01\nУчебная заметка"
        self.assertEqual(save(notes), {"text": notes})
        command("tar -czf ~/docs.tar.gz -C ~ docs")
        self.assertIn("docs/notes.txt", command("tar -tzf ~/docs.tar.gz"))
        command("tar -czf ~/backup.tar.gz -C ~ docs")
        command("mkdir -p ~/restore")
        command("tar -xzf ~/backup.tar.gz -C ~/restore")
        self.assertEqual(command("cmp ~/docs/control.txt ~/restore/docs/control.txt"), "Код завершения: 0")
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request("/api/document", lesson), {"text": notes})
        self.assertEqual(self.request("/api/document", {**lesson, "profile": "student-b"}), {"text": ""})
        result = self.request("/api/check", {**lesson, "answers": answers})
        self.assertTrue(all(item["passed"] for item in result["results"]))
        save("ОП01\nНовая редакция")
        result = self.request("/api/check", {**lesson, "answers": answers})
        self.assertFalse(result["results"][2]["passed"])
        self.assertFalse(result["results"][3]["passed"])


    def test_installer_resumes_and_checks_first_boot(self):
        lesson = {"lesson": "os-installation", "profile": "student-a"}

        def command(value):
            return self.request("/api/terminal", {**lesson, "command": value})

        self.assertEqual(command("installer status")["wizard"]["id"], "image")
        self.assertEqual(command("installer boot")["wizard"]["id"], "image")
        self.assertEqual(command("installer image netinst-amd64")["wizard"]["id"], "image")
        self.assertEqual(command("installer image dvd-amd64")["wizard"]["id"], "disk")
        self.assertEqual(command("installer disk vda gpt-efi-ext4")["wizard"]["id"], "disk")
        self.assertEqual(command("installer disk vdb gpt-ext4")["wizard"]["id"], "disk")
        self.assertEqual(command("installer disk vdb gpt-efi-ext4")["wizard"]["id"], "settings")
        self.stop_server()
        self.start_server()
        self.assertEqual(command("installer status")["wizard"]["id"], "settings")
        self.assertEqual(command("installer settings ru_RU.UTF-8 Europe/Moscow student")["wizard"]["id"], "install")
        self.assertEqual(command("installer install")["wizard"]["id"], "boot")
        self.assertIn("после первого запуска", command("lspci -k")["output"])
        self.assertEqual(command("installer boot")["wizard"]["title"], "Debian запущен")
        for probe in ("cat /etc/os-release", "findmnt /", "locale", "timedatectl", "whoami"):
            command(probe)
        submission = {**lesson, "answers": {"version": "13", "driver": "e1000e"}}
        self.assertFalse(self.request("/api/check", submission)["results"][1]["passed"])
        first_probe = command("lspci -k")["output"]
        self.assertIn("Kernel modules: e1000e", first_probe)
        self.assertNotIn("Kernel driver in use", first_probe)
        self.assertIn("отсутствует", command("sudo modprobe e1000")["output"])
        self.assertIn("загружен", command("sudo modprobe e1000e")["output"])
        self.assertFalse(self.request("/api/check", submission)["results"][1]["passed"])
        self.assertIn("Kernel driver in use: e1000e", command("lspci -k")["output"])
        result = self.request("/api/check", submission)
        self.assertTrue(all(item["passed"] for item in result["results"]))


    def test_bash_checks_arguments_and_does_not_reuse_runs_after_edit(self):
        lesson = {"lesson": "shell-automation", "profile": "student-a"}
        submission = {**lesson, "answers": {}}
        script = '''#!/bin/bash
directory="$1"; output="$2"
if [ -d "$directory" ]; then
  tar -czf "$output" -C "$directory" .
else
  echo "Каталог не найден"
  exit 1
fi
'''
        self.request("/api/document", {**lesson, "text": script})
        manual = self.request("/api/terminal", {**lesson, "command": "bash backup.sh materials course.tar.gz"})
        self.assertIn("Создан архив course.tar.gz", manual["output"])
        manual = self.request("/api/terminal", {**lesson, "command": "bash backup.sh absent course.tar.gz"})
        self.assertIn("Код завершения: 1", manual["output"])
        self.stop_server()
        self.start_server()
        result = self.request("/api/check", submission)
        self.assertTrue(all(item["passed"] for item in result["results"]))
        self.request("/api/document", {**lesson, "text": "tar -czf course.tar.gz materials"})
        result = self.request("/api/check", submission)
        self.assertEqual([item["passed"] for item in result["results"]], [True, False, True, False, False])
        self.request("/api/document", {**lesson, "text": 'tar -czf "$2" "$1"'})
        result = self.request("/api/check", submission)
        self.assertEqual([item["passed"] for item in result["results"]], [True, False, True, True, False])
        alternate = 'test -d "$1" && tar -czf "$2" "$1" || exit 7'
        self.request("/api/document", {**lesson, "text": alternate})
        self.request("/api/terminal", {**lesson, "command": "bash backup.sh materials course.tar.gz"})
        result = self.request("/api/check", submission)
        self.assertTrue(all(item["passed"] for item in result["results"]))


if __name__ == "__main__":
    unittest.main()
