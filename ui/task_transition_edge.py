import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets


class TPMSTransitionEdgeTaskPanel:
    def __init__(self, obj):
        import tpms_generator

        self.obj = obj
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("TPMS Transition Edge")
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

        self.edges = QtWidgets.QLabel(", ".join(getattr(obj, "EdgeNames", [])) or "None")
        self.edges.setWordWrap(True)
        form.addRow("Edges", self.edges)

        self.btn_select = QtWidgets.QPushButton("Use selected edge")
        self.btn_select.clicked.connect(self._use_selected_edge)
        form.addRow("", self.btn_select)

        self.blend_radius = self._double_spin(float(getattr(obj, "BlendRadius", 5.0)), 0.001, 100000.0, 0.1)
        form.addRow("Blend radius", self.blend_radius)

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

        # Temporary variables to store newly selected source and edges
        self.new_source = getattr(obj, "SourceObject", None)
        self.new_edges = list(getattr(obj, "EdgeNames", []))

        self._set_tooltips()

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

    def _set_tooltips(self):
        self._set_tip(self.enabled, "Turns this transition edge control on or off.")
        self._set_tip(self.btn_select, "Grabs the edge currently selected in the 3D viewer.")
        self._set_tip(self.blend_radius, "The radius of the transition blending cylinder around the edge.")
        self._set_tip(self.transition_blend_mode, "How transition region blends adjacent structures.")

    def _use_selected_edge(self):
        selections = Gui.Selection.getSelectionEx()
        if not selections:
            QtWidgets.QMessageBox.warning(self.form, "Transition Edge", "Select an edge in the 3D viewer first.")
            return

        for selection in selections:
            source = getattr(selection, "Object", None)
            if source is None or not hasattr(source, "Shape"):
                continue
            edge_names = [
                str(name)
                for name in getattr(selection, "SubElementNames", [])
                if str(name).startswith("Edge")
            ]
            if not edge_names:
                continue

            self.new_source = source
            self.new_edges = edge_names
            self.source.setText(getattr(source, "Label", getattr(source, "Name", "Selected object")))
            self.edges.setText(", ".join(edge_names))
            return

        QtWidgets.QMessageBox.warning(self.form, "Transition Edge", "No edge was selected in the 3D viewer.")

    def accept(self):
        obj = self.obj
        doc = obj.Document
        doc.openTransaction("Edit TPMS transition edge")
        try:
            obj.Enabled = bool(self.enabled.isChecked())
            if self.new_source is not None:
                obj.SourceObject = self.new_source
            obj.EdgeNames = list(self.new_edges)
            obj.BlendRadius = float(self.blend_radius.value())
            obj.TransitionBlendMode = self.transition_blend_mode.currentText()
            obj.touch()
            doc.recompute()
        except Exception as exc:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(self.form, "Transition Edge", str(exc))
            raise
        else:
            doc.commitTransaction()
        return True

    def reject(self):
        return True
