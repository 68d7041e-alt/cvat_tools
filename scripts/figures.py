#!/usr/bin/env python3
"""Map between the source figures.json schema and CVAT shapes, in both directions.

Holds no transport: the caller passes plain dictionaries in and gets plain dictionaries
back, so the same label naming and keypoint order serve the import and the export.
"""

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

# CSS colour names used by meta.json; an unlisted name is an error rather than a default.
CSS_COLORS = {
    "aqua": "#00ffff",
    "black": "#000000",
    "blue": "#0000ff",
    "brown": "#a52a2a",
    "cyan": "#00ffff",
    "fuchsia": "#ff00ff",
    "gold": "#ffd700",
    "gray": "#808080",
    "green": "#008000",
    "lime": "#00ff00",
    "magenta": "#ff00ff",
    "maroon": "#800000",
    "navy": "#000080",
    "olive": "#808000",
    "orange": "#ffa500",
    "pink": "#ffc0cb",
    "purple": "#800080",
    "red": "#ff0000",
    "silver": "#c0c0c0",
    "teal": "#008080",
    "violet": "#ee82ee",
    "white": "#ffffff",
    "yellow": "#ffff00",
}

SKELETON_SUFFIX = "_skeleton"
TRASH_LABEL = "trash"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")

# The skeleton svg lives in a 100x100 viewport; keep the nodes off the edges.
VIEWPORT_MIN = 10.0
VIEWPORT_MAX = 90.0


def color(name: str) -> str:
    if name.startswith("#"):
        return name
    if name.lower() not in CSS_COLORS:
        sys.exit(f"unknown colour name {name!r}; add it to CSS_COLORS in {Path(__file__).name}")
    return CSS_COLORS[name.lower()]


def viewport(value: float) -> float:
    """Map a unit keypoint coordinate onto the svg viewport."""
    return VIEWPORT_MIN + value * (VIEWPORT_MAX - VIEWPORT_MIN)


def connection_pairs(attributes: dict) -> list:
    """Edges of a skeleton, from the list form or from the adjacency map form."""
    edges = attributes.get("keypoint_connections")
    if edges:
        return [(edge["from"], edge["to"], edge.get("color")) for edge in edges]

    pairs = []
    seen = set()
    for node, neighbours in (attributes.get("connections") or {}).items():
        for neighbour in neighbours:
            key = frozenset((node, neighbour))
            if node != neighbour and key not in seen:
                seen.add(key)
                pairs.append((node, neighbour, None))
    return pairs


def build_svg(keypoint_info: dict, connections: list, node_ids: dict, stroke: str) -> str:
    if len(keypoint_info) == 1:
        positions = {name: (50.0, 50.0) for name in keypoint_info}
    elif all("x" in point and "y" in point for point in keypoint_info.values()):
        positions = {
            name: (viewport(point["x"]), viewport(point["y"]))
            for name, point in keypoint_info.items()
        }
    else:
        # no layout in meta.json: spread the nodes evenly around the viewport
        step = 2 * math.pi / len(keypoint_info)
        positions = {
            name: (50 + 40 * math.cos(index * step), 50 + 40 * math.sin(index * step))
            for index, name in enumerate(keypoint_info)
        }

    elements = []
    for source, target, edge_color in connections:
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        elements.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color(edge_color) if edge_color else stroke}" '
            f'data-type="edge" data-node-from="{node_ids[source]}" stroke-width="0.5" '
            f'data-node-to="{node_ids[target]}"></line>'
        )

    for name, point in keypoint_info.items():
        x, y = positions[name]
        node_id = node_ids[name]
        elements.append(
            f'<circle r="1.5" stroke="black" fill="{color(point["color"]) if point.get("color") else stroke}" cx="{x}" cy="{y}" '
            f'stroke-width="0.1" data-type="element node" data-element-id="{node_id}" '
            f'data-node-id="{node_id}" data-label-name="{name}"></circle>'
        )

    return "".join(elements)


def build_labels(meta: dict) -> list:
    labels = []
    for entry in meta["labels"]:
        if entry["type"] == "BBOX":
            labels.append(
                {
                    "name": entry["name"],
                    "type": "rectangle",
                    "color": color(entry["color"]),
                    "attributes": [],
                }
            )
        elif entry["type"] == "KGROUP":
            attributes = entry.get("attributes") or {}
            keypoint_info = attributes.get("keypoint_info") or {}
            if not keypoint_info:
                sys.exit(f"KGROUP label {entry['name']!r} has no keypoint_info")
            node_ids = {name: index for index, name in enumerate(keypoint_info, start=1)}
            labels.append(
                {
                    "name": entry["name"] + SKELETON_SUFFIX,
                    "type": "skeleton",
                    "color": color(entry["color"]),
                    "attributes": [],
                    "sublabels": [
                        {
                            "name": name,
                            "type": "points",
                            "color": color(point["color"]) if point.get("color") else color(entry["color"]),
                            "attributes": [],
                        }
                        for name, point in keypoint_info.items()
                    ],
                    "svg": build_svg(
                        keypoint_info,
                        connection_pairs(attributes),
                        node_ids,
                        color(entry["color"]),
                    ),
                }
            )
        elif entry["type"] == "MASK":
            labels.append(
                {
                    "name": entry["name"],
                    "type": "mask",
                    "color": color(entry["color"]),
                    "attributes": [],
                }
            )
        else:
            sys.exit(f"unsupported label type {entry['type']!r} in meta.json")

    names = [label["name"] for label in labels]
    clashing = {name for name in names if names.count(name) > 1}
    if clashing:
        sys.exit(f"meta.json gives one name to several shapes, which CVAT refuses: {sorted(clashing)}")
    return labels


def cvat_runs(data: bytes) -> list:
    """Run lengths over a flat 0/1 buffer, starting with the count of zeros."""
    runs = []
    position = 0
    value = 0
    while position < len(data):
        following = data.find(1 - value, position)
        if following == -1:
            following = len(data)
        runs.append(following - position)
        position = following
        value = 1 - value
    return runs


def coco_rle_to_cvat_mask(rle: list, h: int, w: int) -> list | None:
    """COCO column-major runs over h x w into CVAT [runs..., left, top, right, bottom]."""
    if sum(rle) != h * w:
        sys.exit(f"an rle of {sum(rle)} pixels does not cover the {w}x{h} mask it declares")

    spans = []
    position = 0
    value = 0
    for length in rle:
        if value and length:
            start, end = position, position + length
            while start < end:
                x = start // h
                stop = min(end, (x + 1) * h)
                spans.append((x, start - x * h, stop - x * h))
                start = stop
        position += length
        value = 1 - value

    if not spans:
        return None

    left = min(span[0] for span in spans)
    right = max(span[0] for span in spans)
    top = min(span[1] for span in spans)
    bottom = max(span[2] for span in spans) - 1

    width = right - left + 1
    crop = bytearray(width * (bottom - top + 1))
    for x, y0, y1 in spans:
        start = (y0 - top) * width + (x - left)
        crop[start : start + (y1 - y0) * width : width] = b"\x01" * (y1 - y0)

    return cvat_runs(bytes(crop)) + [left, top, right, bottom]


def cvat_mask_to_coco_rle(points: list, height: int, width: int) -> list:
    """CVAT [runs..., left, top, right, bottom] into COCO column-major runs over the image."""
    left, top, right, bottom = (int(value) for value in points[-4:])
    crop_width = right - left + 1
    crop = bytearray(crop_width * (bottom - top + 1))

    position = 0
    value = 0
    for length in points[:-4]:
        length = int(length)
        if value and length:
            crop[position : position + length] = b"\x01" * length
        position += length
        value = 1 - value

    full = bytearray(width * height)
    for row in range(bottom - top + 1):
        start = (top + row) * width + left
        full[start : start + crop_width] = crop[row * crop_width : (row + 1) * crop_width]

    return cvat_runs(b"".join(full[x::width] for x in range(width)))


def polygon_to_coco_rle(points: list, height: int, width: int) -> list:
    """A CVAT polygon [x1, y1, x2, y2, ...], filled, into COCO column-major runs over the image.

    The mask holds every pixel the polygon covers, its outline included. CVAT has already fitted
    the polygon into the frame, so nothing is drawn past the edge.
    """
    image = Image.new("L", (width, height), 0)
    ImageDraw.Draw(image).polygon(list(zip(points[0::2], points[1::2])), fill=1, outline=1)
    data = image.tobytes()
    return cvat_runs(b"".join(data[x::width] for x in range(width)))


def mask_names(meta: dict) -> set:
    return {entry["name"] for entry in meta["labels"] if entry["type"] == "MASK"}


def keypoint_names(meta: dict) -> dict:
    return {
        entry["name"]: list((entry.get("attributes") or {}).get("keypoint_info") or {})
        for entry in meta["labels"]
        if entry["type"] == "KGROUP"
    }


def build_annotations(figures: dict, meta: dict, image_names: list) -> tuple[dict, dict]:
    sublabels = keypoint_names(meta)
    masks = mask_names(meta)
    counts = {"boxes": 0, "skeletons": 0, "masks": 0, "trash": 0, "incomplete": 0, "dropped": 0}
    annotations = {}

    for name in image_names:
        figure = figures[name]
        shapes = []

        if figure.get("trash"):
            shapes.append({"type": "tag", "label": TRASH_LABEL})
            counts["trash"] += 1

        # A detection-only task writes no "kgroups" key at all.
        for box in figure.get("bboxes", []):
            shapes.append(
                {
                    "type": "rectangle",
                    "label": box["label"],
                    "points": [box["x1"], box["y1"], box["x2"], box["y2"]],
                }
            )
            counts["boxes"] += 1

        for mask in figure.get("masks", []):
            if mask["label"] not in masks:
                sys.exit(f"{name}: mask label {mask['label']!r} is not in meta.json")

            points = coco_rle_to_cvat_mask(mask["rle"], mask["h"], mask["w"])
            if points is None:
                counts["dropped"] += 1
                continue
            shapes.append(
                {"type": "mask", "label": mask["label"], "points": points}
            )
            counts["masks"] += 1

        for group in figure.get("kgroups", []):
            wanted = sublabels.get(group["label"])
            if wanted is None:
                sys.exit(f"{name}: kgroup label {group['label']!r} is not in meta.json")

            present = {point["label"]: (point["x"], point["y"]) for point in group["points"]}
            if not present:
                counts["dropped"] += 1
                continue
            if len(present) != len(wanted):
                counts["incomplete"] += 1

            # A skeleton needs an element per sublabel, so a missing keypoint is placed at the
            # centroid of the ones that are there and marked outside for the annotator to move.
            centroid = [
                sum(value[0] for value in present.values()) / len(present),
                sum(value[1] for value in present.values()) / len(present),
            ]
            shapes.append(
                {
                    "type": "skeleton",
                    "label": group["label"] + SKELETON_SUFFIX,
                    "elements": [
                        {
                            "label": sublabel,
                            "points": list(present.get(sublabel, centroid)),
                            "outside": sublabel not in present,
                        }
                        for sublabel in wanted
                    ],
                }
            )
            counts["skeletons"] += 1

        annotations[name] = {
            "width": figure["width"],
            "height": figure["height"],
            "shapes": shapes,
        }

    return annotations, counts


def rectangle_corners(points: list, rotation: float) -> list:
    x1, y1, x2, y2 = points
    if not rotation:
        return [x1, y1, x2, y2]

    # A rotated rectangle has no place in the figures.json schema; keep its outer box.
    angle = math.radians(rotation)
    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    rotated = [
        (
            center_x + (x - center_x) * math.cos(angle) - (y - center_y) * math.sin(angle),
            center_y + (x - center_x) * math.sin(angle) + (y - center_y) * math.cos(angle),
        )
        for x, y in corners
    ]
    xs = [point[0] for point in rotated]
    ys = [point[1] for point in rotated]
    return [min(xs), min(ys), max(xs), max(ys)]


def inside_frame(x: float, y: float, width: int, height: int) -> bool:
    return 0 <= x <= width and 0 <= y <= height


def pull_into_frame(x: float, y: float, width: int, height: int) -> tuple:
    """Drop a keypoint that lies past the frame perpendicularly onto the nearest edge.

    CVAT fits boxes and polygons into the frame but keeps a skeleton point wherever it was
    dropped, so a point meant for the edge ends a little past it. Clamping each coordinate on its
    own is the perpendicular onto that edge, or the corner for a point past two edges at once —
    the same fit CVAT gives a polygon.
    """
    return min(max(x, 0), width), min(max(y, 0), height)


def read_task(source: Path) -> tuple[list, dict, list, dict]:
    """Read one source task directory into CVAT labels, per-image shapes and image paths."""
    images_dir = source / "img"
    if not images_dir.is_dir():
        sys.exit(f"{images_dir} does not exist")

    meta = json.loads((source / "meta.json").read_text())
    figures = json.loads((source / "figures.json").read_text())

    images = sorted(path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    missing = [path.name for path in images if path.name not in figures]
    if missing:
        sys.exit(f"{len(missing)} images have no entry in figures.json, first is {missing[0]}")

    labels = build_labels(meta)
    if any("trash" in figure for figure in figures.values()):
        labels.append({"name": TRASH_LABEL, "type": "tag", "color": color("gray"), "attributes": []})

    annotations, counts = build_annotations(figures, meta, [path.name for path in images])
    return labels, annotations, images, counts


def figures_from_shapes(
    frames: dict, shapes: list, tags: list, names: dict, sublabels: dict, counts
) -> dict:
    """Turn the shapes and tags of one job into the figures.json entry of every frame."""
    figures = {
        frame["name"]: {
            "trash": False,
            "bboxes": [],
            "kgroups": [],
            "height": frame["height"],
            "width": frame["width"],
        }
        for frame in frames.values()
    }

    for tag in tags:
        frame = frames.get(tag.frame)
        if frame is not None and names.get(tag.label_id) == TRASH_LABEL:
            figures[frame["name"]]["trash"] = True
            counts["trash"] += 1

    for shape in shapes:
        frame = frames.get(shape.frame)
        if frame is None:
            counts["shapes outside the job frames"] += 1
            continue
        figure = figures[frame["name"]]

        if shape.type.value == "rectangle":
            x1, y1, x2, y2 = rectangle_corners(list(shape.points), shape.rotation or 0.0)
            figure["bboxes"].append(
                {
                    "x1": round(x1),
                    "y1": round(y1),
                    "x2": round(x2),
                    "y2": round(y2),
                    "label": names.get(shape.label_id, str(shape.label_id)),
                    "score": round(float(getattr(shape, "score", 1.0) or 1.0), 4),
                }
            )
            counts["bboxes"] += 1
        elif shape.type.value == "skeleton":
            label = names.get(shape.label_id, str(shape.label_id))
            visible = [element for element in shape.elements if not element.outside]
            counts["keypoints left outside"] += len(shape.elements) - len(visible)
            width, height = frame["width"], frame["height"]
            points = []
            for element in visible:
                x, y = element.points[0], element.points[1]
                if not inside_frame(x, y, width, height):
                    x, y = pull_into_frame(x, y, width, height)
                    counts["keypoints pulled to the frame edge"] += 1
                sublabel, order = sublabels.get(element.label_id, (str(element.label_id), 0))
                points.append((order, {"x": round(x), "y": round(y), "label": sublabel}))
            # keep the keypoint order of the skeleton definition, as figures.json has it
            points = [point for _, point in sorted(points, key=lambda item: item[0])]
            figure["kgroups"].append(
                {
                    "points": points,
                    "label": label[: -len(SKELETON_SUFFIX)]
                    if label.endswith(SKELETON_SUFFIX)
                    else label,
                }
            )
            counts["kgroups"] += 1
        elif shape.type.value == "mask":
            label = names.get(shape.label_id, str(shape.label_id))
            figure.setdefault("masks", []).append(
                {
                    "rle": cvat_mask_to_coco_rle(
                        list(shape.points), frame["height"], frame["width"]
                    ),
                    "h": frame["height"],
                    "w": frame["width"],
                    "label": label,
                }
            )
            counts["masks"] += 1
        elif shape.type.value == "polygon":
            # A polygon is only a quicker way to draw a mask, so it leaves as one: same list,
            # same encoding, and the reader of figures.json cannot tell the two apart.
            label = names.get(shape.label_id, str(shape.label_id))
            figure.setdefault("masks", []).append(
                {
                    "rle": polygon_to_coco_rle(
                        list(shape.points), frame["height"], frame["width"]
                    ),
                    "h": frame["height"],
                    "w": frame["width"],
                    "label": label,
                }
            )
            counts["masks"] += 1
            counts["masks drawn as polygons"] += 1
        else:
            counts[f"{shape.type.value} shapes skipped"] += 1

    return figures
