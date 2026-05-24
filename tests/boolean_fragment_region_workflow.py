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
    add_tpms_region_settings_for_all_regions,
    boundary_region_items,
    is_tpms_unit_cell,
    make_tpms_unit_cell,
    selected_boundary_region,
)


STUDY_DIR = "/home/kevin/Dropbox/UAntwerp/PhD_thesis/FreeCAD_files/TPMS_study"
TEST_FILES = (
    "boolean_fragment_density_grading.FCStd",
    "boolean_fragment_test2.FCStd",
    "boolean_fragment_test3.FCStd",
)


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
            int(getattr(controller, "RegionIndex", 0))
        } | {
            int(getattr(obj, "RegionIndex", 0))
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


def main():
    for name in TEST_FILES:
        run_file(os.path.join(STUDY_DIR, name))
    run_generated_transition_region_case()
    run_cylindrical_ring_boundary_origin_case()


if not getattr(App, "_tpms_boolean_fragment_region_workflow_ran", False):
    App._tpms_boolean_fragment_region_workflow_ran = True
    main()
