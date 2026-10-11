-- Ejecutar como superusuario de PostgreSQL:
--   psql -U postgres -f scripts/crear_base_datos.sql
-- Cambia la contraseña ANTES de ejecutar y usa la misma en el archivo .env

CREATE USER taller_user WITH PASSWORD 'taller_pass';
CREATE DATABASE taller_mecanico OWNER taller_user ENCODING 'UTF8' TEMPLATE template0;
GRANT ALL PRIVILEGES ON DATABASE taller_mecanico TO taller_user;
