"""An offline UEFI installation scenario on simulated disks."""

STAGES = (
    {
        "id": "image",
        "title": "Загрузочный образ",
        "action": "Подготовить носитель",
        "fields": [{
            "label": "Образ Debian 13",
            "options": {"dvd-amd64": "DVD · amd64", "netinst-amd64": "Netinst · amd64", "dvd-arm64": "DVD · arm64"},
        }],
        "expected": ["dvd-amd64"],
        "error": "Для автономной установки на этой машине нужен полный DVD-образ для amd64.",
        "success": "Носитель подготовлен. Учебная машина загрузилась с DVD.",
    },
    {
        "id": "disk",
        "title": "Диск и разметка",
        "action": "Применить разметку",
        "fields": [
            {"label": "Диск", "options": {"vda": "/dev/vda · учебные данные", "vdb": "/dev/vdb · пустой диск 32 ГиБ"}},
            {"label": "Схема разделов", "options": {
                "gpt-efi-ext4": "GPT · EFI FAT32 и корень ext4",
                "gpt-ext4": "GPT · только корень ext4",
                "mbr-ext4": "MBR · только корень ext4",
            }},
        ],
        "expected": ["vdb", "gpt-efi-ext4"],
        "error": "Выберите пустой диск /dev/vdb. Для UEFI нужны системный раздел EFI и раздел для корня.",
        "success": "На /dev/vdb созданы раздел EFI и корневой раздел ext4.",
    },
    {
        "id": "settings",
        "title": "Параметры системы",
        "action": "Сохранить параметры",
        "fields": [
            {"label": "Язык", "options": {"ru_RU.UTF-8": "Русский", "en_US.UTF-8": "Английский"}},
            {"label": "Часовой пояс", "options": {"Europe/Moscow": "Москва", "UTC": "UTC"}},
            {"label": "Учётная запись", "options": {"student": "student", "admin": "admin"}},
        ],
        "expected": ["ru_RU.UTF-8", "Europe/Moscow", "student"],
        "error": "По условию нужны русский язык, часовой пояс Москва и пользователь student.",
        "success": "Параметры установщика сохранены.",
    },
    {
        "id": "install",
        "title": "Установка",
        "action": "Установить Debian",
        "fields": [],
        "expected": [],
        "error": "",
        "success": "Debian установлен на /dev/vdb. Установочный носитель отсоединён.",
    },
    {
        "id": "boot",
        "title": "Первый запуск",
        "action": "Загрузиться с диска",
        "fields": [],
        "expected": [],
        "error": "",
        "success": "Debian запущен с /dev/vdb. Проверьте систему и сетевое устройство в консоли.",
    },
)
INSTALLER_COMMANDS = (
    "cat /etc/os-release", "findmnt /", "locale", "timedatectl", "whoami", "lspci -k",
    "sudo modprobe ИМЯ_МОДУЛЯ", "lab-reset",
)
BOOT_COMMANDS = {
    "cat /etc/os-release": ("version_read", 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nVERSION_ID="13"'),
    "findmnt /": ("root_read", "TARGET SOURCE     FSTYPE OPTIONS\n/      /dev/vdb2  ext4   rw,relatime"),
    "locale": ("locale_read", "LANG=ru_RU.UTF-8"),
    "timedatectl": ("timezone_read", "Time zone: Europe/Moscow (MSK, +0300)"),
    "whoami": ("account_read", "student"),
}


def wizard(state):
    stage = state.get("stage", 0)
    if stage >= len(STAGES):
        return {"stage": stage, "title": "Debian запущен", "message": state.get("message", "")}
    data = STAGES[stage]
    return {
        "stage": stage, "total": len(STAGES), "id": data["id"], "title": data["title"], "action": data["action"],
        "fields": data["fields"], "message": state.get("message", ""),
    }


def install(command, state):
    if command == "installer status":
        return ""
    if command == "lab-reset":
        state.clear()
        return "Учебная машина возвращена к началу установки."
    stage = state.get("stage", 0)
    parts = command.split()
    if parts[:1] == ["installer"]:
        if stage >= len(STAGES) or len(parts) < 2 or parts[1] != STAGES[stage]["id"]:
            return "Сначала завершите текущий шаг установщика."
        data = STAGES[stage]
        if parts[2:] != data["expected"]:
            state["message"] = data["error"] or "Проверьте параметры шага."
        else:
            state.update(stage=stage + 1, message=data["success"])
        return state["message"]
    loading_driver = parts[:2] == ["sudo", "modprobe"] and len(parts) == 3
    if command in BOOT_COMMANDS or command == "lspci -k" or loading_driver:
        if stage < len(STAGES):
            return "Эта команда доступна после первого запуска с диска."
        if command == "lspci -k":
            loaded = state.get("driver_loaded", False)
            state["driver_read"] = loaded
            driver = "\tKernel driver in use: e1000e\n" if loaded else ""
            return ("00:03.0 Ethernet controller: Intel 82574L Gigabit Network Connection\n"
                    f"{driver}\tKernel modules: e1000e")
        if loading_driver:
            if parts[2] != "e1000e":
                return f"modprobe: модуль {parts[2]} отсутствует в учебной системе."
            state["driver_loaded"] = True
            return "Модуль e1000e загружен. Проверьте привязку драйвера через lspci -k."
        marker, output = BOOT_COMMANDS[command]
        state[marker] = True
        return output
    return None


def installer_checks(state):
    stage = state.get("stage", 0)
    return {
        "media": stage >= 1,
        "layout": stage >= 2,
        "installed": stage >= 5 and state.get("root_read"),
        "setup": stage >= 3 and all(state.get(key) for key in ("locale_read", "timezone_read", "account_read")),
    }
