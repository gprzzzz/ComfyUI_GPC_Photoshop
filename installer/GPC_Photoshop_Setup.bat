@echo off
rem GPC Photoshop setup for Windows: installs ComfyUI, the node pack and the Photoshop panel.
rem One file on purpose, so it can be downloaded and double-clicked. The rest of it is PowerShell.
set "GPC_SETUP_FILE=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$GpcScript = ([IO.File]::ReadAllText($env:GPC_SETUP_FILE) -split '(?m)^#POWERSHELL\r?$', 2)[1]; & ([scriptblock]::Create($GpcScript))"
exit /b %errorlevel%
#POWERSHELL
$ErrorActionPreference = 'Stop'

# ---- What gets installed. Versions are the ones the templates were tested with. ----

$UvVersion = '0.9.26'
$PythonVersion = '3.12'
$TorchVersion = '2.9.1'
$TorchVisionVersion = '0.24.1'
$CudaFlavor = 'cu128'
$ComfyCommit = 'a11f68dd3b5393b6afc37e01c91fa84963d2668a'
$PackZip = 'https://github.com/gprzzzz/ComfyUI_GPC_Photoshop/archive/refs/heads/main.zip'
$PackName = 'ComfyUI_GPC_Photoshop'
$MarkerName = '.gpc_install.json'

$NodePacks = @(
    @{ Name = 'comfyui-inpaint-nodes'; Repo = 'Acly/comfyui-inpaint-nodes'; Commit = 'd74ecec6c377073a6885697f07a019d050f0d545'; LocalOnly = $false }
    @{ Name = 'comfyui_controlnet_aux'; Repo = 'Fannovel16/comfyui_controlnet_aux'; Commit = '83463c2e4b04e729268e57f638b4212e0da4badc'; LocalOnly = $true }
    @{ Name = 'ComfyUI_IPAdapter_plus'; Repo = 'cubiq/ComfyUI_IPAdapter_plus'; Commit = 'b188a6cb39b512a9c6da7235b880af42c78ccd0d'; LocalOnly = $true }
)

# What comfyui_controlnet_aux needs for the one node the templates use, and to load without errors.
$LocalPackages = @('scikit-image', 'scikit-learn', 'matplotlib', 'huggingface_hub', 'importlib_metadata', 'python-dateutil', 'omegaconf', 'ftfy', 'addict', 'yacs', 'yapf', 'fvcore', 'trimesh', 'albumentations')

$Models = @(
    @{ File = 'flux2-klein-4b.safetensors'; Folder = 'diffusion_models'; Size = 7751105712; Sha256 = 'ec3d4e733a771f61c052fb4856c48b336c55eaf2c65487c2a1faeb9bbda7a343'; Url = 'https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/resolve/main/flux-2-klein-4b.safetensors' }
    @{ File = 'qwen_3_4b.safetensors'; Folder = 'text_encoders'; Size = 8044982048; Sha256 = '6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a'; Url = 'https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors' }
    @{ File = 'flux2-vae.safetensors'; Folder = 'vae'; Size = 336211292; Sha256 = '868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3'; Url = 'https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b/resolve/main/split_files/vae/flux2-vae.safetensors' }
    @{ File = 'juggernautXL_ragnarokBy.safetensors'; Folder = 'checkpoints'; Size = 7105350162; Sha256 = 'dd08fa32f98d05a2443ca1419e46df1575a0811f6e3b246d9dd47ff20f5eb66a'; Url = 'https://civitai.com/api/download/models/1759168' }
    @{ File = 'xinsir-controlnet-union-sdxl-1.0-promax.safetensors'; Folder = 'controlnet'; Size = 2513342408; Sha256 = '9fae2e50cb431bfcbe05822b59ec2228df545ef27f711dea8949e9f4ed9f7cdc'; Url = 'https://huggingface.co/xinsir/controlnet-union-sdxl-1.0/resolve/main/diffusion_pytorch_model_promax.safetensors' }
    @{ File = 'ip-adapter-plus_sdxl_vit-h.safetensors'; Folder = 'ipadapter'; Size = 847517512; Sha256 = '3f5062b8400c94b7159665b21ba5c62acdcd7682262743d7f2aefedef00e6581'; Url = 'https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors' }
    @{ File = 'CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors'; Folder = 'clip_vision'; Size = 2528373448; Sha256 = '6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030'; Url = 'https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors' }
    @{ File = 'z_image_turbo_bf16.safetensors'; Folder = 'diffusion_models'; Size = 12309866400; Sha256 = '2407613050b809ffdff18a4ac99af83ea6b95443ecebdf80e064a79c825574a6'; Url = 'https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors' }
    @{ File = 'flux_vae.safetensors'; Folder = 'vae'; Size = 335304388; Sha256 = 'afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38'; Url = 'https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors' }
    @{ File = 'Z-Image-Turbo-Fun-Controlnet-Tile-2.1-lite-2601-8steps.safetensors'; Folder = 'model_patches'; Size = 2016627488; Sha256 = '880bf452b060abfcbccedee56f8d3dbf8aed2cb0311b599210361b414fc8f2fd'; Url = 'https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Tile-2.1-lite-2601-8steps.safetensors' }
    @{ File = '4x_NMKD-Superscale-SP_178000_G.pth'; Folder = 'upscale_models'; Size = 66958607; Sha256 = '1d1b0078fe71446e0469d8d4df59e96baa80d83cda600d68237d655830821bcc'; Url = 'https://huggingface.co/gemasai/4x_NMKD-Superscale-SP_178000_G/resolve/main/4x_NMKD-Superscale-SP_178000_G.pth' }
)

# Disk space, in GB, on top of the models.
$BaseGb = 3
$CudaExtraGb = 6
$DlssGb = 1

# Keeps a later release of a dependency from breaking a tested ComfyUI.
$Constraints = @'
addict==2.4.0
aiohappyeyeballs==2.7.1
aiohttp==3.14.5
aiosignal==1.4.0
albucore==0.0.24
albumentations==2.0.8
alembic==1.20.1
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.16.0
attrs==26.1.0
av==19.0.2
blake3==1.0.11
certifi==2026.10.23
charset-normalizer==3.5.2
click==8.5.0
cloudpickle==3.1.2
colorama==0.4.6
comfy-aimdo==0.6.0
comfy-kitchen==0.2.40
comfyui-embedded-docs==0.4.3
comfyui-frontend-package==1.41.21
comfyui-workflow-templates==0.9.26
comfyui-workflow-templates-core==0.3.173
comfyui-workflow-templates-media-api==0.3.64
comfyui-workflow-templates-media-image==0.3.107
comfyui-workflow-templates-media-other==0.3.146
comfyui-workflow-templates-media-video==0.3.62
contourpy==1.4.0
cycler==0.12.1
einops==0.8.2
filelock==4.2.4
fonttools==4.68.0
frozenlist==1.8.0
fsspec==2026.9.0
ftfy==6.3.1
fvcore==0.1.5.post20221221
glfw==2.11.0
h11==0.16.0
hf-xet==1.8.0
httpcore2==2.16.0
httpx2==2.16.0
huggingface-hub==2.4.0
idna==3.20
imageio==2.38.1
importlib-metadata==10.1.0
iopath==0.1.10
jinja2==3.1.6
joblib==1.6.0
kiwisolver==1.5.1
kornia==0.9.0
kornia-rs==0.2.0
lazy-loader==0.6
mako==1.4.3
markdown-it-py==4.2.0
markupsafe==3.0.3
matplotlib==3.11.2
mdurl==0.1.2
mpmath==1.3.0
multidict==7.2.1
narwhals==2.28.0
networkx==3.7
numpy==2.5.4
omegaconf==2.4.0
opencv-python-headless==5.0.0.93
packaging==26.3
pillow==13.0.0
platformdirs==4.14.3
portalocker==4.4.2
propcache==0.5.4
psutil==7.2.2
pydantic==2.14.2
pydantic-core==2.50.2
pydantic-settings==2.16.2
pygments==2.21.0
pyopengl==3.1.10
pyparsing==3.3.3
python-dateutil==4.0.0
python-dotenv==1.2.4
pyyaml==6.0.3
regex==2026.9.29
requests==2.34.2
rich==15.0.0
safetensors==0.8.0
scikit-image==0.26.0
scikit-learn==1.9.1
scipy==1.18.1
sentencepiece==0.2.2
setuptools==78.1.0
shellingham==1.5.4
simpleeval==1.0.8
simsimd==6.5.16
spandrel==0.4.2
sqlalchemy==2.1.6
stringzilla==5.3.2
sympy==1.14.0
tabulate==0.10.0
termcolor==3.3.0
threadpoolctl==3.7.0
tifffile==2026.10.15
tokenizers==0.23.3
torchsde==0.2.6
tqdm==4.70.1
trampoline==0.1.2
transformers==5.22.1
trimesh==5.2.0
truststore==0.10.5
typer==0.27.3
typing-extensions==4.16.0
typing-inspection==0.4.4
tzdata==2026.6
urllib3==2.8.0
wcwidth==0.9.4
yacs==0.1.8
yapf==0.43.0
yarl==1.25.1
zipp==4.1.2
'@

$CepDir = if ($env:GPC_SETUP_CEP) { $env:GPC_SETUP_CEP } else { Join-Path $env:APPDATA 'Adobe\CEP\extensions' }
$PanelId = 'com.gpc.comfyui.photoshop'
$ShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Start ComfyUI (GPC Photoshop).lnk'

# ---- Helpers, used on the worker thread ----

function Write-Log($S, [string]$text) {
    [void]$S.Log.Add($text)
    if ($S.LogFile) { [IO.File]::AppendAllText($S.LogFile, $text + "`r`n") }
}

function Enter-Step($S, [string]$status) {
    $S.Status = $status
    $S.Detail = ''
    $S.StepBase = $S.StepBase + $S.StepWeight
    $S.StepWeight = $S.Plan[$status]
    Set-StepFraction $S 0
    Write-Log $S $status
}

function Set-StepFraction($S, [double]$fraction) {
    $S.Percent = [int][Math]::Min(100, 100.0 * ($S.StepBase + $S.StepWeight * $fraction) / $S.PlanTotal)
}

function Test-Cancel($S) {
    if ($S.Cancel) { throw 'Stopped. Run setup again to carry on where it left off.' }
}

# Runs a program with no window, its output going to install.log. Returns its exit code.
function Invoke-Tool($S, [string]$exe, [string[]]$arguments, [string]$cwd, [scriptblock]$tick) {
    $out = Join-Path $S.Dir 'downloads\tool_output.txt'
    $line = '"' + $exe + '" ' + (($arguments | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = Join-Path $env:SystemRoot 'System32\cmd.exe'
    $psi.Arguments = '/d /s /c "' + $line + ' > "' + $out + '" 2>&1"'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = if ($cwd) { $cwd } else { $S.Dir }
    $psi.EnvironmentVariables['UV_CACHE_DIR'] = Join-Path $S.Dir 'downloads\uv_cache'
    $psi.EnvironmentVariables['UV_PYTHON_INSTALL_DIR'] = Join-Path $S.Dir 'python'
    $psi.EnvironmentVariables['UV_PYTHON_PREFERENCE'] = 'only-managed'
    $psi.EnvironmentVariables['UV_NO_CONFIG'] = '1'
    $process = [Diagnostics.Process]::Start($psi)
    try {
        while (-not $process.WaitForExit(300)) {
            Test-Cancel $S
            if ($tick) { & $tick }
        }
    } finally {
        # Stopped, or something above failed: don't leave a download running.
        if (-not $process.HasExited) {
            & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /T /F /PID $process.Id 2>&1 | Out-Null
            [void]$process.WaitForExit(5000)
        }
    }
    $code = $process.ExitCode
    if (Test-Path $out) {
        # Progress bars rewrite one line with carriage returns; keep what they ended on.
        $lines = (Get-Content -LiteralPath $out -Raw) -split '\r?\n' | ForEach-Object { ($_ -split '\r')[-1] } | Where-Object { $_ }
        $S.LastOutput = @($lines | Select-Object -Last 6) -join "`r`n"
        if ($S.LogFile -and $lines) { [IO.File]::AppendAllText($S.LogFile, (($lines -join "`r`n") + "`r`n")) }
        Remove-Item -LiteralPath $out -Force
    }
    return $code
}

function Invoke-Checked($S, [string]$exe, [string[]]$arguments, [string]$what, [string]$cwd) {
    $code = Invoke-Tool $S $exe $arguments $cwd $null
    if ($code -ne 0) { throw "$what failed (exit code $code).`r`n$($S.LastOutput)" }
}

function Format-Gb([double]$bytes) { '{0:N1} GB' -f ($bytes / 1GB) }

# Downloads to <path>.part, resuming when the size is known, and checks it before renaming.
function Get-Download($S, [string]$url, [string]$path, [long]$size, [string]$sha256, [long]$doneBytes, [long]$totalBytes) {
    $part = "$path.part"
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    $name = Split-Path $path -Leaf
    $tick = {
        if ($size -gt 0 -and (Test-Path -LiteralPath $part)) {
            $have = (Get-Item -LiteralPath $part).Length
            $S.Detail = "$name  $(Format-Gb $have) of $(Format-Gb $size)"
            if ($totalBytes -gt 0) { Set-StepFraction $S (($doneBytes + $have) / $totalBytes) }
        }
    }
    if ($size -le 0 -and (Test-Path -LiteralPath $part)) { Remove-Item -LiteralPath $part -Force }
    $lastError = ''
    foreach ($attempt in 1..4) {
        Test-Cancel $S
        $have = if (Test-Path -LiteralPath $part) { (Get-Item -LiteralPath $part).Length } else { 0 }
        if ($size -gt 0 -and $have -eq $size) { break }
        if ($size -gt 0 -and $have -gt $size) { Remove-Item -LiteralPath $part -Force }
        $arguments = @('-L', '--fail', '-sS', '--connect-timeout', '30', '-o', $part)
        if ($size -gt 0) { $arguments += @('-C', '-') }
        $arguments += $url
        $code = Invoke-Tool $S $curl $arguments $S.Dir $tick
        if ($code -eq 0) { $lastError = ''; break }
        $lastError = "curl exit code $code. $($S.LastOutput)"
        Write-Log $S "  $name`: try $attempt failed: $lastError"
        # The server refused to resume: start over.
        if ($code -eq 33) { Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue }
        if ($attempt -lt 4) { Start-Sleep -Seconds (5 * $attempt) }
    }
    if ($lastError) { throw "Couldn't download $name`: $lastError" }
    if ($sha256) {
        $S.Detail = "$name  checking"
        $actual = (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $sha256) {
            Remove-Item -LiteralPath $part -Force
            throw "$name came down damaged or changed at the source (checksum mismatch). Run setup again to retry."
        }
    }
    Move-Item -LiteralPath $part -Destination $path -Force
}

# Unpacks a GitHub source zip into target, dropping its top folder.
function Expand-Source($S, [string]$zip, [string]$target) {
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    Invoke-Checked $S $tar @('-xf', $zip, '--strip-components=1', '-C', $target) "Unpacking $(Split-Path $zip -Leaf)"
    Remove-Item -LiteralPath $zip -Force
}

function Read-Marker([string]$dir) {
    $path = Join-Path $dir $MarkerName
    if (Test-Path -LiteralPath $path) { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
    return $null
}

function Write-Marker($S) {
    $S.Marker | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $S.Dir $MarkerName) -Encoding UTF8
}

# Why setup can't use this folder, or nothing. A folder of other things is refused so that
# neither setup nor the uninstaller ever mixes with them.
function Test-InstallDir([string]$dir) {
    if (-not $dir -or -not [IO.Path]::IsPathRooted($dir)) { return 'Choose a full folder path.' }
    if ($dir -match '[^\x20-\x7E]') { return 'Choose a folder whose path uses plain English letters: some of the tools fail on others.' }
    if (Test-Path -LiteralPath $dir) {
        if (-not (Test-Path -LiteralPath $dir -PathType Container)) { return 'That path is a file.' }
        if ((Get-ChildItem -LiteralPath $dir -Force | Measure-Object).Count -gt 0 -and -not (Test-Path -LiteralPath (Join-Path $dir $MarkerName))) {
            return 'That folder already has other things in it. Choose an empty or new folder.'
        }
    }
    return $null
}

function Get-RunningComfy([string]$dir) {
    $prefix = (Join-Path $dir 'venv').ToLower()
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith($prefix) }
}

function Get-MissingModels([string]$dir) {
    $Models | Where-Object {
        $file = Join-Path $dir ('ComfyUI\models\' + $_.Folder + '\' + $_.File)
        -not ((Test-Path -LiteralPath $file) -and (Get-Item -LiteralPath $file).Length -eq $_.Size)
    }
}

function Install-Panel($S) {
    $source = Join-Path $S.Dir "ComfyUI\custom_nodes\$PackName\photoshop"
    $target = Join-Path $CepDir $PanelId
    New-Item -ItemType Directory -Force -Path $CepDir | Out-Null
    if (Test-Path -LiteralPath $target) {
        if (-not ((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "$target is a folder, not a link from an earlier install. Delete it, then run setup again."
        }
        # Delete, not recursive: this removes the link and leaves what it points at.
        [IO.Directory]::Delete($target)
    }
    New-Item -ItemType Junction -Path $target -Target $source | Out-Null
    if (-not $env:GPC_SETUP_CEP) {
        # Lets Photoshop load a panel that isn't signed through Adobe's store. Versions read
        # different keys, so set them all; LogLevel 6 writes logs for when a panel won't load.
        foreach ($version in 9..12) {
            $key = "HKCU:\Software\Adobe\CSXS.$version"
            New-Item -Path $key -Force | Out-Null
            Set-ItemProperty -Path $key -Name PlayerDebugMode -Value '1'
            Set-ItemProperty -Path $key -Name LogLevel -Value '6'
        }
    }
}

function Write-Launchers($S, [bool]$cuda) {
    $flags = '--windows-standalone-build --disable-auto-launch'
    if (-not $cuda) { $flags += ' --cpu' }
    $start = @"
@echo off
title ComfyUI for GPC Photoshop
cd /d "%~dp0"
venv\Scripts\python.exe -s ComfyUI\main.py $flags
pause
"@
    [IO.File]::WriteAllText((Join-Path $S.Dir 'Start ComfyUI.bat'), $start.Replace("`r`n", "`n").Replace("`n", "`r`n"))
    $link = Join-Path $CepDir $PanelId
    $uninstall = @"
@echo off
echo This removes ComfyUI, its models, your ComfyUI\output images and your Magnific key from:
echo   %~dp0
echo and the panel from Photoshop. Close Photoshop and ComfyUI first.
echo.
set /p ANSWER=Type YES to remove them:
if /i not "%ANSWER%"=="YES" exit /b 0
powershell.exe -NoProfile -Command "`$l = '$link'; if ((Test-Path -LiteralPath `$l) -and ((Get-Item -LiteralPath `$l).Target -join '').ToLower().StartsWith('$($S.Dir.ToLower())')) { [IO.Directory]::Delete(`$l) }"
if exist "$ShortcutPath" del "$ShortcutPath"
cd /d "%~dp0.."
for %%D in (ComfyUI venv python uv downloads) do if exist "%~dp0%%D" rmdir /s /q "%~dp0%%D"
del /q "%~dp0Start ComfyUI.bat" "%~dp0$MarkerName" "%~dp0install.log" 2>nul
echo Removed.
pause
(goto) 2>nul & del "%~f0" & rmdir "%~dp0"
"@
    [IO.File]::WriteAllText((Join-Path $S.Dir 'Uninstall.bat'), $uninstall.Replace("`r`n", "`n").Replace("`n", "`r`n"))
    if (-not $env:GPC_SETUP_CEP) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($ShortcutPath)
        $shortcut.TargetPath = Join-Path $S.Dir 'Start ComfyUI.bat'
        $shortcut.WorkingDirectory = $S.Dir
        $shortcut.Save()
    }
}

# The install itself. $S is a synchronized hashtable shared with the window: Dir, Local, Magnific,
# Dlss and MagnificKey come in; Status, Detail, Percent, Log, Problems, Error and Done go out.
function Start-Install($S) {
    try {
        $dir = $S.Dir
        New-Item -ItemType Directory -Force -Path $dir, (Join-Path $dir 'downloads') | Out-Null
        $S.LogFile = Join-Path $dir 'install.log'
        Write-Log $S "---- $(Get-Date -Format s)  folder: $dir  local: $($S.Local)  magnific: $($S.Magnific)  dlss: $($S.Dlss)"

        $previous = Read-Marker $dir
        $S.Marker = @{
            Comfy = if ($previous) { $previous.Comfy } else { '' }
            Torch = if ($previous) { $previous.Torch } else { '' }
            Packs = if ($previous -and $previous.Packs) { @($previous.Packs) } else { @() }
            Local = [bool]($S.Local -or ($previous -and $previous.Local))
        }
        Write-Marker $S
        # A CUDA PyTorch stays once it's there; running from it is fine without local models.
        $cuda = [bool]($S.Marker.Local -or $S.Marker.Torch -eq 'cuda')
        $torchWanted = if ($cuda) { 'cuda' } else { 'cpu' }
        $missing = if ($S.Local) { @(Get-MissingModels $dir) } else { @() }

        $S.Plan = [ordered]@{
            'Getting uv and Python' = 3
            'Getting ComfyUI' = 3
            'Installing PyTorch' = $(if ($cuda) { 15 } else { 5 })
            'Installing ComfyUI''s Python packages' = 6
            'Getting the node packs' = 2
            'Getting GPC Photoshop' = 1
            'Linking the Photoshop panel' = 1
        }
        if ($S.MagnificKey) { $S.Plan['Saving your Magnific key'] = 1 }
        if ($S.Dlss) { $S.Plan['Getting the DLSS 5 runtime'] = 5 }
        if ($S.Local) { $S.Plan['Downloading models'] = $(if ($missing) { 60 } else { 1 }) }
        $S.Plan['Finishing up'] = 1
        $S.PlanTotal = ($S.Plan.Values | Measure-Object -Sum).Sum
        $S.StepBase = 0
        $S.StepWeight = 0

        Enter-Step $S 'Getting uv and Python'
        $uv = Join-Path $dir 'uv\uv.exe'
        if (-not (Test-Path -LiteralPath $uv)) {
            $zip = Join-Path $dir 'downloads\uv.zip'
            Get-Download $S "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip" $zip 0 '' 0 0
            New-Item -ItemType Directory -Force -Path (Join-Path $dir 'uv') | Out-Null
            Invoke-Checked $S (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xf', $zip, '-C', (Join-Path $dir 'uv')) 'Unpacking uv'
            Remove-Item -LiteralPath $zip -Force
        }
        $python = Join-Path $dir 'venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $python)) {
            Invoke-Checked $S $uv @('venv', '--python', $PythonVersion, (Join-Path $dir 'venv')) 'Creating the Python environment'
        }

        Enter-Step $S 'Getting ComfyUI'
        $comfy = Join-Path $dir 'ComfyUI'
        if ($S.Marker.Comfy -ne $ComfyCommit -or -not (Test-Path -LiteralPath (Join-Path $comfy 'main.py'))) {
            $zip = Join-Path $dir 'downloads\ComfyUI.zip'
            Get-Download $S "https://github.com/comfyanonymous/ComfyUI/archive/$ComfyCommit.zip" $zip 0 '' 0 0
            Expand-Source $S $zip $comfy
            $S.Marker.Comfy = $ComfyCommit
            Write-Marker $S
        }

        Enter-Step $S 'Installing PyTorch'
        if ($S.Marker.Torch -ne $torchWanted) {
            $flavor = if ($cuda) { $CudaFlavor } else { 'cpu' }
            Invoke-Checked $S $uv @('pip', 'install', '--python', $python, '--index-url', "https://download.pytorch.org/whl/$flavor",
                "torch==$TorchVersion+$flavor", "torchvision==$TorchVisionVersion+$flavor", "torchaudio==$TorchVersion+$flavor") 'Installing PyTorch'
            $S.Marker.Torch = $torchWanted
            Write-Marker $S
        }

        Enter-Step $S 'Installing ComfyUI''s Python packages'
        $constraintsFile = Join-Path $dir 'downloads\constraints.txt'
        [IO.File]::WriteAllText($constraintsFile, $Constraints)
        $packages = @('-r', (Join-Path $comfy 'requirements.txt'), 'opencv-python-headless')
        if ($S.Marker.Local) { $packages += $LocalPackages }
        Invoke-Checked $S $uv (@('pip', 'install', '--python', $python, '-c', $constraintsFile) + $packages) 'Installing ComfyUI''s Python packages'

        Enter-Step $S 'Getting the node packs'
        foreach ($pack in $NodePacks) {
            if ($pack.LocalOnly -and -not $S.Marker.Local) { continue }
            $id = "$($pack.Name)@$($pack.Commit)"
            $target = Join-Path $comfy "custom_nodes\$($pack.Name)"
            if ($S.Marker.Packs -contains $id -and (Test-Path -LiteralPath $target)) { continue }
            $S.Detail = $pack.Name
            $zip = Join-Path $dir "downloads\$($pack.Name).zip"
            Get-Download $S "https://github.com/$($pack.Repo)/archive/$($pack.Commit).zip" $zip 0 '' 0 0
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
            Expand-Source $S $zip $target
            $S.Marker.Packs = @($S.Marker.Packs | Where-Object { $_ -notlike "$($pack.Name)@*" }) + $id
            Write-Marker $S
        }

        # Always the latest, so running setup again also updates. The DLSS runtime lives inside.
        Enter-Step $S 'Getting GPC Photoshop'
        $zip = Join-Path $dir 'downloads\pack.zip'
        Get-Download $S $PackZip $zip 0 '' 0 0
        $fresh = Join-Path $dir 'downloads\pack_new'
        if (Test-Path -LiteralPath $fresh) { Remove-Item -LiteralPath $fresh -Recurse -Force }
        Expand-Source $S $zip $fresh
        $packDir = Join-Path $comfy "custom_nodes\$PackName"
        if (Test-Path -LiteralPath $packDir) {
            try {
                if (Test-Path -LiteralPath (Join-Path $packDir 'dlss5_runtime')) {
                    Move-Item -LiteralPath (Join-Path $packDir 'dlss5_runtime') -Destination (Join-Path $fresh 'dlss5_runtime')
                }
                Remove-Item -LiteralPath $packDir -Recurse -Force
            } catch {
                throw "Couldn't replace $packDir`: close Photoshop and ComfyUI, then run setup again. ($_)"
            }
        }
        Move-Item -LiteralPath $fresh -Destination $packDir

        Enter-Step $S 'Linking the Photoshop panel'
        Install-Panel $S

        if ($S.MagnificKey) {
            Enter-Step $S 'Saving your Magnific key'
            $userDir = Join-Path $comfy 'user\gpc_photoshop'
            New-Item -ItemType Directory -Force -Path $userDir | Out-Null
            [IO.File]::WriteAllText((Join-Path $userDir 'magnific_api_key.txt'), $S.MagnificKey.Trim())
        }

        if ($S.Dlss) {
            Enter-Step $S 'Getting the DLSS 5 runtime'
            if (-not (Test-Path -LiteralPath (Join-Path $packDir 'dlss5_runtime\nvngx.dll'))) {
                $S.Detail = 'about 467 MB'
                $code = Invoke-Tool $S $python @((Join-Path $packDir 'tools\install_dlss5_runtime.py'), '--yes') $comfy $null
                if ($code -ne 0) { [void]$S.Problems.Add("The DLSS 5 runtime didn't install: $($S.LastOutput)") }
            }
        }

        if ($S.Local) {
            Enter-Step $S 'Downloading models'
            $total = [long](($missing | ForEach-Object { $_.Size } | Measure-Object -Sum).Sum)
            $done = [long]0
            foreach ($model in $missing) {
                Test-Cancel $S
                $folder = Join-Path $comfy "models\$($model.Folder)"
                New-Item -ItemType Directory -Force -Path $folder | Out-Null
                Write-Log $S "  $($model.File)"
                try {
                    Get-Download $S $model.Url (Join-Path $folder $model.File) $model.Size $model.Sha256 $done $total
                } catch {
                    if ($S.Cancel) { throw }
                    # One bad download shouldn't cost the others. Setup resumes it when run again.
                    [void]$S.Problems.Add("$_")
                    Write-Log $S "  $_"
                }
                $done += $model.Size
            }
        }

        Enter-Step $S 'Finishing up'
        Write-Launchers $S $cuda
        Remove-Item -LiteralPath (Join-Path $dir 'downloads') -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log $S 'Done.'
        $S.Percent = 100
    } catch {
        $S.Error = "$_"
        Write-Log $S "$_"
    } finally {
        $S.Done = $true
    }
}

function New-SetupState($dir, [bool]$local, [bool]$magnific, [bool]$dlss, [string]$key) {
    $S = [hashtable]::Synchronized(@{})
    $S.Dir = $dir
    $S.Local = $local
    $S.Magnific = $magnific
    $S.Dlss = $dlss
    $S.MagnificKey = $key
    $S.Log = [Collections.ArrayList]::Synchronized((New-Object Collections.ArrayList))
    $S.Problems = [Collections.ArrayList]::Synchronized((New-Object Collections.ArrayList))
    $S.Percent = 0
    $S.Status = ''
    $S.Detail = ''
    $S.Done = $false
    $S.Cancel = $false
    return $S
}

# ---- The window ----

function Get-DefaultDir {
    # An earlier install is where the panel's link points: <dir>\ComfyUI\custom_nodes\<pack>\photoshop.
    $link = Join-Path $CepDir $PanelId
    if (Test-Path -LiteralPath $link) {
        $target = @((Get-Item -LiteralPath $link -Force).Target)[0]
        if ($target) {
            $root = Split-Path (Split-Path (Split-Path (Split-Path $target)))
            if ($root -and (Test-Path -LiteralPath (Join-Path $root $MarkerName))) { return $root }
        }
    }
    return Join-Path $env:USERPROFILE 'GPC_Photoshop'
}

function Show-Setup {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()

    $gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
    $nvidia = @($gpus | Where-Object { $_ -match 'NVIDIA' })
    $modelBytes = [double](($Models | ForEach-Object { $_.Size } | Measure-Object -Sum).Sum)

    $ui = @{ Index = 0; State = $null; PowerShell = $null }
    $regular = New-Object Drawing.Font 'Segoe UI', 9
    $small = New-Object Drawing.Font 'Segoe UI', 8.5
    $bold = New-Object Drawing.Font 'Segoe UI', 9, ([Drawing.FontStyle]::Bold)
    $grey = [Drawing.SystemColors]::GrayText

    function New-Label([string]$text, $x, $y, $w, $h, $font, $color) {
        $label = New-Object Windows.Forms.Label
        $label.Text = $text
        $label.Location = New-Object Drawing.Point $x, $y
        $label.Size = New-Object Drawing.Size $w, $h
        if ($font) { $label.Font = $font }
        if ($color) { $label.ForeColor = $color }
        return $label
    }

    function New-Check([string]$text, $x, $y, $w) {
        $check = New-Object Windows.Forms.CheckBox
        $check.Text = $text
        $check.Font = $bold
        $check.Location = New-Object Drawing.Point $x, $y
        $check.Size = New-Object Drawing.Size $w, 22
        return $check
    }

    function New-Button([string]$text, $x, $y, $w) {
        $button = New-Object Windows.Forms.Button
        $button.Text = $text
        $button.Location = New-Object Drawing.Point $x, $y
        $button.Size = New-Object Drawing.Size $w, 30
        return $button
    }

    $form = New-Object Windows.Forms.Form
    $form.Text = 'GPC Photoshop setup'
    $form.Font = $regular
    $form.AutoScaleMode = 'None'
    $form.ClientSize = New-Object Drawing.Size 580, 500
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.StartPosition = 'CenterScreen'

    # Choices
    $choose = New-Object Windows.Forms.Panel
    $choose.Dock = 'Fill'
    $form.Controls.Add($choose)

    $choose.Controls.Add((New-Label 'Installs its own ComfyUI and the Photoshop panel, and leaves any other ComfyUI or Python alone. Run this again later to add more or to update.' 16 12 548 38 $null $null))

    $choose.Controls.Add((New-Label 'Install in' 16 58 60 20 $null $null))
    $folder = New-Object Windows.Forms.TextBox
    $folder.Location = New-Object Drawing.Point 78, 55
    $folder.Size = New-Object Drawing.Size 400, 23
    $folder.Text = Get-DefaultDir
    $choose.Controls.Add($folder)
    $browse = New-Button 'Browse...' 484 53 80
    $browse.Height = 27
    $choose.Controls.Add($browse)

    $checkLocal = New-Check 'All workflows: Edit, Refine and Upscale on your own GPU' 16 92 548
    $choose.Controls.Add($checkLocal)
    $choose.Controls.Add((New-Label ("Flux 2 Klein, SDXL and Z-Image Turbo: $('{0:N0}' -f ($modelBytes / 1GB)) GB of models, each under its own license. Needs a powerful NVIDIA card.") 34 114 530 34 $small $grey))

    $checkMagnific = New-Check 'Magnific: Nano Banana edits' 16 154 548
    $checkMagnific.Checked = $true
    $choose.Controls.Add($checkMagnific)
    $choose.Controls.Add((New-Label 'Runs on Magnific''s servers, so it needs no GPU, but every result costs Magnific credits.' 34 176 530 18 $small $grey))
    $keyLabel = New-Label 'API key' 34 199 50 20 $small $null
    $choose.Controls.Add($keyLabel)
    $key = New-Object Windows.Forms.TextBox
    $key.Location = New-Object Drawing.Point 88, 196
    $key.Size = New-Object Drawing.Size 300, 23
    $key.UseSystemPasswordChar = $true
    $choose.Controls.Add($key)
    $keyLink = New-Object Windows.Forms.LinkLabel
    $keyLink.Text = 'Get a key at magnific.com'
    $keyLink.Font = $small
    $keyLink.Location = New-Object Drawing.Point 396, 199
    $keyLink.Size = New-Object Drawing.Size 168, 18
    $keyLink.add_LinkClicked({ Start-Process 'https://www.magnific.com/user/api-keys' })
    $choose.Controls.Add($keyLink)

    $checkDlss = New-Check 'DLSS 5: Enhance on the Post tab' 16 230 548
    $checkDlss.Checked = [bool]$nvidia
    $choose.Controls.Add($checkDlss)
    $choose.Controls.Add((New-Label 'Runs on your GPU: needs an NVIDIA RTX 30, 40 or 50 card. Downloads about 467 MB.' 34 252 530 18 $small $grey))

    $gpuText = if ($gpus) { 'Graphics card found: ' + ($gpus -join ', ') } else { 'No graphics card found.' }
    if (-not $nvidia) {
        $gpuText += '. No NVIDIA card, so only Magnific is available.'
        $checkLocal.Enabled = $false
        $checkDlss.Enabled = $false
    }
    $choose.Controls.Add((New-Label $gpuText 16 286 548 36 $small $null))

    $space = New-Label '' 16 326 548 36 $small $null
    $choose.Controls.Add($space)

    $choose.Controls.Add((New-Label 'Always installed: ComfyUI, Python, the GPC Photoshop nodes and the Photoshop panel.' 16 370 548 18 $small $grey))

    $install = New-Button 'Install' 374 450 92
    $cancel = New-Button 'Cancel' 472 450 92
    $choose.Controls.Add($install)
    $choose.Controls.Add($cancel)
    $form.AcceptButton = $install
    $form.CancelButton = $cancel

    # Progress
    $work = New-Object Windows.Forms.Panel
    $work.Dock = 'Fill'
    $work.Visible = $false
    $form.Controls.Add($work)
    $status = New-Label 'Starting' 16 14 548 20 $bold $null
    $work.Controls.Add($status)
    $detail = New-Label '' 16 34 548 18 $small $grey
    $work.Controls.Add($detail)
    $bar = New-Object Windows.Forms.ProgressBar
    $bar.Location = New-Object Drawing.Point 16, 56
    $bar.Size = New-Object Drawing.Size 548, 18
    $work.Controls.Add($bar)
    $log = New-Object Windows.Forms.TextBox
    $log.Multiline = $true
    $log.ReadOnly = $true
    $log.ScrollBars = 'Vertical'
    $log.Location = New-Object Drawing.Point 16, 84
    $log.Size = New-Object Drawing.Size 548, 356
    $log.BackColor = [Drawing.SystemColors]::Window
    $work.Controls.Add($log)
    $startComfy = New-Button 'Start ComfyUI' 356 450 110
    $startComfy.Visible = $false
    $work.Controls.Add($startComfy)
    $stop = New-Button 'Stop' 472 450 92
    $work.Controls.Add($stop)

    $needed = {
        $gb = $BaseGb
        if ($checkLocal.Checked) { $gb += $CudaExtraGb + $modelBytes / 1GB }
        if ($checkDlss.Checked) { $gb += $DlssGb }
        return [Math]::Ceiling($gb)
    }

    $refresh = {
        $key.Enabled = $checkMagnific.Checked
        $keyLabel.Enabled = $checkMagnific.Checked
        $install.Enabled = $checkLocal.Checked -or $checkMagnific.Checked -or $checkDlss.Checked
        $text = "Needs about $(& $needed) GB of disk space."
        try {
            $free = (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($folder.Text))).AvailableFreeSpace
            $text += " $('{0:N0}' -f ($free / 1GB)) GB free on that drive."
        } catch { }
        $problem = Test-InstallDir $folder.Text
        if ($problem) { $text += "`r`n$problem" }
        elseif (Test-Path -LiteralPath (Join-Path $folder.Text $MarkerName)) { $text += "`r`nGPC Photoshop is already here: this adds what you tick and updates the rest." }
        $space.Text = $text
    }

    foreach ($check in $checkLocal, $checkMagnific, $checkDlss) { $check.add_CheckedChanged($refresh) }
    $folder.add_TextChanged($refresh)
    $browse.add_Click({
        $dialog = New-Object Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Choose an empty or new folder. The models alone can take tens of GB.'
        if ($dialog.ShowDialog($form) -eq 'OK') { $folder.Text = Join-Path $dialog.SelectedPath 'GPC_Photoshop' }
    })
    $cancel.add_Click({ $form.Close() })
    $startComfy.add_Click({
        Start-Process -FilePath (Join-Path $ui.State.Dir 'Start ComfyUI.bat') -WorkingDirectory $ui.State.Dir
        $form.Close()
    })
    $stop.add_Click({
        if ($ui.State -and -not $ui.State.Done) {
            $ui.State.Cancel = $true
            $stop.Enabled = $false
            $status.Text = 'Stopping'
        } else {
            $form.Close()
        }
    })

    $timer = New-Object Windows.Forms.Timer
    $timer.Interval = 250
    $timer.add_Tick({
        $S = $ui.State
        if (-not $S) { return }
        while ($ui.Index -lt $S.Log.Count) {
            $log.AppendText($S.Log[$ui.Index] + "`r`n")
            $ui.Index++
        }
        if (-not $S.Done) {
            if (-not $S.Cancel) { $status.Text = $S.Status }
            $detail.Text = $S.Detail
            $bar.Value = [Math]::Max(0, [Math]::Min(100, $S.Percent))
            return
        }
        $timer.Stop()
        $detail.Text = ''
        $stop.Text = 'Close'
        $stop.Enabled = $true
        if ($S.Error) {
            $status.Text = if ($S.Cancel) { 'Stopped' } else { 'Setup stopped with a problem' }
            $log.AppendText("`r`nRun setup again to carry on where it left off. Details are in $($S.LogFile)`r`n")
            return
        }
        $bar.Value = 100
        $startComfy.Visible = $true
        $next = "`r`nNext:`r`n  1. Start ComfyUI with the button below, or the shortcut on your desktop. Leave its window open.`r`n  2. Start Photoshop (restart it if it's open).`r`n  3. Open Window > Extensions (legacy) > GPC ComfyUI. The dot at the top turns green when it connects.`r`n"
        if ($S.Magnific -and -not $S.MagnificKey -and -not (Test-Path -LiteralPath (Join-Path $S.Dir 'ComfyUI\user\gpc_photoshop\magnific_api_key.txt'))) {
            $next += "`r`nNo Magnific key yet: run setup again to add one, or put it in`r`n  $($S.Dir)\ComfyUI\user\gpc_photoshop\magnific_api_key.txt`r`n"
        }
        if (-not $S.Marker.Local) {
            $next += "`r`nThe Edit, Refine and Upscale tabs will say what's missing: run setup again and tick All workflows to add them.`r`n"
        }
        if ($S.Problems.Count) {
            $status.Text = 'Installed, with problems'
            $next = "`r`nThese didn't finish. Run setup again to retry them:`r`n  " + (($S.Problems | ForEach-Object { "$_" }) -join "`r`n  ") + "`r`n" + $next
        } else {
            $status.Text = 'Installed'
        }
        $log.AppendText($next)
    })

    $install.add_Click({
        $dir = $folder.Text.Trim().TrimEnd('\')
        $problem = Test-InstallDir $dir
        if ($problem) {
            [void][Windows.Forms.MessageBox]::Show($form, $problem, 'GPC Photoshop setup', 'OK', 'Warning')
            return
        }
        if (@(Get-RunningComfy $dir).Count) {
            [void][Windows.Forms.MessageBox]::Show($form, 'ComfyUI from this folder is running. Close its window, then click Install.', 'GPC Photoshop setup', 'OK', 'Warning')
            return
        }
        try {
            $free = (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($dir))).AvailableFreeSpace / 1GB
            if ($free -lt (& $needed) -and -not (Test-Path -LiteralPath (Join-Path $dir $MarkerName))) {
                $answer = [Windows.Forms.MessageBox]::Show($form, "That drive has $('{0:N0}' -f $free) GB free and this needs about $(& $needed) GB. Install anyway?", 'GPC Photoshop setup', 'YesNo', 'Warning')
                if ($answer -ne 'Yes') { return }
            }
        } catch { }
        if ($checkDlss.Checked) {
            $terms = "DLSS 5 needs files this project doesn't include or own. Setup downloads the DLSS 5 Visual Enhancer release (github.com/Merserk/dlss5-visual-enhancer) and keeps only its runtime: a worker built by that project, NVIDIA's DLSS runtimes (NVIDIA's proprietary terms), ReShade (BSD-3-Clause) and the RenoDX add-on (its own terms).`r`n`r`nInstall them only if you're allowed to use them under those terms. Antivirus software sometimes blocks the worker, nvngx.dll.`r`n`r`nContinue with DLSS 5?"
            if ([Windows.Forms.MessageBox]::Show($form, $terms, 'DLSS 5 runtime', 'YesNo', 'Information') -ne 'Yes') { return }
        }
        $choose.Visible = $false
        $work.Visible = $true
        $form.AcceptButton = $null
        $form.CancelButton = $null
        $keyText = if ($checkMagnific.Checked) { $key.Text } else { '' }
        $ui.State = New-SetupState $dir $checkLocal.Checked $checkMagnific.Checked $checkDlss.Checked $keyText

        $ui.PowerShell = [PowerShell]::Create()
        $ui.PowerShell.Runspace = [RunspaceFactory]::CreateRunspace()
        $ui.PowerShell.Runspace.Open()
        $ui.PowerShell.Runspace.SessionStateProxy.SetVariable('GpcScript', $GpcScript)
        $ui.PowerShell.Runspace.SessionStateProxy.SetVariable('GpcWorkerState', $ui.State)
        [void]$ui.PowerShell.AddScript($GpcScript)
        [void]$ui.PowerShell.BeginInvoke()
        $timer.Start()
    })

    $form.add_FormClosing({
        param($sender, $closing)
        if ($ui.State -and -not $ui.State.Done) {
            $answer = [Windows.Forms.MessageBox]::Show($form, 'Stop the install? Running setup again carries on where it left off.', 'GPC Photoshop setup', 'YesNo', 'Question')
            if ($answer -eq 'Yes') { $ui.State.Cancel = $true }
            $closing.Cancel = $true
        }
    })

    & $refresh
    # Everything above is laid out for 96 DPI; the fonts already follow the screen's.
    $graphics = $form.CreateGraphics()
    $scale = $graphics.DpiX / 96
    $graphics.Dispose()
    $form.Scale((New-Object Drawing.SizeF $scale, $scale))
    $form.ClientSize = New-Object Drawing.Size ([int](580 * $scale)), ([int](500 * $scale))
    if ($GpcShowForm) { & $GpcShowForm $form }
    else { [void]$form.ShowDialog() }
    $timer.Dispose()
}

# ---- Entry points ----

if ($GpcWorkerState) {
    # The worker thread the window starts.
    Start-Install $GpcWorkerState
} elseif ($env:GPC_SETUP_COMPONENTS) {
    # No window, for testing: GPC_SETUP_COMPONENTS=local,magnific,dlss and GPC_SETUP_DIR.
    # GPC_SETUP_CEP replaces the panel's extensions folder and skips the registry and shortcut.
    $parts = $env:GPC_SETUP_COMPONENTS -split ','
    $problem = Test-InstallDir $env:GPC_SETUP_DIR
    if ($problem) { Write-Output $problem; exit 2 }
    $state = New-SetupState $env:GPC_SETUP_DIR ($parts -contains 'local') ($parts -contains 'magnific') ($parts -contains 'dlss') $env:GPC_SETUP_MAGNIFIC_KEY
    Start-Install $state
    $state.Log | ForEach-Object { Write-Output $_ }
    if ($state.Problems.Count) { $state.Problems | ForEach-Object { Write-Output "PROBLEM: $_" } }
    if ($state.Error -or $state.Problems.Count) { exit 1 }
    exit 0
} else {
    try {
        Add-Type -Name Window -Namespace GpcSetup -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
'@
        [void][GpcSetup.Window]::SetProcessDPIAware()
        [void][GpcSetup.Window]::ShowWindow([GpcSetup.Window]::GetConsoleWindow(), 0)
    } catch { }
    try {
        Show-Setup
    } catch {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show("Setup couldn't continue: $_", 'GPC Photoshop setup', 'OK', 'Error')
        exit 1
    }
}
