import FreeCAD as App
import Mesh
import Part


REGION_MODE_ALL = "All regions"
REGION_MODE_SINGLE = "Single region"
REGION_ROLE_BASE = "Base"
REGION_ROLE_OVERRIDE = "Override"
REGION_ROLE_TRANSITION = "Transition"
TRANSITION_MODE_NONE = "None"
TRANSITION_MODE_SHARED_FACE = "Shared face"
TRANSITION_MODE_BRIDGE_REGION = "Bridge region"


def make_tpms_unit_cell(doc=None):
    import tpms_generator

    doc = doc or App.ActiveDocument or App.newDocument("TPMS")

    container = doc.addObject("App::Part", "TPMS_Unit_Cell")
    container.Label = "TPMS Unit Cell"

    controller = doc.addObject("Part::FeaturePython", "TPMS_Parameters")
    controller.Label = "TPMS Parameters"
    TPMSUnitCell(controller)
    _set_controller_shape(controller)
    if getattr(controller, "ViewObject", None) is not None:
        TPMSUnitCellViewProvider(controller.ViewObject)
        _configure_controller_view(controller.ViewObject)
    container.addObject(controller)

    mesh_obj = doc.addObject("Mesh::Feature", "TPMS_Mesh")
    mesh_obj.Label = "TPMS Mesh"
    container.addObject(mesh_obj)
    controller.ResultMesh = mesh_obj

    controller.Surface = "Gyroid"
    controller.Part = tpms_generator.PART_SHEET
    controller.Equation = tpms_generator.SURFACE_EQUATIONS["Gyroid"]
    controller.Resolution = 16
    controller.RepeatX = 1
    controller.RepeatY = 1
    controller.RepeatZ = 1
    controller.Offset = 0.3
    controller.CellSize = App.Vector(10.0, 10.0, 10.0)
    controller.Phase = App.Vector(0.0, 0.0, 0.0)
    controller.CoordinateMode = tpms_generator.COORDINATE_CARTESIAN
    controller.RingRadius = 25.0
    controller.RingOuterRadius = 35.0
    controller.RingHeight = 10.0
    controller.RingAngularCells = 8
    controller.OriginMode = "Boundary object"
    controller.Origin = App.Vector(0.0, 0.0, 0.0)
    controller.RotationMode = "Same as origin"
    controller.OriginRotation = App.Vector(0.0, 0.0, 0.0)
    controller.DensityMode = "Uniform"
    controller.DensityGradient = tpms_generator.GRADIENT_FACE_DISTANCE
    controller.BaseDensity = 1.0
    controller.DensityCountMode = tpms_generator.DENSITY_COUNT_FOLLOW
    controller.FaceDensity = 1.5
    controller.DensityTransition = 5.0
    controller.DensityOffsetMode = "Uniform"
    controller.DensityOffsetGradient = tpms_generator.GRADIENT_FACE_DISTANCE
    controller.DensityOffsetValue = 0.3
    controller.DensityOffsetTransition = 5.0
    controller.GradingResolution = 16
    controller.HarmonicBoundaryCondition = tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR
    controller.MeshStitching = False
    controller.BoundaryMode = tpms_generator.BOUNDARY_BOX
    controller.RegionMode = REGION_MODE_ALL
    controller.RegionIndex = 0
    controller.RegionRole = REGION_ROLE_BASE
    controller.BaseExcludesRegionSettings = True
    controller.TransitionMode = TRANSITION_MODE_NONE
    controller.TransitionWidth = 0.0
    controller.TransitionSourceRegion = 0
    controller.TransitionTargetRegion = 0
    controller.Sampling = 0.0
    controller.AddCaps = True
    controller.MeshRelaxation = False
    controller.RelaxIterations = 5
    controller.RelaxSkipBoundary = True
    controller.RelaxCapSurface = False

    doc.recompute()
    return container, controller, mesh_obj


def add_tpms_region_settings(source_controller):
    if not is_tpms_unit_cell(source_controller):
        raise ValueError("Select a TPMS Parameters object first.")

    doc = source_controller.Document
    container = _container_for(source_controller)
    controller, mesh_obj = _make_region_controller(doc, container)
    _copy_tpms_settings(source_controller, controller)
    _configure_region_controller(source_controller, controller, _next_region_index(source_controller))
    return controller, mesh_obj


def add_tpms_region_settings_for_all_regions(source_controller, skip_existing=True):
    if not is_tpms_unit_cell(source_controller):
        raise ValueError("Select a TPMS Parameters object first.")

    items = boundary_region_items(getattr(source_controller, "BoundaryObject", None))
    if not items:
        raise ValueError("The selected TPMS boundary has no solid regions.")

    existing = set()
    if skip_existing:
        existing = _existing_region_indices(source_controller)

    doc = source_controller.Document
    container = _container_for(source_controller)
    created = []
    for item in items:
        index = int(item["index"])
        if index in existing:
            continue
        controller, mesh_obj = _make_region_controller(doc, container)
        _copy_tpms_settings(source_controller, controller)
        _configure_region_controller(source_controller, controller, index)
        created.append((controller, mesh_obj))
    return created


def _make_region_controller(doc, container):
    controller = doc.addObject("Part::FeaturePython", "TPMS_Region_Parameters")
    controller.Label = "TPMS Region Parameters"
    TPMSUnitCell(controller)
    _set_controller_shape(controller)
    if getattr(controller, "ViewObject", None) is not None:
        TPMSUnitCellViewProvider(controller.ViewObject)
        _configure_controller_view(controller.ViewObject)

    if container is not None:
        container.addObject(controller)
    return controller, None


def _configure_region_controller(source_controller, controller, region_index):
    controller.RegionMode = REGION_MODE_SINGLE
    controller.RegionIndex = int(region_index)
    controller.RegionRole = REGION_ROLE_OVERRIDE
    controller.BaseExcludesRegionSettings = True
    controller.TransitionMode = TRANSITION_MODE_NONE
    controller.RegionDescription = _region_label_for_index(getattr(source_controller, "BoundaryObject", None), region_index)
    controller.Label = "TPMS Region {}".format(int(region_index) + 1)


def _copy_tpms_settings(source, target):
    names = (
        "Surface",
        "Equation",
        "Part",
        "RepeatX",
        "RepeatY",
        "RepeatZ",
        "Offset",
        "CellSize",
        "Phase",
        "CoordinateMode",
        "RingRadius",
        "RingOuterRadius",
        "RingHeight",
        "RingAngularCells",
        "OriginMode",
        "Origin",
        "OriginObject",
        "RotationMode",
        "OriginRotation",
        "RotationObject",
        "DensityMode",
        "DensityGradient",
        "BaseDensity",
        "DensityCountMode",
        "FaceDensity",
        "DensityTransition",
        "FaceControls",
        "DensityOffsetMode",
        "DensityOffsetGradient",
        "DensityOffsetValue",
        "DensityOffsetTransition",
        "DensityOffsetControls",
        "GradingResolution",
        "HarmonicBoundaryCondition",
        "MeshStitching",
        "BoundaryMode",
        "BoundaryObject",
        "Sampling",
        "AddCaps",
        "MeshRelaxation",
        "RelaxIterations",
        "RelaxSkipBoundary",
        "RelaxCapSurface",
    )
    for name in names:
        if hasattr(source, name) and hasattr(target, name):
            try:
                setattr(target, name, getattr(source, name))
            except Exception:
                pass


def _next_region_index(source_controller):
    items = boundary_region_items(getattr(source_controller, "BoundaryObject", None))
    if not items:
        return 0
    used = _existing_region_indices(source_controller)
    for item in items:
        if item["index"] not in used:
            return item["index"]
    return items[-1]["index"]


def _existing_region_indices(source_controller):
    used = set()
    container = _container_for(source_controller)
    for obj in getattr(source_controller.Document, "Objects", []):
        if not is_tpms_unit_cell(obj):
            continue
        if container is not None and _container_for(obj) != container:
            continue
        if getattr(obj, "BoundaryObject", None) != getattr(source_controller, "BoundaryObject", None):
            continue
        if str(getattr(obj, "RegionMode", REGION_MODE_ALL)) == REGION_MODE_SINGLE:
            used.add(int(getattr(obj, "RegionIndex", 0)))
    return used


def _region_setting_indices(controller, roles=None):
    boundary = getattr(controller, "BoundaryObject", None)
    container = _container_for(controller)
    roles = set(roles or (REGION_ROLE_OVERRIDE, REGION_ROLE_TRANSITION))
    indices = set()
    for obj in getattr(controller.Document, "Objects", []):
        if obj is controller or not is_tpms_unit_cell(obj):
            continue
        if container is not None and _container_for(obj) != container:
            continue
        if getattr(obj, "BoundaryObject", None) != boundary:
            continue
        if str(getattr(obj, "RegionMode", REGION_MODE_ALL)) != REGION_MODE_SINGLE:
            continue
        if str(getattr(obj, "RegionRole", REGION_ROLE_OVERRIDE)) in roles:
            indices.add(int(getattr(obj, "RegionIndex", 0)))
    return indices


def _base_controller_for(controller):
    container = _container_for(controller)
    boundary = getattr(controller, "BoundaryObject", None)
    fallback = None
    for obj in getattr(controller.Document, "Objects", []):
        if not is_tpms_unit_cell(obj):
            continue
        if container is not None and _container_for(obj) != container:
            continue
        if getattr(obj, "BoundaryObject", None) != boundary:
            continue
        if obj is controller:
            fallback = obj
        if (
            str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) == REGION_ROLE_BASE
            and str(getattr(obj, "RegionMode", REGION_MODE_ALL)) == REGION_MODE_ALL
        ):
            return obj
    return fallback or controller


def _region_controller_for(controller, region_index, roles=None):
    container = _container_for(controller)
    boundary = getattr(controller, "BoundaryObject", None)
    roles = set(roles or (REGION_ROLE_OVERRIDE, REGION_ROLE_TRANSITION))
    for obj in getattr(controller.Document, "Objects", []):
        if obj is controller or not is_tpms_unit_cell(obj):
            continue
        if container is not None and _container_for(obj) != container:
            continue
        if getattr(obj, "BoundaryObject", None) != boundary:
            continue
        if str(getattr(obj, "RegionMode", REGION_MODE_ALL)) != REGION_MODE_SINGLE:
            continue
        if int(getattr(obj, "RegionIndex", -1)) != int(region_index):
            continue
        if str(getattr(obj, "RegionRole", REGION_ROLE_OVERRIDE)) in roles:
            return obj
    return None


def _effective_resolution(controller):
    base = _base_controller_for(controller)
    if base is not controller:
        resolution = max(4, int(getattr(base, "Resolution", getattr(controller, "Resolution", 16))))
        try:
            controller.Resolution = resolution
        except Exception:
            pass
        return resolution
    return max(4, int(getattr(controller, "Resolution", 16)))


def _sync_region_resolutions_from_base(base_controller):
    if str(getattr(base_controller, "RegionRole", REGION_ROLE_BASE)) != REGION_ROLE_BASE:
        return
    resolution = max(4, int(getattr(base_controller, "Resolution", 16)))
    container = _container_for(base_controller)
    boundary = getattr(base_controller, "BoundaryObject", None)
    for obj in getattr(base_controller.Document, "Objects", []):
        if obj is base_controller or not is_tpms_unit_cell(obj):
            continue
        if container is not None and _container_for(obj) != container:
            continue
        if getattr(obj, "BoundaryObject", None) != boundary:
            continue
        if str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) == REGION_ROLE_BASE:
            continue
        try:
            obj.Resolution = resolution
            obj.touch()
        except Exception:
            pass


def _region_label_for_index(boundary_object, region_index):
    index = int(region_index)
    for item in boundary_region_items(boundary_object):
        if int(item["index"]) == index:
            return item["label"]
    return "Region {}".format(index + 1)


class TPMSUnitCell:
    Type = "TPMS::UnitCell"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        import tpms_generator

        region_role_added = not hasattr(obj, "RegionRole")
        if not hasattr(obj, "Surface"):
            obj.addProperty("App::PropertyEnumeration", "Surface", "TPMS", "Preset TPMS equation")
            obj.Surface = tpms_generator.surface_names() + ["Custom"]
        if not hasattr(obj, "Equation"):
            obj.addProperty("App::PropertyString", "Equation", "TPMS", "Implicit equation using x, y, z")
        if not hasattr(obj, "Part"):
            obj.addProperty("App::PropertyEnumeration", "Part", "TPMS", "Generated region")
            obj.Part = [tpms_generator.PART_SHEET, tpms_generator.PART_UPPER, tpms_generator.PART_LOWER]
        if not hasattr(obj, "Resolution"):
            obj.addProperty("App::PropertyInteger", "Resolution", "TPMS", "Grid cells per unit cell axis")
        if not hasattr(obj, "RepeatX"):
            obj.addProperty("App::PropertyInteger", "RepeatX", "TPMS Array", "Unit cells in X")
            obj.setEditorMode("RepeatX", 2)
        if not hasattr(obj, "RepeatY"):
            obj.addProperty("App::PropertyInteger", "RepeatY", "TPMS Array", "Unit cells in Y")
            obj.setEditorMode("RepeatY", 2)
        if not hasattr(obj, "RepeatZ"):
            obj.addProperty("App::PropertyInteger", "RepeatZ", "TPMS Array", "Unit cells in Z")
            obj.setEditorMode("RepeatZ", 2)
        if not hasattr(obj, "Offset"):
            obj.addProperty("App::PropertyFloat", "Offset", "TPMS", "Sheet thickness or skeletal iso spacing")
        if not hasattr(obj, "CellSize"):
            obj.addProperty("App::PropertyVector", "CellSize", "TPMS", "Unit-cell size in X/Y/Z")
        if not hasattr(obj, "Phase"):
            obj.addProperty("App::PropertyVector", "Phase", "TPMS", "Phase shift in document units")
        if not hasattr(obj, "CoordinateMode"):
            obj.addProperty("App::PropertyEnumeration", "CoordinateMode", "TPMS", "Coordinate system used for TPMS generation")
            obj.CoordinateMode = tpms_generator.coordinate_modes()
            obj.CoordinateMode = tpms_generator.COORDINATE_CARTESIAN
        if not hasattr(obj, "RingRadius"):
            obj.addProperty("App::PropertyFloat", "RingRadius", "TPMS", "Cylindrical ring inner radius")
            obj.RingRadius = 25.0
        if not hasattr(obj, "RingOuterRadius"):
            obj.addProperty("App::PropertyFloat", "RingOuterRadius", "TPMS", "Cylindrical ring outer radius")
            obj.RingOuterRadius = float(getattr(obj, "RingRadius", 25.0)) + float(getattr(obj, "RingRadialThickness", 10.0))
        if hasattr(obj, "RingRadialThickness"):
            obj.setEditorMode("RingRadialThickness", 2)
        if not hasattr(obj, "RingHeight"):
            obj.addProperty("App::PropertyFloat", "RingHeight", "TPMS", "Cylindrical ring height")
            obj.RingHeight = 10.0
        if not hasattr(obj, "RingAngularCells"):
            obj.addProperty("App::PropertyInteger", "RingAngularCells", "TPMS", "TPMS periods around the cylindrical ring")
            obj.RingAngularCells = 8
        if not hasattr(obj, "OriginMode"):
            obj.addProperty("App::PropertyEnumeration", "OriginMode", "TPMS", "How to choose the TPMS phase origin")
            obj.OriginMode = ["Boundary object", "Custom XYZ", "Datum point"]
            obj.OriginMode = "Boundary object"
        if not hasattr(obj, "Origin"):
            obj.addProperty("App::PropertyVector", "Origin", "TPMS", "Custom TPMS phase origin")
            obj.Origin = App.Vector(0.0, 0.0, 0.0)
        if not hasattr(obj, "OriginObject"):
            obj.addProperty("App::PropertyXLink", "OriginObject", "TPMS", "Datum point or object placement used as TPMS phase origin")
        if not hasattr(obj, "RotationMode"):
            obj.addProperty("App::PropertyEnumeration", "RotationMode", "TPMS", "How to choose the TPMS phase-frame rotation")
            obj.RotationMode = ["Same as origin", "Boundary object", "Custom XYZ", "Datum point"]
            obj.RotationMode = "Same as origin"
        if not hasattr(obj, "OriginRotation"):
            obj.addProperty("App::PropertyVector", "OriginRotation", "TPMS", "Custom TPMS phase-frame rotation in XYZ degrees")
            obj.OriginRotation = App.Vector(0.0, 0.0, 0.0)
        if not hasattr(obj, "RotationObject"):
            obj.addProperty("App::PropertyXLink", "RotationObject", "TPMS", "Datum point or object placement used as TPMS phase-frame rotation")
        if hasattr(obj, "RotateWithBoundary"):
            obj.setEditorMode("RotateWithBoundary", 2)
        if not hasattr(obj, "DensityMode"):
            obj.addProperty("App::PropertyEnumeration", "DensityMode", "Grading", "How TPMS unit-cell density is controlled")
            obj.DensityMode = ["Uniform", "Non-uniform"]
            obj.DensityMode = "Uniform"
        if not hasattr(obj, "DensityGradient"):
            obj.addProperty("App::PropertyEnumeration", "DensityGradient", "Grading", "Source of the non-uniform unit-cell density field")
        try:
            current_density_gradient = str(obj.DensityGradient)
            gradients = [tpms_generator.GRADIENT_FACE_DISTANCE, tpms_generator.GRADIENT_FACE_PLANE, tpms_generator.GRADIENT_HARMONIC]
            obj.DensityGradient = gradients
            obj.DensityGradient = current_density_gradient if current_density_gradient in gradients else tpms_generator.GRADIENT_FACE_DISTANCE
        except Exception:
            pass
        if not hasattr(obj, "BaseDensity"):
            obj.addProperty("App::PropertyFloat", "BaseDensity", "Grading", "Base TPMS unit-cell density multiplier")
            obj.BaseDensity = 1.0
        if not hasattr(obj, "DensityCountMode"):
            obj.addProperty("App::PropertyEnumeration", "DensityCountMode", "Grading", "How non-uniform unit-cell density affects total TPMS cell count")
            obj.DensityCountMode = [tpms_generator.DENSITY_COUNT_FOLLOW, tpms_generator.DENSITY_COUNT_PRESERVE]
            obj.DensityCountMode = tpms_generator.DENSITY_COUNT_FOLLOW
        if not hasattr(obj, "FaceDensity"):
            obj.addProperty("App::PropertyFloat", "FaceDensity", "Grading", "Default unit-cell density multiplier for new selected-face controls")
            obj.FaceDensity = 1.5
        if not hasattr(obj, "DensityTransition"):
            obj.addProperty("App::PropertyFloat", "DensityTransition", "Grading", "Default transition distance for new selected-face controls")
            obj.DensityTransition = 5.0
        if not hasattr(obj, "FaceControls"):
            obj.addProperty("App::PropertyLinkList", "FaceControls", "Grading", "Selected-face TPMS unit-cell density controls")
        if not hasattr(obj, "DensityOffsetMode"):
            obj.addProperty("App::PropertyEnumeration", "DensityOffsetMode", "Grading", "How sheet/skeletal thickness is graded")
            obj.DensityOffsetMode = ["Uniform", "Non-uniform"]
            obj.DensityOffsetMode = "Uniform"
        if not hasattr(obj, "DensityOffsetGradient"):
            obj.addProperty("App::PropertyEnumeration", "DensityOffsetGradient", "Grading", "Source of the non-uniform thickness field")
            obj.DensityOffsetGradient = [tpms_generator.GRADIENT_FACE_DISTANCE, tpms_generator.GRADIENT_FACE_PLANE, tpms_generator.GRADIENT_HARMONIC]
            obj.DensityOffsetGradient = tpms_generator.GRADIENT_FACE_DISTANCE
        else:
            try:
                current_offset_gradient = str(obj.DensityOffsetGradient)
                gradients = [tpms_generator.GRADIENT_FACE_DISTANCE, tpms_generator.GRADIENT_FACE_PLANE, tpms_generator.GRADIENT_HARMONIC]
                obj.DensityOffsetGradient = gradients
                obj.DensityOffsetGradient = current_offset_gradient if current_offset_gradient in gradients else tpms_generator.GRADIENT_FACE_DISTANCE
            except Exception:
                pass
        if not hasattr(obj, "DensityOffsetValue"):
            obj.addProperty("App::PropertyFloat", "DensityOffsetValue", "Grading", "Target thickness near selected faces")
            obj.DensityOffsetValue = 0.3
        if not hasattr(obj, "DensityOffsetTransition"):
            obj.addProperty("App::PropertyFloat", "DensityOffsetTransition", "Grading", "Default transition distance for thickness controls")
            obj.DensityOffsetTransition = 5.0
        if not hasattr(obj, "DensityOffsetControls"):
            obj.addProperty("App::PropertyLinkList", "DensityOffsetControls", "Grading", "Selected-face TPMS thickness controls")
        if not hasattr(obj, "GradingResolution"):
            obj.addProperty("App::PropertyInteger", "GradingResolution", "Grading", "Grid cells along the longest axis for harmonic grading; 0 uses TPMS resolution")
            obj.GradingResolution = 16
        if not hasattr(obj, "HarmonicBoundaryCondition"):
            obj.addProperty("App::PropertyEnumeration", "HarmonicBoundaryCondition", "Grading", "How unselected boundary faces behave in harmonic grading")
            obj.HarmonicBoundaryCondition = [tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR, tpms_generator.HARMONIC_BOUNDARY_INSULATOR]
            obj.HarmonicBoundaryCondition = tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR
        if not hasattr(obj, "MeshStitching"):
            obj.addProperty("App::PropertyBool", "MeshStitching", "TPMS Array", "Stitch repeated mesh boundaries")
            obj.MeshStitching = False
        if not hasattr(obj, "BoundaryMode"):
            obj.addProperty("App::PropertyEnumeration", "BoundaryMode", "TPMS", "Boundary used to clip the generated TPMS")
            obj.BoundaryMode = tpms_generator.boundary_modes()
        if not hasattr(obj, "BoundaryObject"):
            obj.addProperty("App::PropertyXLink", "BoundaryObject", "TPMS", "Selected solid or mesh used as boundary")
        if not hasattr(obj, "RegionMode"):
            obj.addProperty("App::PropertyEnumeration", "RegionMode", "TPMS", "Region selection for multi-solid boundaries")
            obj.RegionMode = [REGION_MODE_ALL, REGION_MODE_SINGLE]
            obj.RegionMode = REGION_MODE_ALL
        if not hasattr(obj, "RegionIndex"):
            obj.addProperty("App::PropertyInteger", "RegionIndex", "TPMS", "Zero-based solid region index inside a multi-solid boundary")
            obj.RegionIndex = 0
        if not hasattr(obj, "RegionRole"):
            obj.addProperty("App::PropertyEnumeration", "RegionRole", "TPMS", "How this TPMS setting participates in multi-region generation")
            obj.RegionRole = [REGION_ROLE_BASE, REGION_ROLE_OVERRIDE, REGION_ROLE_TRANSITION]
            obj.RegionRole = REGION_ROLE_BASE
        if not hasattr(obj, "BaseExcludesRegionSettings"):
            obj.addProperty("App::PropertyBool", "BaseExcludesRegionSettings", "TPMS", "Base all-region generation skips regions with override or transition settings")
            obj.BaseExcludesRegionSettings = True
        if not hasattr(obj, "TransitionMode"):
            obj.addProperty("App::PropertyEnumeration", "TransitionMode", "Transition", "How transition TPMS is defined")
            obj.TransitionMode = [TRANSITION_MODE_NONE, TRANSITION_MODE_SHARED_FACE, TRANSITION_MODE_BRIDGE_REGION]
            obj.TransitionMode = TRANSITION_MODE_NONE
        if not hasattr(obj, "TransitionWidth"):
            obj.addProperty("App::PropertyFloat", "TransitionWidth", "Transition", "Transition width near shared region faces")
            obj.TransitionWidth = 0.0
        if not hasattr(obj, "TransitionSourceRegion"):
            obj.addProperty("App::PropertyInteger", "TransitionSourceRegion", "Transition", "Source region index for bridge transition")
            obj.TransitionSourceRegion = 0
        if not hasattr(obj, "TransitionTargetRegion"):
            obj.addProperty("App::PropertyInteger", "TransitionTargetRegion", "Transition", "Target region index for bridge transition")
            obj.TransitionTargetRegion = 0
        if not hasattr(obj, "RegionCount"):
            obj.addProperty("App::PropertyInteger", "RegionCount", "Result", "Detected solid region count in the boundary")
            obj.setEditorMode("RegionCount", 1)
        if not hasattr(obj, "RegionDescription"):
            obj.addProperty("App::PropertyString", "RegionDescription", "Result", "Current boundary region used for generation")
            obj.setEditorMode("RegionDescription", 1)
        if not hasattr(obj, "Sampling"):
            obj.addProperty("App::PropertyFloat", "Sampling", "TPMS", "Target grid resolution along the longest sampled axis; 0 uses Resolution")
            obj.Sampling = 0.0
        if not hasattr(obj, "AddCaps"):
            obj.addProperty("App::PropertyBool", "AddCaps", "TPMS", "Add caps where TPMS intersects the boundary")
            obj.AddCaps = True
        if not hasattr(obj, "MeshRelaxation"):
            obj.addProperty("App::PropertyBool", "MeshRelaxation", "Relaxation", "Apply Lloyd-style mesh relaxation")
            obj.MeshRelaxation = False
        if not hasattr(obj, "RelaxIterations"):
            obj.addProperty("App::PropertyInteger", "RelaxIterations", "Relaxation", "Lloyd-style relaxation iterations")
            obj.RelaxIterations = 5
        if not hasattr(obj, "RelaxSkipBoundary"):
            obj.addProperty("App::PropertyBool", "RelaxSkipBoundary", "Relaxation", "Keep boundary/cap vertices fixed during relaxation")
            obj.RelaxSkipBoundary = True
        if not hasattr(obj, "RelaxCapSurface"):
            obj.addProperty("App::PropertyBool", "RelaxCapSurface", "Relaxation", "Allow cap vertices to relax tangentially while keeping seam fixed")
            obj.RelaxCapSurface = False
        if not hasattr(obj, "ResultMesh"):
            obj.addProperty("App::PropertyLink", "ResultMesh", "TPMS", "Generated mesh object")
        if not hasattr(obj, "ResultRegionMeshes"):
            obj.addProperty("App::PropertyLinkList", "ResultRegionMeshes", "TPMS", "Generated per-region mesh objects")
        if not hasattr(obj, "FacetCount"):
            obj.addProperty("App::PropertyInteger", "FacetCount", "Result", "Generated triangle count")
            obj.setEditorMode("FacetCount", 1)
        if not hasattr(obj, "IsSolidMesh"):
            obj.addProperty("App::PropertyBool", "IsSolidMesh", "Result", "Whether FreeCAD reports the generated mesh as solid")
            obj.setEditorMode("IsSolidMesh", 1)
        if not hasattr(obj, "HasNonManifolds"):
            obj.addProperty("App::PropertyBool", "HasNonManifolds", "Result", "Whether FreeCAD reports non-manifold mesh points")
            obj.setEditorMode("HasNonManifolds", 1)
        if not hasattr(obj, "LastError"):
            obj.addProperty("App::PropertyString", "LastError", "Result", "Last generation error")
            obj.setEditorMode("LastError", 1)
        for prop in ("RepeatX", "RepeatY", "RepeatZ", "MeshStitching"):
            if hasattr(obj, prop):
                obj.setEditorMode(prop, 2)
        if region_role_added and str(getattr(obj, "RegionMode", REGION_MODE_ALL)) == REGION_MODE_SINGLE:
            obj.RegionRole = REGION_ROLE_OVERRIDE
        _sync_resolution_editor_mode(obj)
        if _is_region_setting(obj):
            _clear_region_setting_links(obj)

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def onChanged(self, obj, prop):
        if prop == "Surface" and getattr(obj, "Surface", "") != "Custom":
            try:
                import tpms_generator

                obj.Equation = tpms_generator.SURFACE_EQUATIONS[str(obj.Surface)]
            except Exception:
                pass
        if prop in ("RegionRole", "RegionMode"):
            _sync_resolution_editor_mode(obj)
        if prop == "Resolution" and str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) == REGION_ROLE_BASE:
            _sync_region_resolutions_from_base(obj)
        if prop == "Resolution" and str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) != REGION_ROLE_BASE:
            base = _base_controller_for(obj)
            resolution = max(4, int(getattr(base, "Resolution", getattr(obj, "Resolution", 16))))
            if int(getattr(obj, "Resolution", resolution)) != resolution:
                try:
                    obj.Resolution = resolution
                except Exception:
                    pass

    def execute(self, obj):
        import tpms_generator

        try:
            if _is_region_setting(obj):
                _clear_region_setting_mesh(obj)
                return

            mesh_obj = getattr(obj, "ResultMesh", None)
            if mesh_obj is None:
                mesh_obj = obj.Document.addObject("Mesh::Feature", "TPMS_Mesh")
                mesh_obj.Label = "TPMS Mesh"
                obj.ResultMesh = mesh_obj

            if _uses_per_region_meshes(obj):
                _execute_per_region_meshes(obj, mesh_obj, tpms_generator)
                return

            resolution = _effective_resolution(obj)
            repeat_cell = (1, 1, 1)
            cell_size = _vector_tuple(obj.CellSize, fallback=(10.0, 10.0, 10.0), minimum=1e-9)
            phase = _vector_tuple(obj.Phase, fallback=(0.0, 0.0, 0.0), minimum=None)
            origin = _origin_tuple(obj)
            origin_rotation = _origin_rotation(obj)
            unit_cell_controls = _unit_cell_controls(obj)
            density_offset_controls = _density_offset_controls(obj)
            transition_unit_cell_controls, transition_offset_controls, transition_equation_controls, transition_gradient = _transition_controls(obj)
            if transition_unit_cell_controls:
                unit_cell_controls = list(unit_cell_controls) + transition_unit_cell_controls
            if transition_offset_controls:
                density_offset_controls = list(density_offset_controls) + transition_offset_controls
            effective_base_density = max(0.05, float(getattr(obj, "BaseDensity", 1.0)))
            effective_offset = float(getattr(obj, "Offset", 0.3))
            transition_source = _transition_endpoint_controller(obj, "source")
            effective_equation = str(getattr(obj, "Equation", ""))
            if (transition_unit_cell_controls or transition_offset_controls or transition_equation_controls) and transition_source is not None:
                effective_base_density = max(0.05, float(getattr(transition_source, "BaseDensity", effective_base_density)))
                effective_offset = float(getattr(transition_source, "Offset", effective_offset))
                effective_equation = str(getattr(transition_source, "Equation", effective_equation))
            boundary_object, region_description, region_count = selected_boundary_region(obj)
            obj.RegionCount = int(region_count)
            obj.RegionDescription = region_description
            if boundary_object is None and str(getattr(obj, "BoundaryMode", "")) == tpms_generator.BOUNDARY_SELECTED_SOLID:
                mesh_obj.Mesh = Mesh.Mesh()
                obj.FacetCount = 0
                obj.IsSolidMesh = False
                obj.HasNonManifolds = False
                obj.LastError = ""
                return
            mesh = tpms_generator.generate_freecad_mesh(
                effective_equation,
                str(obj.Part),
                cell_size,
                repeat_cell,
                resolution,
                float(obj.Offset),
                phase,
                bool(getattr(obj, "MeshStitching", False)),
                str(getattr(obj, "BoundaryMode", tpms_generator.BOUNDARY_BOX)),
                boundary_object,
                max(0.0, float(getattr(obj, "Sampling", 0.0))),
                bool(getattr(obj, "AddCaps", True)),
                bool(getattr(obj, "MeshRelaxation", False)),
                max(0, int(getattr(obj, "RelaxIterations", 5))),
                bool(getattr(obj, "RelaxSkipBoundary", True)),
                bool(getattr(obj, "RelaxCapSurface", False)),
                origin,
                origin_rotation,
                "Non-uniform" if transition_unit_cell_controls else str(getattr(obj, "DensityMode", "Uniform")),
                effective_base_density,
                unit_cell_controls,
                str(getattr(obj, "DensityCountMode", tpms_generator.DENSITY_COUNT_FOLLOW)),
                transition_gradient if transition_unit_cell_controls else str(getattr(obj, "DensityGradient", tpms_generator.GRADIENT_FACE_DISTANCE)),
                "Non-uniform" if transition_offset_controls else str(getattr(obj, "DensityOffsetMode", "Uniform")),
                effective_offset,
                density_offset_controls,
                transition_gradient if transition_offset_controls else str(getattr(obj, "DensityOffsetGradient", tpms_generator.GRADIENT_FACE_DISTANCE)),
                transition_equation_controls,
                str(getattr(obj, "CoordinateMode", tpms_generator.COORDINATE_CARTESIAN)),
                max(1e-9, float(getattr(obj, "RingRadius", 25.0))),
                max(1e-9, float(getattr(obj, "RingOuterRadius", float(getattr(obj, "RingRadius", 25.0)) + float(getattr(obj, "RingRadialThickness", 10.0))))),
                max(1e-9, float(getattr(obj, "RingHeight", 10.0))),
                max(1, int(getattr(obj, "RingAngularCells", 8))),
                max(0, int(getattr(obj, "GradingResolution", 16))),
                str(getattr(obj, "HarmonicBoundaryCondition", tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR)),
            )
        except Exception as exc:
            obj.LastError = str(exc)
            App.Console.PrintError("TPMS generation failed: {}\n".format(exc))
            return

        mesh_obj.Mesh = mesh
        mesh_obj.Label = "TPMS Mesh"
        _set_controller_shape(obj)
        obj.FacetCount = int(mesh.CountFacets)
        obj.IsSolidMesh = bool(mesh.isSolid())
        obj.HasNonManifolds = bool(mesh.hasNonManifolds())
        obj.LastError = ""


class TPMSUnitCellViewProvider:
    def __init__(self, view_obj):
        view_obj.Proxy = self
        _configure_controller_view(view_obj)

    def getIcon(self):
        import os
        import GyroidAssemblerUtils

        return os.path.join(GyroidAssemblerUtils.MOD_PATH, "icons", "TPMSAssembler.svg")

    def attach(self, view_obj):
        self.Object = view_obj.Object
        _configure_controller_view(view_obj)

    def doubleClicked(self, view_obj):
        try:
            import FreeCADGui as Gui
            from ui.task_tpms import TPMSTaskPanel

            Gui.Control.showDialog(TPMSTaskPanel(view_obj.Object))
            return True
        except Exception as exc:
            App.Console.PrintError("Unable to open TPMS task panel: {}\n".format(exc))
            return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_tpms_unit_cell(obj):
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, TPMSUnitCell)


class _ShapeBoundaryAdapter:
    TypeId = "TPMS::BoundaryRegion"

    def __init__(self, shape, label, region_solids=None):
        self.Shape = shape
        self.Label = label
        self.Name = label
        self.Placement = App.Placement()
        self.ForceTessellatedBoundary = True
        if region_solids is not None:
            self.BoundaryRegionSolids = list(region_solids)


def boundary_region_solids(boundary_object):
    shape = getattr(boundary_object, "Shape", None)
    if shape is None or shape.isNull():
        return []
    solids = list(getattr(shape, "Solids", []))
    if solids:
        return solids
    try:
        if shape.ShapeType == "Solid":
            return [shape]
    except Exception:
        pass
    return []


def boundary_region_items(boundary_object):
    items = []
    for index, solid in enumerate(boundary_region_solids(boundary_object)):
        bb = solid.BoundBox
        try:
            center = solid.CenterOfMass
            center_text = "center {:.3f}, {:.3f}, {:.3f}".format(float(center.x), float(center.y), float(center.z))
        except Exception:
            center_text = "center unavailable"
        try:
            volume_text = "volume {:.3f}".format(float(solid.Volume))
        except Exception:
            volume_text = "volume unavailable"
        items.append(
            {
                "index": index,
                "label": "Region {} ({}, {}, size {:.3f} x {:.3f} x {:.3f})".format(
                    index + 1,
                    volume_text,
                    center_text,
                    float(bb.XLength),
                    float(bb.YLength),
                    float(bb.ZLength),
                ),
                "solid": solid,
            }
        )
    return items


def selected_boundary_region(controller):
    boundary = getattr(controller, "BoundaryObject", None)
    items = boundary_region_items(boundary)
    if str(getattr(controller, "RegionMode", REGION_MODE_ALL)) != REGION_MODE_SINGLE or len(items) <= 1:
        if len(items) > 1:
            active_items = items
            skipped = set()
            if (
                str(getattr(controller, "RegionRole", REGION_ROLE_BASE)) == REGION_ROLE_BASE
                and bool(getattr(controller, "BaseExcludesRegionSettings", True))
            ):
                skipped = _region_setting_indices(controller)
                active_items = [item for item in items if int(item["index"]) not in skipped]
            if not active_items:
                return None, "Base has no unassigned regions; {} region setting(s) cover all regions".format(len(skipped)), len(items)
            description = "All {} regions".format(len(active_items))
            if skipped:
                description = "{}; skipped {} override/transition region(s)".format(description, len(skipped))
            return (
                _ShapeBoundaryAdapter(
                    boundary.Shape,
                    description,
                    [item["solid"] for item in active_items],
                ),
                description,
                len(items),
            )
        if len(items) == 1:
            return _ShapeBoundaryAdapter(items[0]["solid"], "Region 1"), "Region 1", 1
        return boundary, "No solid regions detected", 0

    index = max(0, min(int(getattr(controller, "RegionIndex", 0)), len(items) - 1))
    item = items[index]
    return _ShapeBoundaryAdapter(item["solid"], item["label"]), item["label"], len(items)


def _is_region_setting(obj):
    return (
        str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) != REGION_ROLE_BASE
        or str(getattr(obj, "RegionMode", REGION_MODE_ALL)) == REGION_MODE_SINGLE
    )


def _uses_per_region_meshes(obj):
    import tpms_generator

    if str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) != REGION_ROLE_BASE:
        return False
    if str(getattr(obj, "RegionMode", REGION_MODE_ALL)) != REGION_MODE_ALL:
        return False
    if str(getattr(obj, "BoundaryMode", "")) != tpms_generator.BOUNDARY_SELECTED_SOLID:
        return False
    return len(boundary_region_items(getattr(obj, "BoundaryObject", None))) > 1


def _clear_region_setting_mesh(obj):
    _clear_region_setting_links(obj)
    obj.FacetCount = 0
    obj.IsSolidMesh = False
    obj.HasNonManifolds = False
    obj.LastError = ""


def _clear_region_setting_links(obj):
    mesh_obj = getattr(obj, "ResultMesh", None)
    if mesh_obj is not None:
        try:
            obj.ResultMesh = None
        except Exception:
            pass
    if hasattr(obj, "ResultRegionMeshes"):
        try:
            obj.ResultRegionMeshes = []
        except Exception:
            pass


def _execute_per_region_meshes(base, primary_mesh_obj, tpms_generator):
    _sync_region_resolutions_from_base(base)
    items = boundary_region_items(getattr(base, "BoundaryObject", None))
    meshes = _ensure_region_result_meshes(base, primary_mesh_obj, len(items))
    total_facets = 0
    any_non_manifold = False
    all_solid = True
    errors = []

    for item in items:
        index = int(item["index"])
        setting = _region_generation_setting(base, index)
        mesh_obj = meshes[index]
        try:
            mesh = _generate_region_mesh(base, setting, item, items, tpms_generator)
        except Exception as exc:
            mesh = Mesh.Mesh()
            errors.append("Region {}: {}".format(index + 1, exc))
        mesh_obj.Mesh = mesh
        mesh_obj.Label = "TPMS Mesh Region {}".format(index + 1)
        total_facets += int(mesh.CountFacets)
        if int(mesh.CountFacets) > 0:
            all_solid = all_solid and bool(mesh.isSolid())
            any_non_manifold = any_non_manifold or bool(mesh.hasNonManifolds())

    base.ResultRegionMeshes = meshes
    base.RegionCount = len(items)
    base.RegionDescription = "Generated {} solid region mesh(es)".format(len(items))
    base.FacetCount = int(total_facets)
    base.IsSolidMesh = bool(total_facets > 0 and all_solid)
    base.HasNonManifolds = bool(any_non_manifold)
    base.LastError = "; ".join(errors)
    if errors:
        App.Console.PrintError("TPMS region generation failed: {}\n".format(base.LastError))


def _ensure_region_result_meshes(base, primary_mesh_obj, count):
    doc = base.Document
    container = _container_for(base)
    meshes = list(getattr(base, "ResultRegionMeshes", []))
    ordered = []
    if primary_mesh_obj is not None:
        ordered.append(primary_mesh_obj)
    for mesh in meshes:
        if mesh is not None and mesh not in ordered:
            ordered.append(mesh)
    while len(ordered) < int(count):
        mesh = doc.addObject("Mesh::Feature", "TPMS_Mesh_Region_{}".format(len(ordered) + 1))
        mesh.Label = "TPMS Mesh Region {}".format(len(ordered) + 1)
        if container is not None:
            container.addObject(mesh)
        ordered.append(mesh)
    return ordered[: int(count)]


def _region_generation_setting(base, region_index):
    transition = _region_controller_for(base, region_index, roles=(REGION_ROLE_TRANSITION,))
    if transition is not None:
        return transition
    override = _region_controller_for(base, region_index, roles=(REGION_ROLE_OVERRIDE,))
    if override is not None:
        return override
    return base


def _generate_region_mesh(base, setting, item, items, tpms_generator):
    resolution = max(4, int(getattr(base, "Resolution", 16)))
    cell_size = _vector_tuple(getattr(setting, "CellSize", getattr(base, "CellSize", App.Vector(10.0, 10.0, 10.0))), fallback=(10.0, 10.0, 10.0), minimum=1e-9)
    phase = _vector_tuple(getattr(setting, "Phase", getattr(base, "Phase", App.Vector(0.0, 0.0, 0.0))), fallback=(0.0, 0.0, 0.0), minimum=None)
    boundary = _ShapeBoundaryAdapter(item["solid"], item["label"])
    unit_cell_controls = _unit_cell_controls(setting)
    offset_controls = _density_offset_controls(setting)
    transition_unit, transition_offset, transition_equation, transition_gradient = _region_transition_controls(base, setting, item, items)
    if transition_unit:
        unit_cell_controls = list(unit_cell_controls) + transition_unit
    if transition_offset:
        offset_controls = list(offset_controls) + transition_offset

    source = _transition_endpoint_controller(setting, "source") if str(getattr(setting, "RegionRole", REGION_ROLE_BASE)) == REGION_ROLE_TRANSITION else setting
    if source is None:
        source = setting
    equation = str(getattr(source, "Equation", getattr(setting, "Equation", getattr(base, "Equation", ""))))
    base_density = max(0.05, float(getattr(source, "BaseDensity", getattr(setting, "BaseDensity", getattr(base, "BaseDensity", 1.0)))))
    offset = float(getattr(source, "Offset", getattr(setting, "Offset", getattr(base, "Offset", 0.3))))

    return tpms_generator.generate_freecad_mesh(
        equation,
        str(getattr(source, "Part", getattr(setting, "Part", getattr(base, "Part", tpms_generator.PART_SHEET)))),
        cell_size,
        (1, 1, 1),
        resolution,
        offset,
        phase,
        bool(getattr(base, "MeshStitching", False)),
        tpms_generator.BOUNDARY_SELECTED_SOLID,
        boundary,
        max(0.0, float(getattr(base, "Sampling", 0.0))),
        bool(getattr(base, "AddCaps", True)),
        bool(getattr(base, "MeshRelaxation", False)),
        max(0, int(getattr(base, "RelaxIterations", 5))),
        bool(getattr(base, "RelaxSkipBoundary", True)),
        bool(getattr(base, "RelaxCapSurface", False)),
        _origin_tuple(base),
        _origin_rotation(base),
        "Non-uniform" if transition_unit else str(getattr(setting, "DensityMode", getattr(base, "DensityMode", "Uniform"))),
        base_density,
        unit_cell_controls,
        str(getattr(setting, "DensityCountMode", getattr(base, "DensityCountMode", tpms_generator.DENSITY_COUNT_FOLLOW))),
        transition_gradient if transition_unit else str(getattr(setting, "DensityGradient", getattr(base, "DensityGradient", tpms_generator.GRADIENT_FACE_DISTANCE))),
        "Non-uniform" if transition_offset else str(getattr(setting, "DensityOffsetMode", getattr(base, "DensityOffsetMode", "Uniform"))),
        offset,
        offset_controls,
        transition_gradient if transition_offset else str(getattr(setting, "DensityOffsetGradient", getattr(base, "DensityOffsetGradient", tpms_generator.GRADIENT_FACE_DISTANCE))),
        transition_equation,
        str(getattr(base, "CoordinateMode", tpms_generator.COORDINATE_CARTESIAN)),
        max(1e-9, float(getattr(base, "RingRadius", 25.0))),
        max(1e-9, float(getattr(base, "RingOuterRadius", float(getattr(base, "RingRadius", 25.0)) + float(getattr(base, "RingRadialThickness", 10.0))))),
        max(1e-9, float(getattr(base, "RingHeight", 10.0))),
        max(1, int(getattr(base, "RingAngularCells", 8))),
        max(0, int(getattr(base, "GradingResolution", 16))),
        str(getattr(base, "HarmonicBoundaryCondition", tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR)),
    )


def _region_transition_controls(base, setting, item, items):
    import tpms_generator

    if str(getattr(setting, "RegionRole", REGION_ROLE_BASE)) == REGION_ROLE_TRANSITION:
        return _transition_controls(setting)

    index = int(item["index"])
    solid = item["solid"]
    width = _shared_transition_width(base, index, None)
    density_controls = []
    offset_controls = []
    equation_controls = []
    gradient = tpms_generator.GRADIENT_FACE_DISTANCE
    for other in items:
        other_index = int(other["index"])
        if other_index == index:
            continue
        other_setting = _region_generation_setting(base, other_index)
        if other_setting is setting:
            continue
        pair_width = _shared_transition_width(base, index, other_index)
        if pair_width <= 0.0 and _same_tpms_region_settings(setting, other_setting):
            continue
        density, offset, equation = _transition_controls_for_touching_faces(
            solid,
            other["solid"],
            other_setting,
            pair_width if pair_width > 0.0 else width,
        )
        density_controls.extend(density)
        offset_controls.extend(offset)
        equation_controls.extend(equation)
    return density_controls, offset_controls, equation_controls, gradient


def _same_tpms_region_settings(left, right):
    return (
        str(getattr(left, "Equation", "")) == str(getattr(right, "Equation", ""))
        and abs(float(getattr(left, "BaseDensity", 1.0)) - float(getattr(right, "BaseDensity", 1.0))) <= 1e-9
        and abs(float(getattr(left, "Offset", 0.3)) - float(getattr(right, "Offset", 0.3))) <= 1e-9
    )


def _shared_transition_width(base, region_a, region_b):
    width = 0.0
    container = _container_for(base)
    boundary = getattr(base, "BoundaryObject", None)
    for obj in getattr(base.Document, "Objects", []):
        if not is_tpms_unit_cell(obj):
            continue
        if container is not None and _container_for(obj) != container:
            continue
        if getattr(obj, "BoundaryObject", None) != boundary:
            continue
        if str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) != REGION_ROLE_TRANSITION:
            continue
        if str(getattr(obj, "TransitionMode", TRANSITION_MODE_NONE)) != TRANSITION_MODE_SHARED_FACE:
            continue
        source = int(getattr(obj, "TransitionSourceRegion", -1))
        target = int(getattr(obj, "TransitionTargetRegion", -1))
        pair_matches = region_b is None or {int(region_a), int(region_b)} == {source, target}
        if pair_matches and int(region_a) in (source, target, int(getattr(obj, "RegionIndex", -2))):
            width = max(width, float(getattr(obj, "TransitionWidth", 0.0)))
    if width > 0.0:
        return width
    try:
        return max(1e-9, 0.5 * min(_vector_tuple(getattr(base, "CellSize", App.Vector(10.0, 10.0, 10.0)), (10.0, 10.0, 10.0), 1e-9)))
    except Exception:
        return 5.0


class TPMSFaceDensityControl:
    Type = "TPMS::FaceDensityControl"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        if not hasattr(obj, "Enabled"):
            obj.addProperty("App::PropertyBool", "Enabled", "Unit cell density", "Use this face unit-cell density control")
            obj.Enabled = True
        if not hasattr(obj, "SourceObject"):
            obj.addProperty("App::PropertyXLink", "SourceObject", "Unit cell density", "Solid object containing the selected face")
        if not hasattr(obj, "FaceNames"):
            obj.addProperty("App::PropertyStringList", "FaceNames", "Unit cell density", "Selected subelement face names")
        if not hasattr(obj, "DensityFactor"):
            obj.addProperty("App::PropertyFloat", "DensityFactor", "Unit cell density", "Target unit-cell density multiplier near the selected face")
            obj.DensityFactor = 1.5
        if not hasattr(obj, "Transition"):
            obj.addProperty("App::PropertyFloat", "Transition", "Unit cell density", "Transition distance away from the selected face")
            obj.Transition = 5.0

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def onChanged(self, obj, prop):
        if prop in ("Enabled", "SourceObject", "FaceNames", "DensityFactor", "Transition"):
            _touch_linked_tpms_controllers(obj)

    def execute(self, obj):
        _set_controller_shape(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class TPMSFaceDensityControlViewProvider:
    def __init__(self, view_obj):
        view_obj.Proxy = self
        _configure_controller_view(view_obj)

    def getIcon(self):
        import os
        import GyroidAssemblerUtils

        return os.path.join(GyroidAssemblerUtils.MOD_PATH, "icons", "TPMSAssembler.svg")

    def attach(self, view_obj):
        self.Object = view_obj.Object
        _configure_controller_view(view_obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def add_face_density_control(controller, source_object, face_names, density=None, transition=None):
    doc = controller.Document
    control = doc.addObject("Part::FeaturePython", "TPMS_Unit_Cell_Density")
    control.Label = "TPMS Unit Cell Density {}".format(",".join(face_names))
    TPMSFaceDensityControl(control)
    _set_controller_shape(control)
    if getattr(control, "ViewObject", None) is not None:
        TPMSFaceDensityControlViewProvider(control.ViewObject)
        _configure_controller_view(control.ViewObject)

    control.SourceObject = source_object
    control.FaceNames = list(face_names)
    control.DensityFactor = float(density if density is not None else getattr(controller, "FaceDensity", 1.5))
    control.Transition = float(transition if transition is not None else getattr(controller, "DensityTransition", 5.0))

    parent = _container_for(controller)
    if parent is not None:
        parent.addObject(control)

    controls = list(getattr(controller, "FaceControls", []))
    controls.append(control)
    controller.FaceControls = controls
    return control


class TPMSOffsetDensityControl:
    Type = "TPMS::OffsetDensityControl"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        if not hasattr(obj, "Enabled"):
            obj.addProperty("App::PropertyBool", "Enabled", "Sheet/skeletal thickness", "Use this thickness control")
            obj.Enabled = True
        if not hasattr(obj, "SourceObject"):
            obj.addProperty("App::PropertyXLink", "SourceObject", "Sheet/skeletal thickness", "Solid object containing the selected face")
        if not hasattr(obj, "FaceNames"):
            obj.addProperty("App::PropertyStringList", "FaceNames", "Sheet/skeletal thickness", "Selected subelement face names")
        if not hasattr(obj, "OffsetValue"):
            obj.addProperty("App::PropertyFloat", "OffsetValue", "Sheet/skeletal thickness", "Target thickness near the selected face")
            obj.OffsetValue = 0.3
        if not hasattr(obj, "Transition"):
            obj.addProperty("App::PropertyFloat", "Transition", "Sheet/skeletal thickness", "Transition distance away from the selected face")
            obj.Transition = 5.0

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def onChanged(self, obj, prop):
        if prop in ("Enabled", "SourceObject", "FaceNames", "OffsetValue", "Transition"):
            _touch_linked_tpms_controllers(obj)

    def execute(self, obj):
        _set_controller_shape(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class TPMSOffsetDensityControlViewProvider:
    def __init__(self, view_obj):
        view_obj.Proxy = self
        _configure_controller_view(view_obj)

    def getIcon(self):
        import os
        import GyroidAssemblerUtils

        return os.path.join(GyroidAssemblerUtils.MOD_PATH, "icons", "TPMSAssembler.svg")

    def attach(self, view_obj):
        self.Object = view_obj.Object
        _configure_controller_view(view_obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def add_offset_density_control(controller, source_object, face_names, offset_value=None, transition=None):
    doc = controller.Document
    control = doc.addObject("Part::FeaturePython", "TPMS_Thickness")
    control.Label = "TPMS Thickness {}".format(",".join(face_names))
    TPMSOffsetDensityControl(control)
    _set_controller_shape(control)
    if getattr(control, "ViewObject", None) is not None:
        TPMSOffsetDensityControlViewProvider(control.ViewObject)
        _configure_controller_view(control.ViewObject)

    control.SourceObject = source_object
    control.FaceNames = list(face_names)
    control.OffsetValue = float(offset_value if offset_value is not None else getattr(controller, "DensityOffsetValue", 0.3))
    control.Transition = float(transition if transition is not None else getattr(controller, "DensityOffsetTransition", 5.0))

    parent = _container_for(controller)
    if parent is not None:
        parent.addObject(control)

    controls = list(getattr(controller, "DensityOffsetControls", []))
    controls.append(control)
    controller.DensityOffsetControls = controls
    return control


class TPMSGradingControl:
    Type = "TPMS::GradingControl"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        if not hasattr(obj, "Enabled"):
            obj.addProperty("App::PropertyBool", "Enabled", "Grading", "Use this grading control")
            obj.Enabled = True
        if not hasattr(obj, "SourceObject"):
            obj.addProperty("App::PropertyXLink", "SourceObject", "Grading", "Solid object containing the selected face")
        if not hasattr(obj, "FaceNames"):
            obj.addProperty("App::PropertyStringList", "FaceNames", "Grading", "Selected subelement face names")
        if not hasattr(obj, "UseUnitCellDensity"):
            obj.addProperty("App::PropertyBool", "UseUnitCellDensity", "Unit cell density", "Use this control for unit-cell density")
            obj.UseUnitCellDensity = True
        if not hasattr(obj, "DensityFactor"):
            obj.addProperty("App::PropertyFloat", "DensityFactor", "Unit cell density", "Target unit-cell density multiplier near the selected face")
            obj.DensityFactor = 1.5
        if not hasattr(obj, "UnitCellTransition"):
            obj.addProperty("App::PropertyFloat", "UnitCellTransition", "Unit cell density", "Transition distance away from the selected face")
            obj.UnitCellTransition = 5.0
        if not hasattr(obj, "UseThickness"):
            obj.addProperty("App::PropertyBool", "UseThickness", "Sheet/skeletal thickness", "Use this control for sheet/skeletal thickness")
            obj.UseThickness = True
        if not hasattr(obj, "OffsetValue"):
            obj.addProperty("App::PropertyFloat", "OffsetValue", "Sheet/skeletal thickness", "Target thickness near the selected face")
            obj.OffsetValue = 0.3
        if not hasattr(obj, "ThicknessTransition"):
            obj.addProperty("App::PropertyFloat", "ThicknessTransition", "Sheet/skeletal thickness", "Transition distance away from the selected face")
            obj.ThicknessTransition = 5.0

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def onChanged(self, obj, prop):
        if prop in (
            "Enabled",
            "SourceObject",
            "FaceNames",
            "UseUnitCellDensity",
            "DensityFactor",
            "UnitCellTransition",
            "UseThickness",
            "OffsetValue",
            "ThicknessTransition",
        ):
            _sync_controller_grading_modes(obj, prop)
            _touch_linked_tpms_controllers(obj)

    def execute(self, obj):
        _set_controller_shape(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class TPMSGradingControlViewProvider:
    def __init__(self, view_obj):
        view_obj.Proxy = self
        _configure_controller_view(view_obj)

    def getIcon(self):
        import os
        import GyroidAssemblerUtils

        return os.path.join(GyroidAssemblerUtils.MOD_PATH, "icons", "TPMSAssembler.svg")

    def attach(self, view_obj):
        self.Object = view_obj.Object
        _configure_controller_view(view_obj)

    def doubleClicked(self, view_obj):
        try:
            import FreeCADGui as Gui
            from ui.task_grading import TPMSGradingTaskPanel

            Gui.Control.showDialog(TPMSGradingTaskPanel(view_obj.Object))
            return True
        except Exception as exc:
            App.Console.PrintError("Unable to open TPMS grading task panel: {}\n".format(exc))
            return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def add_grading_control(
    controller,
    source_object,
    face_names,
    unit_cell_density=None,
    unit_cell_transition=None,
    thickness=None,
    thickness_transition=None,
    use_unit_cell_density=True,
    use_thickness=True,
):
    doc = controller.Document
    control = doc.addObject("Part::FeaturePython", "TPMS_Grading")
    control.Label = "TPMS Grading {}".format(",".join(face_names))
    TPMSGradingControl(control)
    _set_controller_shape(control)
    if getattr(control, "ViewObject", None) is not None:
        TPMSGradingControlViewProvider(control.ViewObject)
        _configure_controller_view(control.ViewObject)

    control.SourceObject = source_object
    control.FaceNames = list(face_names)
    control.UseUnitCellDensity = bool(use_unit_cell_density)
    control.DensityFactor = float(unit_cell_density if unit_cell_density is not None else getattr(controller, "FaceDensity", 1.5))
    control.UnitCellTransition = float(unit_cell_transition if unit_cell_transition is not None else getattr(controller, "DensityTransition", 5.0))
    control.UseThickness = bool(use_thickness)
    control.OffsetValue = float(thickness if thickness is not None else getattr(controller, "DensityOffsetValue", 0.3))
    control.ThicknessTransition = float(thickness_transition if thickness_transition is not None else getattr(controller, "DensityOffsetTransition", 5.0))

    parent = _container_for(controller)
    if parent is not None:
        parent.addObject(control)

    controls = list(getattr(controller, "FaceControls", []))
    if control not in controls:
        controls.append(control)
        controller.FaceControls = controls

    controls = list(getattr(controller, "DensityOffsetControls", []))
    if control not in controls:
        controls.append(control)
        controller.DensityOffsetControls = controls

    if control.UseUnitCellDensity:
        controller.DensityMode = "Non-uniform"
    if control.UseThickness:
        controller.DensityOffsetMode = "Non-uniform"
    try:
        controller.touch()
    except Exception:
        pass
    return control


def _vector_tuple(vector, fallback, minimum=None):
    try:
        values = (float(vector.x), float(vector.y), float(vector.z))
    except Exception:
        values = fallback
    if minimum is None:
        return values
    return tuple(max(minimum, value) for value in values)


def _origin_tuple(obj):
    mode = str(getattr(obj, "OriginMode", "Boundary object"))
    if mode == "Datum point":
        origin_object = getattr(obj, "OriginObject", None)
        placement = getattr(origin_object, "Placement", None)
        if placement is not None:
            base = placement.Base
            return (float(base.x), float(base.y), float(base.z))
    if mode == "Custom XYZ":
        return _vector_tuple(getattr(obj, "Origin", App.Vector(0.0, 0.0, 0.0)), (0.0, 0.0, 0.0), None)
    return None


def _origin_rotation(obj):
    rotation_mode = str(getattr(obj, "RotationMode", "Same as origin"))
    mode = rotation_mode
    if rotation_mode == "Same as origin":
        mode = str(getattr(obj, "OriginMode", "Boundary object"))
        if mode == "Custom XYZ":
            return _vector_tuple(getattr(obj, "OriginRotation", App.Vector(0.0, 0.0, 0.0)), (0.0, 0.0, 0.0), None)
    if mode == "Boundary object":
        boundary = getattr(obj, "BoundaryObject", None)
        placement = getattr(boundary, "Placement", None)
        if placement is not None:
            return placement.Rotation
        return None
    if mode == "Datum point":
        if rotation_mode == "Same as origin":
            rotation_object = getattr(obj, "OriginObject", None)
        else:
            rotation_object = getattr(obj, "RotationObject", None)
        placement = getattr(rotation_object, "Placement", None)
        if placement is not None:
            return placement.Rotation
        return None
    if mode == "Custom XYZ":
        return _vector_tuple(getattr(obj, "OriginRotation", App.Vector(0.0, 0.0, 0.0)), (0.0, 0.0, 0.0), None)
    return None


def _unit_cell_controls(obj):
    if str(getattr(obj, "DensityMode", "Uniform")) != "Non-uniform":
        return []
    import tpms_generator

    gradient = str(getattr(obj, "DensityGradient", tpms_generator.GRADIENT_FACE_DISTANCE))
    controls = []
    for control in getattr(obj, "FaceControls", []):
        if control is None or not bool(getattr(control, "Enabled", True)):
            continue
        if hasattr(control, "UseUnitCellDensity") and not bool(getattr(control, "UseUnitCellDensity", True)):
            continue
        source = getattr(control, "SourceObject", None)
        shape = getattr(source, "Shape", None)
        if shape is None or shape.isNull():
            continue
        for face_name in getattr(control, "FaceNames", []):
            try:
                face = shape.getElement(str(face_name))
                point, normal = _face_point_normal(face)
                surface = _face_surface_mesh(face) if gradient in (tpms_generator.GRADIENT_FACE_DISTANCE, tpms_generator.GRADIENT_HARMONIC) else None
            except Exception as exc:
                App.Console.PrintWarning(
                    "Ignoring TPMS density control {} {}: {}\n".format(
                        getattr(source, "Label", getattr(source, "Name", "Object")),
                        face_name,
                        exc,
                    )
                )
                continue
            controls.append(
                {
                    "type": "face_distance" if surface is not None else "face_plane",
                    "point": point,
                    "normal": normal,
                    "density": max(0.05, float(getattr(control, "DensityFactor", 1.0))),
                    "transition": max(1e-9, float(getattr(control, "UnitCellTransition", getattr(control, "Transition", 1.0)))),
                    "surface": surface,
                }
            )
    return controls


def _density_offset_controls(obj):
    if str(getattr(obj, "DensityOffsetMode", "Uniform")) != "Non-uniform":
        return []
    import tpms_generator

    gradient = str(getattr(obj, "DensityOffsetGradient", tpms_generator.GRADIENT_FACE_DISTANCE))
    controls = []
    for control in getattr(obj, "DensityOffsetControls", []):
        if control is None or not bool(getattr(control, "Enabled", True)):
            continue
        if hasattr(control, "UseThickness") and not bool(getattr(control, "UseThickness", True)):
            continue
        source = getattr(control, "SourceObject", None)
        shape = getattr(source, "Shape", None)
        if shape is None or shape.isNull():
            continue
        for face_name in getattr(control, "FaceNames", []):
            try:
                face = shape.getElement(str(face_name))
                point, normal = _face_point_normal(face)
                surface = _face_surface_mesh(face) if gradient in (tpms_generator.GRADIENT_FACE_DISTANCE, tpms_generator.GRADIENT_HARMONIC) else None
            except Exception as exc:
                App.Console.PrintWarning(
                    "Ignoring TPMS thickness control {} {}: {}\n".format(
                        getattr(source, "Label", getattr(source, "Name", "Object")),
                        face_name,
                        exc,
                    )
                )
                continue
            controls.append(
                {
                    "type": "face_distance" if surface is not None else "face_plane",
                    "point": point,
                    "normal": normal,
                    "offset": float(getattr(control, "OffsetValue", getattr(obj, "Offset", 0.3))),
                    "transition": max(1e-9, float(getattr(control, "ThicknessTransition", getattr(control, "Transition", 1.0)))),
                    "surface": surface,
                }
            )
    return controls


def _transition_endpoint_controller(obj, side):
    if str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) != REGION_ROLE_TRANSITION:
        return None
    if str(getattr(obj, "TransitionMode", TRANSITION_MODE_NONE)) == TRANSITION_MODE_NONE:
        return None
    if side == "source":
        index = int(getattr(obj, "TransitionSourceRegion", 0))
    else:
        index = int(getattr(obj, "TransitionTargetRegion", 0))
    if str(getattr(obj, "RegionMode", REGION_MODE_ALL)) == REGION_MODE_SINGLE and index == int(getattr(obj, "RegionIndex", -1)):
        return obj
    return _region_controller_for(obj, index) or _base_controller_for(obj)


def _transition_controls(obj):
    import tpms_generator

    if str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) != REGION_ROLE_TRANSITION:
        return [], [], [], tpms_generator.GRADIENT_FACE_DISTANCE
    mode = str(getattr(obj, "TransitionMode", TRANSITION_MODE_NONE))
    if mode == TRANSITION_MODE_NONE:
        return [], [], [], tpms_generator.GRADIENT_FACE_DISTANCE
    if str(getattr(obj, "RegionMode", REGION_MODE_ALL)) != REGION_MODE_SINGLE:
        return [], [], [], tpms_generator.GRADIENT_FACE_DISTANCE

    items = boundary_region_items(getattr(obj, "BoundaryObject", None))
    selected_index = int(getattr(obj, "RegionIndex", 0))
    selected_solid = _region_solid_from_items(items, selected_index)
    if selected_solid is None:
        return [], [], [], tpms_generator.GRADIENT_FACE_DISTANCE

    source_index = int(getattr(obj, "TransitionSourceRegion", selected_index))
    target_index = int(getattr(obj, "TransitionTargetRegion", 0))
    source_solid = _region_solid_from_items(items, source_index)
    target_solid = _region_solid_from_items(items, target_index)
    source_setting = _transition_endpoint_controller(obj, "source") or obj
    target_setting = _transition_endpoint_controller(obj, "target") or _base_controller_for(obj)

    width = float(getattr(obj, "TransitionWidth", 0.0))
    if width <= 0.0:
        width = max(
            float(getattr(obj, "DensityTransition", 0.0)),
            float(getattr(obj, "DensityOffsetTransition", 0.0)),
            min(_vector_tuple(getattr(obj, "CellSize", App.Vector(10.0, 10.0, 10.0)), (10.0, 10.0, 10.0), 1e-9)) * 0.5,
        )
    width = max(width, 1e-9)

    density_controls = []
    offset_controls = []
    equation_controls = []
    if mode == TRANSITION_MODE_BRIDGE_REGION:
        if source_solid is not None:
            density, offset, equation = _transition_controls_for_touching_faces(selected_solid, source_solid, source_setting, width)
            density_controls.extend(density)
            offset_controls.extend(offset)
            equation_controls.extend(equation)
        if target_solid is not None:
            density, offset, equation = _transition_controls_for_touching_faces(selected_solid, target_solid, target_setting, width)
            density_controls.extend(density)
            offset_controls.extend(offset)
            equation_controls.extend(equation)
        return density_controls, offset_controls, equation_controls, tpms_generator.GRADIENT_HARMONIC

    # Shared-face mode creates a local transition band near the face shared by
    # the selected region and the opposite endpoint region.
    if selected_index == source_index and target_solid is not None:
        density, offset, equation = _transition_controls_for_touching_faces(selected_solid, target_solid, target_setting, width)
        density_controls.extend(density)
        offset_controls.extend(offset)
        equation_controls.extend(equation)
    elif selected_index == target_index and source_solid is not None:
        density, offset, equation = _transition_controls_for_touching_faces(selected_solid, source_solid, source_setting, width)
        density_controls.extend(density)
        offset_controls.extend(offset)
        equation_controls.extend(equation)
    else:
        for other_solid, setting in ((source_solid, source_setting), (target_solid, target_setting)):
            if other_solid is None:
                continue
            density, offset, equation = _transition_controls_for_touching_faces(selected_solid, other_solid, setting, width)
            density_controls.extend(density)
            offset_controls.extend(offset)
            equation_controls.extend(equation)
    return density_controls, offset_controls, equation_controls, tpms_generator.GRADIENT_FACE_DISTANCE


def _region_solid_from_items(items, region_index):
    for item in items:
        if int(item["index"]) == int(region_index):
            return item["solid"]
    return None


def _transition_controls_for_touching_faces(solid, other_solid, setting, transition_width):
    density_controls = []
    offset_controls = []
    equation_controls = []
    for face in _faces_touching_solid(solid, other_solid):
        try:
            point, normal = _face_point_normal(face)
            surface = _face_surface_mesh(face)
        except Exception as exc:
            App.Console.PrintWarning("Ignoring transition face: {}\n".format(exc))
            continue
        density_controls.append(
            {
                "type": "face_distance",
                "point": point,
                "normal": normal,
                "density": max(0.05, float(getattr(setting, "BaseDensity", 1.0))),
                "transition": float(transition_width),
                "surface": surface,
            }
        )
        offset_controls.append(
            {
                "type": "face_distance",
                "point": point,
                "normal": normal,
                "offset": float(getattr(setting, "Offset", 0.3)),
                "transition": float(transition_width),
                "surface": surface,
            }
        )
        equation = str(getattr(setting, "Equation", "")).strip()
        if equation:
            equation_controls.append(
                {
                    "type": "face_distance",
                    "point": point,
                    "normal": normal,
                    "equation": equation,
                    "transition": float(transition_width),
                    "surface": surface,
                }
            )
    return density_controls, offset_controls, equation_controls


def _faces_touching_solid(solid, other_solid):
    if solid is None or other_solid is None:
        return []
    tolerance = _shape_tolerance(solid)
    faces = []
    for face in getattr(solid, "Faces", []):
        try:
            distance = float(face.distToShape(other_solid)[0])
        except Exception:
            continue
        if distance <= tolerance:
            faces.append(face)
    return faces


def _shape_tolerance(shape):
    try:
        bb = shape.BoundBox
        diagonal = (float(bb.XLength) ** 2 + float(bb.YLength) ** 2 + float(bb.ZLength) ** 2) ** 0.5
    except Exception:
        diagonal = 1.0
    return max(diagonal * 1e-6, 1e-6)


def _sync_resolution_editor_mode(obj):
    if not hasattr(obj, "Resolution"):
        return
    try:
        mode = 0 if str(getattr(obj, "RegionRole", REGION_ROLE_BASE)) == REGION_ROLE_BASE else 1
        obj.setEditorMode("Resolution", mode)
    except Exception:
        pass


def _face_point_normal(face):
    point = face.CenterOfMass
    try:
        umin, umax, vmin, vmax = face.ParameterRange
        normal = face.normalAt(0.5 * (umin + umax), 0.5 * (vmin + vmax))
    except Exception:
        normal = face.Surface.Axis
    length = normal.Length
    if length <= 1e-12:
        raise ValueError("selected face has no usable normal")
    normal.normalize()
    return (
        (float(point.x), float(point.y), float(point.z)),
        (float(normal.x), float(normal.y), float(normal.z)),
    )


def _face_surface_mesh(face):
    bb = face.BoundBox
    span = max(float(bb.XLength), float(bb.YLength), float(bb.ZLength), 1e-9)
    points, triangles = face.tessellate(span / 80.0)
    if not points or not triangles:
        raise ValueError("selected face could not be tessellated")
    return {
        "points": [(float(point.x), float(point.y), float(point.z)) for point in points],
        "triangles": [tuple(int(index) for index in triangle) for triangle in triangles],
    }


def _container_for(obj):
    for parent in getattr(obj, "InList", []):
        if hasattr(parent, "addObject") and hasattr(parent, "Group"):
            return parent
    return None


def _linked_tpms_controllers(control):
    doc = getattr(control, "Document", None)
    if doc is None:
        return []
    controllers = []
    control_container = _container_for(control)
    for obj in getattr(doc, "Objects", []):
        if not is_tpms_unit_cell(obj):
            continue
        if control_container is not None and _container_for(obj) == control_container:
            controllers.append(obj)
            continue
        for prop in ("FaceControls", "DensityOffsetControls"):
            try:
                if control in list(getattr(obj, prop, [])):
                    controllers.append(obj)
                    break
            except Exception:
                continue
    return controllers


def _touch_linked_tpms_controllers(control):
    for controller in _linked_tpms_controllers(control):
        try:
            controller.touch()
        except Exception:
            pass
        if _is_region_setting(controller):
            continue
        mesh = getattr(controller, "ResultMesh", None)
        if mesh is not None:
            try:
                mesh.touch()
            except Exception:
                pass


def _sync_controller_grading_modes(control, prop):
    if prop == "UseUnitCellDensity" and not bool(getattr(control, "UseUnitCellDensity", False)):
        return
    if prop == "UseThickness" and not bool(getattr(control, "UseThickness", False)):
        return
    for controller in _linked_tpms_controllers(control):
        try:
            if hasattr(control, "UseUnitCellDensity") and bool(getattr(control, "UseUnitCellDensity", False)):
                controls = list(getattr(controller, "FaceControls", []))
                if control not in controls:
                    controls.append(control)
                    controller.FaceControls = controls
                controller.DensityMode = "Non-uniform"
            if hasattr(control, "UseThickness") and bool(getattr(control, "UseThickness", False)):
                controls = list(getattr(controller, "DensityOffsetControls", []))
                if control not in controls:
                    controls.append(control)
                    controller.DensityOffsetControls = controls
                controller.DensityOffsetMode = "Non-uniform"
        except Exception:
            pass


def _configure_controller_view(view_obj):
    try:
        view_obj.Visibility = True
    except Exception:
        pass
    try:
        view_obj.Selectable = True
    except Exception:
        pass


def _set_controller_shape(obj):
    if not hasattr(obj, "Shape"):
        return
    try:
        obj.Shape = Part.makeCompound([])
    except Exception:
        pass
