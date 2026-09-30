# cvat_tools

Load an annotation task into a running CVAT, give its job to an annotator, and take the
annotations back in the schema the task came in. Needs nothing but the server address and the
administrator credentials.

## Created

2026-08-25

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Use

```bash
export CVAT_URL=https://<address>
export CVAT_ADMIN_LOGIN=admin
export CVAT_ADMIN_PASSWORD=<password>

.venv/bin/python scripts/cvat_ops.py import --source <task directory>
.venv/bin/python scripts/cvat_ops.py assign --project <task directory name> --annotator User1
.venv/bin/python scripts/cvat_ops.py export-figures --project <name> --output results/figures.json
```

`import` creates a project named after the directory, one task holding every image and one job,
and uploads the detections from `figures.json` as annotations. `assign` gives every job of the
project to that user at stage `annotation`. `export-figures` writes the annotations of the
project's jobs as one file in the source schema.

## The task directory

```
<task>/img/            the images
<task>/meta.json       the label definitions: a BBOX, MASK or KGROUP entry per class
<task>/figures.json    per image name: bboxes, masks and kgroups in absolute pixels
```

`meta.json` declares a class once per shape it carries: `BBOX`, `MASK` and `KGROUP`. A `BBOX`
becomes a `rectangle` and a `MASK` becomes a `mask`, both under the source name; a `KGROUP` becomes
a `skeleton` named `<name>_skeleton`, whose sublabels, colours and edges come from `keypoint_info`
and its connections. CVAT requires top-level label names to be unique within a project, so a name
given to more than one shape stops the import. A keypoint missing from a group is uploaded as an
element marked `outside`; `export-figures` drops it again and strips the skeleton suffix.

CVAT fits boxes and polygons into the frame but keeps a skeleton point wherever it was
dropped, so a point placed for the edge usually lands a little past it. `export-figures` drops such
a point perpendicularly onto the nearest edge, or onto the corner when it is past two edges. A
point that is not visible at all belongs in `outside`, not past the edge.

A frame may carry `"trash": true`, which becomes a CVAT tag named `trash` on that frame; every
frame written by `export-figures` carries the flag. Skeleton edges come either from
`keypoint_connections` as `{"from", "to", "color"}` objects or from a `connections` adjacency map
such as `{"br": ["bl", "fr"]}`, whose edges take the colour of their label.

An entry of the `masks` list is `{"label": …, "rle": [...], "h": …, "w": …}`, where `rle` is the
uncompressed COCO run list over the whole `h` by `w` frame: column-major, the first run counting
background. `export-figures` writes masks back in the same encoding. A polygon drawn in CVAT is
only a quicker way to draw a mask: `export-figures` fills it and writes it into the same list, in
the same encoding.

The server certificate is not verified: the package carries no CA file.

## The worked example

`lp_example/` is a generated task in exactly this layout: a `vehicle` `BBOX`, a `plate` `MASK` and a
`plate` `KGROUP` of four corners joined by a `connections` map, over eight images, with one frame
marked `trash` and one plate missing a corner. It imports as it stands:

```bash
.venv/bin/python scripts/cvat_ops.py import --source lp_example
```

Every field of `figures.json` survives an import followed by an `export-figures` unchanged, except
the `score` of a box: CVAT stores no such field, so an exported box always carries `1.0`.
