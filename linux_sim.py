"""State transitions for the account and command-line practice machines."""
import posixpath
import re


PROJECT = "/srv/project"
ACCOUNT_COMMANDS = (
    "sudo groupadd project", "sudo useradd -m alex", "sudo useradd -m tempuser",
    "sudo usermod -aG project alex", f"sudo chgrp project {PROJECT}", f"sudo chmod 770 {PROJECT}",
    "id alex", f"sudo -u alex test -w {PROJECT}", f"sudo -u tempuser test -w {PROJECT}",
    "sudo userdel -r tempuser", "getent group project", "ls -ld /srv/project", "lab-reset",
)


def accounts(command, state):
    if command == "lab-reset":
        state.clear()
        return "Учётные записи и права сброшены."
    users = state.get("users", {})
    groups = state.get("groups", [])
    group = state.get("project_group", "root")
    mode = state.get("project_mode", "755")
    args = command.split()
    if len(args) == 3 and args[:2] == ["sudo", "groupadd"] and args[2] == "project":
        if "project" in groups:
            return "groupadd: группа project уже существует"
        state["groups"] = [*groups, "project"]
        return ""
    if len(args) in (3, 4) and args[:2] == ["sudo", "useradd"] and (len(args) == 3 or args[2] == "-m"):
        user = args[-1]
        if user not in ("alex", "tempuser"):
            return "useradd: в этой работе используются alex и tempuser"
        if user in users:
            return f"useradd: пользователь {user} уже существует"
        state["users"] = {**users, user: []}
        if user == "tempuser":
            state.pop("removed", None)
            state.pop("verified_after_removal", None)
            state.pop("temp_denied", None)
        return ""
    if args[:3] == ["sudo", "usermod", "-aG"] and len(args) == 5:
        _, _, _, new_group, user = args
        if user not in users or new_group not in groups:
            return "usermod: сначала создайте пользователя и группу"
        if new_group not in users[user]:
            state["users"] = {**users, user: [*users[user], new_group]}
            invalidate_access(state)
        return ""
    if len(args) == 4 and args[0] == "sudo" and args[-1] == PROJECT:
        operation, value = args[1:3]
        if operation == "chgrp":
            if value not in ("root", *groups):
                return "chgrp: группа не существует"
            if value != group:
                state["project_group"] = value
                invalidate_access(state)
            return ""
        if operation == "chmod" and re.fullmatch(r"[0-7]{3}", value):
            if value != mode:
                state["project_mode"] = value
                invalidate_access(state)
            return ""
    if args == ["ls", "-ld", PROJECT]:
        digits = ["".join(letter if int(value) & bit else "-"
                          for letter, bit in zip("rwx", (4, 2, 1))) for value in mode]
        return f"d{''.join(digits)} 2 root {group} 4096 /srv/project"
    if len(args) == 2 and args[0] == "id":
        user = args[1]
        if user not in users:
            return f"id: пользователь {user} не существует"
        return f"uid={1001 if user == 'alex' else 1002}({user}) groups={','.join([user, *users[user]])}"
    if args == ["getent", "group", "project"]:
        if "project" not in groups:
            return "Код завершения: 2"
        if state.get("removed") and "project" in users.get("alex", []):
            state["verified_after_removal"] = True
        members = ",".join(user for user in users if "project" in users[user])
        return f"project:x:1001:{members}"
    if len(args) == 6 and args[:2] == ["sudo", "-u"] and args[3:] == ["test", "-w", PROJECT]:
        user = args[2]
        if user not in users:
            return f"sudo: пользователь {user} не существует"
        allowed = bool(int(mode[1 if group in users[user] else 2]) & 2)
        if user == "alex":
            state["alex_write"] = allowed
        else:
            state["temp_denied"] = not allowed
        return f"Код завершения: {int(not allowed)}"
    if args in (["sudo", "userdel", "tempuser"], ["sudo", "userdel", "-r", "tempuser"]):
        if "tempuser" not in users:
            return "userdel: пользователь tempuser не существует"
        state["users"] = {user: value for user, value in users.items() if user != "tempuser"}
        state["removed"] = True
        state["verified_after_removal"] = False
        return ""
    return None


def invalidate_access(state):
    for marker in ("alex_write", "temp_denied", "verified_after_removal"):
        state.pop(marker, None)


def account_checks(state):
    users = state.get("users", {})
    return {
        "project_member": "project" in users.get("alex", []),
        "project_access": state.get("project_group") == "project" and state.get("project_mode") == "770",
        "access_verified": state.get("alex_write") and state.get("temp_denied"),
        "temp_removed": state.get("removed") and "tempuser" not in users,
        "group_verified": state.get("verified_after_removal"),
    }


HOME = "/home/student"
SOURCE = HOME + "/workspace/source.txt"
COPY = HOME + "/workspace/copy.txt"
REPORT = HOME + "/workspace/report.txt"
SHELL_COMMANDS = (
    "pwd", "ls", "cd workspace", "mkdir workspace", "touch workspace/source.txt",
    "cp workspace/source.txt workspace/copy.txt", "mv workspace/copy.txt workspace/report.txt",
    "sleep 300 &", "ps -o pid,comm", "kill PID", "ip -4 addr show", "ping -c 3 192.168.10.1",
    "dpkg -s coreutils", "lab-reset",
)


def shell(command, state):
    if command == "lab-reset":
        state.clear()
        return "Учебные файлы, рабочий каталог и процесс сброшены."
    args = command.split()
    if not args:
        return ""
    op, *values = args
    cwd = state.get("cwd", HOME)
    directories = state.get("directories", [HOME])
    files = state.get("files", {})
    if command == "pwd":
        return cwd
    if command == "ls":
        return "  ".join(sorted(posixpath.basename(path) for path in [*directories, *files]
                                if posixpath.dirname(path) == cwd))
    if op in ("cd", "mkdir", "touch", "cp", "mv"):
        expected = 2 if op in ("cp", "mv") else 1
        if len(values) != expected and not (op == "cd" and not values):
            return f"{op}: проверьте число аргументов"
        paths = [normalize(path, cwd) for path in values] or [HOME]
        if any(path != HOME and not path.startswith(HOME + "/") for path in paths):
            return f"{op}: в этой работе доступен домашний каталог"
        if op == "cd":
            if paths[0] not in directories:
                return "cd: каталог не найден"
            state["cwd"] = paths[0]
            return ""
        target = paths[-1]
        if posixpath.dirname(target) not in directories:
            return f"{op}: родительский каталог не найден"
        if op == "mkdir":
            if target in directories or target in files:
                return "mkdir: файл или каталог уже существует"
            state["directories"] = [*directories, target]
            return ""
        if target in directories:
            if op == "touch":
                return ""
            target = posixpath.join(target, posixpath.basename(paths[0]))
        if op == "touch":
            if target not in files:
                state["files"] = {**files, target: {"origin": target, "copied": False}}
            return ""
        source = paths[0]
        if source not in files or source == target or target in directories:
            return f"{op}: проверьте исходный файл и назначение"
        if op == "cp":
            state["files"] = {**files, target: {"origin": files[source]["origin"], "copied": True}}
        else:
            state["files"] = {**files, target: {**files[source], "moved_from": source}}
            del state["files"][source]
        return ""
    if command == "sleep 300 &":
        if state.get("running"):
            return "Учебный процесс sleep уже запущен."
        state.update(running=True, process_seen=False, process_stopped=False)
        return "[1] 2048"
    if command in ("ps", "ps -o pid,comm"):
        if state.get("running"):
            state["process_seen"] = True
        return "  PID COMMAND\n  101 bash" + ("\n 2048 sleep" if state.get("running") else "")
    if command == "kill 2048":
        if not state.get("running"):
            return "kill: процесс не найден"
        state["running"] = False
        state["process_stopped"] = state.get("process_seen", False)
        return ""
    if command in ("ip -4 addr show", "ip addr show", "ip -4 addr show eth0"):
        state["ip_seen"] = True
        return "2: eth0: <BROADCAST,MULTICAST,UP> mtu 1500\n    inet 192.168.10.50/24 scope global eth0"
    if command == "ping -c 3 192.168.10.1":
        state["ping_done"] = True
        return "3 packets transmitted, 3 received, 0% packet loss"
    if command == "dpkg -s coreutils":
        state["package_seen"] = True
        return "Package: coreutils\nStatus: install ok installed\nVersion: 9.7-3"
    return None


def normalize(path, cwd):
    if path == "~" or path.startswith("~/"):
        path = HOME + path[1:]
    return "/" + posixpath.normpath(posixpath.join(cwd, path)).lstrip("/")


def shell_checks(state):
    files = state.get("files", {})
    report = files.get(REPORT, {})
    return {
        "source_ready": SOURCE in files,
        "report_ready": report.get("origin") == SOURCE and report.get("copied")
                        and report.get("moved_from") == COPY and COPY not in files,
        "process_stopped": state.get("process_stopped") and not state.get("running"),
        "ping_done": state.get("ping_done"),
    }
