"""Formatos colombianos (dinero, cantidades, fechas) y utilidades de texto."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
WEEKDAYS_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _group(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fmt_money(value, sign: bool = False) -> str:
    """14000 -> "$ 14.000" (pesos colombianos, sin decimales)."""
    if value is None:
        return ""
    n = int(round(float(value)))
    prefix = "-" if n < 0 else ("+" if sign and n > 0 else "")
    return f"{prefix}$ {_group(abs(n))}"


def fmt_number(value, decimals: int = 0) -> str:
    if value is None:
        return ""
    v = float(value)
    if decimals == 0 or abs(v - round(v)) < 1e-9:
        return _group(int(round(v)))
    whole = int(abs(v))
    frac = f"{abs(v) - whole:.{decimals}f}"[2:].rstrip("0")
    s = _group(whole) + ("," + frac if frac else "")
    return ("-" if v < 0 else "") + s


def fmt_qty(value, unit: str = "") -> str:
    s = fmt_number(value, 2)
    return f"{s} {unit}".strip()


def fmt_pct(value) -> str:
    if value is None:
        return ""
    return f"{float(value) * 100:.1f} %".replace(".", ",")


def parse_money(text: str) -> int:
    """Acepta "14.000", "$14,000", "14k", "1,5k", "1.2m". Devuelve pesos enteros."""
    if text is None:
        return 0
    s = str(text).strip().lower().replace("$", "").replace(" ", "")
    if not s:
        return 0
    mult = 1
    if s.endswith("k"):
        mult, s = 1000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    neg = s.startswith("-")
    s = s.lstrip("-+")
    if mult > 1:
        # en "1,5k" o "1.5k" el separador es decimal
        s = s.replace(",", ".")
        if s.count(".") > 1:
            s = s.replace(".", "")
    else:
        # en pesos los puntos y comas son separadores de miles
        s = s.replace(".", "").replace(",", "")
    try:
        value = float(s) * mult if s else 0.0
    except ValueError:
        return 0
    return -int(round(value)) if neg else int(round(value))


def parse_float(text: str) -> float:
    """Cantidades en formato colombiano: punto de miles y coma decimal.

    "6.000" -> 6000 · "1.500" -> 1500 · "2,5" -> 2.5 · "2.5" -> 2.5 · "1.234,5" -> 1234.5 · "0.250" -> 0.25
    (debe poder leer de vuelta lo que escribe fmt_number).
    """
    if text is None:
        return 0.0
    s = str(text).strip().replace(" ", "")
    if not s:
        return 0.0
    neg = s.startswith("-")
    s = s.lstrip("+-")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # 1.234,5
            s = s.replace(".", "").replace(",", ".")
        else:  # 1,234.5 (formato inglés)
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    elif s.count(".") > 1 or re.fullmatch(r"[1-9]\d{0,2}(\.\d{3})+", s):
        s = s.replace(".", "")  # puntos de miles: 6.000, 1.250.000
    try:
        value = float(s)
    except ValueError:
        return 0.0
    return -value if neg else value


def fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%d/%m/%Y")


def fmt_datetime(d) -> str:
    """14/10/26 5:50 p. m."""
    if d is None:
        return ""
    return f"{d:%d/%m/%y} {fmt_time(d)}"


def fmt_time(d) -> str:
    """5:50 p. m. (formato de 12 horas usado en Colombia)."""
    if d is None:
        return ""
    hour = d.hour % 12 or 12
    return f"{hour}:{d.minute:02d} {'a. m.' if d.hour < 12 else 'p. m.'}"


def utc_to_local(d: datetime | None) -> datetime | None:
    """Fecha guardada en UTC (sin zona) -> hora local del PC."""
    if d is None:
        return None
    from datetime import timezone

    return d.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def local_to_utc(d: datetime | None) -> datetime | None:
    """Hora local del PC (sin zona) -> UTC sin zona (como se guarda `created_at`)."""
    if d is None:
        return None
    from datetime import timezone

    return d.astimezone(timezone.utc).replace(tzinfo=None)


def fmt_long_date(d: date) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return f"{WEEKDAYS[d.weekday()]} {d.day} de {MONTHS[d.month - 1]} de {d.year}"


def month_label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1].capitalize()} {year}"


def day_range(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def period_range(start: date, end: date) -> tuple[datetime, datetime]:
    """Rango [inicio, fin] inclusivo en días -> datetimes [desde, hasta)."""
    return datetime(start.year, start.month, start.day), datetime(end.year, end.month, end.day) + timedelta(days=1)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return first, nxt - timedelta(days=1)


def normalize(text: str) -> str:
    """Minúsculas sin tildes ni espacios repetidos: para búsquedas y comparaciones."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def matches(query: str, *fields) -> bool:
    """Todas las palabras de la búsqueda aparecen en alguno de los campos."""
    q = normalize(query)
    if not q:
        return True
    hay = " ".join(normalize(f) for f in fields if f)
    return all(word in hay for word in q.split())
