# Templates

The panel doesn't know about any model. Each **template** is an ordinary ComfyUI workflow in API
format, with a few **marker nodes** that tell the panel where the canvas goes in, where results come
out and which settings to show. To use another model, build its graph in ComfyUI around the same
markers; no panel change is needed.

## Where templates live

The panel lists templates from:

- `templates/` in this pack (the bundled ones, updated by `git pull`)
- `ComfyUI/user/gpc_photoshop/` (yours; a file with the same name overrides a bundled one)

After adding or changing one, click the dot at the top right of the panel and **Reload templates**.

Model names in a template are file names: the server finds each one in its models folder, subfolders
included, so a template works whatever your folder layout. A model that isn't installed is reported in
the panel and in ComfyUI's startup log.

## Making one

1. Build and test the workflow in ComfyUI.
2. Replace its input image with **PS Canvas**, its output with **PS Output**, and the values you want in
   the panel (prompt, strength, steps) with **PS Text / PS Int / PS Float / PS Toggle** nodes.
3. To try it inside ComfyUI, connect a **Load Image** to PS Canvas's `test_image` (and a mask to
   `test_mask`) and queue it as usual. The panel's values replace these.
4. Export it with **Workflow › Export (API)** (turn on *Settings › Dev mode* if the entry is missing),
   save it to `ComfyUI/user/gpc_photoshop/my_template.json`, and reload templates in the panel.

The panel lists controls in node-id order. PS Output's `mode` decides which tab the template appears in.

## Marker and helper nodes

| Node | Role |
| --- | --- |
| **PS Canvas** | Required, exactly one. Outputs the crop around the selection, its mask (white = change) and the crop's width and height, for scaling results back |
| **PS Output** | Required. Sends images back. With `mask` connected, the mask becomes the result's transparency, which is how results blend into the document. `placement` "upscaled" marks results larger than what was sent. `mode` is the tab: edit, refine, upscale or magnific. `mask_as` "layer mask" sends the mask separately, and the panel adds it to the placed layer as a layer mask, so the whole result stays editable |
| **PS Text** | A text box. The first is the prompt; others show smaller below it, or under Advanced with `advanced` ticked (e.g. a prompt suffix). `<Slot label>` mentions become the model's image numbers. Optional `hint`: shown when hovering its name |
| **PS Int / PS Float / PS Toggle** | A control with `label`, `value`, `min`, `max`, `step`, under Advanced. Tick `advanced` to list it after the others, or `main` to show it above the button. PS Toggle's `number` output is `on_number` or `off_number`, e.g. a ControlNet strength that 0 turns off. Optional `hint` |
| **PS Seed** | The seed. Random per run unless the panel's lock is on |
| **PS Reference Latent** | A reference image slot for edit-style models (Flux 2 / Klein, Kontext). An empty slot passes the conditioning through |
| **PS Reference Image** | A reference image slot as a plain IMAGE, plus `provided` (false when empty), for models that take images differently |
| **Magnific Nano Banana** | Sends `image` and up to three references to Nano Banana on Magnific and returns the results, aligned with the image. `model`, `resolution` (auto picks 1K or 2K), `batch`, `thinking` (2.1 only). Needs the Magnific API key |
| **PS Join Text** | Joins two texts with a separator, skipping an empty one, e.g. your prompt and a quality suffix |
| **PS Full Selection Switch** | Passes `partial` through, or `full` when the whole crop is selected; only the branch used runs. The bundled templates skip Color Match with it, which returns black for a full selection |
| **PS Fit Resolution** | Scales the canvas and mask into the model's megapixel range, snapped to a multiple |
| **PS Auto Tile** | Turns tiling on when the crop (times a scale) is too big to sample in one piece without shrinking it, and gives the matching megapixel cap |
| **PS Tiled Diffusion** | A model patch that samples images larger than the model's native size in overlapping tiles, blended at every step (Mixture of Diffusers weights on a grid that shifts each step, as in SpotDiffusion), so there are no seams. ControlNets get each tile's slice. Written from the papers |
| **PS Tiled Refine** | Img2img sampling tile by tile for any image size, with an optional Z-Image / Qwen Image Fun ControlNet per tile. The upscale template's sampler |
| **PS Noise Mask** | *Set Latent Noise Mask*, except that a mask covering everything sets none, so a full selection runs as a plain edit |

The `image` and `mask` inputs on the markers are filled in by the panel; leave them empty.

## The bundled templates

### Flux 2 Klein (`flux2_klein_inpaint`)

Follows the graph Krita AI Diffusion uses for Klein inpainting:

1. Differential Diffusion on the model, so the mask's soft edges become soft denoise.
2. The crop is scaled into 0.6–2 MP (smaller is soft on big selections; more runs out of video memory,
   since the crop also goes in as a reference). The mask is grown and feathered (*Mask grow / feather*).
3. The crop is the first reference latent; up to two more come from the panel's slots.
4. Latent noise mask, 8 euler steps, CFG 1, *Batch* results at once.
5. Color match against the original outside the mask, then scaled back to the crop's size.
6. The output mask is the grown mask shrunk and re-feathered (*Blend shrink / feather*).

### SDXL refine (`sdxl_img2img`)

Follows Krita AI Diffusion's SDXL refine graph: Juggernaut XL with the xinsir ControlNet Union in tile
mode, and EasyCache.

- **Prompt** gets the **Prompt suffix** (Advanced) appended; the optional **Negative** goes before the
  **Default negative** (Advanced).
- **Strength** skips that share of the 20 steps: 0.5 runs the last 10.
- **ControlNet end** (0.95) is a point on the noise timeline, not a share of the steps, and the karras
  schedule puts most steps near the end: 0.95 frees 5 of 20 steps, 0.8 frees 8 of the 12 run at strength
  0.6, which lets SDXL invent details. 1.0 is a little softer.
- **Resolution scale** (1.5) works at 1.5× the crop: up to 2 MP in one piece, up to 6 MP tiled.
- **Auto tile** tiles when the scaled crop is over 2 MP, in seamless 1024 px tiles, and gives every tile
  the whole crop as an IP-Adapter image prompt (**Global context**, 0.45), so a plain patch of sky still
  knows it's sky. Tiling also encodes and decodes in tiles, so big crops fit in video memory.

### Z-Image upscale (`zimage_upscale`)

Follows Krita AI Diffusion's Z-Image Turbo upscale: a lanczos upscale, then a refine in tiles (PS Tiled
Refine) with the Z-Image Fun tile ControlNet. CFG 1 (Turbo is distilled; higher looked the same and was
slower), 15 steps, 896 px tiles, "4k uhd" as the prompt suffix.

### Nano Banana (`nano_banana_2_1`, `nano_banana_pro`, `nano_banana_pro_flash`)

PS Canvas → Magnific Nano Banana → PS Output with `mask_as` "layer mask". The node sends each result to
the panel as soon as Magnific finishes it, and puts it back where it came from: Nano Banana scales its
input to fill its own frame and trims a few pixels off two edges, which the node undoes so results line
up with the document.

## Comparing settings without Photoshop

`tools/sweep.py` runs a template straight through ComfyUI over every combination of settings you give
it, with a fixed seed, and saves the results plus a labelled `sheet.png` with timings. Settings use the
panel's names. Run it from this repo's folder with ComfyUI's Python (it needs Pillow):

```bash
python tools/sweep.py --template sdxl_img2img --image photo.png \
    --prompt "a photograph of a house surrounded by trees" \
    --sweep "Auto tile=off,on" --sweep "Tile ControlNet=off,on" --set "Strength=0.6"
```

`--mask mask.png` limits the change to the white area (default: everything), `--reference 1=file.png`
fills a reference slot, `--server` points at another ComfyUI. Results go to `sweep_out/`.

## Developing

```bash
pip install pytest numpy pillow torch   # or use ComfyUI's Python, which has them
pytest                                   # nodes, templates, the sweep tool
npm test                                 # panel logic and the Photoshop script's plumbing
```

The panel is a CEP extension: an HTML page with Node.js (`photoshop/index.js`, `photoshop/src/`) that
drives Photoshop through ExtendScript (`photoshop/host/photoshop.jsx`, which has to stay ES3). Pixels go
in and out as temporary PNG files: the selection is stored in a temporary channel, the document is
duplicated, flattened, converted to 8-bit sRGB and cropped, and the image and mask are saved as PNGs.
Results are placed with Photoshop's Place command (no document opens): the panel writes the document's
resolution into the PNG so it lands at the right size, and lines it up by its visible pixels (which is
how Photoshop measures a layer).

`template.js` and `comfy.js` have no Photoshop APIs and are tested under Node; the host script is
tested against a small fake of Photoshop's DOM, so those tests check its plumbing, not Photoshop
itself. CEP's Chromium is about version 87: keep the panel's JavaScript and CSS to what it supports.
