"""Generate private deployment configuration; production files are never overwritten."""
import argparse
import os
import re
import secrets
from pathlib import Path


def write_private(path, content, exclusive=True):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o600)
    if os.name != 'nt':
        os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--local', action='store_true')
    group.add_argument('--production', action='store_true')
    parser.add_argument('--domain')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = args.output or root / ('.env.production' if args.production else '.env')
    if args.production:
        if not args.domain or not re.fullmatch(r'(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', args.domain):
            parser.error('--domain must be a DNS name such as films.example.org, without scheme or path')
        postgres = secrets.token_hex(24)
        neo4j = secrets.token_hex(24)
        redis = secrets.token_hex(24)
        values = {
            'CINEGRAPH_ENV': 'production', 'CINEGRAPH_REQUIRE_AUTH': 'true',
            'CINEGRAPH_API_KEY': secrets.token_hex(32), 'DJANGO_SECRET_KEY': secrets.token_hex(48),
            'POSTGRES_PASSWORD': postgres, 'NEO4J_PASSWORD': neo4j, 'REDIS_PASSWORD': redis,
            'DATABASE_URL': f'postgresql://cinegraph:{postgres}@postgres:5432/cinegraph',
            'NEO4J_URI': 'bolt://neo4j:7687', 'NEO4J_USER': 'neo4j', 'NEO4J_DATABASE': 'neo4j',
            'REDIS_URL': f'redis://:{redis}@redis:6379/0',
            'DASHBOARD_DOMAIN': args.domain, 'CATALOG_DOMAIN': 'admin.' + args.domain,
            'DASHBOARD_ORIGIN': 'https://' + args.domain, 'CATALOG_ORIGIN': 'https://admin.' + args.domain,
            'DJANGO_ALLOWED_HOSTS': 'admin.' + args.domain + ',localhost,127.0.0.1,catalog',
            'DJANGO_DEBUG': 'false', 'DJANGO_TRUST_PROXY': 'true',
            'API_BASE_URL': 'http://api:8000', 'CATALOG_URL': 'https://admin.' + args.domain + '/admin/',
            'SEED_SAMPLE_DATA': 'false', 'LLM_API_KEY': '', 'LLM_MODEL': '',
            'LLM_BASE_URL': 'https://api.openai.com/v1', 'LLM_AUTH_HEADER': 'Authorization',
            'CINEGRAPH_IMAGE': 'cinegraph-ai:local',
        }
        try:
            write_private(path, '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
        except FileExistsError:
            parser.error(f'{path} already exists; refusing to replace deployment credentials')
    else:
        current = path.read_text() if path.exists() else (root / '.env.example').read_text()
        entries = {}
        for line in current.splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                entries[key] = value
        entries.update({'CINEGRAPH_ENV': 'development', 'CINEGRAPH_REQUIRE_AUTH': 'true',
                        'REDIS_URL': 'redis://localhost:6388/0', 'SEED_SAMPLE_DATA': 'true'})
        if len(entries.get('CINEGRAPH_API_KEY', '')) < 32:
            entries['CINEGRAPH_API_KEY'] = secrets.token_hex(32)
        secret = entries.get('DJANGO_SECRET_KEY', '')
        if len(secret) < 50 or any(marker in secret.lower() for marker in ['local-only', 'change', 'example']):
            entries['DJANGO_SECRET_KEY'] = secrets.token_hex(48)
        write_private(path, '\n'.join(f'{key}={value}' for key, value in entries.items()) + '\n', exclusive=False)
    print(f'Configuration written to {path}; credentials were not printed.')


if __name__ == '__main__':
    main()
