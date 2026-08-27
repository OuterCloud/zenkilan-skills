#!/usr/bin/env python3
"""Render PPTX to PDF and per-slide PNGs for visual QA.

Backends:
- macOS Keynote (preferred when installed)
- LibreOffice/soffice

Usage:
    python3 render_slides.py deck.pptx --output-dir /tmp/deck-render
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path


def run(cmd):
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc


def export_with_keynote(source: Path, pdf: Path):
    app = Path('/Applications/Keynote.app')
    if not app.exists() or shutil.which('osascript') is None:
        return False
    # Cold-start Keynote explicitly; AppleScript `activate` alone can race and return -600.
    subprocess.run(['open', '-a', 'Keynote'], check=True, capture_output=True)
    time.sleep(3)
    # Keynote caches imported Office documents by path. Use a unique copy so repeated QA
    # renders always reflect the latest bytes written to the original PPTX.
    import_source = pdf.parent / f'.render-{time.time_ns()}-{source.name}'
    shutil.copy2(source, import_source)
    source_s = str(import_source).replace('\\', '\\\\').replace('"', '\\"')
    pdf_s = str(pdf).replace('\\', '\\\\').replace('"', '\\"')
    script = f'''
tell application "Keynote"
    activate
    set docRef to missing value
    try
        set sourceFile to POSIX file "{source_s}"
        set outputFile to POSIX file "{pdf_s}"
        set docRef to open sourceFile
        delay 2
        export docRef to outputFile as PDF
        close docRef saving no
    on error errorMessage number errorNumber
        if docRef is not missing value then close docRef saving no
        error errorMessage number errorNumber
    end try
end tell
'''
    try:
        proc = subprocess.run(['osascript', '-e', script], text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Keynote export failed: {proc.stderr.strip()}")
        for _ in range(30):
            if pdf.exists() and pdf.stat().st_size > 0:
                return True
            time.sleep(0.5)
        raise RuntimeError('Keynote reported success but PDF was not created')
    finally:
        import_source.unlink(missing_ok=True)


def export_with_libreoffice(source: Path, output_dir: Path, pdf: Path):
    binary = shutil.which('soffice') or shutil.which('libreoffice')
    if not binary:
        return False
    run([binary, '--headless', '--convert-to', 'pdf', '--outdir', str(output_dir), str(source)])
    generated = output_dir / f'{source.stem}.pdf'
    if not generated.exists():
        raise RuntimeError('LibreOffice did not create the expected PDF')
    if generated != pdf:
        generated.replace(pdf)
    return True


def pdf_to_pngs(pdf: Path, output_dir: Path, dpi: int):
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError('PyMuPDF is required for PNG rendering: pip install -r requirements.txt') from exc
    doc = pymupdf.open(pdf)
    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    outputs = []
    digits = max(2, len(str(len(doc))))
    for index, page in enumerate(doc, 1):
        target = output_dir / f'slide-{index:0{digits}d}.png'
        page.get_pixmap(matrix=matrix, alpha=False).save(target)
        outputs.append(target)
    return outputs


def main():
    parser = argparse.ArgumentParser(description='Render PPTX slides for visual QA')
    parser.add_argument('pptx')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--dpi', type=int, default=150)
    args = parser.parse_args()

    source = Path(args.pptx).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f'File not found: {source}')
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = output_dir / f'{source.stem}.pdf'
    if pdf.exists():
        pdf.unlink()
    for stale in output_dir.glob('slide-*.png'):
        stale.unlink()

    backend = None
    if sys.platform == 'darwin' and export_with_keynote(source, pdf):
        backend = 'keynote'
    elif export_with_libreoffice(source, output_dir, pdf):
        backend = 'libreoffice'
    else:
        raise SystemExit('No renderer found. Install Keynote (macOS) or LibreOffice.')

    images = pdf_to_pngs(pdf, output_dir, args.dpi)
    print(f'backend={backend}')
    print(f'pdf={pdf}')
    print(f'slides={len(images)}')
    for image in images:
        print(image)


if __name__ == '__main__':
    main()
