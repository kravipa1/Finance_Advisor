# ocr/reader.py
from __future__ import annotations
import argparse
from pathlib import Path

# We’ll wire EasyOCR in Week 1. For Week 0, keep a stub that saves input text files to interim.
INTERIM_DIR = Path("data/interim/ocr_text")


def save_text_stub(input_path: str) -> Path:
    src = Path(input_path)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    txt_out = INTERIM_DIR / (src.stem + ".txt")

    # If the input is already a .txt (fixtures), just copy content.
    if src.suffix.lower() == ".txt":
        txt_out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        # Placeholder: real OCR will go here next week.
        txt_out.write_text(
            "<<OCR not implemented yet for this file type>>", encoding="utf-8"
        )
    return txt_out


def main():
    parser = argparse.ArgumentParser(description="OCR stub to save text outputs.")
    parser.add_argument(
        "--file", required=True, help="Path to input file (image/pdf/txt)"
    )
    args = parser.parse_args()
    out = save_text_stub(args.file)
    print(f"Saved OCR text to {out}")


if __name__ == "__main__":
    main()
