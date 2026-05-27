import FreeCADGui


class TPMSGeneratorWorkbench(Workbench):
    MenuText = "TPMS Generator"
    ToolTip = "Generate capped TPMS unit-cell meshes from implicit equations"

    def __init__(self):
        import os
        import GyroidAssemblerUtils

        icons_path = os.path.join(GyroidAssemblerUtils.MOD_PATH, "icons")
        self.__class__.Icon = os.path.join(icons_path, "TPMSAssembler.svg")
        FreeCADGui.addIconPath(icons_path)

    def Initialize(self):
        import commands.CmdGenerateTPMS
        import commands.CmdAddTPMSRegion
        import commands.CmdAddAllTPMSRegions
        import commands.CmdAddTPMSGrading
        import commands.CmdAddTPMSTransitionFace
        import commands.CmdAddTPMSTransitionEdge
        import commands.CmdRefreshTPMS

        tool_list = [
            "TPMSGenerator_GenerateUnitCell",
            "TPMSGenerator_AddRegionSettings",
            "TPMSGenerator_AddAllRegionSettings",
            "TPMSGenerator_AddGrading",
            "TPMSGenerator_AddTransitionFace",
            "TPMSGenerator_AddTransitionEdge",
            "TPMSGenerator_Refresh",
        ]
        self.appendToolbar("TPMS Generator", tool_list)
        self.appendMenu("&TPMS Generator", tool_list)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(TPMSGeneratorWorkbench())
