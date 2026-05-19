import math

import FreeCAD as App
import Mesh
import numpy as np
import pyvista as pv


SURFACE_EQUATIONS = {
    "Gyroid": "sin(x) * cos(y) + sin(y) * cos(z) + sin(z) * cos(x)",
    "Schwarz P": "cos(x) + cos(y) + cos(z)",
    "Schwarz D": "sin(x) * sin(y) * sin(z) + sin(x) * cos(y) * cos(z) + cos(x) * sin(y) * cos(z) + cos(x) * cos(y) * sin(z)",
    "Neovius": "3 * cos(x) + 3 * cos(y) + 3 * cos(z) + 4 * cos(x) * cos(y) * cos(z)",
    "Schoen IWP": "2 * (cos(x) * cos(y) + cos(y) * cos(z) + cos(z) * cos(x)) - (cos(2*x) + cos(2*y) + cos(2*z))",
    "Schoen FRD": "4 * cos(x) * cos(y) * cos(z) - (cos(2*x) * cos(2*y) + cos(2*y) * cos(2*z) + cos(2*z) * cos(2*x))",
    "Lidinoid": "0.5 * (sin(2*x) * cos(y) * sin(z) + sin(2*y) * cos(z) * sin(x) + sin(2*z) * cos(x) * sin(y)) - 0.5 * (cos(2*x) * cos(2*y) + cos(2*y) * cos(2*z) + cos(2*z) * cos(2*x)) + 0.3",
}


PART_SHEET = "Sheet"
PART_UPPER = "Upper skeletal"
PART_LOWER = "Lower skeletal"
PART_SURFACE = "Zero surface"


SAFE_NAMES = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "asin": np.arcsin,
    "acos": np.arccos,
    "atan": np.arctan,
    "atan2": np.arctan2,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "exp": np.exp,
    "log": np.log,
    "minimum": np.minimum,
    "maximum": np.maximum,
    "min": np.minimum,
    "max": np.maximum,
    "pi": np.pi,
}


def surface_names():
    return list(SURFACE_EQUATIONS)


def evaluate_equation(equation, x, y, z):
    namespace = dict(SAFE_NAMES)
    namespace.update({"x": x, "y": y, "z": z})
    return eval(equation, {"__builtins__": {}}, namespace)


def _make_grid(cell_size, repeat_cell, resolution, phase):
    cell_size = np.asarray(cell_size, dtype=float)
    repeat_cell = np.asarray(repeat_cell, dtype=int)
    repeat_cell = np.maximum(repeat_cell, 1)
    phase = np.asarray(phase, dtype=float)
    domain_size = cell_size * repeat_cell
    half = 0.5 * domain_size
    coords = [
        np.linspace(-half[i], half[i], int(resolution) * int(repeat_cell[i]) + 1)
        for i in range(3)
    ]
    x, y, z = np.meshgrid(*coords, indexing="ij")
    grid = pv.StructuredGrid(x, y, z)

    kx, ky, kz = [2.0 * math.pi / max(cell_size[i], 1e-9) for i in range(3)]
    sx = kx * (x + phase[0])
    sy = ky * (y + phase[1])
    sz = kz * (z + phase[2])
    return grid, sx, sy, sz


def generate_polydata(
    equation,
    part=PART_SHEET,
    cell_size=(1.0, 1.0, 1.0),
    repeat_cell=(1, 1, 1),
    resolution=32,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
):
    grid, x, y, z = _make_grid(cell_size, repeat_cell, resolution, phase)
    field = np.asarray(evaluate_equation(equation, x, y, z), dtype=float)
    if field.shape == ():
        field = np.full(x.shape, float(field))

    grid["surface"] = field.ravel(order="F")
    grid["lower_surface"] = (field + 0.5 * float(offset)).ravel(order="F")
    grid["upper_surface"] = (field - 0.5 * float(offset)).ravel(order="F")

    if part == PART_SHEET:
        volume = grid.clip_scalar(scalars="upper_surface").clip_scalar(
            scalars="lower_surface",
            invert=False,
        )
        return volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    if part == PART_UPPER:
        volume = grid.clip_scalar(scalars="upper_surface", invert=False)
        return volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    if part == PART_LOWER:
        volume = grid.clip_scalar(scalars="lower_surface")
        return volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    if part == PART_SURFACE:
        return grid.contour(isosurfaces=[0.0], scalars="surface").extract_surface().clean().triangulate()
    raise ValueError("Unsupported TPMS part: {}".format(part))


def polydata_to_freecad_mesh(polydata):
    polydata = polydata.triangulate().clean()
    faces = np.asarray(polydata.faces)
    if len(faces) == 0:
        raise ValueError("Generated TPMS mesh is empty")

    mesh = Mesh.Mesh()
    points = polydata.points
    i = 0
    while i < len(faces):
        count = int(faces[i])
        if count == 3:
            a, b, c = [int(v) for v in faces[i + 1 : i + 4]]
            mesh.addFacet(
                App.Vector(*points[a]),
                App.Vector(*points[b]),
                App.Vector(*points[c]),
            )
        i += count + 1

    try:
        mesh.harmonizeNormals()
    except Exception:
        pass
    return mesh


def add_tpms_mesh_to_document(
    equation,
    part=PART_SHEET,
    cell_size=(1.0, 1.0, 1.0),
    repeat_cell=(1, 1, 1),
    resolution=32,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
    label="TPMS unit cell",
):
    if App.ActiveDocument is None:
        App.newDocument("TPMS")
    doc = App.ActiveDocument

    polydata = generate_polydata(equation, part, cell_size, repeat_cell, resolution, offset, phase)
    mesh = polydata_to_freecad_mesh(polydata)

    obj = doc.addObject("Mesh::Feature", "TPMS_Unit_Cell")
    obj.Mesh = mesh
    obj.Label = label
    obj.addProperty("App::PropertyString", "ImplicitEquation", "TPMS", "Implicit equation")
    obj.addProperty("App::PropertyString", "TPMSPart", "TPMS", "Generated TPMS part")
    obj.addProperty("App::PropertyInteger", "Resolution", "TPMS", "Cells per axis")
    obj.addProperty("App::PropertyInteger", "RepeatX", "TPMS", "Unit cells in X")
    obj.addProperty("App::PropertyInteger", "RepeatY", "TPMS", "Unit cells in Y")
    obj.addProperty("App::PropertyInteger", "RepeatZ", "TPMS", "Unit cells in Z")
    obj.addProperty("App::PropertyFloat", "Offset", "TPMS", "Sheet thickness or skeletal iso spacing")
    obj.ImplicitEquation = equation
    obj.TPMSPart = part
    obj.Resolution = int(resolution)
    obj.RepeatX = int(repeat_cell[0])
    obj.RepeatY = int(repeat_cell[1])
    obj.RepeatZ = int(repeat_cell[2])
    obj.Offset = float(offset)
    doc.recompute()
    return obj
