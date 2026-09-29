"""Move referenced sensitive files out of public media after a verified backup."""
import hashlib
import json
import shutil
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.academias.private_media import PRIVATE_FIELDS, private_storage


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


class Command(BaseCommand):
    help = 'Dry-run by default. --apply copies, verifies SHA256 and removes only the public source.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        public = Path(settings.MEDIA_ROOT).resolve()
        private = Path(private_storage.location).resolve()
        if private == public or public in private.parents:
            raise CommandError('PRIVATE_MEDIA_ROOT must be outside public media.')
        names = set()
        for label, field in PRIVATE_FIELDS:
            names.update(name for name in apps.get_model(label)._base_manager.exclude(**{field: ''})
                .exclude(**{field: None}).values_list(field, flat=True))
        referenced = len(names)
        # Replaced/deleted legacy records may leave sensitive files behind.
        # These directories contain only private fields, never public branding.
        for folder in ('comprobantes_eventos', 'qrs_eventos', 'qrs_estudiantes',
                       'soportes_gastos', 'saas_comprobantes', 'saas/gastos_comprobantes'):
            directory = public / folder
            if directory.exists():
                names.update(path.relative_to(public).as_posix() for path in directory.rglob('*') if path.is_file())
        counters = {'referenced': referenced, 'orphaned_private_files': len(names)-referenced,
                    'copied': 0, 'already_private': 0, 'missing': 0}
        manifest = []
        for name in sorted(names):
            source, target = (public / name).resolve(), (private / name).resolve()
            if public not in source.parents or private not in target.parents:
                raise CommandError('Invalid media path; no operation performed for this reference.')
            if not source.exists():
                counters['already_private' if target.exists() else 'missing'] += 1
                continue
            checksum = digest(source)
            if target.exists() and digest(target) != checksum:
                raise CommandError('A private file differs from its public source; manual review required.')
            manifest.append({'name': name, 'sha256': checksum, 'bytes': source.stat().st_size})
            if options['apply']:
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(source, target)
                if digest(target) != checksum:
                    raise CommandError('Private copy failed checksum verification; source preserved.')
                # Persist recovery evidence before removing a verified public copy.
                with (private / 'relocation-manifest.jsonl').open('a', encoding='utf-8') as output:
                    output.write(json.dumps(manifest[-1]) + '\n')
                source.unlink()
            counters['copied'] += 1
        self.stdout.write(json.dumps({'applied': options['apply'], **counters}))
