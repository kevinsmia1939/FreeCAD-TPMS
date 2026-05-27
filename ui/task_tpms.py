import FreeCAD as App


class TPMSTaskPanel:
    def __init__(self, obj):
        from PySide import QtWidgets
        import tpms_generator

        self.obj = obj
        self.generator = tpms_generator
        self.form = QtWidgets.QWidget()
        self._form_layouts = []
        role_title = "Base Region Parameters" if str(getattr(obj, "RegionRole", "Base")) == "Base" else "TPMS Region Parameters"
        if str(getattr(obj, "RegionRole", "Base")) == "Transition":
            role_title = "Transition Region Parameters"
        self.form.setWindowTitle(role_title)

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

        self.offset = self._double_spin(float(obj.Offset), -1000.0, 1000.0, 0.05)
        tpms_layout.addRow("Sheet/skeletal thickness", self.offset)

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

        self.coordinate_mode = QtWidgets.QComboBox()
        self.coordinate_mode.addItems(tpms_generator.coordinate_modes())
        self.coordinate_mode.setCurrentText(str(getattr(obj, "CoordinateMode", tpms_generator.COORDINATE_CARTESIAN)))
        tpms_layout.addRow("Coordinates", self.coordinate_mode)

        self.ring_radius = self._double_spin(float(getattr(obj, "RingRadius", 2.0)), 0.001, 100000.0, 0.5)
        tpms_layout.addRow("Ring inner radius", self.ring_radius)

        outer_radius = float(getattr(obj, "RingOuterRadius", 5.0))
        self.ring_outer_radius = self._double_spin(outer_radius, 0.001, 100000.0, 0.5)
        tpms_layout.addRow("Ring outer radius", self.ring_outer_radius)

        self.ring_height = self._double_spin(float(getattr(obj, "RingHeight", 10.0)), 0.001, 100000.0, 0.5)
        tpms_layout.addRow("Ring height", self.ring_height)

        self.ring_angular_cells = self._spin(max(1, int(getattr(obj, "RingAngularCells", 8))), 1, 1000)
        tpms_layout.addRow("Ring angular cells", self.ring_angular_cells)

        self.boundary_mode = QtWidgets.QComboBox()
        self.boundary_mode.addItems(tpms_generator.boundary_modes())
        self.boundary_mode.setCurrentText(str(getattr(obj, "BoundaryMode", tpms_generator.BOUNDARY_BOX)))
        tpms_layout.addRow("Boundary", self.boundary_mode)

        self.boundary_evaluation = QtWidgets.QComboBox()
        self.boundary_evaluation.addItems(tpms_generator.boundary_evaluation_modes())
        boundary_evaluation = str(
            getattr(obj, "BoundaryEvaluation", tpms_generator.BOUNDARY_EVALUATION_ANALYTICAL)
        )
        if boundary_evaluation not in tpms_generator.boundary_evaluation_modes():
            boundary_evaluation = tpms_generator.BOUNDARY_EVALUATION_ANALYTICAL
        self.boundary_evaluation.setCurrentText(boundary_evaluation)
        tpms_layout.addRow("Boundary evaluation", self.boundary_evaluation)

        self.boundary_label = QtWidgets.QLabel(self._boundary_text())
        self.boundary_select = QtWidgets.QPushButton("Use selection")
        boundary_object_layout = QtWidgets.QHBoxLayout()
        boundary_object_layout.addWidget(self.boundary_label, 1)
        boundary_object_layout.addWidget(self.boundary_select)
        tpms_layout.addRow("Selected boundary", boundary_object_layout)

        self.region_mode = QtWidgets.QComboBox()
        self.region_mode.addItems(["All regions", "Single region"])
        self.region_mode.setCurrentText(str(getattr(obj, "RegionMode", "All regions")))
        tpms_layout.addRow("Boundary regions", self.region_mode)

        self.region_index = QtWidgets.QComboBox()
        tpms_layout.addRow("Selected region", self.region_index)

        self.region_role = QtWidgets.QComboBox()
        self.region_role.addItems(["Base", "Override", "Transition"])
        self.region_role.setCurrentText(str(getattr(obj, "RegionRole", "Base")))
        tpms_layout.addRow("Region role", self.region_role)

        self.sampling = self._double_spin(float(getattr(obj, "Sampling", 0.0)), 0.0, 100000.0, 0.1)
        self.sampling.setSpecialValueText("Use resolution")
        tpms_layout.addRow("Sampling resolution", self.sampling)

        self.add_caps = QtWidgets.QCheckBox()
        self.add_caps.setChecked(bool(getattr(obj, "AddCaps", True)))
        tpms_layout.addRow("Add caps", self.add_caps)

        transition_group = self._group(layout, "Transition")

        self.transition_source = self._spin(self._display_region_index(getattr(obj, "TransitionSourceRegion", 0)), 1, 100000)
        transition_group.addRow("Source region", self.transition_source)

        self.transition_target = self._spin(self._display_region_index(getattr(obj, "TransitionTargetRegion", 0)), 1, 100000)
        transition_group.addRow("Target region", self.transition_target)

        self.transition_blend_mode = QtWidgets.QComboBox()
        self.transition_blend_mode.addItems(
            [
                tpms_generator.TRANSITION_BLEND_THRESHOLD,
                tpms_generator.TRANSITION_BLEND_SIGMOID,
                tpms_generator.TRANSITION_BLEND_NORMALIZED_SUM,
            ]
        )
        self.transition_blend_mode.setCurrentText(
            str(getattr(obj, "TransitionBlendMode", tpms_generator.TRANSITION_BLEND_THRESHOLD))
        )
        transition_group.addRow("Blend mode", self.transition_blend_mode)

        self.transition_correction_factor = self._double_spin(float(getattr(obj, "TransitionCorrectionFactor", 0.0)), 0.0, 10.0, 0.05)
        transition_group.addRow("ASLI Correction", self.transition_correction_factor)

        self.transition_source_labyrinth = QtWidgets.QComboBox()
        self.transition_source_labyrinth.addItems(tpms_generator.labyrinth_modes())
        self.transition_source_labyrinth.setCurrentText(
            str(getattr(obj, "TransitionSourceLabyrinth", tpms_generator.LABYRINTH_AUTO))
        )
        transition_group.addRow("Source labyrinth", self.transition_source_labyrinth)

        self.transition_target_labyrinth = QtWidgets.QComboBox()
        self.transition_target_labyrinth.addItems(tpms_generator.labyrinth_modes())
        self.transition_target_labyrinth.setCurrentText(
            str(getattr(obj, "TransitionTargetLabyrinth", tpms_generator.LABYRINTH_AUTO))
        )
        transition_group.addRow("Target labyrinth", self.transition_target_labyrinth)

        self.transition_topology_mode = QtWidgets.QComboBox()
        self.transition_topology_mode.addItems(tpms_generator.transition_topology_modes())
        self.transition_topology_mode.setCurrentText(
            str(getattr(obj, "TransitionTopologyMode", tpms_generator.TRANSITION_TOPOLOGY_SAME_SIDE))
        )
        transition_group.addRow("Topology", self.transition_topology_mode)

        density_group = self._group(layout, "Grading")

        self.base_density = self._double_spin(float(getattr(obj, "BaseDensity", 1.0)), 0.05, 1000.0, 0.05)
        density_group.addRow("Base unit-cell density", self.base_density)

        self.density_count_mode = QtWidgets.QComboBox()
        self.density_count_mode.addItems([
            tpms_generator.DENSITY_COUNT_FOLLOW,
            tpms_generator.DENSITY_COUNT_PRESERVE,
        ])
        self.density_count_mode.setCurrentText(
            str(getattr(obj, "DensityCountMode", tpms_generator.DENSITY_COUNT_FOLLOW))
        )
        density_group.addRow("Unit-cell count", self.density_count_mode)

        self.grading_resolution = self._spin(max(0, int(getattr(obj, "GradingResolution", 16))), 0, 512)
        self.grading_resolution.setSpecialValueText("Use TPMS resolution")
        density_group.addRow("Harmonic resolution", self.grading_resolution)

        self.harmonic_boundary_condition = QtWidgets.QComboBox()
        self.harmonic_boundary_condition.addItems([
            tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR,
            tpms_generator.HARMONIC_BOUNDARY_INSULATOR,
        ])
        harmonic_boundary_condition = str(
            getattr(obj, "HarmonicBoundaryCondition", tpms_generator.HARMONIC_BOUNDARY_INSULATOR)
        )
        if harmonic_boundary_condition not in (
            tpms_generator.HARMONIC_BOUNDARY_CONDUCTOR,
            tpms_generator.HARMONIC_BOUNDARY_INSULATOR,
        ):
            harmonic_boundary_condition = tpms_generator.HARMONIC_BOUNDARY_INSULATOR
        self.harmonic_boundary_condition.setCurrentText(harmonic_boundary_condition)
        density_group.addRow("Harmonic unselected faces", self.harmonic_boundary_condition)

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

        relaxation_group = self._group(layout, "Relaxation")

        self.mesh_relaxation = QtWidgets.QCheckBox()
        self.mesh_relaxation.setChecked(bool(getattr(obj, "MeshRelaxation", False)))
        relaxation_group.addRow("Relax mesh", self.mesh_relaxation)

        self.relax_iterations = self._spin(max(0, int(getattr(obj, "RelaxIterations", 1))), 0, 100)
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

        self.region_status = QtWidgets.QLabel(self._region_status_text())
        self.region_status.setWordWrap(True)
        status_group.addRow("Region", self.region_status)

        self.result = QtWidgets.QLabel(self._result_text())
        status_group.addRow("Result", self.result)

        self.surface.currentTextChanged.connect(self._surface_changed)
        self.coordinate_mode.currentTextChanged.connect(self._update_coordinate_controls)
        self.boundary_select.clicked.connect(self._use_selected_boundary)
        self.boundary_evaluation.currentTextChanged.connect(self._update_boundary_controls)
        self.region_mode.currentTextChanged.connect(self._update_region_controls)
        self.region_role.currentTextChanged.connect(self._update_region_controls)
        self.origin_select.clicked.connect(self._use_selected_origin)
        self.rotation_select.clicked.connect(self._use_selected_rotation)
        self.boundary_mode.currentTextChanged.connect(self._update_boundary_controls)
        self.origin_mode.currentTextChanged.connect(self._update_origin_controls)
        self.rotation_mode.currentTextChanged.connect(self._update_origin_controls)
        self.mesh_relaxation.stateChanged.connect(self._update_relax_controls)
        self.relax_skip_boundary.stateChanged.connect(self._update_relax_controls)
        self.add_caps.stateChanged.connect(self._update_relax_controls)
        self._update_boundary_controls()
        self._update_coordinate_controls()
        self._update_density_controls()
        self._update_origin_controls()
        self._update_transition_controls()
        self._update_relax_controls()
        self._set_tooltips()

    def _group(self, parent_layout, title):
        from PySide import QtWidgets

        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        self._form_layouts.append(form)
        parent_layout.addWidget(box)
        return form

    def _set_enabled(self, field, enabled):
        field.setEnabled(enabled)
        for form in getattr(self, "_form_layouts", []):
            try:
                label = form.labelForField(field)
            except Exception:
                label = None
            if label is not None:
                label.setEnabled(enabled)

    def _set_enabled_many(self, fields, enabled):
        for field in fields:
            self._set_enabled(field, enabled)

    def _transition_role_active(self):
        return self.region_role.currentText() == "Transition"

    def _structure_surface_active(self):
        return self.surface.currentText() not in (
            self.generator.SURFACE_EMPTY,
            self.generator.SURFACE_SOLID_FILL,
        )

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

    def _set_tip(self, widget, text):
        widget.setToolTip(text)
        widget.setStatusTip(text)
        widget.setWhatsThis(text)

    def _display_region_index(self, stored_index):
        return max(1, int(stored_index) + 1)

    def _stored_region_index(self, displayed_index):
        return max(0, int(displayed_index) - 1)

    def _set_tooltips(self):
        self._set_tip(self.surface, "Preset TPMS equation. Choose Custom to edit the equation directly.")
        self._set_tip(self.equation, "Implicit equation evaluated with x, y, and z. The zero level set defines the TPMS.")
        self._set_tip(self.part, "Sheet creates a thickened TPMS shell. Upper and Lower skeletal create one side of the implicit field.")
        self._set_tip(self.resolution, "TPMS mesh grid resolution. Higher values improve detail but increase memory and compute time.")
        self._set_tip(self.offset, "Sheet thickness or skeletal iso spacing. For sheet TPMS this is symmetric around the TPMS mid-surface. Zero and negative values are allowed.")
        for widget in (self.cell_x, self.cell_y, self.cell_z):
            self._set_tip(widget, "TPMS unit-cell size along this local axis.")
        for widget in (self.phase_x, self.phase_y, self.phase_z):
            self._set_tip(widget, "Phase offset of the TPMS equation along this local axis.")
        self._set_tip(self.coordinate_mode, "Cartesian fills a volume. Cylindrical ring wraps the TPMS around a circular axis.")
        self._set_tip(self.ring_radius, "Inner radius for cylindrical ring TPMS.")
        self._set_tip(self.ring_outer_radius, "Outer radius for cylindrical ring TPMS.")
        self._set_tip(self.ring_height, "Height of the cylindrical ring TPMS.")
        self._set_tip(self.ring_angular_cells, "Number of TPMS periods around the full 360 degree ring.")
        self._set_tip(self.boundary_mode, "Boundary used to clip and cap the generated TPMS.")
        self._set_tip(
            self.boundary_evaluation,
            "Analytical uses exact fields for recognized Part boxes, spheres, cylinders, and tubes. Tessellated SDF forces the selected boundary through mesh-based signed-distance clipping.",
        )
        self._set_tip(self.boundary_select, "Use the currently selected solid or mesh as the TPMS boundary.")
        self._set_tip(self.region_mode, "For BooleanFragments or compounds with multiple solids, choose whether this TPMS parameter fills all regions or one solid region.")
        self._set_tip(self.region_index, "Solid region used when Boundary regions is set to Single region. Region order comes from the FreeCAD shape solids.")
        self._set_tip(self.region_role, "Base is the first region setting. Override defines one fixed TPMS region. Transition blends source and target TPMS fields inside this region.")
        self._set_tip(self.transition_source, "Source region number for this transition region. Region numbering starts at 1.")
        self._set_tip(self.transition_target, "Target region number for this transition region. Region numbering starts at 1.")
        self._set_tip(self.transition_source_labyrinth, "Source labyrinth to connect. Auto follows upper or lower skeletal part.")
        self._set_tip(self.transition_target_labyrinth, "Target labyrinth to connect. Auto follows upper or lower skeletal part.")
        self._set_tip(self.transition_topology_mode, "Same-side blends selected labyrinths directly. Cross-labyrinth bridge adds material near the TPMS mid-surface to create a passage.")
        self._set_tip(
            self.transition_blend_mode,
            "Offset Surface Interpolation blends TPMS part thresholds. Sigmoid blend uses an S-shaped signed-field transition.",
        )
        self._set_tip(self.sampling, "Boundary sampling resolution for tessellated signed-distance clipping. Zero uses TPMS resolution.")
        self._set_tip(self.add_caps, "Adds cap surfaces where TPMS intersects the boundary so the mesh can be closed.")
        self._set_tip(self.base_density, "Base unit-cell density multiplier away from selected grading faces.")
        self._set_tip(self.density_count_mode, "Controls whether density grading changes local cell count or preserves total count.")
        self._set_tip(self.grading_resolution, "Harmonic grading solve resolution. Lower values are faster; zero uses TPMS resolution.")
        self._set_tip(
            self.harmonic_boundary_condition,
            "Conductor fixes unselected boundary faces to the base value. Insulator leaves them free, like a no-flux electric boundary.",
        )
        self._set_tip(self.origin_mode, "Controls where the TPMS coordinate system starts.")
        self._set_tip(self.origin_select, "Use the currently selected datum point or object placement as the TPMS origin.")
        for widget in (self.origin_x, self.origin_y, self.origin_z):
            self._set_tip(widget, "Custom TPMS origin coordinate.")
        self._set_tip(self.rotation_mode, "Controls the TPMS local coordinate frame rotation.")
        self._set_tip(self.rotation_select, "Use the currently selected datum point or object placement as the TPMS rotation source.")
        for widget in (self.rotation_x, self.rotation_y, self.rotation_z):
            self._set_tip(widget, "Custom TPMS rotation angle in degrees.")
        self._set_tip(self.mesh_relaxation, "Apply Lloyd-style smoothing after mesh generation.")
        self._set_tip(self.relax_iterations, "Number of Lloyd relaxation iterations.")
        self._set_tip(self.relax_skip_boundary, "Keep boundary and cap seam vertices fixed during relaxation.")
        self._set_tip(self.relax_cap_surface, "Allow cap vertices to relax tangentially while preserving cap closure.")

    def _surface_changed(self, name):
        if name in self.generator.SURFACE_EQUATIONS:
            self.equation.setText(self.generator.SURFACE_EQUATIONS[name])
        elif name in (self.generator.SURFACE_EMPTY, self.generator.SURFACE_SOLID_FILL):
            self.equation.setText("")
        self._update_surface_controls()
        self._update_coordinate_controls()
        self._update_density_controls()
        self._update_relax_controls()

    def _update_surface_controls(self):
        structure_enabled = self._structure_surface_active() and not self._transition_role_active()
        custom_enabled = self.surface.currentText() == "Custom" and structure_enabled
        self._set_enabled(self.equation, custom_enabled)
        self._set_enabled(self.part, structure_enabled)
        self._set_enabled(self.offset, structure_enabled)
        self._set_enabled_many(
            (
                self.cell_x,
                self.cell_y,
                self.cell_z,
                self.phase_x,
                self.phase_y,
                self.phase_z,
                self.coordinate_mode,
            ),
            structure_enabled,
        )

    def _result_text(self):
        return "{} facets, solid={}, non-manifold={}".format(
            int(getattr(self.obj, "FacetCount", 0)),
            bool(getattr(self.obj, "IsSolidMesh", False)),
            bool(getattr(self.obj, "HasNonManifolds", False)),
        )

    def _region_status_text(self):
        return "{}; role={}; count={}".format(
            str(getattr(self.obj, "RegionDescription", "No region data")),
            str(getattr(self.obj, "RegionRole", "Base")),
            int(getattr(self.obj, "RegionCount", 0)),
        )

    def _boundary_text(self):
        boundary = getattr(self.obj, "BoundaryObject", None)
        if boundary is None:
            return "None"
        return getattr(boundary, "Label", getattr(boundary, "Name", "Selected object"))



    def _current_boundary_object(self):
        if hasattr(self, "_pending_boundary_object"):
            return self._pending_boundary_object
        return getattr(self.obj, "BoundaryObject", None)

    def _region_items(self):
        try:
            from objects.TPMSUnitCell import boundary_region_items

            return boundary_region_items(self._current_boundary_object())
        except Exception:
            return []

    def _boundary_method_text(self):
        if (
            hasattr(self, "coordinate_mode")
            and self.coordinate_mode.currentText() == self.generator.COORDINATE_CYLINDRICAL_RING
            and self.boundary_mode.currentText() == self.generator.BOUNDARY_BOX
        ):
            return "Cylindrical ring parameter space"
        ring_prefix = ""
        if (
            hasattr(self, "coordinate_mode")
            and self.coordinate_mode.currentText() == self.generator.COORDINATE_CYLINDRICAL_RING
        ):
            ring_prefix = "Cylindrical ring clipped by "
        def method_text(text):
            return ring_prefix + text.lower() if ring_prefix else text

        if self.boundary_mode.currentText() == self.generator.BOUNDARY_BOX:
            return "No selected boundary"
        boundary = self._current_boundary_object()
        if boundary is None:
            return "No selected boundary"
        if self.boundary_evaluation.currentText() == self.generator.BOUNDARY_EVALUATION_TESSELLATED_SDF:
            if hasattr(boundary, "Shape") or hasattr(boundary, "Mesh"):
                return method_text("Tessellation signed-distance")
        type_id = getattr(boundary, "TypeId", "")
        if self._is_boolean_fragments_feature(boundary):
            return method_text("Analytical BooleanFragments with tessellation fallback")
        if type_id in ("Part::Fuse", "Part::Cut", "Part::Common", "Part::MultiFuse", "Part::MultiCommon"):
            return method_text("Analytical CSG with tessellation fallback")
        if type_id == "Part::Sphere" and hasattr(boundary, "Radius"):
            return method_text("Analytical sphere")
        spherical_radii = self._analytical_spherical_radii(boundary)
        if len(spherical_radii) == 1:
            return method_text("Analytical sphere")
        if len(spherical_radii) == 2:
            return method_text("Analytical hollow sphere")
        if type_id == "Part::Box" and all(hasattr(boundary, name) for name in ("Length", "Width", "Height")):
            return method_text("Analytical box")
        if type_id == "Part::Cylinder" and all(hasattr(boundary, name) for name in ("Radius", "Height")):
            return method_text("Analytical cylinder")
        if self._is_basic_tube_feature(boundary):
            return method_text("Analytical tube")
        cylindrical_radii = self._analytical_cylindrical_radii(boundary)
        if len(cylindrical_radii) == 1:
            return method_text("Analytical cylinder")
        if len(cylindrical_radii) == 2:
            return method_text("Analytical tube")
        if hasattr(boundary, "Shape"):
            return method_text("Tessellation signed-distance")
        if hasattr(boundary, "Mesh"):
            return method_text("Tessellation signed-distance")
        return "Unsupported boundary"

    def _is_boolean_fragments_feature(self, boundary):
        if getattr(boundary, "TypeId", "") != "Part::FeaturePython":
            return False
        proxy = getattr(boundary, "Proxy", None)
        if getattr(proxy, "Type", "") == "FeatureBooleanFragments":
            return True
        return type(proxy).__name__ == "FeatureBooleanFragments"

    def _is_basic_tube_feature(self, boundary):
        if getattr(boundary, "TypeId", "") != "Part::FeaturePython":
            return False
        proxy = getattr(boundary, "Proxy", None)
        if type(proxy).__name__ != "TubeFeature":
            return False
        return all(hasattr(boundary, name) for name in ("InnerRadius", "OuterRadius", "Height"))

    def _analytical_cylindrical_radii(self, boundary):
        shape = getattr(boundary, "Shape", None)
        if shape is None or shape.isNull():
            return []
        radii = []
        for face in shape.Faces:
            surface = face.Surface
            surface_type = type(surface).__name__
            if surface_type == "Plane":
                continue
            if surface_type != "Cylinder" or not hasattr(surface, "Radius"):
                return []
            if surface_type == "Cylinder" and hasattr(surface, "Radius"):
                radius = round(float(surface.Radius), 9)
                if radius not in radii:
                    radii.append(radius)
        return radii

    def _analytical_spherical_radii(self, boundary):
        shape = getattr(boundary, "Shape", None)
        if shape is None or shape.isNull():
            return []
        radii = []
        for face in shape.Faces:
            surface = face.Surface
            if type(surface).__name__ == "Sphere" and hasattr(surface, "Radius"):
                radius = round(float(surface.Radius), 9)
                if radius not in radii:
                    radii.append(radius)
        return radii

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
        self.boundary_mode.setEnabled(True)
        self.boundary_evaluation.setEnabled(enabled)
        self.boundary_label.setEnabled(enabled)
        self.boundary_select.setEnabled(enabled)
        self.sampling.setEnabled(enabled)
        self._update_region_controls(enabled)
        self.boundary_method.setText(self._boundary_method_text())

    def _update_region_controls(self, boundary_enabled=None):
        if boundary_enabled is None:
            boundary_enabled = self.boundary_mode.currentText() == self.generator.BOUNDARY_SELECTED_SOLID
        items = self._region_items() if boundary_enabled else []
        try:
            from objects.TPMSUnitCell import _effective_region_index_for_object
            current = _effective_region_index_for_object(self.obj)
        except Exception:
            current = int(getattr(self.obj, "RegionIndex", 0))
        if hasattr(self, "_pending_region_index"):
            current = int(self._pending_region_index)

        self.region_index.blockSignals(True)
        self.region_index.clear()
        for item in items:
            self.region_index.addItem(item["label"], item["index"])
        if not items:
            self.region_index.addItem("No solid regions", 0)
        self.region_index.blockSignals(False)

        multi_region = boundary_enabled and len(items) > 1
        self.region_mode.setEnabled(multi_region)
        self.region_index.setEnabled(multi_region and self.region_mode.currentText() == "Single region")
        self._set_enabled(self.resolution, self.region_role.currentText() == "Base")
        if items:
            self.region_index.setCurrentIndex(max(0, min(current, len(items) - 1)))
        if not multi_region:
            self.region_mode.setCurrentText("All regions")
        if hasattr(self, "region_status"):
            self.region_status.setText(self._region_status_text())
        if hasattr(self, "transition_source"):
            self._update_transition_controls()

    def _update_transition_controls(self):
        enabled = self.region_role.currentText() == "Transition"
        self._set_enabled(self.transition_source, enabled)
        self._set_enabled(self.transition_target, enabled)
        region_count = max(1, len(self._region_items()))
        self.transition_source.setRange(1, region_count)
        self.transition_target.setRange(1, region_count)
        self._set_enabled(self.transition_blend_mode, enabled)
        self._set_enabled(self.transition_source_labyrinth, enabled)
        self._set_enabled(self.transition_target_labyrinth, enabled)
        self._set_enabled(self.transition_topology_mode, enabled)
        transition_role = self.region_role.currentText() == "Transition"
        for widget in (
            self.surface,
            self.equation,
            self.part,
            self.offset,
            self.cell_x,
            self.cell_y,
            self.cell_z,
            self.phase_x,
            self.phase_y,
            self.phase_z,
            self.base_density,
            self.density_count_mode,
            self.grading_resolution,
            self.harmonic_boundary_condition,
        ):
            self._set_enabled(widget, not transition_role)
        self._update_surface_controls()
        self._update_coordinate_controls(refresh_boundary=False)
        self._update_density_controls()
        self._update_relax_controls()

    def _update_coordinate_controls(self, refresh_boundary=True):
        ring_mode = (
            self.coordinate_mode.currentText() == self.generator.COORDINATE_CYLINDRICAL_RING
            and self._structure_surface_active()
            and not self._transition_role_active()
        )
        for widget in (
            self.ring_radius,
            self.ring_outer_radius,
            self.ring_height,
            self.ring_angular_cells,
        ):
            self._set_enabled(widget, ring_mode)
        if refresh_boundary:
            self._update_boundary_controls()

    def _update_density_controls(self):
        structure_enabled = self._structure_surface_active() and not self._transition_role_active()
        base_region = self.region_role.currentText() == "Base"
        grading_owner = structure_enabled and base_region

        self._set_enabled(self.base_density, structure_enabled)
        self._set_enabled(self.density_count_mode, grading_owner)

        # Dynamically check if any enabled grading control uses Harmonic
        harmonic_enabled = False
        doc = self.obj.Document
        if doc is not None:
            for candidate in doc.Objects:
                if hasattr(candidate, "Proxy") and candidate.Proxy.__class__.__name__ == "TPMSGradingControl":
                    if bool(getattr(candidate, "Enabled", True)):
                        if (
                            (bool(getattr(candidate, "UseUnitCellDensity", False)) and str(getattr(candidate, "DensitySource", "")) == self.generator.GRADIENT_HARMONIC)
                            or (bool(getattr(candidate, "UseThickness", False)) and str(getattr(candidate, "ThicknessSource", "")) == self.generator.GRADIENT_HARMONIC)
                        ):
                            harmonic_enabled = True
                            break

        self._set_enabled(self.grading_resolution, grading_owner and harmonic_enabled)
        self._set_enabled(self.harmonic_boundary_condition, grading_owner and harmonic_enabled)

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
                self._set_boundary_object(selected)
                return
            if hasattr(selected, "Mesh") and selected.Mesh.CountFacets > 0:
                self._set_boundary_object(selected)
                return
        QtWidgets.QMessageBox.warning(
            self.form,
            "TPMS Parameters",
            "Select a closed solid or mesh boundary first.",
        )

    def _set_boundary_object(self, boundary):
        self._pending_boundary_object = boundary
        self._pending_region_index = 0
        self.boundary_label.setText(getattr(boundary, "Label", getattr(boundary, "Name", "Selected object")))
        self.boundary_mode.setCurrentText(self.generator.BOUNDARY_SELECTED_SOLID)
        self._update_boundary_controls()
        self._apply_boundary_change()

    def _apply_boundary_change(self):
        obj = self.obj
        doc = obj.Document
        doc.openTransaction("Change TPMS boundary")
        try:
            obj.BoundaryMode = self.boundary_mode.currentText()
            obj.BoundaryEvaluation = self.boundary_evaluation.currentText()
            obj.BoundaryObject = self._current_boundary_object()
            obj.RegionMode = self.region_mode.currentText()
            obj.RegionIndex = int(self.region_index.currentData() or 0)
            obj.RegionRole = self.region_role.currentText()
            obj.TransitionSourceRegion = self._stored_region_index(self.transition_source.value())
            obj.TransitionTargetRegion = self._stored_region_index(self.transition_target.value())
            obj.TransitionBlendMode = self.transition_blend_mode.currentText()
            obj.TransitionCorrectionFactor = float(self.transition_correction_factor.value())
            obj.TransitionSourceLabyrinth = self.transition_source_labyrinth.currentText()
            obj.TransitionTargetLabyrinth = self.transition_target_labyrinth.currentText()
            obj.TransitionTopologyMode = self.transition_topology_mode.currentText()
            obj.Sampling = float(self.sampling.value())
            obj.AddCaps = bool(self.add_caps.isChecked())
            obj.touch()
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()
        self.boundary_method.setText(self._boundary_method_text())
        self.region_status.setText(self._region_status_text())
        self.result.setText(self._result_text())

    def _apply_grading_settings(self):
        obj = self.obj
        obj.BaseDensity = float(self.base_density.value())
        if self.region_role.currentText() == "Base":
            obj.DensityCountMode = self.density_count_mode.currentText()
            obj.GradingResolution = int(self.grading_resolution.value())
            obj.HarmonicBoundaryCondition = self.harmonic_boundary_condition.currentText()
        obj.touch()

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
            if self.region_role.currentText() == "Base":
                obj.Resolution = int(self.resolution.value())
            obj.RepeatX = 1
            obj.RepeatY = 1
            obj.RepeatZ = 1
            obj.Offset = float(self.offset.value())
            obj.CellSize = App.Vector(self.cell_x.value(), self.cell_y.value(), self.cell_z.value())
            obj.Phase = App.Vector(self.phase_x.value(), self.phase_y.value(), self.phase_z.value())
            obj.CoordinateMode = self.coordinate_mode.currentText()
            obj.RingRadius = float(self.ring_radius.value())
            obj.RingOuterRadius = max(float(self.ring_outer_radius.value()), float(self.ring_radius.value()) + 1e-9)
            obj.RingHeight = float(self.ring_height.value())
            obj.RingAngularCells = int(self.ring_angular_cells.value())
            self._apply_grading_settings()
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
            obj.BoundaryEvaluation = self.boundary_evaluation.currentText()
            if hasattr(self, "_pending_boundary_object"):
                obj.BoundaryObject = self._pending_boundary_object
            obj.RegionMode = self.region_mode.currentText()
            current_index = int(self.region_index.currentData() or 0)
            obj.RegionIndex = current_index
            source_obj = None
            for item in self._region_items():
                if int(item["index"]) == current_index:
                    source_obj = item.get("analytical_object")
                    break
            if hasattr(obj, "RegionSourceObject"):
                obj.RegionSourceObject = source_obj
            obj.RegionRole = self.region_role.currentText()
            obj.TransitionSourceRegion = self._stored_region_index(self.transition_source.value())
            obj.TransitionTargetRegion = self._stored_region_index(self.transition_target.value())
            obj.TransitionBlendMode = self.transition_blend_mode.currentText()
            obj.TransitionCorrectionFactor = float(self.transition_correction_factor.value())
            obj.TransitionSourceLabyrinth = self.transition_source_labyrinth.currentText()
            obj.TransitionTargetLabyrinth = self.transition_target_labyrinth.currentText()
            obj.TransitionTopologyMode = self.transition_topology_mode.currentText()
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
