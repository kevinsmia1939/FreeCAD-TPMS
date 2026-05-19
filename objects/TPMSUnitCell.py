import FreeCAD as App


def make_tpms_unit_cell(doc=None):
    import tpms_generator

    doc = doc or App.ActiveDocument or App.newDocument("TPMS")

    container = doc.addObject("App::Part", "TPMS_Unit_Cell")
    container.Label = "TPMS Unit Cell"

    controller = doc.addObject("App::FeaturePython", "TPMS_Parameters")
    controller.Label = "TPMS Parameters"
    TPMSUnitCell(controller)
    if getattr(controller, "ViewObject", None) is not None:
        TPMSUnitCellViewProvider(controller.ViewObject)
    container.addObject(controller)

    mesh_obj = doc.addObject("Mesh::Feature", "TPMS_Mesh")
    mesh_obj.Label = "TPMS Mesh"
    container.addObject(mesh_obj)
    controller.ResultMesh = mesh_obj

    controller.Surface = "Gyroid"
    controller.Part = tpms_generator.PART_SHEET
    controller.Equation = tpms_generator.SURFACE_EQUATIONS["Gyroid"]
    controller.Resolution = 32
    controller.RepeatX = 1
    controller.RepeatY = 1
    controller.RepeatZ = 1
    controller.Offset = 0.3
    controller.CellSize = App.Vector(1.0, 1.0, 1.0)
    controller.Phase = App.Vector(0.0, 0.0, 0.0)

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
        if not hasattr(obj, "RepeatY"):
            obj.addProperty("App::PropertyInteger", "RepeatY", "TPMS Array", "Unit cells in Y")
        if not hasattr(obj, "RepeatZ"):
            obj.addProperty("App::PropertyInteger", "RepeatZ", "TPMS Array", "Unit cells in Z")
        if not hasattr(obj, "Offset"):
            obj.addProperty("App::PropertyFloat", "Offset", "TPMS", "Sheet thickness or skeletal iso spacing")
        if not hasattr(obj, "CellSize"):
            obj.addProperty("App::PropertyVector", "CellSize", "TPMS", "Unit-cell size in X/Y/Z")
        if not hasattr(obj, "Phase"):
            obj.addProperty("App::PropertyVector", "Phase", "TPMS", "Phase shift in document units")
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
            mesh_obj = obj.Document.addObject("Mesh::Feature", "{}_Mesh".format(obj.Name))
            mesh_obj.Label = "{} Mesh".format(obj.Label)
            obj.ResultMesh = mesh_obj

        try:
            resolution = max(4, int(obj.Resolution))
            repeat_cell = (
                max(1, int(obj.RepeatX)),
                max(1, int(obj.RepeatY)),
                max(1, int(obj.RepeatZ)),
            )
            cell_size = _vector_tuple(obj.CellSize, fallback=(1.0, 1.0, 1.0), minimum=1e-9)
            phase = _vector_tuple(obj.Phase, fallback=(0.0, 0.0, 0.0), minimum=None)
            polydata = tpms_generator.generate_polydata(
                obj.Equation,
                str(obj.Part),
                cell_size,
                repeat_cell,
                resolution,
                float(obj.Offset),
                phase,
            )
            mesh = tpms_generator.polydata_to_freecad_mesh(polydata)
        except Exception as exc:
            obj.LastError = str(exc)
            App.Console.PrintError("TPMS generation failed: {}\n".format(exc))
            return

        mesh_obj.Mesh = mesh
        mesh_obj.Label = "{} Mesh".format(obj.Label)
        obj.FacetCount = int(mesh.CountFacets)
        obj.IsSolidMesh = bool(mesh.isSolid())
        obj.HasNonManifolds = bool(mesh.hasNonManifolds())
        obj.LastError = ""


class TPMSUnitCellViewProvider:
    def __init__(self, view_obj):
        view_obj.Proxy = self

    def getIcon(self):
        import os
        import GyroidAssemblerUtils

        return os.path.join(GyroidAssemblerUtils.MOD_PATH, "icons", "TPMSAssembler.svg")

    def attach(self, view_obj):
        self.Object = view_obj.Object

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_tpms_unit_cell(obj):
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, TPMSUnitCell)


def _vector_tuple(vector, fallback, minimum=None):
    try:
        values = (float(vector.x), float(vector.y), float(vector.z))
    except Exception:
        values = fallback
    if minimum is None:
        return values
    return tuple(max(minimum, value) for value in values)
