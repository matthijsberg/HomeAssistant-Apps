import subprocess
from pathlib import Path


def test_okf_bundle_conformance():
    repo_root = Path(__file__).resolve().parent.parent.parent
    knowledge_dir = repo_root / 'knowledge'
    validator_script = repo_root / 'scripts' / 'validate.sh'

    assert knowledge_dir.exists(), f'Missing OKF knowledge bundle at {knowledge_dir}'
    assert (knowledge_dir / 'index.md').exists(), 'Missing bundle root index.md'
    assert validator_script.exists(), f'Missing OKF validator script at {validator_script}'

    res = subprocess.run(
        [str(validator_script), str(knowledge_dir)],
        capture_output=True,
        text=True
    )
    assert res.returncode == 0, f'OKF validation failed:\n{res.stdout}\n{res.stderr}'
    assert 'Bundle is OKF v0.2 conformant' in res.stdout
