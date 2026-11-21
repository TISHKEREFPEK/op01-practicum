"""Archive and document exercises using snapshots of virtual files."""

DOC = "~/docs/notes.txt"
CONTROL = "Контрольный файл ОП01\n"
SEEDS = {
    "~/docs": {"control.txt": CONTROL},
    "~/materials": {"guide.txt": "Учебные материалы ОП01", "signature-test.txt": "Учебная сигнатура"},
}
DESTINATIONS = {"~/unpacked", "~/restore"}
SCAN = "clamscan -r -l /home/student/scan.log /home/student/materials"
UTILITIES_COMMANDS = (
    "tar -czf ~/course.tar.gz -C ~ materials", "gzip -t ~/course.tar.gz", "mkdir -p ~/unpacked",
    "tar -xzf ~/course.tar.gz -C ~/unpacked", "diff -r ~/materials ~/unpacked/materials",
    SCAN, "cat ~/scan.log", "df -h /", "lab-reset",
)
APPS_COMMANDS = (
    "cat ~/docs/notes.txt", "tar -czf ~/docs.tar.gz -C ~ docs", "tar -tzf ~/docs.tar.gz",
    "tar -czf ~/backup.tar.gz -C ~ docs", "mkdir -p ~/restore",
    "tar -xzf ~/backup.tar.gz -C ~/restore", "cmp ~/docs/control.txt ~/restore/docs/control.txt", "lab-reset",
)


def source(state, folder):
    values = dict(SEEDS[folder])
    if folder == "~/docs" and state.get("document") is not None:
        values["notes.txt"] = state["document"]
    return values


def archive_tools(command, state, folder, allowed):
    archives = state.get("archives", {})
    extracts = state.get("extracts", {})
    args = command.split()
    args = [arg.replace("/home/student/", "~/", 1) if arg.startswith("/home/student/") else arg for arg in args]
    if command == "lab-reset":
        state.clear()
        return "Учебные файлы и результаты действий сброшены."
    if len(args) == 6 and args[:2] == ["tar", "-czf"] and args[-3:] == ["-C", "~", folder[2:]]:
        name = args[2]
        if name not in allowed:
            return "tar: выберите имя архива из условия."
        state["archives"] = {**archives, name: {"files": source(state, folder)}}
        return ""
    if len(args) == 3 and args[:2] in (["tar", "-tzf"], ["gzip", "-t"]):
        name = args[2]
        if name not in archives:
            return f"{args[0]}: {name}: No such file or directory"
        flag = "listed" if args[0] == "tar" else "tested"
        entry = archives[name]
        state["archives"] = {**archives, name: {**entry, flag: True}}
        return "\n".join(folder[2:] + "/" + path for path in entry["files"]) if flag == "listed" else "Код завершения: 0"
    if len(args) == 3 and args[:2] == ["mkdir", "-p"] and args[-1] in DESTINATIONS:
        directory = args[-1]
        if directory not in state.get("directories", []):
            state["directories"] = [*state.get("directories", []), directory]
        return ""
    if len(args) == 5 and args[:2] == ["tar", "-xzf"] and args[3] == "-C":
        name, destination = args[2], args[4]
        if name not in archives or destination not in state.get("directories", []):
            return "tar: архив или каталог назначения не найден."
        state["extracts"] = {**extracts, destination: {"archive": name, "files": archives[name]["files"]}}
        if destination == "~/unpacked":
            state["compared"] = False
        if destination == "~/restore":
            state["restore_compared"] = False
        return ""
    return None


def utilities(command, state):
    if command == "diff -r ~/materials ~/unpacked/materials":
        destination = state.get("extracts", {}).get("~/unpacked")
        if not destination:
            return "diff: ~/unpacked/materials: No such file or directory"
        if destination["files"] == SEEDS["~/materials"]:
            state["compared"] = True
            return "Код завершения: 0"
        return "Код завершения: 1"
    if command == SCAN:
        state.update(scan=True, scan_read=False)
        return "/home/student/materials/signature-test.txt: Lab-Signature-Test FOUND\nInfected files: 1"
    if command == "cat ~/scan.log":
        if not state.get("scan"):
            return "cat: ~/scan.log: No such file or directory"
        state["scan_read"] = True
        return "/home/student/materials/signature-test.txt: Lab-Signature-Test FOUND\nInfected files: 1"
    if command == "df -h /":
        state["disk_seen"] = True
        return "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        30G   29G    1G  97% /"
    return archive_tools(command, state, "~/materials", {"~/course.tar.gz"})


def utilities_checks(state):
    archive = state.get("archives", {}).get("~/course.tar.gz", {})
    extracted = state.get("extracts", {}).get("~/unpacked", {})
    return {
        "archive_tested": archive.get("tested"),
        "archive_extracted": extracted.get("archive") == "~/course.tar.gz" and state.get("compared"),
        "scan_read": state.get("scan_read"),
    }


def apps(command, state):
    if command == "cat ~/docs/notes.txt":
        return state.get("document", "cat: ~/docs/notes.txt: No such file or directory")
    if command == "cmp ~/docs/control.txt ~/restore/docs/control.txt":
        restored = state.get("extracts", {}).get("~/restore", {})
        if not restored:
            return "cmp: ~/restore/docs/control.txt: No such file or directory"
        state["restore_compared"] = restored["files"].get("control.txt") == CONTROL
        return f"Код завершения: {int(not state['restore_compared'])}"
    return archive_tools(command, state, "~/docs", {"~/docs.tar.gz", "~/backup.tar.gz"})


def apps_checks(state):
    document = state.get("document", "").splitlines()
    current = source(state, "~/docs")
    archives = state.get("archives", {})
    archive = archives.get("~/docs.tar.gz", {})
    backup = archives.get("~/backup.tar.gz", {})
    restored = state.get("extracts", {}).get("~/restore", {})
    return {
        "document": (len(document) >= 2 and document[0].strip() == "ОП01" and
                     any(line.strip() for line in document[1:])),
        "archive": archive.get("files") == current and archive.get("listed"),
        "backup": backup.get("files") == current,
        "restore": restored.get("archive") == "~/backup.tar.gz" and restored.get("files") == backup.get("files")
                   and state.get("restore_compared"),
    }
