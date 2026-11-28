"""Registro de columnas cifradas: qué se recifra al rotar la DEK de una clínica.

Cada columna lleva sus consultas escritas a mano (sin SQL armado con f-strings):
- `leer`: hasta `:n` filas de la clínica `:c` cuyo valor NO está cifrado con la versión
  `:v` (los bytes 2–5 del valor son la versión de la DEK, big-endian).
- `escribir`: guarda el valor recifrado `:valor` en la fila `:i`.
- `contar`: cuántos valores de la clínica faltan por recifrar.

`tests/db/test_rotacion.py` compara este registro con todas las columnas `bytea` del
esquema: una columna cifrada nueva que no se registre aquí hace fallar las pruebas.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import TextClause, text

from app.crypto.fields import FieldContext


@dataclass(frozen=True)
class ColumnaCifrada:
    tabla: str
    columna: str
    leer: TextClause
    escribir: TextClause
    contar: TextClause

    def contexto(self, clinica_id: UUID, fila_id: UUID) -> FieldContext:
        return FieldContext(self.tabla, self.columna, clinica_id, fila_id)


# Datos legales: viven en la fila de la clínica (fila_id = clinica_id).
_CLINICA = [
    ColumnaCifrada(
        "clinica",
        "rfc",
        text(
            "SELECT id, rfc AS valor FROM clinica WHERE id = :c "
            "AND substring(rfc from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE clinica SET rfc = :valor WHERE id = :i"),
        text("SELECT count(*) FROM clinica WHERE id = :c AND substring(rfc from 2 for 4) <> :v"),
    ),
    ColumnaCifrada(
        "clinica",
        "representante_nombre",
        text(
            "SELECT id, representante_nombre AS valor FROM clinica WHERE id = :c "
            "AND substring(representante_nombre from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE clinica SET representante_nombre = :valor WHERE id = :i"),
        text(
            "SELECT count(*) FROM clinica WHERE id = :c "
            "AND substring(representante_nombre from 2 for 4) <> :v"
        ),
    ),
    ColumnaCifrada(
        "clinica",
        "representante_curp",
        text(
            "SELECT id, representante_curp AS valor FROM clinica WHERE id = :c "
            "AND substring(representante_curp from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE clinica SET representante_curp = :valor WHERE id = :i"),
        text(
            "SELECT count(*) FROM clinica WHERE id = :c "
            "AND substring(representante_curp from 2 for 4) <> :v"
        ),
    ),
]

_PERSONAL = [
    ColumnaCifrada(
        "personal",
        "nombre",
        text(
            "SELECT id, nombre AS valor FROM personal WHERE clinica_id = :c "
            "AND substring(nombre from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE personal SET nombre = :valor WHERE id = :i"),
        text(
            "SELECT count(*) FROM personal WHERE clinica_id = :c "
            "AND substring(nombre from 2 for 4) <> :v"
        ),
    ),
    ColumnaCifrada(
        "personal",
        "contacto_preferido",
        text(
            "SELECT id, contacto_preferido AS valor FROM personal WHERE clinica_id = :c "
            "AND contacto_preferido IS NOT NULL "
            "AND substring(contacto_preferido from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE personal SET contacto_preferido = :valor WHERE id = :i"),
        text(
            "SELECT count(*) FROM personal WHERE clinica_id = :c "
            "AND contacto_preferido IS NOT NULL "
            "AND substring(contacto_preferido from 2 for 4) <> :v"
        ),
    ),
]

_PACIENTE = [
    ColumnaCifrada(
        "paciente",
        "nombre",
        text(
            "SELECT id, nombre AS valor FROM paciente WHERE clinica_id = :c "
            "AND substring(nombre from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE paciente SET nombre = :valor WHERE id = :i"),
        text(
            "SELECT count(*) FROM paciente WHERE clinica_id = :c "
            "AND substring(nombre from 2 for 4) <> :v"
        ),
    ),
    ColumnaCifrada(
        "paciente",
        "telefono",
        text(
            "SELECT id, telefono AS valor FROM paciente WHERE clinica_id = :c "
            "AND substring(telefono from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE paciente SET telefono = :valor WHERE id = :i"),
        text(
            "SELECT count(*) FROM paciente WHERE clinica_id = :c "
            "AND substring(telefono from 2 for 4) <> :v"
        ),
    ),
]

_AGENDA = [
    ColumnaCifrada(
        "evento_agenda",
        "comentario",
        text(
            "SELECT id, comentario AS valor FROM evento_agenda WHERE clinica_id = :c "
            "AND comentario IS NOT NULL AND substring(comentario from 2 for 4) <> :v LIMIT :n"
        ),
        text("UPDATE evento_agenda SET comentario = :valor WHERE id = :i"),
        text(
            "SELECT count(*) FROM evento_agenda WHERE clinica_id = :c "
            "AND comentario IS NOT NULL AND substring(comentario from 2 for 4) <> :v"
        ),
    ),
]

# Cifradas con la DEK de cada clínica: las recifra `rotacion dek`.
COLUMNAS_CLINICA: tuple[ColumnaCifrada, ...] = (*_CLINICA, *_PERSONAL, *_PACIENTE, *_AGENDA)

# Cifradas con la DEK de plataforma. Su rotación está pospuesta (exige recalcular los índices
# ciegos de correo y teléfono); la rotación de KEK sí reenvuelve la DEK de plataforma.
COLUMNAS_PLATAFORMA: tuple[tuple[str, str], ...] = (
    ("usuario", "email"),
    ("usuario", "totp_secret"),
    ("invitacion", "email"),
)

# `bytea` que NO son datos cifrados con una DEK (con el motivo).
BYTEA_NO_CIFRADAS: dict[tuple[str, str], str] = {
    ("clinica", "dek_wrapped"): "DEK envuelta con la KEK",
    ("clinica", "dek_anterior_wrapped"): "DEK anterior envuelta con la KEK (durante rotación)",
    ("llave_plataforma", "dek_wrapped"): "DEK de plataforma envuelta con la KEK",
    ("usuario", "email_idx"): "índice ciego (HMAC)",
    ("invitacion", "email_idx"): "índice ciego (HMAC)",
    ("paciente", "telefono_idx"): "índice ciego (HMAC)",
    ("invitacion", "token_hash"): "hash del token",
    ("sesion", "token_hash"): "hash del token",
    ("restablecimiento", "token_hash"): "hash del token",
    ("codigo_recuperacion", "codigo_hash"): "hash del código",
    ("intento_login", "clave_hash"): "HMAC de la clave de límite de intentos",
}


def params(clinica_id: UUID, version: bytes, n: int = 0) -> dict[str, Any]:
    return {"c": clinica_id, "v": version, "n": n}
