import FreeCAD
import FreeCADGui


def _mod_path():
    import GyroidAssemblerUtils

    return GyroidAssemblerUtils.MOD_PATH


class GenerateTPMSCommand:
    def GetResources(self):
        import os

        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "TPMSAssembler.svg"),
            "MenuText": "Create TPMS Unit Cell",
            "ToolTip": (
                "Create a parametric TPMS unit-cell container. Edit its parameters "
                "in the side Property panel and recompute to regenerate the mesh."
            ),
        }

    def IsActive(self):
        return True

    def Activated(self):
        from objects.TPMSUnitCell import make_tpms_unit_cell

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("TPMS")
        doc.openTransaction("Create TPMS unit cell")
        try:
            container, controller, mesh_obj = make_tpms_unit_cell(doc)
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()

        FreeCAD.Console.PrintMessage(
            "Created {} with editable controller {} and mesh {}.\n".format(
                container.Label,
                controller.Label,
                mesh_obj.Label,
            )
        )

        try:
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(controller)
            FreeCADGui.ActiveDocument.ActiveView.viewAxometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass


if hasattr(FreeCADGui, "addCommand"):
    FreeCADGui.addCommand("TPMSGenerator_GenerateUnitCell", GenerateTPMSCommand())
