"""Matriz de permisos (sección 5) como datos. Función pura, sin BD."""

from enum import StrEnum


class Rol(StrEnum):
    ADMIN = "admin"
    ASISTENTE = "asistente"
    MEDICO = "medico"


class Alcance(StrEnum):
    TODOS = "todos"
    PROPIOS = "propios"  # médico: solo sus pacientes y su agenda


class Accion(StrEnum):
    VER_PACIENTES = "ver_pacientes"
    GESTIONAR_CITAS = "gestionar_citas"  # crear, editar, cancelar
    BLOQUEAR_AGENDA = "bloquear_agenda"
    CREAR_PACIENTE = "crear_paciente"
    MARCAR_OPTIN = "marcar_optin"
    REACTIVAR_RECORDATORIOS = "reactivar_recordatorios"
    VINCULAR_PACIENTES = "vincular_pacientes"
    AGREGAR_MEDICOS = "agregar_medicos"
    AGREGAR_ASISTENTES = "agregar_asistentes"
    GESTIONAR_SALAS = "gestionar_salas"
    CONFIGURAR_CLINICA = "configurar_clinica"
    BORRAR = "borrar"
    VER_PERSONAL = "ver_personal"
    EDITAR_PERSONAL = "editar_personal"
    VER_SALAS = "ver_salas"


_A, _S, _M = Rol.ADMIN, Rol.ASISTENTE, Rol.MEDICO
_T, _P = Alcance.TODOS, Alcance.PROPIOS

# Rol ausente = sin permiso. El operador no figura: nunca entra por aquí.
MATRIZ: dict[Accion, dict[Rol, Alcance]] = {
    Accion.VER_PACIENTES: {_A: _T, _S: _T, _M: _P},
    Accion.GESTIONAR_CITAS: {_A: _T, _S: _T, _M: _P},
    Accion.BLOQUEAR_AGENDA: {_A: _T, _S: _T, _M: _P},
    Accion.CREAR_PACIENTE: {_A: _T, _S: _T, _M: _T},
    Accion.MARCAR_OPTIN: {_A: _T, _S: _T, _M: _P},
    Accion.REACTIVAR_RECORDATORIOS: {_A: _T, _S: _T, _M: _P},
    Accion.VINCULAR_PACIENTES: {_A: _T, _S: _T},
    Accion.AGREGAR_MEDICOS: {_A: _T, _S: _T},
    Accion.AGREGAR_ASISTENTES: {_A: _T},
    Accion.GESTIONAR_SALAS: {_A: _T},
    Accion.CONFIGURAR_CLINICA: {_A: _T},
    Accion.BORRAR: {_A: _T},
    Accion.VER_PERSONAL: {_A: _T, _S: _T, _M: _P},
    Accion.EDITAR_PERSONAL: {_A: _T},
    Accion.VER_SALAS: {_A: _T, _S: _T, _M: _T},
}


def alcance(rol: Rol, accion: Accion) -> Alcance | None:
    return MATRIZ[accion].get(rol)
