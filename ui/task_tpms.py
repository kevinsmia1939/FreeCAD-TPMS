import FreeCAD as App


class TPMSTaskPanel:
    def __init__(self, obj):
        from PySide import QtWidgets
        import tpms_generator

        self.obj = obj
        self.generator = tpms_generator
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("TPMS Parameters")

        layout = QtWidgets.QVBoxLayout(self.form)

        tpms_layout = self._group(layout, "TPMS")

        self.surface = QtWidgets.QComboBox()
        self.surface.addItems(tpms_generator.surface_names() + ["Custom"])
        self.surface.setCurrentText(str(obj.Surface))
        tpms_layout.addRow("Surface", self.surface)

        self.equation = QtWidgets.QLineEdit(str(obj.Equation))
        tpms_layout.addRow("Equation", self.equation)

        self.part = QtWidgets.QComboBox()
        self.part.addItems([tpms_generator.PART_SHEET, tpms_generator.PART_UPPER, tpms_generator.PART_LOWER])
        self.part.setCurrentText(str(obj.Part))
        tpms_layout.addRow("Part", self.part)

        self.resolution = QtWidgets.QSpinBox()
        self.resolution.setRange(4, 256)
        self.resolution.setValue(max(4, int(obj.Resolution)))
        tpms_layout.addRow("Resolution", self.resolution)

        self.offset = self._double_spin(float(obj.Offset), 0.001, 1000.0, 0.05)
        tpms_layout.addRow("Offset", self.offset)

        self.cell_x = self._double_spin(float(obj.CellSize.x), 0.001, 100000.0, 0.1)
        self.cell_y = self._double_spin(float(obj.CellSize.y), 0.001, 100000.0, 0.1)
        self.cell_z = self._double_spin(float(obj.CellSize.z), 0.001, 100000.0, 0.1)
        cell_layout = QtWidgets.QHBoxLayout()
        cell_layout.addWidget(self.cell_x)
        cell_layout.addWidget(self.cell_y)
        cell_layout.addWidget(self.cell_z)
        tpms_layout.addRow("Cell size XYZ", cell_layout)

        self.phase_x = self._double_spin(float(obj.Phase.x), -100000.0, 100000.0, 0.05)
        self.phase_y = self._double_spin(float(obj.Phase.y), -100000.0, 100000.0, 0.05)
        self.phase_z = self._double_spin(float(obj.Phase.z), -100000.0, 100000.0, 0.05)
        phase_layout = QtWidgets.QHBoxLayout()
        phase_layout.addWidget(self.phase_x)
        phase_layout.addWidget(self.phase_y)
        phase_layout.addWidget(self.phase_z)
        tpms_layout.addRow("Phase XYZ", phase_layout)

        density_group = self._group(layout, "Density")

        self.density_mode = QtWidgets.QComboBox()
        self.density_mode.addItems(["Uniform", "Non-uniform"])
        self.density_mode.setCurrentText(str(getattr(obj, "DensityMode", "Uniform")))
        density_group.addRow("Density", self.density_mode)

        self.base_density = self._double_spin(float(getattr(obj, "BaseDensity", 1.0)), 0.05, 1000.0, 0.05)
        density_group.addRow("Base density", self.base_density)

        self.face_density = self._double_spin(float(getattr(obj, "FaceDensity", 1.5)), 0.05, 1000.0, 0.05)
        density_group.addRow("New face density", self.face_density)

        self.density_transition = self._double_spin(float(getattr(obj, "DensityTransition", 5.0)), 0.001, 100000.0, 0.1)
        density_group.addRow("Transition", self.density_transition)

        self.face_controls_label = QtWidgets.QLabel(self._face_controls_text())
        self.add_face_controls = QtWidgets.QPushButton("Add selected faces")
        face_controls_layout = QtWidgets.QHBoxLayout()
        face_controls_layout.addWidget(self.face_controls_label, 1)
        face_controls_layout.addWidget(self.add_face_controls)
        density_group.addRow("Face controls", face_controls_layout)

        origin_group = self._group(layout, "Origin")

        self.origin_mode = QtWidgets.QComboBox()
        self.origin_mode.addItems(["Boundary object", "Custom XYZ", "Datum point"])
        self.origin_mode.setCurrentText(str(getattr(obj, "OriginMode", "Boundary object")))
        origin_group.addRow("Origin", self.origin_mode)

        origin = getattr(obj, "Origin", App.Vector(0.0, 0.0, 0.0))
        self.origin_x = self._double_spin(float(origin.x), -100000.0, 100000.0, 0.1)
        self.origin_y = self._double_spin(float(origin.y), -100000.0, 100000.0, 0.1)
        self.origin_z = self._double_spin(float(origin.z), -100000.0, 100000.0, 0.1)
        origin_layout = QtWidgets.QHBoxLayout()
        origin_layout.addWidget(self.origin_x)
        origin_layout.addWidget(self.origin_y)
        origin_layout.addWidget(self.origin_z)
        origin_group.addRow("Origin XYZ", origin_layout)

        self.origin_label = QtWidgets.QLabel(self._origin_text())
        self.origin_select = QtWidgets.QPushButton("Use selection")
        origin_object_layout = QtWidgets.QHBoxLayout()
        origin_object_layout.addWidget(self.origin_label, 1)
        origin_object_layout.addWidget(self.origin_select)
        origin_group.addRow("Datum point", origin_object_layout)

        self.origin_location = QtWidgets.QLabel(self._origin_location_text())
        self.origin_location.setWordWrap(True)
        origin_group.addRow("Datum XYZ", self.origin_location)

        self.rotation_mode = QtWidgets.QComboBox()
        self.rotation_mode.addItems(["Same as origin", "Boundary object", "Custom XYZ", "Datum point"])
        self.rotation_mode.setCurrentText(str(getattr(obj, "RotationMode", "Same as origin")))
        origin_group.addRow("Rotation", self.rotation_mode)

        rotation = getattr(obj, "OriginRotation", App.Vector(0.0, 0.0, 0.0))
        self.rotation_x = self._double_spin(float(rotation.x), -360000.0, 360000.0, 1.0)
        self.rotation_y = self._double_spin(float(rotation.y), -360000.0, 360000.0, 1.0)
        self.rotation_z = self._double_spin(float(rotation.z), -360000.0, 360000.0, 1.0)
        rotation_layout = QtWidgets.QHBoxLayout()
        rotation_layout.addWidget(self.rotation_x)
        rotation_layout.addWidget(self.rotation_y)
        rotation_layout.addWidget(self.rotation_z)
        origin_group.addRow("Rotation XYZ deg", rotation_layout)

        self.rotation_label = QtWidgets.QLabel(self._rotation_text())
        self.rotation_select = QtWidgets.QPushButton("Use selection")
        rotation_object_layout = QtWidgets.QHBoxLayout()
        rotation_object_layout.addWidget(self.rotation_label, 1)
        rotation_object_layout.addWidget(self.rotation_select)
        origin_group.addRow("Rotation object", rotation_object_layout)

        self.rotation_location = QtWidgets.QLabel(self._rotation_location_text())
        self.rotation_location.setWordWrap(True)
        origin_group.addRow("Rotation object XYZ", self.rotation_location)

        boundary_group = self._group(layout, "Boundary")

        self.boundary_mode = QtWidgets.QComboBox()
        self.boundary_mode.addItems(tpms_generator.boundary_modes())
        self.boundary_mode.setCurrentText(str(getattr(obj, "BoundaryMode", tpms_generator.BOUNDARY_BOX)))
        boundary_group.addRow("Boundary", self.boundary_mode)

        self.boundary_label = QtWidgets.QLabel(self._boundary_text())
        self.boundary_select = QtWidgets.QPushButton("Use selection")
        boundary_object_layout = QtWidgets.QHBoxLayout()
        boundary_object_layout.addWidget(self.boundary_label, 1)
        boundary_object_layout.addWidget(self.boundary_select)
        boundary_group.addRow("Selected boundary", boundary_object_layout)

        self.sampling = self._double_spin(float(getattr(obj, "Sampling", 0.0)), 0.0, 100000.0, 0.1)
        self.sampling.setSpecialValueText("Use resolution")
        boundary_group.addRow("Sampling resolution", self.sampling)

        self.add_caps = QtWidgets.QCheckBox()
        self.add_caps.setChecked(bool(getattr(obj, "AddCaps", True)))
        boundary_group.addRow("Add caps", self.add_caps)

        relaxation_group = self._group(layout, "Relaxation")

        self.mesh_relaxation = QtWidgets.QCheckBox()
        self.mesh_relaxation.setChecked(bool(getattr(obj, "MeshRelaxation", False)))
        relaxation_group.addRow("Relax mesh", self.mesh_relaxation)

        self.relax_iterations = self._spin(max(0, int(getattr(obj, "RelaxIterations", 5))), 0, 100)
        relaxation_group.addRow("Relax iterations", self.relax_iterations)

        self.relax_skip_boundary = QtWidgets.QCheckBox()
        self.relax_skip_boundary.setChecked(bool(getattr(obj, "RelaxSkipBoundary", True)))
        relaxation_group.addRow("Skip bounds", self.relax_skip_boundary)

        self.relax_cap_surface = QtWidgets.QCheckBox()
        self.relax_cap_surface.setChecked(bool(getattr(obj, "RelaxCapSurface", False)))
        relaxation_group.addRow("Relax caps", self.relax_cap_surface)

        layout.addStretch(1)

        status_group = self._group(layout, "Status")
        self.boundary_method = QtWidgets.QLabel(self._boundary_method_text())
        self.boundary_method.setWordWrap(True)
        status_group.addRow("Boundary method", self.boundary_method)

        self.result = QtWidgets.QLabel(self._result_text())
        status_group.addRow("Result", self.result)

        self.surface.currentTextChanged.connect(self._surface_changed)
        self.density_mode.currentTextChanged.connect(self._update_density_controls)
        self.add_face_controls.clicked.connect(self._add_selected_face_controls)
        self.boundary_select.clicked.connect(self._use_selected_boundary)
        self.origin_select.clicked.connect(self._use_selected_origin)
        self.rotation_select.clicked.connect(self._use_selected_rotation)
        self.boundary_mode.currentTextChanged.connect(self._update_boundary_controls)
        self.origin_mode.currentTextChanged.connect(self._update_origin_controls)
        self.rotation_mode.currentTextChanged.connect(self._update_origin_controls)
        self.mesh_relaxation.stateChanged.connect(self._update_relax_controls)
        self.relax_skip_boundary.stateChanged.connect(self._update_relax_controls)
        self.add_caps.stateChanged.connect(self._update_relax_controls)
        self._update_boundary_controls()
        self._update_density_controls()
        self._update_origin_controls()
        self._update_relax_controls()

    def _group(self, parent_layout, title):
        from PySide import QtWidgets

        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        parent_layout.addWidget(box)
        return form

    def _spin(self, value, minimum, maximum):
        from PySide import QtWidgets

        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _double_spin(self, value, minimum, maximum, step):
        from PySide import QtWidgets

        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _surface_changed(self, name):
        if name in self.generator.SURFACE_EQUATIONS:
            self.equation.setText(self.generator.SURFACE_EQUATIONS[name])

    def _result_text(self):
        return "{} facets, solid={}, non-manifold={}".format(
            int(getattr(self.obj, "FacetCount", 0)),
            bool(getattr(self.obj, "IsSolidMesh", False)),
            bool(getattr(self.obj, "HasNonManifolds", False)),
        )

    def _boundary_text(self):
        boundary = getattr(self.obj, "BoundaryObject", None)
        if boundary is None:
            return "None"
        return getattr(boundary, "Label", getattr(boundary, "Name", "Selected object"))

    def _face_controls_text(self):
        count = len([control for control in getattr(self.obj, "FaceControls", []) if control is not None])
        if count == 1:
            return "1 control"
        return "{} controls".format(count)

    def _current_boundary_object(self):
        if hasattr(self, "_pending_boundary_object"):
            return self._pending_boundary_object
        return getattr(self.obj, "BoundaryObject", None)

    def _boundary_method_text(self):
        if self.boundary_mode.currentText() == self.generator.BOUNDARY_BOX:
            return "No selected boundary"
        boundary = self._current_boundary_object()
        if boundary is None:
            return "No selected boundary"
        type_id = getattr(boundary, "TypeId", "")
        if type_id == "Part::Sphere" and hasattr(boundary, "Radius"):
            return "Analytical sphere"
        if type_id == "Part::Box" and all(hasattr(boundary, name) for name in ("Length", "Width", "Height")):
            return "Analytical box"
        if hasattr(boundary, "Shape"):
            return "Tessellation signed-distance"
        if hasattr(boundary, "Mesh"):
            return "Tessellation signed-distance"
        return "Unsupported boundary"

    def _origin_text(self):
        origin_object = self._current_origin_object()
        if origin_object is None:
            return "None"
        return getattr(origin_object, "Label", getattr(origin_object, "Name", "Selected object"))

    def _rotation_text(self):
        rotation_object = self._current_rotation_object()
        if rotation_object is None:
            return "None"
        return getattr(rotation_object, "Label", getattr(rotation_object, "Name", "Selected object"))

    def _current_origin_object(self):
        if hasattr(self, "_pending_origin_object"):
            return self._pending_origin_object
        return getattr(self.obj, "OriginObject", None)

    def _current_rotation_object(self):
        if hasattr(self, "_pending_rotation_object"):
            return self._pending_rotation_object
        return getattr(self.obj, "RotationObject", None)

    def _placement_xyz_text(self, placement_object):
        placement = getattr(placement_object, "Placement", None)
        if placement is None:
            return "None"
        base = placement.Base
        return "X={:.4f}, Y={:.4f}, Z={:.4f}".format(float(base.x), float(base.y), float(base.z))

    def _origin_location_text(self):
        return self._placement_xyz_text(self._current_origin_object())

    def _rotation_location_text(self):
        return self._placement_xyz_text(self._current_rotation_object())

    def _update_boundary_controls(self):
        enabled = self.boundary_mode.currentText() == self.generator.BOUNDARY_SELECTED_SOLID
        self.boundary_label.setEnabled(enabled)
        self.boundary_select.setEnabled(enabled)
        self.boundary_method.setText(self._boundary_method_text())

    def _update_density_controls(self):
        enabled = self.density_mode.currentText() == "Non-uniform"
        self.face_density.setEnabled(enabled)
        self.density_transition.setEnabled(enabled)
        self.face_controls_label.setEnabled(enabled)
        self.add_face_controls.setEnabled(enabled)
        self.face_controls_label.setText(self._face_controls_text())

    def _update_origin_controls(self):
        custom_enabled = self.origin_mode.currentText() == "Custom XYZ"
        datum_enabled = self.origin_mode.currentText() == "Datum point"
        for widget in (self.origin_x, self.origin_y, self.origin_z):
            widget.setEnabled(custom_enabled)
        self.origin_label.setEnabled(datum_enabled)
        self.origin_select.setEnabled(datum_enabled)
        self.origin_location.setEnabled(datum_enabled)
        self.origin_location.setText(self._origin_location_text())

        rotation_mode = self.rotation_mode.currentText()
        rotation_custom_enabled = rotation_mode == "Custom XYZ" or (
            rotation_mode == "Same as origin" and self.origin_mode.currentText() == "Custom XYZ"
        )
        rotation_datum_enabled = rotation_mode == "Datum point"
        for widget in (self.rotation_x, self.rotation_y, self.rotation_z):
            widget.setEnabled(rotation_custom_enabled)
        self.rotation_label.setEnabled(rotation_datum_enabled)
        self.rotation_select.setEnabled(rotation_datum_enabled)
        self.rotation_location.setEnabled(rotation_datum_enabled)
        self.rotation_location.setText(self._rotation_location_text())

    def _update_relax_controls(self):
        enabled = bool(self.mesh_relaxation.isChecked())
        self.relax_iterations.setEnabled(enabled)
        self.relax_skip_boundary.setEnabled(enabled)
        self.relax_cap_surface.setEnabled(
            enabled
            and bool(self.relax_skip_boundary.isChecked())
            and bool(self.add_caps.isChecked())
        )

    def _use_selected_boundary(self):
        from PySide import QtWidgets

        try:
            import FreeCADGui as Gui
        except Exception:
            return

        for selected in Gui.Selection.getSelection():
            if selected is self.obj:
                continue
            if hasattr(selected, "Shape") and not selected.Shape.isNull():
                self._pending_boundary_object = selected
                self.boundary_label.setText(getattr(selected, "Label", selected.Name))
                self.boundary_mode.setCurrentText(self.generator.BOUNDARY_SELECTED_SOLID)
                self._update_boundary_controls()
                return
            if hasattr(selected, "Mesh") and selected.Mesh.CountFacets > 0:
                self._pending_boundary_object = selected
                self.boundary_label.setText(getattr(selected, "Label", selected.Name))
                self.boundary_mode.setCurrentText(self.generator.BOUNDARY_SELECTED_SOLID)
                self._update_boundary_controls()
                return
        QtWidgets.QMessageBox.warning(
            self.form,
            "TPMS Parameters",
            "Select a closed solid or mesh boundary first.",
        )

    def _add_selected_face_controls(self):
        from PySide import QtWidgets

        try:
            import FreeCADGui as Gui
            from objects.TPMSUnitCell import add_face_density_control
        except Exception:
            return

        created = 0
        doc = self.obj.Document
        doc.openTransaction("Add TPMS face density controls")
        try:
            for selection in Gui.Selection.getSelectionEx():
                source = getattr(selection, "Object", None)
                if source is None or not hasattr(source, "Shape"):
                    continue
                face_names = [
                    str(name)
                    for name in getattr(selection, "SubElementNames", [])
                    if str(name).startswith("Face")
                ]
                if not face_names:
                    continue
                add_face_density_control(
                    self.obj,
                    source,
                    face_names,
                    self.face_density.value(),
                    self.density_transition.value(),
                )
                created += 1
            if not created:
                raise ValueError("Select one or more solid faces first.")
        except Exception as exc:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(self.form, "TPMS Parameters", str(exc))
            return
        else:
            doc.commitTransaction()

        self.density_mode.setCurrentText("Non-uniform")
        self.face_controls_label.setText(self._face_controls_text())
        self._update_density_controls()

    def _use_selected_origin(self):
        from PySide import QtWidgets

        try:
            import FreeCADGui as Gui
        except Exception:
            return

        for selected in Gui.Selection.getSelection():
            if selected is self.obj:
                continue
            if hasattr(selected, "Placement"):
                self._pending_origin_object = selected
                self.origin_label.setText(getattr(selected, "Label", selected.Name))
                self.origin_location.setText(self._origin_location_text())
                self.origin_mode.setCurrentText("Datum point")
                return
        QtWidgets.QMessageBox.warning(
            self.form,
            "TPMS Parameters",
            "Select a datum point or any object with a Placement first.",
        )

    def _use_selected_rotation(self):
        from PySide import QtWidgets

        try:
            import FreeCADGui as Gui
        except Exception:
            return

        for selected in Gui.Selection.getSelection():
            if selected is self.obj:
                continue
            if hasattr(selected, "Placement"):
                self._pending_rotation_object = selected
                self.rotation_label.setText(getattr(selected, "Label", selected.Name))
                self.rotation_location.setText(self._rotation_location_text())
                self.rotation_mode.setCurrentText("Datum point")
                return
        QtWidgets.QMessageBox.warning(
            self.form,
            "TPMS Parameters",
            "Select a datum point or any object with a Placement first.",
        )

    def accept(self):
        obj = self.obj
        doc = obj.Document
        doc.openTransaction("Edit TPMS parameters")
        try:
            obj.Surface = self.surface.currentText()
            obj.Equation = self.equation.text()
            obj.Part = self.part.currentText()
            obj.Resolution = int(self.resolution.value())
            obj.RepeatX = 1
            obj.RepeatY = 1
            obj.RepeatZ = 1
            obj.Offset = float(self.offset.value())
            obj.CellSize = App.Vector(self.cell_x.value(), self.cell_y.value(), self.cell_z.value())
            obj.Phase = App.Vector(self.phase_x.value(), self.phase_y.value(), self.phase_z.value())
            obj.DensityMode = self.density_mode.currentText()
            obj.BaseDensity = float(self.base_density.value())
            obj.FaceDensity = float(self.face_density.value())
            obj.DensityTransition = float(self.density_transition.value())
            obj.OriginMode = self.origin_mode.currentText()
            obj.Origin = App.Vector(self.origin_x.value(), self.origin_y.value(), self.origin_z.value())
            if hasattr(self, "_pending_origin_object"):
                obj.OriginObject = self._pending_origin_object
            obj.RotationMode = self.rotation_mode.currentText()
            obj.OriginRotation = App.Vector(self.rotation_x.value(), self.rotation_y.value(), self.rotation_z.value())
            if hasattr(self, "_pending_rotation_object"):
                obj.RotationObject = self._pending_rotation_object
            obj.MeshStitching = False
            obj.BoundaryMode = self.boundary_mode.currentText()
            if hasattr(self, "_pending_boundary_object"):
                obj.BoundaryObject = self._pending_boundary_object
            obj.Sampling = float(self.sampling.value())
            obj.AddCaps = bool(self.add_caps.isChecked())
            obj.MeshRelaxation = bool(self.mesh_relaxation.isChecked())
            obj.RelaxIterations = int(self.relax_iterations.value())
            obj.RelaxSkipBoundary = bool(self.relax_skip_boundary.isChecked())
            obj.RelaxCapSurface = bool(self.relax_cap_surface.isChecked())
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()
        return True

    def reject(self):
        return True
