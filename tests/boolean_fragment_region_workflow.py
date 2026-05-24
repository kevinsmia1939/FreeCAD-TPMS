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
    _transition_controls,
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
        transition_control_count = 0
        if os.path.basename(path) == "boolean_fragment_density_grading.FCStd" and len(region_settings_before_recompute) >= 2:
            transition_controller = region_settings_before_recompute[0]
            target_controller = region_settings_before_recompute[1]
            transition_controller.RegionRole = REGION_ROLE_TRANSITION
            transition_controller.TransitionMode = "Shared face"
            transition_controller.TransitionSourceRegion = int(getattr(transition_controller, "RegionIndex", 0))
            transition_controller.TransitionTargetRegion = int(getattr(target_controller, "RegionIndex", 0))
            transition_controller.TransitionWidth = 5.0
            transition_controller.Resolution = 37
            target_controller.BaseDensity = 1.8
            target_controller.Offset = 0.8
            transition_density, transition_offset, transition_equation, _transition_gradient = _transition_controls(transition_controller)
            transition_control_count = len(transition_density) + len(transition_offset) + len(transition_equation)
            if transition_control_count <= 0:
                raise RuntimeError("{} transition controller did not detect a shared-face transition".format(path))
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
        if len(single_region) < len(regions):
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
        if not base_description.startswith("Generated {} solid region mesh".format(len(regions))):
            raise RuntimeError(
                "{} base controller did not generate per-region meshes: {}".format(path, base_description)
            )

        region_meshes = list(getattr(controller, "ResultRegionMeshes", []))
        if len(region_meshes) != len(regions):
            raise RuntimeError("{} has {} result meshes for {} regions".format(path, len(region_meshes), len(regions)))
        region_facets = [int(mesh.Mesh.CountFacets) for mesh in region_meshes]
        if any(facets <= 0 for facets in region_facets):
            raise RuntimeError("{} generated empty per-region mesh facets {}".format(path, region_facets))
        print(
            "PASS {} regions={} created={} transition_controls={} region_facets={} main_region='{}' main_bounds={}".format(
                os.path.basename(path),
                len(regions),
                len(created),
                transition_control_count,
                region_facets,
                base_description,
                tuple(round(value, 6) for value in _mesh_bounds(controller.ResultMesh)) if _mesh_facet_count(controller) else (),
            )
        )
    finally:
        App.closeDocument(doc.Name)


def main():
    for name in TEST_FILES:
        run_file(os.path.join(STUDY_DIR, name))


if not getattr(App, "_tpms_boolean_fragment_region_workflow_ran", False):
    App._tpms_boolean_fragment_region_workflow_ran = True
    main()
