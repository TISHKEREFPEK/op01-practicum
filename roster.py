"""Create and update classroom accounts without placing passwords in command arguments."""
import argparse
from getpass import getpass
from pathlib import Path

from classroom import ROLES, account, read_roster, valid_profile, write_roster


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("roster", type=Path)
    parser.add_argument("login")
    parser.add_argument("role", choices=sorted(ROLES))
    args = parser.parse_args()
    if not valid_profile(args.login):
        parser.error("Введите имя длиной до 48 символов.")
    password = getpass("Пароль учётной записи: ")
    if not 12 <= len(password) <= 200:
        parser.error("Пароль должен содержать от 12 до 200 символов.")
    if password != getpass("Повторите пароль: "):
        parser.error("Пароли не совпадают.")
    try:
        result = read_roster(args.roster) if args.roster.exists() else {}
        result[args.login] = account(password, args.role)
        write_roster(args.roster, result)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print("Учётная запись сохранена.")


if __name__ == "__main__":
    main()
