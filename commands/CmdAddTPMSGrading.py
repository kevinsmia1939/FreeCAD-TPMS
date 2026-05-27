import FreeCAD
import FreeCADGui


def _mod_path():
    import GyroidAssemblerUtils

    return GyroidAssemblerUtils.MOD_PATH


def _selected_controller():
    from objects.TPMSUnitCell import is_tpms_unit_cell

    selected = FreeCADGui.Selection.getSelection()
    for obj in selected:
        if is_tpms_unit_cell(obj):
            return obj
    for obj in selected:
        for child in getattr(obj, "Group", []):
            if is_tpms_unit_cell(child):
                return child
    doc = FreeCAD.ActiveDocument
    if doc is not None:
        for obj in doc.Objects:
            if is_tpms_unit_cell(obj):
                return obj
    return None


class AddTPMSGradingCommand:
    def GetResources(self):
        import os

        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "TPMSGrading.svg"),
            "MenuText": "Add TPMS Grading",
            "ToolTip": "Add a separate TPMS grading control to dynamically grade unit-cell density or sheet/skeletal thickness from selected faces.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from objects.TPMSUnitCell import add_grading_control

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("TPMS")
        source_controller = _selected_controller()
        if source_controller is None:
            FreeCAD.Console.PrintError("Select a TPMS Parameters object first.\n")
            return

        # Capture selected face names and source objects from active selection
        source_object = None
        face_names = []
        for selection in FreeCADGui.Selection.getSelectionEx():
            obj = getattr(selection, "Object", None)
            if obj is None or not hasattr(obj, "Shape"):
                continue
            faces = [
                str(name)
                for name in getattr(selection, "SubElementNames", [])
                if str(name).startswith("Face")
            ]
            if faces:
                source_object = obj
                face_names.extend(faces)

        # Fallback if no faces are selected
        if source_object is None:
            source_object = getattr(source_controller, "BoundaryObject", None)
            if source_object is None:
                source_object = source_controller

        doc.openTransaction("Add TPMS grading control")
        try:
            control = add_grading_control(
                source_controller,
                source_object,
                face_names,
                use_unit_cell_density=True,
                use_thickness=True,
            )
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()

        FreeCAD.Console.PrintMessage(
            "Created grading control {}. Double-click it to configure its grading parameters.\n".format(
                control.Label
            )
        )

        try:
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(control)
        except Exception:
            pass


if hasattr(FreeCADGui, "addCommand"):
    FreeCADGui.addCommand("TPMSGenerator_AddGrading", AddTPMSGradingCommand())
