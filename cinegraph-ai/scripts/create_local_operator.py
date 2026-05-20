"""Create a local-only operator and save its generated password in a private file."""
import json
import os
import secrets
from pathlib import Path

import django

if os.getenv('CINEGRAPH_ENV', 'development') != 'development':
    raise SystemExit('Local bootstrap is disabled outside development; use createsuperuser in deployment.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cinegraph.catalog.settings')
django.setup()
from django.contrib.auth import get_user_model  # noqa: E402

path = Path(__file__).resolve().parents[1] / '.local-admin.json'
if path.exists():
    raise SystemExit(f'Existing credentials preserved at {path}')
if get_user_model().objects.filter(username='operator').exists():
    raise SystemExit('Existing operator account preserved; use its current password or Django changepassword.')
password = secrets.token_urlsafe(24)
# Open exclusively before account creation; no password is written to terminal/logs.
with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
    try:
        get_user_model().objects.create_superuser(username='operator', email='', password=password)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    json.dump({'username': 'operator', 'password': password, 'dashboard': 'http://localhost:5100/login'}, output)
print(f'Local operator created. Private credentials: {path}')
