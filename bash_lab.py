"""Small, deterministic Bash subset for the archive-writing exercise."""
import re


SCRIPT = "~/backup.sh"
SAMPLES = {
    "materials": ("guide.txt", "tables/values.csv"),
    "logs": ("first.log", "second.log"),
}
MANUAL = "bash backup.sh materials course.tar.gz"
COMMANDS = (MANUAL, "bash backup.sh absent course.tar.gz", "ls", "cat ~/backup.sh", "lab-reset")
TOKEN = re.compile(r"""(?:'[^'\n]*'|"[^"\n]*"|[^ \t\r\n;&|'"\\`<>#])+|&&|\|\||;|[ \t\r]+|#[^\n]*|\n""")
PART = re.compile(r"""'[^']*'|"[^"]*"|[^'"]+""")
VARIABLE = re.compile(r"\$(?:\{([\w?]+)\}|([a-zA-Z_]\w*|[0-9?]))")


def lex(text):
    tokens = []
    cursor = 0
    while cursor < len(text):
        match = TOKEN.match(text, cursor)
        if not match:
            raise ValueError("В этом тренажёре доступны простые команды, if и &&/||.")
        value = match[0]
        cursor = match.end()
        if value in ("\n", ";"):
            if tokens and tokens[-1] not in (";", "&&", "||"):
                tokens.append(";")
        elif not value.isspace() and not value.startswith("#"):
            tokens.append(value)
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = iter(tokens)
        self.current = next(self.tokens, None)

    def advance(self):
        token = self.current
        self.current = next(self.tokens, None)
        return token

    def expect(self, token):
        if self.current != token:
            raise ValueError(f"Ожидается {token}.")
        self.advance()

    def block(self, stop=()):
        commands = []
        while self.current is not None and self.current not in stop:
            if self.current == ";":
                self.advance()
                continue
            if self.current == "if":
                self.advance()
                condition = self.chain()
                self.expect(";")
                self.expect("then")
                yes = self.block(("else", "fi"))
                no = []
                if self.current == "else":
                    self.advance()
                    no = self.block(("fi",))
                self.expect("fi")
                commands.append(("if", condition, yes, no))
            else:
                commands.append(("chain", self.chain()))
            if self.current not in (None, ";", *stop):
                raise ValueError("Разделите команды переводом строки или точкой с запятой.")
        return commands

    def words(self):
        words = []
        while self.current not in (None, ";", "&&", "||"):
            if self.current in ("then", "else", "fi") and not words:
                break
            words.append(self.advance())
        if not words:
            raise ValueError("Ожидается команда.")
        return words

    def chain(self):
        chain = [(None, self.words())]
        while self.current in ("&&", "||"):
            operator = self.advance()
            chain.append((operator, self.words()))
        return chain


class ExitScript(Exception):
    pass


class Trial:
    def __init__(self, directory, output):
        self.variables = {"0": "backup.sh", "1": directory, "2": output}
        self.status = 0
        self.archives = {}
        self.messages = []

    def expand(self, token):
        parts = []
        for part in PART.findall(token):
            if part.startswith("'"):
                parts.append(part[1:-1])
                continue
            quoted = part.startswith('"')
            if quoted:
                part = part[1:-1]
            if "$" in VARIABLE.sub("", part):
                raise ValueError("Поддерживаются параметры $1, $2 и простые переменные.")
            expanded = VARIABLE.sub(lambda match: self.value(match[1] or match[2]), part)
            if not quoted and any(char.isspace() for char in expanded):
                raise ValueError("Заключите переменную с пробелами в двойные кавычки.")
            parts.append(expanded)
        return "".join(parts)

    def value(self, name):
        return str(self.status) if name == "?" else self.variables.get(name, "")

    def execute(self, words):
        if len(words) == 1 and (assignment := re.fullmatch(r"([a-zA-Z_]\w*)=(.*)", words[0])):
            self.variables[assignment[1]] = self.expand(assignment[2])
            return 0
        name, *args = map(self.expand, words)
        if name in ("[", "test"):
            if name == "[":
                if args[-1:] != ["]"]:
                    raise ValueError("Закройте условие символом ].")
                args = args[:-1]
            inverted = bool(args and args[0] == "!")
            if inverted:
                args = args[1:]
            if len(args) != 2 or args[0] != "-d":
                raise ValueError("Для проверки каталога используйте test -d.")
            return int((args[1].rstrip("/") in SAMPLES) == inverted)
        if name == "echo":
            self.messages.append(" ".join(args))
            return 0
        if name == "exit":
            if len(args) > 1 or (args and not re.fullmatch(r"[0-9]{1,3}", args[0])):
                raise ValueError("Укажите числовой код выхода.")
            raise ExitScript(int(args[0]) % 256 if args else self.status)
        if name == "tar":
            return self.tar(args)
        raise ValueError(f"Команда {name!r} в этом упражнении не поддерживается.")

    def tar(self, args):
        if len(args) not in (3, 5) or args[0] != "-czf":
            raise ValueError("Для архива используйте tar -czf.")
        target = args[1]
        if len(args) == 5 and (args[2] != "-C" or args[4] != "."):
            raise ValueError("После -C укажите каталог, затем точку.")
        if not re.fullmatch(r"[a-zA-Z0-9._-]+\.tar\.gz", target):
            raise ValueError("Укажите имя выходного файла с расширением .tar.gz.")
        folder = (args[3] if len(args) == 5 else args[2]).rstrip("/")
        if folder not in SAMPLES:
            self.archives[target] = ()
            self.messages.append(f"tar: {folder}: No such file or directory")
            return 2
        self.archives[target] = SAMPLES[folder]
        return 0

    def chain(self, chain):
        for connector, words in chain:
            if (connector == "&&" and self.status != 0) or (connector == "||" and self.status == 0):
                continue
            self.status = self.execute(words)

    def block(self, statements):
        for kind, *parts in statements:
            self.chain(parts[0])
            if kind == "if":
                branch = parts[1] if self.status == 0 else parts[2]
                self.status = 0
                self.block(branch)


def run_script(text, directory, archive):
    trial = Trial(directory, archive)
    try:
        trial.block(Parser(lex(text)).block())
    except ExitScript as stop:
        trial.status = stop.args[0]
    except ValueError as error:
        trial.messages.append(str(error))
        trial.status = 2
        return trial, False
    return trial, True


def automation(command, state):
    text = state.get("document")
    if command == "lab-reset":
        state.clear()
        return "Учебная папка и скрипт сброшены."
    if command == "ls":
        names = [*SAMPLES, *state.get("archives", [])]
        return "  ".join(names + (["backup.sh"] if text is not None else []))
    if command in ("cat ~/backup.sh", "cat backup.sh"):
        return text if text is not None else "cat: backup.sh: No such file or directory"
    words = command.split()
    if len(words) == 4 and words[0] == "bash" and words[1] in ("backup.sh", "./backup.sh", SCRIPT):
        if text is None:
            return "Сначала сохраните скрипт в редакторе."
        trial, valid = run_script(text, *words[2:])
        state["archives"] = list(trial.archives)
        if valid:
            state["trial_script"] = text
        return "\n".join([*trial.messages, *(f"Создан архив {name}" for name in trial.archives),
                          f"Код завершения: {trial.status}"])
    return None


def automation_checks(state):
    text = state.get("document", "")
    tests = {}
    for sample, output in (("materials", "course.tar.gz"), ("logs", "logs-copy.tar.gz"), ("absent", "not-created.tar.gz")):
        trial, valid = run_script(text, sample, output)
        if sample in SAMPLES:
            tests[sample] = valid and trial.status == 0 and trial.archives == {output: SAMPLES[sample]}
        else:
            tests[sample] = valid and trial.status != 0 and not trial.archives
    return {"script": bool(text.strip()), "trial": bool(text.strip()) and state.get("trial_script") == text, **tests}
