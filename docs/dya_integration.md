# Integración financiera privada con DyA

Cambio acotado al tenant ID 3 / `bachatamania` / COP. No hay llamadas HTTP en el checkout ni escritura hacia DyA.

Crear/editar evento: **Conectar con finanzas Duane y Aleja**, desactivado inicialmente. Se oculta a otras academias. Migración: `eventos.0021_evento_connect_dya_finances_evento_updated_at`.

API: `GET /api/integrations/dya/events/` y `GET /api/integrations/dya/events/<id>/` con cabecera `Authorization: Bearer <DYA_INTEGRATION_API_TOKEN>`. Token vacío/incorrecto 401; producción exige HTTPS; métodos de escritura 405 (o 403 CSRF antes de la vista). No hay credenciales en query strings. Respuestas no-store y sólo eventos opt-in del tenant correcto.

El listado devuelve `schema_version=1`, `complete=true`, `events[]`. Cada elemento contiene evento, receipts, expenses, income.paid_receipts_total, refunds, refund_semantics y fingerprint. Los campos conservan nombres de modelos reales. Cada recibo transmite sólo identidad financiera, importes, fecha, forma/origen de pago, revisión y anulación; nunca comprador/contactos/comprobantes/QR. El importe reconocido es monto_total de revisados no anulados, sin volver a aplicar descuentos ni multiplicar entradas.

Estos modelos no tienen estados pending/failed/refunded ni ledger independiente de devoluciones. Por eso `refunds=[]`, `refund_semantics=annulments_in_receipts_no_refund_ledger`. Se transmiten anulaciones como anulaciones, sin inventar retornos bancarios. Si se añade un verdadero ledger de refunds, versionar explícitamente el contrato y el adaptador consumidor antes de exponerlo. No interpretar recibo revisado como conciliación bancaria demostrada.

Lectura en transacción consistente. El fingerprint cubre hijos para detectar gastos editados/eliminados, ventas y anulaciones, aunque updated_at del padre no varíe. El total de ventas es informativo, no un saldo bancario.

Las cuentas, default y override se configuran sólo en DyA. AppDanza no guarda sus IDs ni saldos. DyA hace pull aproximadamente cada cinco minutos y conserva la última instantánea si AppDanza está caído.

## Configuración privada

`.env`: `DYA_INTEGRATION_API_TOKEN` (aleatorio, compartido con APPDANZA_API_TOKEN de DyA). `.env.example` deja el valor vacío. En producción mantener `DJANGO_ENV=production`, `DEBUG=False`, HTTPS y configuración habitual de host/proxy. No habilitar DEBUG para eludir HTTPS.

## Comandos después de Git

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py test apps.eventos.test_dya_api
python manage.py test
```

Backup antes de migrar la DB operativa; nunca migrar ni escribir `daappdanzaproduccion.sqlite3` (copia de auditoría readonly). La prueba completa local usa DB temporal y pasa 9 tests. SHA256 de la copia: `f9765dd429ae5fbc67dd8db93869fd95a14e51b3e457fc8f57e5ff853b0f1bb8`.

Desplegar AppDanza primero y luego DyA. Activar el switch únicamente en los eventos elegidos después del despliegue; la migración no activa ninguno. No se desplegó esta integración ni se hizo Git en la misión pre-Git.

## Agenda pública para el asistente de Social Studio (15 oct 2026)

`GET /api/integrations/dya/agenda/` con el mismo `Authorization: Bearer <DYA_INTEGRATION_API_TOKEN>` (HTTPS en producción;
ruta añadida explícitamente a `PUBLIC_ROUTES` porque se autentica sola). Devuelve `schema_version=1`, `kind=public_agenda`,
`events[]` con sólo lo que ya muestra la página pública de cada academia: nombre, inicio/fin, lugar, ciudad, estado,
enlace de registro (externo o el público de AppDanza), póster y precios de preventa/puerta. Sólo eventos de academias
activas en `REGISTRO_ONLINE`/`REGISTRO_PUERTA` desde hace 6 h en adelante (máx. 50). Nunca recibos, compradores,
contactos, pagos ni gastos. Filtro opcional `?academy=slug1,slug2`.

Social Studio (DyA) la lee cada ≤5 min y muestra sólo los eventos cuyo lugar menciona Distrito Social / Cra 29 #68-18.
Desplegado en producción el 15 oct 2026 16:49 UTC desde la rama `feature/social-public-events` (basada en el commit de
producción f23db6c de `fix/eventos-metricas-inscripciones-20261012`); sin migraciones; backup previo de la DB en
`~/backups/appdanza-agenda-20261015T164915Z/`. Rollback: `git checkout fix/eventos-metricas-inscripciones-20261012` y reload.
Tests: `apps.eventos.test_public_agenda` (5) + suite completa 100 OK.
