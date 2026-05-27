"""Headless BooleanFragments region workflow smoke test.

Run with:
    FreeCADCmd -c "import runpy; runpy.run_path('tests/boolean_fragment_region_workflow.py', run_name='__main__')"
"""

import os
import sys


MOD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if MOD_PATH not in sys.path:
    sys.path.insert(0, MOD_PATH)

import FreeCAD as App

import tpms_generator
from objects.TPMSUnitCell import (
    REGION_ROLE_BASE,
    REGION_ROLE_OVERRIDE,
    REGION_ROLE_TRANSITION,
    REGION_MODE_ALL,
    add_grading_control,
    add_tpms_region_settings,
    add_tpms_region_settings_for_all_regions,
    boundary_region_items,
    is_tpms_unit_cell,
    make_tpms_unit_cell,
    selected_boundary_region,
    _effective_region_index_for_object,
)


STUDY_DIR = "/home/kevin/Dropbox/UAntwerp/PhD_thesis/FreeCAD_files/TPMS_study"
TEST_FILES = (
    "boolean_fragment_density_grading.FCStd",
    "boolean_fragment_test2.FCStd",
    "boolean_fragment_test3.FCStd",
)
HARMONIC_DENSITY_FILE = "harmonic_unit_cell.FCStd"


def _find_boundary(doc):
    candidates = []
    for obj in doc.Objects:
        if is_tpms_unit_cell(obj):
            boundary = getattr(obj, "BoundaryObject", None)
            if boundary is not None and len(boundary_region_items(boundary)) > 1:
                return boundary
        if len(boundary_region_items(obj)) > 1:
            candidates.append(obj)
    if not candidates:
        raise RuntimeError("No multi-solid boundary found in {}".format(doc.Name))
    candidates.sort(key=lambda obj: len(boundary_region_items(obj)), reverse=True)
    return candidates[0]


def _main_controller(doc, boundary):
    for obj in doc.Objects:
        if is_tpms_unit_cell(obj):
            obj.BoundaryObject = boundary
            return obj
    container, controller, _mesh_obj = make_tpms_unit_cell(doc)
    return controller


def _configure_fast(controller, boundary):
    controller.Surface = "Gyroid"
    controller.Equation = tpms_generator.SURFACE_EQUATIONS["Gyroid"]
    controller.Part = tpms_generator.PART_SHEET
    controller.Resolution = 6
    controller.CellSize = App.Vector(10.0, 10.0, 10.0)
    controller.Offset = 0.4
    controller.BoundaryMode = tpms_generator.BOUNDARY_SELECTED_SOLID
    controller.BoundaryObject = boundary
    controller.RegionMode = REGION_MODE_ALL
    controller.RegionIndex = 0
    controller.Sampling = 0.0
    controller.AddCaps = False
    controller.MeshRelaxation = False


def _mesh_bounds(mesh_obj):
    bb = mesh_obj.Mesh.BoundBox
    return (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)


def _mesh_facet_count(controller):
    mesh_obj = getattr(controller, "ResultMesh", None)
    if mesh_obj is None:
        return 0
    return int(mesh_obj.Mesh.CountFacets)


def _role(controller):
    return str(getattr(controller, "RegionRole", REGION_ROLE_BASE))


def run_file(path):
    doc = App.openDocument(path)
    try:
        boundary = _find_boundary(doc)
        regions = boundary_region_items(boundary)
        if len(regions) < 2:
            raise RuntimeError("{} exposes fewer than 2 regions".format(path))

        controller = _main_controller(doc, boundary)
        _configure_fast(controller, boundary)
        created = add_tpms_region_settings_for_all_regions(controller, skip_existing=True)
        controllers_before_recompute = [
            obj
            for obj in doc.Objects
            if is_tpms_unit_cell(obj) and getattr(obj, "BoundaryObject", None) == boundary
        ]
        region_settings_before_recompute = [
            obj
            for obj in controllers_before_recompute
            if str(getattr(obj, "RegionMode", "")) == "Single region"
        ]
        doc.recompute()

        controllers = [
            obj
            for obj in doc.Objects
            if is_tpms_unit_cell(obj) and getattr(obj, "BoundaryObject", None) == boundary
        ]
        single_region = [
            obj
            for obj in controllers
            if str(getattr(obj, "RegionMode", "")) == "Single region"
        ]
        if len(single_region) < max(0, len(regions) - 1):
            raise RuntimeError(
                "{} has {} region controllers for {} regions".format(
                    path,
                    len(single_region),
                    len(regions),
                )
            )

        for obj in controllers:
            last_error = str(getattr(obj, "LastError", ""))
            if last_error:
                raise RuntimeError("{} generation failed: {}".format(obj.Label, last_error))

            facets = _mesh_facet_count(obj)
            role = _role(obj)
            if obj is controller and facets <= 0:
                raise RuntimeError("{} generated an empty primary region mesh".format(obj.Label))
            if obj is not controller and facets != 0:
                raise RuntimeError("{} generated an independent mesh; region settings should be settings-only".format(obj.Label))
            if _role(obj) != REGION_ROLE_BASE and int(getattr(obj, "Resolution", 0)) != int(controller.Resolution):
                raise RuntimeError(
                    "{} kept an independent resolution {} instead of base {}".format(
                        obj.Label,
                        int(getattr(obj, "Resolution", 0)),
                        int(controller.Resolution),
                    )
                )
        covered_regions = {
            _effective_region_index_for_object(controller)
        } | {
            _effective_region_index_for_object(obj)
            for obj in single_region
            if _role(obj) in (REGION_ROLE_OVERRIDE, REGION_ROLE_TRANSITION)
        }
        if not set(range(len(regions))).issubset(covered_regions):
            raise RuntimeError(
                "{} region override coverage is incomplete: {} of {}".format(
                    path,
                    sorted(covered_regions),
                    list(range(len(regions))),
                )
            )

        base_description = str(getattr(controller, "RegionDescription", ""))
        if not base_description.startswith("Generated continuous hybrid mesh across {} solid region".format(len(regions))):
            raise RuntimeError(
                "{} base controller did not generate a continuous hybrid mesh: {}".format(path, base_description)
            )

        region_meshes = list(getattr(controller, "ResultRegionMeshes", []))
        if region_meshes:
            raise RuntimeError("{} generated {} per-region meshes instead of one continuous mesh".format(path, len(region_meshes)))
        main_facets = _mesh_facet_count(controller)
        if main_facets <= 0:
            raise RuntimeError("{} generated an empty continuous mesh".format(path))
        print(
            "PASS {} regions={} created={} main_facets={} main_region='{}' main_bounds={}".format(
                os.path.basename(path),
                len(regions),
                len(created),
                main_facets,
                base_description,
                tuple(round(value, 6) for value in _mesh_bounds(controller.ResultMesh)) if _mesh_facet_count(controller) else (),
            )
        )
    finally:
        App.closeDocument(doc.Name)


def _has_degenerate_facets(mesh, tolerance=1e-12):
    try:
        for facet in mesh.Facets:
            points = facet.Points
            if len(points) != 3:
                return True
            a, b, c = points
            ab = b.sub(a)
            ac = c.sub(a)
            if ab.cross(ac).Length * 0.5 <= tolerance:
                return True
    except Exception:
        return False
    return False


def _assert_transition_weight_varies(source_solid, transition_solid, target_solid):
    import numpy as np
    import tpms_generator as generator

    bb = transition_solid.BoundBox
    xs = np.linspace(float(bb.XMin) + 0.5, float(bb.XMax) - 0.5, 9)
    ys = np.full(xs.shape, 0.5 * (float(bb.YMin) + float(bb.YMax)))
    zs = np.full(xs.shape, 0.5 * (float(bb.ZMin) + float(bb.ZMax)))
    wx = xs.reshape((-1, 1, 1))
    wy = ys.reshape((-1, 1, 1))
    wz = zs.reshape((-1, 1, 1))
    source_distance = generator._selected_boundary_distance_vtk(
        _BoundaryProbe(source_solid),
        wx,
        wy,
        wz,
        0.0,
        16,
    ).ravel()
    target_distance = generator._selected_boundary_distance_vtk(
        _BoundaryProbe(target_solid),
        wx,
        wy,
        wz,
        0.0,
        16,
    ).ravel()
    weight = source_distance / (source_distance + target_distance)
    if float(np.max(weight) - np.min(weight)) < 0.5:
        raise RuntimeError("Transition blend weight is nearly constant: {}".format(weight.tolist()))
    if not (weight[0] < 0.2 and weight[-1] > 0.8):
        raise RuntimeError("Transition blend weight does not span source to target: {}".format(weight.tolist()))


class _BoundaryProbe:
    def __init__(self, shape, placement=None):
        self.Shape = shape
        if placement is not None:
            self.Placement = placement


def run_generated_transition_region_case():
    import Part

    doc = App.newDocument("TPMS_transition_region_test")
    try:
        solids = [
            Part.makeBox(10.0, 10.0, 10.0, App.Vector(0.0, 0.0, 0.0)),
            Part.makeBox(10.0, 10.0, 10.0, App.Vector(10.0, 0.0, 0.0)),
            Part.makeBox(10.0, 10.0, 10.0, App.Vector(20.0, 0.0, 0.0)),
        ]
        boundary = doc.addObject("Part::Feature", "Three_Region_Fragment")
        boundary.Label = "Three Region BooleanFragments Equivalent"
        boundary.Shape = Part.makeCompound(solids)

        _container, controller, _mesh_obj = make_tpms_unit_cell(doc)
        _configure_fast(controller, boundary)
        controller.Resolution = 10
        controller.AddCaps = True
        controller.RegionIndex = 0
        controller.Label = "Base Region Parameters"
        created = add_tpms_region_settings_for_all_regions(controller, skip_existing=True)
        if len(created) != 2:
            raise RuntimeError("Expected 2 region settings after base region, got {}".format(len(created)))

        settings = {
            int(getattr(obj, "RegionIndex", -1)): obj
            for obj, _mesh in created
        }
        transition = settings[1]
        target = settings[2]
        transition.RegionRole = REGION_ROLE_TRANSITION
        transition.TransitionSourceRegion = 0
        transition.TransitionTargetRegion = 2
        target.Surface = "Schwarz P"
        target.Equation = tpms_generator.SURFACE_EQUATIONS["Schwarz P"]
        target.Part = tpms_generator.PART_UPPER
        target.BaseDensity = 1.35
        target.Offset = 0.65
        _assert_transition_weight_varies(solids[0], solids[1], solids[2])

        doc.recompute()
        mesh_obj = controller.ResultMesh
        if mesh_obj is None or mesh_obj.Mesh.CountFacets <= 0:
            raise RuntimeError("Transition-region case generated an empty mesh")
        if list(getattr(controller, "ResultRegionMeshes", [])):
            raise RuntimeError("Transition-region case generated per-region meshes")
        for obj in settings.values():
            if getattr(obj, "ResultMesh", None) is not None:
                raise RuntimeError("{} owns an independent mesh".format(obj.Label))
        if mesh_obj.Mesh.hasNonManifolds():
            raise RuntimeError("Transition-region case has non-manifold points")
        if _has_degenerate_facets(mesh_obj.Mesh):
            raise RuntimeError("Transition-region case has degenerate facets")
        print(
            "PASS generated_transition_region regions=3 created={} main_facets={} solid={} non_manifold={}".format(
                len(created),
                int(mesh_obj.Mesh.CountFacets),
                bool(mesh_obj.Mesh.isSolid()),
                bool(mesh_obj.Mesh.hasNonManifolds()),
            )
        )
    finally:
        App.closeDocument(doc.Name)


def run_region_grading_separation_case():
    import hashlib
    import Part

    doc = App.newDocument("TPMS_region_grading_separation_test")
    try:
        solids = [
            Part.makeBox(10.0, 10.0, 10.0, App.Vector(0.0, 0.0, 0.0)),
            Part.makeBox(10.0, 10.0, 10.0, App.Vector(10.0, 0.0, 0.0)),
        ]
        boundary = doc.addObject("Part::Feature", "Two_Region_Fragment")
        boundary.Label = "Two Region BooleanFragments Equivalent"
        boundary.Shape = Part.makeCompound(solids)

        _container, controller, _mesh_obj = make_tpms_unit_cell(doc)
        _configure_fast(controller, boundary)
        controller.Resolution = 8
        controller.AddCaps = True
        controller.BaseDensity = 1.0
        control = add_grading_control(
            controller,
            boundary,
            ["Face1"],
            unit_cell_density=1.8,
            unit_cell_transition=8.0,
            thickness=None,
            thickness_transition=None,
            use_unit_cell_density=True,
            use_thickness=False,
        )
        control.DensitySource = tpms_generator.GRADIENT_FACE_DISTANCE
        created = add_tpms_region_settings_for_all_regions(controller, skip_existing=True)
        if len(created) != 1:
            raise RuntimeError("Expected one added region setting, got {}".format(len(created)))
        region_controller = created[0][0]
        if hasattr(region_controller, "FaceControls"):
            raise RuntimeError("Region controller contains legacy FaceControls")
        if hasattr(region_controller, "DensityOffsetControls"):
            raise RuntimeError("Region controller contains legacy DensityOffsetControls")

        signatures = []
        for enabled in (False, True):
            control.Enabled = enabled
            controller.touch()
            doc.recompute()
            mesh = controller.ResultMesh.Mesh
            sample = [
                (round(point.x, 5), round(point.y, 5), round(point.z, 5))
                for point in mesh.Points[:1000]
            ]
            mode_name = "Non-uniform" if enabled else "Uniform"
            signatures.append((mode_name, int(mesh.CountFacets), hashlib.sha256(repr(sample).encode("utf-8")).hexdigest()[:16]))
        if signatures[0][1:] == signatures[1][1:]:
            raise RuntimeError("Base grading did not change hybrid region mesh signature: {}".format(signatures))
        print(
            "PASS region_grading_separation uniform_facets={} graded_facets={} uniform_hash={} graded_hash={}".format(
                signatures[0][1],
                signatures[1][1],
                signatures[0][2],
                signatures[1][2],
            )
        )
    finally:
        App.closeDocument(doc.Name)


def _hybrid_transition_polydata(
    source_surface,
    source_part,
    target_surface,
    target_part,
    blend_mode=None,
    source_labyrinth=None,
    target_labyrinth=None,
    topology=None,
    correction_factor=0.0,
):
    import Part

    solids = [
        Part.makeBox(10.0, 10.0, 10.0, App.Vector(0.0, 0.0, 0.0)),
        Part.makeBox(10.0, 10.0, 10.0, App.Vector(10.0, 0.0, 0.0)),
        Part.makeBox(10.0, 10.0, 10.0, App.Vector(20.0, 0.0, 0.0)),
    ]
    source_equation = tpms_generator.SURFACE_EQUATIONS.get(source_surface, "")
    target_equation = tpms_generator.SURFACE_EQUATIONS.get(target_surface, "")
    source = _BoundaryProbe(solids[0])
    transition = _BoundaryProbe(solids[1])
    target = _BoundaryProbe(solids[2])
    outer_shape = solids[0].multiFuse(solids[1:])
    try:
        outer_shape = outer_shape.removeSplitter()
    except Exception:
        pass
    outer = _BoundaryProbe(outer_shape)
    return tpms_generator.generate_hybrid_polydata(
        tpms_generator.SURFACE_EQUATIONS["Gyroid"],
        tpms_generator.PART_SHEET,
        (10.0, 10.0, 10.0),
        (1, 1, 1),
        10,
        0.4,
        (0.0, 0.0, 0.0),
        tpms_generator.BOUNDARY_SELECTED_SOLID,
        outer,
        0.0,
        True,
        None,
        None,
        1.0,
        [
            {
                "index": 0,
                "boundary_object": source,
                "surface": source_surface,
                "part": source_part,
                "equation": source_equation,
                "offset": 0.4,
                "base_density": 1.0,
            },
            {
                "index": 2,
                "boundary_object": target,
                "surface": target_surface,
                "part": target_part,
                "equation": target_equation,
                "offset": 0.65,
                "base_density": 1.2,
            },
        ],
        [],
        [
            {
                "index": 1,
                "boundary_object": transition,
                "source_boundary_object": source,
                "source_surface": source_surface,
                "source_part": source_part,
                "source_equation": source_equation,
                "source_offset": 0.4,
                "source_base_density": 1.0,
                "target_boundary_object": target,
                "target_surface": target_surface,
                "target_part": target_part,
                "target_equation": target_equation,
                "target_offset": 0.65,
                "target_base_density": 1.2,
                "blend": blend_mode or tpms_generator.TRANSITION_BLEND_THRESHOLD,
                "correction_factor": correction_factor,
                "source_labyrinth": source_labyrinth or tpms_generator.LABYRINTH_AUTO,
                "target_labyrinth": target_labyrinth or tpms_generator.LABYRINTH_AUTO,
                "topology": topology or tpms_generator.TRANSITION_TOPOLOGY_SAME_SIDE,
            },
        ],
    )


def _assert_valid_polydata(name, polydata):
    if polydata.n_points <= 0 or polydata.n_cells <= 0:
        raise RuntimeError("{} generated empty polydata".format(name))
    mesh = tpms_generator.polydata_to_freecad_mesh(polydata)
    if mesh.CountFacets <= 0:
        raise RuntimeError("{} converted to an empty FreeCAD mesh".format(name))
    if mesh.hasNonManifolds():
        print("WARNING: {} generated non-manifold points (acceptable for low-resolution blends)".format(name))
    if _has_degenerate_facets(mesh):
        raise RuntimeError("{} generated degenerate facets".format(name))
    return mesh


def run_transition_region_surface_modes_case():
    sheet_to_upper = _hybrid_transition_polydata(
        "Gyroid",
        tpms_generator.PART_SHEET,
        "Schwarz P",
        tpms_generator.PART_UPPER,
    )
    sheet_mesh = _assert_valid_polydata("Sheet to upper-skeletal transition", sheet_to_upper)

    empty_to_solid = _hybrid_transition_polydata(
        tpms_generator.SURFACE_EMPTY,
        tpms_generator.PART_SHEET,
        tpms_generator.SURFACE_SOLID_FILL,
        tpms_generator.PART_SHEET,
    )
    solid_mesh = _assert_valid_polydata("Empty to solid-fill transition", empty_to_solid)
    bounds = solid_mesh.BoundBox
    if bounds.XMin < 13.0 or bounds.XMax < 29.5:
        raise RuntimeError(
            "Empty to solid-fill transition occupied unexpected bounds: ({:.3f}, {:.3f})".format(
                bounds.XMin,
                bounds.XMax,
            )
        )

    empty_to_tpms = _hybrid_transition_polydata(
        tpms_generator.SURFACE_EMPTY,
        tpms_generator.PART_SHEET,
        "Gyroid",
        tpms_generator.PART_LOWER,
    )
    lower_mesh = _assert_valid_polydata("Empty to lower-skeletal transition", empty_to_tpms)

    upper_to_sheet = _hybrid_transition_polydata(
        "Gyroid",
        tpms_generator.PART_UPPER,
        "Gyroid",
        tpms_generator.PART_SHEET,
        tpms_generator.TRANSITION_BLEND_SIGMOID,
    )
    upper_sheet_mesh = _assert_valid_polydata("Upper-skeletal to sheet transition", upper_to_sheet)

    print(
        "PASS transition_region_surface_modes sheet_upper_facets={} empty_solid_facets={} empty_lower_facets={} upper_sheet_facets={}".format(
            int(sheet_mesh.CountFacets),
            int(solid_mesh.CountFacets),
            int(lower_mesh.CountFacets),
            int(upper_sheet_mesh.CountFacets),
        )
    )


def run_labyrinth_transition_modes_case():
    import hashlib

    def signature(mesh):
        sample = [
            (round(point.x, 5), round(point.y, 5), round(point.z, 5))
            for point in mesh.Points[:1000]
        ]
        return int(mesh.CountFacets), hashlib.sha256(repr(sample).encode("utf-8")).hexdigest()[:16]

    same_side = _hybrid_transition_polydata(
        "Gyroid",
        tpms_generator.PART_UPPER,
        "Gyroid",
        tpms_generator.PART_UPPER,
        source_labyrinth=tpms_generator.LABYRINTH_POSITIVE,
        target_labyrinth=tpms_generator.LABYRINTH_POSITIVE,
        topology=tpms_generator.TRANSITION_TOPOLOGY_SAME_SIDE,
    )
    same_mesh = _assert_valid_polydata("Upper-to-upper labyrinth transition", same_side)

    cross_side = _hybrid_transition_polydata(
        "Gyroid",
        tpms_generator.PART_UPPER,
        "Gyroid",
        tpms_generator.PART_LOWER,
        source_labyrinth=tpms_generator.LABYRINTH_POSITIVE,
        target_labyrinth=tpms_generator.LABYRINTH_NEGATIVE,
        topology=tpms_generator.TRANSITION_TOPOLOGY_CROSS_BRIDGE,
    )
    cross_mesh = _assert_valid_polydata("Upper-to-lower labyrinth transition", cross_side)

    same_signature = signature(same_mesh)
    cross_signature = signature(cross_mesh)
    if same_signature == cross_signature:
        raise RuntimeError("Same-side and cross-labyrinth transitions produced identical signatures")
    offset_blend = _hybrid_transition_polydata(
        "Gyroid",
        tpms_generator.PART_UPPER,
        "Gyroid",
        tpms_generator.PART_LOWER,
        blend_mode=tpms_generator.TRANSITION_BLEND_THRESHOLD,
        source_labyrinth=tpms_generator.LABYRINTH_POSITIVE,
        target_labyrinth=tpms_generator.LABYRINTH_NEGATIVE,
        topology=tpms_generator.TRANSITION_TOPOLOGY_CROSS_BRIDGE,
    )
    sigmoid_blend = _hybrid_transition_polydata(
        "Gyroid",
        tpms_generator.PART_UPPER,
        "Gyroid",
        tpms_generator.PART_LOWER,
        blend_mode=tpms_generator.TRANSITION_BLEND_SIGMOID,
        source_labyrinth=tpms_generator.LABYRINTH_POSITIVE,
        target_labyrinth=tpms_generator.LABYRINTH_NEGATIVE,
        topology=tpms_generator.TRANSITION_TOPOLOGY_CROSS_BRIDGE,
    )
    asli_blend = _hybrid_transition_polydata(
        "Gyroid",
        tpms_generator.PART_UPPER,
        "Gyroid",
        tpms_generator.PART_LOWER,
        blend_mode=tpms_generator.TRANSITION_BLEND_NORMALIZED_SUM,
        correction_factor=0.5,
        source_labyrinth=tpms_generator.LABYRINTH_POSITIVE,
        target_labyrinth=tpms_generator.LABYRINTH_NEGATIVE,
        topology=tpms_generator.TRANSITION_TOPOLOGY_CROSS_BRIDGE,
    )
    offset_signature = signature(_assert_valid_polydata("Cross-labyrinth offset-surface blend", offset_blend))
    sigmoid_signature = signature(_assert_valid_polydata("Cross-labyrinth sigmoid blend", sigmoid_blend))
    asli_signature = signature(_assert_valid_polydata("Cross-labyrinth ASLI blend", asli_blend))
    if offset_signature == sigmoid_signature:
        raise RuntimeError("Transition blend modes produced identical signatures")
    if asli_signature in (offset_signature, sigmoid_signature):
        raise RuntimeError("ASLI transition blend matched an existing blend signature")
    print(
        "PASS labyrinth_transition_modes same_facets={} same_hash={} cross_facets={} cross_hash={} offset_hash={} sigmoid_hash={} asli_hash={}".format(
            same_signature[0],
            same_signature[1],
            cross_signature[0],
            cross_signature[1],
            offset_signature[1],
            sigmoid_signature[1],
            asli_signature[1],
        )
    )


def run_cylindrical_ring_boundary_origin_case():
    import Part

    placement = App.Placement(App.Vector(42.0, -17.0, 6.0), App.Rotation())
    boundary = _BoundaryProbe(Part.makeBox(80.0, 80.0, 40.0, App.Vector(2.0, -57.0, -4.0)), placement)
    polydata = tpms_generator.generate_cylindrical_ring_polydata(
        tpms_generator.SURFACE_EQUATIONS["Gyroid"],
        tpms_generator.PART_SURFACE,
        (10.0, 10.0, 10.0),
        8,
        0.3,
        (0.0, 0.0, 0.0),
        False,
        None,
        None,
        6.0,
        9.0,
        10.0,
        6,
        boundary_mode=tpms_generator.BOUNDARY_SELECTED_SOLID,
        boundary_object=boundary,
    )
    if polydata.n_points <= 0:
        raise RuntimeError("Cylindrical ring boundary-origin case generated an empty surface")
    center = polydata.center
    expected = (placement.Base.x, placement.Base.y)
    error = ((float(center[0]) - expected[0]) ** 2 + (float(center[1]) - expected[1]) ** 2) ** 0.5
    if error > 2.0:
        raise RuntimeError(
            "Cylindrical ring ignored boundary origin: center=({:.3f}, {:.3f}), expected near=({:.3f}, {:.3f})".format(
                float(center[0]),
                float(center[1]),
                expected[0],
                expected[1],
            )
        )
    print(
        "PASS cylindrical_ring_boundary_origin center=({:.3f}, {:.3f}, {:.3f}) expected_xy=({:.3f}, {:.3f})".format(
            float(center[0]),
            float(center[1]),
            float(center[2]),
            expected[0],
            expected[1],
        )
    )

    moved_tube_placement = App.Placement(App.Vector(10.5, 0.0, 0.0), App.Rotation())
    outer = Part.makeCylinder(5.0, 10.0, moved_tube_placement.Base)
    inner = Part.makeCylinder(2.0, 10.0, moved_tube_placement.Base)
    tube_boundary = _BoundaryProbe(outer.cut(inner), moved_tube_placement)
    controller = type("ControllerProbe", (), {})()
    controller.BoundaryObject = tube_boundary
    controller.RegionMode = REGION_MODE_ALL
    controller.RegionRole = REGION_ROLE_BASE
    controller.BaseExcludesRegionSettings = False
    region_boundary, _description, _count = selected_boundary_region(controller)
    polydata = tpms_generator.generate_cylindrical_ring_polydata(
        tpms_generator.SURFACE_EQUATIONS["Gyroid"],
        tpms_generator.PART_SHEET,
        (10.0, 10.0, 10.0),
        8,
        0.3,
        (0.0, 0.0, 0.0),
        True,
        None,
        None,
        2.0,
        5.0,
        10.0,
        8,
        boundary_mode=tpms_generator.BOUNDARY_SELECTED_SOLID,
        boundary_object=region_boundary,
    )
    if polydata.n_points <= 0:
        raise RuntimeError("Cylindrical ring region-adapter origin case generated an empty surface")
    bounds = polydata.bounds
    if abs(float(bounds[0]) - 5.5) > 0.2 or abs(float(bounds[1]) - 15.5) > 0.2:
        raise RuntimeError(
            "Cylindrical ring region adapter lost boundary placement: bounds=({:.3f}, {:.3f})".format(
                float(bounds[0]),
                float(bounds[1]),
            )
        )
    print(
        "PASS cylindrical_ring_region_adapter_origin x_bounds=({:.3f}, {:.3f})".format(
            float(bounds[0]),
            float(bounds[1]),
        )
    )


def run_cylindrical_ring_radial_continuity_case():
    params = (
        tpms_generator.SURFACE_EQUATIONS["Gyroid"],
        tpms_generator.PART_SURFACE,
        (10.0, 10.0, 10.0),
        12,
        0.0,
        (0.0, 0.0, 0.0),
        False,
        None,
        None,
        1.0,
    )
    inner_radius = 1.0
    height = 10.0
    resolution = 8
    radius_5 = tpms_generator.generate_cylindrical_ring_polydata(
        *params,
        5.0,
        height,
        resolution,
    )
    radius_6 = tpms_generator.generate_cylindrical_ring_polydata(
        *params,
        6.0,
        height,
        resolution,
    )

    def interior_points(polydata, radial_limit):
        points = set()
        for x, y, z in polydata.points:
            radius = (float(x) * float(x) + float(y) * float(y)) ** 0.5
            if inner_radius + 0.2 < radius < radial_limit:
                points.add((round(float(x), 4), round(float(y), 4), round(float(z), 4)))
        return points

    common_5 = interior_points(radius_5, 4.75)
    common_6 = interior_points(radius_6, 4.75)
    if not common_5:
        raise RuntimeError("Cylindrical continuity case produced no shared interior points")
    if common_5 != common_6:
        raise RuntimeError(
            "Cylindrical ring field changed inside unchanged radius: only_5={} only_6={}".format(
                len(common_5 - common_6),
                len(common_6 - common_5),
            )
        )
    print("PASS cylindrical_ring_radial_continuity shared_points={}".format(len(common_5)))


def run_hybrid_cylindrical_coordinate_mode_case():
    import hashlib
    import Part

    boundary = _BoundaryProbe(Part.makeCylinder(5.0, 8.0, App.Vector(0.0, 0.0, 0.0)))
    region_spec = {
        "index": 0,
        "boundary_object": boundary,
        "surface": "Gyroid",
        "part": tpms_generator.PART_SHEET,
        "equation": tpms_generator.SURFACE_EQUATIONS["Gyroid"],
        "offset": 0.35,
        "base_density": 1.0,
    }
    signatures = []
    for coordinate_mode in (
        tpms_generator.COORDINATE_CARTESIAN,
        tpms_generator.COORDINATE_CYLINDRICAL_RING,
    ):
        polydata = tpms_generator.generate_hybrid_polydata(
            tpms_generator.SURFACE_EQUATIONS["Gyroid"],
            tpms_generator.PART_SHEET,
            (10.0, 10.0, 10.0),
            (1, 1, 1),
            8,
            0.35,
            (0.0, 0.0, 0.0),
            tpms_generator.BOUNDARY_SELECTED_SOLID,
            boundary,
            0.0,
            False,
            (0.0, 0.0, 0.0),
            None,
            1.0,
            [region_spec],
            [],
            [],
            coordinate_mode=coordinate_mode,
            ring_angular_cells=8,
        )
        if polydata.n_points <= 0 or polydata.n_cells <= 0:
            raise RuntimeError("{} hybrid coordinate mode generated empty polydata".format(coordinate_mode))
        sample = [tuple(round(float(value), 4) for value in point) for point in polydata.points[:2000]]
        signatures.append((coordinate_mode, int(polydata.n_cells), hashlib.sha256(repr(sample).encode("utf-8")).hexdigest()[:16]))
    if signatures[0][1:] == signatures[1][1:]:
        raise RuntimeError("Hybrid cylindrical coordinate mode matched Cartesian signature: {}".format(signatures))
    print(
        "PASS hybrid_cylindrical_coordinate_mode cartesian_facets={} cylindrical_facets={} cartesian_hash={} cylindrical_hash={}".format(
            signatures[0][1],
            signatures[1][1],
            signatures[0][2],
            signatures[1][2],
        )
    )


def run_tessellated_boundary_signed_distance_case():
    import numpy as np
    import Part

    shape = Part.makeBox(8.0, 8.0, 8.0, App.Vector(-4.0, -4.0, -4.0))
    shape.rotate(App.Vector(0.0, 0.0, 0.0), App.Vector(0.0, 1.0, 0.0), 27.0)
    boundary = _BoundaryProbe(shape)
    boundary.ForceTessellatedBoundary = True

    coords = np.linspace(-6.0, 6.0, 13)
    wx, wy, wz = np.meshgrid(coords, coords, coords, indexing="ij")
    field = tpms_generator._selected_boundary_field_signed_vtk(boundary, wx, wy, wz, 0.0, 13)
    spacing = float(coords[1] - coords[0])
    positive = field[field > 0.0]
    negative = field[field < 0.0]
    if not len(positive) or not len(negative):
        raise RuntimeError("Tessellated signed boundary field did not classify both sides")
    if float(np.max(positive)) <= spacing * 1.5:
        raise RuntimeError("Tessellated signed boundary field does not contain interior distances")
    if len(np.unique(np.round(np.abs(field), 4))) <= 8:
        raise RuntimeError("Tessellated signed boundary field still looks binary/stepwise")

    polydata = tpms_generator.generate_polydata(
        tpms_generator.SURFACE_EQUATIONS["Gyroid"],
        tpms_generator.PART_SHEET,
        (8.0, 8.0, 8.0),
        (1, 1, 1),
        8,
        0.35,
        (0.0, 0.0, 0.0),
        tpms_generator.BOUNDARY_SELECTED_SOLID,
        boundary,
        0.0,
        True,
        None,
        None,
    )
    if polydata.n_points <= 0 or polydata.n_cells <= 0:
        raise RuntimeError("Tessellated signed boundary generated an empty capped mesh")
    print(
        "PASS tessellated_boundary_signed_distance max_inside={:.4f} unique_distances={} facets={}".format(
            float(np.max(positive)),
            len(np.unique(np.round(np.abs(field), 4))),
            int(polydata.n_cells),
        )
    )


def run_boundary_evaluation_mode_case():
    import numpy as np
    import Part

    doc = App.newDocument("TPMS_boundary_evaluation_mode_test")
    try:
        sphere = doc.addObject("Part::Sphere", "Analytical_Or_SDF_Sphere")
        sphere.Radius = 5.0
        doc.recompute()

        _container, controller, _mesh_obj = make_tpms_unit_cell(doc)
        controller.BoundaryMode = tpms_generator.BOUNDARY_SELECTED_SOLID
        controller.BoundaryObject = sphere
        controller.RegionMode = REGION_MODE_ALL

        controller.BoundaryEvaluation = tpms_generator.BOUNDARY_EVALUATION_ANALYTICAL
        analytical_boundary, _description, _count = selected_boundary_region(controller)
        coords = np.linspace(-6.0, 6.0, 9)
        wx, wy, wz = np.meshgrid(coords, coords, coords, indexing="ij")
        analytical_field = tpms_generator._analytic_boundary_field(analytical_boundary, wx, wy, wz)
        if analytical_field is None:
            raise RuntimeError("Analytical boundary evaluation did not preserve the Part sphere analytical field")

        controller.BoundaryEvaluation = tpms_generator.BOUNDARY_EVALUATION_TESSELLATED_SDF
        tessellated_boundary, _description, _count = selected_boundary_region(controller)
        if not bool(getattr(tessellated_boundary, "ForceTessellatedBoundary", False)):
            raise RuntimeError("Tessellated SDF boundary evaluation did not force tessellation")
        if tpms_generator._analytic_boundary_field(tessellated_boundary, wx, wy, wz) is not None:
            raise RuntimeError("Tessellated SDF boundary evaluation still used an analytical field")
        sdf_field = tpms_generator._selected_boundary_field_signed_vtk(tessellated_boundary, wx, wy, wz, 0.0, 9)
        if not (np.any(sdf_field > 0.0) and np.any(sdf_field < 0.0)):
            raise RuntimeError("Tessellated SDF boundary evaluation did not produce signed distances")

        print(
            "PASS boundary_evaluation_mode analytical_type={} sdf_forced={} sdf_unique={}".format(
                getattr(analytical_boundary, "TypeId", ""),
                bool(getattr(tessellated_boundary, "ForceTessellatedBoundary", False)),
                len(np.unique(np.round(np.abs(sdf_field), 4))),
            )
        )
    finally:
        App.closeDocument(doc.Name)


def run_analytical_csg_boundary_case():
    import numpy as np

    doc = App.newDocument("TPMS_analytical_csg_boundary_test")
    try:
        box = doc.addObject("Part::Box", "Box")
        box.Length = 8.0
        box.Width = 8.0
        box.Height = 8.0
        box.Placement.Base = App.Vector(-4.0, -4.0, -4.0)

        sphere = doc.addObject("Part::Sphere", "Sphere")
        sphere.Radius = 5.0

        fuse = doc.addObject("Part::Fuse", "Box_Fuse_Sphere")
        fuse.Base = box
        fuse.Tool = sphere

        common = doc.addObject("Part::Common", "Box_Common_Sphere")
        common.Base = box
        common.Tool = sphere

        cut = doc.addObject("Part::Cut", "Box_Cut_Sphere")
        cut.Base = box
        cut.Tool = sphere
        moved_fuse = doc.addObject("Part::MultiFuse", "Moved_Box_Fuse_Sphere")
        moved_fuse.Shapes = [box, sphere]
        moved_fuse.Placement.Base = App.Vector(-11.0, 0.0, 0.0)
        doc.recompute()

        wx = np.array([0.0, 3.8, 5.5], dtype=float).reshape((3, 1, 1))
        wy = np.array([0.0, 3.8, 0.0], dtype=float).reshape((3, 1, 1))
        wz = np.zeros_like(wx)
        box_field = tpms_generator._primitive_analytic_boundary_field(box, wx, wy, wz)
        sphere_field = tpms_generator._primitive_analytic_boundary_field(sphere, wx, wy, wz)
        fuse_field = tpms_generator._analytic_boundary_field(fuse, wx, wy, wz)
        common_field = tpms_generator._analytic_boundary_field(common, wx, wy, wz)
        cut_field = tpms_generator._analytic_boundary_field(cut, wx, wy, wz)

        if fuse_field is None or common_field is None or cut_field is None:
            raise RuntimeError("Analytical CSG did not return fields for all Boolean operations")
        if not np.allclose(fuse_field, np.maximum(box_field, sphere_field)):
            raise RuntimeError("Analytical CSG fuse did not use positive-inside union")
        if not np.allclose(common_field, np.minimum(box_field, sphere_field)):
            raise RuntimeError("Analytical CSG common did not use positive-inside intersection")
        if not np.allclose(cut_field, np.minimum(box_field, -sphere_field)):
            raise RuntimeError("Analytical CSG cut did not use positive-inside subtraction")
        if not (cut_field[0, 0, 0] < 0.0 and cut_field[1, 0, 0] > 0.0 and cut_field[2, 0, 0] < 0.0):
            raise RuntimeError("Analytical CSG cut point classification is wrong: {}".format(cut_field.ravel().tolist()))

        moved_wx = np.array([-11.0, -0.5], dtype=float).reshape((2, 1, 1))
        moved_wy = np.zeros_like(moved_wx)
        moved_wz = np.array([0.0, 5.0], dtype=float).reshape((2, 1, 1))
        moved_field = tpms_generator._analytic_boundary_field(moved_fuse, moved_wx, moved_wy, moved_wz)
        if moved_field is None or not (moved_field[0, 0, 0] > 0.0 and moved_field[1, 0, 0] < 0.0):
            raise RuntimeError(
                "Analytical CSG did not respect Boolean object placement: {}".format(
                    None if moved_field is None else moved_field.ravel().tolist()
                )
            )

        print(
            "PASS analytical_csg_boundary fuse={} common={} cut={} moved={}".format(
                [round(float(value), 4) for value in fuse_field.ravel()],
                [round(float(value), 4) for value in common_field.ravel()],
                [round(float(value), 4) for value in cut_field.ravel()],
                [round(float(value), 4) for value in moved_field.ravel()],
            )
        )
    finally:
        App.closeDocument(doc.Name)


def _make_tube_shell(inner_radius, outer_radius, height):
    import Part

    outer = Part.makeCylinder(
        float(outer_radius),
        float(height),
        App.Vector(0.0, 0.0, 0.0),
        App.Vector(0.0, 0.0, 1.0),
    )
    inner = Part.makeCylinder(
        float(inner_radius),
        float(height) + 2.0,
        App.Vector(0.0, 0.0, -1.0),
        App.Vector(0.0, 0.0, 1.0),
    )
    return outer.cut(inner)


class TubeFeature:
    pass


class FeatureBooleanFragments:
    Type = "FeatureBooleanFragments"


class _AnalyticalTubeProbe:
    TypeId = "Part::FeaturePython"

    def __init__(self, name, inner_radius, outer_radius, height):
        self.Name = name
        self.Label = name
        self.Proxy = TubeFeature()
        self.Placement = App.Placement()
        self.InnerRadius = float(inner_radius)
        self.OuterRadius = float(outer_radius)
        self.Height = float(height)
        self.Shape = _make_tube_shell(inner_radius, outer_radius, height)


class _BooleanFragmentsProbe:
    TypeId = "Part::FeaturePython"

    def __init__(self, objects):
        import Part

        self.Name = "Tube_BooleanFragments"
        self.Label = "Tube BooleanFragments"
        self.Proxy = FeatureBooleanFragments()
        self.Placement = App.Placement()
        self.Objects = list(objects)
        self.Shape = Part.makeCompound([obj.Shape.Solids[0] for obj in objects])


def run_cylindrical_analytical_csg_tube_boundary_case():
    import numpy as np
    import Part

    doc = App.newDocument("TPMS_cylindrical_analytical_csg_tube_test")
    try:
        outer = doc.addObject("Part::Cylinder", "Outer_Cylinder")
        outer.Radius = 7.0
        outer.Height = 10.0

        inner = doc.addObject("Part::Cylinder", "Inner_Cylinder")
        inner.Radius = 1.0
        inner.Height = 12.0
        inner.Placement.Base = App.Vector(0.0, 0.0, -1.0)

        tube = doc.addObject("Part::Cut", "Analytical_Tube")
        tube.Base = outer
        tube.Tool = inner
        doc.recompute()

        sample_x = np.array([0.5, 2.0, 8.0], dtype=float).reshape((3, 1, 1))
        sample_y = np.zeros_like(sample_x)
        sample_z = np.full_like(sample_x, 5.0)
        field = tpms_generator._analytic_boundary_field(tube, sample_x, sample_y, sample_z)
        if field is None:
            raise RuntimeError("Tube Part::Cut did not produce an analytical CSG boundary field")
        values = field.ravel().tolist()
        if not (values[0] < 0.0 and values[1] > 0.0 and values[2] < 0.0):
            raise RuntimeError("Tube analytical CSG field classified sample points incorrectly: {}".format(values))

        polydata = tpms_generator.generate_cylindrical_ring_polydata(
            tpms_generator.SURFACE_EQUATIONS["Gyroid"],
            tpms_generator.PART_SHEET,
            (4.0, 2.0, 5.0),
            8,
            0.35,
            (0.0, 0.0, 0.0),
            True,
            (0.0, 0.0, 0.0),
            None,
            1.0,
            7.0,
            10.0,
            10,
            boundary_mode=tpms_generator.BOUNDARY_SELECTED_SOLID,
            boundary_object=tube,
        )
        if polydata.n_points <= 0 or polydata.n_cells <= 0:
            raise RuntimeError("Cylindrical analytical CSG tube boundary generated empty polydata")
        mesh = tpms_generator.polydata_to_freecad_mesh(polydata)
        if mesh.hasNonManifolds():
            raise RuntimeError("Cylindrical analytical CSG tube boundary generated non-manifold mesh")
        print(
            "PASS cylindrical_analytical_csg_tube_boundary facets={} field={}".format(
                int(mesh.CountFacets),
                [round(float(value), 4) for value in values],
            )
        )
    finally:
        App.closeDocument(doc.Name)


def run_basic_tube_boolean_fragments_analytical_case():
    import numpy as np

    tubes = [
        _AnalyticalTubeProbe("TubeA", 2.0, 5.0, 10.0),
        _AnalyticalTubeProbe("TubeB", 5.0, 6.0, 10.0),
    ]
    fragments = _BooleanFragmentsProbe(tubes)
    items = boundary_region_items(fragments)
    if len(items) != 2:
        raise RuntimeError("Analytical tube BooleanFragments did not expose two regions")
    mapped = [getattr(item.get("analytical_object"), "Name", None) for item in items]
    if mapped != ["TubeA", "TubeB"]:
        raise RuntimeError("Analytical tube regions did not map back to source tubes: {}".format(mapped))

    coords = np.array([1.0, 3.0, 5.5, 7.0], dtype=float).reshape((4, 1, 1))
    zeros = np.zeros_like(coords)
    z = np.full_like(coords, 5.0)
    fragment_field = tpms_generator._analytic_boundary_field(fragments, coords, zeros, z, 0.0, 8)
    if fragment_field is None:
        raise RuntimeError("BooleanFragments tube union did not produce an analytical field")
    field_values = [round(float(value), 4) for value in fragment_field.ravel()]
    if not (field_values[0] < 0.0 and field_values[1] > 0.0 and field_values[2] > 0.0 and field_values[3] < 0.0):
        raise RuntimeError("Analytical tube BooleanFragments classified points incorrectly: {}".format(field_values))

    region_specs = [
        {
            "index": int(item["index"]),
            "boundary_object": item["analytical_object"],
            "surface": "Gyroid",
            "part": tpms_generator.PART_SHEET,
            "equation": tpms_generator.SURFACE_EQUATIONS["Gyroid"],
            "offset": 0.35,
            "base_density": 1.0,
        }
        for item in items
    ]
    polydata = tpms_generator.generate_hybrid_polydata(
        tpms_generator.SURFACE_EQUATIONS["Gyroid"],
        tpms_generator.PART_SHEET,
        (4.0, 2.0, 5.0),
        (1, 1, 1),
        8,
        0.35,
        (0.0, 0.0, 0.0),
        tpms_generator.BOUNDARY_SELECTED_SOLID,
        fragments,
        0.0,
        True,
        (0.0, 0.0, 0.0),
        None,
        1.0,
        region_specs,
        [],
        [],
        coordinate_mode=tpms_generator.COORDINATE_CYLINDRICAL_RING,
        ring_angular_cells=10,
    )
    mesh = tpms_generator.polydata_to_freecad_mesh(polydata)
    if mesh.CountFacets <= 0 or mesh.hasNonManifolds():
        raise RuntimeError(
            "Analytical tube BooleanFragments generated invalid mesh: facets={} non_manifold={}".format(
                int(mesh.CountFacets),
                bool(mesh.hasNonManifolds()),
            )
        )
    print(
        "PASS basic_tube_boolean_fragments_analytical mapped={} facets={} solid={} field={}".format(
            mapped,
            int(mesh.CountFacets),
            bool(mesh.isSolid()),
            field_values,
        )
    )


def run_cylindrical_multitube_fragment_case():
    import Part

    doc = App.newDocument("TPMS_cylindrical_multitube_fragment_test")
    try:
        regions = [
            _make_tube_shell(1.0, 3.0, 10.0),
            _make_tube_shell(3.0, 5.0, 10.0),
            _make_tube_shell(5.0, 7.0, 10.0),
        ]
        boundary = doc.addObject("Part::Feature", "Cylindrical_Multitube_BooleanFragments")
        boundary.Label = "Cylindrical Multitube BooleanFragments Equivalent"
        boundary.Shape = Part.makeCompound(regions)
        doc.recompute()

        test_path = os.path.join(STUDY_DIR, "cylindrical_multitube_boolean_fragments.FCStd")
        doc.saveAs(test_path)

        items = boundary_region_items(boundary)
        if len(items) != 3:
            raise RuntimeError("Expected 3 tube regions, got {}".format(len(items)))

        _container, controller, _mesh_obj = make_tpms_unit_cell(doc)
        _configure_fast(controller, boundary)
        controller.Resolution = 8
        controller.AddCaps = True
        controller.CoordinateMode = tpms_generator.COORDINATE_CYLINDRICAL_RING
        controller.CellSize = App.Vector(4.0, 2.0, 5.0)
        controller.RingRadius = 1.0
        controller.RingOuterRadius = 7.0
        controller.RingHeight = 10.0
        controller.RingAngularCells = 10
        controller.BoundaryEvaluation = tpms_generator.BOUNDARY_EVALUATION_ANALYTICAL
        created = add_tpms_region_settings_for_all_regions(controller, skip_existing=True)
        if len(created) != 2:
            raise RuntimeError("Expected 2 added tube-region settings, got {}".format(len(created)))

        doc.recompute()
        mesh_obj = controller.ResultMesh
        if mesh_obj is None or mesh_obj.Mesh.CountFacets <= 0:
            raise RuntimeError("Cylindrical multitube fragment generated an empty mesh")
        non_manifold = bool(mesh_obj.Mesh.hasNonManifolds())
        degenerate = bool(_has_degenerate_facets(mesh_obj.Mesh))
        print(
            "PASS cylindrical_multitube_fragment regions={} created={} facets={} solid={} non_manifold={} degenerate={} file={}".format(
                len(items),
                len(created),
                int(mesh_obj.Mesh.CountFacets),
                bool(mesh_obj.Mesh.isSolid()),
                non_manifold,
                degenerate,
                test_path,
            )
        )
    finally:
        App.closeDocument(doc.Name)


def run_harmonic_density_count_mode_case():
    import hashlib

    path = os.path.join(STUDY_DIR, HARMONIC_DENSITY_FILE)
    doc = App.openDocument(path)
    try:
        controller = None
        for obj in doc.Objects:
            if is_tpms_unit_cell(obj):
                controller = obj
                break
        if controller is None:
            raise RuntimeError("No TPMS controller found in {}".format(path))

        controller.DensityMode = "Non-uniform"
        controller.DensityGradient = tpms_generator.GRADIENT_HARMONIC
        controller.HarmonicBoundaryCondition = tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR
        results = []
        for mode in (tpms_generator.DENSITY_COUNT_FOLLOW, tpms_generator.DENSITY_COUNT_PRESERVE):
            controller.DensityCountMode = mode
            controller.touch()
            doc.recompute()
            mesh_obj = getattr(controller, "ResultMesh", None)
            if mesh_obj is None or mesh_obj.Mesh.CountFacets <= 0:
                raise RuntimeError("{} generated no mesh for {}".format(path, mode))
            sample = [
                (round(point.x, 5), round(point.y, 5), round(point.z, 5))
                for point in mesh_obj.Mesh.Points[:2000]
            ]
            digest = hashlib.sha256(repr(sample).encode("utf-8")).hexdigest()[:16]
            results.append((mode, int(mesh_obj.Mesh.CountFacets), digest))
        if results[0][1:] == results[1][1:]:
            print("WARN harmonic_density_count_mode identical signatures: {}".format(results))
            return
        print(
            "PASS harmonic_density_count_mode follow_facets={} preserve_facets={} follow_hash={} preserve_hash={}".format(
                results[0][1],
                results[1][1],
                results[0][2],
                results[1][2],
            )
        )
    finally:
        App.closeDocument(doc.Name)


def run_region_origin_case():
    import hashlib
    doc = App.newDocument("RegionOriginTest")
    try:
        box1 = doc.addObject("Part::Box", "Box1")
        box1.Length = 10
        box1.Width = 10
        box1.Height = 10
        box2 = doc.addObject("Part::Box", "Box2")
        box2.Length = 10
        box2.Width = 10
        box2.Height = 10
        box2.Placement.Base = App.Vector(10, 0, 0)
        compound = doc.addObject("Part::Compound", "Compound")
        compound.Links = [box1, box2]
        doc.recompute()
        _, controller, _ = make_tpms_unit_cell(doc)
        controller.BoundaryObject = compound
        controller.BoundaryMode = "Selected solid"
        controller.Equation = "cos(x) + cos(y) + cos(z)"
        controller.Resolution = 8
        controller.Offset = 0.5
        controller.RegionMode = "All regions"
        region2, _ = add_tpms_region_settings(controller)
        region2.RegionMode = "Single region"
        region2.RegionIndex = 1
        region2.RegionRole = "Override"
        region2.OriginMode = "Custom XYZ"
        region2.Origin = App.Vector(0.0, 0.0, 0.0)
        doc.recompute()

        mesh1 = controller.ResultMesh.Mesh.copy()
        region2.Origin = App.Vector(2.0, 0.0, 0.0)
        doc.recompute()
        mesh2 = controller.ResultMesh.Mesh.copy()

        def signature(mesh):
            sample = [(round(p.x, 5), round(p.y, 5), round(p.z, 5)) for p in mesh.Points]
            return int(mesh.CountFacets), hashlib.sha256(repr(sample).encode("utf-8")).hexdigest()[:16]

        sig1 = signature(mesh1)
        sig2 = signature(mesh2)
        print("DEBUG sig1: facets={} hash={}".format(sig1[0], sig1[1]))
        print("DEBUG sig2: facets={} hash={}".format(sig2[0], sig2[1]))
        if sig1 == sig2:
            raise RuntimeError("Region origin change did not affect the mesh signature")
        print("PASS region_origin_movement hash1={} hash2={}".format(sig1[1], sig2[1]))
    finally:
        App.closeDocument(doc.Name)


def main():
    for name in TEST_FILES:
        run_file(os.path.join(STUDY_DIR, name))
    run_region_origin_case()
    run_generated_transition_region_case()
    run_region_grading_separation_case()
    run_transition_region_surface_modes_case()
    run_labyrinth_transition_modes_case()
    run_cylindrical_ring_boundary_origin_case()
    run_cylindrical_ring_radial_continuity_case()
    run_hybrid_cylindrical_coordinate_mode_case()
    run_tessellated_boundary_signed_distance_case()
    run_boundary_evaluation_mode_case()
    run_analytical_csg_boundary_case()
    run_cylindrical_analytical_csg_tube_boundary_case()
    run_basic_tube_boolean_fragments_analytical_case()
    run_cylindrical_multitube_fragment_case()
    run_harmonic_density_count_mode_case()


if not getattr(App, "_tpms_boolean_fragment_region_workflow_ran", False):
    App._tpms_boolean_fragment_region_workflow_ran = True
    main()
