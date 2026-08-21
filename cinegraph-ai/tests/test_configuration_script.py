import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'configure.py'


def test_production_configuration_is_private_unique_and_never_overwritten(tmp_path):
    output = tmp_path / '.env.production'
    result = subprocess.run([sys.executable, str(SCRIPT), '--production', '--domain', 'films.example.org',
                             '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = output.read_text()
    assert 'CINEGRAPH_ENV=production' in text
    assert 'SEED_SAMPLE_DATA=false' in text
    assert 'DASHBOARD_ORIGIN=https://films.example.org' in text
    assert 'CINEGRAPH_API_KEY=' in text
    if os.name != 'nt':
        assert output.stat().st_mode & 0o777 == 0o600
    again = subprocess.run([sys.executable, str(SCRIPT), '--production', '--domain', 'films.example.org',
                            '--output', str(output)], capture_output=True, text=True)
    assert again.returncode != 0
    assert output.read_text() == text
    assert text.split('CINEGRAPH_API_KEY=')[1].splitlines()[0] not in result.stdout


def test_production_configuration_rejects_url_and_shell_metacharacter_domains(tmp_path):
    for value in ['http://insecure.example', 'example.org/path', 'example.org;cmd', 'localhost']:
        result = subprocess.run([sys.executable, str(SCRIPT), '--production', '--domain', value,
                                 '--output', str(tmp_path / '.env')], capture_output=True)
        assert result.returncode != 0
    assert not (tmp_path / '.env').exists()
