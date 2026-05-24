import FreeCAD
import FreeCADGui


def _mod_path():
    import GyroidAssemblerUtils

    return GyroidAssemblerUtils.MOD_PATH


class RefreshTPMSCommand:
    def GetResources(self):
        import os

        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "TPMSRefresh.svg"),
            "MenuText": "Refresh TPMS",
            "ToolTip": "Mark all TPMS parameter objects dirty and recompute the active document.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from objects.TPMSUnitCell import is_tpms_unit_cell

        doc = FreeCAD.ActiveDocument
        if doc is None:
            FreeCAD.Console.PrintError("No active document to refresh.\n")
            return

        controllers = [obj for obj in doc.Objects if is_tpms_unit_cell(obj)]
        if not controllers:
            FreeCAD.Console.PrintMessage("No TPMS parameter objects found.\n")
            doc.recompute()
            return

        doc.openTransaction("Refresh TPMS")
        try:
            for controller in controllers:
                controller.touch()
                mesh_obj = getattr(controller, "ResultMesh", None)
                if mesh_obj is not None:
                    mesh_obj.touch()
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()

        FreeCAD.Console.PrintMessage(
            "Refreshed {} TPMS parameter object(s).\n".format(len(controllers))
        )


if hasattr(FreeCADGui, "addCommand"):
    FreeCADGui.addCommand("TPMSGenerator_Refresh", RefreshTPMSCommand())
