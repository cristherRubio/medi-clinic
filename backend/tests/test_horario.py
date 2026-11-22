"""Zona horaria y horario laboral (lógica pura)."""

from datetime import UTC, datetime

import pytest
from app.horario import Horario, a_utc, cargar_horario, validar_zona
from pydantic import ValidationError

CDMX = "America/Mexico_City"  # UTC-6 todo el año


def _h(**dias: list[list[str]]) -> Horario:
    return Horario.model_validate(dias)


def _local(dia: int, hhmm: str) -> datetime:
    """2026-11-23 es lunes; `dia` 0 = lunes. Hora de CDMX → UTC."""
    h, m = hhmm.split(":")
    return a_utc(datetime(2026, 11, 23 + dia, int(h), int(m)), CDMX)


def test_validar_zona() -> None:
    assert validar_zona("America/Tijuana") == "America/Tijuana"
    for mala in ("Marte/Base", "", "../etc/passwd"):
        with pytest.raises(ValueError, match="Zona horaria"):
            validar_zona(mala)


@pytest.mark.parametrize(
    "dias",
    [
        {"lun": [["10:00", "09:00"]]},  # termina antes de empezar
        {"lun": [["09:00", "09:00"]]},
        {"lun": [["09:00", "14:00"], ["13:00", "16:00"]]},  # traslape
        {"lun": [["25:00", "26:00"]]},
        {"lun": [["9:00", "14:00"]]},
        {"lunes": [["09:00", "14:00"]]},  # día desconocido
    ],
)
def test_horario_invalido(dias: dict[str, list[list[str]]]) -> None:
    with pytest.raises(ValidationError):
        Horario.model_validate(dias)


def test_horario_ordena_tramos_y_acepta_24() -> None:
    h = _h(lun=[["16:00", "24:00"], ["09:00", "14:00"]])
    assert h.lun == [("09:00", "14:00"), ("16:00", "24:00")]
    assert h.mar == []


def test_sin_configurar_todo_cabe() -> None:
    h = cargar_horario({})
    assert not h.configurado()
    assert h.dentro(_local(6, "03:00"), _local(6, "04:00"), CDMX)


@pytest.mark.parametrize(
    ("dia", "ini", "fin", "esperado"),
    [
        (0, "09:00", "09:30", True),
        (0, "13:30", "14:00", True),
        (0, "13:45", "14:15", False),  # se sale del tramo
        (0, "14:00", "16:00", False),  # entre tramos
        (0, "08:45", "09:15", False),
        (0, "16:00", "20:00", True),
        (6, "10:00", "11:00", False),  # domingo cerrado
    ],
)
def test_dentro(dia: int, ini: str, fin: str, esperado: bool) -> None:
    h = _h(lun=[["09:00", "14:00"], ["16:00", "20:00"]])
    assert h.dentro(_local(dia, ini), _local(dia, fin), CDMX) is esperado


def test_dentro_hasta_medianoche() -> None:
    h = _h(lun=[["20:00", "24:00"]])
    assert h.dentro(_local(0, "23:00"), _local(1, "00:00"), CDMX)
    assert not h.dentro(_local(0, "23:00"), _local(1, "00:30"), CDMX)


def test_a_utc() -> None:
    assert a_utc(datetime(2026, 11, 23, 10, 0), CDMX) == datetime(2026, 11, 23, 16, 0, tzinfo=UTC)
    # Tijuana en noviembre: UTC-8.
    assert a_utc(datetime(2026, 11, 23, 10, 0), "America/Tijuana") == datetime(
        2026, 11, 23, 18, 0, tzinfo=UTC
    )
    explicita = datetime.fromisoformat("2026-11-23T10:00:00-05:00")
    assert a_utc(explicita, CDMX) == datetime(2026, 11, 23, 15, 0, tzinfo=UTC)
