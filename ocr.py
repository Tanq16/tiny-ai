#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#     "pillow>=10.2,<11",
#     "requests>=2.32",  # surya 0.17 imports requests without declaring it
#     "surya-ocr>=0.17.1,<0.18",
#     "transformers>=4.56.1,<5",  # surya 0.17 predates the transformers 5 config rework
# ]
# ///
"""Reads text, layout and tables out of a single image with Surya."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import tinyai_common as common

TEXT_BOX_COLOR = (0, 170, 60)
TABLE_BOX_COLOR = (0, 105, 220)


def center_inside(inner: list[float], outer: tuple[float, float, float, float]) -> bool:
    x = (inner[0] + inner[2]) / 2
    y = (inner[1] + inner[3]) / 2
    return outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]


def plain_text(markup: str) -> str:
    from surya.recognition.util import MATH_BLOCK, STRIP_TAGS

    return STRIP_TAGS.sub("", MATH_BLOCK.sub(lambda match: match.group(2), markup)).strip()


def cell_grid(table, origin: tuple[float, float], lines: list[tuple[list[float], str]]) -> list[list[str]]:
    left, top = origin
    rows: dict[int, dict[int, str]] = {}
    for cell in table.cells:
        box = (
            cell.bbox[0] + left,
            cell.bbox[1] + top,
            cell.bbox[2] + left,
            cell.bbox[3] + top,
        )
        text = " ".join(value for bbox, value in lines if center_inside(bbox, box)).strip()
        column = cell.col_id if cell.col_id is not None else cell.within_row_id
        rows.setdefault(cell.row_id, {})[column] = text
    if not rows:
        return []
    width = max(max(columns) for columns in rows.values()) + 1
    return [[rows[row].get(column, "") for column in range(width)] for row in sorted(rows)]


def markdown_table(rows: list[list[str]]) -> str:
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cell.replace("|", r"\|") or " " for cell in cells) + " |"

    header, *body = rows
    return "\n".join([line(header), line(["---"] * len(header)), *(line(row) for row in body)])


def recognize_tables(image, lines, rep: common.Reporter) -> list[dict]:
    from surya.common.util import expand_bbox
    from surya.foundation import FoundationPredictor
    from surya.layout import LayoutPredictor
    from surya.settings import settings
    from surya.table_rec import TableRecPredictor

    rep.progress(0.55, "loading layout model")
    layout = LayoutPredictor(FoundationPredictor(checkpoint=settings.LAYOUT_MODEL_CHECKPOINT))

    rep.progress(0.7, "detecting tables")
    regions = [box for box in layout([image])[0].bboxes if box.label in ("Table", "TableOfContents")]
    if not regions:
        rep.log("no tables detected")
        return []

    crops, origins = [], []
    for region in regions:
        left, top, right, bottom = (int(v) for v in expand_bbox(region.bbox))
        crops.append(image.crop((left, top, right, bottom)))
        origins.append((left, top))

    rep.progress(0.8, f"reading {len(crops)} table(s)", current=0, total=len(crops))
    predictions = TableRecPredictor()(crops)

    tables = []
    for index, (region, origin, table) in enumerate(zip(regions, origins, predictions, strict=True), start=1):
        rows = cell_grid(table, origin, lines)
        if rows:
            tables.append({"bbox": region.bbox, "rows": rows, "cells": table.model_dump()["cells"]})
        rep.progress(
            0.8 + 0.05 * index / len(crops), f"table {index}/{len(crops)}", current=index, total=len(crops)
        )
    return tables


def write_tables(tables: list[dict], outdir: Path, rep: common.Reporter) -> None:
    markdown = "\n\n".join(
        f"## Table {index}\n\n{markdown_table(table['rows'])}" for index, table in enumerate(tables, start=1)
    )
    target = outdir / "tables.md"
    target.write_text(markdown + "\n", encoding="utf-8")
    rep.artifact(target, label="Tables")

    target = outdir / "tables.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for index, table in enumerate(tables):
            if index:
                writer.writerow([])
            writer.writerows(table["rows"])
    rep.artifact(target, kind="text", label="Tables (CSV)")


def write_annotation(image, result, tables: list[dict], outdir: Path, rep: common.Reporter) -> None:
    from PIL import ImageDraw

    preview = image.copy()
    draw = ImageDraw.Draw(preview)
    for line in result.text_lines:
        draw.polygon([tuple(point) for point in line.polygon], outline=TEXT_BOX_COLOR, width=2)
    for table in tables:
        draw.rectangle(tuple(table["bbox"]), outline=TABLE_BOX_COLOR, width=4)
    target = outdir / "annotated.png"
    preview.save(target)
    rep.artifact(target, kind="image", label="Annotated preview")


def main(args: argparse.Namespace, rep: common.Reporter) -> None:
    source = common.require_file(args.input, "input")
    outdir = common.ensure_outdir(args.outdir)
    device = common.resolve_device(args.device)

    # Surya binds its torch device as an import-time default argument.
    os.environ["TORCH_DEVICE"] = device
    os.environ["DISABLE_TQDM"] = "true"

    langs = [code.strip() for code in args.langs.split(",") if code.strip()]
    rep.start(
        device=device,
        input=str(source),
        langs=",".join(langs) or None,
        tables=args.tables,
        annotate=args.annotate,
    )
    rep.log("surya recognizes scripts without a language hint, so langs is recorded but not applied")

    from PIL import Image
    from surya.detection import DetectionPredictor
    from surya.foundation import FoundationPredictor
    from surya.recognition import RecognitionPredictor

    image = Image.open(source).convert("RGB")

    rep.progress(0.05, "loading recognition model")
    recognizer = RecognitionPredictor(FoundationPredictor())

    rep.progress(0.25, "reading text")
    result = recognizer([image], det_predictor=DetectionPredictor(), sort_lines=True)[0]
    lines = [(line.bbox, plain_text(line.text)) for line in result.text_lines]
    text = "\n".join(value for _, value in lines)
    rep.log(f"recognized {len(lines)} text line(s)")

    tables = recognize_tables(image, lines, rep) if args.tables else []

    rep.progress(0.9, "writing artifacts")
    target = outdir / "text.txt"
    target.write_text(text + "\n", encoding="utf-8")
    rep.artifact(target, kind="text", label="Text")

    payload = result.model_dump()
    payload["image"] = {"path": str(source), "width": image.width, "height": image.height}
    payload["langs"] = langs
    payload["tables"] = tables
    target = outdir / "ocr.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rep.artifact(target, kind="json", label="Structured result")

    if tables:
        write_tables(tables, outdir, rep)
    if args.annotate:
        write_annotation(image, result, tables, outdir, rep)

    rep.progress(1.0, "complete")
    rep.result({"text": text, "lines": len(lines), "tables": len(tables)})
    rep.done()


parser = common.base_parser("ocr", "Read text, layout and tables out of an image with Surya.")
parser.add_argument("--input", required=True, help="image to read")
parser.add_argument("--langs", default="en", help="comma-separated ISO language codes")
parser.add_argument(
    "--tables",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="recognize table structure",
)
parser.add_argument(
    "--annotate",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="write a preview with the detected boxes drawn on it",
)

if __name__ == "__main__":
    common.run("ocr", main, parser)
