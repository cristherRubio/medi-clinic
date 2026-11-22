"""Toda ruta que modifica datos está en esta tabla con la acción de auditoría que registra.

La tabla se escribe a mano (no se deriva del código). `tests/api/test_auditoria.py` ejecuta
cada ruta y comprueba que se registró esa acción. Al agregar un endpoint que modifica
(POST/PATCH/PUT/DELETE), agrégalo aquí o este archivo falla.
"""

from app.main import create_app

Ruta = tuple[str, str]

# Rutas que modifican pero no escriben datos (con el motivo).
EXENTAS: dict[Ruta, str] = {
    ("POST", "/api/pacientes/buscar"): "solo lectura; POST para no poner el nombre en la URL",
}

# grupo → {(método, ruta): acción registrada en el caso exitoso}
GRUPOS: dict[str, dict[Ruta, str]] = {
    "auth": {
        ("POST", "/api/auth/login"): "login_ok",
        ("POST", "/api/auth/login/totp"): "login_ok",
        ("POST", "/api/auth/login/recuperacion"): "login_ok",
        ("POST", "/api/auth/logout"): "logout",
        ("POST", "/api/auth/contexto"): "contexto_elegido",
    },
    "activacion": {
        ("POST", "/api/auth/activar/iniciar"): "activacion_iniciada",
        ("POST", "/api/auth/activar/confirmar"): "activacion_ok",
        ("POST", "/api/auth/activar/aceptar"): "invitacion_aceptada",
    },
    "operador": {
        ("POST", "/api/operador/clinicas"): "clinica_creada",
        ("PATCH", "/api/operador/clinicas/{clinica_id}"): "clinica_actualizada",
        ("POST", "/api/operador/invitaciones/{invitacion_id}/revocar"): "invitacion_revocada",
        ("POST", "/api/operador/invitaciones/{invitacion_id}/extender"): "invitacion_extendida",
    },
    "clinica": {
        ("PATCH", "/api/clinica"): "clinica_configurada",
        ("POST", "/api/salas"): "sala_creada",
        ("PATCH", "/api/salas/{sala_id}"): "sala_editada",
        ("PATCH", "/api/personal/{personal_id}"): "personal_editado",
        ("POST", "/api/personal/{personal_id}/desactivar"): "personal_desactivado",
        ("POST", "/api/personal/{personal_id}/reactivar"): "personal_reactivado",
        ("POST", "/api/personal/invitaciones"): "invitacion_creada",
        ("POST", "/api/personal/invitaciones/{invitacion_id}/revocar"): "invitacion_revocada",
        ("POST", "/api/pacientes"): "paciente_creado",
        ("PATCH", "/api/pacientes/{paciente_id}"): "paciente_editado",
        ("DELETE", "/api/pacientes/{paciente_id}"): "paciente_eliminado",
        ("POST", "/api/pacientes/{paciente_id}/restaurar"): "paciente_restaurado",
        ("POST", "/api/pacientes/{paciente_id}/autorizacion"): "paciente_autorizacion",
        (
            "POST",
            "/api/pacientes/{paciente_id}/reactivar-recordatorios",
        ): "recordatorios_reactivados",
        ("PUT", "/api/pacientes/{paciente_id}/medicos"): "paciente_vinculado",
        ("POST", "/api/agenda"): "evento_creado",
        ("PATCH", "/api/agenda/{evento_id}"): "evento_editado",
        ("POST", "/api/agenda/{evento_id}/cancelar"): "evento_cancelado",
    },
}


def rutas_que_modifican() -> set[Ruta]:
    rutas = create_app().openapi()["paths"]
    return {
        (metodo.upper(), ruta)
        for ruta, operaciones in rutas.items()
        for metodo in operaciones
        if metodo in ("post", "patch", "put", "delete")
    }


def test_todas_las_rutas_que_modifican_estan_cubiertas() -> None:
    cubiertas: set[Ruta] = set(EXENTAS)
    for rutas in GRUPOS.values():
        assert not cubiertas & set(rutas), "ruta repetida en dos grupos"
        cubiertas |= set(rutas)
    assert rutas_que_modifican() == cubiertas
