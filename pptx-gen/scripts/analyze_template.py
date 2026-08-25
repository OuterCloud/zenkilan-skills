#!/usr/bin/env python3
"""
analyze_template.py - Analyze a .pptx template via OOXML and output full shape inventory as JSON.

Outputs every slide's complete shape tree with stable shape_id (p:cNvPr @id), name,
type, full text (not truncated), position, placeholder info, media relation count,
and background info. Designed for LLM-driven slide selection and fill planning.

Usage:
    python3 analyze_template.py <template.pptx> [--output analysis.json]
"""

import sys
import json
import argparse
import zipfile
from pathlib import Path
from lxml import etree

# OOXML namespaces
NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
}

EMU_PER_INCH = 914400


def emu_to_inches(emu_str):
    """Convert EMU string to inches float."""
    if emu_str is None:
        return None
    try:
        return round(int(emu_str) / EMU_PER_INCH, 2)
    except (ValueError, TypeError):
        return None


def _find_txbody(shape_elem):
    """Find a text body regardless of whether the template uses p:txBody or a:txBody."""
    for elem in shape_elem.iter():
        if etree.QName(elem.tag).localname == 'txBody':
            return elem
    return None


def get_text_from_txbody(txbody):
    """Extract complete text while preserving paragraphs and soft line breaks."""
    if txbody is None:
        return ""
    paragraphs = []
    for p_elem in txbody:
        if etree.QName(p_elem.tag).localname != 'p':
            continue
        chunks = []
        for elem in p_elem.iter():
            local = etree.QName(elem.tag).localname
            if local == 't' and elem.text:
                chunks.append(elem.text)
            elif local == 'br':
                chunks.append('\n')
        paragraphs.append("".join(chunks))
    return "\n".join(paragraphs)


def classify_shape(sp_elem):
    """Determine the shape type from the element tag."""
    tag = etree.QName(sp_elem.tag).localname
    type_map = {
        'sp': 'shape',
        'pic': 'picture',
        'graphicFrame': 'graphicFrame',
        'grpSp': 'group',
        'cxnSp': 'connector',
    }
    return type_map.get(tag, tag)


def extract_shape_info(sp_elem, ns=NS):
    """Extract shape info including shape_id, name, type, text, position, placeholder."""
    shape_type = classify_shape(sp_elem)

    # Find cNvPr - the stable identifier
    # For groups: p:grpSpPr doesn't have cNvPr at child level, it's under nvGrpSpPr
    cnvpr = None
    # Standard shapes: nvSpPr/cNvPr or nvPicPr/cNvPr or nvGrpSpPr/cNvPr
    for nv_tag in ['nvSpPr', 'nvPicPr', 'nvGrpSpPr', 'nvGraphicFramePr', 'nvCxnSpPr']:
        nv_elem = sp_elem.find(f'p:{nv_tag}', ns)
        if nv_elem is not None:
            cnvpr = nv_elem.find('p:cNvPr', ns)
            break
    if cnvpr is None:
        # Try without namespace (some elements use different ns patterns)
        for child in sp_elem:
            local = etree.QName(child.tag).localname
            if local.startswith('nv') and local.endswith('Pr'):
                for sub in child:
                    if etree.QName(sub.tag).localname == 'cNvPr':
                        cnvpr = sub
                        break
                if cnvpr is not None:
                    break

    if cnvpr is None:
        return None

    shape_id = int(cnvpr.get('id', '0'))
    shape_name = cnvpr.get('name', '')

    # Get text from txBody. Real-world templates may use p:txBody or a:txBody.
    txbody = _find_txbody(sp_elem)
    text = get_text_from_txbody(txbody)
    has_text_body = txbody is not None

    # Position from spPr/xfrm or grpSpPr/xfrm
    position = {}
    xfrm = sp_elem.find('.//p:spPr/a:xfrm', ns)
    if xfrm is None:
        xfrm = sp_elem.find('.//p:grpSpPr/a:xfrm', ns)
    if xfrm is not None:
        off = xfrm.find('a:off', ns)
        ext = xfrm.find('a:ext', ns)
        if off is not None:
            position['left_inches'] = emu_to_inches(off.get('x'))
            position['top_inches'] = emu_to_inches(off.get('y'))
        if ext is not None:
            position['width_inches'] = emu_to_inches(ext.get('cx'))
            position['height_inches'] = emu_to_inches(ext.get('cy'))

    # Placeholder info
    is_placeholder = False
    placeholder_idx = None
    placeholder_type = None
    # Check nvSpPr/nvPr/p:ph
    for nv_tag in ['nvSpPr', 'nvPicPr', 'nvGrpSpPr', 'nvGraphicFramePr']:
        nv_elem = sp_elem.find(f'p:{nv_tag}', ns)
        if nv_elem is not None:
            nvpr = nv_elem.find('p:nvPr', ns)
            if nvpr is not None:
                ph = nvpr.find('p:ph', ns)
                if ph is not None:
                    is_placeholder = True
                    idx_val = ph.get('idx')
                    placeholder_idx = int(idx_val) if idx_val else 0
                    placeholder_type = ph.get('type', 'body')
                    break

    info = {
        'shape_id': shape_id,
        'name': shape_name,
        'type': shape_type,
        'text': text,
        'has_text_body': has_text_body,
        'position': position,
        'is_placeholder': is_placeholder,
    }
    if is_placeholder:
        info['placeholder_idx'] = placeholder_idx
        info['placeholder_type'] = placeholder_type

    return info


def extract_shapes_recursive(sp_tree, ns=NS):
    """Extract all shapes from a spTree, recursing into groups."""
    shapes = []
    shape_tags = {'sp', 'pic', 'graphicFrame', 'grpSp', 'cxnSp'}

    for child in sp_tree:
        local = etree.QName(child.tag).localname
        if local in shape_tags:
            info = extract_shape_info(child, ns)
            if info:
                # If it's a group, recurse into children
                if local == 'grpSp':
                    info['children'] = extract_shapes_recursive(child, ns)
                shapes.append(info)
    return shapes


def count_media_rels(rels_xml_bytes):
    """Count media/image relationships in a slide rels."""
    if not rels_xml_bytes:
        return 0
    try:
        root = etree.fromstring(rels_xml_bytes)
    except etree.XMLSyntaxError:
        return 0
    count = 0
    for rel in root.findall('rel:Relationship', NS):
        target = rel.get('Target', '')
        if '../media/' in target or 'media/' in target:
            count += 1
    return count


def get_background_info(slide_root, ns=NS):
    """Extract background information from a slide."""
    bg = slide_root.find('.//p:cSld/p:bg', ns)
    if bg is None:
        return None

    bg_info = {'has_background': True}

    # Check for solid fill
    solid = bg.find('.//a:solidFill', ns)
    if solid is not None:
        srgb = solid.find('a:srgbClr', ns)
        if srgb is not None:
            bg_info['type'] = 'solid'
            bg_info['color'] = srgb.get('val')
            return bg_info

    # Check for gradient
    grad = bg.find('.//a:gradFill', ns)
    if grad is not None:
        bg_info['type'] = 'gradient'
        return bg_info

    # Check for image fill (blipFill)
    blip = bg.find('.//a:blipFill', ns)
    if blip is not None:
        bg_info['type'] = 'image'
        return bg_info

    bg_info['type'] = 'other'
    return bg_info


def analyze_template(pptx_path):
    """Analyze a .pptx template and return full structure as dict."""
    pptx_path = str(pptx_path)

    with zipfile.ZipFile(pptx_path, 'r') as zf:
        namelist = zf.namelist()

        # Parse presentation.xml
        pres_xml = zf.read('ppt/presentation.xml')
        pres_root = etree.fromstring(pres_xml)

        # Get slide dimensions
        sld_sz = pres_root.find('.//p:sldSz', NS)
        width_emu = int(sld_sz.get('cx', '12192000')) if sld_sz is not None else 12192000
        height_emu = int(sld_sz.get('cy', '6858000')) if sld_sz is not None else 6858000

        # Parse presentation rels to find slide ordering
        pres_rels_xml = zf.read('ppt/_rels/presentation.xml.rels')
        pres_rels_root = etree.fromstring(pres_rels_xml)

        # Get sldIdLst for ordering
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        slide_order = []  # list of (rId, part_path)
        if sld_id_lst is not None:
            for sld_id in sld_id_lst.findall('p:sldId', NS):
                r_id = sld_id.get(f'{{{NS["r"]}}}id')
                slide_order.append(r_id)

        # Map rId -> target from pres rels
        rid_to_target = {}
        for rel in pres_rels_root.findall('rel:Relationship', NS):
            rid_to_target[rel.get('Id')] = rel.get('Target')

        # Analyze each slide in order
        slides_info = []
        for idx, r_id in enumerate(slide_order):
            target = rid_to_target.get(r_id, '')
            # Target is like "slides/slide1.xml" - make full path
            slide_path = f'ppt/{target}' if not target.startswith('ppt/') else target
            rels_path = slide_path.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels'

            if slide_path not in namelist:
                continue

            slide_xml = zf.read(slide_path)
            slide_root = etree.fromstring(slide_xml)

            # Get shapes from spTree
            sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
            shapes = []
            if sp_tree is not None:
                shapes = extract_shapes_recursive(sp_tree, NS)

            # Count media rels
            media_count = 0
            if rels_path in namelist:
                media_count = count_media_rels(zf.read(rels_path))

            # Get background
            bg_info = get_background_info(slide_root, NS)

            # Determine layout via rels
            layout_name = None
            if rels_path in namelist:
                slide_rels = etree.fromstring(zf.read(rels_path))
                for rel in slide_rels.findall('rel:Relationship', NS):
                    if 'slideLayout' in rel.get('Type', ''):
                        layout_target = rel.get('Target', '')
                        # Try to get layout name from the layout XML
                        layout_path = f'ppt/slides/{layout_target}' if layout_target.startswith('../') else f'ppt/{layout_target}'
                        layout_path = layout_path.replace('ppt/slides/../', 'ppt/')
                        if layout_path in namelist:
                            try:
                                layout_root = etree.fromstring(zf.read(layout_path))
                                csld = layout_root.find('p:cSld', NS)
                                if csld is not None:
                                    layout_name = csld.get('name', layout_target)
                                else:
                                    layout_name = layout_target
                            except Exception:
                                layout_name = layout_target
                        break

            # Build text_shape_ids for easy LLM reference
            text_shape_ids = []
            for s in shapes:
                if s.get('has_text_body') and s.get('text', '').strip():
                    text_shape_ids.append(s['shape_id'])
                # Check children in groups
                for child in s.get('children', []):
                    if child.get('has_text_body') and child.get('text', '').strip():
                        text_shape_ids.append(child['shape_id'])

            slide_info = {
                'index': idx,
                'source_slide': idx,  # for use in fill data
                'slide_part': slide_path,
                'layout': layout_name,
                'background': bg_info,
                'media_relation_count': media_count,
                'shapes': shapes,
                'text_shape_ids': text_shape_ids,
                'suggested_usage': _suggest_usage(shapes, bg_info, media_count),
            }
            slides_info.append(slide_info)

        result = {
            'file': pptx_path,
            'slide_width_inches': round(width_emu / EMU_PER_INCH, 2),
            'slide_height_inches': round(height_emu / EMU_PER_INCH, 2),
            'slide_count': len(slides_info),
            'slides': slides_info,
        }

    return result


def _suggest_usage(shapes, bg_info, media_count):
    """Heuristic to suggest what the slide might be used for."""
    text_shapes = [s for s in shapes if s.get('has_text_body') and s.get('text', '').strip()]
    placeholders = [s for s in shapes if s.get('is_placeholder')]

    has_title = any(s.get('placeholder_type') in ('title', 'ctrTitle') for s in placeholders)
    has_body = any(s.get('placeholder_type') == 'body' for s in placeholders)
    has_subtitle = any(s.get('placeholder_type') in ('subTitle', 'subtitle') for s in placeholders)

    if has_title and has_subtitle and not has_body:
        return 'cover / title slide'
    if has_title and has_body:
        return 'content slide (title + body)'
    if has_title and media_count > 0:
        return 'image/media slide with title'
    if media_count > 0 and len(text_shapes) <= 2:
        return 'visual / image slide'
    if has_title and not has_body and len(text_shapes) <= 2:
        return 'section divider'
    if len(text_shapes) > 4:
        return 'multi-content / complex layout'
    if len(text_shapes) == 0 and media_count == 0:
        return 'blank / decorative'

    return 'general content'


def main():
    parser = argparse.ArgumentParser(
        description='Analyze a .pptx template and output full shape inventory as JSON.'
    )
    parser.add_argument('template', help='Path to template .pptx file')
    parser.add_argument('--output', '-o', help='Output JSON file path (default: stdout)')
    args = parser.parse_args()

    if not Path(args.template).exists():
        print(f"Error: File not found: {args.template}", file=sys.stderr)
        sys.exit(1)

    result = analyze_template(args.template)
    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_json, encoding='utf-8')
        print(f"Analysis written to: {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == '__main__':
    main()
