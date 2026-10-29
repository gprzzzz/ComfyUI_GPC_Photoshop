# Install

Two parts, both from this repo:

| Part | Where it goes |
| --- | --- |
| The node pack (repo root: `nodes/`, `templates/`) | `ComfyUI/custom_nodes/`. It serves the templates to the panel and adds the marker nodes they use |
| The Photoshop panel (`photoshop/`) | Photoshop's CEP extensions folder, linked by an installer |

## Requirements

- **Photoshop 2022 (v23) or newer**, Windows or macOS. No Creative Cloud app or sign-in needed.
- **A recent ComfyUI** (the templates use core nodes such as EasyCache and ModelPatchLoader). It can run
  on the same computer or another one on your network.
- A GPU that runs the models you pick. Flux 2 Klein 4B and Z-Image Turbo are the lightest; the
  Magnific tab needs no GPU at all.

## 1. ComfyUI side

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/gprzzzz/ComfyUI_GPC_Photoshop.git
```

Restart ComfyUI. The nodes appear under **GPC Photoshop**, and the startup log lists any template whose
nodes or models are missing, for example:

```
[GPC Photoshop] Template 'sdxl_img2img' won't run yet. Missing models: ip-adapter-plus_sdxl_vit-h.safetensors (in models/ipadapter). ...
```

### Node packs

Install these with ComfyUI-Manager or `git clone` into `custom_nodes/`, then restart ComfyUI:

| Pack | Needed by |
| --- | --- |
| [comfyui-inpaint-nodes](https://github.com/Acly/comfyui-inpaint-nodes) | every bundled template (mask grow, blur and color match) |
| [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | SDXL refine |
| [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) | SDXL refine (global context while tiling) |

### Models

Only the templates you use need their models. Put each file in the folder shown, inside
`ComfyUI/models/`. Subfolders are fine (`checkpoints/SDXL/…`): the panel finds a model by its file name.
If you use [Krita AI Diffusion](https://github.com/Acly/krita-ai-diffusion), its ComfyUI already has
most of these.

**Edit: Flux 2 Klein** (`flux2_klein_inpaint`)

| File | Folder |
| --- | --- |
| `flux2-klein-4b.safetensors` | `diffusion_models` |
| `qwen_3_4b.safetensors` | `text_encoders` |
| `flux2-vae.safetensors` | `vae` |

Klein 4B is Apache 2.0. The 9B model is non-commercial.

**Refine: SDXL** (`sdxl_img2img`)

| File | Folder |
| --- | --- |
| `juggernautXL_ragnarokBy.safetensors` (or any SDXL checkpoint: change the name in your own copy of the template) | `checkpoints` |
| `xinsir-controlnet-union-sdxl-1.0-promax.safetensors` | `controlnet` |
| `ip-adapter-plus_sdxl_vit-h.safetensors` | `ipadapter` |
| `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `clip_vision` |

**Upscale: Z-Image Turbo** (`zimage_upscale`)

| File | Folder |
| --- | --- |
| `z_image_turbo_bf16.safetensors` | `diffusion_models` |
| `qwen_3_4b.safetensors` | `text_encoders` |
| `flux_vae.safetensors` | `vae` |
| `Z-Image-Turbo-Fun-Controlnet-Tile-2.1-lite-2601-8steps.safetensors` | `model_patches` |

**Magnific: Nano Banana** (`nano_banana_2_1`, `nano_banana_pro`, `nano_banana_pro_flash`): no models,
but a Magnific API key (below).

## 2. Photoshop side

1. Close Photoshop.
2. Run the installer in this repo's `photoshop/` folder:
   - **Windows:** double-click `photoshop\install_windows.bat`
   - **macOS:** in Terminal, `sh photoshop/install_mac.sh`
3. Start Photoshop and open **Window › Extensions (legacy) › GPC ComfyUI**.
4. The panel connects to `http://127.0.0.1:8188` on its own. The dot at the top right is green when it's
   connected; click it to enter another address.

What the installer does:

- It **links** the `photoshop/` folder into your CEP extensions folder, so `git pull` updates the panel
  too (close and reopen the panel to load the new version).
- It sets **PlayerDebugMode**, which lets Photoshop load panels that aren't signed through Adobe's store,
  and turns on CEP logging for troubleshooting.

To do the same by hand:

| | Copy `photoshop/` into | Then set |
| --- | --- | --- |
| Windows | `%APPDATA%\Adobe\CEP\extensions\com.gpc.comfyui.photoshop` | registry `HKCU\Software\Adobe\CSXS.11`, string `PlayerDebugMode` = `1` |
| macOS | `~/Library/Application Support/Adobe/CEP/extensions/com.gpc.comfyui.photoshop` | `defaults write com.adobe.CSXS.11 PlayerDebugMode 1` |

(The installers set CSXS.9 to CSXS.12, which covers Photoshop 2022 and later.)

## 3. Connecting

- **Same computer:** nothing to set up. The panel talks to ComfyUI on `127.0.0.1`, which a firewall that
  blocks Adobe programs from the internet doesn't affect.
- **Another computer:** start ComfyUI with `--listen`, enter its address in the panel (click the dot),
  and allow Photoshop's `CEPHtmlEngine` through the firewall to reach it.

## 4. Magnific (optional)

The Magnific tab edits with Google's Nano Banana models through [Magnific's API](https://docs.magnific.com).
ComfyUI makes the requests, so the ComfyUI computer needs internet access; Photoshop doesn't.

1. Create an API key at [magnific.com › API keys](https://www.magnific.com/user/api-keys).
2. Give it to ComfyUI in **one** of these ways:
   - a text file holding only the key, at `ComfyUI/user/gpc_photoshop/magnific_api_key.txt`, or
   - the environment variable `MAGNIFIC_API_KEY`.
3. Restart ComfyUI.

**Every result costs Magnific credits**, even if your plan has unlimited Nano Banana in Magnific's own
app: API calls always run on credits. Keep the key file out of anything you share.

## Updating

```bash
cd ComfyUI/custom_nodes/ComfyUI_GPC_Photoshop
git pull
```

Then restart ComfyUI and close and reopen the panel (or restart Photoshop).

## Uninstalling

Delete `ComfyUI/custom_nodes/ComfyUI_GPC_Photoshop`, and the `com.gpc.comfyui.photoshop` link in the
CEP extensions folder from the table above. Your own templates in `ComfyUI/user/gpc_photoshop/` stay
until you delete them.

## Troubleshooting

**Window › Extensions (legacy) is grayed out, or the panel isn't listed.** Photoshop loaded no panel.
Check that the installer ran with Photoshop closed. The CEP log says why a panel was skipped: the newest
`CEP*-PHXS.log` in `%TEMP%` (Windows) or `~/Library/Logs/CSXS/` (macOS).

**The dot stays gray or red.** ComfyUI isn't reachable at that address. Open the address in a browser;
if ComfyUI's page loads there, click the dot, check the address and click **Connect**.

**"This ComfyUI doesn't have ComfyUI_GPC_Photoshop loaded."** The node pack isn't in that ComfyUI's
`custom_nodes`, or it failed to load: look for errors mentioning GPC Photoshop in ComfyUI's log.

**"Missing nodes: …" or "Missing models: …" under the prompt.** Install what it names (see above), then
click the dot and **Reload templates**.

**The panel is blank or a button does nothing.** To see the panel's own errors, create a file named
`.debug` in the `photoshop/` folder containing:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ExtensionList>
  <Extension Id="com.gpc.comfyui.photoshop.panel">
    <HostList>
      <Host Name="PHXS" Port="8098" />
      <Host Name="PHSP" Port="8098" />
    </HostList>
  </Extension>
</ExtensionList>
```

Restart Photoshop, open the panel, and browse to `http://localhost:8098` in Chrome or Edge to get its
console. Please include what it shows when you report a problem.
