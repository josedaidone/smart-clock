import getpass

from werkzeug.security import check_password_hash

from smart_clock.__main__ import main
from smart_clock.config import load_config

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_hash_password_prints_a_line_the_config_accepts(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "a long enough password")
    assert main(["hash-password", "--user", "jose"]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    stored = tomllib.loads(line)["jose"]
    assert "a long enough password" not in line
    assert check_password_hash(stored, "a long enough password")

    config_file = tmp_path / "config.toml"
    config_file.write_text("[web.users]\n" + line + "\n")
    assert load_config(config_file).web.users == {"jose": stored}


def test_hash_password_rejects_short_passwords(monkeypatch, capsys):
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "short")
    assert main(["hash-password"]) == 1
    assert "8 characters" in capsys.readouterr().err


def test_bad_config_exits_with_a_readable_message(tmp_path, capsys):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[display]\nbrightnes = 3\n")
    assert main(["run", "--simulate", "--config", str(config_file)]) == 2
    assert "unknown setting" in capsys.readouterr().err
