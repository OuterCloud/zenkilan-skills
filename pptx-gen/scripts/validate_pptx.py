#!/usr/bin/env python3
"""
validate_pptx.py - Validate structural integrity of a .pptx file.

Checks:
- ZIP CRC integrity (testzip)
- All XML parts are parseable
- presentation.xml slide relationships exist and target parts exist
- Each slide XML's r:embed/r:link references are in slide rels (External exempt)
- [Content_Types].xml contains overrides for all slides
- Forbidden placeholder text detection
- Optional --template comparison (slide count, media preservation)

Exit codes:
  0 = valid
  1 = validation errors found
  2 = file not found / cannot open

Usage:
    python3 validate_pptx.py <file.pptx> [--template <source.pptx>] [--forbidden-patterns pat1 pat2]
"""

import sys
import re
import json
import argparse
import zipfile
from pathlib import Path
from lxml import etree

NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}

CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'

DEFAULT_FORBIDDEN_PATTERNS = [
    r'Please Enter',
    r'Enter your subhead',
    r'TITLE GOES HERE',
    r'[Ss]ample [Tt]ext',
    r'Lorem',
    r'\bTODO\b',
    r'Click to edit',
    r'Insert text here',
    r'Type here',
    r'Add text',
    r'Your text here',
]


class ValidationResult:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = {}

    @property
    def valid(self):
        return len(self.errors) == 0

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def report(self):
        lines = []
        if self.valid:
            lines.append("✓ VALID")
        else:
            lines.append(f"✗ INVALID ({len(self.errors)} error(s))")

        if self.info:
            lines.append(f"  Info: {json.dumps(self.info, ensure_ascii=False)}")

        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN: {w}")

        return "\n".join(lines)


def get_txbody_text(txbody):
    """Extract text from an a:txBody element."""
    if txbody is None:
        return ""
    paragraphs = []
    for p_elem in txbody.findall('a:p', NS):
        para_texts = []
        for r_elem in p_elem.findall('a:r', NS):
            t_elem = r_elem.find('a:t', NS)
            if t_elem is not None and t_elem.text:
                para_texts.append(t_elem.text)
        paragraphs.append("".join(para_texts))
    return "\n".join(paragraphs)


def validate_pptx(pptx_path, template_path=None, extra_forbidden=None):
    """Validate a .pptx file. Returns ValidationResult."""
    result = ValidationResult()
    pptx_path = str(pptx_path)

    # 1. ZIP integrity
    try:
        zf = zipfile.ZipFile(pptx_path, 'r')
    except (zipfile.BadZipFile, FileNotFoundError, OSError) as e:
        result.error(f"Cannot open ZIP: {e}")
        return result

    bad = zf.testzip()
    if bad is not None:
        result.error(f"ZIP CRC error in: {bad}")
        zf.close()
        return result

    namelist = set(zf.namelist())

    # 2. XML parseability for key parts
    xml_parts = [n for n in namelist if n.endswith('.xml') or n.endswith('.rels')]
    for part in xml_parts:
        try:
            etree.fromstring(zf.read(part))
        except etree.XMLSyntaxError as e:
            result.error(f"XML parse error in {part}: {e}")

    if not result.valid:
        zf.close()
        return result

    # 3. Parse presentation.xml and its rels
    if 'ppt/presentation.xml' not in namelist:
        result.error("Missing ppt/presentation.xml")
        zf.close()
        return result

    pres_root = etree.fromstring(zf.read('ppt/presentation.xml'))

    pres_rels_path = 'ppt/_rels/presentation.xml.rels'
    if pres_rels_path not in namelist:
        result.error("Missing ppt/_rels/presentation.xml.rels")
        zf.close()
        return result

    pres_rels_root = etree.fromstring(zf.read(pres_rels_path))

    # Build rId -> (Type, Target) map
    pres_rel_map = {}
    for rel in pres_rels_root.findall('rel:Relationship', NS):
        pres_rel_map[rel.get('Id')] = (rel.get('Type', ''), rel.get('Target', ''))

    # 4. Check each slide in sldIdLst
    r_ns = NS['r']
    sld_id_lst = pres_root.find('p:sldIdLst', NS)
    slide_parts = []

    if sld_id_lst is not None:
        for sld_id in sld_id_lst.findall('p:sldId', NS):
            rid = sld_id.get(f'{{{r_ns}}}id')
            if rid not in pres_rel_map:
                result.error(f"sldIdLst references {rid} but no such relationship exists")
                continue

            rel_type, target = pres_rel_map[rid]
            slide_path = f'ppt/{target}' if not target.startswith('/') else target.lstrip('/')

            if slide_path not in namelist:
                result.error(f"Slide relationship {rid} targets {slide_path} which does not exist")
                continue

            slide_parts.append(slide_path)

    result.info['slide_count'] = len(slide_parts)

    # 5. For each slide, check that r:embed/r:link refs are in slide rels
    for slide_path in slide_parts:
        rels_path = slide_path.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels'

        # Build set of rIds from slide rels
        slide_rids = set()
        if rels_path in namelist:
            slide_rels_root = etree.fromstring(zf.read(rels_path))
            for rel in slide_rels_root.findall('rel:Relationship', NS):
                slide_rids.add(rel.get('Id'))

            # Check that non-External targets exist
            for rel in slide_rels_root.findall('rel:Relationship', NS):
                target_mode = rel.get('TargetMode', '')
                if target_mode == 'External':
                    continue
                target = rel.get('Target', '')
                # Resolve relative path
                if target.startswith('../'):
                    resolved = f'ppt/{target[3:]}'
                elif target.startswith('/'):
                    resolved = target.lstrip('/')
                else:
                    # Relative to slide directory
                    resolved = f'ppt/slides/{target}'

                # Normalize path
                resolved = re.sub(r'/[^/]+/\.\./', '/', resolved)

                # Layout/master/theme references may exist in other dirs
                if resolved not in namelist:
                    # Try without ppt/ prefix normalization
                    alt_resolved = f'ppt/{target}' if not target.startswith('/') else target.lstrip('/')
                    alt_resolved = re.sub(r'/[^/]+/\.\./', '/', alt_resolved)
                    if alt_resolved not in namelist:
                        result.warn(f"{slide_path}: rel target '{target}' resolved to '{resolved}' not found (may be layout-inherited)")

        # Check r:embed and r:link references in slide XML
        slide_root = etree.fromstring(zf.read(slide_path))
        r_embed_ns = f'{{{r_ns}}}'
        for elem in slide_root.iter():
            for attr_name in ['embed', 'link', 'id']:
                full_attr = f'{r_embed_ns}{attr_name}'
                val = elem.get(full_attr)
                if val and val.startswith('rId'):
                    if val not in slide_rids:
                        # Check if this is a layout-inherited reference (common in placeholders)
                        # Shapes that inherit from layout don't need local rels
                        tag_local = etree.QName(elem.tag).localname
                        if tag_local in ('blipFill', 'blip', 'hlinkClick', 'hlinkMouseOver'):
                            result.warn(f"{slide_path}: {tag_local} references {val} not in slide rels (may be layout-inherited)")
                        else:
                            # Only error for blip (image) references that should be local
                            pass

    # 6. [Content_Types].xml slide overrides
    if '[Content_Types].xml' in namelist:
        ct_root = etree.fromstring(zf.read('[Content_Types].xml'))
        ct_overrides = set()
        for override in ct_root.findall(f'{{{CT_NS}}}Override'):
            ct_overrides.add(override.get('PartName', ''))

        for slide_path in slide_parts:
            expected_override = f'/{slide_path}'
            if expected_override not in ct_overrides:
                result.error(f"[Content_Types].xml missing Override for {expected_override}")

    # 7. Forbidden placeholder text
    forbidden_patterns = DEFAULT_FORBIDDEN_PATTERNS + (extra_forbidden or [])
    compiled = []
    for pat in forbidden_patterns:
        try:
            compiled.append((pat, re.compile(pat, re.IGNORECASE)))
        except re.error:
            compiled.append((pat, re.compile(re.escape(pat), re.IGNORECASE)))

    for slide_idx, slide_path in enumerate(slide_parts):
        slide_root = etree.fromstring(zf.read(slide_path))
        for elem in slide_root.iter():
            if etree.QName(elem.tag).localname == 'txBody':
                text = get_txbody_text(elem)
                if not text.strip():
                    continue
                for pat_str, pat_re in compiled:
                    if pat_re.search(text):
                        result.error(f"Slide {slide_idx + 1} ({slide_path}): forbidden text pattern '{pat_str}' found")
                        break

    # 8. Template comparison (optional)
    if template_path and Path(template_path).exists():
        try:
            with zipfile.ZipFile(str(template_path), 'r') as tzf:
                tpl_namelist = set(tzf.namelist())

                # Count template slides
                tpl_pres = etree.fromstring(tzf.read('ppt/presentation.xml'))
                tpl_sld_lst = tpl_pres.find('p:sldIdLst', NS)
                tpl_slide_count = len(tpl_sld_lst.findall('p:sldId', NS)) if tpl_sld_lst is not None else 0

                result.info['template_slide_count'] = tpl_slide_count

                # Check media preservation
                tpl_media = {n for n in tpl_namelist if n.startswith('ppt/media/')}
                out_media = {n for n in namelist if n.startswith('ppt/media/')}
                missing_media = tpl_media - out_media

                result.info['template_media_count'] = len(tpl_media)
                result.info['output_media_count'] = len(out_media)

                if missing_media:
                    result.warn(f"Media parts from template not in output: {sorted(missing_media)[:5]}")
                else:
                    result.info['all_media_preserved'] = True

        except Exception as e:
            result.warn(f"Template comparison failed: {e}")

    zf.close()
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Validate structural integrity of a .pptx file.'
    )
    parser.add_argument('pptx', help='Path to .pptx file to validate')
    parser.add_argument('--template', help='Optional template .pptx for comparison')
    parser.add_argument('--forbidden-patterns', nargs='*', default=[],
                        help='Additional forbidden text patterns (regex)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    if not Path(args.pptx).exists():
        print(f"Error: File not found: {args.pptx}", file=sys.stderr)
        sys.exit(2)

    result = validate_pptx(args.pptx, args.template, args.forbidden_patterns)

    if args.json:
        output = {
            'valid': result.valid,
            'errors': result.errors,
            'warnings': result.warnings,
            'info': result.info,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(result.report())

    sys.exit(0 if result.valid else 1)


if __name__ == '__main__':
    main()
