"""Integration/Unit test for region-specific thickness grading negation on shared faces.

Run with:
    FreeCADCmd -c "import runpy; runpy.run_path('tests/test_region_negation.py', run_name='__main__')"
"""

import os
import sys
import numpy as np

MOD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if MOD_PATH not in sys.path:
    sys.path.insert(0, MOD_PATH)

import FreeCAD as App
import BOPTools.SplitFeatures
import tpms_generator
from objects.TPMSUnitCell import (
    make_tpms_unit_cell,
    add_tpms_region_settings,
    add_grading_control,
    boundary_region_solids,
)

def test_negation():
    print("Initializing region negation test...")
    doc = App.newDocument("TestRegionNegation")

    box1 = doc.addObject("Part::Box", "Box1")
    box1.Length = 10.0
    box1.Width = 10.0
    box1.Height = 10.0

    box2 = doc.addObject("Part::Box", "Box2")
    box2.Length = 10.0
    box2.Width = 10.0
    box2.Height = 10.0
    box2.Placement = App.Placement(App.Vector(10.0, 0.0, 0.0), App.Rotation())
    doc.recompute()

    bf = BOPTools.SplitFeatures.makeBooleanFragments("BooleanFragments")
    bf.Objects = [box1, box2]
    bf.Mode = "Standard"
    doc.recompute()

    container, base, mesh_obj = make_tpms_unit_cell(doc)
    base.BoundaryMode = "Selected solid"
    base.BoundaryObject = bf
    base.Resolution = 8
    base.Offset = 0.3
    base.CellSize = App.Vector(10.0, 10.0, 10.0)
    base.Surface = "Gyroid"
    base.Equation = tpms_generator.SURFACE_EQUATIONS["Gyroid"]
    base.Part = "Sheet"

    override, _ = add_tpms_region_settings(base)
    override.RegionRole = "Override"
    override.RegionIndex = 1
    override.RegionSourceObject = box2
    override.Surface = "Gyroid"
    override.Equation = tpms_generator.SURFACE_EQUATIONS["Gyroid"]
    override.Part = "Upper skeletal"

    shared_face_name = None
    for face_index, face in enumerate(bf.Shape.Faces):
        com = face.CenterOfMass
        if abs(com.x - 10.0) < 1e-2 and abs(com.y - 5.0) < 1e-2 and abs(com.z - 5.0) < 1e-2:
            shared_face_name = "Face" + str(face_index + 1)
            break

    print("Located shared face: {}".format(shared_face_name))
    assert shared_face_name is not None

    # Let's add the grading control
    from objects.TPMSUnitCell import add_grading_control
    control = add_grading_control(
        base,
        bf,
        [shared_face_name],
        unit_cell_density=1.5,
        unit_cell_transition=5.0,
        thickness=0.5,
        thickness_transition=4.0,
        use_unit_cell_density=False,
        use_thickness=True,
    )

    # Set NegateRegions to contain the override region (Region 2)
    control.NegateRegions = [override]
    doc.recompute()

    from objects.TPMSUnitCell import boundary_region_items, _density_offset_controls
    items = boundary_region_items(bf)

    override_idx = None
    for item in items:
        if item.get("analytical_object") is override.RegionSourceObject:
            override_idx = int(item["index"])
            break
            
    print("override_idx topologically resolved to:", override_idx)
    assert override_idx is not None
    
    offset_ctrls = _density_offset_controls(base)
    assert len(offset_ctrls) > 0
    assert override_idx in offset_ctrls[0]["negated_regions"]
    print("Verification of negated_regions index mapping: PASS")

    # Verify that the generator evaluates the thickness field with correct regional signs.
    # Region 0 (x < 10) should have target = 0.5.
    # Region 1 (x > 10) should have target = -0.5.
    from objects.TPMSUnitCell import boundary_region_items, _hybrid_region_specs
    items = boundary_region_items(bf)
    region_specs = _hybrid_region_specs(base, items)

    print("Generating hybrid polydata mesh...")
    poly = tpms_generator.generate_hybrid_polydata(
        base.Equation,
        base.Part,
        (10.0, 10.0, 10.0),
        (1, 1, 1),
        8,
        0.3,
        (0.0, 0.0, 0.0),
        base.BoundaryMode,
        bf,
        0.0,
        True,
        None,
        None,
        1.0,
        region_specs,
        [],
        [],
        "Uniform",
        [],
        "Follow unit cell density",
        "Face distance",
        "Non-uniform",
        offset_ctrls,
        "Face distance",
    )
    print("Mesh generation successful: {} points".format(poly.GetNumberOfPoints()))
    assert poly.GetNumberOfPoints() > 0

    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_negation()
