"""Optional roster-authenticated mode with short-lived server-side sessions."""
import hashlib
from hmac import compare_digest
from http.cookies import CookieError, SimpleCookie
import json
import re
import secrets
from tempfile import NamedTemporaryFile
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic


COOKIE = "op01_session"
SESSION_SECONDS = 8 * 60 * 60
ROLES = {"student", "teacher"}


def valid_profile(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[\w .-]{1,48}", value)) and bool(value.strip())


def password_digest(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()


def account(password, role):
    salt = secrets.token_hex(16)
    return {"role": role, "salt": salt, "digest": password_digest(password, salt)}


def read_roster(path):
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Список учётных записей должен быть объектом JSON.")
    for login, record in result.items():
        if (not valid_profile(login) or not isinstance(record, dict)
                or record.keys() != {"role", "salt", "digest"}
                or not isinstance(record["role"], str) or record["role"] not in ROLES
                or not isinstance(record["salt"], str) or not re.fullmatch(r"[a-f0-9]{32}", record["salt"])
                or not isinstance(record["digest"], str) or not re.fullmatch(r"[a-f0-9]{64}", record["digest"])):
            raise ValueError("В списке есть некорректная учётная запись.")
    return result


def write_roster(path, result):
    with NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as output:
        pending = Path(output.name)
        try:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.close()
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def token_from_cookie(header):
    try:
        cookie = SimpleCookie(header or "").get(COOKIE)
    except CookieError:
        return ""
    return cookie.value if cookie else ""


def cookie_header(token):
    age = SESSION_SECONDS if token else 0
    return f"{COOKIE}={token}; Path=/; Max-Age={age}; HttpOnly; SameSite=Strict; Secure"


class Classroom:
    def __init__(self, roster):
        self.roster = roster
        self.students = {login for login, record in roster.items() if record["role"] == "student"}
        self.sessions = {}
        self.lock = Lock()
        self.hash_slot = BoundedSemaphore(4)

    def sign_in(self, login, password):
        if not valid_profile(login) or not isinstance(password, str) or not 1 <= len(password) <= 200:
            return None
        record = self.roster.get(login)
        digest = record["digest"] if record else "0" * 64
        salt = record["salt"] if record else "0" * 32
        if not self.hash_slot.acquire(timeout=3):
            raise TimeoutError("Password verification is busy")
        try:
            matches = compare_digest(digest, password_digest(password, salt))
        finally:
            self.hash_slot.release()
        if not matches or record is None:
            return None
        now = monotonic()
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions = {key: value for key, value in self.sessions.items() if value[1] > now}
            self.sessions[token] = (login, now + SESSION_SECONDS)
        return token

    def identity(self, token):
        with self.lock:
            session = self.sessions.get(token)
            if session is None:
                return None
            login, expires = session
            if expires <= monotonic():
                self.sessions.pop(token, None)
                return None
        return {"profile": login, "teacher": self.roster[login]["role"] == "teacher"}

    def sign_out(self, token):
        with self.lock:
            self.sessions.pop(token, None)
