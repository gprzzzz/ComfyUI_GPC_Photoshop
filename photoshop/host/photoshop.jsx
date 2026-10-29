// Photoshop side of the panel (ExtendScript, so ES3: no let/const, arrows or JSON).
// Each gpc* function is called from the panel through evalScript and returns a
// string: JSON on success, or "ERROR: message".

var GPC_MASK_CHANNEL = "GPC Inpaint Mask";
var GPC_SRGB = "sRGB IEC61966-2.1";

function gpcQuote(s) {
  s = String(s);
  var out = '"';
  for (var i = 0; i < s.length; i++) {
    var c = s.charAt(i);
    var code = s.charCodeAt(i);
    if (c === '"' || c === "\\") out += "\\" + c;
    else if (code < 32) out += "\\u" + ("000" + code.toString(16)).slice(-4);
    else out += c;
  }
  return out + '"';
}

// Runs fn with pixel units and no dialogs, turning exceptions into "ERROR: ...".
function gpcRun(fn) {
  var units = app.preferences.rulerUnits;
  var dialogs = app.displayDialogs;
  try {
    app.preferences.rulerUnits = Units.PIXELS;
    app.displayDialogs = DialogModes.NO;
    return fn();
  } catch (e) {
    return "ERROR: " + e.message + (e.line ? " (line " + e.line + ")" : "");
  } finally {
    app.preferences.rulerUnits = units;
    app.displayDialogs = dialogs;
  }
}

function gpcPx(v) {
  return Math.round(v.as("px"));
}

function gpcColor(r, g, b) {
  var c = new SolidColor();
  c.rgb.red = r;
  c.rgb.green = g;
  c.rgb.blue = b;
  return c;
}

function gpcFindDocument(id) {
  for (var i = 0; i < app.documents.length; i++) {
    if (app.documents[i].id == id) return app.documents[i];
  }
  return null;
}

function gpcPngOptions() {
  var o = new PNGSaveOptions();
  o.compression = 6;
  o.interlaced = false;
  return o;
}

// Flat, 8-bit, RGB, sRGB: what the model expects.
function gpcNormalize(doc) {
  doc.flatten();
  if (doc.mode != DocumentMode.RGB) doc.changeMode(ChangeMode.RGB);
  if (doc.bitsPerChannel != BitsPerChannelType.EIGHT) doc.bitsPerChannel = BitsPerChannelType.EIGHT;
  try {
    if (doc.colorProfileName != GPC_SRGB) doc.convertProfile(GPC_SRGB, Intent.RELATIVECOLORIMETRIC, true, false);
  } catch (e) {
    // untagged documents have no profile name; treat them as sRGB
  }
}

function gpcDocInfo() {
  return gpcRun(function () {
    if (!app.documents.length) return "ERROR: Open a document first.";
    var d = app.activeDocument;
    return '{"id":' + d.id + ',"width":' + gpcPx(d.width) + ',"height":' + gpcPx(d.height) + ',"resolution":' + d.resolution + ',"title":' + gpcQuote(d.name) + "}";
  });
}

function gpcSelectionBounds() {
  return gpcRun(function () {
    var b;
    try {
      b = app.activeDocument.selection.bounds;
    } catch (e) {
      return "null"; // no selection
    }
    return '{"left":' + gpcPx(b[0]) + ',"top":' + gpcPx(b[1]) + ',"right":' + gpcPx(b[2]) + ',"bottom":' + gpcPx(b[3]) + "}";
  });
}

function gpcLayers() {
  return gpcRun(function () {
    if (!app.documents.length) return "[]";
    var out = [];
    var walk = function (layers, prefix) {
      for (var i = 0; i < layers.length; i++) {
        var l = layers[i];
        if (l.typename == "LayerSet") walk(l.layers, prefix + l.name + " / ");
        else out.push('{"id":' + l.id + ',"name":' + gpcQuote(prefix + l.name) + "}");
      }
    };
    walk(app.activeDocument.layers, "");
    return "[" + out.join(",") + "]";
  });
}

function gpcHasSelection(doc) {
  try {
    doc.selection.bounds;
    return true;
  } catch (e) {
    return false;
  }
}

// Saves the visible image inside the crop, and the selection as a mask (white =
// inpaint, feathering kept), as two PNG files. With no selection the mask is all white.
function gpcExportCanvas(left, top, right, bottom, imagePath, maskPath) {
  return gpcRun(function () {
    var src = app.activeDocument;
    var hadSelection = gpcHasSelection(src);
    if (!hadSelection) src.selection.selectAll();
    var channel = src.channels.add();
    channel.name = GPC_MASK_CHANNEL;
    src.selection.store(channel);
    var copy = null;
    try {
      copy = src.duplicate("GPC export", true);
      app.activeDocument = copy;
      gpcNormalize(copy);
      copy.selection.deselect();
      copy.crop([left, top, right, bottom]);
      copy.saveAs(new File(imagePath), gpcPngOptions(), true, Extension.LOWERCASE);

      copy.artLayers.add();
      copy.selection.selectAll();
      copy.selection.fill(gpcColor(0, 0, 0));
      copy.selection.load(copy.channels.getByName(GPC_MASK_CHANNEL));
      copy.selection.fill(gpcColor(255, 255, 255));
      copy.selection.deselect();
      copy.saveAs(new File(maskPath), gpcPngOptions(), true, Extension.LOWERCASE);
    } finally {
      if (copy) copy.close(SaveOptions.DONOTSAVECHANGES);
      app.activeDocument = src;
      if (hadSelection) src.selection.load(channel);
      else src.selection.deselect();
      channel.remove();
    }
    return '"ok"';
  });
}

function gpcFindLayer(layers, id) {
  for (var i = 0; i < layers.length; i++) {
    if (layers[i].id == id) return layers[i];
    if (layers[i].typename == "LayerSet") {
      var found = gpcFindLayer(layers[i].layers, id);
      if (found) return found;
    }
  }
  return null;
}

// Saves one layer, trimmed to its pixels and scaled to at most maxPixels, as a PNG.
function gpcExportLayer(layerId, path, maxPixels) {
  return gpcRun(function () {
    var src = app.activeDocument;
    var layer = gpcFindLayer(src.layers, layerId);
    if (!layer) return "ERROR: That reference layer no longer exists.";
    var copy = app.documents.add(src.width, src.height, src.resolution, "GPC reference", NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    try {
      app.activeDocument = src;
      var dup = layer.duplicate(copy, ElementPlacement.PLACEATBEGINNING);
      app.activeDocument = copy;
      dup.visible = true;
      copy.artLayers[copy.artLayers.length - 1].remove(); // the new document's empty layer
      copy.trim(TrimType.TRANSPARENT);
      gpcNormalize(copy);
      var w = gpcPx(copy.width);
      var h = gpcPx(copy.height);
      var scale = Math.sqrt(maxPixels / (w * h));
      if (scale < 1) copy.resizeImage(UnitValue(Math.round(w * scale), "px"), UnitValue(Math.round(h * scale), "px"), null, ResampleMethod.BICUBIC);
      copy.saveAs(new File(path), gpcPngOptions(), true, Extension.LOWERCASE);
    } finally {
      copy.close(SaveOptions.DONOTSAVECHANGES);
      app.activeDocument = src;
    }
    return '"ok"';
  });
}

// Runs fn as one history step ("Undo <title>") in doc.
function gpcInHistory(doc, title, fn) {
  $.global.gpcHistoryFn = fn;
  $.global.gpcHistoryResult = undefined;
  $.global.gpcHistoryError = null;
  doc.suspendHistory(title, "try { $.global.gpcHistoryResult = $.global.gpcHistoryFn(); } catch (e) { $.global.gpcHistoryError = e; }");
  if ($.global.gpcHistoryError) throw $.global.gpcHistoryError;
  return $.global.gpcHistoryResult;
}

function gpcPlaceImage(path) {
  var desc = new ActionDescriptor();
  desc.putPath(charIDToTypeID("null"), new File(path));
  desc.putEnumerated(charIDToTypeID("FTcs"), charIDToTypeID("QCSt"), charIDToTypeID("Qcsa"));
  var offset = new ActionDescriptor();
  offset.putUnitDouble(charIDToTypeID("Hrzn"), charIDToTypeID("#Pxl"), 0);
  offset.putUnitDouble(charIDToTypeID("Vrtc"), charIDToTypeID("#Pxl"), 0);
  desc.putObject(charIDToTypeID("Ofst"), charIDToTypeID("Ofst"), offset);
  executeAction(charIDToTypeID("Plc "), desc, DialogModes.NO);
}

// Opens the grayscale mask PNG, scales it to width x height and copies it into
// doc as a white layer whose transparency is the mask (not through the
// clipboard, which stays the user's). Returns the layer and where its visible
// pixels start inside the mask: { layer, left, top }.
function gpcMaskCarrier(doc, maskPath, width, height) {
  var m = app.open(new File(maskPath));
  try {
    m.resizeImage(UnitValue(width, "px"), UnitValue(height, "px"), null, ResampleMethod.BICUBIC);
    m.selection.load(m.channels[0]);
    var white = m.artLayers.add();
    m.selection.fill(gpcColor(255, 255, 255));
    m.selection.deselect();
    var b = white.bounds;
    var layer = white.duplicate(doc, ElementPlacement.PLACEATBEGINNING);
    return { layer: layer, left: b[0].as("px"), top: b[1].as("px") };
  } finally {
    m.close(SaveOptions.DONOTSAVECHANGES);
    app.activeDocument = doc;
  }
}

// Selects the transparency of layer (Ctrl+click on its thumbnail).
function gpcSelectTransparency(layer) {
  var desc = new ActionDescriptor();
  var sel = new ActionReference();
  sel.putProperty(charIDToTypeID("Chnl"), charIDToTypeID("fsel"));
  desc.putReference(charIDToTypeID("null"), sel);
  var from = new ActionReference();
  from.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("Trsp"));
  from.putIdentifier(charIDToTypeID("Lyr "), layer.id);
  desc.putReference(charIDToTypeID("T   "), from);
  executeAction(charIDToTypeID("setd"), desc, DialogModes.NO);
}

// Adds a layer mask revealing the selection to the active layer.
function gpcMaskFromSelection() {
  var desc = new ActionDescriptor();
  desc.putClass(charIDToTypeID("Nw  "), charIDToTypeID("Chnl"));
  var at = new ActionReference();
  at.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("Msk "));
  desc.putReference(charIDToTypeID("At  "), at);
  desc.putEnumerated(charIDToTypeID("Usng"), charIDToTypeID("UsrM"), charIDToTypeID("RvlS"));
  executeAction(charIDToTypeID("Mk  "), desc, DialogModes.NO);
}

// Gives layer the carrier's transparency as its layer mask, with the carrier's
// top-left on (left, top), then removes the carrier. The user's selection stays.
function gpcApplyMask(doc, layer, carrier, left, top) {
  var b = carrier.layer.bounds;
  carrier.layer.translate(left + carrier.left - b[0].as("px"), top + carrier.top - b[1].as("px"));
  var kept = null;
  if (gpcHasSelection(doc)) {
    kept = doc.channels.add();
    kept.name = GPC_MASK_CHANNEL;
    doc.selection.store(kept);
  }
  try {
    gpcSelectTransparency(carrier.layer);
    carrier.layer.remove();
    doc.activeLayer = layer;
    gpcMaskFromSelection();
  } finally {
    if (kept) {
      doc.selection.load(kept);
      kept.remove();
    } else {
      doc.selection.deselect();
    }
  }
}

// Places a result PNG into document docId as a smart object, without opening it
// as a document, so that the image's top-left lands at (left, top). Photoshop
// measures a layer by its visible pixels, so the panel passes where those are
// inside the PNG: vis = [left, top, right, bottom]. Removes layer replaceId
// first, if it still exists. With maskPath, the grayscale PNG there becomes the
// layer's mask, scaled to maskWidth x maskHeight at (left, top). Returns the new
// layer's id.
function gpcPlace(path, docId, left, top, vis, name, replaceId, maskPath, maskWidth, maskHeight) {
  return gpcRun(function () {
    var target = gpcFindDocument(docId);
    if (!target) return "ERROR: The document this was generated for is closed.";
    app.activeDocument = target;
    // Opening the mask switches documents, so it happens before the history step;
    // its layer is gone again by the end of it.
    var carrier = maskPath ? gpcMaskCarrier(target, maskPath, maskWidth, maskHeight) : null;
    var id = gpcInHistory(target, name, function () {
      var old = replaceId ? gpcFindLayer(target.layers, replaceId) : null;
      if (old) old.remove();
      gpcPlaceImage(path);
      var layer = target.activeLayer;
      layer.name = name;
      // Place sizes by resolution (the panel writes the document's into the PNG);
      // correct anything left over, e.g. from "Resize Image During Place".
      var width = vis[2] - vis[0];
      var height = vis[3] - vis[1];
      var b = layer.bounds;
      var w = b[2].as("px") - b[0].as("px");
      var h = b[3].as("px") - b[1].as("px");
      if (Math.abs(w - width) > 0.5 || Math.abs(h - height) > 0.5) {
        layer.resize((width / w) * 100, (height / h) * 100, AnchorPosition.TOPLEFT);
        b = layer.bounds;
      }
      var dx = left + vis[0] - b[0].as("px");
      var dy = top + vis[1] - b[1].as("px");
      if (dx || dy) layer.translate(dx, dy);
      if (carrier) gpcApplyMask(target, layer, carrier, left, top);
      return layer.id;
    });
    return String(id);
  });
}

// Opens smart object layerId's contents as a document, runs fn(inner), saves the
// contents back and closes them.
function gpcInSmartObject(target, layerId, fn) {
  var layer = gpcFindLayer(target.layers, layerId);
  if (!layer) throw new Error("The preview layer was deleted.");
  app.activeDocument = target;
  target.activeLayer = layer;
  executeAction(stringIDToTypeID("placedLayerEditContents"), new ActionDescriptor(), DialogModes.NO);
  var inner = app.activeDocument;
  try {
    fn(inner);
    inner.save();
  } finally {
    inner.close(SaveOptions.DONOTSAVECHANGES);
    app.activeDocument = target;
  }
}

// Inside a stack, layers run Result 1 (bottom) to Result n (top); shows only result index.
function gpcShowOnly(inner, index) {
  var n = inner.layers.length;
  for (var i = 0; i < n; i++) inner.layers[i].visible = n - 1 - i == index;
}

// Turns placed result layerId (no mask yet) into a stack: one smart object
// holding it and the PNGs at paths as smart objects Result 1, 2, ..., each with
// all its pixels, result show (0 = the first) visible. A placed PNG's contents
// are a PNG, which can't hold layers, so the layer is first wrapped in a new
// smart object (Convert to Smart Object), whose contents are a PSB at the
// layer's size in the document. With maskPath, the mask is added to the stack
// afterwards (converting a masked layer would move its mask inside). Returns
// the stack's layer id.
function gpcStack(docId, layerId, paths, show, maskPath, left, top, maskWidth, maskHeight) {
  return gpcRun(function () {
    var target = gpcFindDocument(docId);
    if (!target) return "ERROR: The document this was generated for is closed.";
    var layer = gpcFindLayer(target.layers, layerId);
    if (!layer) return "ERROR: The preview layer was deleted.";
    app.activeDocument = target;
    target.activeLayer = layer;
    var name = layer.name;
    executeAction(stringIDToTypeID("newPlacedLayer"), undefined, DialogModes.NO);
    var stack = target.activeLayer;
    stack.name = name;
    gpcInSmartObject(target, stack.id, function (inner) {
      var width = inner.width.as("px");
      var height = inner.height.as("px");
      inner.layers[0].name = "Result 1";
      for (var i = 0; i < paths.length; i++) {
        // The panel set each PNG's resolution so Place lands it at this size.
        gpcPlaceImage(paths[i]);
        var placed = inner.activeLayer;
        placed.name = "Result " + (i + 2);
        var b = placed.bounds;
        var w = b[2].as("px") - b[0].as("px");
        var h = b[3].as("px") - b[1].as("px");
        if (Math.abs(w - width) > 0.5 || Math.abs(h - height) > 0.5) placed.resize((width / w) * 100, (height / h) * 100, AnchorPosition.TOPLEFT);
        b = placed.bounds;
        if (b[0].as("px") || b[1].as("px")) placed.translate(-b[0].as("px"), -b[1].as("px"));
      }
      gpcShowOnly(inner, show);
    });
    if (maskPath) {
      var carrier = gpcMaskCarrier(target, maskPath, maskWidth, maskHeight);
      gpcInHistory(target, name, function () {
        gpcApplyMask(target, stack, carrier, left, top);
      });
    }
    return String(stack.id);
  });
}

// Shows result index inside a stacked smart object.
function gpcStackShow(docId, layerId, index) {
  return gpcRun(function () {
    var target = gpcFindDocument(docId);
    if (!target) return "ERROR: The document this was generated for is closed.";
    gpcInSmartObject(target, layerId, function (inner) {
      gpcShowOnly(inner, index);
    });
    return '"ok"';
  });
}

// Keeps a placed result under its final name, rasterized unless asked to stay a smart object.
function gpcBake(docId, layerId, name, keepSmart) {
  return gpcRun(function () {
    var target = gpcFindDocument(docId);
    if (!target) return "ERROR: The document this was generated for is closed.";
    var layer = gpcFindLayer(target.layers, layerId);
    if (!layer) return "ERROR: The preview layer was deleted.";
    app.activeDocument = target;
    gpcInHistory(target, name, function () {
      if (!keepSmart) layer.rasterize(RasterizeType.ENTIRELAYER);
      layer.name = name;
    });
    return '"ok"';
  });
}

// Removes a layer if it still exists (a preview the user may have deleted already).
function gpcRemoveLayer(docId, layerId) {
  return gpcRun(function () {
    var target = gpcFindDocument(docId);
    var layer = target ? gpcFindLayer(target.layers, layerId) : null;
    if (layer) {
      app.activeDocument = target;
      gpcInHistory(target, "Remove GPC preview", function () {
        layer.remove();
      });
    }
    return '"ok"';
  });
}

// Opens a result PNG as a new, untitled document called name, at the given resolution.
function gpcOpenAsDocument(path, name, resolution) {
  return gpcRun(function () {
    var opened = app.open(new File(path));
    var doc;
    try {
      try {
        opened.colorProfileName = GPC_SRGB;
      } catch (e) {
        // keep whatever profile it opened with
      }
      doc = opened.duplicate(name, false);
    } finally {
      opened.close(SaveOptions.DONOTSAVECHANGES);
    }
    app.activeDocument = doc;
    if (resolution) doc.resizeImage(undefined, undefined, resolution, ResampleMethod.NONE);
    return String(doc.id);
  });
}
