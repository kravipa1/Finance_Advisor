# tasks.py
"""
Developer task runner using Invoke.
Run `inv --list` to see tasks.

Key tasks:
  inv ocr --input <img|pdf>
  inv normalize --input data/interim/ocr_text/<name>.txt
  inv extract --input data/interim/normalized_text/<name>.txt
  inv pipeline --input <img|pdf|txt>  (or --indir <folder>)
  inv test
  inv clean
"""

from invoke import task
from pathlib import Path
import shutil
import sys


REPO = Path(__file__).parent
OCRDIR = REPO / "data" / "interim" / "ocr_text"
NORMDIR = REPO / "data" / "interim" / "normalized_text"
PARSEDIR = REPO / "data" / "interim" / "parsed"


def _python():
    """Return the python executable inside the current venv (WHY: consistent)."""
    return sys.executable or "python"


@task(
    help={
        "input": "Path to an image/PDF file",
        "outdir": "Where to write raw OCR .txt (default: data/interim/ocr_text)",
        "lang": "EasyOCR languages, space-separated (default: en)",
        "gpu": "Use GPU for OCR if CUDA available",
        "min_conf": "Min confidence to keep a span (default: 0.5)",
        "no_paragraph": "Disable paragraph grouping",
        "dpi": "PDF render DPI (default: 200)",
    }
)
def ocr(
    c,
    input,
    outdir=str(OCRDIR),
    lang="en",
    gpu=False,
    min_conf=0.5,
    no_paragraph=False,
    dpi=200,
):
    """Run OCR on one image/PDF."""
    args = [
        "-m",
        "ocr.reader",
        "--input",
        input,
        "--outdir",
        outdir,
        "--lang",
        *lang.split(),
        "--min_conf",
        str(min_conf),
        "--dpi",
        str(dpi),
    ]
    if gpu:
        args.append("--gpu")
    if no_paragraph:
        args.append("--no-paragraph")
    c.run(f'"{_python()}" ' + " ".join(args), pty=False)


@task(
    help={
        "input": "Path to OCR .txt file",
        "outdir": "Where to write normalized .txt (default: data/interim/normalized_text)",
    }
)
def normalize(c, input, outdir=str(NORMDIR)):
    """Normalize one OCR .txt file."""
    c.run(
        f'"{_python()}" -m parser.normalizer --input "{input}" --outdir "{outdir}"',
        pty=False,
    )


@task(
    help={
        "input": "Path to normalized .txt file",
        "outdir": "Where to write parsed .json (default: data/interim/parsed)",
    }
)
def extract(c, input, outdir=str(PARSEDIR)):
    """Extract fields from one normalized .txt file into JSON."""
    c.run(
        f'"{_python()}" -m parser.extractor --input "{input}" --outdir "{outdir}"',
        pty=False,
    )


@task(
    help={
        "input": "Single file (image/pdf/txt)",
        "indir": "Directory of files to batch",
        "ocrdir": "Write raw OCR here (default: data/interim/ocr_text)",
        "normdir": "Write normalized here (default: data/interim/normalized_text)",
        "parsedir": "Write parsed JSON here (default: data/interim/parsed)",
        "lang": "EasyOCR languages (default: en)",
        "gpu": "Use GPU for OCR if CUDA available",
        "min_conf": "Min confidence (default: 0.5)",
        "no_paragraph": "Disable paragraph grouping",
        "dpi": "PDF render DPI (default: 200)",
    }
)
def pipeline(
    c,
    input=None,
    indir=None,
    ocrdir=str(OCRDIR),
    normdir=str(NORMDIR),
    parsedir=str(PARSEDIR),
    lang="en",
    gpu=False,
    min_conf=0.5,
    no_paragraph=False,
    dpi=200,
):
    """Run OCR -> normalize -> extract (single file or batch directory)."""
    if not input and not indir:
        raise SystemExit("Provide --input <file> or --indir <folder>")

    args = [
        "-m",
        "pipeline.runner",
        "--ocrdir",
        f'"{ocrdir}"',
        "--normdir",
        f'"{normdir}"',
        "--parsedir",
        f'"{parsedir}"',
        "--lang",
        *lang.split(),
        "--min-conf",
        str(min_conf),
        "--dpi",
        str(dpi),
    ]

    if input:
        args += ["--input", f'"{input}"']
    if indir:
        args += ["--indir", f'"{indir}"']
    if gpu:
        args.append("--gpu")
    if no_paragraph:
        args.append("--no-paragraph")

    c.run(f'"{_python()}" ' + " ".join(args), pty=False)


@task
def test(c):
    """Run unit tests with pytest."""
    c.run(f'"{_python()}" -m pytest -q', pty=False)


@task
def clean(c):
    """Delete interim outputs (ocr_text, normalized_text, parsed)."""
    for d in [OCRDIR, NORMDIR, PARSEDIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"Removed {d}")
    # Recreate empty dirs to keep structure predictable
    OCRDIR.mkdir(parents=True, exist_ok=True)
    NORMDIR.mkdir(parents=True, exist_ok=True)
    PARSEDIR.mkdir(parents=True, exist_ok=True)
