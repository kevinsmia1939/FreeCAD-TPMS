# TPMS Generator

FreeCAD workbench for generating TPMS meshes from implicit equations.  The
workbench creates parametric TPMS controller objects in the model tree, so the
mesh can be refreshed after changing the boundary, resolution, equation,
grading, or coordinate mode.

![TPMS Generator example](example/screenshot.png)

## Features

- Generate sheet, skeletal, upper, lower, or zero-surface TPMS meshes.
- Use preset equations such as Gyroid and Schwarz P, or enter a custom implicit
  equation.
- Clip TPMS directly to selected FreeCAD solids without a separate mesh boolean.
- Use analytical boundaries for supported Part boxes, spheres, cylinders, and
  tubes.
- Generate cylindrical-coordinate TPMS rings with seamless angular wrapping.
- Add capped or uncapped meshes.
- Apply uniform or non-uniform unit-cell density and offset/thickness grading.
- Use selected-face distance fields or harmonic fields for grading.
- Split BooleanFragments into regions and assign per-region TPMS settings.
- Blend two TPMS equations through an explicit transition region.

## Installation

Clone or copy this folder into the FreeCAD user `Mod` directory:

```bash
~/.local/share/FreeCAD/v1-1/Mod/gyroid_assembler
```

Restart FreeCAD and select the `TPMS Generator` workbench.

## Basic Workflow

1. Create or import a solid boundary in FreeCAD.
2. Switch to the `TPMS Generator` workbench.
3. Click `Create TPMS Unit Cell`.
4. Select the generated `Base Region Parameters` object in the tree.
5. Set `Boundary Mode` to `Selected solid` and choose the boundary object.
6. Adjust the equation, part type, resolution, cell size, sheet/skeletal
   thickness, and capping options.
7. Click `Refresh TPMS` or recompute the document.

Double-click a TPMS parameter object in the tree to reopen its task panel.

## Boolean Fragment Regions

For a `BooleanFragments` object with multiple solid regions:

1. Use the fragment object as the selected boundary.
2. Click `Add TPMS Settings For All Regions`.
3. Edit each region parameter object as needed.
4. Mark an intermediate region as a transition region when blending two
   different TPMS equations.

Transitions are explicit: shared faces between two regions do not blend by
themselves.  A separate transition region must be assigned source and target
regions.

### Transition Blend Modes

Transition regions support two blend modes:

- `Offset Surface Interpolation`: blends the valid TPMS material interval for
  each part type.  For example, a sheet is treated as the interval around the
  TPMS zero surface, while upper and lower skeletal parts are treated as
  one-sided intervals.  This is the safer choice for transitions between sheet
  and skeletal TPMS because it avoids field cancellation that can create torn or
  abrupt-looking meshes.
- `Sigmoid blend`: blends the signed implicit material fields, but remaps the transition weight through
  a normalized sigmoid curve.  This keeps more of each endpoint structure near
  the transition boundaries and makes the blend change faster near the middle
  of the transition region.

## TPMS Transition Face & Edge

For finer, boundary-specific control in partitioned multi-region models, the workbench supports blending directly along shared faces or shared edges of adjoining solid regions.

### TPMS Transition Face

A face-based transition blends two adjacent TPMS structures across a shared boundary face.

#### Mathematical Formulation

1. **Blend Weight**: The transition weight $t(x)$ is computed from the signed distance $d(x)$ to the shared face and the configured blend width $W$:
   $$t(x) = \text{clip}\left(\frac{1}{2} \left(1 + \frac{2d(x)}{W}\right), 0.0, 1.0\right)$$
   If `Sigmoid` blend mode is selected, $t(x)$ is mapped through a normalized sigmoid curve:
   $$\sigma(t) = \frac{1}{1 + e^{-k(t - 0.5)}}$$

2. **Phase 1 (TPMS & Offset Blend)**: The implicit functions $F$ and offsets $O$ are blended linearly:
   $$F_{blended}(x) = (1 - t(x)) F_{source}(x) + t(x) F_{target}(x)$$
   $$O_{blended}(x) = (1 - t(x)) O_{source} + t(x) O_{target}$$

3. **Phase 2 (Interval Bound Blending)**: To ensure a continuous material boundary without mesh tearing (especially when morphing between sheet and skeletal structures), we blend the lower and upper bounds of the respective part intervals ($L_k, U_k$):
   $$L_{blended}(x) = (1 - t(x)) L_{source}(x) + t(x) L_{target}(x)$$
   $$U_{blended}(x) = (1 - t(x)) U_{source}(x) + t(x) U_{target}(x)$$
   
   The final material field $M_{blended}(x)$ is computed as:
   $$M_{blended}(x) = \min\left(F_{blended}(x) - L_{blended}(x), U_{blended}(x) - F_{blended}(x)\right)$$

---

### TPMS Transition Edge

An edge-based transition blends multiple ($N \ge 2$) adjacent TPMS structures meeting at a shared topological boundary edge.

#### Mathematical Formulation

1. **Blend Weight**: We compute a radial cylindrical blend weight $u(x) = \text{clip}(d_{edge}(x) / R, 0.0, 1.0)$ using the distance $d_{edge}(x)$ to the edge points and the blend radius $R$.
   The edge weight is smoothstepped to zero at the cylinder boundary:
   $$w_{edge}(x) = 1.0 - \text{smoothstep}(u(x))$$

2. **Phase 1 (N-Way Fields & Hierarchical Background Blending)**:
   We evaluate the continuous Euclidean regional weights $w_k(x)$ for each adjacent region $k$ and blend the implicit fields and offsets:
   $$F_{blended}(x) = \sum_{k=1}^N w_k(x) F_k(x), \quad O_{blended}(x) = \sum_{k=1}^N w_k(x) O_k$$
   
   To achieve $C^1$ continuity at the cylinder boundary ($d_{edge} \approx R$), we hierarchically blend $F_{blended}$ and $O_{blended}$ with the pre-existing background fields $F_{bg}$ and $O_{bg}$ (which already contain face transitions):
   $$F_{final}(x) = w_{edge}(x) F_{blended}(x) + (1.0 - w_{edge}(x)) F_{bg}(x)$$
   $$O_{final}(x) = w_{edge}(x) O_{blended}(x) + (1.0 - w_{edge}(x)) O_{bg}(x)$$

3. **Phase 2 (N-Way Interval Boundary Blending)**:
   Directly averaging material fields causes out-of-phase field cancellation, producing thin strings and severe hollow voids along the edge. Instead, we perform **N-Way Interval Boundary Blending** by blending the lower and upper bounds of the part intervals ($L_k, U_k$):
   $$L_{blended}(x) = \sum_{k=1}^N w_k(x) L_k(x), \quad U_{blended}(x) = \sum_{k=1}^N w_k(x) U_k(x)$$
   
   The pure edge material field is then constructed from the final Phase 1 field and these blended bounds:
   $$M_{blended}(x) = \min\left(F_{final}(x) - L_{blended}(x), U_{blended}(x) - F_{final}(x)\right)$$
   
   This edge material field is hierarchically blended into the background material field $M_{bg}(x)$ to ensure a watertight, smooth, and seamless morph:
   $$M_{final}(x) = w_{edge}(x) M_{blended}(x) + (1.0 - w_{edge}(x)) M_{bg}(x)$$

## Cylindrical Rings

Set `Coordinate Mode` to `Cylindrical ring` to generate TPMS in cylindrical
coordinates.  With `Origin Mode` set to `Boundary object`, the ring center
follows the selected boundary object's placement.  Tube boundaries can be used
to clip the ring directly.

## Tests

Run the headless workflow test from this folder:

```bash
python3 -m py_compile tpms_generator.py objects/TPMSUnitCell.py ui/task_tpms.py tests/boolean_fragment_region_workflow.py
FreeCADCmd -c "import runpy; runpy.run_path('tests/boolean_fragment_region_workflow.py', run_name='__main__')"
```

The workflow test checks BooleanFragments region handling, transition-region
generation, cylindrical ring origin handling, and basic mesh validity.

## Notes

- Higher mesh resolution increases generation time and memory use quickly.
- Mesh relaxation is optional and off by default for predictable boundaries.
- Capping is on by default so generated sheet and skeletal meshes can be closed
  against the selected boundary.
- Sheet thickness is symmetric around the TPMS mid-surface.  A sheet thickness
  of `t` generates material between approximately `F = -t/2` and `F = +t/2`,
  so both labyrinth sides are offset equally before boundary clipping and
  grading are applied.
- `example/example1.FCStd` and `example/screenshot.png` show a multi-region TPMS
  setup in FreeCAD.

## License
GPL-3.0 license
