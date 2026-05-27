"""Continuity and smoothness validation test for edge-based TPMS transitions.
Mathematically measures the maximum Z gap along Edge3 AND at the cylinder boundary
to objectively prove there are no voids/holes and no pinching at the transition boundary.

Run with:
    FreeCADCmd -c "import runpy; runpy.run_path('tests/test_edge_transition_smoothness.py', run_name='__main__')"
"""

import os
import sys

MOD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if MOD_PATH not in sys.path:
    sys.path.insert(0, MOD_PATH)

import FreeCAD as App
import numpy as np
import tpms_generator
from objects.TPMSUnitCell import add_tpms_transition_edge


def verify_edge_continuity(mesh_obj, label, blend_radius=5.0):
    """Check Z-gap continuity near Edge3 and at the cylinder boundary."""
    # Edge3 lies along X=10, Y=0, Z=[0, 20]
    pts_near_edge = []
    pts_at_boundary = []
    for p in mesh_obj.Mesh.Points:
        dist_to_edge = np.sqrt((p.x - 10.0)**2 + p.y**2)
        if 0.0 <= p.z <= 20.0:
            if dist_to_edge <= 1.5:
                pts_near_edge.append(float(p.z))
            # Cylinder boundary ring: d in [R-1.5, R+1.5]
            if abs(dist_to_edge - blend_radius) <= 1.5:
                pts_at_boundary.append(float(p.z))
                
    print("[{}] Found {} vertices near Edge3 center.".format(label, len(pts_near_edge)))
    assert len(pts_near_edge) > 0, "No vertices found near Edge3, indicates severe pinching or voids!"
    
    # Sort Z values and compute maximum gap between consecutive vertices
    z_sorted = sorted(pts_near_edge)
    z_gaps = [z_sorted[i+1] - z_sorted[i] for i in range(len(z_sorted)-1)]
    max_gap = max(z_gaps) if z_gaps else 20.0
    
    print("[{}] Maximum Z gap near edge center: {:.4f} mm".format(label, max_gap))
    assert max_gap < 1.2, "Edge center discontinuity! Max Z gap is {:.4f} mm".format(max_gap)
    print("[{}] EDGE CENTER: Continuous (no holes)!".format(label))
    
    # Verify cylinder boundary continuity (where pinching used to happen)
    print("[{}] Found {} vertices at cylinder boundary (d~{}).".format(label, len(pts_at_boundary), blend_radius))
    if len(pts_at_boundary) > 1:
        z_sorted_b = sorted(pts_at_boundary)
        z_gaps_b = [z_sorted_b[i+1] - z_sorted_b[i] for i in range(len(z_sorted_b)-1)]
        max_gap_b = max(z_gaps_b) if z_gaps_b else 20.0
        print("[{}] Maximum Z gap at cylinder boundary: {:.4f} mm".format(label, max_gap_b))
        assert max_gap_b < 1.2, "Cylinder boundary pinching! Max Z gap is {:.4f} mm".format(max_gap_b)
        print("[{}] CYLINDER BOUNDARY: Continuous (no pinching)!".format(label))
    else:
        print("[{}] WARNING: Not enough boundary vertices to measure.".format(label))


def main():
    path = "/home/kevin/.local/share/FreeCAD/v1-1/Mod/gyroid_assembler/example/three_region_overlapped.FCStd"
    print("Loading file: {}".format(path))
    doc = App.openDocument(path)
    
    base = [o for o in doc.Objects if hasattr(o, "TransitionEdges")][0]
    
    # Set to higher resolution for precise smoothness check
    base.Resolution = 32
    bf = base.BoundaryObject
    
    # Clean previous transition edges to prevent duplicate overlap
    edges = list(base.TransitionEdges)
    for e in edges:
        doc.removeObject(e.Name)
    base.TransitionEdges = []
    doc.recompute()
    
    # Add our Edge3 transition
    print("\n--- Testing Sigmoid Blend Mode ---")
    control = add_tpms_transition_edge(base, source_object=bf, edge_names=["Edge3"], blend_radius=5.0)
    control.TransitionBlendMode = tpms_generator.TRANSITION_BLEND_SIGMOID
    doc.recompute()
    verify_edge_continuity(base.ResultMesh, "Sigmoid Mode")
    
    print("\n--- Testing ASLI Normalized Sum Blend Mode ---")
    control.TransitionBlendMode = tpms_generator.TRANSITION_BLEND_NORMALIZED_SUM
    doc.recompute()
    verify_edge_continuity(base.ResultMesh, "ASLI Mode")
    
    print("\n--- Testing Threshold Blend Mode ---")
    control.TransitionBlendMode = tpms_generator.TRANSITION_BLEND_THRESHOLD
    doc.recompute()
    verify_edge_continuity(base.ResultMesh, "Threshold Mode")
    
    print("\nALL SMOOTHNESS AND CONTINUITY TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
