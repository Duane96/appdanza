"""Migrate an isolated SQLite backup and prove every pre-existing row survives.

Run with the deployment virtualenv. This script never migrates --source.
The new directory contains private copies; do not commit or expose it.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def snapshot(db):
    result = {}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        columns = [r[1] for r in db.execute('PRAGMA table_info('+quoted(table)+')')]
        rows = list(db.execute('SELECT rowid,'+','.join(map(quoted, columns))+' FROM '+quoted(table)+' ORDER BY rowid'))
        result[table] = {'columns': columns, 'max_rowid': max((r[0] for r in rows), default=0),
            'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows, ensure_ascii=False,
                separators=(',', ':'), default=str).encode()).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--api-baseline', help='Optional private dya-v1.json snapshot')
    args = parser.parse_args()
    source, directory = Path(args.source).resolve(), Path(args.directory).resolve()
    if not source.is_file() or directory.exists():
        raise SystemExit('Source must exist; rehearsal directory must be new.')
    os.umask(0o077)
    directory.mkdir(parents=True, mode=0o700)
    target = directory/'rehearsal.sqlite3'
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
        before = snapshot(copy)
    (directory/'before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, 'APPDANZA_DB_ENGINE': 'sqlite', 'APPDANZA_SQLITE_PATH': str(target), 'DJANGO_ENV': 'development'}
    subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=root, env=env, check=True)
    failures = []
    with sqlite3.connect(target) as copy:
        if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            failures.append('integrity_check')
        if list(copy.execute('PRAGMA foreign_key_check')):
            failures.append('foreign_key_check')
        for table, entry in before.items():
            rows = list(copy.execute('SELECT rowid,'+','.join(map(quoted, entry['columns']))+' FROM '+quoted(table)
                +' WHERE rowid<=? ORDER BY rowid', [entry['max_rowid']]))
            digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':'), default=str).encode()).hexdigest()
            if len(rows) != entry['count'] or digest != entry['sha256']:
                failures.append(table)
    os.environ.update({key: env[key] for key in ('APPDANZA_DB_ENGINE', 'APPDANZA_SQLITE_PATH', 'DJANGO_ENV')})
    os.environ['DJANGO_SETTINGS_MODULE'] = 'gestoracademia.settings'
    sys.path.insert(0, str(root))
    import django
    django.setup()
    from apps.academias.models import Academia
    from apps.academias.models import PerfilUsuario
    from apps.academias.student_identity import student_for
    from apps.saas_core.models import SaaSInvoice, UsageEntry
    from apps.saas_core.policy import BillingPolicy
    from apps.eventos.models import Evento
    from apps.eventos.dya_api import payload
    tenants = {}
    for tenant in Academia.unfiltered_objects.filter(slug__in=('bachatamania', 'bachatop')):
        policy = BillingPolicy(tenant)
        tenants[tenant.slug] = {'mode': policy.account.mode, 'exempt': policy.exempt,
            'restricted': policy.restricted, 'automatic_charges': policy.can_automatically_charge,
            'invoices': SaaSInvoice.objects.filter(academia=tenant).count(),
            'usage': UsageEntry.objects.filter(academia=tenant).count()}
        profiles = PerfilUsuario.objects.filter(academia=tenant, rol='ESTUDIANTE').select_related('user')
        tenants[tenant.slug]['student_accounts'] = profiles.count()
        tenants[tenant.slug]['student_accounts_resolved'] = sum(student_for(p.user, tenant) is not None for p in profiles)
        if not policy.exempt or policy.restricted or policy.can_automatically_charge or tenants[tenant.slug]['invoices']:
            failures.append('access:'+tenant.slug)
    api_count = 0
    if args.api_baseline:
        baseline = json.loads(Path(args.api_baseline).read_text())
        for prior in baseline:
            event = Evento.unfiltered_objects.select_related('academia').get(pk=prior['event']['id'])
            if payload(event)['fingerprint'] != prior['fingerprint']:
                failures.append('api:'+str(event.pk))
            api_count += 1
    report = {'old_tables_verified': len(before), 'api_events_verified': api_count,
        'tenants': tenants, 'failures': failures, 'passed': not failures}
    (directory/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
