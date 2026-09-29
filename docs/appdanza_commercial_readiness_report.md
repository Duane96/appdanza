# AppDanza — cierre de hardening y billing comercial

Validación: 29 de septiembre de 2026 (UTC). Alcance: AppDanza; contrato DyA v1 conservado. Operación y rollback: [commercial_operations.md](commercial_operations.md).

## 1. Estado

**IMPLEMENTADO Y DESPLEGADO; operación existente estable.** Billing manual, políticas, metering y outbox disponibles. No se certifica cobro automático live: faltan credenciales propias de ePayco y validación real de su producto. PostgreSQL no está habilitado en el plan de hosting. No se hicieron cargos reales ni se publicaron precios nuevos inventados.

## 2. Seguridad

Autorización central denegada por defecto, CSRF en mutaciones, operaciones por POST, escaping de datos dinámicos, encabezados de branding limitados a formato permitido. Nuevas cuentas con contraseña inutilizable e invitación de un solo uso; contraseñas anteriores intactas. Comprobantes/QR con autorización y almacenamiento privado, validación de formato/tamaño y nombres opacos.

En producción: 771 archivos respaldados (229.957.563 bytes); 717 referencias privadas trasladadas con SHA256, cero faltantes. Revisión adicional de carpetas sensibles sin huérfanos restantes. URL pública antigua de QR → 404; descarga privada anónima → 403. No se cambiaron imágenes públicas.

`check` sin errores. `check --deploy` conserva tres avisos: HSTS no configurado, redirect HTTPS delegado a PythonAnywhere (Force HTTPS activo), prefijo legacy `django-insecure-` en clave existente de 66 caracteres/40 caracteres distintos. No se imprimió ni se rotó esa clave ni se invalidaron masivamente sesiones. El prefijo por sí solo no mide su entropía. Escaneo de secretos y rutas privadas del índice: PASS.

## 3. Multi-tenancy

TenantMembership admite múltiples organizaciones, roles OWNER/ADMIN/TEACHER/STUDENT/BILLING y revocación explícita. Staff Django sin superusuario no equivale a superadmin. Colaboradores de eventos limitados a recursos y operaciones autorizados. Queryset tenant sin contexto devuelve vacío; FK cruzada rechazada por modelos/servicios/formularios. Middleware limpia contexto al finalizar.

## 4. Bachatamanía

Tenant real 3, `bachatamania`: INTERNAL, exención permanente centralizada. Suscripción $0, fee $0, cero invoices/usage históricos nuevos, cargos automáticos deshabilitados. Conservados 12 eventos, 363 recibos, 273 QR y 23 gastos. API limitada a los cuatro eventos conectados.

## 5. Bachatop

Tenant real 11, nombre «Luis y Camila», slug `bachatop`: COMPLIMENTARY, externo gratuito, sin fecha de corte inferida ni conversión automática a pago. La licencia partner anterior omite el vencimiento técnico: no se utilizó esa fecha para retirar su acceso.

Conservados 14 alumnos, 2 planes, 10 inscripciones, 5 asistencias, 1 profesor, 1 clase, 12 sesiones, 1 reserva, 10 recibos financieros y 16 perfiles. Identidad legacy de los 14 alumnos resuelta sin modificar usuarios/contraseñas. Panel admin, Mi plan y portal alumno: 200 con usuarios reales y conexión readonly.

## 6. Pagos de eventos y QR

Nuevos registros PENDING, importe/cupón cotizados en servidor y clave idempotente. CONFIRMED requiere revisión; una Admission estable por derecho de acceso y QR emitido una vez. Anulación revoca acceso; no se presenta como devolución bancaria. Reembolso real documentado separado. Reemisión mantiene Admission/consumo; check-in diario y simultáneo protegido. Legacy conserva banderas y valores, sin reinterpretar aprobación histórica.

## 7. Finanzas

Agregados independientes evitan multiplicación por joins; margen corregido; consecutivos, stock POS, reservas/créditos, asistencia, preparación y pago a profesores con transacciones y defensas idempotentes. Cancelación conserva historial y devolución de crédito se aplica una vez a la inscripción original. Clase pagada no se reabre desde el formulario. Sin reseteos contables ni recomputación retroactiva de comisiones legacy.

## 8. Planes y capabilities

BillingAccount + CommercialSubscription + PlanVersion inmutable. Capabilities centralizadas y límites de alumnos/profesores/eventos abiertos; concesiones y datos actuales conservados. Cambio de versión en próximo período; cancelación al final del período. Admin publica nuevas versiones con importes explícitos; catálogo vacío tiene estado controlado. No se copiaron tarifas arbitrarias a contratos existentes.

## 9. Ledger comercial

SaaSInvoice/InvoiceLine, SaaSPayment, PaymentAttempt, SaaSCredit, SaaSRefund, UsageEntry/Allocation independientes de recibos de academias. Valor facial preservado; créditos reducen neto. Pago manual confirmado por superadmin con referencia bancaria verificada. Refund registra devolución ya comprobada, no envía dinero. No se declara facturación electrónica DIAN.

## 10. ePayco

Cliente propio, TLS y timeouts, sin fallback a credenciales DyA. Tokenización navegador→ePayco, backend rechaza PAN/CVV. Mandato cifrado y revocable. Firma de callback + consulta independiente al proveedor verifican importe, moneda, merchant, modo y referencia. Recurrencia gestionada sólo por AppDanza; timeout UNKNOWN no genera cargo nuevo ciego. Conciliación programada y CLI.

Matriz de mocks: confirmación, duplicado, importe/merchant inválido, revocación, timeout y recuperación. **Sandbox real: no ejecutado, faltan cuatro variables merchant propias. Live: deshabilitado. Automatic billing: deshabilitado.** No cargos reales.

## 11. Usage de eventos nuevos

Admission comercial explícita, confirmada y pagada; no equivalencia ticket creado = cobro. Cortesías, importe cero, pendientes, escaneos/reemisiones y legacy excluidos. Tarifa evento → tenant → plan → global, snapshot inmutable. Cierre mensual asigna una sola vez. Reembolso real genera crédito; anulación por sí sola no lo simula.

## 12. Exención de consumo interno

Bachatamanía no genera deuda SaaS ni fee. Migración no recorre QR históricos para facturarlos. Tras despliegue y worker: cero invoices y cero usage en producción.

## 13. Dunning

Gracia configurable → LIMITED → SUSPENDED, avisos en outbox y datos conservados. Pago recupera acceso sólo sin otra deuda exigible. Exentos no entran en dunning. Reintentos acotados a días configurados; UNKNOWN se concilia primero.

## 14. Portal

Mi plan, política y concesión; recursos/límites; cambio/cancelación de plan; cuentas de cobro; comprobantes privados; estado del mandato; pagos, créditos y reembolsos. Comprobación móvil 390 px sin desbordamiento horizontal de página. Formulario público cambia cantidad y recibe cotización del servidor (fixture 100→200). Panel maestro con cantidades reales y scroll contenido de tablas.

## 15. Jobs / outbox

Leases con recuperación, dedupe, retries acotados, errores sin payloads y limpieza del payload completado. EMAIL, EVENT_QR, BILLING_WEBHOOK, BILLING_CHARGE. Tarea PythonAnywhere **1531477**, horaria al minuto 25: `bash /home/Duane96/appdanza/scripts/run_commercial_worker.sh`.

Proceso 3550 segundos, flock exclusivo, outbox cada 2 segundos y evaluación/conciliación cada 300; intervalo aproximado de 50 segundos sin proceso entre horas. Confirmado en Running tasks desde 05:25:18 UTC. Trabajo real sobre QR existente: DONE, un intento, sin error, payload limpiado; no regeneró el QR ni movió dinero. Supervisor DyA 274221 siguió Running sin cambios.

## 16. PostgreSQL

**No migrado.** Panel PythonAnywhere muestra upgrade requerido y no hay instancia autorizada disponible. Settings por entorno, driver opcional y procedimiento de export/import/validación/rollback preparados. Suite PostgreSQL **no ejecutada**: no se afirma compatibilidad verificada sin servidor. SQLite usa transacciones IMMEDIATE y prueba de concurrencia con DB de archivo. No se hizo upgrade ni cutover arriesgado.

## 17. Tests

Entorno limpio instalado desde requirements. **69/69 PASS** en Python 3.14 / Django 5.2.14 con SQLite de archivo, incluidos cuatro escenarios concurrentes. Runtime PythonAnywhere Python 3.10.5 / Django 5.2.14: **68/68 PASS** del commit de despliegue base; el test adicional de traslado de huérfanos pasó localmente con sus 12 pruebas relacionadas. Check 0; makemigrations --check --dry-run sin cambios; diff --check y secret scan PASS.

Ensayo de copia real: integridad, foreign keys, hash de columnas/filas de 51 tablas, cuatro fingerprints y accesos protegidos PASS. Migración activa repitió comparación exacta de las 51 tablas; PASS. No se migró la copia de auditoría local.

## 18. Producción / Git

Repositorio `Duane96/appdanza`, main. Commits funcionales: **87dbf67** (hardening y billing), **ec6118f8c280ca62051f8058efa6f0d6df9b2f22** (protección de archivos privados huérfanos). Documentación: **be77aad**. Este informe se añade en un commit documental posterior; no altera el estado funcional probado.

Ruta `/home/Duane96/appdanza`; venv `/home/Duane96/.virtualenvs/appdanzaenv`. 19 migraciones aplicadas. collectstatic: 1 copiado, 127 sin cambios. Reload realizado; al restaurar WSGI se actualizó su mtime y se repitió reload hasta verificar HTTP 200. WSGI final idéntico al original.

Backups privados `/home/Duane96/backups/appdanza-commercial-20260929T035518Z`, ensayo `production-rehearsal/`, punto final `cutover/`. DB, media, .env, código y WSGI respaldados. Restore inicial verificado, conservación de filas activa verificada. No backups/DB/env/logs en Git.

Smokes HTTP 200: raíz, Bachatop, login Bachatop, Bachatamanía, registro y API autenticada. Vistas admin/Mi plan/alumno de ambos tenants 200 en modo readonly. Negativas de archivos 404/403. El navegador conectado rechazó abrir www.appdanza.com; estas verificaciones públicas se hicieron por HTTP desde el servidor y la UI móvil se verificó localmente.

## 19. API DyA y saldos

Ruta y schema v1 sin cambios. Cuatro eventos 2, 8, 9, 12 conservan fingerprints. Dry-run + real + repetición: **4 UNCHANGED en cada pasada**, cero errores. Comparación exacta de 12 tablas financieras DyA sin cambios.

| Métrica DyA | Antes | Después |
|---|---:|---:|
| Disponible | $890.000 | $890.000 |
| Caja | $499.410 | $499.410 |
| Ecosistema | $1.389.410 | $1.389.410 |
| Reembolsos pendientes | $0 | $0 |
| Asignaciones pendientes | $0 | $0 |

Evidencia privada: `dya-after-deploy.json` en el backup remoto. DyA no se modificó durante esta fase.

## 20. Condiciones externas y alcance de la certificación

- ePayco propio: credenciales/producto habilitado, sandbox real y autorización live antes de activar cobros. Las credenciales DyA no se reutilizan.
- PostgreSQL: instancia/plan habilitado, suite y ensayo reales antes del cutover; hoy no disponible.
- Publicación comercial de precios/planes: configuración del propietario; la plataforma no inventa precios definitivos ni factura a tenants antiguos automáticamente.

Operación actual desplegada estable y apta para continuar usando los tenants existentes. No se presenta como ya validado un checkout recurrente live ni una migración PostgreSQL que no ocurrieron. Siguiente fase autorizada: exclusivamente los cuatro ajustes finales de DyA.
