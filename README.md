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
<task>/meta.json       the label definitions: a BBOX and a KGROUP entry per class
<task>/figures.json    per image name: bboxes and kgroups in absolute pixels
```

A class becomes two CVAT labels, because CVAT requires top-level label names to be unique within a
project: a `rectangle` under the source name and a `skeleton` named `<name>_skeleton`, whose
sublabels, colours and edges come from `keypoint_info` and `keypoint_connections`. A keypoint
missing from a group is uploaded as an element marked `outside`; `export-figures` drops it again.

The server certificate is not verified: the package carries no CA file.
# cvat_tools
