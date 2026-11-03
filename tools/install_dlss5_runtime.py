"""Fetch or register the native DLSS 5 runtime that the DLSS5 Enhance node drives.

The runtime consists of NVIDIA, ReShade and RenoDX binaries that are not part of
this repository and are not redistributed by it. This downloads the DLSS 5 Visual
Enhancer release and keeps only its runtime folder, or records the path of an
existing one (from that application, or from ComfyUI-DLSS5-Enhancer). Adapted
from Blueforcer's install_runtime.py (MIT, see nodes/dlss5/LICENSE).

Run it with ComfyUI's Python:
    python tools/install_dlss5_runtime.py                      # download and install
    python tools/install_dlss5_runtime.py --runtime-dir <path> # use an existing runtime
"""

import argparse
import importlib.util
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Loaded on its own: importing the nodes package would need ComfyUI.
_spec = importlib.util.spec_from_file_location("gpc_dlss5_paths", HERE.parent / "nodes" / "dlss5" / "paths.py")
paths = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = paths
_spec.loader.exec_module(paths)

RELEASE_URL = "https://github.com/Merserk/dlss5-visual-enhancer/releases/download/v3.0/DLSS.5.Visual.Enhancer.v3.0.zip"
MARKER = "bin/runtime/"

NOTICE = """
This downloads the DLSS 5 Visual Enhancer release (about 467 MB) and extracts
only its runtime folder:

  nvngx.dll             standalone D3D12 worker built by the upstream project, under
                        its own terms (an executable, not NVIDIA's NGX core)
  nvngx_dlss.dll        DLSS Super Resolution runtime      - NVIDIA proprietary terms
  nvngx_dlssnr.dll      DLSS Neural Rendering runtime      - NVIDIA proprietary terms
  dxgi.dll              ReShade carrier                    - BSD-3-Clause
  renodx-dlss5.addon64  RenoDX DLSS 5 add-on               - its own distribution terms

These files are neither owned nor redistributed by GPC Photoshop. Install only
components you are authorised to use, from sources their licences permit.
"""


def download(url, target):
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as response, target.open("wb") as sink:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while block := response.read(1024 * 1024):
            sink.write(block)
            received += len(block)
            print(f"\r  {received / 1e6:8.1f}" + (f" / {total / 1e6:.1f}" if total else "") + " MB", end="")
    print()
    if total and received != total:
        raise SystemExit(f"The download stopped after {received} of {total} bytes. Run the script again.")


def extract(archive_path, target):
    with zipfile.ZipFile(archive_path) as archive:
        members = []
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            at = name.lower().find(MARKER)
            if info.is_dir() or at < 0:
                continue
            relative = Path(name[at + len(MARKER) :])
            # Entries that would land outside the target are skipped.
            if relative.is_absolute() or relative.drive or ".." in relative.parts:
                print(f"Skipped unsafe archive entry: {info.filename}")
                continue
            members.append((info, relative))
        if not members:
            raise SystemExit(f"The archive contains no {MARKER} entries.")
        target.mkdir(parents=True, exist_ok=True)
        for existing in target.glob("*"):
            try:
                if existing.is_file():
                    existing.open("ab").close()
            except OSError as exc:
                raise SystemExit(f"{existing} is in use ({exc}). Close ComfyUI first.")
        print(f"Extracting {len(members)} files to {target}")
        for info, relative in members:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as sink:
                shutil.copyfileobj(source, sink)


def register(runtime_dir):
    paths.RuntimeLayout(root=runtime_dir).validate()
    print(f"Registered {runtime_dir}\nWrote {paths.write_runtime_file(runtime_dir)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime-dir", type=Path, help="Use an existing runtime folder (the one holding nvngx.dll).")
    parser.add_argument("--url", default=RELEASE_URL, help="Release archive to download.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    if args.runtime_dir:
        try:
            register(args.runtime_dir.expanduser().resolve())
        except paths.RuntimeMissing as e:
            raise SystemExit(str(e))
        return

    print(NOTICE)
    if not args.url.lower().startswith("https://"):
        raise SystemExit(f"Refusing to download {args.url}: only https URLs are accepted.")
    if not args.yes and input("Continue? [y/N] ").strip().lower() not in {"y", "yes"}:
        raise SystemExit("Aborted.")
    with tempfile.TemporaryDirectory(prefix="dlss5-") as workspace:
        archive = Path(workspace) / "release.zip"
        download(args.url, archive)
        extract(archive, paths.BUNDLED_RUNTIME)
    paths.RuntimeLayout(root=paths.BUNDLED_RUNTIME).validate()
    print(f"Runtime ready in {paths.BUNDLED_RUNTIME}. Restart ComfyUI.")


if __name__ == "__main__":
    main()
