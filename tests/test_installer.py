import glob
import json
import os
import re
import shutil
import subprocess

import pytest

from nodes.templates import model_refs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, "installer", "GPC_Photoshop_Setup.bat")


def setup_text():
    with open(SETUP, newline="", encoding="ascii") as f:
        return f.read()


def installer_models():
    return re.findall(r"@\{ File = '([^']+)'; Folder = '([^']+)'; Size = (\d+); Sha256 = '([0-9a-f]{64})'; Url = 'https://[^']+' \}", setup_text())


def test_installer_downloads_exactly_what_the_templates_load():
    wanted = set()
    for path in glob.glob(os.path.join(ROOT, "templates", "*.json")):
        with open(path, encoding="utf-8") as f:
            wanted |= {(name, folder) for _, _, folder, name in model_refs(json.load(f))}
    assert {(name, folder) for name, folder, _, _ in installer_models()} == wanted


def test_setup_is_a_crlf_batch_file():
    text = setup_text()
    assert "\n" not in text.replace("\r\n", "")
    assert "#POWERSHELL\r\n" in text


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="needs Windows PowerShell")
def test_setup_parses_as_powershell(tmp_path):
    check = tmp_path / "check.ps1"
    check.write_text(
        "$text = ([IO.File]::ReadAllText($args[0]) -split '(?m)^#POWERSHELL\\r?$', 2)[1]\n"
        "$errors = $null\n"
        "[void][Management.Automation.Language.Parser]::ParseInput($text, [ref]$null, [ref]$errors)\n"
        "$errors | ForEach-Object { $_.ToString() }\n"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(check), SETUP], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == ""
