from __future__ import annotations

from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"

NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_DC = "http://purl.org/dc/elements/1.1/"

ET.register_namespace("x", NS_X)
ET.register_namespace("rdf", NS_RDF)
ET.register_namespace("dc", NS_DC)


def _build_xmp_with_subject(person_name: str) -> bytes:
    xmpmeta = ET.Element(f"{{{NS_X}}}xmpmeta")
    rdf_root = ET.SubElement(xmpmeta, f"{{{NS_RDF}}}RDF")
    desc = ET.SubElement(rdf_root, f"{{{NS_RDF}}}Description")
    subject = ET.SubElement(desc, f"{{{NS_DC}}}subject")
    bag = ET.SubElement(subject, f"{{{NS_RDF}}}Bag")
    li = ET.SubElement(bag, f"{{{NS_RDF}}}li")
    li.text = person_name
    return ET.tostring(xmpmeta, encoding="utf-8", xml_declaration=False)


def _add_subject_to_existing_xmp(xml_bytes: bytes, person_name: str) -> tuple[bytes, bool]:
    text = xml_bytes.decode("utf-8", errors="replace")
    root = ET.fromstring(text)

    desc = root.find(f".//{{{NS_RDF}}}Description")
    if desc is None:
        rdf_root = root.find(f".//{{{NS_RDF}}}RDF")
        if rdf_root is None:
            raise ValueError("Invalid XMP: missing rdf:RDF")
        desc = ET.SubElement(rdf_root, f"{{{NS_RDF}}}Description")

    subject = desc.find(f"{{{NS_DC}}}subject")
    if subject is None:
        subject = ET.SubElement(desc, f"{{{NS_DC}}}subject")

    bag = subject.find(f"{{{NS_RDF}}}Bag")
    if bag is None:
        bag = ET.SubElement(subject, f"{{{NS_RDF}}}Bag")

    existing = {(li.text or "").strip() for li in bag.findall(f"{{{NS_RDF}}}li")}
    if person_name in existing:
        return xml_bytes, False

    li = ET.SubElement(bag, f"{{{NS_RDF}}}li")
    li.text = person_name
    return ET.tostring(root, encoding="utf-8", xml_declaration=False), True


def _find_jpeg_xmp_segment(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[0:2] != b"\xFF\xD8":
        return None

    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        j = i + 1
        while j < len(data) and data[j] == 0xFF:
            j += 1
        if j >= len(data):
            return None
        marker = data[j]
        marker_pos = j - 1
        if marker == 0xDA:
            return None
        if marker in (0xD8, 0xD9):
            i = j + 1
            continue
        if j + 2 >= len(data):
            return None
        seg_len = (data[j + 1] << 8) | data[j + 2]
        seg_end = marker_pos + 2 + seg_len
        if seg_end > len(data) or seg_len < 2:
            return None
        payload_start = j + 3
        payload_end = marker_pos + 2 + seg_len
        payload = data[payload_start:payload_end]
        if marker == 0xE1 and payload.startswith(XMP_HEADER):
            return marker_pos, seg_end
        i = seg_end
    return None


def _find_jpeg_insert_pos(data: bytes) -> int:
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        j = i + 1
        while j < len(data) and data[j] == 0xFF:
            j += 1
        if j >= len(data):
            return len(data)
        marker = data[j]
        marker_pos = j - 1
        if marker == 0xDA:
            return marker_pos
        if marker in (0xD8, 0xD9):
            i = j + 1
            continue
        if j + 2 >= len(data):
            return len(data)
        seg_len = (data[j + 1] << 8) | data[j + 2]
        seg_end = marker_pos + 2 + seg_len
        if seg_end > len(data) or seg_len < 2:
            return len(data)
        i = seg_end
    return len(data)


def _build_app1_xmp_segment(xml_bytes: bytes) -> bytes:
    payload = XMP_HEADER + xml_bytes
    seg_len = len(payload) + 2
    if seg_len > 65535:
        raise ValueError("XMP payload too large for JPEG APP1 segment")
    return b"\xFF\xE1" + seg_len.to_bytes(2, "big") + payload


def ensure_person_name_in_xmp(image_path: str, person_name: str) -> str:
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        return "skipped_missing"

    try:
        data = path.read_bytes()
    except Exception:
        return "error"

    if len(data) < 4 or data[0:2] != b"\xFF\xD8":
        return "skipped_unsupported"

    try:
        xmp_span = _find_jpeg_xmp_segment(data)
        if xmp_span is None:
            xml_bytes = _build_xmp_with_subject(person_name)
            seg = _build_app1_xmp_segment(xml_bytes)
            insert_pos = _find_jpeg_insert_pos(data)
            out = data[:insert_pos] + seg + data[insert_pos:]
            changed = True
        else:
            start, end = xmp_span
            old_seg = data[start:end]
            payload = old_seg[4:]
            xml_old = payload[len(XMP_HEADER):]
            xml_new, changed = _add_subject_to_existing_xmp(xml_old, person_name)
            if changed:
                new_seg = _build_app1_xmp_segment(xml_new)
                out = data[:start] + new_seg + data[end:]
            else:
                out = data

        if not changed:
            return "already_present"

        with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix, dir=str(path.parent)) as tmp:
            tmp.write(out)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
        return "tagged"
    except Exception:
        return "error"


def remove_person_name_from_xmp(image_path: str, person_name: str) -> str:
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        return "skipped_missing"

    try:
        data = path.read_bytes()
    except Exception:
        return "error"

    if len(data) < 4 or data[0:2] != b"\xFF\xD8":
        return "skipped_unsupported"

    try:
        xmp_span = _find_jpeg_xmp_segment(data)
        if xmp_span is None:
            return "not_found"

        start, end = xmp_span
        old_seg = data[start:end]
        payload = old_seg[4:]
        xml_old = payload[len(XMP_HEADER):]
        text = xml_old.decode("utf-8", errors="replace")
        root = ET.fromstring(text)

        changed = False
        for bag in root.findall(f".//{{{NS_DC}}}subject/{{{NS_RDF}}}Bag"):
            for li in list(bag.findall(f"{{{NS_RDF}}}li")):
                if (li.text or "").strip() == person_name:
                    bag.remove(li)
                    changed = True

        if not changed:
            return "not_found"

        xml_new = ET.tostring(root, encoding="utf-8", xml_declaration=False)
        new_seg = _build_app1_xmp_segment(xml_new)
        out = data[:start] + new_seg + data[end:]

        with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix, dir=str(path.parent)) as tmp:
            tmp.write(out)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
        return "removed"
    except Exception:
        return "error"

