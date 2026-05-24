import FreeCAD as App


class TPMSGradingTaskPanel:
    def __init__(self, obj):
        from PySide import QtWidgets

        self.obj = obj
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("TPMS Grading")

        layout = QtWidgets.QVBoxLayout(self.form)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.enabled = QtWidgets.QCheckBox()
        self.enabled.setChecked(bool(getattr(obj, "Enabled", True)))
        form.addRow("Enabled", self.enabled)

        self.source = QtWidgets.QLabel(self._source_text())
        self.source.setWordWrap(True)
        form.addRow("Source solid", self.source)

        self.faces = QtWidgets.QLabel(", ".join(getattr(obj, "FaceNames", [])) or "None")
        self.faces.setWordWrap(True)
        form.addRow("Faces", self.faces)

        self.affected_regions = QtWidgets.QLineEdit(str(getattr(obj, "AffectedRegions", "")))
        form.addRow("Affected regions", self.affected_regions)

        self.use_unit_cell_density = QtWidgets.QCheckBox()
        self.use_unit_cell_density.setChecked(bool(getattr(obj, "UseUnitCellDensity", True)))
        form.addRow("Unit-cell density", self.use_unit_cell_density)

        self.density_factor = self._double_spin(float(getattr(obj, "DensityFactor", 1.5)), 0.05, 1000.0, 0.05)
        form.addRow("Density factor", self.density_factor)

        self.unit_cell_transition = self._double_spin(
            float(getattr(obj, "UnitCellTransition", getattr(obj, "Transition", 5.0))),
            0.001,
            100000.0,
            0.1,
        )
        form.addRow("Density transition", self.unit_cell_transition)

        self.use_thickness = QtWidgets.QCheckBox()
        self.use_thickness.setChecked(bool(getattr(obj, "UseThickness", True)))
        form.addRow("Thickness", self.use_thickness)

        self.offset_value = self._double_spin(float(getattr(obj, "OffsetValue", 0.3)), -1000.0, 1000.0, 0.05)
        form.addRow("Thickness value", self.offset_value)

        self.thickness_transition = self._double_spin(
            float(getattr(obj, "ThicknessTransition", getattr(obj, "Transition", 5.0))),
            0.001,
            100000.0,
            0.1,
        )
        form.addRow("Thickness transition", self.thickness_transition)

        self.use_unit_cell_density.stateChanged.connect(self._update_controls)
        self.use_thickness.stateChanged.connect(self._update_controls)
        self._set_tooltips()
        self._update_controls()

    def _double_spin(self, value, minimum, maximum, step):
        from PySide import QtWidgets

        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _source_text(self):
        source = getattr(self.obj, "SourceObject", None)
        if source is None:
            return "None"
        return getattr(source, "Label", getattr(source, "Name", "Selected object"))

    def _set_tip(self, widget, text):
        widget.setToolTip(text)
        widget.setStatusTip(text)
        widget.setWhatsThis(text)

    def _set_tooltips(self):
        self._set_tip(self.enabled, "Turns this selected-face grading control on or off without deleting it.")
        self._set_tip(self.source, "The solid whose face selection created this grading control.")
        self._set_tip(self.faces, "The selected face names used as the grading source region.")
        self._set_tip(
            self.affected_regions,
            "One-based region numbers affected by this control, for example 1,3. Leave empty to affect all regions.",
        )
        self._set_tip(
            self.use_unit_cell_density,
            "Applies this face control to unit-cell density grading. Disable it to keep only thickness grading.",
        )
        self._set_tip(
            self.density_factor,
            "Target unit-cell density multiplier near the selected faces. Higher values create smaller local TPMS cells.",
        )
        self._set_tip(
            self.unit_cell_transition,
            "Distance over which unit-cell density blends from the selected-face value back to the base value.",
        )
        self._set_tip(
            self.use_thickness,
            "Applies this face control to sheet or skeletal thickness grading.",
        )
        self._set_tip(
            self.offset_value,
            "Target sheet thickness or skeletal iso spacing near the selected faces. Zero and negative values are allowed.",
        )
        self._set_tip(
            self.thickness_transition,
            "Distance over which thickness blends from the selected-face value back to the base thickness.",
        )

    def _update_controls(self):
        density_enabled = self.use_unit_cell_density.isChecked()
        thickness_enabled = self.use_thickness.isChecked()
        self.density_factor.setEnabled(density_enabled)
        self.unit_cell_transition.setEnabled(density_enabled)
        self.offset_value.setEnabled(thickness_enabled)
        self.thickness_transition.setEnabled(thickness_enabled)

    def accept(self):
        obj = self.obj
        doc = obj.Document
        doc.openTransaction("Edit TPMS grading")
        try:
            obj.Enabled = bool(self.enabled.isChecked())
            obj.AffectedRegions = self.affected_regions.text().strip()
            obj.UseUnitCellDensity = bool(self.use_unit_cell_density.isChecked())
            obj.DensityFactor = float(self.density_factor.value())
            obj.UnitCellTransition = float(self.unit_cell_transition.value())
            obj.UseThickness = bool(self.use_thickness.isChecked())
            obj.OffsetValue = float(self.offset_value.value())
            obj.ThicknessTransition = float(self.thickness_transition.value())
            obj.touch()
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()
        return True

    def reject(self):
        return True
