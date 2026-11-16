#!/usr/bin/env python3
"""Extract Ubiquiti UniFi OS Server embedded OCI image layers into /rootfs."""

import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path


def extract_installer(installer_path: Path, build_dir: Path, rootfs_dir: Path) -> None:
    oci_dir = build_dir / "oci"
    oci_dir.mkdir(parents=True, exist_ok=True)
    rootfs_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(installer_path) as zf:
        zf.extract("image.tar", build_dir)

    with tarfile.open(build_dir / "image.tar") as itf:
        itf.extractall(oci_dir, filter="fully_trusted")

    manifest = json.loads((oci_dir / "manifest.json").read_text(encoding="utf-8"))
    layers = manifest[0].get("Layers", [])
    print(f"Extracting {len(layers)} OCI layers into {rootfs_dir}...")

    for layer_rel in layers:
        layer_path = oci_dir / layer_rel
        print(f"  Unpacking {layer_rel}...")
        with tarfile.open(layer_path) as tf:
            for member in tf.getmembers():
                rel = member.name.lstrip("./")
                if not rel:
                    continue
                base = os.path.basename(rel)
                parent = rootfs_dir / os.path.dirname(rel)

                if base == ".wh..wh..opq":
                    if parent.is_dir():
                        for entry in os.listdir(parent):
                            ep = parent / entry
                            if ep.is_dir() and not ep.is_symlink():
                                shutil.rmtree(ep, ignore_errors=True)
                            else:
                                ep.unlink(missing_ok=True)
                    continue

                if base.startswith(".wh."):
                    target_del = parent / base[4:]
                    if os.path.lexists(target_del):
                        if target_del.is_dir() and not target_del.is_symlink():
                            shutil.rmtree(target_del, ignore_errors=True)
                        else:
                            target_del.unlink(missing_ok=True)
                    continue

                dest = rootfs_dir / rel
                if os.path.lexists(dest) and not (
                    member.isdir() and dest.is_dir() and not dest.is_symlink()
                ):
                    if dest.is_dir() and not dest.is_symlink():
                        shutil.rmtree(dest, ignore_errors=True)
                    else:
                        dest.unlink(missing_ok=True)

                try:
                    tf.extract(member, path=rootfs_dir, set_attrs=True, filter="fully_trusted")
                except Exception as exc:
                    print(f"    warn: {rel}: {exc}")

    print("OCI rootfs extraction complete.")


if __name__ == "__main__":
    extract_installer(Path("/build/installer.bin"), Path("/build"), Path("/rootfs"))
