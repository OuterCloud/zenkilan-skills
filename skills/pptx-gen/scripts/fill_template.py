#!/usr/bin/env python3
"""
fill_template.py - Fill a .pptx template using OOXML package-level operations.

Uses zipfile + lxml only. No python-pptx dependency.

Core workflow:
1. Read all parts from the template ZIP
2. For each slide spec in data.json, copy the source slide XML + rels to a new unique part
3. Apply shape edits by shape_id (stable p:cNvPr @id)
4. Update presentation.xml sldIdLst, presentation.xml.rels, [Content_Types].xml
5. Write output ZIP preserving all other template parts (media, layouts, themes, etc.)

Data JSON format (v2 - shape_id based):
{
  "slides": [
    {
      "source_slide": 0,
      "edits": [
        {"shape_id": 68, "text": "New Title"},
        {"shape_id": 53, "paragraphs": [
          {"text": "Bold line", "bold": true, "size": 24},
          {"text": "Normal line"}
        ]},
        {"shape_id": 41, "clear": true}
      ],
      "clear_shape_ids": [99, 100],
      "editable_shape_ids": [68, 53, 41, 99, 100],
      "require_all_edits": true
    }
  ],
  "forbidden_text_patterns": ["TODO", "FIXME"]
}

Also supports legacy format with "duplicate_from" and "replacements".
"""

import sys
import json
import copy
import re
import argparse
import zipfile
from io import BytesIO
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

# Namespace URIs for relationship types
REL_TYPE_SLIDE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide'
REL_TYPE_NOTES = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide'

# Default forbidden placeholder patterns
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


class FillError(Exception):
    """Raised when fill operation encounters a hard error."""
    pass


def register_namespaces():
    """Register all OOXML namespaces for clean serialization."""
    ns_map = {
        'a': NS['a'],
        'r': NS['r'],
        'p': NS['p'],
        # Additional common namespaces
        'p14': 'http://schemas.microsoft.com/office/powerpoint/2010/main',
        'p15': 'http://schemas.microsoft.com/office/powerpoint/2012/main',
        'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    }
    for prefix, uri in ns_map.items():
        try:
            etree.register_namespace(prefix, uri)
        except Exception:
            pass


register_namespaces()


# ──────────────────────────────────────────────────────────────────────────────
# Text editing helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_txbody_text(txbody):
    """Get all text from an a:txBody element."""
    if txbody is None:
        return ""
    paragraphs = []
    for p_elem in txbody.findall('a:p', NS):
        para_texts = []
        for r_elem in p_elem.findall('a:r', NS):
            t_elem = r_elem.find('a:t', NS)
            if t_elem is not None and t_elem.text:
                para_texts.append(t_elem.text)
        for br_elem in p_elem.findall('a:br', NS):
            para_texts.append('\n')
        paragraphs.append("".join(para_texts))
    return "\n".join(paragraphs)


def _get_first_rpr(txbody):
    """Get the rPr from the first run in the txBody for format preservation."""
    for p_elem in txbody.findall('a:p', NS):
        for r_elem in p_elem.findall('a:r', NS):
            rpr = r_elem.find('a:rPr', NS)
            if rpr is not None:
                return copy.deepcopy(rpr)
    return None


def _get_first_ppr(txbody):
    """Get the pPr from the first paragraph in the txBody."""
    for p_elem in txbody.findall('a:p', NS):
        ppr = p_elem.find('a:pPr', NS)
        if ppr is not None:
            return copy.deepcopy(ppr)
    return None


def _make_rpr(base_rpr, bold=None, size=None, color=None):
    """Create a run properties element with overrides."""
    a_ns = NS['a']
    if base_rpr is not None:
        rpr = copy.deepcopy(base_rpr)
    else:
        rpr = etree.Element(f'{{{a_ns}}}rPr')

    if bold is not None:
        rpr.set('b', '1' if bold else '0')
    if size is not None:
        # OOXML uses hundredths of a point
        rpr.set('sz', str(int(size * 100)))
    if color is not None:
        # Remove existing solidFill if present
        for sf in rpr.findall(f'{{{a_ns}}}solidFill'):
            rpr.remove(sf)
        solid_fill = etree.SubElement(rpr, f'{{{a_ns}}}solidFill')
        srgb = etree.SubElement(solid_fill, f'{{{a_ns}}}srgbClr')
        srgb.set('val', color.lstrip('#'))
    return rpr


def _make_ppr(base_ppr, alignment=None, level=None):
    """Create paragraph properties element with overrides."""
    a_ns = NS['a']
    if base_ppr is not None:
        ppr = copy.deepcopy(base_ppr)
    else:
        ppr = etree.Element(f'{{{a_ns}}}pPr')

    if alignment is not None:
        algn_map = {'left': 'l', 'center': 'ctr', 'right': 'r', 'justify': 'just'}
        ppr.set('algn', algn_map.get(alignment, alignment))
    if level is not None:
        ppr.set('lvl', str(level))
    return ppr


def set_txbody_text(txbody, text_or_paragraphs):
    """
    Replace txBody content preserving first run/paragraph format.

    text_or_paragraphs can be:
    - str: simple text, \\n splits into paragraphs
    - list of dicts: [{"text": "...", "bold": true, "size": 24, "color": "FF0000",
                       "alignment": "center", "level": 0}]
    """
    a_ns = NS['a']

    # Save format templates from first para/run
    base_rpr = _get_first_rpr(txbody)
    base_ppr = _get_first_ppr(txbody)

    # Remove all existing paragraphs
    for p_elem in list(txbody.findall('a:p', NS)):
        txbody.remove(p_elem)

    # Normalize input to paragraph list
    if isinstance(text_or_paragraphs, str):
        para_specs = [{'text': line} for line in text_or_paragraphs.split('\n')]
    elif isinstance(text_or_paragraphs, list):
        para_specs = text_or_paragraphs
    else:
        para_specs = [{'text': str(text_or_paragraphs)}]

    for para_spec in para_specs:
        if isinstance(para_spec, str):
            para_spec = {'text': para_spec}

        p_text = para_spec.get('text', '')
        p_bold = para_spec.get('bold')
        p_size = para_spec.get('size')
        p_color = para_spec.get('color')
        p_alignment = para_spec.get('alignment')
        p_level = para_spec.get('level')

        p_elem = etree.SubElement(txbody, f'{{{a_ns}}}p')

        # Paragraph properties
        ppr = _make_ppr(base_ppr, alignment=p_alignment, level=p_level)
        if ppr is not None and (len(ppr.attrib) > 0 or len(ppr) > 0):
            p_elem.insert(0, ppr)

        # Create run
        r_elem = etree.SubElement(p_elem, f'{{{a_ns}}}r')

        # Run properties
        rpr = _make_rpr(base_rpr, bold=p_bold, size=p_size, color=p_color)
        if rpr is not None:
            r_elem.insert(0, rpr)

        # Text
        t_elem = etree.SubElement(r_elem, f'{{{a_ns}}}t')
        t_elem.text = p_text

    # Ensure at least one paragraph exists
    if len(txbody.findall('a:p', NS)) == 0:
        p_elem = etree.SubElement(txbody, f'{{{a_ns}}}p')


def clear_txbody(txbody):
    """Clear all text from txBody, leaving one empty paragraph (OOXML requires it)."""
    a_ns = NS['a']
    # Save pPr from first para for the empty para
    base_ppr = _get_first_ppr(txbody)
    base_rpr = _get_first_rpr(txbody)

    for p_elem in list(txbody.findall('a:p', NS)):
        txbody.remove(p_elem)

    # One empty paragraph is required
    p_elem = etree.SubElement(txbody, f'{{{a_ns}}}p')
    if base_ppr is not None:
        p_elem.insert(0, copy.deepcopy(base_ppr))
    # Add endParaRPr to preserve formatting for future edits
    if base_rpr is not None:
        end_rpr = copy.deepcopy(base_rpr)
        end_rpr.tag = f'{{{a_ns}}}endParaRPr'
        p_elem.append(end_rpr)


# ──────────────────────────────────────────────────────────────────────────────
# Shape finding by shape_id
# ──────────────────────────────────────────────────────────────────────────────

def _find_txbody(shape_elem):
    """Find txBody element in a shape, regardless of namespace (a: or p:)."""
    for elem in shape_elem.iter():
        if etree.QName(elem.tag).localname == 'txBody':
            return elem
    return None

def find_shape_by_id(sp_tree, shape_id):
    """
    Recursively find a shape element by its cNvPr @id in the spTree.
    Returns the shape element (p:sp, p:graphicFrame, etc.) or None.
    """
    shape_local_names = {'sp', 'pic', 'graphicFrame', 'grpSp', 'cxnSp'}

    def _search(parent):
        for child in parent:
            local = etree.QName(child.tag).localname
            if local in shape_local_names:
                # Check cNvPr in this shape
                cnvpr = _get_cnvpr(child)
                if cnvpr is not None and cnvpr.get('id') == str(shape_id):
                    return child
                # Recurse into groups
                if local == 'grpSp':
                    result = _search(child)
                    if result is not None:
                        return result
        return None

    return _search(sp_tree)


def _get_cnvpr(shape_elem):
    """Get the cNvPr element from a shape. Works with any namespace."""
    for child in shape_elem:
        local = etree.QName(child.tag).localname
        if local.startswith('nv') and local.endswith('Pr'):
            # Look for cNvPr inside the nvXxxPr element
            for sub in child:
                if etree.QName(sub.tag).localname == 'cNvPr':
                    return sub
    return None


def get_all_shape_ids(sp_tree):
    """Get all shape IDs in a spTree (for duplicate detection)."""
    ids = []
    shape_local_names = {'sp', 'pic', 'graphicFrame', 'grpSp', 'cxnSp'}

    def _collect(parent):
        for child in parent:
            local = etree.QName(child.tag).localname
            if local in shape_local_names:
                cnvpr = _get_cnvpr(child)
                if cnvpr is not None:
                    try:
                        ids.append(int(cnvpr.get('id', '0')))
                    except ValueError:
                        pass
                if local == 'grpSp':
                    _collect(child)

    _collect(sp_tree)
    return ids


# ──────────────────────────────────────────────────────────────────────────────
# OOXML Package manipulation
# ──────────────────────────────────────────────────────────────────────────────

def read_zip_parts(pptx_path):
    """Read all parts from a .pptx ZIP into a dict {path: bytes}."""
    parts = {}
    with zipfile.ZipFile(pptx_path, 'r') as zf:
        for name in zf.namelist():
            parts[name] = zf.read(name)
    return parts


def get_slide_order(pres_root):
    """Get ordered list of (sldId, rId) from presentation.xml."""
    r_ns = NS['r']
    sld_id_lst = pres_root.find('p:sldIdLst', NS)
    if sld_id_lst is None:
        return []
    result = []
    for sld_id in sld_id_lst.findall('p:sldId', NS):
        sid = sld_id.get('id')
        rid = sld_id.get(f'{{{r_ns}}}id')
        result.append((sid, rid))
    return result


def get_max_slide_id(pres_root):
    """Get the maximum slide ID currently used."""
    max_id = 255  # Start above typical IDs
    sld_id_lst = pres_root.find('p:sldIdLst', NS)
    if sld_id_lst is not None:
        for sld_id in sld_id_lst.findall('p:sldId', NS):
            try:
                max_id = max(max_id, int(sld_id.get('id', '0')))
            except ValueError:
                pass
    return max_id


def get_max_rid(rels_root):
    """Get the maximum numeric rId from a relationships XML."""
    max_rid = 0
    for rel in rels_root.findall('rel:Relationship', NS):
        rid = rel.get('Id', '')
        m = re.match(r'rId(\d+)', rid)
        if m:
            max_rid = max(max_rid, int(m.group(1)))
    return max_rid


def resolve_slide_index_to_part(slide_index, parts, pres_root, pres_rels_root):
    """Given a 0-based slide index, find the source slide part path and its rels path."""
    slide_order = get_slide_order(pres_root)
    if slide_index < 0 or slide_index >= len(slide_order):
        raise FillError(f"source_slide index {slide_index} out of range (0-{len(slide_order)-1})")

    _, r_id = slide_order[slide_index]

    # Find the target path from pres rels
    target = None
    for rel in pres_rels_root.findall('rel:Relationship', NS):
        if rel.get('Id') == r_id:
            target = rel.get('Target')
            break

    if target is None:
        raise FillError(f"Cannot find relationship {r_id} in presentation.xml.rels")

    slide_path = f'ppt/{target}' if not target.startswith('/') else target.lstrip('/')
    rels_path = slide_path.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels'

    if slide_path not in parts:
        raise FillError(f"Slide part not found: {slide_path}")

    return slide_path, rels_path


def remove_notes_rels(rels_bytes):
    """Remove notesSlide relationships from slide rels XML bytes. Returns new bytes."""
    if not rels_bytes:
        return rels_bytes
    root = etree.fromstring(rels_bytes)
    removed = False
    for rel in list(root.findall('rel:Relationship', NS)):
        rel_type = rel.get('Type', '')
        if 'notesSlide' in rel_type:
            root.remove(rel)
            removed = True
    if removed:
        return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    return rels_bytes


# ──────────────────────────────────────────────────────────────────────────────
# Legacy replacements support
# ──────────────────────────────────────────────────────────────────────────────

def apply_legacy_replacements(slide_root, replacements, slide_idx, allow_warnings=False):
    """
    Apply old-style text replacements {"old_text": "new_text"}.
    Detects ambiguity: 0 or >1 match is a hard fail unless --allow-warnings.
    """
    sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
    if sp_tree is None:
        return

    # Collect all txBody elements with their text
    all_txbodies = []
    for elem in sp_tree.iter():
        if etree.QName(elem.tag).localname == 'txBody':
            text = get_txbody_text(elem)
            if text.strip():
                all_txbodies.append((elem, text))

    for old_text, new_text in replacements.items():
        matches = [(tb, txt) for tb, txt in all_txbodies if old_text in txt]
        if len(matches) == 0:
            msg = f"Slide {slide_idx}: replacement key '{old_text}' matched 0 shapes"
            if allow_warnings:
                print(f"  Warning: {msg}", file=sys.stderr)
            else:
                raise FillError(msg)
        elif len(matches) > 1:
            msg = f"Slide {slide_idx}: replacement key '{old_text}' matched {len(matches)} shapes (ambiguous)"
            if allow_warnings:
                print(f"  Warning: {msg}", file=sys.stderr)
                # Apply to first match only
                set_txbody_text(matches[0][0], new_text)
            else:
                raise FillError(msg)
        else:
            set_txbody_text(matches[0][0], new_text)


# ──────────────────────────────────────────────────────────────────────────────
# Main fill logic
# ──────────────────────────────────────────────────────────────────────────────

def fill_template(template_path, data, output_path, allow_warnings=False):
    """
    Main fill function. Reads template, creates output with specified slides.
    """
    parts = read_zip_parts(template_path)

    # Parse key package parts
    pres_xml = parts['ppt/presentation.xml']
    pres_root = etree.fromstring(pres_xml)
    pres_rels_xml = parts['ppt/_rels/presentation.xml.rels']
    pres_rels_root = etree.fromstring(pres_rels_xml)
    ct_xml = parts['[Content_Types].xml']
    ct_root = etree.fromstring(ct_xml)

    slides_data = data.get('slides', [])
    if not slides_data:
        raise FillError("No slides defined in data JSON")

    # Track new slides
    max_slide_id = get_max_slide_id(pres_root)
    max_rid = get_max_rid(pres_rels_root)

    # Find max existing slide number for naming
    existing_slide_nums = []
    for name in parts:
        m = re.match(r'ppt/slides/slide(\d+)\.xml$', name)
        if m:
            existing_slide_nums.append(int(m.group(1)))
    next_slide_num = max(existing_slide_nums) + 1 if existing_slide_nums else 1

    # Process each slide spec
    new_slide_entries = []  # (new_slide_path, new_rels_path, slide_id, r_id)

    for spec_idx, spec in enumerate(slides_data):
        # Resolve source_slide (also support legacy duplicate_from)
        source_idx = spec.get('source_slide', spec.get('duplicate_from'))
        if source_idx is None:
            raise FillError(f"Slide spec {spec_idx}: missing 'source_slide' or 'duplicate_from'")

        src_path, src_rels_path = resolve_slide_index_to_part(
            source_idx, parts, pres_root, pres_rels_root
        )

        # Copy source slide XML
        new_slide_num = next_slide_num
        next_slide_num += 1
        new_slide_path = f'ppt/slides/slide{new_slide_num}.xml'
        new_rels_path = f'ppt/slides/_rels/slide{new_slide_num}.xml.rels'

        # Deep copy slide XML
        slide_xml_bytes = parts[src_path]
        slide_root = etree.fromstring(slide_xml_bytes)

        # Copy rels (preserving all relationships except notes)
        if src_rels_path in parts:
            rels_bytes = remove_notes_rels(parts[src_rels_path])
        else:
            # Create minimal rels if source has none
            rels_bytes = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'

        # ─── Apply edits ───

        # shape_id based edits (v2)
        edits = spec.get('edits', [])
        clear_shape_ids = spec.get('clear_shape_ids', [])
        editable_shape_ids = spec.get('editable_shape_ids', [])
        require_all_edits = spec.get('require_all_edits', False)

        sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
        if sp_tree is None:
            raise FillError(f"Slide spec {spec_idx}: source slide {source_idx} has no spTree")

        # Check for duplicate shape IDs
        all_ids = get_all_shape_ids(sp_tree)
        id_counts = {}
        for sid in all_ids:
            id_counts[sid] = id_counts.get(sid, 0) + 1
        duplicates = [sid for sid, cnt in id_counts.items() if cnt > 1]
        if duplicates:
            msg = f"Slide spec {spec_idx}: source slide {source_idx} has duplicate shape IDs: {duplicates}"
            if not allow_warnings:
                raise FillError(msg)
            print(f"  Warning: {msg}", file=sys.stderr)

        # Apply shape_id edits
        edited_shape_ids = set()
        for edit in edits:
            shape_id = edit.get('shape_id')
            if shape_id is None:
                raise FillError(f"Slide spec {spec_idx}: edit missing 'shape_id'")

            shape_elem = find_shape_by_id(sp_tree, shape_id)
            if shape_elem is None:
                msg = f"Slide spec {spec_idx}: shape_id {shape_id} not found in source slide {source_idx}"
                if allow_warnings:
                    print(f"  Warning: {msg}", file=sys.stderr)
                    continue
                else:
                    raise FillError(msg)

            txbody = _find_txbody(shape_elem)
            if txbody is None:
                msg = f"Slide spec {spec_idx}: shape_id {shape_id} has no text body"
                if allow_warnings:
                    print(f"  Warning: {msg}", file=sys.stderr)
                    continue
                else:
                    raise FillError(msg)

            if edit.get('clear', False):
                clear_txbody(txbody)
            elif 'paragraphs' in edit:
                set_txbody_text(txbody, edit['paragraphs'])
            elif 'text' in edit:
                set_txbody_text(txbody, edit['text'])

            edited_shape_ids.add(shape_id)

        # Apply clear_shape_ids
        for shape_id in clear_shape_ids:
            if shape_id in edited_shape_ids:
                continue  # Already handled by edits
            shape_elem = find_shape_by_id(sp_tree, shape_id)
            if shape_elem is None:
                msg = f"Slide spec {spec_idx}: clear_shape_ids: shape_id {shape_id} not found"
                if allow_warnings:
                    print(f"  Warning: {msg}", file=sys.stderr)
                else:
                    raise FillError(msg)
                continue

            txbody = _find_txbody(shape_elem)
            if txbody is not None:
                clear_txbody(txbody)
            edited_shape_ids.add(shape_id)

        # Require all edits check
        if require_all_edits and editable_shape_ids:
            unedited = set(editable_shape_ids) - edited_shape_ids
            if unedited:
                raise FillError(
                    f"Slide spec {spec_idx}: require_all_edits is true but these shapes "
                    f"were not edited/cleared: {sorted(unedited)}"
                )

        # Legacy replacements support
        replacements = spec.get('replacements')
        if replacements:
            apply_legacy_replacements(slide_root, replacements, spec_idx, allow_warnings)

        # Legacy textboxes support
        textboxes = spec.get('textboxes')
        if textboxes:
            repl_dict = {}
            for item in textboxes:
                match_text = item.get('match', '')
                content = item.get('content', '')
                if match_text:
                    repl_dict[match_text] = content
            if repl_dict:
                apply_legacy_replacements(slide_root, repl_dict, spec_idx, allow_warnings)

        # Serialize modified slide
        new_slide_xml = etree.tostring(slide_root, xml_declaration=True, encoding='UTF-8', standalone=True)
        parts[new_slide_path] = new_slide_xml
        parts[new_rels_path] = rels_bytes

        # Assign IDs
        max_slide_id += 1
        max_rid += 1
        new_sid = str(max_slide_id)
        new_rid = f'rId{max_rid}'

        new_slide_entries.append((new_slide_path, new_rels_path, new_sid, new_rid))

    # ─── Update presentation.xml ───

    # Reuse the existing sldIdLst in place so presentation child order is unchanged.
    # PowerPoint is sensitive to the schema order of notesMasterIdLst/handoutMasterIdLst/sldIdLst.
    r_ns = NS['r']
    p_ns = NS['p']
    sld_id_lst = pres_root.find('p:sldIdLst', NS)
    if sld_id_lst is None:
        sld_id_lst = etree.Element(f'{{{p_ns}}}sldIdLst')
        # Insert after the last master list, otherwise after sldMasterIdLst.
        insert_after = None
        for tag in ('handoutMasterIdLst', 'notesMasterIdLst', 'sldMasterIdLst'):
            elem = pres_root.find(f'p:{tag}', NS)
            if elem is not None:
                insert_after = elem
                break
        if insert_after is None:
            pres_root.insert(0, sld_id_lst)
        else:
            pres_root.insert(list(pres_root).index(insert_after) + 1, sld_id_lst)
    else:
        for child in list(sld_id_lst):
            sld_id_lst.remove(child)

    for _, _, sid, rid in new_slide_entries:
        sld_id_elem = etree.SubElement(sld_id_lst, f'{{{p_ns}}}sldId')
        sld_id_elem.set('id', sid)
        sld_id_elem.set(f'{{{r_ns}}}id', rid)

    # ─── Update presentation.xml.rels ───

    # Remove existing slide relationships, keep everything else
    for rel in list(pres_rels_root.findall('rel:Relationship', NS)):
        if rel.get('Type') == REL_TYPE_SLIDE:
            pres_rels_root.remove(rel)

    # Add new slide relationships
    rel_ns = NS['rel']
    for slide_path, _, _, rid in new_slide_entries:
        # Target is relative to ppt/ directory
        target = slide_path.replace('ppt/', '')
        rel_elem = etree.SubElement(pres_rels_root, f'{{{rel_ns}}}Relationship')
        rel_elem.set('Id', rid)
        rel_elem.set('Type', REL_TYPE_SLIDE)
        rel_elem.set('Target', target)

    # ─── Update [Content_Types].xml ───

    ct_ns = 'http://schemas.openxmlformats.org/package/2006/content-types'
    existing_overrides = {
        override.get('PartName', '')
        for override in ct_root.findall(f'{{{ct_ns}}}Override')
    }

    # Keep the template's overrides because its source slide parts remain in the package
    # as an unreferenced design palette. Add overrides only for newly created slide parts.
    slide_content_type = 'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'
    for slide_path, _, _, _ in new_slide_entries:
        part_name = f'/{slide_path}'
        if part_name in existing_overrides:
            continue
        override_elem = etree.SubElement(ct_root, f'{{{ct_ns}}}Override')
        override_elem.set('PartName', part_name)
        override_elem.set('ContentType', slide_content_type)
        existing_overrides.add(part_name)

    # ─── Forbidden text check ───

    forbidden_patterns = data.get('forbidden_text_patterns', [])
    all_patterns = DEFAULT_FORBIDDEN_PATTERNS + forbidden_patterns

    # Compile patterns
    compiled_patterns = []
    for pat in all_patterns:
        try:
            compiled_patterns.append((pat, re.compile(pat, re.IGNORECASE)))
        except re.error:
            compiled_patterns.append((pat, re.compile(re.escape(pat), re.IGNORECASE)))

    # Scan all output slides for forbidden text
    violations = []
    for spec_idx, (slide_path, _, _, _) in enumerate(new_slide_entries):
        slide_root = etree.fromstring(parts[slide_path])
        sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
        if sp_tree is None:
            continue

        for elem in sp_tree.iter():
            if etree.QName(elem.tag).localname == 'txBody':
                text = get_txbody_text(elem)
                if not text.strip():
                    continue
                for pat_str, pat_re in compiled_patterns:
                    if pat_re.search(text):
                        # Find shape_id for error message
                        parent = elem.getparent()
                        shape_id = '?'
                        while parent is not None:
                            cnvpr = _get_cnvpr(parent)
                            if cnvpr is not None:
                                shape_id = cnvpr.get('id', '?')
                                break
                            parent = parent.getparent()

                        source_idx = slides_data[spec_idx].get(
                            'source_slide', slides_data[spec_idx].get('duplicate_from', '?'))
                        violations.append(
                            f"Slide {spec_idx} (source={source_idx}, shape_id={shape_id}): "
                            f"forbidden pattern '{pat_str}' found in: {text[:80]!r}"
                        )
                        break  # One violation per shape is enough

    if violations and not allow_warnings:
        raise FillError(
            "Forbidden placeholder text detected:\n" + "\n".join(f"  - {v}" for v in violations)
        )
    elif violations:
        for v in violations:
            print(f"  Warning (forbidden text): {v}", file=sys.stderr)

    # ─── Serialize updated package parts ───

    parts['ppt/presentation.xml'] = etree.tostring(
        pres_root, xml_declaration=True, encoding='UTF-8', standalone=True
    )
    parts['ppt/_rels/presentation.xml.rels'] = etree.tostring(
        pres_rels_root, xml_declaration=True, encoding='UTF-8', standalone=True
    )
    parts['[Content_Types].xml'] = etree.tostring(
        ct_root, xml_declaration=True, encoding='UTF-8', standalone=True
    )

    # ─── Write output ZIP ───

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(str(output_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, content)

    return {
        'output': str(output_path),
        'slide_count': len(new_slide_entries),
        'warnings': len(violations),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Fill a .pptx template using OOXML package-level operations (no python-pptx).'
    )
    parser.add_argument('--template', required=True, help='Path to template .pptx file')
    parser.add_argument('--data', required=True, help='Path to content JSON file')
    parser.add_argument('--output', required=True, help='Output .pptx file path')
    parser.add_argument('--allow-warnings', action='store_true',
                        help='Downgrade hard errors to warnings (missing shapes, ambiguous matches, forbidden text)')
    args = parser.parse_args()

    # Load data
    try:
        with open(args.data, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading data JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Fill template
    try:
        result = fill_template(args.template, data, args.output, args.allow_warnings)
        print(f"Generated {result['slide_count']} slides -> {result['output']}", file=sys.stderr)
        if result['warnings'] > 0:
            print(f"  {result['warnings']} warning(s)", file=sys.stderr)
    except FillError as e:
        print(f"FILL ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
