"""Discovery and validation of the native DLSS 5 runtime.

The runtime binaries are NVIDIA/ReShade/RenoDX components that this repository
neither ships nor redistributes; ``tools/install_dlss5_runtime.py`` fetches them,
or points at an existing DLSS 5 Visual Enhancer or ComfyUI-DLSS5-Enhancer install.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parents[2]
# ComfyUI/custom_nodes/<this pack> -> ComfyUI
COMFY_ROOT = PACK_ROOT.parents[1]
BUNDLED_RUNTIME = PACK_ROOT / "dlss5_runtime"
RUNTIME_FILE = "dlss5_runtime.txt"
# Blueforcer's pack, when it's installed next to this one.
UPSTREAM_PACK = PACK_ROOT.parent / "ComfyUI-DLSS5-Enhancer"

RUNTIME_ENV = "DLSS5_RUNTIME_DIR"

# The worker keeps NVIDIA's image name because the signed-snippet caller
# contract checks it; it is an executable, not a library.
WORKER_NAME = "nvngx.dll"

REQUIRED_RUNTIME_FILES = (
    WORKER_NAME,
    "dxgi.dll",
    "renodx-dlss5.addon64",
    "nvngx_dlss.dll",
    "nvngx_dlssnr.dll",
)

SETUP_HINT = """Install it with (from the ComfyUI folder, with ComfyUI's Python):
    python custom_nodes/ComfyUI_GPC_Photoshop/tools/install_dlss5_runtime.py
or point it at an existing runtime folder (the one holding nvngx.dll):
    python ... install_dlss5_runtime.py --runtime-dir <path>
or set the DLSS5_RUNTIME_DIR environment variable."""


class RuntimeMissing(RuntimeError):
    """Raised when the native runtime is absent or incomplete."""


@dataclass(frozen=True, slots=True)
class RuntimeLayout:
    """Resolved locations of every binary a render session needs."""

    root: Path
    # Excluded from equality so the layout stays hashable and comparable.
    config: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def worker(self) -> Path:
        return self.root / WORKER_NAME

    @property
    def addon(self) -> Path:
        return self.root / "renodx-dlss5.addon64"

    @property
    def neural_runtime(self) -> Path:
        return self.root / "nvngx_dlssnr.dll"

    @property
    def reshade_log(self) -> Path:
        return self.root / "ReShade.log"

    def validate(self) -> "RuntimeLayout":
        missing = [
            str(self.root / name)
            for name in REQUIRED_RUNTIME_FILES
            if not (self.root / name).is_file()
        ]
        if missing:
            raise RuntimeMissing(
                "The DLSS 5 runtime in "
                f"{self.root} is incomplete. Missing:\n  "
                + "\n  ".join(missing)
                + "\n\n"
                + SETUP_HINT
            )
        return self


def user_dir() -> Path:
    try:
        import folder_paths

        return Path(folder_paths.get_user_directory())
    except ImportError:  # the install script runs outside ComfyUI
        return COMFY_ROOT / "user"


def runtime_file() -> Path:
    return user_dir() / "gpc_photoshop" / RUNTIME_FILE


def write_runtime_file(runtime_dir: Path) -> Path:
    """Remember the runtime location for later ComfyUI sessions."""
    target = runtime_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(Path(runtime_dir).resolve()) + "\n", encoding="utf-8")
    return target


def _read_line(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _upstream_config() -> str:
    try:
        data = json.loads((UPSTREAM_PACK / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return data.get("runtime_dir", "") if isinstance(data, dict) else ""


def _runtime_candidates() -> list[Path]:
    values = [
        os.environ.get(RUNTIME_ENV, ""),
        _read_line(runtime_file()),
        str(BUNDLED_RUNTIME),
        _upstream_config(),
        str(UPSTREAM_PACK / "runtime"),
    ]
    return [Path(v) for v in values if v]


def find_runtime(override: str | os.PathLike[str] | None = None) -> RuntimeLayout:
    """Locate the runtime; ``override`` wins, then the env var, the user file, our
    own folder and Blueforcer's pack next to this one."""
    candidates = [Path(override)] if override else _runtime_candidates()

    for candidate in candidates:
        root = candidate.expanduser()
        if (root / WORKER_NAME).is_file():
            return RuntimeLayout(root=root.resolve()).validate()

    searched = "\n  ".join(str(path) for path in candidates)
    raise RuntimeMissing(
        "No DLSS 5 runtime was found. Searched:\n  " + searched + "\n\n" + SETUP_HINT
    )
