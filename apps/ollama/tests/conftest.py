"""Pytest fixtures for ha-addon-ollama test suite."""

from pathlib import Path

import pytest
import yaml

APP_ROOT = Path(__file__).parent.parent


@pytest.fixture
def app_root():
    return APP_ROOT


@pytest.fixture
def config_yaml(app_root):
    with open(app_root / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def build_yaml(app_root):
    with open(app_root / "build.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def translations_yaml(app_root):
    with open(app_root / "translations" / "en.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
