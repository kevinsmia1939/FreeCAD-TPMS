import FreeCAD as App
import Part


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
    controller.OriginMode = "Boundary object"
    controller.Origin = App.Vector(0.0, 0.0, 0.0)
    controller.RotationMode = "Same as origin"
    controller.OriginRotation = App.Vector(0.0, 0.0, 0.0)
    controller.DensityMode = "Uniform"
    controller.BaseDensity = 1.0
    controller.FaceDensity = 1.5
    controller.DensityTransition = 5.0
    controller.MeshStitching = False
    controller.BoundaryMode = tpms_generator.BOUNDARY_BOX
    controller.Sampling = 0.0
    controller.AddCaps = True
    controller.MeshRelaxation = False
    controller.RelaxIterations = 5
    controller.RelaxSkipBoundary = True
    controller.RelaxCapSurface = False

    doc.recompute()
    return container, controller, mesh_obj


class TPMSUnitCell:
    Type = "TPMS::UnitCell"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        import tpms_generator

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
            obj.addProperty("App::PropertyEnumeration", "DensityMode", "Density", "How TPMS cell density is controlled")
            obj.DensityMode = ["Uniform", "Non-uniform"]
            obj.DensityMode = "Uniform"
        if not hasattr(obj, "BaseDensity"):
            obj.addProperty("App::PropertyFloat", "BaseDensity", "Density", "Base TPMS density multiplier")
            obj.BaseDensity = 1.0
        if not hasattr(obj, "FaceDensity"):
            obj.addProperty("App::PropertyFloat", "FaceDensity", "Density", "Default density multiplier for new selected-face controls")
            obj.FaceDensity = 1.5
        if not hasattr(obj, "DensityTransition"):
            obj.addProperty("App::PropertyFloat", "DensityTransition", "Density", "Default transition distance for new selected-face controls")
            obj.DensityTransition = 5.0
        if not hasattr(obj, "FaceControls"):
            obj.addProperty("App::PropertyLinkList", "FaceControls", "Density", "Selected-face TPMS density controls")
        if not hasattr(obj, "MeshStitching"):
            obj.addProperty("App::PropertyBool", "MeshStitching", "TPMS Array", "Stitch repeated mesh boundaries")
            obj.MeshStitching = False
        if not hasattr(obj, "BoundaryMode"):
            obj.addProperty("App::PropertyEnumeration", "BoundaryMode", "Boundary", "Boundary used to clip the generated TPMS")
            obj.BoundaryMode = tpms_generator.boundary_modes()
        if not hasattr(obj, "BoundaryObject"):
            obj.addProperty("App::PropertyXLink", "BoundaryObject", "Boundary", "Selected solid or mesh used as boundary")
        if not hasattr(obj, "Sampling"):
            obj.addProperty("App::PropertyFloat", "Sampling", "Boundary", "Target grid resolution along the longest sampled axis; 0 uses Resolution")
            obj.Sampling = 0.0
        if not hasattr(obj, "AddCaps"):
            obj.addProperty("App::PropertyBool", "AddCaps", "Boundary", "Add caps where TPMS intersects the boundary")
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

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

    def onChanged(self, obj, prop):
        if prop == "Surface" and getattr(obj, "Surface", "") != "Custom":
            try:
                import tpms_generator

                obj.Equation = tpms_generator.SURFACE_EQUATIONS[str(obj.Surface)]
            except Exception:
                pass

    def execute(self, obj):
        import tpms_generator

        mesh_obj = getattr(obj, "ResultMesh", None)
        if mesh_obj is None:
            mesh_obj = obj.Document.addObject("Mesh::Feature", "TPMS_Mesh")
            mesh_obj.Label = "TPMS Mesh"
            obj.ResultMesh = mesh_obj

        try:
            resolution = max(4, int(obj.Resolution))
            repeat_cell = (1, 1, 1)
            cell_size = _vector_tuple(obj.CellSize, fallback=(10.0, 10.0, 10.0), minimum=1e-9)
            phase = _vector_tuple(obj.Phase, fallback=(0.0, 0.0, 0.0), minimum=None)
            origin = _origin_tuple(obj)
            origin_rotation = _origin_rotation(obj)
            density_controls = _density_controls(obj)
            mesh = tpms_generator.generate_freecad_mesh(
                obj.Equation,
                str(obj.Part),
                cell_size,
                repeat_cell,
                resolution,
                float(obj.Offset),
                phase,
                bool(getattr(obj, "MeshStitching", False)),
                str(getattr(obj, "BoundaryMode", tpms_generator.BOUNDARY_BOX)),
                getattr(obj, "BoundaryObject", None),
                max(0.0, float(getattr(obj, "Sampling", 0.0))),
                bool(getattr(obj, "AddCaps", True)),
                bool(getattr(obj, "MeshRelaxation", False)),
                max(0, int(getattr(obj, "RelaxIterations", 5))),
                bool(getattr(obj, "RelaxSkipBoundary", True)),
                bool(getattr(obj, "RelaxCapSurface", False)),
                origin,
                origin_rotation,
                str(getattr(obj, "DensityMode", "Uniform")),
                max(0.05, float(getattr(obj, "BaseDensity", 1.0))),
                density_controls,
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


class TPMSFaceDensityControl:
    Type = "TPMS::FaceDensityControl"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        if not hasattr(obj, "Enabled"):
            obj.addProperty("App::PropertyBool", "Enabled", "Density", "Use this face density control")
            obj.Enabled = True
        if not hasattr(obj, "SourceObject"):
            obj.addProperty("App::PropertyXLink", "SourceObject", "Density", "Solid object containing the selected face")
        if not hasattr(obj, "FaceNames"):
            obj.addProperty("App::PropertyStringList", "FaceNames", "Density", "Selected subelement face names")
        if not hasattr(obj, "DensityFactor"):
            obj.addProperty("App::PropertyFloat", "DensityFactor", "Density", "Target density multiplier near the selected face")
            obj.DensityFactor = 1.5
        if not hasattr(obj, "Transition"):
            obj.addProperty("App::PropertyFloat", "Transition", "Density", "Transition distance away from the selected face")
            obj.Transition = 5.0

    def onDocumentRestored(self, obj):
        self._add_properties(obj)

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
    control = doc.addObject("Part::FeaturePython", "TPMS_Face_Density")
    control.Label = "TPMS Face Density {}".format(",".join(face_names))
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


def _density_controls(obj):
    if str(getattr(obj, "DensityMode", "Uniform")) != "Non-uniform":
        return []
    controls = []
    for control in getattr(obj, "FaceControls", []):
        if control is None or not bool(getattr(control, "Enabled", True)):
            continue
        source = getattr(control, "SourceObject", None)
        shape = getattr(source, "Shape", None)
        if shape is None or shape.isNull():
            continue
        for face_name in getattr(control, "FaceNames", []):
            try:
                face = shape.getElement(str(face_name))
                point, normal = _face_point_normal(face)
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
                    "point": point,
                    "normal": normal,
                    "density": max(0.05, float(getattr(control, "DensityFactor", 1.0))),
                    "transition": max(1e-9, float(getattr(control, "Transition", 1.0))),
                }
            )
    return controls


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


def _container_for(obj):
    for parent in getattr(obj, "InList", []):
        if hasattr(parent, "addObject") and hasattr(parent, "Group"):
            return parent
    return None


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
