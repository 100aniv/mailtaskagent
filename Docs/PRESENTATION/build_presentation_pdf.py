"""Render the four exported slide PNGs into the submission PDF.

Export the slides first (PowerPoint, 2560x1440, saved as slide-1..4.png)
into tmp/pdfs/presentation-<version>/, then run this.
"""
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


# Derived from this file's location so the build does not depend on where
# the repository was cloned.
ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "tmp" / "pdfs" / "presentation-v12"
OUTPUT = ROOT / "Docs" / "PRESENTATION" / "2. 최종" / "09285_백준현_AI_Master_최종발표자료_v12.pdf"
PAGE_SIZE = (960, 540)


def main() -> None:
    images = sorted(IMAGE_DIR.glob("slide-*.png"))
    if len(images) != 4:
        raise RuntimeError(f"Expected 4 rendered slides, found {len(images)}")

    pdf = canvas.Canvas(str(OUTPUT), pagesize=PAGE_SIZE, pageCompression=1)
    for slide in images:
        pdf.drawImage(ImageReader(str(slide)), 0, 0, PAGE_SIZE[0], PAGE_SIZE[1])
        pdf.showPage()
    pdf.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()
