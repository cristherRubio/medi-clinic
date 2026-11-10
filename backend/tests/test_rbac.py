"""La matriz de permisos coincide con la sección 5 (tabla escrita aparte, no leída de MATRIZ)."""

import pytest
from app.auth.rbac import Accion, Alcance, Rol, alcance

T, P = Alcance.TODOS, Alcance.PROPIOS
# (admin, asistente, médico); None = sin permiso
ESPERADO: dict[Accion, tuple[Alcance | None, Alcance | None, Alcance | None]] = {
    Accion.VER_PACIENTES: (T, T, P),
    Accion.GESTIONAR_CITAS: (T, T, P),
    Accion.BLOQUEAR_AGENDA: (T, T, P),
    Accion.CREAR_PACIENTE: (T, T, T),
    Accion.MARCAR_OPTIN: (T, T, P),
    Accion.REACTIVAR_RECORDATORIOS: (T, T, P),
    Accion.VINCULAR_PACIENTES: (T, T, None),
    Accion.AGREGAR_MEDICOS: (T, T, None),
    Accion.AGREGAR_ASISTENTES: (T, None, None),
    Accion.GESTIONAR_SALAS: (T, None, None),
    Accion.CONFIGURAR_CLINICA: (T, None, None),
    Accion.BORRAR: (T, None, None),
}
ROLES = (Rol.ADMIN, Rol.ASISTENTE, Rol.MEDICO)


def test_todas_las_acciones_cubiertas() -> None:
    assert set(ESPERADO) == set(Accion)


@pytest.mark.parametrize("accion", list(Accion))
@pytest.mark.parametrize("i", range(3))
def test_matriz(accion: Accion, i: int) -> None:
    assert alcance(ROLES[i], accion) == ESPERADO[accion][i]
