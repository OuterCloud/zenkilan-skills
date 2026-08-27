#!/usr/bin/env python3
"""
test_pptx_gen.py - Automated tests for fill_template, analyze_template, and validate_pptx.

Uses a programmatically generated minimal .pptx template to verify:
- Background/image relationships are preserved
- Duplicate source slide can generate multiple output pages
- shape_id precise replacement works
- Clear shape_ids works
- Ambiguous text match causes hard fail
- Forbidden text detection works
- require_all_edits enforcement
- Validator passes for valid output
- Validator catches structural errors

Run:
    python3 -m pytest test_pptx_gen.py -v
  or:
    python3 test_pptx_gen.py
"""

import os
import sys
import json
import copy
import tempfile
import unittest
import zipfile
from pathlib import Path
from lxml import etree

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

from fill_template import (
    fill_template, FillError, read_zip_parts, get_txbody_text,
    find_shape_by_id, set_txbody_text, clear_txbody, NS,
    DEFAULT_FORBIDDEN_PATTERNS, _find_txbody,
)
from analyze_template import analyze_template
from validate_pptx import validate_pptx


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic template builder
# ──────────────────────────────────────────────────────────────────────────────

def build_minimal_pptx(output_path, num_slides=2, add_image_rel=True, add_background=True):
    """
    Build a minimal valid .pptx with controllable properties:
    - Configurable number of slides
    - Optional image relationship (media/image1.png)
    - Optional background fill
    - Each slide has 2 shapes with known shape_ids and text
    """
    # Namespaces
    p_ns = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    a_ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    ct_ns = 'http://schemas.openxmlformats.org/package/2006/content-types'

    # Slide layout (minimal)
    layout_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="{a_ns}" xmlns:r="{r_ns}" xmlns:p="{p_ns}" type="blank">
  <p:cSld name="Blank"><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
</p:sldLayout>'''

    # Slide master (minimal)
    master_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="{a_ns}" xmlns:r="{r_ns}" xmlns:p="{p_ns}">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649" r:id="rId1"/>
  </p:sldLayoutIdLst>
</p:sldMaster>'''

    # Theme (minimal)
    theme_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="{a_ns}" name="TestTheme">
  <a:themeElements>
    <a:clrScheme name="Test"><a:dk1><a:srgbClr val="000000"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="000000"/></a:dk2><a:lt2><a:srgbClr val="FFFFFF"/></a:lt2><a:accent1><a:srgbClr val="4472C4"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2><a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4><a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>
    <a:fontScheme name="Test"><a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>
    <a:fmtScheme name="Test"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
  </a:themeElements>
</a:theme>'''

    def make_slide_xml(slide_num, add_bg=False):
        bg_xml = ''
        if add_bg:
            bg_xml = f'''<p:bg><p:bgPr><a:solidFill><a:srgbClr val="2F5496"/></a:solidFill></p:bgPr></p:bg>'''

        # Shape IDs: slide 1 gets 10,11; slide 2 gets 20,21; etc.
        base_id = slide_num * 10
        title_id = base_id + 1
        body_id = base_id + 2

        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="{a_ns}" xmlns:r="{r_ns}" xmlns:p="{p_ns}">
  <p:cSld>
    {bg_xml}
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="{title_id}" name="Title {slide_num}"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="title"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="457200" y="274638"/><a:ext cx="8229600" cy="1143000"/></a:xfrm>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="4400" b="1"/>
              <a:t>Please Enter Title {slide_num}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="{body_id}" name="Body {slide_num}"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="body" idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="457200" y="1600200"/><a:ext cx="8229600" cy="4525963"/></a:xfrm>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="2000"/>
              <a:t>Sample text body {slide_num}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:pic>
        <p:nvPicPr><p:cNvPr id="{base_id + 3}" name="Picture {slide_num}"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
        <p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
        <p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
      </p:pic>
    </p:spTree>
  </p:cSld>
</p:sld>'''

    def make_slide_rels(slide_num, has_image=False):
        image_rel = ''
        if has_image:
            image_rel = f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>'

        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{rel_ns}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  {image_rel}
</Relationships>'''

    # Build presentation.xml
    sld_id_entries = []
    sld_rel_entries = []
    for i in range(num_slides):
        sld_id = 256 + i
        rid = f'rId{i + 2}'  # rId1 = slideMaster
        sld_id_entries.append(f'<p:sldId id="{sld_id}" r:id="{rid}"/>')
        sld_rel_entries.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i+1}.xml"/>'
        )

    pres_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="{a_ns}" xmlns:r="{r_ns}" xmlns:p="{p_ns}">
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId1"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
    {"".join(sld_id_entries)}
  </p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>'''

    pres_rels_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{rel_ns}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
  {"".join(sld_rel_entries)}
  <Relationship Id="rId{num_slides + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
</Relationships>'''

    # Content Types
    slide_overrides = ""
    for i in range(num_slides):
        slide_overrides += f'<Override PartName="/ppt/slides/slide{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>\n'

    content_types_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="{ct_ns}">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  {slide_overrides}
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
</Types>'''

    # Master rels
    master_rels_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{rel_ns}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>'''

    layout_rels_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{rel_ns}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>'''

    # Fake image (1x1 PNG)
    fake_png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
        b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
        b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )

    # Write ZIP
    with zipfile.ZipFile(str(output_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types_xml)
        zf.writestr('_rels/.rels', f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{rel_ns}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>''')
        zf.writestr('ppt/presentation.xml', pres_xml)
        zf.writestr('ppt/_rels/presentation.xml.rels', pres_rels_xml)
        zf.writestr('ppt/slideMasters/slideMaster1.xml', master_xml)
        zf.writestr('ppt/slideMasters/_rels/slideMaster1.xml.rels', master_rels_xml)
        zf.writestr('ppt/slideLayouts/slideLayout1.xml', layout_xml)
        zf.writestr('ppt/slideLayouts/_rels/slideLayout1.xml.rels', layout_rels_xml)
        zf.writestr('ppt/theme/theme1.xml', theme_xml)

        for i in range(num_slides):
            slide_xml = make_slide_xml(i + 1, add_bg=add_background)
            slide_rels = make_slide_rels(i + 1, has_image=add_image_rel)
            zf.writestr(f'ppt/slides/slide{i+1}.xml', slide_xml)
            zf.writestr(f'ppt/slides/_rels/slide{i+1}.xml.rels', slide_rels)

        if add_image_rel:
            zf.writestr('ppt/media/image1.png', fake_png)

    return output_path


# ──────────────────────────────────────────────────────────────────────────────
# Test cases
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeTemplate(unittest.TestCase):
    """Test analyze_template.py functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.template_path = Path(self.tmpdir) / 'template.pptx'
        build_minimal_pptx(self.template_path, num_slides=2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_analysis(self):
        """Analyze returns correct structure with shape_ids."""
        result = analyze_template(str(self.template_path))
        self.assertEqual(result['slide_count'], 2)
        self.assertEqual(len(result['slides']), 2)

    def test_shape_ids_present(self):
        """Each shape has a numeric shape_id from cNvPr."""
        result = analyze_template(str(self.template_path))
        for slide in result['slides']:
            for shape in slide['shapes']:
                self.assertIsInstance(shape['shape_id'], int)
                self.assertGreater(shape['shape_id'], 0)

    def test_text_not_truncated(self):
        """Text is not truncated in output."""
        result = analyze_template(str(self.template_path))
        slide0 = result['slides'][0]
        # Find title shape
        title_shapes = [s for s in slide0['shapes'] if 'Title' in s.get('name', '')]
        self.assertTrue(len(title_shapes) > 0)
        # Text should not end with "..."
        for s in title_shapes:
            self.assertFalse(s['text'].endswith('...'))

    def test_text_shape_ids_list(self):
        """text_shape_ids contains IDs of shapes with non-empty text."""
        result = analyze_template(str(self.template_path))
        for slide in result['slides']:
            self.assertIn('text_shape_ids', slide)
            self.assertIsInstance(slide['text_shape_ids'], list)
            # Our synthetic template has 2 text shapes per slide
            self.assertEqual(len(slide['text_shape_ids']), 2)

    def test_placeholder_info(self):
        """Placeholder shapes include idx and type."""
        result = analyze_template(str(self.template_path))
        slide0 = result['slides'][0]
        placeholders = [s for s in slide0['shapes'] if s.get('is_placeholder')]
        self.assertTrue(len(placeholders) >= 2)
        for ph in placeholders:
            self.assertIn('placeholder_idx', ph)
            self.assertIn('placeholder_type', ph)


class TestFillTemplate(unittest.TestCase):
    """Test fill_template.py core functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.template_path = Path(self.tmpdir) / 'template.pptx'
        self.output_path = Path(self.tmpdir) / 'output.pptx'
        build_minimal_pptx(self.template_path, num_slides=2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_fill(self):
        """Basic fill with shape_id edit produces valid output."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'New Title'},
                    {'shape_id': 12, 'text': 'New Body'},
                ],
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path))
        self.assertEqual(result['slide_count'], 1)
        self.assertTrue(self.output_path.exists())

        # Verify text was replaced
        parts = read_zip_parts(str(self.output_path))
        # Find the output slide
        slide_parts = [k for k in parts if k.startswith('ppt/slides/slide') and k.endswith('.xml')
                       and '_rels' not in k]
        # Parse presentation to find which slides are referenced
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        pres_rels = etree.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        # Get the first slide's content
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        sld_ids = sld_id_lst.findall('p:sldId', NS)
        self.assertEqual(len(sld_ids), 1)

        # Verify text content
        r_ns = NS['r']
        rid = sld_ids[0].get(f'{{{r_ns}}}id')
        target = None
        for rel in pres_rels.findall('rel:Relationship', NS):
            if rel.get('Id') == rid:
                target = rel.get('Target')
        self.assertIsNotNone(target)
        slide_path = f'ppt/{target}'
        slide_root = etree.fromstring(parts[slide_path])
        sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
        shape = find_shape_by_id(sp_tree, 11)
        self.assertIsNotNone(shape)
        txbody = _find_txbody(shape)
        text = get_txbody_text(txbody)
        self.assertEqual(text, 'New Title')

    def test_duplicate_source_two_pages(self):
        """Same source slide duplicated to produce two output pages."""
        data = {
            'slides': [
                {'source_slide': 0, 'edits': [
                    {'shape_id': 11, 'text': 'Page 1'},
                    {'shape_id': 12, 'text': 'Body 1'},
                ]},
                {'source_slide': 0, 'edits': [
                    {'shape_id': 11, 'text': 'Page 2'},
                    {'shape_id': 12, 'text': 'Body 2'},
                ]},
            ]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path))
        self.assertEqual(result['slide_count'], 2)

        # Verify both slides exist and have different content
        parts = read_zip_parts(str(self.output_path))
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        sld_ids = sld_id_lst.findall('p:sldId', NS)
        self.assertEqual(len(sld_ids), 2)

    def test_background_preserved(self):
        """Background fill is preserved in output slide."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'Has BG'},
                    {'shape_id': 12, 'text': 'Body'},
                ],
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path))

        # Check that slide XML still has background
        parts = read_zip_parts(str(self.output_path))
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        pres_rels = etree.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        r_ns = NS['r']
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        rid = sld_id_lst.findall('p:sldId', NS)[0].get(f'{{{r_ns}}}id')
        target = None
        for rel in pres_rels.findall('rel:Relationship', NS):
            if rel.get('Id') == rid:
                target = rel.get('Target')
        slide_root = etree.fromstring(parts[f'ppt/{target}'])
        bg = slide_root.find('.//p:cSld/p:bg', NS)
        self.assertIsNotNone(bg, "Background should be preserved")

    def test_image_relation_preserved(self):
        """Image relationships in slide rels are preserved."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'Has Image Rel'},
                    {'shape_id': 12, 'text': 'Body'},
                ],
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path))

        # Check that output slide rels still has image relationship
        parts = read_zip_parts(str(self.output_path))
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        pres_rels = etree.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        r_ns = NS['r']
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        rid = sld_id_lst.findall('p:sldId', NS)[0].get(f'{{{r_ns}}}id')
        target = None
        for rel in pres_rels.findall('rel:Relationship', NS):
            if rel.get('Id') == rid:
                target = rel.get('Target')
        slide_path = f'ppt/{target}'
        rels_path = slide_path.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels'

        self.assertIn(rels_path, parts)
        rels_root = etree.fromstring(parts[rels_path])
        image_rels = [r for r in rels_root.findall('rel:Relationship', NS)
                      if 'image' in r.get('Type', '')]
        self.assertTrue(len(image_rels) > 0, "Image relationship should be preserved")

        # Media file should still exist
        self.assertIn('ppt/media/image1.png', parts)

    def test_shape_id_not_found_fails(self):
        """Referencing a non-existent shape_id causes hard fail."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [{'shape_id': 999, 'text': 'No such shape'}],
            }]
        }
        with self.assertRaises(FillError) as ctx:
            fill_template(str(self.template_path), data, str(self.output_path))
        self.assertIn('999', str(ctx.exception))
        self.assertIn('not found', str(ctx.exception))

    def test_shape_no_textbody_fails(self):
        """Editing a shape without txBody causes hard fail."""
        # Build a template with a picture shape (no txBody)
        # For simplicity, use the existing template and target the group shape root (id=1)
        # which typically has no txBody
        # Actually, let's create a specific test case
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [{'shape_id': 13, 'text': 'No textbody here'}],
            }]
        }
        with self.assertRaises(FillError) as ctx:
            fill_template(str(self.template_path), data, str(self.output_path))
        self.assertIn('no text body', str(ctx.exception).lower())

    def test_clear_shape_ids(self):
        """clear_shape_ids clears text from specified shapes."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [{'shape_id': 11, 'text': 'Kept Title'}],
                'clear_shape_ids': [12],
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path),
                               allow_warnings=True)

        # Check body text is cleared
        parts = read_zip_parts(str(self.output_path))
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        pres_rels = etree.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        r_ns = NS['r']
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        rid = sld_id_lst.findall('p:sldId', NS)[0].get(f'{{{r_ns}}}id')
        target = None
        for rel in pres_rels.findall('rel:Relationship', NS):
            if rel.get('Id') == rid:
                target = rel.get('Target')
        slide_root = etree.fromstring(parts[f'ppt/{target}'])
        sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
        shape = find_shape_by_id(sp_tree, 12)
        txbody = _find_txbody(shape)
        text = get_txbody_text(txbody)
        self.assertEqual(text.strip(), '')

    def test_require_all_edits_fails(self):
        """require_all_edits=true with unedited shapes causes fail."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [{'shape_id': 11, 'text': 'Only title'}],
                'editable_shape_ids': [11, 12],
                'require_all_edits': True,
            }]
        }
        with self.assertRaises(FillError) as ctx:
            fill_template(str(self.template_path), data, str(self.output_path))
        self.assertIn('12', str(ctx.exception))

    def test_require_all_edits_passes_with_clear(self):
        """require_all_edits passes when all shapes edited or cleared."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [{'shape_id': 11, 'text': 'Title'}],
                'clear_shape_ids': [12],
                'editable_shape_ids': [11, 12],
                'require_all_edits': True,
            }]
        }
        # Should not raise - forbidden text warning will be in allow mode
        result = fill_template(str(self.template_path), data, str(self.output_path),
                               allow_warnings=True)
        self.assertEqual(result['slide_count'], 1)

    def test_forbidden_text_detection(self):
        """Forbidden placeholder text causes hard fail by default."""
        # Don't edit the body which has "Sample text body" (matches "Sample text" pattern)
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [{'shape_id': 11, 'text': 'Good Title'}],
                # shape 12 still has "Sample text body 1"
            }]
        }
        with self.assertRaises(FillError) as ctx:
            fill_template(str(self.template_path), data, str(self.output_path))
        self.assertIn('forbidden', str(ctx.exception).lower())

    def test_forbidden_text_custom_pattern(self):
        """Custom forbidden patterns are detected."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'ACME Corp Title'},
                    {'shape_id': 12, 'text': 'Content with DRAFT marker'},
                ],
            }],
            'forbidden_text_patterns': ['DRAFT'],
        }
        with self.assertRaises(FillError) as ctx:
            fill_template(str(self.template_path), data, str(self.output_path))
        self.assertIn('DRAFT', str(ctx.exception))

    def test_legacy_replacements_exact_match(self):
        """Legacy replacements with exact single match works."""
        data = {
            'slides': [{
                'source_slide': 0,
                'replacements': {
                    'Please Enter Title 1': 'Real Title',
                    'Sample text body 1': 'Real body content',
                },
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path),
                               allow_warnings=True)
        self.assertEqual(result['slide_count'], 1)

    def test_legacy_replacements_zero_match_fails(self):
        """Legacy replacements with 0 matches causes fail."""
        data = {
            'slides': [{
                'source_slide': 0,
                'replacements': {
                    'This text does not exist anywhere': 'New text',
                },
            }]
        }
        with self.assertRaises(FillError) as ctx:
            fill_template(str(self.template_path), data, str(self.output_path))
        self.assertIn('matched 0', str(ctx.exception))

    def test_paragraphs_format(self):
        """Paragraphs array edit produces multiple paragraphs."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'Title'},
                    {'shape_id': 12, 'paragraphs': [
                        {'text': 'Line 1', 'bold': True},
                        {'text': 'Line 2', 'size': 16},
                        {'text': 'Line 3', 'color': 'FF0000'},
                    ]},
                ],
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path),
                               allow_warnings=True)

        # Check paragraph count
        parts = read_zip_parts(str(self.output_path))
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        pres_rels = etree.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        r_ns = NS['r']
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        rid = sld_id_lst.findall('p:sldId', NS)[0].get(f'{{{r_ns}}}id')
        target = None
        for rel in pres_rels.findall('rel:Relationship', NS):
            if rel.get('Id') == rid:
                target = rel.get('Target')
        slide_root = etree.fromstring(parts[f'ppt/{target}'])
        sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
        shape = find_shape_by_id(sp_tree, 12)
        txbody = _find_txbody(shape)
        paras = txbody.findall('a:p', NS)
        self.assertEqual(len(paras), 3)

    def test_newline_in_text_splits_paragraphs(self):
        """Newline in text string creates multiple paragraphs."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'Title'},
                    {'shape_id': 12, 'text': 'Line A\nLine B\nLine C'},
                ],
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path),
                               allow_warnings=True)

        parts = read_zip_parts(str(self.output_path))
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        pres_rels = etree.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        r_ns = NS['r']
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        rid = sld_id_lst.findall('p:sldId', NS)[0].get(f'{{{r_ns}}}id')
        target = None
        for rel in pres_rels.findall('rel:Relationship', NS):
            if rel.get('Id') == rid:
                target = rel.get('Target')
        slide_root = etree.fromstring(parts[f'ppt/{target}'])
        sp_tree = slide_root.find('.//p:cSld/p:spTree', NS)
        shape = find_shape_by_id(sp_tree, 12)
        txbody = _find_txbody(shape)
        paras = txbody.findall('a:p', NS)
        self.assertEqual(len(paras), 3)

    def test_source_slide_out_of_range(self):
        """source_slide out of range causes error."""
        data = {
            'slides': [{'source_slide': 99, 'edits': []}]
        }
        with self.assertRaises(FillError):
            fill_template(str(self.template_path), data, str(self.output_path))

    def test_allow_warnings_mode(self):
        """--allow-warnings downgrades errors to warnings."""
        data = {
            'slides': [{
                'source_slide': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'Title'},
                    {'shape_id': 999, 'text': 'No such shape'},  # Would normally fail
                ],
            }]
        }
        # Should not raise with allow_warnings=True
        result = fill_template(str(self.template_path), data, str(self.output_path),
                               allow_warnings=True)
        self.assertEqual(result['slide_count'], 1)

    def test_notes_slide_removed(self):
        """notesSlide relationships are removed from copied slide rels."""
        # Build template with notes relationship
        template_with_notes = Path(self.tmpdir) / 'template_notes.pptx'
        build_minimal_pptx(template_with_notes, num_slides=1)

        # Manually add a notes rel to slide1 rels
        parts = {}
        with zipfile.ZipFile(str(template_with_notes), 'r') as zf:
            for name in zf.namelist():
                parts[name] = zf.read(name)

        # Add notes relationship to slide1.xml.rels
        rels_path = 'ppt/slides/_rels/slide1.xml.rels'
        rels_root = etree.fromstring(parts[rels_path])
        rel_ns_uri = 'http://schemas.openxmlformats.org/package/2006/relationships'
        notes_rel = etree.SubElement(rels_root, f'{{{rel_ns_uri}}}Relationship')
        notes_rel.set('Id', 'rId99')
        notes_rel.set('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide')
        notes_rel.set('Target', '../notesSlides/notesSlide1.xml')
        parts[rels_path] = etree.tostring(rels_root, xml_declaration=True, encoding='UTF-8')

        # Rewrite template
        with zipfile.ZipFile(str(template_with_notes), 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in parts.items():
                zf.writestr(name, content)

        # Fill
        data = {'slides': [{'source_slide': 0, 'edits': [{'shape_id': 11, 'text': 'No Notes'}]}]}
        output = Path(self.tmpdir) / 'output_notes.pptx'
        fill_template(str(template_with_notes), data, str(output), allow_warnings=True)

        # Verify notes rel is gone
        out_parts = read_zip_parts(str(output))
        pres_root = etree.fromstring(out_parts['ppt/presentation.xml'])
        pres_rels = etree.fromstring(out_parts['ppt/_rels/presentation.xml.rels'])
        r_ns = NS['r']
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        rid = sld_id_lst.findall('p:sldId', NS)[0].get(f'{{{r_ns}}}id')
        target = None
        for rel in pres_rels.findall('rel:Relationship', NS):
            if rel.get('Id') == rid:
                target = rel.get('Target')
        slide_rels_path = f'ppt/{target}'.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels'
        if slide_rels_path in out_parts:
            rels_root = etree.fromstring(out_parts[slide_rels_path])
            for rel in rels_root.findall('rel:Relationship', NS):
                self.assertNotIn('notesSlide', rel.get('Type', ''))

    def test_content_types_updated(self):
        """[Content_Types].xml has overrides for all output slides."""
        data = {
            'slides': [
                {'source_slide': 0, 'edits': [{'shape_id': 11, 'text': 'S1'}]},
                {'source_slide': 1, 'edits': [{'shape_id': 21, 'text': 'S2'}]},
            ]
        }
        fill_template(str(self.template_path), data, str(self.output_path), allow_warnings=True)

        parts = read_zip_parts(str(self.output_path))
        ct_root = etree.fromstring(parts['[Content_Types].xml'])
        ct_ns = 'http://schemas.openxmlformats.org/package/2006/content-types'
        overrides = [o.get('PartName') for o in ct_root.findall(f'{{{ct_ns}}}Override')]
        slide_overrides = [o for o in overrides if '/ppt/slides/slide' in o]
        # 2 source slide parts remain as the design palette + 2 new output slide parts.
        self.assertEqual(len(slide_overrides), 4)
        self.assertIn('/ppt/slides/slide1.xml', slide_overrides)
        self.assertIn('/ppt/slides/slide2.xml', slide_overrides)


class TestValidatePptx(unittest.TestCase):
    """Test validate_pptx.py functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.template_path = Path(self.tmpdir) / 'template.pptx'
        build_minimal_pptx(self.template_path, num_slides=2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_template_passes(self):
        """A structurally valid output with real content passes validation."""
        output_path = Path(self.tmpdir) / 'clean-output.pptx'
        data = {
            'slides': [
                {'source_slide': 0, 'edits': [
                    {'shape_id': 11, 'text': 'Real Title 1'},
                    {'shape_id': 12, 'text': 'Real Body 1'},
                ]},
                {'source_slide': 1, 'edits': [
                    {'shape_id': 21, 'text': 'Real Title 2'},
                    {'shape_id': 22, 'text': 'Real Body 2'},
                ]},
            ]
        }
        fill_template(str(self.template_path), data, str(output_path), allow_warnings=True)
        result = validate_pptx(str(output_path))
        self.assertTrue(result.valid, f"Errors: {result.errors}")

    def test_valid_fill_output_passes(self):
        """Output from fill_template passes validation."""
        output_path = Path(self.tmpdir) / 'output.pptx'
        data = {
            'slides': [
                {'source_slide': 0, 'edits': [
                    {'shape_id': 11, 'text': 'Real Title'},
                    {'shape_id': 12, 'text': 'Real Body'},
                ]},
            ]
        }
        fill_template(str(self.template_path), data, str(output_path), allow_warnings=True)
        result = validate_pptx(str(output_path))
        self.assertTrue(result.valid, f"Errors: {result.errors}")

    def test_corrupted_zip_fails(self):
        """Corrupted ZIP is detected."""
        bad_path = Path(self.tmpdir) / 'bad.pptx'
        bad_path.write_bytes(b'not a zip file')
        result = validate_pptx(str(bad_path))
        self.assertFalse(result.valid)

    def test_missing_slide_part_fails(self):
        """Missing slide part referenced by presentation fails."""
        # Read template, remove a slide file, rewrite
        parts = {}
        with zipfile.ZipFile(str(self.template_path), 'r') as zf:
            for name in zf.namelist():
                parts[name] = zf.read(name)

        # Remove slide2.xml
        del parts['ppt/slides/slide2.xml']

        broken_path = Path(self.tmpdir) / 'broken.pptx'
        with zipfile.ZipFile(str(broken_path), 'w') as zf:
            for name, content in parts.items():
                zf.writestr(name, content)

        result = validate_pptx(str(broken_path))
        self.assertFalse(result.valid)
        self.assertTrue(any('slide2' in e for e in result.errors))

    def test_missing_content_type_override_fails(self):
        """Missing [Content_Types] override for a slide fails."""
        parts = {}
        with zipfile.ZipFile(str(self.template_path), 'r') as zf:
            for name in zf.namelist():
                parts[name] = zf.read(name)

        # Remove slide2 override from content types
        ct_root = etree.fromstring(parts['[Content_Types].xml'])
        ct_ns = 'http://schemas.openxmlformats.org/package/2006/content-types'
        for override in list(ct_root.findall(f'{{{ct_ns}}}Override')):
            if 'slide2' in override.get('PartName', ''):
                ct_root.remove(override)
        parts['[Content_Types].xml'] = etree.tostring(ct_root, xml_declaration=True, encoding='UTF-8')

        broken_path = Path(self.tmpdir) / 'broken_ct.pptx'
        with zipfile.ZipFile(str(broken_path), 'w') as zf:
            for name, content in parts.items():
                zf.writestr(name, content)

        result = validate_pptx(str(broken_path))
        self.assertFalse(result.valid)
        self.assertTrue(any('Content_Types' in e for e in result.errors))

    def test_template_comparison(self):
        """Template comparison reports slide count and media preservation."""
        output_path = Path(self.tmpdir) / 'output.pptx'
        data = {
            'slides': [
                {'source_slide': 0, 'edits': [
                    {'shape_id': 11, 'text': 'Title'},
                    {'shape_id': 12, 'text': 'Body'},
                ]},
            ]
        }
        fill_template(str(self.template_path), data, str(output_path), allow_warnings=True)

        result = validate_pptx(str(output_path), template_path=str(self.template_path))
        self.assertTrue(result.valid)
        self.assertIn('template_slide_count', result.info)
        self.assertEqual(result.info['template_slide_count'], 2)
        self.assertEqual(result.info['slide_count'], 1)
        self.assertTrue(result.info.get('all_media_preserved', False))

    def test_forbidden_text_fails_validation(self):
        """Forbidden placeholder text makes validation fail."""
        # The template itself has "Please Enter" and "Sample text".
        result = validate_pptx(str(self.template_path))
        self.assertFalse(result.valid)
        self.assertTrue(any('forbidden text pattern' in error for error in result.errors))


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.template_path = Path(self.tmpdir) / 'template.pptx'
        self.output_path = Path(self.tmpdir) / 'output.pptx'
        build_minimal_pptx(self.template_path, num_slides=2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_slides_array_fails(self):
        """Empty slides array causes error."""
        data = {'slides': []}
        with self.assertRaises(FillError):
            fill_template(str(self.template_path), data, str(self.output_path))

    def test_missing_source_slide_field_fails(self):
        """Missing source_slide/duplicate_from causes error."""
        data = {'slides': [{'edits': []}]}
        with self.assertRaises(FillError):
            fill_template(str(self.template_path), data, str(self.output_path))

    def test_duplicate_from_legacy_compat(self):
        """duplicate_from is accepted as alias for source_slide."""
        data = {
            'slides': [{
                'duplicate_from': 0,
                'edits': [
                    {'shape_id': 11, 'text': 'Via Legacy'},
                    {'shape_id': 12, 'text': 'Body'},
                ],
            }]
        }
        result = fill_template(str(self.template_path), data, str(self.output_path),
                               allow_warnings=True)
        self.assertEqual(result['slide_count'], 1)

    def test_presentation_only_references_output_slides(self):
        """Output presentation.xml only references the generated slides, not template sources."""
        data = {
            'slides': [
                {'source_slide': 0, 'edits': [
                    {'shape_id': 11, 'text': 'Only Me'},
                    {'shape_id': 12, 'text': 'And Me'},
                ]},
            ]
        }
        fill_template(str(self.template_path), data, str(self.output_path), allow_warnings=True)

        parts = read_zip_parts(str(self.output_path))
        pres_root = etree.fromstring(parts['ppt/presentation.xml'])
        sld_id_lst = pres_root.find('p:sldIdLst', NS)
        sld_ids = sld_id_lst.findall('p:sldId', NS)
        # Should only have 1 slide (not the 2 template slides)
        self.assertEqual(len(sld_ids), 1)

    def test_non_slide_rels_preserved(self):
        """Non-slide relationships in presentation.xml.rels are preserved."""
        data = {
            'slides': [{'source_slide': 0, 'edits': [
                {'shape_id': 11, 'text': 'T'}, {'shape_id': 12, 'text': 'B'}
            ]}]
        }
        fill_template(str(self.template_path), data, str(self.output_path), allow_warnings=True)

        parts = read_zip_parts(str(self.output_path))
        pres_rels = etree.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        all_rels = pres_rels.findall('rel:Relationship', NS)

        # Should have: 1 slideMaster + 1 theme + 1 new slide = 3
        types = [r.get('Type', '') for r in all_rels]
        master_rels = [t for t in types if 'slideMaster' in t]
        theme_rels = [t for t in types if 'theme' in t]
        slide_rels = [t for t in types if t.endswith('/slide')]

        self.assertEqual(len(master_rels), 1, "slideMaster rel preserved")
        self.assertEqual(len(theme_rels), 1, "theme rel preserved")
        self.assertEqual(len(slide_rels), 1, "exactly 1 output slide rel")


if __name__ == '__main__':
    unittest.main(verbosity=2)
