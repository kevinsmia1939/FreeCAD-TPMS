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


class AddTPMSTransitionFaceCommand:
    def GetResources(self):
        import os

        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "TPMSTransitionFace.svg"),
            "MenuText": "Add TPMS Transition Face",
            "ToolTip": "Add a face-based transition blend between adjacent solid regions of a multi-region boundary.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from objects.TPMSUnitCell import add_tpms_transition_face

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("TPMS")
        source = _selected_controller()
        if source is None:
            FreeCAD.Console.PrintError("Select a TPMS Parameters object first.\n")
            return

        doc.openTransaction("Add TPMS transition face")
        try:
            control = add_tpms_transition_face(source)
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()

        FreeCAD.Console.PrintMessage(
            "Created {} settings. Double-click it to select the transition face and blend width.\n".format(
                control.Label
            )
        )

        try:
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(control)
        except Exception:
            pass


if hasattr(FreeCADGui, "addCommand"):
    FreeCADGui.addCommand("TPMSGenerator_AddTransitionFace", AddTPMSTransitionFaceCommand())
