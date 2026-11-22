"""Linux administration exercises with isolated simulated services and storage."""

UNIT = "lab-report.service"
CONFIG = "/etc/lab-report.conf"
URL = "http://127.0.0.1:8080/health"
INCIDENT_COMMANDS = (
    f"curl -I {URL}", f"systemctl status {UNIT}", f"journalctl -u {UNIT} -n 10",
    "free -h", f"cat {CONFIG}", f"sudo sed -i s/PORT=abc/PORT=8080/ {CONFIG}",
    f"sudo systemctl restart {UNIT}", f"sudo systemctl stop {UNIT}", "lab-reset",
)


def incident(command, state):
    edited = state.get("edited", False)
    active = state.get("active", False)
    failed = state.get("status", "failed") == "failed"
    if command == "lab-reset":
        state.clear()
        return "Восстановлена исходная конфигурация со сбоем."
    if command == f"curl -I {URL}":
        if active:
            state["http_verified"] = True
            return "HTTP/1.1 200 OK\nContent-Length: 2"
        if not edited:
            state["failure_reproduced"] = True
        return "curl: (7) Failed to connect to 127.0.0.1 port 8080: Connection refused"
    if command == f"systemctl status {UNIT}":
        status = "active (running)" if active else "failed (Result: exit-code)" if failed else "inactive (dead)"
        return f"● {UNIT} - Учебный HTTP-отчёт\n     Active: {status}"
    if command == f"journalctl -u {UNIT} -n 10":
        if not edited:
            state["log_before"] = True
        output = "lab-report[241]: invalid PORT value: abc\nsystemd[1]: lab-report.service: Failed with result 'exit-code'."
        return output + ("\nlab-report[512]: Listening on 127.0.0.1:8080" if active else "")
    if command == "free -h":
        if not edited:
            state["memory_before"] = True
        return "               total        used        free      available\nMem:           8.0Gi       2.8Gi       4.1Gi         5Gi"
    if command == f"cat {CONFIG}":
        return f"PORT={'8080' if edited else 'abc'}"
    if command == f"sudo sed -i s/PORT=abc/PORT=8080/ {CONFIG}":
        state["edited"] = True
        return ""
    if command == f"sudo systemctl restart {UNIT}":
        state.update(active=edited, status="active" if edited else "failed", http_verified=False)
        return "" if edited else f"Job for {UNIT} failed because the process exited with an error."
    if command == f"sudo systemctl stop {UNIT}":
        state.update(active=False, status="inactive", http_verified=False)
        return ""
    return None


def incident_checks(state):
    return {
        "reproduced": state.get("failure_reproduced"),
        "edited": state.get("edited"),
        "active": state.get("active"),
        "verified": state.get("http_verified") and state.get("active"),
    }


CACHE = "/var/tmp/op01-cache"
INDEX = "lab-indexer.service"
PERFORMANCE_COMMANDS = (
    "systemctl list-unit-files --state=enabled", f"sudo systemctl disable {INDEX}",
    f"sudo systemctl enable {INDEX}", f"du -sh {CACHE}", "df -h /",
    f"rm -- {CACHE}/index.tmp", "lsblk -d -o NAME,ROTA", "lsblk -D", "sudo fstrim -n -v /", "lab-reset",
)


def performance(command, state):
    enabled = state.get("enabled", True)
    cleaned = state.get("cleaned", False)
    if command == "lab-reset":
        state.clear()
        return "Автозагрузка и временные файлы восстановлены."
    if command == "systemctl list-unit-files --state=enabled":
        if enabled:
            state["startup_before"] = True
        if not enabled:
            state["startup_verified"] = True
        units = f"{INDEX:<24} enabled\n" if enabled else ""
        return f"UNIT FILE                STATE\n{units}cron.service            enabled"
    if command in (f"sudo systemctl disable {INDEX}", f"sudo systemctl enable {INDEX}"):
        new_state = command.startswith("sudo systemctl enable")
        if enabled != new_state:
            state.update(enabled=new_state, startup_verified=False)
        return ""
    if command == f"du -sh {CACHE}":
        if not cleaned:
            state["cache_seen"] = True
        return f"{'16K' if cleaned else '2.0G'}    {CACHE}"
    if command == "df -h /":
        state["disk_after" if cleaned else "disk_before"] = True
        return ("Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        30G   "
                + ("24G    6G  80% /" if cleaned else "26G    4G  87% /"))
    if command in (f"rm -- {CACHE}/index.tmp", f"rm {CACHE}/index.tmp"):
        if cleaned:
            return "rm: index.tmp: No such file or directory"
        state["cleaned"] = True
        return ""
    if command == "lsblk -d -o NAME,ROTA":
        state["disk_type_seen"] = True
        return "NAME ROTA\nsda     0"
    if command in ("lsblk -D", "lsblk --discard"):
        state["discard_seen"] = True
        return "NAME  DISC-ALN DISC-GRAN DISC-MAX DISC-ZERO\nsda          0        4K       2G         0\n└─sda1       0        4K       2G         0"
    if command in ("sudo fstrim -n -v /", "sudo fstrim --dry-run --verbose /"):
        if state.get("disk_type_seen") and state.get("discard_seen"):
            state["trim_previewed"] = True
        return "/: пробный запуск TRIM. Свободные блоки не изменены."
    return None


def performance_checks(state):
    return {
        "autostart_checked": state.get("startup_before") and state.get("startup_verified"),
        "autostart_disabled": state.get("enabled") is False,
        "cache_cleaned": state.get("cache_seen") and state.get("cleaned"),
        "trim_previewed": state.get("trim_previewed"),
    }


DOCUMENT = "/srv/lab/notes.txt"
BACKUP = "~/backup.tar.gz"
RESTORE = "~/restore"
SAFETY_COMMANDS = (
    "ps -eo pid,comm,%cpu --sort=-%cpu", "journalctl -p warning -n 10",
    f"sudo -u analyst test -r {DOCUMENT}", f"sudo -u visitor test -r {DOCUMENT}",
    f"tar -czf {BACKUP} -C /srv/lab notes.txt", f"tar -tzf {BACKUP}",
    f"mkdir -p {RESTORE}", f"tar -xzf {BACKUP} -C {RESTORE}",
    f"cmp {DOCUMENT} {RESTORE}/notes.txt", "lab-reset",
)


def system_safety(command, state):
    if command == "lab-reset":
        state.clear()
        return "Учебная папка и результаты диагностики восстановлены до начального состояния."
    if command == "ps -eo pid,comm,%cpu --sort=-%cpu":
        state["process_seen"] = True
        return "  PID COMMAND         %CPU\n  742 lab-sync        84.0\n  101 bash             0.2"
    if command == "journalctl -p warning -n 10":
        state["journal_seen"] = True
        return "lab-sync[742]: sync paused: cache is full"
    if command == f"sudo -u analyst test -r {DOCUMENT}":
        state["analyst_read"] = True
        return "Код завершения: 0"
    if command == f"sudo -u visitor test -r {DOCUMENT}":
        state["visitor_denied"] = True
        return "Код завершения: 1"
    if command == f"tar -czf {BACKUP} -C /srv/lab notes.txt":
        state["backup"] = {"notes.txt": "Контрольная заметка ОП01"}
        state["listed"] = False
        return ""
    if command == f"tar -tzf {BACKUP}":
        backup = state.get("backup")
        if not backup:
            return "tar: backup.tar.gz: Cannot open: No such file or directory"
        state["listed"] = True
        return "\n".join(backup)
    if command in (f"mkdir -p {RESTORE}", f"mkdir {RESTORE}"):
        state["restore_dir"] = True
        return ""
    if command == f"tar -xzf {BACKUP} -C {RESTORE}":
        if not state.get("backup"):
            return "tar: backup.tar.gz: Cannot open: No such file or directory"
        if not state.get("restore_dir"):
            return "tar: ~/restore: Cannot open: No such file or directory"
        state.update(restored=state["backup"]["notes.txt"], compared=False)
        return ""
    if command == f"cmp {DOCUMENT} {RESTORE}/notes.txt":
        if not state.get("restored"):
            return "cmp: ~/restore/notes.txt: No such file or directory"
        state["compared"] = state["restored"] == "Контрольная заметка ОП01"
        return f"Код завершения: {int(not state['compared'])}"
    return None


def safety_checks(state):
    return {
        "access": state.get("analyst_read") and state.get("visitor_denied"),
        "backup": state.get("backup") and state.get("listed"),
        "restore": state.get("restored") and state.get("compared"),
    }
