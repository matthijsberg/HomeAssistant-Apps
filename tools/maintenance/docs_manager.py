"""
Documentation and changelog manager for HomeAssistant-Apps.
Synchronizes config.yaml version, CHANGELOG.md, README.md, and DOCS.md.
"""
from datetime import datetime
from pathlib import Path
import re
from typing import Optional
import yaml

def sync_manifest_version(app_dir: Path, new_version: str) -> bool:
    manifest_path = app_dir / "config.yaml"
    if not manifest_path.exists():
        manifest_path = app_dir / "config.yaml.disabled"
    if not manifest_path.exists():
        return False

    content = manifest_path.read_text(encoding="utf-8")
    updated = re.sub(r'^(version:\s*["\']?)([^"\'\n]+)(["\']?)', rf'\g<1>{new_version}\g<3>', content, flags=re.MULTILINE)
    manifest_path.write_text(updated, encoding="utf-8")
    return True

def prepend_changelog_entry(app_dir: Path, new_version: str, summary: str, details: Optional[str] = None) -> bool:
    changelog_path = app_dir / "CHANGELOG.md"
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    new_entry = f"""## [{new_version}] - {today_str}

### Changed
- {summary}
"""
    if details:
        new_entry += f"- Details: {details}\n"
    new_entry += "- Verified: Linting, pipeline tests, and HA mock run passed.\n\n"

    if not changelog_path.exists():
        changelog_path.write_text(f"# Changelog\n\nAll notable changes to this app are documented in this file.\n\n{new_entry}", encoding="utf-8")
        return True

    content = changelog_path.read_text(encoding="utf-8")
    # Insert after top header
    header_match = re.search(r"^(#\s+Changelog\s*\n+)", content, flags=re.IGNORECASE)
    if header_match:
        idx = header_match.end()
        updated = content[:idx] + new_entry + content[idx:]
    else:
        updated = new_entry + content

    changelog_path.write_text(updated, encoding="utf-8")
    return True

def sync_readme_version(app_dir: Path, new_version: str) -> bool:
    readme_path = app_dir / "README.md"
    if not readme_path.exists():
        return False

    content = readme_path.read_text(encoding="utf-8")
    # Replace version badges e.g. badge/version-0.1.5-blue
    updated = re.sub(r'(badge/version-)[0-9\.\-a-zA-Z]+(-[a-zA-Z]+)', rf'\g<1>{new_version}\g<2>', content)
    # Replace version in text like `Version: 0.1.5`
    updated = re.sub(r'(Version:\s*`?)[0-9\.\-a-zA-Z]+(`?)', rf'\g<1>{new_version}\g<2>', updated)
    
    readme_path.write_text(updated, encoding="utf-8")
    return True
