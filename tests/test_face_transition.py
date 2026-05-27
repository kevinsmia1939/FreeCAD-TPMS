"""Integration test for face-based TPMS transitions.

Run with:
    FreeCADCmd -c "import runpy; runpy.run_path('tests/test_face_transition.py', run_name='__main__')"
"""

import os
import sys

MOD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if MOD_PATH not in sys.path:
    sys.path.insert(0, MOD_PATH)

import FreeCAD as App
import BOPTools.SplitFeatures
import tpms_generator
from objects.TPMSUnitCell import (
    make_tpms_unit_cell,
    add_tpms_region_settings,
    add_tpms_transition_face,
    boundary_region_solids
)


def main():
    print("Initializing test document...")
    doc = App.newDocument("TestFaceTransitionDoc")

    print("Creating two adjacent boxes...")
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

    print("Creating BooleanFragments compound solid...")
    bf = BOPTools.SplitFeatures.makeBooleanFragments("BooleanFragments")
    bf.Label = "BooleanFragments"
    bf.Objects = [box1, box2]
    bf.Mode = "Standard"
    doc.recompute()

    # Verify we got exactly two solids in the fragmented compound
    solids = boundary_region_solids(bf)
    print("Found {} solids in BooleanFragments compound.".format(len(solids)))
    assert len(solids) == 2, "Expected exactly 2 solid regions, found {}".format(len(solids))

    print("Creating TPMS base controller...")
    container, base, mesh_obj = make_tpms_unit_cell(doc)
    base.BoundaryMode = "Selected solid"
    base.BoundaryObject = bf
    base.Resolution = 8
    base.Offset = 0.3
    base.CellSize = App.Vector(10.0, 10.0, 10.0)
    base.Surface = "Gyroid"
    base.Equation = tpms_generator.SURFACE_EQUATIONS["Gyroid"]
    base.Part = "Sheet"

    print("Adding override settings for Region 2...")
    override, _ = add_tpms_region_settings(base)
    override.RegionRole = "Override"
    override.RegionIndex = 1
    override.Surface = "Schwarz P"
    override.Equation = tpms_generator.SURFACE_EQUATIONS["Schwarz P"]
    override.Part = "Sheet"

    # Identify the shared face between box 1 and box 2
    # The face lies exactly at X=10, Y=5, Z=5 (center of mass)
    print("Locating shared boundary face in compound shape...")
    shared_face_name = None
    for face_index, face in enumerate(bf.Shape.Faces):
        com = face.CenterOfMass
        if abs(com.x - 10.0) < 1e-2 and abs(com.y - 5.0) < 1e-2 and abs(com.z - 5.0) < 1e-2:
            shared_face_name = "Face" + str(face_index + 1)
            break

    print("Located shared boundary face: {}".format(shared_face_name))
    assert shared_face_name is not None, "Shared face not found by CenterOfMass matching"

    print("Adding face-based TPMS transition...")
    control = add_tpms_transition_face(base, source_object=bf, face_names=[shared_face_name], blend_width=4.0)
    control.TransitionBlendMode = tpms_generator.TRANSITION_BLEND_SIGMOID
    
    print("Triggering document recompute to generate TPMS mesh...")
    doc.recompute()

    print("Verifying generated mesh...")
    facet_count = mesh_obj.Mesh.CountFacets
    print("Generated mesh contains {} facets.".format(facet_count))
    assert facet_count > 0, "Generated mesh contains 0 facets, generation failed"

    is_solid = mesh_obj.Mesh.isSolid()
    print("Is solid mesh: {}".format(is_solid))
    assert is_solid, "Generated hybrid mesh is not solid (not manifold or watertight)"

    print("Switching to Normalized sum (ASLI) blend mode...")
    control.TransitionBlendMode = tpms_generator.TRANSITION_BLEND_NORMALIZED_SUM
    control.TransitionCorrectionFactor = 0.5
    
    print("Triggering document recompute for ASLI transition...")
    doc.recompute()

    facet_count = mesh_obj.Mesh.CountFacets
    print("Generated ASLI mesh contains {} facets.".format(facet_count))
    assert facet_count > 0, "Generated ASLI mesh contains 0 facets, generation failed"
    assert mesh_obj.Mesh.isSolid(), "Generated ASLI hybrid mesh is not solid"

    print("ALL TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
