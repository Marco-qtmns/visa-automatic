from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pymupdf as fitz


ROOT = Path(__file__).resolve().parents[1]

FILES = [
    ROOT / "templates" / "canada" / "IMM5257.pdf",
    ROOT / "templates" / "canada" / "IMM5707.pdf",
    ROOT / "templates" / "canada" / "IMM5476.pdf",
]


def xref_number(value: str) -> int | None:
    match = re.search(r"(\d+)\s+\d+\s+R", value or "")
    return int(match.group(1)) if match else None


def xfa_refs(doc: fitz.Document) -> list[int]:
    catalog = doc.pdf_catalog()

    kind, value = doc.xref_get_key(catalog, "AcroForm")
    if kind != "xref":
        return []

    acroform = xref_number(value)
    if acroform is None:
        return []

    kind, value = doc.xref_get_key(acroform, "XFA")
    if kind != "array":
        return []

    return [
        int(x)
        for x in re.findall(r"(\d+)\s+\d+\s+R", value)
    ]


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def inspect(path: Path) -> None:
    print()
    print("=" * 80)
    print(path.name)
    print("=" * 80)

    if not path.exists():
        print("MISSING FILE")
        return

    doc = fitz.open(path)

    widgets = []

    for page_number, page in enumerate(doc, start=1):
        for widget in page.widgets() or []:
            widgets.append(
                (
                    page_number,
                    widget.field_name,
                    widget.field_type_string,
                    widget.field_value,
                )
            )

    print(f"Pages: {doc.page_count}")
    print(f"AcroForm widgets: {len(widgets)}")

    if widgets:
        print("\nAcroForm fields:")
        for page, name, kind, value in widgets:
            print(
                f"  p{page}: {name} "
                f"[{kind}] = {value!r}"
            )

    refs = xfa_refs(doc)

    print(f"\nXFA stream references: {refs}")

    all_fields: list[str] = []
    all_groups: list[str] = []

    for ref in refs:
        try:
            data = doc.xref_stream(ref)
        except Exception:
            continue

        if not data:
            continue

        xml = data.decode("utf-8", errors="ignore")

        if "<" not in xml:
            continue

        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            continue

        fields = []
        groups = []

        for element in root.iter():
            tag = local_tag(element.tag)
            name = element.attrib.get("name", "").strip()

            if not name:
                continue

            if tag == "field":
                fields.append(name)

            elif tag == "exclGroup":
                groups.append(name)

        if fields or groups:
            print(f"\nXFA object {ref}:")

            if fields:
                print(f"  Fields: {len(fields)}")
                for name in fields:
                    print(f"    FIELD {name}")

            if groups:
                print(f"  Exclusive groups: {len(groups)}")
                for name in groups:
                    print(f"    GROUP {name}")

            all_fields.extend(fields)
            all_groups.extend(groups)

    print("\nUnique XFA field names:")
    counts = Counter(all_fields)

    for name in sorted(counts):
        print(f"  {name} ({counts[name]})")

    print("\nUnique exclusive groups:")
    counts = Counter(all_groups)

    for name in sorted(counts):
        print(f"  {name} ({counts[name]})")


def main() -> None:
    for path in FILES:
        inspect(path)


if __name__ == "__main__":
    main()
