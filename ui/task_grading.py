import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore


class TPMSGradingTaskPanel:
    def __init__(self, obj):
        self.obj = obj
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("TPMS Grading")
        self._form_layouts = []

        layout = QtWidgets.QVBoxLayout(self.form)
        form = QtWidgets.QFormLayout()
        self._form_layouts.append(form)
        layout.addLayout(form)

        # Enabled Checkbox
        self.enabled = QtWidgets.QCheckBox()
        self.enabled.setChecked(bool(getattr(obj, "Enabled", True)))
        form.addRow("Enabled", self.enabled)

        # Source solid and Faces labels
        self.source_obj = getattr(obj, "SourceObject", None)
        self.face_names = list(getattr(obj, "FaceNames", []))

        self.source = QtWidgets.QLabel(self._source_text())
        self.source.setWordWrap(True)
        form.addRow("Source solid", self.source)

        self.faces = QtWidgets.QLabel(", ".join(self.face_names) or "None")
        self.faces.setWordWrap(True)
        form.addRow("Faces", self.faces)

        # Capture button for multi-face selection
        self.capture_btn = QtWidgets.QPushButton("Capture selected 3D faces")
        self.capture_btn.clicked.connect(self._capture_selected_faces)
        form.addRow("", self.capture_btn)

        # Affected Regions Section
        self.regions_group = QtWidgets.QGroupBox("Affected Regions")
        self.regions_layout = QtWidgets.QVBoxLayout(self.regions_group)
        self.region_checkboxes = {}  # solid_idx: (checkbox, parameter_obj)
        form.addRow("", self.regions_group)
        self._refresh_affected_regions()

        # Cell Number Density Group
        self.density_group = QtWidgets.QGroupBox("Cell Number Density")
        density_form = QtWidgets.QFormLayout(self.density_group)
        self._form_layouts.append(density_form)
        layout.addWidget(self.density_group)

        self.use_unit_cell_density = QtWidgets.QCheckBox()
        self.use_unit_cell_density.setChecked(bool(getattr(obj, "UseUnitCellDensity", True)))
        density_form.addRow("Enable cell density", self.use_unit_cell_density)

        self.density_source = QtWidgets.QComboBox()
        import tpms_generator
        self.density_source.addItems([
            tpms_generator.GRADIENT_FACE_DISTANCE,
            tpms_generator.GRADIENT_FACE_PLANE,
            tpms_generator.GRADIENT_HARMONIC
        ])
        curr_dens_src = str(getattr(obj, "DensitySource", tpms_generator.GRADIENT_FACE_DISTANCE))
        self.density_source.setCurrentText(curr_dens_src)
        density_form.addRow("Density source", self.density_source)

        self.density_factor = self._double_spin(float(getattr(obj, "DensityFactor", 1.5)), 0.05, 1000.0, 0.05)
        density_form.addRow("Density factor", self.density_factor)

        self.unit_cell_transition = self._double_spin(
            float(getattr(obj, "UnitCellTransition", 5.0)),
            0.001,
            100000.0,
            0.1,
        )
        density_form.addRow("Density transition", self.unit_cell_transition)

        # Sheet/Skeletal Thickness Group
        self.thickness_group = QtWidgets.QGroupBox("Sheet/Skeletal Thickness")
        thickness_form = QtWidgets.QFormLayout(self.thickness_group)
        self._form_layouts.append(thickness_form)
        layout.addWidget(self.thickness_group)

        self.use_thickness = QtWidgets.QCheckBox()
        self.use_thickness.setChecked(bool(getattr(obj, "UseThickness", True)))
        thickness_form.addRow("Enable thickness", self.use_thickness)

        self.thickness_source = QtWidgets.QComboBox()
        self.thickness_source.addItems([
            tpms_generator.GRADIENT_FACE_DISTANCE,
            tpms_generator.GRADIENT_FACE_PLANE,
            tpms_generator.GRADIENT_HARMONIC
        ])
        curr_thick_src = str(getattr(obj, "ThicknessSource", tpms_generator.GRADIENT_FACE_DISTANCE))
        self.thickness_source.setCurrentText(curr_thick_src)
        thickness_form.addRow("Thickness source", self.thickness_source)

        self.offset_value = self._double_spin(float(getattr(obj, "OffsetValue", 0.3)), -1000.0, 1000.0, 0.05)
        thickness_form.addRow("Thickness value", self.offset_value)

        self.thickness_transition = self._double_spin(
            float(getattr(obj, "ThicknessTransition", 5.0)),
            0.001,
            100000.0,
            0.1,
        )
        thickness_form.addRow("Thickness transition", self.thickness_transition)

        # Connect signals
        self.use_unit_cell_density.stateChanged.connect(self._update_controls)
        self.use_thickness.stateChanged.connect(self._update_controls)
        self.density_source.currentTextChanged.connect(self._update_controls)
        self.thickness_source.currentTextChanged.connect(self._update_controls)

        self._set_tooltips()
        self._update_controls()

    def _double_spin(self, value, minimum, maximum, step):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _source_text(self):
        if self.source_obj is None:
            return "None"
        return getattr(self.source_obj, "Label", getattr(self.source_obj, "Name", "Selected object"))

    def _capture_selected_faces(self):
        captured_source = None
        captured_faces = []
        for selection in Gui.Selection.getSelectionEx():
            obj = getattr(selection, "Object", None)
            if obj is None or not hasattr(obj, "Shape"):
                continue
            faces = [
                str(name)
                for name in getattr(selection, "SubElementNames", [])
                if str(name).startswith("Face")
            ]
            if faces:
                captured_source = obj
                captured_faces.extend(faces)

        if captured_source is not None and captured_faces:
            self.source_obj = captured_source
            self.face_names = list(captured_faces)
            self.source.setText(self._source_text())
            self.faces.setText(", ".join(self.face_names))
            self._refresh_affected_regions()
        else:
            QtWidgets.QMessageBox.warning(
                self.form,
                "TPMS Grading",
                "Select one or more faces in the 3D viewer first, then click this button."
            )

    def _refresh_affected_regions(self):
        # Clear existing checkboxes
        for i in reversed(range(self.regions_layout.count())):
            widget = self.regions_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.region_checkboxes.clear()

        # Find base controller
        base = self._controller()
        if base is None:
            self.regions_group.setVisible(False)
            return

        from objects.TPMSUnitCell import boundary_region_solids, _adjacent_solid_indices_for_face
        boundary = getattr(base, "BoundaryObject", None)
        solids = boundary_region_solids(boundary) if boundary else []
        
        if len(solids) <= 1:
            # Single region, no need to display region checkboxes
            self.regions_group.setVisible(False)
            return

        self.regions_group.setVisible(True)

        # Gather adjacent solid indices for all selected faces
        adj_indices = set()
        shape = getattr(self.source_obj, "Shape", None) if self.source_obj else None
        if shape is not None and boundary is not None:
            for face_name in self.face_names:
                try:
                    face = shape.getElement(str(face_name))
                    indices = _adjacent_solid_indices_for_face(boundary, face)
                    adj_indices.update(indices)
                except Exception:
                    pass

        if not adj_indices:
            # If no indices mapped yet, fallback to all region indices
            adj_indices = set(range(len(solids)))

        # Find all region parameter objects in the document
        regions_in_doc = {}
        for o in self.obj.Document.Objects:
            if hasattr(o, "Proxy") and o.Proxy.__class__.__name__ == "TPMSUnitCell":
                role = str(getattr(o, "RegionRole", ""))
                if role != "Base":
                    try:
                        idx = int(getattr(o, "RegionIndex", 0))
                        regions_in_doc[idx] = o
                    except Exception:
                        pass

        # Load currently linked regions from AffectedRegions
        currently_linked = list(getattr(self.obj, "AffectedRegions", []))

        # Add checkboxes for each adjacent region
        for idx in sorted(adj_indices):
            parameter_obj = regions_in_doc.get(idx, base)
            label = "Region {} ({})".format(idx + 1, parameter_obj.Label)
            
            cb = QtWidgets.QCheckBox(label)
            # Default to checked if currently_linked is empty or parameter_obj is in it
            is_checked = len(currently_linked) == 0 or parameter_obj in currently_linked
            cb.setChecked(is_checked)
            
            self.regions_layout.addWidget(cb)
            self.region_checkboxes[idx] = (cb, parameter_obj)

    def _controller(self):
        doc = getattr(self.obj, "Document", None)
        if doc is None:
            return None
        for candidate in doc.Objects:
            if hasattr(candidate, "Proxy") and candidate.Proxy.__class__.__name__ == "TPMSUnitCell":
                if str(getattr(candidate, "RegionRole", "")) == "Base":
                    return candidate
        return None

    def _set_tip(self, widget, text):
        widget.setToolTip(text)
        widget.setStatusTip(text)
        widget.setWhatsThis(text)

    def _set_enabled(self, field, enabled):
        field.setEnabled(enabled)
        for form in getattr(self, "_form_layouts", []):
            try:
                label = form.labelForField(field)
            except Exception:
                label = None
            if label is not None:
                label.setEnabled(enabled)

    def _set_tooltips(self):
        self._set_tip(self.enabled, "Turns this selected-face grading control on or off.")
        self._set_tip(self.source, "The solid whose face selection created this grading control.")
        self._set_tip(self.faces, "The selected face names used as the grading source region.")
        self._set_tip(self.capture_btn, "Capture currently selected faces from the 3D viewer.")
        self._set_tip(
            self.use_unit_cell_density,
            "Applies this face control to unit-cell density grading.",
        )
        self._set_tip(
            self.density_source,
            "Mode used to evaluate the density field: Face distance, Face plane, or Harmonic PDE.",
        )
        self._set_tip(
            self.density_factor,
            "Target unit-cell density multiplier near the selected faces.",
        )
        self._set_tip(
            self.unit_cell_transition,
            "Transition distance for density grading (disabled for Harmonic source).",
        )
        self._set_tip(
            self.use_thickness,
            "Applies this face control to sheet or skeletal thickness grading.",
        )
        self._set_tip(
            self.thickness_source,
            "Mode used to evaluate the thickness field: Face distance, Face plane, or Harmonic PDE.",
        )
        self._set_tip(
            self.offset_value,
            "Target thickness value near the selected faces.",
        )
        self._set_tip(
            self.thickness_transition,
            "Transition distance for thickness grading (disabled for Harmonic source).",
        )

    def _update_controls(self):
        import tpms_generator
        density_enabled = self.use_unit_cell_density.isChecked()
        thickness_enabled = self.use_thickness.isChecked()

        # Density controls
        self._set_enabled(self.density_source, density_enabled)
        self._set_enabled(self.density_factor, density_enabled)
        is_density_harmonic = self.density_source.currentText() == tpms_generator.GRADIENT_HARMONIC
        self._set_enabled(self.unit_cell_transition, density_enabled and not is_density_harmonic)

        # Thickness controls
        self._set_enabled(self.thickness_source, thickness_enabled)
        self._set_enabled(self.offset_value, thickness_enabled)
        is_thickness_harmonic = self.thickness_source.currentText() == tpms_generator.GRADIENT_HARMONIC
        self._set_enabled(self.thickness_transition, thickness_enabled and not is_thickness_harmonic)

    def accept(self):
        obj = self.obj
        doc = obj.Document
        doc.openTransaction("Edit TPMS grading")
        try:
            obj.Enabled = bool(self.enabled.isChecked())
            obj.SourceObject = self.source_obj
            obj.FaceNames = list(self.face_names)
            
            # Save parameters
            obj.UseUnitCellDensity = bool(self.use_unit_cell_density.isChecked())
            obj.DensitySource = str(self.density_source.currentText())
            obj.DensityFactor = float(self.density_factor.value())
            obj.UnitCellTransition = float(self.unit_cell_transition.value())
            
            obj.UseThickness = bool(self.use_thickness.isChecked())
            obj.ThicknessSource = str(self.thickness_source.currentText())
            obj.OffsetValue = float(self.offset_value.value())
            obj.ThicknessTransition = float(self.thickness_transition.value())

            # Save AffectedRegions link list
            selected_regions = []
            all_checked = True
            all_unchecked = True
            for cb, param_obj in self.region_checkboxes.values():
                if cb.isChecked():
                    selected_regions.append(param_obj)
                    all_unchecked = False
                else:
                    all_checked = False

            if all_checked or all_unchecked:
                # Default is empty list which means "All" regions are affected
                obj.AffectedRegions = []
            else:
                obj.AffectedRegions = selected_regions

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
