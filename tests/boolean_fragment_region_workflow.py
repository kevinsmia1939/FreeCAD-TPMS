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
            description = str(getattr(obj, "RegionDescription", ""))
            base_can_be_empty = (
                obj is controller
                and role == REGION_ROLE_BASE
                and description.startswith("Base has no unassigned regions")
            )
            if facets <= 0 and not base_can_be_empty:
                raise RuntimeError("{} generated an empty mesh".format(obj.Label))

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
        if len(covered_regions) >= len(regions) and not base_description.startswith("Base has no unassigned regions"):
            raise RuntimeError(
                "{} base controller did not skip covered regions: {}".format(path, base_description)
            )

        override_facets = sum(_mesh_facet_count(obj) for obj in single_region)
        print(
            "PASS {} regions={} created={} main_facets={} override_facets={} main_region='{}' main_bounds={}".format(
                os.path.basename(path),
                len(regions),
                len(created),
                _mesh_facet_count(controller),
                override_facets,
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
