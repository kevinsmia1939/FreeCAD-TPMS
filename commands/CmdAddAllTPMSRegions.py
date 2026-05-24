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


class AddAllTPMSRegionsCommand:
    def GetResources(self):
        import os

        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "TPMSAssembler.svg"),
            "MenuText": "Add TPMS Settings For All Regions",
            "ToolTip": "Create one TPMS parameter object for each missing solid region of a multi-region boundary.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from objects.TPMSUnitCell import add_tpms_region_settings_for_all_regions

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("TPMS")
        source = _selected_controller()
        if source is None:
            FreeCAD.Console.PrintError("Select a TPMS Parameters object first.\n")
            return

        doc.openTransaction("Add TPMS settings for all regions")
        try:
            created = add_tpms_region_settings_for_all_regions(source, skip_existing=True)
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()

        FreeCAD.Console.PrintMessage(
            "Created {} TPMS region setting object(s).\n".format(len(created))
        )

        try:
            FreeCADGui.Selection.clearSelection()
            if created:
                FreeCADGui.Selection.addSelection(created[-1][0])
            else:
                FreeCADGui.Selection.addSelection(source)
        except Exception:
            pass


if hasattr(FreeCADGui, "addCommand"):
    FreeCADGui.addCommand("TPMSGenerator_AddAllRegionSettings", AddAllTPMSRegionsCommand())
