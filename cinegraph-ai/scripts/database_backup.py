"""Create a PostgreSQL custom archive with SHA256; restore only to a NEW database.

Uses the configured Docker Compose PostgreSQL service; never overwrites a database.
"""
import argparse
import hashlib
import os
import re
import subprocess
from pathlib import Path


def compose_command(compose_file, *args, env_file=None):
    prefix = ['docker', 'compose']
    if env_file:
        prefix += ['--env-file', str(env_file)]
    return [*prefix, '-f', str(compose_file), 'exec', '-T', 'postgres', *args]


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose-file', type=Path, default=Path(__file__).resolve().parents[1] / 'compose.yaml')
    parser.add_argument('--env-file', type=Path)
    sub = parser.add_subparsers(dest='action', required=True)
    backup = sub.add_parser('backup')
    backup.add_argument('--output', type=Path, required=True)
    restore = sub.add_parser('restore')
    restore.add_argument('--input', type=Path, required=True)
    restore.add_argument('--database', required=True, help='New database name; existing databases are never replaced')
    args = parser.parse_args()
    if args.action == 'backup':
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
            result = subprocess.run(compose_command(args.compose_file, 'pg_dump', '-U', 'cinegraph',
                                                    '-d', 'cinegraph', '--format=custom', env_file=args.env_file), stdout=handle)
        if result.returncode:
            args.output.unlink()
            raise SystemExit('Backup failed; incomplete archive removed')
        checksum = args.output.with_suffix(args.output.suffix + '.sha256')
        with os.fdopen(os.open(checksum, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
            handle.write(digest(args.output) + '\n')
        print(f'Backup and SHA256 saved: {args.output}')
    else:
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', args.database) or args.database in {'cinegraph', 'postgres', 'template0', 'template1'}:
            parser.error('--database must be a new lowercase recovery database name, never a live/system database')
        checksum = args.input.with_suffix(args.input.suffix + '.sha256').read_text().strip()
        if digest(args.input) != checksum:
            raise SystemExit('Backup checksum mismatch; no database was created')
        # createdb fails if target exists. Do not use --clean, DROP DATABASE, or overwrite semantics.
        subprocess.run(compose_command(args.compose_file, 'createdb', '-U', 'cinegraph', args.database, env_file=args.env_file), check=True)
        with args.input.open('rb') as archive:
            subprocess.run(compose_command(args.compose_file, 'pg_restore', '-U', 'cinegraph',
                                           '-d', args.database, '--no-owner', '--exit-on-error', env_file=args.env_file), stdin=archive, check=True)
        print(f'Restored to NEW database {args.database}; validate before changing application configuration.')


if __name__ == '__main__':
    main()
