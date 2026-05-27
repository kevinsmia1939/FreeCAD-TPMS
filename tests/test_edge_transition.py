"""Integration test for edge-based TPMS transitions.

Run with:
    FreeCADCmd -c "import runpy; runpy.run_path('tests/test_edge_transition.py', run_name='__main__')"
"""

import os
import sys

MOD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if MOD_PATH not in sys.path:
    sys.path.insert(0, MOD_PATH)

import FreeCAD as App
import numpy as np
import tpms_generator
from objects.TPMSUnitCell import (
    add_tpms_transition_edge,
    _adjacent_solid_indices_for_edge,
    boundary_region_solids
)


def main():
    path = "/home/kevin/.local/share/FreeCAD/v1-1/Mod/gyroid_assembler/example/three_region_overlapped.FCStd"
    print("Loading file: {}".format(path))
    doc = App.openDocument(path)
    
    # Find base controller
    base = None
    for obj in doc.Objects:
        if hasattr(obj, "TransitionEdges"):
            base = obj
            break
            
    assert base is not None, "Base controller not found in document"
    
    # Configure base: Sheet Gyroid
    base.Surface = "Gyroid"
    base.Equation = tpms_generator.SURFACE_EQUATIONS["Gyroid"]
    base.Part = "Sheet"
    base.Resolution = 8
    base.Offset = 0.3
    
    # Configure overrides:
    # Region 2 (Index 1): Schwarz P
    # Region 3 (Index 2): Schoen FRD
    from objects.TPMSUnitCell import _effective_region_index_for_object
    for obj in doc.Objects:
        if getattr(obj, "RegionRole", None) == "Override":
            idx = _effective_region_index_for_object(obj)
            if idx == 1:
                obj.Surface = "Schwarz P"
                obj.Equation = tpms_generator.SURFACE_EQUATIONS["Schwarz P"]
                obj.Part = "Sheet"
                obj.Offset = 0.3
                print("Configured Region 2 Override: Schwarz P")
            elif idx == 2:
                obj.Surface = "Schoen FRD"
                obj.Equation = tpms_generator.SURFACE_EQUATIONS["Schoen FRD"]
                obj.Part = "Sheet"
                obj.Offset = 0.3
                print("Configured Region 3 Override: Schoen FRD")
                
    bf = base.BoundaryObject
    assert bf is not None, "BoundaryObject is missing"
    
    # Let's inspect Edge3 of the boundary object
    print("Extracting Edge3 from BooleanFragments...")
    edge = bf.Shape.getElement("Edge3")
    assert edge is not None, "Edge3 not found in BooleanFragments compound shape"
    
    # Verify we can find adjacent solids sharing Edge3
    adj_indices = _adjacent_solid_indices_for_edge(bf, edge)
    print("Adjacent solid indices for Edge3: {}".format(adj_indices))
    assert len(adj_indices) >= 3, "Expected at least 3 adjacent solids sharing Edge3, but found: {}".format(len(adj_indices))
    
    # Add the edge transition control
    print("Adding edge transition control for Edge3...")
    control = add_tpms_transition_edge(base, source_object=bf, edge_names=["Edge3"], blend_radius=5.0)
    control.TransitionBlendMode = tpms_generator.TRANSITION_BLEND_SIGMOID
    
    print("Recomputing document...")
    doc.recompute()
    
    # Let's inspect the generated mesh
    mesh_obj = base.ResultMesh
    facet_count = mesh_obj.Mesh.CountFacets
    print("Generated mesh contains {} facets.".format(facet_count))
    assert facet_count > 0, "Generated mesh contains 0 facets, generation failed"
    
    is_solid = mesh_obj.Mesh.isSolid()
    print("Is solid mesh: {}".format(is_solid))
    assert is_solid, "Generated edge-blended hybrid mesh is not solid (not watertight/manifold)"
    
    print("Switching to Normalized sum (ASLI) blend mode...")
    control.TransitionBlendMode = tpms_generator.TRANSITION_BLEND_NORMALIZED_SUM
    
    print("Triggering document recompute for ASLI transition...")
    doc.recompute()
    
    facet_count = mesh_obj.Mesh.CountFacets
    print("Generated ASLI mesh contains {} facets.".format(facet_count))
    assert facet_count > 0, "Generated ASLI mesh contains 0 facets, generation failed"
    assert mesh_obj.Mesh.isSolid(), "Generated ASLI hybrid mesh is not solid"
    
    print("\nALL EDGE TRANSITION TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
