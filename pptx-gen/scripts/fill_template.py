#!/usr/bin/env python3
"""
fill_template.py - Fill a .pptx template by duplicating slides and replacing content.

The fundamental principle: ALWAYS use the template. Duplicate existing template slides
that have the desired visual design, then replace the text content. This preserves all
backgrounds, decorative elements, fonts, and brand styling.

Usage:
    python fill_template.py --template <template.pptx> --data <content.json> --output <output.pptx>

Data JSON format:
{
  "slides": [
    {
      "duplicate_from": 0,
      "replacements": {
        "Original Title Text": "New Title",
        "Original body text": "New body content"
      }
    },
    {
      "duplicate_from": 5,
      "replacements": {
        "Please Enter Your Headline": "My Actual Headline",
        "Enter your subhead line here": "Actual subtitle"
      }
    },
    {
      "duplicate_from": 3,
      "textboxes": [
        {
          "match": "partial text to find",
          "content": "Full replacement text"
        }
      ]
    },
    {
      "duplicate_from": 5,
      "placeholders": {
        "0": {"type": "text", "content": "Title via placeholder idx"}
      },
      "replacements": {
        "some text in free textbox": "new text"
      }
    }
  ]
}

Three ways to target content on a duplicated slide:
1. "replacements": {"old text": "new text"} — find textbox by its current text (partial match), replace
2. "textboxes": [{"match": "...", "content": "..."}] — same as above but as array
3. "placeholders": {"idx": {...}} — target standard placeholders by index (if available)

All three can be combined on one slide spec.
"""

import sys
import json
import copy
import argparse
from pathlib import Path
from lxml import etree

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN


def duplicate_slide(prs, slide_index):
    """
    Duplicate an existing slide by deep-copying its XML and relationships.
    Returns the new slide object.
    """
    source_slide = prs.slides[slide_index]
    slide_layout = source_slide.slide_layout

    # Add a new slide with the same layout
    new_slide = prs.slides.add_slide(slide_layout)

    # Deep copy the entire cSld element (contains all visible content)
    source_cSld = source_slide._element.find(
        '{http://schemas.openxmlformats.org/presentationml/2006/main}cSld'
    )
    new_cSld = new_slide._element.find(
        '{http://schemas.openxmlformats.org/presentationml/2006/main}cSld'
    )

    if source_cSld is not None and new_cSld is not None:
        new_slide._element.replace(new_cSld, copy.deepcopy(source_cSld))

    # Copy relationships (images, embedded objects, etc.)
    for rel in source_slide.part.rels.values():
        if "slideLayout" in rel.reltype or "notesSlide" in rel.reltype:
            continue
        if rel.is_external:
            new_slide.part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        else:
            try:
                new_slide.part.rels.get_or_add(rel.reltype, rel.target_part)
            except Exception:
                pass

    return new_slide


A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def get_textbody_text(txBody):
    """Get all text from a txBody element (works for both a:txBody and p:txBody)."""
    texts = []
    # Find all <a:p> (paragraph) elements - search by local name
    for elem in txBody:
        if elem.tag.endswith('}p') or elem.tag == 'p':
            para_text = ''
            for sub in elem.iter():
                if (sub.tag.endswith('}t') or sub.tag == 't') and sub.text:
                    para_text += sub.text
            texts.append(para_text)
    return "\n".join(texts)


def replace_textbody_text(txBody, new_text):
    """
    Replace text in a txBody element while preserving first run's formatting.
    Splits new_text by newlines into separate paragraphs.
    Works with any namespace (a: or p:).
    """
    # Find all paragraph elements
    paras = [elem for elem in txBody if elem.tag.endswith('}p') or elem.tag == 'p']
    if not paras:
        return False

    # Determine the namespace prefix used for paragraphs
    first_para = paras[0]
    para_ns = first_para.tag.rsplit('}', 1)[0] + '}' if '}' in first_para.tag else ''

    # Find first run and its properties for formatting reference
    rPr_template = None
    pPr_template = None
    for child in first_para:
        if child.tag.endswith('}pPr'):
            pPr_template = child
        elif child.tag.endswith('}r'):
            for rc in child:
                if rc.tag.endswith('}rPr'):
                    rPr_template = rc
                    break
            break

    # Remove all existing paragraphs
    for p in paras:
        txBody.remove(p)

    # Create new paragraphs for each line
    lines = new_text.split("\n")
    for line in lines:
        p_elem = etree.SubElement(txBody, f'{para_ns}p')
        # Copy paragraph properties
        if pPr_template is not None:
            p_elem.append(copy.deepcopy(pPr_template))
        # Create run
        r_elem = etree.SubElement(p_elem, f'{para_ns}r')
        # Copy run properties
        if rPr_template is not None:
            r_elem.append(copy.deepcopy(rPr_template))
        # Set text
        t_elem = etree.SubElement(r_elem, f'{para_ns}t')
        t_elem.text = line

    return True


def apply_replacements(slide, replacements):
    """
    Find text bodies on the slide whose text contains the key (partial match),
    and replace their text. Works directly on XML to handle duplicated slides.
    Searches both a:txBody and p:txBody namespaces.
    """
    matched = set()

    # Find all txBody elements regardless of namespace (they can be a:txBody or p:txBody)
    slide_elem = slide._element
    all_txBodies = []
    for elem in slide_elem.iter():
        if elem.tag.endswith('}txBody') or elem.tag == 'txBody':
            all_txBodies.append(elem)

    for txBody in all_txBodies:
        body_text = get_textbody_text(txBody)
        if not body_text.strip():
            continue

        for old_text, new_text in replacements.items():
            if old_text in body_text and old_text not in matched:
                replace_textbody_text(txBody, new_text)
                matched.add(old_text)
                break

    unmatched = set(replacements.keys()) - matched
    if unmatched:
        print(f"  Warning: No match found for: {unmatched}", file=sys.stderr)


def apply_textboxes(slide, textboxes):
    """
    Array-based text replacement. Each item: {"match": "...", "content": "..."}
    """
    replacements = {}
    for item in textboxes:
        match_text = item.get("match", "")
        content = item.get("content", "")
        if match_text:
            replacements[match_text] = content
    if replacements:
        apply_replacements(slide, replacements)


def apply_placeholder_content(slide, placeholders_data):
    """Fill standard placeholders by idx — works on non-duplicated slides or via XML."""
    # For placeholders, try python-pptx's native access first
    for idx_str, ph_data in placeholders_data.items():
        try:
            idx = int(idx_str)
        except ValueError:
            continue

        ph_type = ph_data.get("type", "text")
        content = ph_data.get("content", "")

        # Try native placeholder access
        placeholder = None
        try:
            for ph in slide.placeholders:
                if ph.placeholder_format.idx == idx:
                    placeholder = ph
                    break
        except Exception:
            pass

        if placeholder is not None and ph_type == "text":
            if placeholder.has_text_frame:
                # Use XML method for reliability
                txBody = placeholder._element.find(f'.//{{{A_NS}}}txBody')
                if txBody is not None:
                    replace_textbody_text(txBody, content)
                continue

        if placeholder is not None and ph_type == "image":
            if Path(content).exists():
                try:
                    placeholder.insert_picture(content)
                except Exception as e:
                    print(f"  Warning: Image insert failed: {e}", file=sys.stderr)
            continue

        # Fallback: search in XML for placeholder by idx attribute
        slide_elem = slide._element
        # Placeholders have a <p:ph> element with idx attribute
        for sp in slide_elem.findall(f'.//{{{P_NS}}}cSld/{{{P_NS}}}spTree//'):
            ph_elem = sp.find(f'.//{{{P_NS}}}ph')
            if ph_elem is not None:
                sp_idx = ph_elem.get('idx', '')
                if sp_idx == idx_str:
                    txBody = sp.find(f'.//{{{A_NS}}}txBody')
                    if txBody is not None and ph_type == "text":
                        replace_textbody_text(txBody, content)
                    break


def process_slide(prs, slide_spec):
    """Process a single slide specification by duplicating and filling."""
    if "duplicate_from" not in slide_spec:
        print("  Error: Each slide must have 'duplicate_from' to specify which template slide to use",
              file=sys.stderr)
        return None

    source_idx = slide_spec["duplicate_from"]
    if source_idx < 0 or source_idx >= len(prs.slides):
        print(f"  Error: duplicate_from index {source_idx} out of range (0-{len(prs.slides)-1})",
              file=sys.stderr)
        return None

    slide = duplicate_slide(prs, source_idx)

    # Apply content in order: placeholders first, then text replacements
    if "placeholders" in slide_spec:
        apply_placeholder_content(slide, slide_spec["placeholders"])

    if "replacements" in slide_spec:
        apply_replacements(slide, slide_spec["replacements"])

    if "textboxes" in slide_spec:
        apply_textboxes(slide, slide_spec["textboxes"])

    return slide


def main():
    parser = argparse.ArgumentParser(
        description="Fill a .pptx template by duplicating slides and replacing content."
    )
    parser.add_argument("--template", required=True, help="Path to template .pptx file")
    parser.add_argument("--data", required=True, help="Path to content JSON file")
    parser.add_argument("--output", required=True, help="Output .pptx file path")
    args = parser.parse_args()

    # Load template
    try:
        prs = Presentation(args.template)
    except Exception as e:
        print(f"Error loading template: {e}", file=sys.stderr)
        sys.exit(1)

    # Load data
    try:
        with open(args.data, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading data JSON: {e}", file=sys.stderr)
        sys.exit(1)

    slides_data = data.get("slides", [])
    if not slides_data:
        print("Warning: No slides defined in data JSON", file=sys.stderr)
        sys.exit(1)

    # Record original slide count — these are the template "palette" slides
    original_slide_count = len(prs.slides)
    print(f"Template has {original_slide_count} slides available as source", file=sys.stderr)

    # Process each slide spec (all must use duplicate_from)
    created_slides = []
    for i, slide_spec in enumerate(slides_data):
        print(f"Processing slide {i + 1}/{len(slides_data)}...", file=sys.stderr)
        slide = process_slide(prs, slide_spec)
        if slide:
            created_slides.append(slide)

    # Remove original template slides (they served as the palette)
    slide_list = prs.slides._sldIdLst
    slide_ids = list(slide_list)
    for i in range(min(original_slide_count, len(slide_ids))):
        slide_list.remove(slide_ids[i])

    print(f"Generated {len(created_slides)} slides, removed {original_slide_count} template source slides",
          file=sys.stderr)

    # Save output
    try:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))
        print(f"Output saved to: {args.output}")
    except Exception as e:
        print(f"Error saving output: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
