"""Converts a PDF or office document to Markdown, HTML or JSON with Marker."""

from __future__ import annotations

import argparse
import os

import tinyai_common as common

INLINE_MARKDOWN_CHARS = 200_000


def page_range(spec: str) -> list[int] | None:
    if not spec.strip():
        return None
    from marker.util import parse_range_str

    pages = parse_range_str(spec)
    if pages[0] < 1:
        raise ValueError(f"page numbers start at 1, got {pages[0]}")
    # Marker counts pages from zero, the catalog and its help text from one.
    return [page - 1 for page in pages]


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    source = common.require_file(args.input, "input")
    outdir = common.ensure_outdir(args.outdir)
    device = common.resolve_device(args.device)

    # Marker and surya bind their torch device as an import-time default argument.
    os.environ["TORCH_DEVICE"] = device
    os.environ["DISABLE_TQDM"] = "true"

    rep.start(
        device=device,
        input=str(source),
        format=args.format,
        pages=args.pages or None,
        force_ocr=args.force_ocr,
    )

    rep.progress(0.05, "loading models")
    from marker.config.parser import ConfigParser
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import convert_if_not_rgb, text_from_rendered
    from marker.settings import settings

    config: dict[str, object] = {
        "output_format": args.format,
        "force_ocr": args.force_ocr,
        "disable_tqdm": True,
    }
    pages = page_range(args.pages)
    if pages is not None:
        config["page_range"] = pages

    converter = PdfConverter(
        artifact_dict=create_model_dict(),
        config=config,
        renderer=ConfigParser({"output_format": args.format}).get_renderer(),
    )

    rep.progress(0.2, "converting document")
    rendered = converter(str(source))
    text, ext, images = text_from_rendered(rendered)
    rep.log(f"converted {converter.page_count} page(s)")

    rep.progress(0.85, "writing artifacts")
    document = outdir / f"document.{ext}"
    document.write_text(text, encoding=settings.OUTPUT_ENCODING, errors="replace")

    written = [document]
    for name, image in images.items():
        target = outdir / name
        convert_if_not_rgb(image).save(target, settings.OUTPUT_IMAGE_FORMAT)
        written.append(target)

    bundle = common.zip_bundle(written, outdir / "document.zip")

    rep.artifact(document, label="Document")
    for target in written[1:]:
        rep.artifact(target, kind="image")
    rep.artifact(bundle, kind="archive", label="Bundle")

    result: dict[str, object] = {"pages": converter.page_count, "format": args.format}
    if args.format == "markdown":
        result["markdown"] = text[:INLINE_MARKDOWN_CHARS]
        result["truncated"] = len(text) > INLINE_MARKDOWN_CHARS
    rep.progress(1.0, "complete")
    rep.result(result)
    rep.done()


parser = common.base_parser("doc2md", "Convert a document to Markdown, HTML or JSON with Marker.")
parser.add_argument("--input", required=True, help="document to convert")
parser.add_argument(
    "--pages", default="", help="page range such as 1-10 or 1,4-6; empty converts the whole document"
)
parser.add_argument(
    "--format", default="markdown", choices=("markdown", "html", "json"), help="output format"
)
parser.add_argument(
    "--force-ocr", action="store_true", help="re-read every page with OCR instead of its text layer"
)


def main() -> None:
    common.run("doc2md", run, parser)
