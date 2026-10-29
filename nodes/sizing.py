"""Pure size math, kept free of torch so it can be tested anywhere."""

import math

MEGAPIXEL = 1024 * 1024


def fit_size(width, height, min_megapixels, max_megapixels, multiple):
    """Scale ``width x height`` into ``[min, max]`` megapixels, snapped to ``multiple``.

    A crop already inside the range keeps its scale and is only snapped. Aspect
    ratio is kept as closely as the snapping allows.
    """
    area = width * height
    scale = 1.0
    if area < min_megapixels * MEGAPIXEL:
        scale = math.sqrt(min_megapixels * MEGAPIXEL / area)
    elif area > max_megapixels * MEGAPIXEL:
        scale = math.sqrt(max_megapixels * MEGAPIXEL / area)
    return _snap(width * scale, multiple), _snap(height * scale, multiple)


def _snap(value, multiple):
    return max(multiple, int(round(value / multiple)) * multiple)


def needs_tiles(width, height, scale, untiled_max_megapixels):
    """Whether a crop, scaled by ``scale``, is too big to sample in one piece
    without shrinking it (and losing detail when it's scaled back)."""
    return width * height * scale * scale > untiled_max_megapixels * MEGAPIXEL
