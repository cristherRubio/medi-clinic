"""Zona horaria y horario laboral de la clínica. Lógica pura, sin BD.

`horario_laboral` se guarda como `{"lun": [["09:00", "14:00"], ...], ..., "dom": []}`.
Sin ningún tramo configurado (p. ej. `{}`) no hay restricción de horario.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

DIAS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")  # índice = datetime.weekday()


def validar_zona(zona: str) -> str:
    try:
        ZoneInfo(zona)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError("Zona horaria inválida") from None
    return zona


ZonaHoraria = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    AfterValidator(validar_zona),
]
# "24:00" solo tiene sentido como fin de un tramo.
Hora = Annotated[str, StringConstraints(pattern=r"^(([01][0-9]|2[0-3]):[0-5][0-9]|24:00)$")]


def _validar_tramos(tramos: list[tuple[str, str]]) -> list[tuple[str, str]]:
    ordenados = sorted(tramos)
    for inicio, fin in ordenados:
        if inicio >= fin:
            raise ValueError("Cada tramo debe terminar después de empezar")
    for (_, fin_a), (inicio_b, _) in zip(ordenados, ordenados[1:], strict=False):
        if inicio_b < fin_a:
            raise ValueError("Los tramos de un día no deben traslaparse")
    return ordenados


Tramos = Annotated[
    list[tuple[Hora, Hora]],
    Field(default_factory=list, max_length=6),
    AfterValidator(_validar_tramos),
]


class Horario(BaseModel):
    """Tramos por día de la semana, en la hora local de la clínica."""

    model_config = ConfigDict(extra="forbid")

    lun: Tramos
    mar: Tramos
    mie: Tramos
    jue: Tramos
    vie: Tramos
    sab: Tramos
    dom: Tramos

    def configurado(self) -> bool:
        return any(getattr(self, d) for d in DIAS)

    def dentro(self, inicio: datetime, fin: datetime, zona: str) -> bool:
        """¿El intervalo [inicio, fin) cabe en un solo tramo de su día (hora de la clínica)?

        Sin tramos configurados, todo cabe. Un evento que cruza la medianoche no cabe
        (salvo que termine justo a las 00:00).
        """
        if not self.configurado():
            return True
        tz = ZoneInfo(zona)
        ini, fn = inicio.astimezone(tz), fin.astimezone(tz)
        m_ini = _minutos(ini)
        if fn.date() == ini.date():
            m_fin = _minutos(fn)
        elif (fn - ini).days == 0 and _minutos(fn) == 0 and fn.date() > ini.date():
            m_fin = 24 * 60.0
        else:
            return False
        tramos: list[tuple[str, str]] = getattr(self, DIAS[ini.weekday()])
        return any(_hm(t_ini) <= m_ini and m_fin <= _hm(t_fin) for t_ini, t_fin in tramos)


def _minutos(momento: datetime) -> float:
    return momento.hour * 60 + momento.minute + momento.second / 60 + momento.microsecond / 6e7


def _hm(hora: str) -> float:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def cargar_horario(valor: Any) -> Horario:
    """Desde el jsonb de la BD (`{}` = sin configurar)."""
    return Horario.model_validate(valor or {})


def a_utc(momento: datetime, zona: str) -> datetime:
    """Sin zona explícita, la fecha se interpreta en la zona de la clínica."""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZoneInfo(zona))
    return momento.astimezone(UTC)
