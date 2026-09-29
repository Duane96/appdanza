# Operación comercial de AppDanza

## Despliegue y reversión

Proyecto `/home/Duane96/appdanza`, virtualenv `/home/Duane96/.virtualenvs/appdanzaenv`.
Antes de migrar: ventana sin escrituras, copia SQLite con `Connection.backup`, backup privado de media, .env, código y WSGI. Mantener permisos 0700/0600 y manifiestos fuera de Git y del directorio público.

Ensayar el código final con `python scripts/rehearse_sqlite_migration.py --source BACKUP/before.sqlite3 --directory BACKUP/rehearsal --api-baseline BACKUP/dya-v1.json`. La fuente nunca se migra. El ensayo exige integridad, FKs, hash de todas las columnas y filas históricas, acceso gratis a los dos tenants protegidos y las huellas API v1.

Aplicar `pip install -r requirements.txt`, `manage.py migrate --noinput`, `manage.py privatize_uploads` (simulación), `manage.py privatize_uploads --apply`, `manage.py collectstatic --noinput`, `manage.py check --deploy`, reload. Los archivos privados se copian y verifican SHA256 antes de retirar la copia pública. Su manifiesto permite restaurar cada ubicación original. No retirar ningún backup.

Rollback: detener solamente el worker AppDanza y las escrituras; restaurar juntos el HEAD, DB, media privada/pública y configuración del mismo punto de corte, comprobar integridad y API, reload y reanudar. Nunca ejecutar código antiguo contra una DB parcialmente migrada. Restaurar una copia antigua después de reabrir escrituras requiere primero reconciliar los registros posteriores; no descartar ventas.

## Worker en el plan actual de PythonAnywhere

La única tarea always-on está ocupada por DyA y no se modifica. Crear tarea **hourly** con `bash /home/Duane96/appdanza/scripts/run_commercial_worker.sh`. El proceso dura 3550 segundos, usa `flock` exclusivo, procesa outbox cada 2 segundos y evalúa billing/conciliación cada 300 segundos. Queda una ventana de aproximadamente 50 segundos por hora; no se promete ejecución continua. Las leases vencidas se recuperan; trabajos FAILED requieren revisión en admin. No imprimir destinatarios ni payloads. `run_jobs --once --limit 100` permite una ejecución acotada.

## Contratos, tarifas y dinero

Publicar una **nueva** PlanVersion desde el admin cuando el propietario haya definido precios y capabilities. Versiones históricas son inmutables. No se publican automáticamente tarifas inventadas. El catálogo vacío muestra un estado controlado. Los tenants existentes conservan su política de acceso.

Bachatamanía INTERNAL: exenta permanente, sin deuda ni cargos. Bachatop COMPLIMENTARY: acceso concedido, sin conversión automática a pago. Su fecha técnica legacy no se interpreta como fin de la cortesía. Cambiar una concesión requiere decisión explícita y motivo en admin; nunca cobro retroactivo.

Las cuentas de cobro SaaS son distintas a recibos de academias y no son facturas electrónicas DIAN. Contratación explícita produce una cuenta por período. La tarifa de nuevos registros usa precedencia evento → tenant → versión de plan → global; exención gana siempre. Sólo admisiones comerciales explícitas confirmadas y pagadas generan consumo cobrable. Cortesías, importe cero, pendientes, QR reemitidos, escaneos y registros históricos no generan nuevos cargos. El cierre mensual asigna cada consumo una sola vez.

Cancelación operativa no es devolución bancaria. `record_refund` requiere referencia y monto real verificados y genera créditos de usage nuevos, sin borrar historia. El valor facial de una cuenta no cambia: créditos reducen su neto. Un reembolso SaaS se registra mediante `billing.record_saas_refund(payment, ...)` sólo tras verificar la devolución real; no ejecuta transferencias. Véase la firma del servicio y su validación de monto/referencia. Los historiales de pagos, créditos y reembolsos se consultan en el portal.

Impago: gracia configurable → LIMITED → SUSPENDED; sin borrar datos. Cobro confirmado recupera acceso sólo si no queda otra deuda exigible. Cancelación al final del período, cambio de versión al siguiente período, no prorrateo oculto.

## ePayco propio y conciliación

Configuración privada exclusiva de AppDanza: APPDANZA_EPAYCO_PUBLIC_KEY, PRIVATE_KEY, CUSTOMER_ID y P_KEY (todos con prefijo APPDANZA_EPAYCO_), APPDANZA_TOKEN_ENCRYPTION_KEY (Fernet). No reutilizar credenciales de DyA. APPDANZA_EPAYCO_TEST=true, APPDANZA_EPAYCO_LIVE_ENABLED=false, APPDANZA_AUTOMATIC_BILLING_ENABLED=false por defecto. Nunca incluir claves en logs/Git.

Tokenización directa navegador→ePayco; PAN/CVV no tienen nombre de formulario ni se aceptan en backend. Recurrencia gestionada por AppDanza, no activar además una suscripción nativa que duplique cobros. Callback firmado y consulta independiente al proveedor; redirects y respuesta inmediata del cargo no confirman pagos. Timeouts → UNKNOWN y conciliación, nunca reintento ciego. `manage.py reconcile_billing --limit 50` consulta referencias conocidas; `--reference REFERENCIA` reconcilia una referencia verificada. UNKNOWN sin referencia exige revisión del merchant antes de habilitar otro intento.

Antes de live: credenciales propias, sandbox real completo (éxito/rechazo/timeout/webhook repetido/importes), conciliación y autorización contractual. Mocks no acreditan disponibilidad del producto ePayco. El despliegue sin credenciales conserva billing manual y no cobra automáticamente.

Fuentes de contrato: [SDK oficial](https://github.com/epayco/epayco-python), [confirmaciones](https://docs.epayco.com/docs/url-de-confirmacion), [cobro con token](https://docs.epayco.com/docs/cobrar-con-token).

## PostgreSQL: preparado, no migrado

El plan actual de PythonAnywhere no ofrece PostgreSQL. No se solicita upgrade ni se inventan credenciales. Al disponer de instancia autorizada: instalar requirements-postgres.txt en un entorno de ensayo; configurar APPDANZA_DB_ENGINE=postgresql y APPDANZA_DB_NAME/USER/PASSWORD/HOST/PORT/SSLMODE privados (TLS require por defecto).

Primero ejecutar toda la suite contra una **DB de tests aislada** con permisos de creación; después restaurar una copia SQLite privada, migrarla con este código y exportar `dumpdata --all --natural-foreign --exclude contenttypes --exclude auth.permission --indent 2` a archivo privado. Crear DB PostgreSQL vacía, migrate, cargar fixture preservando PK y verificar secuencias, conteos por tabla/tenant, hashes normalizados por tipo, FKs, montos Decimal, timestamps, Bachatop, Bachatamanía y API v1. Probar concurrencia, colisiones de consecutivos, QR y facturación. No exportar desde producción en movimiento.

Cutover sólo después del rehearsal aprobado por resultados: congelar escrituras, snapshot final, repetir importación y comparación, cambiar configuración DB, reload/smokes y reabrir. SQLite original y backups quedan intactos para rollback. Una vez hay nuevas escrituras PostgreSQL, rollback necesita reconciliación inversa; no basta cambiar un env var. No se afirma compatibilidad verificada hasta ejecutar esa suite y ensayo en PostgreSQL real.
