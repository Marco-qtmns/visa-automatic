"""Read-only, deterministic XFA/AcroForm inventory; never saves an input PDF.

XML locators use namespace-qualified tags and 1-based sibling indexes (same tag).
Named paths use zero-based sibling indexes (same tag and name). They describe
prototype nodes, not runtime repeat instances. No values/defaults are exported.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]


def inventory(path: Path) -> dict:
    result = {'file': f'templates/canada/{path.name}',
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'packets': [], 'fields': [], 'widgets': []}
    with fitz.open(path) as doc:
        result['pages'] = len(doc)
        kind, value = doc.xref_get_key(doc.pdf_catalog(), 'AcroForm/XFA')
        if kind == 'array':
            refs = [(name, int(ref)) for name, ref in
                    re.findall(r'\(([^)]*)\)\s*(\d+)\s+\d+\s+R', value)]
        elif kind == 'xref':
            refs = [('xdp', int(value.split()[0]))]
        elif kind == 'null':
            refs = []
        else:
            raise ValueError(f'Unsupported XFA object {kind} in {path.name}')
        for packet_index, (packet, xref) in enumerate(refs):
            data = doc.xref_stream(xref)
            metadata = {'name': packet, 'index': packet_index, 'xref': xref,
                        'sha256': hashlib.sha256(data).hexdigest()}
            result['packets'].append(metadata)
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                metadata['xml_parseable'] = False
                continue
            metadata['xml_parseable'] = True

            def walk(node, xml_path, named_path):
                tag = node.tag.rsplit('}', 1)[-1]
                if tag in ('field', 'exclGroup'):
                    caption = node.find('./{*}caption')
                    assist = node.find('./{*}assist')
                    items = [' '.join(n.itertext()).strip()
                             for n in node.findall('./{*}items')]
                    result['fields'].append({
                        'packet': packet, 'packet_index': packet_index,
                        'packet_sha256': metadata['sha256'], 'kind': tag,
                        'name': node.get('name'), 'named_path': named_path,
                        'xml_path': xml_path,
                        'caption': ' '.join(caption.itertext()).strip() if caption is not None else '',
                        'assist': ' '.join(assist.itertext()).strip() if assist is not None else '',
                        'items': items,
                    })
                tags, names = defaultdict(int), defaultdict(int)
                for child in node:
                    if not isinstance(child.tag, str):
                        continue
                    tags[child.tag] += 1
                    local = child.tag.rsplit('}', 1)[-1]
                    name = child.get('name', '#' + local)
                    key = (child.tag, name)
                    index = names[key]; names[key] += 1
                    walk(child, xml_path + [{'tag': child.tag, 'index': tags[child.tag]}],
                         named_path + '/' + name + f'[{index}]')
            walk(root, [{'tag': root.tag, 'index': 1}], root.get('name', '#'+root.tag.rsplit('}',1)[-1])+'[0]')
        for page_no, page in enumerate(doc, 1):
            for widget in page.widgets() or []:
                result['widgets'].append({'page': page_no, 'xref': widget.xref,
                    'field_name': widget.field_name, 'type': widget.field_type_string})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = {name: inventory(ROOT / 'templates/canada' / f'{name}.pdf')
            for name in ('IMM5257', 'IMM5707', 'IMM5476')}
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
