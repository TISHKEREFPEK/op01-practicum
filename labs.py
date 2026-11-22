"""Deterministic Linux exercises. Commands only inspect or update simulated state."""

from archive_labs import APPS_COMMANDS, DOC, UTILITIES_COMMANDS, apps, apps_checks, utilities, utilities_checks
from bash_lab import COMMANDS as BASH_COMMANDS, SCRIPT, automation, automation_checks
from installer_lab import INSTALLER_COMMANDS, install, installer_checks, wizard
from linux_sim import ACCOUNT_COMMANDS, SHELL_COMMANDS, account_checks, accounts, shell, shell_checks
from system_labs import (
    INCIDENT_COMMANDS, PERFORMANCE_COMMANDS, SAFETY_COMMANDS, incident, incident_checks,
    performance, performance_checks, safety_checks, system_safety,
)

INVENTORY = {
    "lscpu": "Architecture:        x86_64\nCPU(s):              8\nModel name:          Intel Core i5-10400",
    "free -h": "               total        used        free\nMem:            16Gi       2.4Gi        13Gi\nSwap:          2.0Gi          0B       2.0Gi",
    "lsblk": "NAME    SIZE TYPE MOUNTPOINTS\nsda     512G disk\n└─sda1  512G part /",
    "lspci": "00:02.0 VGA compatible controller: Intel UHD Graphics 630",
}

HARDWARE_COMMANDS = (
    "lspci -k", "free -h", "lab-load start", "lab-load stop", "vmstat 1 2",
    "cat /proc/interrupts", "ping -c 3 192.168.10.1", "lab-reset",
)
SHARE_FILE = "/srv/course/report.txt"
MEDIA_CACHE = "/mnt/media/preview.cache"
MEDIA_REPORT = "/mnt/media/report.txt"
SHARE_COMMANDS = (
    "lsblk", "df -h /mnt/media", f"getfacl {SHARE_FILE}",
    f"sudo setfacl -m u:editor:rw,u:reader:r {SHARE_FILE}",
    f"sudo -u editor test -w {SHARE_FILE}", f"sudo -u reader test -r {SHARE_FILE}",
    f"sudo -u reader test -w {SHARE_FILE}", "du -ah --max-depth=1 /mnt/media",
    f"rm -- {MEDIA_CACHE}", f"cp {SHARE_FILE} {MEDIA_REPORT}", f"cmp {SHARE_FILE} {MEDIA_REPORT}", "lab-reset",
)


def field(label, expected, *, options=None, observed=()):
    definition = {"label": label, "expected": expected, "observed": observed}
    if options is not None:
        definition["options"] = options
    return definition


def inventory(command, state):
    if command in INVENTORY:
        state["observed"] = True
        return INVENTORY[command]
    return None


def hardware(command, state):
    if command == "lab-reset":
        state.clear()
        return "Учебная машина вернулась к исходным показателям. Черновик сохранён без изменений."
    loaded = state.get("loaded", False)
    packets = state.get("packets", 0)
    if command == "lspci -k":
        state["driver_read"] = True
        return "00:03.0 Ethernet controller: Virtio network device\n\tKernel driver in use: virtio-pci\n\tKernel modules: virtio_pci"
    if command == "free -h":
        state["memory_after" if loaded else "memory_before"] = True
        return ("               total        used        free      available\n"
                + ("Mem:            16Gi       7.0Gi       7.3Gi          9Gi" if loaded else
                   "Mem:            16Gi       3.0Gi        11Gi         13Gi"))
    if command == "lab-load start":
        state["loaded"] = True
        return "Учебная нагрузка запущена. Она заняла 4 ГиБ памяти и продолжает чтение с диска."
    if command == "lab-load stop":
        state["loaded"] = False
        return "Учебная нагрузка остановлена."
    if command == "vmstat 1 2":
        if loaded:
            state["io_read"] = True
        return ("... ----io---- ...\n        bi    bo\n        12     4\n"
                + ("      2048    16" if loaded else "        12     4"))
    if command == "cat /proc/interrupts":
        state["interrupts_after" if packets else "interrupts_before"] = True
        return f"           CPU0\n 36:        {40 + packets:<5}  PCI-MSI  virtio0-input.0"
    if command == "ping -c 3 192.168.10.1":
        state["packets"] = packets + 3
        return "PING 192.168.10.1\n3 packets transmitted, 3 received, 0% packet loss"
    return None


def resource_sharing(command, state):
    permissions = state.get("permissions", {})
    cleared = state.get("media_cache_removed", False)
    if command == "lab-reset":
        state.clear()
        return "Учебные устройства и права возвращены к исходному состоянию."
    if command == "lsblk":
        state["devices_read"] = True
        return "NAME   SIZE TYPE MOUNTPOINTS\nsda    64G  disk\n└─sda1 64G  part /\nsdb     8G  disk /mnt/media"
    if command == "df -h /mnt/media":
        state["media_space_seen" if cleared else "usage_read"] = True
        usage = "6.0G  2.0G  75%" if cleared else "8.0G    0B 100%"
        return f"Filesystem      Size  Used Avail Use% Mounted on\n/dev/sdb        8.0G  {usage} /mnt/media"
    if command == "du -ah --max-depth=1 /mnt/media":
        if cleared:
            report = f"4.0K    {MEDIA_REPORT}\n" if state.get("media_report_copied") else ""
            return f"6.0G    /mnt/media/materials\n{report}6.0G    /mnt/media"
        state["media_cache_seen"] = True
        return f"6.0G    /mnt/media/materials\n2.0G    {MEDIA_CACHE}\n8.0G    /mnt/media"
    if command in (f"rm -- {MEDIA_CACHE}", f"rm {MEDIA_CACHE}"):
        if cleared:
            return f"rm: {MEDIA_CACHE}: No such file or directory"
        state["media_cache_removed"] = True
        return ""
    if command == f"cp {SHARE_FILE} {MEDIA_REPORT}":
        if not cleared:
            return f"cp: {MEDIA_REPORT}: No space left on device"
        state["media_report_copied"] = True
        state.pop("media_verified", None)
        return ""
    if command == f"cmp {SHARE_FILE} {MEDIA_REPORT}":
        if not state.get("media_report_copied"):
            return f"cmp: {MEDIA_REPORT}: No such file or directory"
        state["media_verified"] = all(state.get(marker) for marker in ("usage_read", "media_cache_seen", "media_space_seen"))
        return "Код завершения: 0"
    args = command.split()
    if args == ["getfacl", SHARE_FILE]:
        entries = [f"user:{name}:{mode}" for name, mode in sorted(permissions.items())]
        mask = ["mask::rw-" if "rw-" in permissions.values() else "mask::r--"] if entries else []
        return "\n".join([f"# file: {SHARE_FILE}", "# owner: student", "user::rw-",
                          *entries, "group::---", *mask, "other::---"])
    if len(args) == 5 and args[:3] == ["sudo", "setfacl", "-m"] and args[-1] == SHARE_FILE:
        updated = dict(permissions)
        for entry in args[3].split(","):
            parts = entry.split(":")
            if len(parts) != 3 or parts[0] != "u" or parts[1] not in ("editor", "reader"):
                return "setfacl: укажите учебного пользователя editor или reader."
            _, user, mode = parts
            if mode not in ("r", "rw", "r--", "rw-"):
                return "setfacl: в этой работе используйте r или rw."
            updated[user] = "rw-" if "w" in mode else "r--"
        if updated != permissions:
            for name in ("editor_write", "reader_read", "reader_denied"):
                state.pop(name, None)
            state["permissions"] = updated
        return ""
    if (len(args) == 6 and args[0:2] == ["sudo", "-u"] and args[3] == "test"
            and args[2] in ("editor", "reader") and args[4] in ("-r", "-w") and args[5] == SHARE_FILE):
        user, flag = args[2], args[4]
        allowed = flag[1] in permissions.get(user, "")
        if (user, flag, allowed) == ("editor", "-w", True):
            state["editor_write"] = True
        if (user, flag, allowed) == ("reader", "-r", True):
            state["reader_read"] = True
        if (user, flag, allowed) == ("reader", "-w", False) and permissions.get("reader") == "r--":
            state["reader_denied"] = True
        return f"Код завершения: {int(not allowed)}"
    return None


LABS = {
    "machine-inventory": {
        "title": "Паспорт машины",
        "prompt": "Определите, что первым ограничит задачу, которой нужно 22 ГиБ оперативной памяти. Для процессора, диска и графики её требования выполнены.",
        "commands": tuple(INVENTORY),
        "execute": inventory,
        "fields": {
            "model": field("Модель процессора", "intel core i5-10400"),
            "threads": field("Логические процессоры", "8"),
            "ram": field("Оперативная память, ГиБ", "16"),
            "disk": field("Ёмкость накопителя, ГиБ", "512"),
            "gpu": field("Графический адаптер", "intel uhd graphics 630"),
            "bottleneck": field("Узкое место", "ram", options={
                "cpu": "Процессор", "ram": "Оперативная память", "disk": "Накопитель",
                "gpu": "Графический адаптер",
            }),
        },
    },
    "os-and-hardware": {
        "title": "Протокол наблюдений",
        "prompt": "Запишите результаты команды free по колонке available. В таблице vmstat используйте второй замер.",
        "commands": HARDWARE_COMMANDS,
        "execute": hardware,
        "fields": {
            "driver": field("Драйвер сетевого устройства", "virtio-pci", observed=("driver_read",)),
            "before": field("Доступно до нагрузки, ГиБ", "13", observed=("memory_before",)),
            "after": field("Доступно под нагрузкой, ГиБ", "9", observed=("memory_after",)),
            "disk_read": field("Чтение с диска во втором замере, блоков/с", "2048", observed=("io_read",)),
            "buffer": field("Зачем ОС буферизует ввод-вывод", "smooth", options={
                "smooth": "Сгладить разницу в скорости обмена",
                "replace": "Заменить драйвер устройства",
                "interrupt": "Отключить обработку прерываний",
            }),
            "irq": field("Изменение счётчика virtio0-input.0", "up", options={
                "up": "Вырос", "same": "Остался прежним", "down": "Уменьшился",
            }, observed=("interrupts_before", "interrupts_after")),
        },
    },
    "accounts-and-permissions": {
        "title": "Проверка учётных записей и доступа",
        "prompt": "Команда «Проверить работу» сверит права папки, результаты проверок от имени пользователей и состояние учётных записей.",
        "commands": ACCOUNT_COMMANDS,
        "execute": accounts,
        "fields": {},
        "inspect": account_checks,
        "criteria": {
            "project_member": "alex входит в группу project",
            "project_access": "Группа project владеет папкой, режим доступа 770",
            "access_verified": "Запись для alex разрешена, для tempuser запрещена",
            "temp_removed": "Временная учётная запись tempuser удалена",
            "group_verified": "Состав группы проверен после удаления временной записи",
        },
    },
    "shell-basics": {
        "title": "Результаты работы в Linux",
        "prompt": "Перенесите IP-адрес и версию установленного пакета из вывода команд. Остальные действия проверяются по состоянию машины.",
        "commands": SHELL_COMMANDS,
        "execute": shell,
        "inspect": shell_checks,
        "fields": {
            "ip": field("IPv4-адрес интерфейса eth0 без маски", "192.168.10.50", observed=("ip_seen",)),
            "package": field("Версия coreutils", "9.7-3", observed=("package_seen",)),
        },
        "criteria": {
            "source_ready": "Исходный файл source.txt сохранён",
            "report_ready": "Копия переименована из copy.txt в report.txt",
            "process_stopped": "PID процесса sleep найден и процесс завершён",
            "ping_done": "Проверена связь со шлюзом",
        },
    },
    "incident-diagnostics": {
        "title": "Отчёт об инциденте",
        "prompt": "Укажите причину сбоя и доступную память до изменения конфигурации службы.",
        "commands": INCIDENT_COMMANDS,
        "execute": incident,
        "inspect": incident_checks,
        "fields": {
            "cause": field("Причина сбоя", "port", observed=("log_before",), options={
                "memory": "Системе не хватило оперативной памяти",
                "port": "Вместо номера порта в конфигурации записан текст",
                "disk": "Корневой диск переполнен",
            }),
            "memory": field("Доступная память, ГиБ", "5", observed=("memory_before",)),
        },
        "criteria": {
            "reproduced": "Отказ HTTP воспроизведён до изменения конфигурации",
            "edited": "В конфигурации установлен порт 8080",
            "active": "Служба работает с исправленной конфигурацией",
            "verified": "После последнего запуска получен HTTP 200",
        },
    },
    "performance": {
        "title": "Отчёт по оптимизации",
        "prompt": "Сравните свободное место в колонке Avail. Определите тип накопителя по ROTA и выберите способ обслуживания.",
        "commands": PERFORMANCE_COMMANDS,
        "execute": performance,
        "inspect": performance_checks,
        "fields": {
            "before": field("Доступно до очистки, ГиБ", "4", observed=("disk_before",)),
            "after": field("Доступно после очистки, ГиБ", "6", observed=("disk_after",)),
            "method": field("Способ обслуживания учебного диска", "trim", observed=("disk_type_seen",), options={
                "trim": "Твердотельный накопитель. Использовать TRIM, если он поддерживается",
                "defrag": "Магнитный диск. Проверить фрагментацию и необходимость дефрагментации",
            }),
        },
        "criteria": {
            "autostart_checked": "Список автозагрузки проверен до и после изменения",
            "autostart_disabled": "Автозапуск lab-indexer.service отключён",
            "cache_cleaned": "Измерен и очищен учебный кэш",
            "trim_previewed": "Проверены тип диска и поддержка discard, выполнен пробный TRIM",
        },
    },
    "system-safety": {
        "title": "Отчёт по диагностике и резервной копии",
        "prompt": "Запишите PID процесса с высокой нагрузкой и причину остановки синхронизации. Прогресс резервной копии определяется по действиям в консоли.",
        "commands": SAFETY_COMMANDS,
        "execute": system_safety,
        "inspect": safety_checks,
        "fields": {
            "pid": field("PID процесса с высокой загрузкой CPU", "742", observed=("process_seen",)),
            "cause": field("Причина остановки синхронизации", "cache", observed=("journal_seen",), options={
                "cache": "Кэш заполнен", "driver": "Драйвер отсутствует", "dns": "DNS не отвечает",
            }),
        },
        "criteria": {
            "access": "Проверены права чтения для analyst и visitor",
            "backup": "Резервная копия создана, список файлов проверен",
            "restore": "Документ восстановлен в отдельную папку и сверён с оригиналом",
        },
    },
    "shell-automation": {
        "title": "Проверка сценария",
        "prompt": "Тренажёр выполняет учебное подмножество Bash: переменные, if/then/else/fi, &&/||, test -d, echo, tar -czf и exit. Проверка запускает сохранённый файл с разными аргументами.",
        "commands": BASH_COMMANDS,
        "execute": automation,
        "inspect": automation_checks,
        "editor": SCRIPT,
        "fields": {},
        "criteria": {
            "script": "Скрипт сохранён в ~/backup.sh",
            "trial": "Текущая версия скрипта запускалась в консоли",
            "materials": "Для каталога materials создан архив с нужным именем и файлами",
            "logs": "Тот же скрипт работает для каталога logs и другого имени архива",
            "absent": "Отсутствующий каталог даёт ненулевой код выхода без архива",
        },
    },
    "os-installation": {
        "title": "Проверка установленной системы",
        "prompt": "После первого запуска соберите сведения о системе, загрузите модуль сетевого драйвера и проверьте его через lspci -k.",
        "commands": INSTALLER_COMMANDS,
        "execute": install,
        "inspect": installer_checks,
        "wizard": wizard,
        "fields": {
            "version": field("Номер выпуска Debian", "13", observed=("version_read",)),
            "driver": field("Драйвер сетевого устройства", "e1000e", observed=("driver_loaded", "driver_read")),
        },
        "criteria": {
            "media": "Выбран автономный образ Debian для amd64",
            "layout": "Учебный диск размечен для UEFI",
            "installed": "Система запущена с диска, корневой раздел проверен",
            "setup": "Язык, часовой пояс и учётная запись проверены",
        },
    },
    "system-utilities": {
        "title": "Отчёт о состоянии системы",
        "prompt": "Укажите число срабатываний учебного сканера и процент занятого места на системном диске.",
        "commands": UTILITIES_COMMANDS,
        "execute": utilities,
        "inspect": utilities_checks,
        "fields": {
            "alerts": field("Срабатывания в журнале проверки", "1", observed=("scan_read",)),
            "used": field("Занято на /, %", "97", observed=("disk_seen",)),
            "conclusion": field("Что требует внимания", "disk", observed=("disk_seen",), options={
                "disk": "На системном диске осталось мало свободного места",
                "memory": "Системе не хватает оперативной памяти",
                "network": "Не настроен основной шлюз",
            }),
        },
        "criteria": {
            "archive_tested": "Целостность архива проверена",
            "archive_extracted": "Распакованный каталог совпадает с исходным",
            "scan_read": "Проверка выполнена, её журнал прочитан",
        },
    },
    "built-in-apps": {
        "title": "Проверка документа и восстановления",
        "prompt": "Сохраните документ в редакторе и выполните операции с архивом и резервной копией в консоли.",
        "commands": APPS_COMMANDS,
        "execute": apps,
        "inspect": apps_checks,
        "editor": DOC,
        "fields": {
            "recovery": field("Зачем извлекать копию в отдельный каталог", "keep", options={
                "keep": "Проверить копию до перезаписи исходных файлов",
                "size": "Уменьшить размер резервной копии",
                "delete": "Удалить исходную версию автоматически",
            }),
        },
        "criteria": {
            "document": "Документ начинается с ОП01 и содержит заметку",
            "archive": "Актуальный каталог заархивирован, состав проверен",
            "backup": "Отдельная резервная копия содержит актуальный документ",
            "restore": "Контрольный файл восстановлен из резервной копии и сверён",
        },
    },
    "resource-sharing": {
        "title": "Отчёт по устройству и доступу",
        "prompt": "Укажите устройство с неполадкой и объясните, почему на него не удаётся сохранить файл.",
        "commands": SHARE_COMMANDS,
        "execute": resource_sharing,
        "fields": {
            "device": field("Устройство Linux", "/dev/sdb", observed=("devices_read",)),
            "size": field("Ёмкость устройства, ГиБ", "8", observed=("devices_read",)),
            "cause": field("Причина неполадки", "full", options={
                "full": "На накопителе нет свободного места",
                "missing": "Устройство не подключено",
                "graphics": "Неполадка видеодрайвера",
            }, observed=("usage_read",)),
        },
        "criteria": {
            "editor_write": "Пользователь editor может писать",
            "reader_read": "Пользователь reader может читать",
            "reader_denied": "Попытка записи от reader отклонена",
            "media_verified": "Освобождено место на накопителе, файл скопирован и сверен",
        },
    },
}


def run_command(lab, command, state):
    if command == "help":
        return "Команды учебной машины:\n" + "\n".join(lab["commands"])
    output = lab["execute"](command, state)
    return output if output is not None else "Команда недоступна в этой работе. Введите help."


def check_answers(lab, answers, state):
    results = []
    for key, definition in lab["fields"].items():
        answer = " ".join(answers.get(key, "").casefold().split())
        observed = all(state.get(marker) for marker in definition["observed"])
        results.append({
            "label": definition["label"],
            "passed": answer == definition["expected"] and observed,
            **({"hint": "Выполните соответствующий замер в терминале."} if not observed else {}),
        })
    evidence = lab["inspect"](state) if "inspect" in lab else state
    for marker, label in lab.get("criteria", {}).items():
        results.append({"label": label, "passed": bool(evidence.get(marker))})
    return results


def public_labs(labs):
    return {
        identifier: {
            "title": lab["title"],
            "prompt": lab["prompt"],
            **({"editor": lab["editor"]} if "editor" in lab else {}),
            **({"wizard": True} if "wizard" in lab else {}),
            "fields": [
                {"name": name, "label": spec["label"], "options": spec.get("options")}
                for name, spec in lab["fields"].items()
            ],
        }
        for identifier, lab in labs.items()
    }
