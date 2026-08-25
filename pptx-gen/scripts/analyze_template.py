#!/usr/bin/env python3
"""
analyze_template.py - Analyze a .pptx template and output its structure as JSON.

Outputs all slide layouts, placeholders, AND free textboxes on each slide,
so the agent knows exactly what text to target for replacement.

Usage:
    python analyze_template.py <template.pptx>
"""

import sys
import json
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER


def emu_to_inches(emu_value):
    if emu_value is None:
        return None
    return round(emu_value / 914400, 2)


def placeholder_type_name(ph_type):
    type_map = {
        PP_PLACEHOLDER.TITLE: "title",
        PP_PLACEHOLDER.CENTER_TITLE: "center_title",
        PP_PLACEHOLDER.SUBTITLE: "subtitle",
        PP_PLACEHOLDER.BODY: "body",
        PP_PLACEHOLDER.OBJECT: "object",
    }
    return type_map.get(ph_type, str(ph_type) if ph_type else "unknown")


def get_shape_text(shape):
    """Get text content of a shape, truncated for readability."""
    if not shape.has_text_frame:
        return ""
    text = "\n".join(para.text for para in shape.text_frame.paragraphs)
    return text[:200] + "..." if len(text) > 200 else text


def analyze_template(pptx_path):
    prs = Presentation(pptx_path)

    result = {
        "file": pptx_path,
        "slide_width_inches": round(prs.slide_width / 914400, 2),
        "slide_height_inches": round(prs.slide_height / 914400, 2),
        "layouts": [],
        "existing_slides": [],
    }

    # Analyze layouts
    for layout in prs.slide_layouts:
        layout_info = {"name": layout.name, "placeholders": []}
        for ph in layout.placeholders:
            ph_info = {
                "idx": ph.placeholder_format.idx,
                "name": ph.name,
                "type": placeholder_type_name(ph.placeholder_format.type),
                "position": {
                    "left_inches": emu_to_inches(ph.left),
                    "top_inches": emu_to_inches(ph.top),
                    "width_inches": emu_to_inches(ph.width),
                    "height_inches": emu_to_inches(ph.height),
                },
            }
            layout_info["placeholders"].append(ph_info)
        result["layouts"].append(layout_info)

    # Analyze existing slides — include ALL text content (placeholders + free textboxes)
    for idx, slide in enumerate(prs.slides):
        slide_info = {
            "index": idx,
            "layout": slide.slide_layout.name,
            "placeholders": [],
            "textboxes": [],
        }

        for shape in slide.shapes:
            text = get_shape_text(shape)
            shape_data = {
                "name": shape.name,
                "text": text,
                "position": {
                    "left_inches": emu_to_inches(shape.left),
                    "top_inches": emu_to_inches(shape.top),
                    "width_inches": emu_to_inches(shape.width),
                    "height_inches": emu_to_inches(shape.height),
                },
            }

            if shape.is_placeholder:
                ph_fmt = shape.placeholder_format
                shape_data["idx"] = ph_fmt.idx
                shape_data["type"] = placeholder_type_name(ph_fmt.type)
                slide_info["placeholders"].append(shape_data)
            elif shape.has_text_frame and text.strip():
                # Free textbox with content
                slide_info["textboxes"].append(shape_data)

        result["existing_slides"].append(slide_info)

    return result


def main():
    if len(sys.argv) != 2:
        print("Usage: python analyze_template.py <template.pptx>", file=sys.stderr)
        sys.exit(1)

    pptx_path = sys.argv[1]
    result = analyze_template(pptx_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
