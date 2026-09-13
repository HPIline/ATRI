"""Conservative manufacturing package from the same solids as the assembly.

Exported meshes and drawings remain review artifacts until the assembly and
manufacturing holds are resolved. A supplied side_flat is a stock-angle cutting
template, never an unfolded sheet-metal blank. No nesting or kerf is applied.
"""
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import Counter
import json
import re
import zipfile

import cadquery as cq

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PRINTABLE = {"petg", "tpu"}
MATERIALS = {"petg": "PETG", "tpu": "TPU", "al": "aluminum; alloy/temper require source metadata"}
GEOMETRY_KEYS = {"wp", "flat", "side_flat", "output_flat"}


def _shape(value, name):
    values = value.vals() if isinstance(value, cq.Workplane) else [value]
    solids = []
    for part in values:
        if not isinstance(part, (cq.Solid, cq.Compound)) or not part.isValid():
            raise ValueError(f"Invalid or non-solid geometry: {name}")
        children = part.Solids()
        if not children or any(not s.isValid() or s.Volume() <= 0 for s in children):
            raise ValueError(f"Invalid solid geometry: {name}")
        solids.extend(children)
    if not solids:
        raise ValueError(f"Missing solid geometry: {name}")
    return cq.Compound.makeCompound(solids)


def orient_for_print(shape, face):
    """Turn the explicit outward face normal toward -Z, then place on Z=0."""
    rotations = {"+X": ((0, 1, 0), 90), "-X": ((0, 1, 0), -90),
                 "+Y": ((1, 0, 0), -90), "-Y": ((1, 0, 0), 90),
                 "+Z": ((1, 0, 0), 180), "-Z": ((1, 0, 0), 0)}
    if face not in rotations:
        raise ValueError(f"Unsupported print_face: {face!r}")
    axis, angle = rotations[face]
    turned = shape.rotate((0, 0, 0), axis, angle)
    return turned.translate((0, 0, -turned.BoundingBox().zmin))


def _xml(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def write_3mf(shape, filename, tolerance=0.05):
    """One object per solid, preserving all coordinates in explicit millimeters."""
    model = ET.Element("model", {"xmlns": CORE, "unit": "millimeter"})
    resources = ET.SubElement(model, "resources")
    build = ET.SubElement(model, "build")
    for number, solid in enumerate(shape.Solids(), 1):
        points, faces = solid.tessellate(tolerance, 0.1)
        if not points or not faces:
            raise ValueError(f"Empty tessellation in {filename}, solid {number}")
        # OCC tessellates faces separately; weld their common edge vertices so
        # the 3MF has a closed indexed surface, not disconnected face islands.
        unique, indices, lookup = [], [], {}
        for point in points:
            coordinates = point.toTuple()
            key = tuple(round(v, 8) for v in coordinates)
            if key not in lookup:
                lookup[key] = len(unique)
                unique.append(coordinates)
            indices.append(lookup[key])
        faces = [tuple(indices[v] for v in triangle) for triangle in faces]
        edges = Counter()
        directed = Counter()
        for triangle in faces:
            if len(set(triangle)) != 3:
                raise ValueError(f"Degenerate 3MF triangle: {filename}, solid {number}")
            for a, b in zip(triangle, triangle[1:]+triangle[:1]):
                edges[tuple(sorted((a, b)))] += 1
                directed[(a, b)] += 1
        if any(count != 2 for count in edges.values()) or any(
                directed[(a, b)] != directed[(b, a)] for a, b in edges):
            raise ValueError(f"Non-manifold or inconsistently wound 3MF: {filename}, solid {number}")
        obj = ET.SubElement(resources, "object", {"id": str(number), "type": "model"})
        mesh = ET.SubElement(obj, "mesh")
        vertices = ET.SubElement(mesh, "vertices")
        triangles = ET.SubElement(mesh, "triangles")
        for coordinates in unique:
            ET.SubElement(vertices, "vertex", {a: format(v, ".12g") for a, v in zip("xyz", coordinates)})
        for triangle in faces:
            ET.SubElement(triangles, "triangle", {f"v{i+1}": str(v) for i, v in enumerate(triangle)})
        ET.SubElement(build, "item", {"objectid": str(number)})
    types = ET.Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
    ET.SubElement(types, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    ET.SubElement(types, "Default", {"Extension": "model", "ContentType": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"})
    relationships = ET.Element("Relationships", {"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"})
    ET.SubElement(relationships, "Relationship", {"Id": "rel0", "Target": "/3D/3dmodel.model",
        "Type": "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"})
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _xml(types))
        archive.writestr("_rels/.rels", _xml(relationships))
        archive.writestr("3D/3dmodel.model", _xml(model))


def _profile_face(flat):
    """Require a straight extrusion: a countersunk solid is not a laser blank."""
    bb = flat.BoundingBox()
    bottoms = [f for f in flat.Faces() if f.geomType() == "PLANE"
               and abs(f.Center().z - bb.zmin) < 1e-6
               and abs(abs(f.normalAt().z) - 1) < 1e-6]
    if not bottoms:
        return None
    section = cq.Compound.makeCompound(bottoms)
    zmin = min(f.Center().z for f in bottoms)
    tops = [f for f in flat.Faces() if f.geomType() == "PLANE"
            and abs(f.Center().z-bb.zmax) < 1e-6
            and abs(abs(f.normalAt().z)-1) < 1e-6]
    if not tops:
        return None
    thickness = max(f.Center().z for f in tops)-zmin
    extrusion = cq.Compound.makeCompound([
        cq.Solid.extrudeLinear(f.outerWire(), f.innerWires(), (0, 0, thickness))
        for f in bottoms])
    # Equal total volumes alone cannot detect a pocket paired with a protrusion.
    common = flat.intersect(extrusion).Volume()
    if abs(flat.Volume()-common) > 1e-5 or abs(extrusion.Volume()-common) > 1e-5:
        return None
    return section.translate((0, 0, -zmin))


def export_manufacturing(items, folder):
    """Export every item or reject the package; never imply gate closure.

    Missing orientation retains an assembly-coordinate review STL but produces
no print-ready file. The caller must use a fresh output directory, preventing
    obsolete part files from surviving a model revision.
    """
    items = list(items)
    names = [item["name"] for item in items]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate part names")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", n) or n in {".", ".."} for n in names):
        raise ValueError("Part names must be safe individual filenames")
    prepared = []
    for item in items:
        shape = _shape(item["wp"], item["name"])
        metadata = {k: v for k, v in item.items() if k not in GEOMETRY_KEYS}
        json.dumps(metadata, allow_nan=False)
        auxiliary = {k: _shape(item[k], item["name"]+":"+k) for k in ("flat", "side_flat") if k in item}
        if item.get("print_face") is not None:
            orient_for_print(shape, item["print_face"])
        prepared.append((item, shape, metadata, auxiliary))
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise ValueError(f"Manufacturing directory must be empty: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for item, shape, metadata, auxiliary in prepared:
        name, kind = item["name"], item["kind"]
        row = dict(name=name, link=item["link"], kind=kind, quantity=1,
                   volume_mm3=shape.Volume(), solid_count=len(shape.Solids()),
                   material=item.get("material", MATERIALS.get(kind, "purchased part; see source")),
                   source=item.get("source", item.get("source_url")), metadata=metadata,
                   process=item.get("manufacturing", item.get("spec", "unspecified")),
                   files={}, unresolved=[])
        if not row["source"]:
            row["unresolved"].append("source_not_attached")
        if item.get("qualification"):
            row["unresolved"].append("qualification_required: " + str(item["qualification"]))
        review = f"review/{name}.stl"
        (folder / "review").mkdir(exist_ok=True)
        cq.exporters.export(shape, str(folder / review), tolerance=0.05, angularTolerance=0.1)
        row["files"]["review_stl"] = review
        if kind in PRINTABLE:
            if not item.get("print_face"):
                row["unresolved"].append("print_face_missing")
            else:
                printed = orient_for_print(shape, item["print_face"])
                (folder / "print").mkdir(exist_ok=True)
                for suffix in ("stl", "3mf"):
                    filename = f"print/{name}.{suffix}"
                    if suffix == "3mf":
                        write_3mf(printed, folder / filename)
                    else:
                        cq.exporters.export(printed, str(folder / filename), tolerance=0.05, angularTolerance=0.1)
                    row["files"][suffix] = filename
                row["print_face"] = item["print_face"]
                row["unresolved"].append("slicer_supports_and_process_not_qualified")
        if kind == "al":
            if "flat" in auxiliary:
                flat = auxiliary["flat"]
                row["laser_blank_volume_mm3"] = flat.Volume()
                row["stock_thickness_mm"] = flat.BoundingBox().zlen
                face = _profile_face(flat)
                if face is None:
                    row["unresolved"].append("flat_is_not_constant_thickness_profile")
                else:
                    (folder / "laser").mkdir(exist_ok=True)
                    filename = f"laser/{name}.dxf"
                    cq.exporters.export(face, str(folder / filename))
                    row["files"]["laser_dxf"] = filename
                if abs(flat.Volume()-shape.Volume()) > 1e-5 or re.search(
                        r"countersink|drill|tap|沉孔|钻|攻丝", row["process"], re.I):
                    row["unresolved"].append("secondary_operations_require_drawing")
            else:
                row["unresolved"].append("stock_or_purchased_part_requires_process_drawing")
            for template_key in ("side_flat", "output_flat"):
                if template_key not in auxiliary:
                    continue
                template = _profile_face(auxiliary[template_key])
                if template is not None:
                    (folder / "stock-templates").mkdir(exist_ok=True)
                    filename = f"stock-templates/{name}-{template_key}-REFERENCE-ONLY.dxf"
                    cq.exporters.export(template, str(folder / filename))
                    row["files"][template_key + "_reference_dxf"] = filename
                row["unresolved"].append(template_key + "_is_not_unfolded_blank_or_complete_drilling_drawing")
        rows.append(row)
    result = dict(schema_version=1, units="mm", release_ready=False,
                  format_reference="https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md",
                  assembly_gate_status="not evaluated by manufacturing exporter",
                  quantity_policy="one row per named assembly item; no inferred equivalence grouping",
                  part_count=len(rows), parts=rows)
    (folder / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    from .cad_export import build_items
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New or empty output directory")
    args = parser.parse_args()
    report = export_manufacturing(build_items(), args.out)
    print(json.dumps({"parts": report["part_count"], "release_ready": False}))
