import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets


class TPMSTransitionFaceTaskPanel:
    def __init__(self, obj):
        import tpms_generator

        self.obj = obj
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("TPMS Transition Face")
        self._form_layouts = []

        layout = QtWidgets.QVBoxLayout(self.form)
        form = QtWidgets.QFormLayout()
        self._form_layouts.append(form)
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

        self.btn_select = QtWidgets.QPushButton("Use selected face")
        self.btn_select.clicked.connect(self._use_selected_face)
        form.addRow("", self.btn_select)

        self.blend_width = self._double_spin(float(getattr(obj, "BlendWidth", 5.0)), 0.001, 100000.0, 0.1)
        form.addRow("Blend width", self.blend_width)

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
        form.addRow("Blend mode", self.transition_blend_mode)

        self.transition_correction_factor = self._double_spin(float(getattr(obj, "TransitionCorrectionFactor", 0.0)), -10.0, 10.0, 0.05)
        form.addRow("ASLI Correction", self.transition_correction_factor)

        self.transition_source_labyrinth = QtWidgets.QComboBox()
        self.transition_source_labyrinth.addItems(tpms_generator.labyrinth_modes())
        self.transition_source_labyrinth.setCurrentText(
            str(getattr(obj, "TransitionSourceLabyrinth", tpms_generator.LABYRINTH_AUTO))
        )
        form.addRow("Source labyrinth", self.transition_source_labyrinth)

        self.transition_target_labyrinth = QtWidgets.QComboBox()
        self.transition_target_labyrinth.addItems(tpms_generator.labyrinth_modes())
        self.transition_target_labyrinth.setCurrentText(
            str(getattr(obj, "TransitionTargetLabyrinth", tpms_generator.LABYRINTH_AUTO))
        )
        form.addRow("Target labyrinth", self.transition_target_labyrinth)

        self.transition_topology_mode = QtWidgets.QComboBox()
        self.transition_topology_mode.addItems(tpms_generator.transition_topology_modes())
        self.transition_topology_mode.setCurrentText(
            str(getattr(obj, "TransitionTopologyMode", tpms_generator.TRANSITION_TOPOLOGY_SAME_SIDE))
        )
        form.addRow("Topology", self.transition_topology_mode)

        # Temporary variables to store newly selected source and faces
        self.new_source = getattr(obj, "SourceObject", None)
        self.new_faces = list(getattr(obj, "FaceNames", []))

        self.transition_blend_mode.currentTextChanged.connect(self._update_controls)
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
        source = getattr(self.obj, "SourceObject", None)
        if source is None:
            return "None"
        return getattr(source, "Label", getattr(source, "Name", "Selected object"))

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
        self._set_tip(self.enabled, "Turns this transition face control on or off.")
        self._set_tip(self.btn_select, "Grabs the face currently selected in the 3D viewer.")
        self._set_tip(self.blend_width, "The width of the transition region across the face.")
        self._set_tip(self.transition_blend_mode, "How transition region blends source and target structures.")
        self._set_tip(self.transition_correction_factor, "Thinning compensation factor for normalized weighted sum.")

    def _update_controls(self):
        is_asli = self.transition_blend_mode.currentText() == "Normalized sum (ASLI)"
        self._set_enabled(self.transition_correction_factor, is_asli)

    def _use_selected_face(self):
        selections = Gui.Selection.getSelectionEx()
        if not selections:
            QtWidgets.QMessageBox.warning(self.form, "Transition Face", "Select a face in the 3D viewer first.")
            return

        for selection in selections:
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

            self.new_source = source
            self.new_faces = face_names
            self.source.setText(getattr(source, "Label", getattr(source, "Name", "Selected object")))
            self.faces.setText(", ".join(face_names))
            return

        QtWidgets.QMessageBox.warning(self.form, "Transition Face", "No face was selected in the 3D viewer.")

    def accept(self):
        obj = self.obj
        doc = obj.Document
        doc.openTransaction("Edit TPMS transition face")
        try:
            obj.Enabled = bool(self.enabled.isChecked())
            if self.new_source is not None:
                obj.SourceObject = self.new_source
            obj.FaceNames = list(self.new_faces)
            obj.BlendWidth = float(self.blend_width.value())
            obj.TransitionBlendMode = self.transition_blend_mode.currentText()
            obj.TransitionCorrectionFactor = float(self.transition_correction_factor.value())
            obj.TransitionSourceLabyrinth = self.transition_source_labyrinth.currentText()
            obj.TransitionTargetLabyrinth = self.transition_target_labyrinth.currentText()
            obj.TransitionTopologyMode = self.transition_topology_mode.currentText()
            obj.touch()
            doc.recompute()
        except Exception as exc:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(self.form, "Transition Face", str(exc))
            raise
        else:
            doc.commitTransaction()
        return True

    def reject(self):
        return True
