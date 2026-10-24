-- Roles de la aplicación. Se ejecuta una vez, como superusuario (init de Docker o CI).
-- Variables que recibe de psql: dbname, migrador_pw, app_pw, operador_pw.

CREATE ROLE migrador LOGIN PASSWORD :'migrador_pw';  -- dueño de tablas (Alembic)
CREATE ROLE app      LOGIN PASSWORD :'app_pw';       -- la API; sin ser dueño, para que RLS aplique
CREATE ROLE operador LOGIN PASSWORD :'operador_pw';  -- sin permisos por defecto; se otorgan por tabla

ALTER DATABASE :"dbname" OWNER TO migrador;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO app, operador;

ALTER SCHEMA public OWNER TO migrador;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app, operador;

-- Todo lo que cree el migrador queda accesible para `app`. El operador no recibe nada aquí:
-- sus permisos (clinica, usuario, invitacion) se otorgan en las migraciones de la Fase 1.
ALTER DEFAULT PRIVILEGES FOR ROLE migrador IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrador IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app;