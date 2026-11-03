from xml.etree import ElementTree as ET


def serialize(value, root="response"):
    node = ET.Element(root)
    if isinstance(value, list):
        for item in value:
            node.append(ET.fromstring(serialize(item, "item")))
    elif isinstance(value, dict):
        for key, item in value.items():
            child = ET.SubElement(node, key)
            if item is None:
                child.set("null", "true")
            else:
                child.text = str(item)
    return ET.tostring(node, encoding="utf-8", xml_declaration=True)


def parse(body):
    if b"<!" in body:
        raise ValueError("XML declarations and entities are not allowed")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise ValueError("Malformed XML") from error
    values = {child.tag: child.text or "" for child in root}
    if len(values) != len(root) or any(len(child) for child in root):
        raise ValueError("Expected distinct flat XML fields")
    return values
