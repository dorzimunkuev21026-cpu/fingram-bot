"""Данные покупателей. Хранится только: Telegram-ID, время принятия оферты, время и сумма оплаты."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# На Bothost сохраняется только папка /app/data, поэтому данные кладём туда, если она есть.
DATA_DIR = Path(os.environ.get("DATA_DIR") or ("/app/data" if Path("/app/data").is_dir() else Path(__file__).parent))
BUYERS_FILE = DATA_DIR / "buyers.json"
CIRCLES_FILE = DATA_DIR / "circles.json"  # id кружочков в нужном порядке


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path=None):
    path = path or BUYERS_FILE
    if not path.exists():
        return {}
    # Битый файл даст ошибку, а не молча сбросит список покупателей.
    return json.loads(path.read_text(encoding="utf-8"))


def _write(data, path=None):
    path = path or BUYERS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)  # читать может только владелец файла
    tmp.replace(path)


def has_paid(user_id, path=None):
    return "paid_at" in _load(path).get(str(user_id), {})


def has_accepted(user_id, path=None):
    return "accepted_at" in _load(path).get(str(user_id), {})


def save_accept(user_id, path=None):
    """Время нажатия «Принимаю оферту». Доступ к продукту это НЕ даёт."""
    data = _load(path)
    record = data.setdefault(str(user_id), {})
    if "paid_at" not in record:
        record["accepted_at"] = _now()
    _write(data, path)


def save_buyer(user_id, amount_rub, path=None):
    data = _load(path)
    record = data.setdefault(str(user_id), {})
    record.setdefault("paid_at", _now())
    record.setdefault("amount_rub", amount_rub)
    _write(data, path)


def get_circles(path=None):
    path = path or CIRCLES_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def add_circle(file_id, path=None):
    path = path or CIRCLES_FILE
    data = get_circles(path) + [file_id]
    _write(data, path)
    return len(data)


def clear_circles(path=None):
    _write([], path or CIRCLES_FILE)
