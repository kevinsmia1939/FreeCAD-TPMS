import math
import os
import warnings

import FreeCAD as App
import Mesh
import numpy as np
import pyvista as pv
import vtk


SURFACE_EQUATIONS = {
    "Gyroid": "sin(x) * cos(y) + sin(y) * cos(z) + sin(z) * cos(x)",
    "Schwarz P": "cos(x) + cos(y) + cos(z)",
    "Schwarz D": "sin(x) * sin(y) * sin(z) + sin(x) * cos(y) * cos(z) + cos(x) * sin(y) * cos(z) + cos(x) * cos(y) * sin(z)",
    "Neovius": "3 * cos(x) + 3 * cos(y) + 3 * cos(z) + 4 * cos(x) * cos(y) * cos(z)",
    "Schoen IWP": "2 * (cos(x) * cos(y) + cos(y) * cos(z) + cos(z) * cos(x)) - (cos(2*x) + cos(2*y) + cos(2*z))",
    "Schoen FRD": "4 * cos(x) * cos(y) * cos(z) - (cos(2*x) * cos(2*y) + cos(2*y) * cos(2*z) + cos(2*z) * cos(2*x))",
    "Lidinoid": "0.5 * (sin(2*x) * cos(y) * sin(z) + sin(2*y) * cos(z) * sin(x) + sin(2*z) * cos(x) * sin(y)) - 0.5 * (cos(2*x) * cos(2*y) + cos(2*y) * cos(2*z) + cos(2*z) * cos(2*x)) + 0.3",
}

SURFACE_EMPTY = "Empty"
SURFACE_SOLID_FILL = "Solid fill"

PART_SHEET = "Sheet"
PART_UPPER = "Upper skeletal"
PART_LOWER = "Lower skeletal"
PART_SURFACE = "Zero surface"

COORDINATE_CARTESIAN = "Cartesian"
COORDINATE_CYLINDRICAL_RING = "Cylindrical ring"

BOUNDARY_BOX = "Box"
BOUNDARY_SPHERE = "Sphere"
BOUNDARY_SELECTED_SOLID = "Selected solid"
BOUNDARY_EVALUATION_ANALYTICAL = "Analytical when available"
BOUNDARY_EVALUATION_TESSELLATED_SDF = "Tessellated SDF"
DENSITY_COUNT_PRESERVE = "Preserve overall count"
DENSITY_COUNT_FOLLOW = "Follow unit cell density"
GRADIENT_FACE_DISTANCE = "Selected-face distance field"
GRADIENT_FACE_PLANE = "Face plane"
GRADIENT_HARMONIC = "Harmonic field"
HARMONIC_BOUNDARY_CONDUCTOR = "Conductor"
HARMONIC_BOUNDARY_INSULATOR = "Insulator"
TRANSITION_BLEND_THRESHOLD = "Offset Surface Interpolation"
TRANSITION_BLEND_SIGMOID = "Sigmoid blend"
TRANSITION_BLEND_NORMALIZED_SUM = "Normalized weighted sum (ASLI)"
LABYRINTH_AUTO = "Auto"
LABYRINTH_POSITIVE = "Upper labyrinth"
LABYRINTH_NEGATIVE = "Lower labyrinth"
TRANSITION_TOPOLOGY_SAME_SIDE = "Same-side signed blend"
TRANSITION_TOPOLOGY_CROSS_BRIDGE = "Cross-labyrinth bridge"

_BOUNDARY_FIELD_CACHE = {}
_BOUNDARY_FIELD_CACHE_ORDER = []
_BOUNDARY_FIELD_CACHE_LIMIT = 8
_VTK_SMP_CONFIGURED = False


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
    return list(SURFACE_EQUATIONS) + [SURFACE_EMPTY, SURFACE_SOLID_FILL]


def evaluate_equation(equation, x, y, z):
    try:
        import numexpr
        return numexpr.evaluate(equation, local_dict={"x": x, "y": y, "z": z})
    except Exception:
        # Fall back to native numpy eval if numexpr is missing or fails
        namespace = dict(SAFE_NAMES)
        namespace.update({"x": x, "y": y, "z": z})
        return eval(equation, {"__builtins__": {}}, namespace)


def configure_vtk_smp():
    global _VTK_SMP_CONFIGURED
    if _VTK_SMP_CONFIGURED:
        return
    _VTK_SMP_CONFIGURED = True

    requested = os.environ.get("TPMS_VTK_SMP_BACKEND") or os.environ.get("VTK_SMP_BACKEND_IN_USE")
    candidates = [requested] if requested else ["STDThread"]

    for backend in candidates:
        if not backend:
            continue
        try:
            if vtk.vtkSMPTools.SetBackend(backend):
                max_threads = os.environ.get("TPMS_VTK_MAX_THREADS") or os.environ.get("VTK_SMP_MAX_THREADS")
                if max_threads:
                    vtk.vtkSMPTools.Initialize(max(1, int(max_threads)))
                return
        except Exception as exc:
            App.Console.PrintWarning("Unable to configure VTK SMP backend '{}': {}\n".format(backend, exc))


def boundary_modes():
    return [BOUNDARY_BOX, BOUNDARY_SELECTED_SOLID]


def boundary_evaluation_modes():
    return [BOUNDARY_EVALUATION_ANALYTICAL, BOUNDARY_EVALUATION_TESSELLATED_SDF]


def coordinate_modes():
    return [COORDINATE_CARTESIAN, COORDINATE_CYLINDRICAL_RING]


def labyrinth_modes():
    return [LABYRINTH_AUTO, LABYRINTH_POSITIVE, LABYRINTH_NEGATIVE]


def transition_topology_modes():
    return [TRANSITION_TOPOLOGY_SAME_SIDE, TRANSITION_TOPOLOGY_CROSS_BRIDGE]


def _make_axis(minimum, maximum, default_count):
    count = max(2, int(default_count))
    return np.linspace(float(minimum), float(maximum), count)


def _make_aligned_axis(minimum, maximum, spacing, anchor=0.0):
    spacing = max(float(spacing), 1e-12)
    anchor = float(anchor)
    lower = anchor + math.floor((float(minimum) - anchor) / spacing) * spacing
    upper = anchor + math.ceil((float(maximum) - anchor) / spacing) * spacing
    count = max(1, int(round((upper - lower) / spacing)))
    return lower + spacing * np.arange(count + 1, dtype=float)


def _rectilinear_axes(wx, wy, wz):
    if wx.ndim != 3 or wy.ndim != 3 or wz.ndim != 3:
        return None
    x_axis = np.asarray(wx[:, 0, 0], dtype=float)
    y_axis = np.asarray(wy[0, :, 0], dtype=float)
    z_axis = np.asarray(wz[0, 0, :], dtype=float)
    if (
        np.allclose(wx, x_axis[:, None, None])
        and np.allclose(wy, y_axis[None, :, None])
        and np.allclose(wz, z_axis[None, None, :])
    ):
        return x_axis, y_axis, z_axis
    return None


def _coarse_axes_for_harmonic(axes, target_resolution):
    resolution = int(target_resolution)
    if resolution <= 0:
        return None
    lengths = [max(abs(float(axis[-1] - axis[0])), 1e-9) for axis in axes]
    spacing = max(lengths) / max(float(resolution), 1.0)
    counts = [min(len(axes[i]), max(3, int(math.ceil(lengths[i] / spacing)) + 1)) for i in range(3)]
    if all(counts[i] >= len(axes[i]) for i in range(3)):
        return None
    return tuple(_make_axis(float(axes[i][0]), float(axes[i][-1]), counts[i]) for i in range(3))


def _interpolate_rectilinear_field(source_axes, source_values, target_axes):
    try:
        from scipy.interpolate import RegularGridInterpolator
    except Exception as exc:
        App.Console.PrintWarning("SciPy interpolation unavailable; using full-resolution harmonic field: {}\n".format(exc))
        return None

    interpolator = RegularGridInterpolator(source_axes, source_values, bounds_error=False, fill_value=None)
    tx, ty, tz = np.meshgrid(*target_axes, indexing="ij")
    points = np.column_stack((tx.ravel(order="C"), ty.ravel(order="C"), tz.ravel(order="C")))
    return interpolator(points).reshape(tx.shape, order="C")


def _shape_bounds(boundary_object):
    if boundary_object is None:
        raise ValueError("Selected boundary needs a linked solid or mesh object")
    if hasattr(boundary_object, "Shape"):
        shape = boundary_object.Shape
        if shape.isNull():
            raise ValueError("Selected solid boundary shape is empty")
        bb = shape.BoundBox
    elif hasattr(boundary_object, "Mesh"):
        mesh = boundary_object.Mesh
        if mesh.CountFacets == 0:
            raise ValueError("Selected mesh boundary is empty")
        bb = mesh.BoundBox
    else:
        raise ValueError("Selected boundary needs a linked solid or mesh object")
    return (
        (float(bb.XMin), float(bb.XMax)),
        (float(bb.YMin), float(bb.YMax)),
        (float(bb.ZMin), float(bb.ZMax)),
    )


def _make_grid(
    cell_size,
    repeat_cell,
    resolution,
    phase,
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    origin=None,
    origin_rotation=None,
    density_mode="Uniform",
    base_density=1.0,
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    density_offset_mode="Uniform",
    density_offset_value=0.3,
    density_offset_controls=None,
    density_offset_gradient=GRADIENT_FACE_DISTANCE,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    cell_size = np.asarray(cell_size, dtype=float)
    repeat_cell = np.asarray(repeat_cell, dtype=int)
    repeat_cell = np.maximum(repeat_cell, 1)
    phase = np.asarray(phase, dtype=float)

    if origin is None:
        origin = _default_origin(boundary_mode, boundary_object)
    phase_origin = np.asarray(origin, dtype=float)
    aligned_spacing = None

    if boundary_mode == BOUNDARY_SELECTED_SOLID:
        bounds = _shape_bounds(boundary_object)
        fallback_spacing = min(float(value) / max(int(resolution), 1) for value in cell_size)
        spacing = max(fallback_spacing, 1e-9)
        aligned_spacing = spacing
        if _needs_curved_analytic_padding(boundary_object):
            bounds = [(axis_min - spacing, axis_max + spacing) for axis_min, axis_max in bounds]
        default_counts = [
            int(math.ceil(max(bounds[i][1] - bounds[i][0], 1e-9) / spacing)) + 1
            for i in range(3)
        ]
    else:
        domain_size = cell_size * repeat_cell
        bounds = [(phase_origin[i], phase_origin[i] + domain_size[i]) for i in range(3)]
        default_counts = [int(resolution) * int(repeat_cell[i]) + 1 for i in range(3)]

    if sampling and sampling > 0.0:
        lengths = [max(bounds[i][1] - bounds[i][0], 1e-9) for i in range(3)]
        spacing = max(lengths) / max(float(sampling), 1.0)
        aligned_spacing = max(spacing, 1e-9)
        default_counts = [int(math.ceil(length / spacing)) + 1 for length in lengths]

    if aligned_spacing is not None:
        coords = [
            _make_aligned_axis(bounds[i][0], bounds[i][1], aligned_spacing, phase_origin[i])
            for i in range(3)
        ]
        default_counts = [len(axis) for axis in coords]
    else:
        coords = [_make_axis(bounds[i][0], bounds[i][1], default_counts[i]) for i in range(3)]
    wx, wy, wz = np.meshgrid(*coords, indexing="ij")
    spacing = tuple(
        float(coords[i][1] - coords[i][0]) if len(coords[i]) > 1 else 1.0
        for i in range(3)
    )
    grid_origin = tuple(float(coords[i][0]) for i in range(3))
    grid = pv.ImageData(dimensions=tuple(default_counts), spacing=spacing, origin=grid_origin)

    rotation_matrix = _rotation_matrix(origin_rotation, boundary_object)
    if rotation_matrix is not None:
        tx, ty, tz = _world_to_origin_frame_arrays(rotation_matrix, wx, wy, wz, phase_origin)
    else:
        tx = wx - phase_origin[0]
        ty = wy - phase_origin[1]
        tz = wz - phase_origin[2]

    px, py, pz = _density_phase_coordinates(
        tx,
        ty,
        tz,
        wx,
        wy,
        wz,
        phase,
        density_mode,
        base_density,
        density_controls,
        density_count_mode,
        density_gradient,
        boundary_mode,
        boundary_object,
        sampling,
        grading_resolution,
        harmonic_boundary_condition,
    )
    offset_field = _offset_field(
        wx,
        wy,
        wz,
        float(density_offset_value),
        density_offset_mode,
        density_offset_controls,
        density_offset_gradient,
        boundary_mode,
        boundary_object,
        sampling,
        grading_resolution,
        harmonic_boundary_condition,
    )
    kx, ky, kz = [2.0 * math.pi / max(cell_size[i], 1e-9) for i in range(3)]
    sx = kx * px
    sy = ky * py
    sz = kz * pz
    return grid, sx, sy, sz, offset_field, wx, wy, wz


def _cylindrical_phase_grid(
    wx,
    wy,
    wz,
    cell_size,
    phase,
    origin=None,
    origin_rotation=None,
    boundary_object=None,
    ring_angular_cells=8,
    density_mode="Uniform",
    base_density=1.0,
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    boundary_mode=BOUNDARY_BOX,
    sampling=0.0,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    cell_size = np.asarray(cell_size, dtype=float)
    phase = np.asarray(phase, dtype=float)
    if origin is None:
        origin = _default_origin(boundary_mode, boundary_object)
    origin = np.asarray(origin, dtype=float)

    rotation_matrix = _rotation_matrix(origin_rotation, boundary_object)
    if rotation_matrix is not None:
        lx, ly, lz = _world_to_origin_frame_arrays(rotation_matrix, wx, wy, wz, origin)
    else:
        lx = wx - origin[0]
        ly = wy - origin[1]
        lz = wz - origin[2]

    angular_cells = max(1, int(ring_angular_cells))
    period = max(float(cell_size[0]) * float(angular_cells), 1e-9)
    theta = np.mod(np.arctan2(ly, lx), 2.0 * math.pi)
    angular = theta * period / (2.0 * math.pi)
    radial = np.sqrt(lx * lx + ly * ly)

    px, py, pz = _density_phase_coordinates(
        angular,
        radial,
        lz,
        wx,
        wy,
        wz,
        phase,
        density_mode,
        base_density,
        density_controls,
        density_count_mode,
        density_gradient,
        boundary_mode,
        boundary_object,
        sampling,
        grading_resolution,
        harmonic_boundary_condition,
    )
    kx, ky, kz = [2.0 * math.pi / max(cell_size[i], 1e-9) for i in range(3)]
    return kx * px, ky * py, kz * pz


def _default_origin(boundary_mode, boundary_object):
    if boundary_mode == BOUNDARY_SELECTED_SOLID and boundary_object is not None:
        placement = getattr(boundary_object, "Placement", None)
        if placement is not None:
            base = placement.Base
            return (float(base.x), float(base.y), float(base.z))
        try:
            bounds = _shape_bounds(boundary_object)
            return tuple(float(bounds[i][0]) for i in range(3))
        except Exception:
            pass
    return (0.0, 0.0, 0.0)


def _needs_curved_analytic_padding(boundary_object):
    type_id = getattr(boundary_object, "TypeId", "")
    if type_id == "Part::Sphere" and hasattr(boundary_object, "Radius"):
        return True
    if _is_part_cylinder(boundary_object):
        return True
    if _is_part_box(boundary_object):
        return False
    shape = getattr(boundary_object, "Shape", None)
    if shape is None or shape.isNull():
        return False
    return _cylindrical_shell_from_shape(shape) is not None or _spherical_shell_from_shape(shape) is not None


def _density_multiplier(wx, wy, wz, density_mode="Uniform", base_density=1.0, density_controls=None):
    base = max(0.05, float(base_density))
    density = np.full(wx.shape, base, dtype=float)
    if str(density_mode) != "Non-uniform" or not density_controls:
        return density

    for control in density_controls:
        try:
            if control.get("type") == "face_distance":
                density = _apply_face_distance_density_multiplier(density, wx, wy, wz, control, base)
                continue
            point = np.asarray(control["point"], dtype=float)
            normal = np.asarray(control["normal"], dtype=float)
            target = max(0.05, float(control["density"]))
            transition = max(1e-9, float(control["transition"]))
        except Exception:
            continue
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-12:
            continue
        normal = normal / norm
        distance = np.abs(
            (wx - point[0]) * normal[0]
            + (wy - point[1]) * normal[1]
            + (wz - point[2]) * normal[2]
        )
        t = np.clip(distance / transition, 0.0, 1.0)
        smooth = t * t * (3.0 - 2.0 * t)
        weight = 1.0 - smooth
        density += weight * (target - base)
    return np.maximum(density, 0.05)


def _normalize_density_to_base(density, base_density):
    density = np.asarray(density, dtype=float)
    finite = np.isfinite(density)
    if not np.any(finite):
        return density
    mean_density = float(np.mean(density[finite]))
    if mean_density <= 1e-12:
        return density
    return np.maximum(density * (float(base_density) / mean_density), 0.05)


def _offset_field(
    wx,
    wy,
    wz,
    base_offset,
    density_offset_mode,
    density_offset_controls,
    density_offset_gradient,
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    offset = np.full(wx.shape, float(base_offset), dtype=float)
    if str(density_offset_mode) != "Non-uniform" or not density_offset_controls:
        return offset

    gradient = str(density_offset_gradient)
    if gradient == GRADIENT_HARMONIC:
        return _harmonic_interpolated_field(
            wx,
            wy,
            wz,
            boundary_mode,
            boundary_object,
            sampling,
            density_offset_controls,
            float(base_offset),
            "offset",
            minimum=None,
            grading_resolution=grading_resolution,
            harmonic_boundary_condition=harmonic_boundary_condition,
        )

    for control in density_offset_controls:
        try:
            if control.get("type", "face_plane") == "face_distance":
                offset = _apply_face_distance_offset_field(offset, wx, wy, wz, control, base_offset)
                continue
            point = np.asarray(control["point"], dtype=float)
            normal = np.asarray(control["normal"], dtype=float)
            target = float(control.get("offset", base_offset))
            transition = max(1e-9, float(control.get("transition", 1.0)))
        except Exception:
            continue
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-12:
            continue
        normal = normal / norm
        distance = np.abs(
            (wx - point[0]) * normal[0]
            + (wy - point[1]) * normal[1]
            + (wz - point[2]) * normal[2]
        )
        t = np.clip(distance / transition, 0.0, 1.0)
        smooth = t * t * (3.0 - 2.0 * t)
        weight = 1.0 - smooth
        offset += weight * (target - base_offset)
    return offset


def _apply_face_distance_offset_field(offset, wx, wy, wz, control, base_offset):
    distance = np.abs(_face_distance_field(wx, wy, wz, control))
    target = float(control.get("offset", base_offset))
    transition = max(1e-9, float(control.get("transition", 1.0)))
    weight = _smooth_falloff_weight(distance, transition)
    return offset + weight * (target - base_offset)


def _apply_offset_controls_to_field(
    offset,
    wx,
    wy,
    wz,
    density_offset_mode,
    density_offset_controls,
    density_offset_gradient,
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    offset = np.asarray(offset, dtype=float)
    if str(density_offset_mode) != "Non-uniform" or not density_offset_controls:
        return offset

    gradient = str(density_offset_gradient)
    if gradient == GRADIENT_HARMONIC:
        finite = np.isfinite(offset)
        base_value = float(np.mean(offset[finite])) if np.any(finite) else 0.0
        return _harmonic_interpolated_field(
            wx,
            wy,
            wz,
            boundary_mode,
            boundary_object,
            sampling,
            density_offset_controls,
            base_value,
            "offset",
            minimum=None,
            grading_resolution=grading_resolution,
            harmonic_boundary_condition=harmonic_boundary_condition,
        )

    result = np.array(offset, dtype=float, copy=True)
    for control in density_offset_controls:
        try:
            target = float(control.get("offset", 0.0))
            if control.get("type", "face_plane") == "face_distance":
                distance = np.abs(_face_distance_field(wx, wy, wz, control))
            else:
                point = np.asarray(control["point"], dtype=float)
                normal = np.asarray(control["normal"], dtype=float)
                norm = float(np.linalg.norm(normal))
                if norm <= 1e-12:
                    continue
                normal = normal / norm
                distance = np.abs(
                    (wx - point[0]) * normal[0]
                    + (wy - point[1]) * normal[1]
                    + (wz - point[2]) * normal[2]
                )
            transition = max(1e-9, float(control.get("transition", 1.0)))
            weight = _smooth_falloff_weight(distance, transition)
            result = result + weight * (target - result)
        except Exception as exc:
            App.Console.PrintWarning("Ignoring TPMS hybrid thickness grading control: {}\n".format(exc))
    return result


def _density_phase_coordinates(
    tx,
    ty,
    tz,
    wx,
    wy,
    wz,
    phase,
    density_mode="Uniform",
    base_density=1.0,
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    base = max(0.05, float(base_density))
    px = base * (tx + phase[0])
    py = base * (ty + phase[1])
    pz = base * (tz + phase[2])

    if str(density_mode) != "Non-uniform" or not density_controls:
        return px, py, pz

    if str(density_gradient) == GRADIENT_HARMONIC:
        density = _harmonic_interpolated_field(
            wx,
            wy,
            wz,
            boundary_mode,
            boundary_object,
            sampling,
            density_controls,
            base,
            "density",
            minimum=0.05,
            grading_resolution=grading_resolution,
            harmonic_boundary_condition=harmonic_boundary_condition,
        )
        if str(density_count_mode) == DENSITY_COUNT_PRESERVE:
            density = _normalize_density_to_base(density, base)
        return (tx + phase[0]) * density, (ty + phase[1]) * density, (tz + phase[2]) * density

    if str(density_count_mode) == DENSITY_COUNT_PRESERVE:
        density = _density_multiplier(wx, wy, wz, density_mode, base_density, density_controls)
        return (tx + phase[0]) * density, (ty + phase[1]) * density, (tz + phase[2]) * density

    for control in density_controls:
        try:
            if control.get("type") == "face_distance":
                px, py, pz = _apply_face_distance_phase_coordinates(px, py, pz, wx, wy, wz, control, base)
                continue
            point = np.asarray(control["point"], dtype=float)
            normal = np.asarray(control["normal"], dtype=float)
            target = max(0.05, float(control["density"]))
            transition = max(1e-9, float(control["transition"]))
        except Exception:
            continue
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-12:
            continue
        normal = normal / norm
        signed_distance = (
            (wx - point[0]) * normal[0]
            + (wy - point[1]) * normal[1]
            + (wz - point[2]) * normal[2]
        )
        u = np.clip(np.abs(signed_distance) / transition, 0.0, 1.0)
        integral = u - u**3 + 0.5 * u**4
        correction = np.sign(signed_distance) * (target - base) * transition * integral
        px += correction * normal[0]
        py += correction * normal[1]
        pz += correction * normal[2]
    return px, py, pz


def _apply_face_distance_density_multiplier(density, wx, wy, wz, control, base):
    distance = np.abs(_face_distance_field(wx, wy, wz, control))
    target = max(0.05, float(control.get("density", base)))
    transition = max(1e-9, float(control.get("transition", 1.0)))
    weight = _smooth_falloff_weight(distance, transition)
    return density + weight * (target - base)


def _apply_face_distance_phase_coordinates(px, py, pz, wx, wy, wz, control, base):
    signed_distance = _face_distance_field(wx, wy, wz, control)
    distance = np.abs(signed_distance)
    target = max(0.05, float(control.get("density", base)))
    transition = max(1e-9, float(control.get("transition", 1.0)))
    u = np.clip(distance / transition, 0.0, 1.0)
    integral = u - u**3 + 0.5 * u**4
    correction = np.sign(signed_distance) * (target - base) * transition * integral
    gx, gy, gz = np.gradient(signed_distance)
    length = np.sqrt(gx * gx + gy * gy + gz * gz)
    length = np.maximum(length, 1e-12)
    px = px + correction * gx / length
    py = py + correction * gy / length
    pz = pz + correction * gz / length
    return px, py, pz


def _face_distance_field(wx, wy, wz, control):
    surface = _control_surface_polydata(control)
    points = np.column_stack((wx.ravel(order="C"), wy.ravel(order="C"), wz.ravel(order="C")))
    return _implicit_distances(surface, points).reshape(wx.shape, order="C")


def _control_surface_polydata(control):
    surface = control.get("surface") or {}
    points = np.asarray(surface.get("points", []), dtype=float)
    triangles = surface.get("triangles", [])
    if len(points) == 0 or len(triangles) == 0:
        raise ValueError("selected face grading control has no tessellated surface")
    face_array = np.empty(len(triangles) * 4, dtype=np.int64)
    face_array[0::4] = 3
    for index, triangle in enumerate(triangles):
        base = index * 4
        face_array[base + 1 : base + 4] = triangle
    return pv.PolyData(points, face_array).triangulate().clean()


def _smooth_falloff_weight(distance, transition):
    t = np.clip(distance / max(float(transition), 1e-12), 0.0, 1.0)
    smooth = t * t * (3.0 - 2.0 * t)
    return 1.0 - smooth


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _sigmoidstep(t, sharpness=10.0):
    t = np.clip(t, 0.0, 1.0)
    low = 1.0 / (1.0 + math.exp(0.5 * sharpness))
    high = 1.0 / (1.0 + math.exp(-0.5 * sharpness))
    value = 1.0 / (1.0 + np.exp(-sharpness * (t - 0.5)))
    return np.clip((value - low) / (high - low), 0.0, 1.0)


def _labyrinth_sign(labyrinth, part_name):
    mode = str(labyrinth or LABYRINTH_AUTO)
    part_name = str(part_name)
    if mode == LABYRINTH_POSITIVE:
        return 1.0
    if mode == LABYRINTH_NEGATIVE:
        return -1.0
    if part_name == PART_UPPER:
        return 1.0
    if part_name == PART_LOWER:
        return -1.0
    return None


def _is_skeletal_part(part_name):
    return str(part_name) in (PART_UPPER, PART_LOWER)


def _blend_equation_field(base_field, x, y, z, wx, wy, wz, equation_blend_controls=None):
    field = np.asarray(base_field, dtype=float)
    for control in equation_blend_controls or []:
        equation = str(control.get("equation", "")).strip()
        if not equation:
            continue
        try:
            target = np.asarray(evaluate_equation(equation, x, y, z), dtype=float)
            if target.shape == ():
                target = np.full(field.shape, float(target), dtype=float)
            if target.shape != field.shape:
                continue
            if control.get("type") == "face_distance":
                distance = np.abs(_face_distance_field(wx, wy, wz, control))
            else:
                point = np.asarray(control["point"], dtype=float)
                normal = np.asarray(control["normal"], dtype=float)
                normal_length = float(np.linalg.norm(normal))
                if normal_length <= 1e-12:
                    continue
                normal = normal / normal_length
                distance = np.abs(
                    (wx - point[0]) * normal[0]
                    + (wy - point[1]) * normal[1]
                    + (wz - point[2]) * normal[2]
                )
            weight = _smooth_falloff_weight(distance, max(1e-9, float(control.get("transition", 1.0))))
            field = field + weight * (target - field)
        except Exception as exc:
            App.Console.PrintWarning("Ignoring TPMS equation blend control: {}\n".format(exc))
    return field


def _harmonic_interpolated_field(
    wx,
    wy,
    wz,
    boundary_mode,
    boundary_object,
    sampling,
    controls,
    base_value,
    value_key,
    minimum=0.0,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    axes = _rectilinear_axes(wx, wy, wz)
    coarse_axes = _coarse_axes_for_harmonic(axes, grading_resolution) if axes is not None else None
    if coarse_axes is not None:
        cwx, cwy, cwz = np.meshgrid(*coarse_axes, indexing="ij")
        coarse = _harmonic_interpolated_field(
            cwx,
            cwy,
            cwz,
            boundary_mode,
            boundary_object,
            sampling,
            controls,
            base_value,
            value_key,
            minimum=minimum,
            grading_resolution=0,
            harmonic_boundary_condition=harmonic_boundary_condition,
        )
        interpolated = _interpolate_rectilinear_field(coarse_axes, coarse, axes)
        if interpolated is not None:
            return interpolated

    lower_bound = None if minimum is None else float(minimum)
    inside = _domain_inside_mask(boundary_mode, boundary_object, wx, wy, wz, sampling)
    if not np.any(inside):
        value = float(base_value) if lower_bound is None else max(lower_bound, float(base_value))
        return np.full(wx.shape, value, dtype=float)

    if str(harmonic_boundary_condition) == HARMONIC_BOUNDARY_INSULATOR:
        fixed = np.zeros(wx.shape, dtype=bool)
    else:
        fixed = _domain_boundary_mask(inside)
    values = np.full(wx.shape, float(base_value), dtype=float)

    selected_fixed = np.zeros(wx.shape, dtype=bool)
    selected_values = np.zeros(wx.shape, dtype=float)
    selected_counts = np.zeros(wx.shape, dtype=float)
    band = 1.5 * max(
        _axis_spacing(wx, axis=0),
        _axis_spacing(wy, axis=1),
        _axis_spacing(wz, axis=2),
    )

    for control in controls or []:
        try:
            target = float(control.get(value_key, base_value))
            if control.get("surface"):
                distance = np.abs(_face_distance_field(wx, wy, wz, control))
            else:
                point = np.asarray(control["point"], dtype=float)
                normal = np.asarray(control["normal"], dtype=float)
                normal_length = float(np.linalg.norm(normal))
                if normal_length <= 1e-12:
                    continue
                normal = normal / normal_length
                distance = np.abs(
                    (wx - point[0]) * normal[0]
                    + (wy - point[1]) * normal[1]
                    + (wz - point[2]) * normal[2]
                )
        except Exception:
            continue
        mask = inside & (distance <= band)
        if not np.any(mask):
            closest = inside & (distance <= max(float(np.min(distance[inside])) + 1e-12, band))
            mask = closest
        selected_fixed |= mask
        selected_values[mask] += target
        selected_counts[mask] += 1.0

    if np.any(selected_fixed):
        values[selected_fixed] = selected_values[selected_fixed] / np.maximum(selected_counts[selected_fixed], 1.0)
        fixed |= selected_fixed

    unknown = inside & ~fixed
    if not np.any(unknown):
        return values if lower_bound is None else np.maximum(values, lower_bound)

    solved = _solve_harmonic_grid(inside, fixed, values)
    return solved if lower_bound is None else np.maximum(solved, lower_bound)


def _domain_inside_mask(boundary_mode, boundary_object, wx, wy, wz, sampling):
    if boundary_mode == BOUNDARY_BOX:
        return np.ones(wx.shape, dtype=bool)
    if boundary_mode == BOUNDARY_SPHERE:
        center = np.array(
            [
                0.5 * (float(np.min(wx)) + float(np.max(wx))),
                0.5 * (float(np.min(wy)) + float(np.max(wy))),
                0.5 * (float(np.min(wz)) + float(np.max(wz))),
            ]
        )
        radius = 0.5 * min(
            float(np.max(wx)) - float(np.min(wx)),
            float(np.max(wy)) - float(np.min(wy)),
            float(np.max(wz)) - float(np.min(wz)),
        )
        return ((wx - center[0]) ** 2 + (wy - center[1]) ** 2 + (wz - center[2]) ** 2) <= radius * radius
    if boundary_mode == BOUNDARY_SELECTED_SOLID and boundary_object is not None:
        field = _analytic_boundary_field(boundary_object, wx, wy, wz)
        if field is not None:
            return field >= 0.0
        fallback_resolution = max(wx.shape)
        try:
            field = _selected_boundary_field_signed_vtk(boundary_object, wx, wy, wz, sampling, fallback_resolution)
            return field >= 0.0
        except Exception:
            if hasattr(boundary_object, "Shape"):
                return _selected_solid_field(boundary_object.Shape, wx, wy, wz, 1e-7) >= 0.0
    return np.ones(wx.shape, dtype=bool)


def _domain_boundary_mask(inside):
    boundary = np.zeros(inside.shape, dtype=bool)
    boundary[0, :, :] |= inside[0, :, :]
    boundary[-1, :, :] |= inside[-1, :, :]
    boundary[:, 0, :] |= inside[:, 0, :]
    boundary[:, -1, :] |= inside[:, -1, :]
    boundary[:, :, 0] |= inside[:, :, 0]
    boundary[:, :, -1] |= inside[:, :, -1]

    for axis in range(3):
        lower = [slice(None)] * 3
        upper = [slice(None)] * 3
        lower[axis] = slice(0, -1)
        upper[axis] = slice(1, None)
        neighbor_outside = inside[tuple(lower)] != inside[tuple(upper)]
        boundary[tuple(lower)] |= inside[tuple(lower)] & neighbor_outside
        boundary[tuple(upper)] |= inside[tuple(upper)] & neighbor_outside
    return boundary


def _solve_harmonic_grid(inside, fixed, fixed_values):
    try:
        from scipy import sparse
        from scipy.sparse import linalg as spla
    except Exception as exc:
        App.Console.PrintWarning("SciPy sparse solver unavailable; harmonic field falls back to fixed values: {}\n".format(exc))
        return fixed_values.copy()

    unknown = inside & ~fixed
    indices = -np.ones(inside.shape, dtype=np.int64)
    indices[unknown] = np.arange(int(np.count_nonzero(unknown)), dtype=np.int64)
    n_unknown = int(np.count_nonzero(unknown))
    rows = []
    cols = []
    data = []
    rhs = np.zeros(n_unknown, dtype=float)

    neighbor_offsets = ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1))
    for i, j, k in np.argwhere(unknown):
        row = int(indices[i, j, k])
        diagonal = 0.0
        for di, dj, dk in neighbor_offsets:
            ni, nj, nk = int(i + di), int(j + dj), int(k + dk)
            if ni < 0 or nj < 0 or nk < 0 or ni >= inside.shape[0] or nj >= inside.shape[1] or nk >= inside.shape[2]:
                continue
            if not inside[ni, nj, nk]:
                continue
            diagonal += 1.0
            if fixed[ni, nj, nk]:
                rhs[row] += float(fixed_values[ni, nj, nk])
            else:
                col = int(indices[ni, nj, nk])
                if col >= 0:
                    rows.append(row)
                    cols.append(col)
                    data.append(-1.0)
        rows.append(row)
        cols.append(row)
        data.append(max(diagonal, 1.0))

    matrix = sparse.csr_matrix((data, (rows, cols)), shape=(n_unknown, n_unknown))
    try:
        import pyamg

        ml = pyamg.smoothed_aggregation_solver(matrix)
        solution = ml.solve(rhs, tol=1e-8, maxiter=100, accel="cg")
        result = fixed_values.copy()
        result[unknown] = solution
        return result
    except Exception as exc:
        App.Console.PrintWarning("PyAMG harmonic solve unavailable; falling back to SciPy direct solve: {}\n".format(exc))

    try:
        solution = spla.spsolve(matrix, rhs)
    except Exception as exc:
        App.Console.PrintWarning("Direct harmonic solve failed; trying conjugate gradient: {}\n".format(exc))
        solution, info = spla.cg(matrix, rhs, rtol=1e-8, atol=1e-10, maxiter=max(1000, n_unknown * 2))
        if info != 0:
            App.Console.PrintWarning("Conjugate-gradient harmonic solve did not fully converge (info={}).\n".format(info))

    result = fixed_values.copy()
    result[unknown] = solution
    return result


def _selected_solid_field(shape, wx, wy, wz, tolerance):
    values = np.empty(wx.shape, dtype=float)
    flat_x = wx.ravel(order="C")
    flat_y = wy.ravel(order="C")
    flat_z = wz.ravel(order="C")
    flat_values = values.ravel(order="C")
    inside_value = max(float(tolerance), 1e-6)
    for i, (x, y, z) in enumerate(zip(flat_x, flat_y, flat_z)):
        point = App.Vector(float(x), float(y), float(z))
        flat_values[i] = inside_value if shape.isInside(point, tolerance, True) else -inside_value
    return values


def _shape_to_polydata(shape, deflection):
    points, triangles = shape.tessellate(float(deflection))
    if not points or not triangles:
        raise ValueError("Selected solid boundary could not be tessellated")

    point_array = np.array([[point.x, point.y, point.z] for point in points], dtype=float)
    face_array = np.empty(len(triangles) * 4, dtype=np.int64)
    face_array[0::4] = 3
    for index, triangle in enumerate(triangles):
        base = index * 4
        face_array[base + 1 : base + 4] = triangle
    return pv.PolyData(point_array, face_array).triangulate().clean()


def _mesh_to_polydata(mesh):
    points, triangles = mesh.Topology
    if not points or not triangles:
        raise ValueError("Selected mesh boundary is empty")

    point_array = np.array([[point.x, point.y, point.z] for point in points], dtype=float)
    face_array = np.empty(len(triangles) * 4, dtype=np.int64)
    face_array[0::4] = 3
    for index, triangle in enumerate(triangles):
        base = index * 4
        face_array[base + 1 : base + 4] = triangle
    return pv.PolyData(point_array, face_array).triangulate().clean()


def _boundary_to_polydata(boundary_object, wx, wy, wz, sampling, fallback_resolution):
    if hasattr(boundary_object, "Mesh"):
        return _mesh_to_polydata(boundary_object.Mesh)
    if hasattr(boundary_object, "Shape"):
        lengths = (
            float(np.max(wx)) - float(np.min(wx)),
            float(np.max(wy)) - float(np.min(wy)),
            float(np.max(wz)) - float(np.min(wz)),
        )
        max_length = max(max(lengths), 1e-9)
        resolution = float(sampling) if sampling and sampling > 0.0 else float(fallback_resolution)
        deflection = max_length / max(resolution * 2.0, 8.0)
        return _shape_to_polydata(boundary_object.Shape, deflection)
    raise ValueError("Selected boundary needs a linked solid or mesh object")


def _selected_boundary_field_binary_vtk(boundary_object, wx, wy, wz, sampling, fallback_resolution):
    solids = getattr(boundary_object, "BoundaryRegionSolids", None)
    if solids:
        inside = np.zeros(wx.shape, dtype=bool)
        for solid in solids:
            solid_adapter = _BoundaryShapeAdapter(solid)
            inside |= _selected_boundary_field_binary_vtk(
                solid_adapter,
                wx,
                wy,
                wz,
                sampling,
                fallback_resolution,
            ) > 0.0
        return np.where(inside, 1.0, -1.0)

    surface = _boundary_to_polydata(boundary_object, wx, wy, wz, sampling, fallback_resolution)
    points = np.column_stack((wx.ravel(order="C"), wy.ravel(order="C"), wz.ravel(order="C")))
    inside = _classify_points(surface, points)
    return np.where(inside.reshape(wx.shape, order="C"), 1.0, -1.0)


def _classify_points(surface, points):
    cloud = pv.PolyData(points)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        selected = cloud.select_enclosed_points(surface, tolerance=0.0, check_surface=False)
    return np.asarray(selected["SelectedPoints"], dtype=bool)


def _implicit_distances(surface, points):
    cloud = pv.PolyData(points)
    sampled = cloud.compute_implicit_distance(surface, inplace=False)
    return np.asarray(sampled["implicit_distance"], dtype=float)


def _selected_boundary_distance_vtk(boundary_object, wx, wy, wz, sampling, fallback_resolution):
    analytical = _analytic_boundary_field(boundary_object, wx, wy, wz, sampling, fallback_resolution)
    if analytical is not None:
        return np.abs(analytical)

    solids = getattr(boundary_object, "BoundaryRegionSolids", None)
    if solids:
        field = None
        for solid in solids:
            solid_adapter = _BoundaryShapeAdapter(solid)
            solid_field = _selected_boundary_distance_vtk(
                solid_adapter,
                wx,
                wy,
                wz,
                sampling,
                fallback_resolution,
            )
            field = solid_field if field is None else np.minimum(field, solid_field)
        if field is not None:
            return field

    cache_key = _boundary_field_cache_key(boundary_object, wx, wy, wz, sampling, fallback_resolution, "distance")
    if cache_key is not None and cache_key in _BOUNDARY_FIELD_CACHE:
        return _BOUNDARY_FIELD_CACHE[cache_key].copy()

    surface = _boundary_to_polydata(boundary_object, wx, wy, wz, sampling, fallback_resolution)
    points = np.column_stack((wx.ravel(order="C"), wy.ravel(order="C"), wz.ravel(order="C")))
    distance = np.abs(_implicit_distances(surface, points)).reshape(wx.shape, order="C")
    _store_boundary_field_cache(cache_key, distance)
    return distance


def _selected_boundary_field_signed_vtk(boundary_object, wx, wy, wz, sampling, fallback_resolution):
    analytical = _analytic_boundary_field(boundary_object, wx, wy, wz, sampling, fallback_resolution)
    if analytical is not None:
        return analytical

    solids = getattr(boundary_object, "BoundaryRegionSolids", None)
    if solids:
        field = None
        for solid in solids:
            solid_adapter = _BoundaryShapeAdapter(solid)
            solid_field = _selected_boundary_field_signed_vtk(
                solid_adapter,
                wx,
                wy,
                wz,
                sampling,
                fallback_resolution,
            )
            field = solid_field if field is None else np.maximum(field, solid_field)
        if field is not None:
            return field

    cache_key = _boundary_field_cache_key(boundary_object, wx, wy, wz, sampling, fallback_resolution, "signed")
    if cache_key is not None and cache_key in _BOUNDARY_FIELD_CACHE:
        return _BOUNDARY_FIELD_CACHE[cache_key].copy()

    surface = _boundary_to_polydata(boundary_object, wx, wy, wz, sampling, fallback_resolution)
    points = np.column_stack((wx.ravel(order="C"), wy.ravel(order="C"), wz.ravel(order="C")))
    inside = _classify_points(surface, points).reshape(wx.shape, order="C")
    distance = np.abs(_implicit_distances(surface, points)).reshape(wx.shape, order="C")
    field = np.where(inside, distance, -distance).astype(float)
    _store_boundary_field_cache(cache_key, field)
    return field


class _BoundaryShapeAdapter:
    TypeId = "TPMS::BoundaryRegionSolid"

    def __init__(self, shape):
        self.Shape = shape
        self.Placement = App.Placement()
        self.ForceTessellatedBoundary = True


def _boundary_field_cache_key(boundary_object, wx, wy, wz, sampling, fallback_resolution, mode):
    if boundary_object is None or not hasattr(boundary_object, "Shape"):
        return None
    shape = boundary_object.Shape
    try:
        shape_hash = int(shape.hashCode())
    except Exception:
        return None
    bb = shape.BoundBox
    return (
        mode,
        shape_hash,
        round(float(bb.XMin), 9),
        round(float(bb.XMax), 9),
        round(float(bb.YMin), 9),
        round(float(bb.YMax), 9),
        round(float(bb.ZMin), 9),
        round(float(bb.ZMax), 9),
        tuple(int(value) for value in wx.shape),
        round(float(np.min(wx)), 9),
        round(float(np.max(wx)), 9),
        round(float(np.min(wy)), 9),
        round(float(np.max(wy)), 9),
        round(float(np.min(wz)), 9),
        round(float(np.max(wz)), 9),
        round(float(sampling), 9),
        int(fallback_resolution),
    )


def _store_boundary_field_cache(cache_key, field):
    if cache_key is None:
        return
    if cache_key in _BOUNDARY_FIELD_CACHE:
        _BOUNDARY_FIELD_CACHE[cache_key] = field.copy()
        return
    _BOUNDARY_FIELD_CACHE[cache_key] = field.copy()
    _BOUNDARY_FIELD_CACHE_ORDER.append(cache_key)
    while len(_BOUNDARY_FIELD_CACHE_ORDER) > _BOUNDARY_FIELD_CACHE_LIMIT:
        oldest = _BOUNDARY_FIELD_CACHE_ORDER.pop(0)
        _BOUNDARY_FIELD_CACHE.pop(oldest, None)


def _axis_spacing(values, axis):
    if values.shape[axis] < 2:
        return 1.0
    lower = [0, 0, 0]
    upper = [0, 0, 0]
    upper[axis] = 1
    return max(abs(float(values[tuple(upper)] - values[tuple(lower)])), 1e-9)


def _add_boundary_field(grid, wx, wy, wz, boundary_mode, boundary_object=None, sampling=0.0):
    field = _boundary_field(boundary_mode, boundary_object, wx, wy, wz, sampling)
    if field is None:
        return False
    grid["boundary"] = field.ravel(order="F")
    return True


def _boundary_field(boundary_mode, boundary_object, wx, wy, wz, sampling=0.0):
    if boundary_mode == BOUNDARY_BOX:
        return None
    if boundary_mode == BOUNDARY_SPHERE:
        center = np.array(
            [
                0.5 * (float(np.min(wx)) + float(np.max(wx))),
                0.5 * (float(np.min(wy)) + float(np.max(wy))),
                0.5 * (float(np.min(wz)) + float(np.max(wz))),
            ]
        )
        radius = 0.5 * min(
            float(np.max(wx)) - float(np.min(wx)),
            float(np.max(wy)) - float(np.min(wy)),
            float(np.max(wz)) - float(np.min(wz)),
        )
        field = radius * radius - ((wx - center[0]) ** 2 + (wy - center[1]) ** 2 + (wz - center[2]) ** 2)
    elif boundary_mode == BOUNDARY_SELECTED_SOLID:
        if boundary_object is None:
            raise ValueError("Selected boundary needs a linked solid or mesh object")
        fallback_resolution = max(wx.shape)
        field = _analytic_boundary_field(boundary_object, wx, wy, wz, sampling, fallback_resolution)
        if field is not None:
            return field
        try:
            field = _selected_boundary_field_signed_vtk(boundary_object, wx, wy, wz, sampling, fallback_resolution)
        except Exception as exc:
            App.Console.PrintWarning(
                "Signed-distance boundary sampling failed; falling back to binary classification: {}\n".format(exc)
            )
            try:
                fallback_resolution = max(wx.shape)
                field = _selected_boundary_field_binary_vtk(boundary_object, wx, wy, wz, sampling, fallback_resolution)
            except Exception:
                if not hasattr(boundary_object, "Shape"):
                    raise
                tolerance = 1e-7
                field = _selected_solid_field(boundary_object.Shape, wx, wy, wz, tolerance)
    else:
        raise ValueError("Unsupported boundary mode: {}".format(boundary_mode))

    return field


def _analytic_boundary_field(boundary_object, wx, wy, wz, sampling=0.0, fallback_resolution=None):
    if bool(getattr(boundary_object, "ForceTessellatedBoundary", False)):
        return None
    csg_field = _analytic_csg_boundary_field(boundary_object, wx, wy, wz, sampling, fallback_resolution)
    if csg_field is not None:
        return csg_field
    return _primitive_analytic_boundary_field(boundary_object, wx, wy, wz)


def _primitive_analytic_boundary_field(boundary_object, wx, wy, wz):
    type_id = getattr(boundary_object, "TypeId", "")
    placement = getattr(boundary_object, "Placement", None)
    if placement is None:
        return None

    if type_id == "Part::Sphere" and hasattr(boundary_object, "Radius"):
        radius = float(boundary_object.Radius)
        lx, ly, lz = _world_to_local_arrays(placement, wx, wy, wz)
        return radius - np.sqrt(lx * lx + ly * ly + lz * lz)

    if _is_part_cylinder(boundary_object):
        radius = float(boundary_object.Radius)
        height = float(boundary_object.Height)
        lx, ly, lz = _world_to_local_arrays(placement, wx, wy, wz)
        return _cylindrical_shell_field(lx, ly, lz, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), radius, 0.0, 0.0, height)

    if _is_basic_tube_feature(boundary_object):
        inner_radius = _length_value(getattr(boundary_object, "InnerRadius", 0.0))
        outer_radius = _length_value(getattr(boundary_object, "OuterRadius", 0.0))
        height = _length_value(getattr(boundary_object, "Height", 0.0))
        lx, ly, lz = _world_to_local_arrays(placement, wx, wy, wz)
        return _cylindrical_shell_field(
            lx,
            ly,
            lz,
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            outer_radius,
            inner_radius,
            0.0,
            height,
        )

    if _is_part_box(boundary_object):
        length = float(boundary_object.Length)
        width = float(boundary_object.Width)
        height = float(boundary_object.Height)
        lx, ly, lz = _world_to_local_arrays(placement, wx, wy, wz)
        inside_distance = np.minimum.reduce((lx, length - lx, ly, width - ly, lz, height - lz))
        outside = np.sqrt(
            np.maximum(-lx, 0.0) ** 2
            + np.maximum(lx - length, 0.0) ** 2
            + np.maximum(-ly, 0.0) ** 2
            + np.maximum(ly - width, 0.0) ** 2
            + np.maximum(-lz, 0.0) ** 2
            + np.maximum(lz - height, 0.0) ** 2
        )
        return np.where(inside_distance >= 0.0, inside_distance, -outside)

    if hasattr(boundary_object, "Shape"):
        sphere_shell = _spherical_shell_from_shape(boundary_object.Shape)
        if sphere_shell is not None:
            return _spherical_shell_field(wx, wy, wz, *sphere_shell)
        shell = _cylindrical_shell_from_shape(boundary_object.Shape)
        if shell is not None:
            return _cylindrical_shell_field(wx, wy, wz, *shell)

    return None


def _cylindrical_shell_from_boundary_object(boundary_object):
    if boundary_object is None or bool(getattr(boundary_object, "ForceTessellatedBoundary", False)):
        return None

    if _is_boolean_fragments_feature(boundary_object):
        shells = []
        for source_object in _boolean_fragments_objects(boundary_object):
            shell = _cylindrical_shell_from_boundary_object(source_object)
            if shell is None:
                return None
            shells.append(shell)
        if not shells:
            return None
        return _combine_coaxial_shells(shells)

    if _is_basic_tube_feature(boundary_object):
        placement = getattr(boundary_object, "Placement", None)
        if placement is None:
            return None
        center, axis = _placement_z_axis(placement)
        return (
            tuple(center),
            tuple(axis),
            _length_value(getattr(boundary_object, "OuterRadius", 0.0)),
            _length_value(getattr(boundary_object, "InnerRadius", 0.0)),
            0.0,
            _length_value(getattr(boundary_object, "Height", 0.0)),
        )

    if _is_part_cylinder(boundary_object):
        placement = getattr(boundary_object, "Placement", None)
        if placement is None:
            return None
        center, axis = _placement_z_axis(placement)
        return (
            tuple(center),
            tuple(axis),
            float(boundary_object.Radius),
            0.0,
            0.0,
            float(boundary_object.Height),
        )

    shape = getattr(boundary_object, "Shape", None)
    if shape is not None:
        return _cylindrical_shell_from_shape(shape)
    return None


def _placement_z_axis(placement):
    matrix = placement.Matrix
    center = np.array((float(matrix.A14), float(matrix.A24), float(matrix.A34)), dtype=float)
    axis = np.array((float(matrix.A13), float(matrix.A23), float(matrix.A33)), dtype=float)
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        axis = np.array((0.0, 0.0, 1.0), dtype=float)
    else:
        axis = axis / length
    return center, axis


def _combine_coaxial_shells(shells):
    center, axis, outer_radius, inner_radius, hmin, hmax = shells[0]
    center = np.asarray(center, dtype=float)
    axis = np.asarray(axis, dtype=float)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    inner = float(inner_radius)
    outer = float(outer_radius)
    lower = float(hmin)
    upper = float(hmax)
    tolerance = max(abs(outer), 1.0) * 1e-6

    for shell in shells[1:]:
        other_center, other_axis, other_outer, other_inner, other_hmin, other_hmax = shell
        other_center = np.asarray(other_center, dtype=float)
        other_axis = np.asarray(other_axis, dtype=float)
        other_axis = other_axis / max(float(np.linalg.norm(other_axis)), 1e-12)
        if abs(abs(float(np.dot(axis, other_axis))) - 1.0) > 1e-6:
            return None
        offset = other_center - center
        radial_offset = offset - np.dot(offset, axis) * axis
        if float(np.linalg.norm(radial_offset)) > tolerance:
            return None
        axial_offset = float(np.dot(offset, axis))
        inner = min(inner, float(other_inner))
        outer = max(outer, float(other_outer))
        lower = min(lower, axial_offset + float(other_hmin))
        upper = max(upper, axial_offset + float(other_hmax))

    if outer <= max(inner, 0.0) or upper <= lower:
        return None
    return tuple(center), tuple(axis), outer, max(0.0, inner), lower, upper


def _analytic_csg_boundary_field(boundary_object, wx, wy, wz, sampling=0.0, fallback_resolution=None):
    if boundary_object is None:
        return None
    type_id = getattr(boundary_object, "TypeId", "")
    if _is_boolean_fragments_feature(boundary_object):
        wx, wy, wz = _csg_operand_coordinates(boundary_object, wx, wy, wz)
        objects = _boolean_fragments_objects(boundary_object)
        if not objects:
            return None
        fields = []
        for source_object in objects:
            field = _analytic_or_leaf_boundary_field(source_object, wx, wy, wz, sampling, fallback_resolution)
            if field is None:
                return None
            fields.append(field)
        result = fields[0]
        for field in fields[1:]:
            result = np.maximum(result, field)
        return result

    if type_id in ("Part::Fuse", "Part::Cut", "Part::Common"):
        wx, wy, wz = _csg_operand_coordinates(boundary_object, wx, wy, wz)
        base = getattr(boundary_object, "Base", None)
        tool = getattr(boundary_object, "Tool", None)
        if base is None or tool is None:
            return None
        base_field = _analytic_or_leaf_boundary_field(base, wx, wy, wz, sampling, fallback_resolution)
        tool_field = _analytic_or_leaf_boundary_field(tool, wx, wy, wz, sampling, fallback_resolution)
        if base_field is None or tool_field is None:
            return None
        if type_id == "Part::Fuse":
            return np.maximum(base_field, tool_field)
        if type_id == "Part::Common":
            return np.minimum(base_field, tool_field)
        return np.minimum(base_field, -tool_field)

    if type_id in ("Part::MultiFuse", "Part::MultiCommon"):
        wx, wy, wz = _csg_operand_coordinates(boundary_object, wx, wy, wz)
        shapes = list(getattr(boundary_object, "Shapes", []) or [])
        if not shapes:
            return None
        fields = []
        for shape_object in shapes:
            field = _analytic_or_leaf_boundary_field(shape_object, wx, wy, wz, sampling, fallback_resolution)
            if field is None:
                return None
            fields.append(field)
        result = fields[0]
        for field in fields[1:]:
            if type_id == "Part::MultiFuse":
                result = np.maximum(result, field)
            else:
                result = np.minimum(result, field)
        return result

    if type_id == "Part::Compound":
        wx, wy, wz = _csg_operand_coordinates(boundary_object, wx, wy, wz)
        shapes = list(getattr(boundary_object, "Links", []) or [])
        if not shapes:
            return None
        fields = []
        for shape_object in shapes:
            field = _analytic_or_leaf_boundary_field(shape_object, wx, wy, wz, sampling, fallback_resolution)
            if field is None:
                return None
            fields.append(field)
        result = fields[0]
        for field in fields[1:]:
            result = np.maximum(result, field)
        return result

    return None


def _is_boolean_fragments_feature(boundary_object):
    if getattr(boundary_object, "TypeId", "") != "Part::FeaturePython":
        return False
    proxy = getattr(boundary_object, "Proxy", None)
    if getattr(proxy, "Type", "") == "FeatureBooleanFragments":
        return True
    return type(proxy).__name__ == "FeatureBooleanFragments"


def _boolean_fragments_objects(boundary_object):
    objects = list(getattr(boundary_object, "Objects", []) or [])
    if objects:
        return objects
    return list(getattr(boundary_object, "Shapes", []) or [])


def _csg_operand_coordinates(boundary_object, wx, wy, wz):
    placement = getattr(boundary_object, "Placement", None)
    if placement is None:
        return wx, wy, wz
    try:
        return _world_to_local_arrays(placement, wx, wy, wz)
    except Exception:
        return wx, wy, wz


def _analytic_or_leaf_boundary_field(boundary_object, wx, wy, wz, sampling=0.0, fallback_resolution=None):
    if boundary_object is None or bool(getattr(boundary_object, "ForceTessellatedBoundary", False)):
        return None
    field = _analytic_csg_boundary_field(boundary_object, wx, wy, wz, sampling, fallback_resolution)
    if field is not None:
        return field
    field = _primitive_analytic_boundary_field(boundary_object, wx, wy, wz)
    if field is not None:
        return field
    if hasattr(boundary_object, "Shape") or hasattr(boundary_object, "Mesh"):
        try:
            resolution = max(wx.shape) if fallback_resolution is None else fallback_resolution
            return _selected_boundary_field_signed_vtk(boundary_object, wx, wy, wz, sampling, resolution)
        except Exception as exc:
            App.Console.PrintWarning("Mixed analytical CSG leaf fell back unsuccessfully: {}\n".format(exc))
    return None


def _is_part_cylinder(boundary_object):
    if getattr(boundary_object, "TypeId", "") != "Part::Cylinder":
        return False
    if not all(hasattr(boundary_object, name) for name in ("Radius", "Height")):
        return False
    angle = float(getattr(boundary_object, "Angle", 360.0))
    return abs(angle - 360.0) <= 1e-7


def _is_part_box(boundary_object):
    return (
        getattr(boundary_object, "TypeId", "") == "Part::Box"
        and all(hasattr(boundary_object, name) for name in ("Length", "Width", "Height"))
    )


def _is_basic_tube_feature(boundary_object):
    if getattr(boundary_object, "TypeId", "") != "Part::FeaturePython":
        return False
    if not all(hasattr(boundary_object, name) for name in ("InnerRadius", "OuterRadius", "Height")):
        return False
    proxy = getattr(boundary_object, "Proxy", None)
    if type(proxy).__name__ != "TubeFeature":
        return False
    return _length_value(getattr(boundary_object, "OuterRadius", 0.0)) > _length_value(
        getattr(boundary_object, "InnerRadius", 0.0)
    )


def _length_value(value):
    try:
        return float(value.Value)
    except Exception:
        return float(value)


def _cylindrical_shell_from_shape(shape):
    if shape is None or shape.isNull():
        return None

    cylinders = []
    for face in shape.Faces:
        surface = face.Surface
        surface_type = type(surface).__name__
        if surface_type == "Plane":
            continue
        if surface_type != "Cylinder" or not hasattr(surface, "Radius"):
            return None
        try:
            umin, umax, _vmin, _vmax = face.ParameterRange
        except Exception:
            return None
        if abs(abs(float(umax) - float(umin)) - 2.0 * math.pi) > 1e-5:
            return None
        center = _vector_array(surface.Center)
        axis = _unit_array(surface.Axis)
        if axis is None:
            return None
        cylinders.append((float(surface.Radius), center, axis))

    if len(cylinders) not in (1, 2):
        return None

    cylinders.sort(key=lambda item: item[0])
    radii = [item[0] for item in cylinders]
    if radii[-1] <= 1e-9:
        return None
    if len(radii) == 2 and abs(radii[1] - radii[0]) <= max(radii[1] * 1e-7, 1e-9):
        return None

    center = cylinders[-1][1]
    axis = cylinders[-1][2]
    tolerance = max(radii[-1] * 1e-6, 1e-7)
    for _radius, other_center, other_axis in cylinders:
        if abs(abs(float(np.dot(axis, other_axis))) - 1.0) > 1e-6:
            return None
        offset = other_center - center
        radial_offset = offset - np.dot(offset, axis) * axis
        if float(np.linalg.norm(radial_offset)) > tolerance:
            return None

    projections = []
    for vertex in shape.Vertexes:
        point = _vector_array(vertex.Point)
        projections.append(float(np.dot(point - center, axis)))
    if not projections:
        return None
    hmin = min(projections)
    hmax = max(projections)
    if hmax - hmin <= 1e-9:
        return None

    inner_radius = radii[0] if len(radii) == 2 else 0.0
    outer_radius = radii[-1]
    return tuple(center), tuple(axis), outer_radius, inner_radius, hmin, hmax


def _spherical_shell_from_shape(shape):
    if shape is None or shape.isNull():
        return None

    spheres = []
    for face in shape.Faces:
        surface = face.Surface
        if type(surface).__name__ != "Sphere" or not hasattr(surface, "Radius"):
            continue
        center = _vector_array(surface.Center)
        spheres.append((float(surface.Radius), center))

    if len(spheres) not in (1, 2):
        return None

    spheres.sort(key=lambda item: item[0])
    radii = [item[0] for item in spheres]
    if radii[-1] <= 1e-9:
        return None
    if len(radii) == 2 and abs(radii[1] - radii[0]) <= max(radii[1] * 1e-7, 1e-9):
        return None

    center = spheres[-1][1]
    tolerance = max(radii[-1] * 1e-6, 1e-7)
    for _radius, other_center in spheres:
        if float(np.linalg.norm(other_center - center)) > tolerance:
            return None

    inner_radius = radii[0] if len(radii) == 2 else 0.0
    outer_radius = radii[-1]
    return tuple(center), outer_radius, inner_radius


def _spherical_shell_field(px, py, pz, center, outer_radius, inner_radius):
    center = np.asarray(center, dtype=float)
    dx = px - center[0]
    dy = py - center[1]
    dz = pz - center[2]
    radius = np.sqrt(dx * dx + dy * dy + dz * dz)

    inner_radius = max(0.0, float(inner_radius))
    outer_radius = max(inner_radius + 1e-12, float(outer_radius))
    inside_distance = np.minimum(radius - inner_radius, outer_radius - radius)
    outside = np.maximum(inner_radius - radius, 0.0) + np.maximum(radius - outer_radius, 0.0)
    return np.where(inside_distance >= 0.0, inside_distance, -outside)


def _cylindrical_shell_field(px, py, pz, center, axis, outer_radius, inner_radius, hmin, hmax):
    center = np.asarray(center, dtype=float)
    axis = np.asarray(axis, dtype=float)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)

    dx = px - center[0]
    dy = py - center[1]
    dz = pz - center[2]
    axial = dx * axis[0] + dy * axis[1] + dz * axis[2]
    radial_sq = dx * dx + dy * dy + dz * dz - axial * axial
    radial = np.sqrt(np.maximum(radial_sq, 0.0))

    inner_radius = max(0.0, float(inner_radius))
    outer_radius = max(inner_radius + 1e-12, float(outer_radius))
    lower = float(hmin)
    upper = float(hmax)

    inside_distance = np.minimum.reduce(
        (
            radial - inner_radius,
            outer_radius - radial,
            axial - lower,
            upper - axial,
        )
    )
    radial_outside = np.maximum(inner_radius - radial, 0.0) + np.maximum(radial - outer_radius, 0.0)
    axial_outside = np.maximum(lower - axial, 0.0) + np.maximum(axial - upper, 0.0)
    outside = np.sqrt(radial_outside * radial_outside + axial_outside * axial_outside)
    return np.where(inside_distance >= 0.0, inside_distance, -outside)


def _vector_array(vector):
    return np.array((float(vector.x), float(vector.y), float(vector.z)), dtype=float)


def _unit_array(vector):
    values = _vector_array(vector)
    length = float(np.linalg.norm(values))
    if length <= 1e-12:
        return None
    return values / length


def _world_to_local_arrays(placement, wx, wy, wz):
    inverse = placement.inverse()
    matrix = inverse.Matrix
    lx = matrix.A11 * wx + matrix.A12 * wy + matrix.A13 * wz + matrix.A14
    ly = matrix.A21 * wx + matrix.A22 * wy + matrix.A23 * wz + matrix.A24
    lz = matrix.A31 * wx + matrix.A32 * wy + matrix.A33 * wz + matrix.A34
    return lx, ly, lz


def _rotation_matrix(origin_rotation, boundary_object=None):
    if isinstance(origin_rotation, bool):
        if origin_rotation and _is_part_box(boundary_object):
            return _freecad_rotation_matrix(boundary_object.Placement.Rotation)
        return None
    if origin_rotation is None:
        return None
    if hasattr(origin_rotation, "toMatrix"):
        return _freecad_rotation_matrix(origin_rotation)
    try:
        rx, ry, rz = [math.radians(float(value)) for value in origin_rotation]
    except Exception:
        return None

    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array(((1.0, 0.0, 0.0), (0.0, cx, -sx), (0.0, sx, cx)), dtype=float)
    my = np.array(((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy)), dtype=float)
    mz = np.array(((cz, -sz, 0.0), (sz, cz, 0.0), (0.0, 0.0, 1.0)), dtype=float)
    return mz @ my @ mx


def _freecad_rotation_matrix(rotation):
    matrix = rotation.toMatrix()
    return np.array(
        (
            (float(matrix.A11), float(matrix.A12), float(matrix.A13)),
            (float(matrix.A21), float(matrix.A22), float(matrix.A23)),
            (float(matrix.A31), float(matrix.A32), float(matrix.A33)),
        ),
        dtype=float,
    )


def _world_to_origin_frame_arrays(rotation_matrix, wx, wy, wz, origin):
    inverse = rotation_matrix.T
    dx = wx - float(origin[0])
    dy = wy - float(origin[1])
    dz = wz - float(origin[2])
    tx = inverse[0, 0] * dx + inverse[0, 1] * dy + inverse[0, 2] * dz
    ty = inverse[1, 0] * dx + inverse[1, 1] * dy + inverse[1, 2] * dz
    tz = inverse[2, 0] * dx + inverse[2, 1] * dy + inverse[2, 2] * dz
    return tx, ty, tz


def _apply_boundary_clip(volume, has_boundary):
    if not has_boundary:
        return volume
    return volume.clip_scalar(scalars="boundary", value=0.0, invert=False)


def _contour_surface(grid, scalars):
    return grid.contour(isosurfaces=[0.0], scalars=scalars).extract_surface(algorithm="dataset_surface").triangulate()


def _combine_polydata(parts):
    non_empty = [part for part in parts if part.n_points > 0 and part.n_cells > 0]
    if not non_empty:
        raise ValueError("Generated TPMS mesh is empty")
    combined = non_empty[0]
    for part in non_empty[1:]:
        combined = combined.merge(part, merge_points=False)
    return combined.clean().triangulate()


def _generate_uncapped_polydata(grid, part, has_boundary):
    if part == PART_SHEET:
        surface = _combine_polydata(
            [
                _contour_surface(grid, "upper_surface"),
                _contour_surface(grid, "lower_surface"),
            ]
        )
    elif part == PART_UPPER:
        surface = _contour_surface(grid, "upper_surface")
    elif part == PART_LOWER:
        surface = _contour_surface(grid, "lower_surface")
    elif part == PART_SURFACE:
        surface = _contour_surface(grid, "surface")
    else:
        raise ValueError("Unsupported TPMS part: {}".format(part))

    surface = _apply_boundary_clip(surface, has_boundary)
    return surface.clean().triangulate()


def _extract_part_polydata(grid, part, has_boundary, add_caps, material_scalars=None):
    if material_scalars is not None:
        if not add_caps:
            surface = grid.contour(isosurfaces=[0.0], scalars=material_scalars)
            surface = _apply_boundary_clip(surface, has_boundary)
            return surface.extract_surface(algorithm="dataset_surface").clean().triangulate()
        volume = grid.clip_scalar(scalars=material_scalars, value=0.0, invert=False)
        volume = _apply_boundary_clip(volume, has_boundary)
        return volume.extract_surface(algorithm="dataset_surface").clean().triangulate()

    if not add_caps:
        return _generate_uncapped_polydata(grid, part, has_boundary)

    if part == PART_SHEET:
        volume = grid.clip_scalar(scalars="upper_surface").clip_scalar(
            scalars="lower_surface",
            invert=False,
        )
        volume = _apply_boundary_clip(volume, has_boundary)
        return volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    if part == PART_UPPER:
        volume = grid.clip_scalar(scalars="upper_surface", invert=False)
        volume = _apply_boundary_clip(volume, has_boundary)
        return volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    if part == PART_LOWER:
        volume = grid.clip_scalar(scalars="lower_surface")
        volume = _apply_boundary_clip(volume, has_boundary)
        return volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    if part == PART_SURFACE:
        return grid.contour(isosurfaces=[0.0], scalars="surface").extract_surface().clean().triangulate()
    raise ValueError("Unsupported TPMS part: {}".format(part))


def generate_polydata(
    equation,
    part=PART_SHEET,
    cell_size=(1.0, 1.0, 1.0),
    repeat_cell=(1, 1, 1),
    resolution=32,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    add_caps=True,
    origin=None,
    origin_rotation=None,
    density_mode="Uniform",
    base_density=1.0,
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    density_offset_mode="Uniform",
    density_offset_value=0.3,
    density_offset_controls=None,
    density_offset_gradient=GRADIENT_FACE_DISTANCE,
    equation_blend_controls=None,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    configure_vtk_smp()
    grid, x, y, z, offset_field, wx, wy, wz = _make_grid(
        cell_size,
        repeat_cell,
        resolution,
        phase,
        boundary_mode,
        boundary_object,
        sampling,
        origin,
        origin_rotation,
        density_mode,
        base_density,
        density_controls,
        density_count_mode,
        density_gradient,
        density_offset_mode,
        density_offset_value,
        density_offset_controls,
        density_offset_gradient,
        grading_resolution,
        harmonic_boundary_condition,
    )
    field = np.asarray(evaluate_equation(equation, x, y, z), dtype=float)
    if field.shape == ():
        field = np.full(x.shape, float(field))
    field = _blend_equation_field(field, x, y, z, wx, wy, wz, equation_blend_controls)

    if offset_field.shape != field.shape:
        offset_field = np.full(field.shape, float(density_offset_value), dtype=float)
    grid["surface"] = field.ravel(order="F")
    grid["lower_surface"] = (field + 0.5 * offset_field).ravel(order="F")
    grid["upper_surface"] = (field - 0.5 * offset_field).ravel(order="F")
    has_boundary = _add_boundary_field(grid, wx, wy, wz, boundary_mode, boundary_object, sampling)
    return _extract_part_polydata(grid, part, has_boundary, add_caps)


def generate_hybrid_polydata(
    equation,
    part=PART_SHEET,
    cell_size=(1.0, 1.0, 1.0),
    repeat_cell=(1, 1, 1),
    resolution=32,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
    boundary_mode=BOUNDARY_SELECTED_SOLID,
    boundary_object=None,
    sampling=0.0,
    add_caps=True,
    origin=None,
    origin_rotation=None,
    base_density=1.0,
    region_specs=None,
    transition_controls=None,
    transition_region_specs=None,
    density_mode="Uniform",
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    density_offset_mode="Uniform",
    density_offset_controls=None,
    density_offset_gradient=GRADIENT_FACE_DISTANCE,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
    coordinate_mode=COORDINATE_CARTESIAN,
    ring_angular_cells=8,
    face_transition_specs=None,
    edge_transition_specs=None,
):
    configure_vtk_smp()
    region_specs = list(region_specs or [])
    transition_controls = list(transition_controls or [])
    transition_region_specs = list(transition_region_specs or [])
    face_transition_specs = list(face_transition_specs or [])
    edge_transition_specs = list(edge_transition_specs or [])
    cylindrical_grid = None
    if str(coordinate_mode) == COORDINATE_CYLINDRICAL_RING:
        cylindrical_grid = _make_hybrid_cylindrical_ring_grid(
            boundary_object,
            cell_size,
            resolution,
            phase,
            origin,
            origin_rotation,
            ring_angular_cells,
            density_mode,
            base_density,
            density_controls,
            density_count_mode,
            density_gradient,
            boundary_mode,
            sampling,
            offset,
            grading_resolution,
            harmonic_boundary_condition,
        )
    if cylindrical_grid is not None:
        grid, x, y, z, offset_field, wx, wy, wz, ring_map = cylindrical_grid
    else:
        ring_map = None
        grid, x, y, z, offset_field, wx, wy, wz = _make_grid(
            cell_size,
            repeat_cell,
            resolution,
            phase,
            boundary_mode,
            boundary_object,
            sampling,
            origin,
            origin_rotation,
            density_mode,
            base_density,
            density_controls,
            density_count_mode,
            density_gradient,
            "Uniform",
            offset,
            None,
            GRADIENT_FACE_DISTANCE,
            grading_resolution,
            harmonic_boundary_condition,
        )
        if str(coordinate_mode) == COORDINATE_CYLINDRICAL_RING:
            x, y, z = _cylindrical_phase_grid(
                wx,
                wy,
                wz,
                cell_size,
                phase,
                origin,
                origin_rotation,
                boundary_object,
                ring_angular_cells,
                density_mode,
                base_density,
                density_controls,
                density_count_mode,
                density_gradient,
                boundary_mode,
                sampling,
                grading_resolution,
                harmonic_boundary_condition,
            )

    field = np.asarray(evaluate_equation(equation, x, y, z), dtype=float)
    if field.shape == ():
        field = np.full(x.shape, float(field))
    offset_field = np.full(field.shape, float(offset), dtype=float)
    material_field = np.full(field.shape, -1.0, dtype=float)
    region_index = np.full(field.shape, -1, dtype=np.int32)
    base_density = max(0.05, float(base_density))
    fill_value = max(1.0, abs(float(offset)))

    fallback_resolution = max(wx.shape)
    def boundary_mask(boundary):
        try:
            return _selected_boundary_field_signed_vtk(boundary, wx, wy, wz, sampling, fallback_resolution) >= 0.0
        except Exception:
            return _selected_boundary_field_binary_vtk(boundary, wx, wy, wz, sampling, fallback_resolution) > 0.0

    def boundary_distance(boundary):
        try:
            return _selected_boundary_distance_vtk(boundary, wx, wy, wz, sampling, fallback_resolution)
        except Exception:
            mask = _selected_boundary_field_binary_vtk(boundary, wx, wy, wz, sampling, fallback_resolution) > 0.0
            return np.where(mask, 0.0, np.inf)

    def evaluated_field(spec, equation_key="equation", density_key="base_density"):
        surface_key = equation_key.replace("equation", "surface")
        surface_mode = str(spec.get(surface_key, spec.get("surface", "")))
        if surface_mode in (SURFACE_EMPTY, SURFACE_SOLID_FILL):
            return np.zeros(field.shape, dtype=float)

        origin_key = equation_key.replace("equation", "origin")
        rotation_key = equation_key.replace("equation", "origin_rotation")
        
        # We must apply the same base_density and phase shift as _density_phase_coordinates
        # to ensure local origins stay in sync with the global grid.
        global_phase = np.asarray(phase, dtype=float)
        global_base_density = max(0.05, float(base_density))

        # Check if this specific spec has a local origin/rotation override.
        if spec.get(origin_key) is not None or spec.get(rotation_key) is not None:
            local_origin = spec.get(origin_key)
            if local_origin is None:
                local_origin = _default_origin(BOUNDARY_SELECTED_SOLID, spec.get("boundary_object"))
            local_origin = np.asarray(local_origin, dtype=float)
            local_rotation = spec.get(rotation_key)
            local_rotation_matrix = _rotation_matrix(local_rotation, spec.get("boundary_object"))

            if local_rotation_matrix is not None:
                lx, ly, lz = _world_to_origin_frame_arrays(local_rotation_matrix, wx, wy, wz, local_origin)
            else:
                lx = wx - local_origin[0]
                ly = wy - local_origin[1]
                lz = wz - local_origin[2]
            
            # Apply global phase and scaling
            lx = global_base_density * (lx + global_phase[0])
            ly = global_base_density * (ly + global_phase[1])
            lz = global_base_density * (lz + global_phase[2])
        else:
            # Fall back to pre-calculated global phase coordinates
            lx, ly, lz = x, y, z

        density = max(0.05, float(spec.get(density_key, base_density)))
        # scale here is (target_density / base_density). 
        # Since lx is already scaled by base_density, lx * scale = target_density * (tx + phase)
        scale = density / global_base_density
        equation_text = str(spec.get(equation_key, equation)).strip()
        if not equation_text:
            equation_text = equation
        values = np.asarray(evaluate_equation(equation_text, lx * scale, ly * scale, lz * scale), dtype=float)
        if values.shape == ():
            values = np.full(field.shape, float(values))
        return values

    def material_from_field(values, offset_values, part_name, surface_mode=""):
        surface_mode = str(surface_mode)
        if surface_mode == SURFACE_EMPTY:
            return np.full(field.shape, -fill_value, dtype=float)
        if surface_mode == SURFACE_SOLID_FILL:
            return np.full(field.shape, fill_value, dtype=float)
        offset_values = np.asarray(offset_values, dtype=float)
        half_offset = 0.5 * offset_values
        if str(part_name) == PART_UPPER:
            return values - half_offset
        if str(part_name) == PART_LOWER:
            return -values - half_offset
        if str(part_name) == PART_SURFACE:
            return -np.abs(values)
        return np.minimum(half_offset - values, values + half_offset)

    def interval_bounds_for_part(values, offset_values, part_name):
        offset_values = np.asarray(offset_values, dtype=float)
        half_offset = 0.5 * offset_values
        values = np.asarray(values, dtype=float)
        limit = max(
            float(np.nanmax(np.abs(values))) if values.size else 1.0,
            float(np.nanmax(np.abs(offset_values))) if offset_values.size else 1.0,
            1.0,
        ) + 1.0
        part_name = str(part_name)
        if part_name == PART_UPPER:
            return half_offset, np.full(field.shape, limit, dtype=float)
        if part_name == PART_LOWER:
            return np.full(field.shape, -limit, dtype=float), -half_offset
        if part_name == PART_SHEET:
            return -half_offset, half_offset
        return None, None

    def transition_material_from_parts(
        source_values,
        target_values,
        offset_values,
        blend_weight,
        source_part,
        target_part,
        source_surface="",
        target_surface="",
    ):
        if str(source_surface) in (SURFACE_EMPTY, SURFACE_SOLID_FILL) or str(target_surface) in (SURFACE_EMPTY, SURFACE_SOLID_FILL):
            return None
        source_lower, source_upper = interval_bounds_for_part(source_values, offset_values, source_part)
        target_lower, target_upper = interval_bounds_for_part(target_values, offset_values, target_part)
        if source_lower is None or target_lower is None:
            return None
        blend_values = (1.0 - blend_weight) * source_values + blend_weight * target_values
        lower = (1.0 - blend_weight) * source_lower + blend_weight * target_lower
        upper = (1.0 - blend_weight) * source_upper + blend_weight * target_upper
        return np.minimum(blend_values - lower, upper - blend_values)

    def transition_weight(raw_weight, blend_mode):
        if str(blend_mode) == TRANSITION_BLEND_SIGMOID:
            return _sigmoidstep(raw_weight)
        return _smoothstep(raw_weight)

    def _edge_transition_distance(edge_points):
        """
        Compute the Euclidean distance from each grid voxel to the nearest edge transition point.
        Uses Scipy's cKDTree for high-performance spatial querying.
        """
        from scipy.spatial import cKDTree as KDTree
        pts = np.column_stack((wx.ravel(), wy.ravel(), wz.ravel()))
        tree = KDTree(edge_points)
        dist_flat, _ = tree.query(pts, k=1)
        return dist_flat.reshape(wx.shape)

    def _edge_transition_weights(adj_specs, distance, blend_radius, blend_mode):
        """
        Compute continuous, normalized N-way weights for solid regions meeting at an edge.
        Ensures C^1 continuity at the edge center and cylinder boundary.
        
        Returns:
            weights: A list of tuples (r_spec, w_k) containing the region spec and its weight array.
            u: Smoothstepped normalized radial coordinate (1.0 at cylinder boundary, 0.0 at center).
        """
        N = len(adj_specs)
        u = np.clip(distance / blend_radius, 0.0, 1.0)
        u = transition_weight(u, blend_mode)
        
        v_keys = []
        for r_spec in adj_specs:
            r_boundary = r_spec.get("boundary_object")
            if r_boundary is None:
                # Fallback weight when no boundary object is defined
                own_mask = (region_index == int(r_spec["index"]))
                w_k_fallback = np.where(own_mask, 1.0 / N + ((N - 1.0) / N) * u, (1.0 - u) / N)
                v_keys.append(w_k_fallback)
            else:
                dist_k = boundary_distance(r_boundary)
                inside_k = boundary_mask(r_boundary)
                d_k = np.where(inside_k, 0.0, dist_k)
                
                t_k = np.clip(1.0 - d_k / blend_radius, 0.0, 1.0)
                v_k = transition_weight(t_k, blend_mode)
                v_keys.append(v_k)
        
        v_sum = sum(v_keys)
        v_sum = np.where(v_sum > 1e-12, v_sum, 1.0)
        
        weights = []
        for idx, r_spec in enumerate(adj_specs):
            w_k = v_keys[idx] / v_sum
            weights.append((r_spec, w_k))
            
        return weights, u

    def skeletal_part_for_labyrinth(part_name, labyrinth):
        if not _is_skeletal_part(part_name):
            return str(part_name)
        sign = _labyrinth_sign(labyrinth, part_name)
        if sign is None:
            return str(part_name)
        return PART_UPPER if sign > 0.0 else PART_LOWER

    def cross_labyrinth_bridge_material(
        source_values,
        target_values,
        offset_values,
        blend_weight,
        source_part,
        target_part,
        source_labyrinth,
        target_labyrinth,
        topology_mode,
        source_surface="",
        target_surface="",
    ):
        if str(source_surface) in (SURFACE_EMPTY, SURFACE_SOLID_FILL) or str(target_surface) in (SURFACE_EMPTY, SURFACE_SOLID_FILL):
            return None
        if not (_is_skeletal_part(source_part) and _is_skeletal_part(target_part)):
            return None
        if str(topology_mode or TRANSITION_TOPOLOGY_SAME_SIDE) != TRANSITION_TOPOLOGY_CROSS_BRIDGE:
            return None
        source_sign = _labyrinth_sign(source_labyrinth, source_part)
        target_sign = _labyrinth_sign(target_labyrinth, target_part)
        if source_sign is None or target_sign is None or source_sign == target_sign:
            return None
        offset_values = np.asarray(offset_values, dtype=float)
        half_offset = 0.5 * offset_values
        blend_values = (1.0 - blend_weight) * source_values + blend_weight * target_values
        bridge_peak = 4.0 * blend_weight * (1.0 - blend_weight)
        return bridge_peak * half_offset - np.abs(blend_values)

    def material_for_spec(spec, equation_key="equation", density_key="base_density", offset_key="offset", part_key="part", surface_key="surface"):
        surface_mode = str(spec.get(surface_key, spec.get("surface", "")))
        offset_value = float(spec.get(offset_key, offset))
        values = evaluated_field(spec, equation_key, density_key)
        return material_from_field(values, offset_value, str(spec.get(part_key, part)), surface_mode)

    for spec in region_specs:
        boundary = spec.get("boundary_object")
        if boundary is None:
            continue
        # Use mask_boundary_object (fragmented solid) if available, to ensure non-overlapping
        # voxel assignment even when the source objects overlap before fragmentation.
        mask_boundary = spec.get("mask_boundary_object", boundary)
        mask = boundary_mask(mask_boundary)
        if not np.any(mask):
            continue
        spec_field = evaluated_field(spec)
        if spec_field.shape == field.shape:
            field[mask] = spec_field[mask]
        offset_field[mask] = float(spec.get("offset", offset))
        spec_material = material_for_spec(spec)
        if spec_material.shape == material_field.shape:
            material_field[mask] = spec_material[mask]
        region_index[mask] = int(spec.get("index", -1))


    for spec in transition_region_specs:
        boundary = spec.get("boundary_object")
        source_boundary = spec.get("source_boundary_object")
        target_boundary = spec.get("target_boundary_object")
        if boundary is None or source_boundary is None or target_boundary is None:
            continue
        mask = boundary_mask(boundary)
        if not np.any(mask):
            continue
        source_field = evaluated_field(spec, "source_equation", "source_base_density")
        target_field = evaluated_field(spec, "target_equation", "target_base_density")
        if source_field.shape != field.shape or target_field.shape != field.shape:
            continue
        source_material = material_for_spec(
            spec,
            "source_equation",
            "source_base_density",
            "source_offset",
            "source_part",
            "source_surface",
        )
        target_material = material_for_spec(
            spec,
            "target_equation",
            "target_base_density",
            "target_offset",
            "target_part",
            "target_surface",
        )
        if source_material.shape != material_field.shape or target_material.shape != material_field.shape:
            continue
        source_distance = boundary_distance(source_boundary)
        target_distance = boundary_distance(target_boundary)
        denom = source_distance + target_distance
        t = np.divide(
            source_distance,
            denom,
            out=np.full(field.shape, 0.5, dtype=float),
            where=np.isfinite(denom) & (denom > 1e-12),
        )
        blend_mode = str(spec.get("blend", TRANSITION_BLEND_THRESHOLD))
        t = transition_weight(t, blend_mode)
        field[mask] = ((1.0 - t) * source_field + t * target_field)[mask]
        source_offset = float(spec.get("source_offset", offset))
        target_offset = float(spec.get("target_offset", offset))
        offset_field[mask] = ((1.0 - t) * source_offset + t * target_offset)[mask]
        material_field[mask] = ((1.0 - t) * source_material + t * target_material)[mask]
        region_index[mask] = int(spec.get("index", -1))

    for spec in list(face_transition_specs or []):
        source_index = int(spec.get("source_index", -1))
        target_index = int(spec.get("target_index", -1))
        blend_width = float(spec.get("blend_width", 5.0))
        if source_index == -1 or target_index == -1:
            continue
        transition_mask = (region_index == source_index) | (region_index == target_index)
        if not np.any(transition_mask):
            continue
        try:
            distance = np.abs(_face_distance_field(wx, wy, wz, spec))
            blend_mask = transition_mask & (distance <= blend_width / 2.0)
            if not np.any(blend_mask):
                continue
            source_field = evaluated_field(spec, "source_equation", "source_base_density")
            target_field = evaluated_field(spec, "target_equation", "target_base_density")
            if source_field.shape != field.shape or target_field.shape != field.shape:
                continue
            t = np.where(region_index == source_index, 0.5 * (1.0 - 2.0 * distance / blend_width), 0.5 * (1.0 + 2.0 * distance / blend_width))
            t = np.clip(t, 0.0, 1.0)
            blend_mode = str(spec.get("blend", TRANSITION_BLEND_THRESHOLD))
            t = transition_weight(t, blend_mode)
            field[blend_mask] = ((1.0 - t) * source_field + t * target_field)[blend_mask]
            source_offset = float(spec.get("source_offset", offset))
            target_offset = float(spec.get("target_offset", offset))
            offset_field[blend_mask] = ((1.0 - t) * source_offset + t * target_offset)[blend_mask]
        except Exception as exc:
            App.Console.PrintWarning("Failed to apply face transition: {}\n".format(exc))

    for spec in list(edge_transition_specs or []):
        blend_radius = float(spec.get("blend_radius", 5.0))
        edge_points = spec.get("edge_points", [])
        if not edge_points or blend_radius <= 0.0:
            continue
        adj_specs = spec.get("adjacent_regions", [])
        if len(adj_specs) < 2:
            continue
        
        adj_indices = [int(r["index"]) for r in adj_specs]
        transition_mask = np.isin(region_index, adj_indices)
        if not np.any(transition_mask):
            continue
            
        try:
            # 1. Compute Euclidean distance from each voxel to the transition edge
            distance = _edge_transition_distance(edge_points)
            
            # Define the cylindrical region of influence
            blend_mask = transition_mask & (distance <= blend_radius)
            if not np.any(blend_mask):
                continue
                
            # 2. Compute N-way regional blending weights and the radial blend coordinate
            blend_mode = str(spec.get("blend", TRANSITION_BLEND_THRESHOLD))
            weights, u = _edge_transition_weights(adj_specs, distance, blend_radius, blend_mode)
            
            # 3. Capture pre-existing background (which already contains face transitions)
            bg_field = field.copy()
            bg_offset = offset_field.copy()
            
            # 4. Perform N-way convex combination blending for Phase 1 fields and offsets
            blended_field = np.zeros(field.shape, dtype=float)
            blended_offset = np.zeros(field.shape, dtype=float)
            
            for r_spec, w_k in weights:
                r_field = evaluated_field(r_spec, "equation", "base_density")
                r_offset = float(r_spec.get("offset", offset))
                
                blended_field += w_k * r_field
                blended_offset += w_k * r_offset
            
            # 5. Hierarchical Background Blending: smoothly morph the edge blend 
            # into the background fields to maintain C^1 continuity at the boundary (d = R).
            w_edge = 1.0 - u
            final_field = w_edge * blended_field + (1.0 - w_edge) * bg_field
            final_offset = w_edge * blended_offset + (1.0 - w_edge) * bg_offset
                
            field[blend_mask] = final_field[blend_mask]
            offset_field[blend_mask] = final_offset[blend_mask]
        except Exception as exc:
            App.Console.PrintWarning("Failed to apply edge transition in Phase 1: {}\n".format(exc))

    for control in transition_controls:
        source_index = int(control.get("source_index", -999999))
        target_equation = str(control.get("target_equation", "")).strip()
        if not target_equation:
            continue
        mask = region_index == source_index
        if not np.any(mask):
            continue
        try:
            distance = np.abs(_face_distance_field(wx, wy, wz, control))
            weight = _smooth_falloff_weight(distance, max(1e-9, float(control.get("transition", 1.0))))
            weight = np.where(mask, weight, 0.0)
            if not np.any(weight > 0.0):
                continue
            density = max(0.05, float(control.get("target_density", base_density)))
            scale = density / base_density
            target = np.asarray(evaluate_equation(target_equation, x * scale, y * scale, z * scale), dtype=float)
            if target.shape == ():
                target = np.full(field.shape, float(target))
            if target.shape != field.shape:
                continue
            field = field + weight * (target - field)
            if "target_offset" in control:
                offset_field = offset_field + weight * (float(control["target_offset"]) - offset_field)
        except Exception as exc:
            App.Console.PrintWarning("Ignoring hybrid TPMS transition control: {}\n".format(exc))

    offset_field = _apply_offset_controls_to_field(
        offset_field,
        wx,
        wy,
        wz,
        density_offset_mode,
        density_offset_controls,
        density_offset_gradient,
        boundary_mode,
        boundary_object,
        sampling,
        grading_resolution,
        harmonic_boundary_condition,
    )
    material_field = np.full(field.shape, -1.0, dtype=float)
    for spec in region_specs:
        boundary = spec.get("boundary_object")
        if boundary is None:
            continue
        # Use mask_boundary_object (fragmented solid) if available, to ensure non-overlapping
        # voxel assignment even when the source objects overlap before fragmentation.
        mask_boundary = spec.get("mask_boundary_object", boundary)
        mask = boundary_mask(mask_boundary)
        if not np.any(mask):
            continue
        spec_field = evaluated_field(spec)
        spec_material = material_from_field(
            spec_field,
            offset_field,
            str(spec.get("part", part)),
            str(spec.get("surface", "")),
        )
        material_field[mask] = spec_material[mask]

    for spec in transition_region_specs:
        boundary = spec.get("boundary_object")
        source_boundary = spec.get("source_boundary_object")
        target_boundary = spec.get("target_boundary_object")
        if boundary is None or source_boundary is None or target_boundary is None:
            continue
        mask = boundary_mask(boundary)
        if not np.any(mask):
            continue
        source_field = evaluated_field(spec, "source_equation", "source_base_density")
        target_field = evaluated_field(spec, "target_equation", "target_base_density")
        source_material = material_from_field(
            source_field,
            offset_field,
            str(spec.get("source_part", part)),
            str(spec.get("source_surface", "")),
        )
        target_material = material_from_field(
            target_field,
            offset_field,
            str(spec.get("target_part", part)),
            str(spec.get("target_surface", "")),
        )
        source_distance = boundary_distance(source_boundary)
        target_distance = boundary_distance(target_boundary)
        denom = source_distance + target_distance
        t = np.divide(
            source_distance,
            denom,
            out=np.full(field.shape, 0.5, dtype=float),
            where=np.isfinite(denom) & (denom > 1e-12),
        )
        blend_mode = str(spec.get("blend", TRANSITION_BLEND_THRESHOLD))
        t = transition_weight(t, blend_mode)
        source_part = str(spec.get("source_part", part))
        target_part = str(spec.get("target_part", part))
        source_labyrinth = str(spec.get("source_labyrinth", LABYRINTH_AUTO))
        target_labyrinth = str(spec.get("target_labyrinth", LABYRINTH_AUTO))
        topology_mode = str(spec.get("topology", TRANSITION_TOPOLOGY_SAME_SIDE))
        effective_source_part = skeletal_part_for_labyrinth(source_part, source_labyrinth)
        effective_target_part = skeletal_part_for_labyrinth(target_part, target_labyrinth)
        source_material = material_from_field(
            source_field,
            offset_field,
            effective_source_part,
            str(spec.get("source_surface", "")),
        )
        target_material = material_from_field(
            target_field,
            offset_field,
            effective_target_part,
            str(spec.get("target_surface", "")),
        )
        if blend_mode == TRANSITION_BLEND_SIGMOID:
            blended_material = ((1.0 - t) * source_material + t * target_material)
        elif blend_mode == TRANSITION_BLEND_NORMALIZED_SUM:
            k = float(spec.get("correction_factor", 0.0))
            w1 = 1.0 - t
            w2 = t
            # Avoid division by zero at endpoints, though np.divide handles it
            norm = np.sqrt(w1**2 + w2**2)
            W1 = np.divide(w1, norm, out=np.zeros_like(w1), where=norm > 1e-12)
            W2 = np.divide(w2, norm, out=np.zeros_like(w2), where=norm > 1e-12)

            # ASLI correction factor peaks at W=0.5
            C1 = 1.0 + k * (1.0 - (2.0 * W1 - 1.0)**2)
            C2 = 1.0 + k * (1.0 - (2.0 * W2 - 1.0)**2)

            def adjust_offset_asli(off, part_name, corr):
                # For skeletal, thinning is compensated by reducing the threshold (offset)
                # For sheets, thinning is compensated by increasing the thickness (offset)
                if _is_skeletal_part(part_name):
                    return off / corr
                return off * corr

            # We use the interpolated offset_field as base, as it already handles
            # grading between source and target offset values.
            source_material_adj = material_from_field(
                source_field,
                adjust_offset_asli(offset_field, effective_source_part, C1),
                effective_source_part,
                str(spec.get("source_surface", "")),
            )
            target_material_adj = material_from_field(
                target_field,
                adjust_offset_asli(offset_field, effective_target_part, C2),
                effective_target_part,
                str(spec.get("target_surface", "")),
            )
            blended_material = W1 * source_material_adj + W2 * target_material_adj
        else:
            blended_material = transition_material_from_parts(
                source_field,
                target_field,
                offset_field,
                t,
                effective_source_part,
                effective_target_part,
                str(spec.get("source_surface", "")),
                str(spec.get("target_surface", "")),
            )
            if blended_material is None:
                blended_material = ((1.0 - t) * source_material + t * target_material)
        bridge_material = cross_labyrinth_bridge_material(
            source_field,
            target_field,
            offset_field,
            t,
            source_part,
            target_part,
            source_labyrinth,
            target_labyrinth,
            topology_mode,
            str(spec.get("source_surface", "")),
            str(spec.get("target_surface", "")),
        )
        if bridge_material is not None:
            blended_material = np.maximum(blended_material, bridge_material)
        material_field[mask] = blended_material[mask]

    for spec in list(face_transition_specs or []):
        source_index = int(spec.get("source_index", -1))
        target_index = int(spec.get("target_index", -1))
        blend_width = float(spec.get("blend_width", 5.0))
        if source_index == -1 or target_index == -1:
            continue
        transition_mask = (region_index == source_index) | (region_index == target_index)
        if not np.any(transition_mask):
            continue
        try:
            distance = np.abs(_face_distance_field(wx, wy, wz, spec))
            blend_mask = transition_mask & (distance <= blend_width / 2.0)
            if not np.any(blend_mask):
                continue
                
            source_field = evaluated_field(spec, "source_equation", "source_base_density")
            target_field = evaluated_field(spec, "target_equation", "target_base_density")
            
            t = np.where(region_index == source_index, 0.5 * (1.0 - 2.0 * distance / blend_width), 0.5 * (1.0 + 2.0 * distance / blend_width))
            t = np.clip(t, 0.0, 1.0)
            
            blend_mode = str(spec.get("blend", TRANSITION_BLEND_THRESHOLD))
            t = transition_weight(t, blend_mode)
            
            source_part = str(spec.get("source_part", part))
            target_part = str(spec.get("target_part", part))
            source_labyrinth = str(spec.get("source_labyrinth", LABYRINTH_AUTO))
            target_labyrinth = str(spec.get("target_labyrinth", LABYRINTH_AUTO))
            topology_mode = str(spec.get("topology", TRANSITION_TOPOLOGY_SAME_SIDE))
            effective_source_part = skeletal_part_for_labyrinth(source_part, source_labyrinth)
            effective_target_part = skeletal_part_for_labyrinth(target_part, target_labyrinth)
            
            source_material = material_from_field(
                source_field,
                offset_field,
                effective_source_part,
                str(spec.get("source_surface", "")),
            )
            target_material = material_from_field(
                target_field,
                offset_field,
                effective_target_part,
                str(spec.get("target_surface", "")),
            )
            
            if blend_mode == TRANSITION_BLEND_SIGMOID:
                blended_material = ((1.0 - t) * source_material + t * target_material)
            elif blend_mode == TRANSITION_BLEND_NORMALIZED_SUM:
                k = float(spec.get("correction_factor", 0.0))
                w1 = 1.0 - t
                w2 = t
                norm = np.sqrt(w1**2 + w2**2)
                W1 = np.divide(w1, norm, out=np.zeros_like(w1), where=norm > 1e-12)
                W2 = np.divide(w2, norm, out=np.zeros_like(w2), where=norm > 1e-12)
                
                C1 = 1.0 + k * (1.0 - (2.0 * W1 - 1.0)**2)
                C2 = 1.0 + k * (1.0 - (2.0 * W2 - 1.0)**2)
                
                def adjust_offset_asli(off, part_name, corr):
                    if _is_skeletal_part(part_name):
                        return off / corr
                    return off * corr
                    
                source_material_adj = material_from_field(
                    source_field,
                    adjust_offset_asli(offset_field, effective_source_part, C1),
                    effective_source_part,
                    str(spec.get("source_surface", "")),
                )
                target_material_adj = material_from_field(
                    target_field,
                    adjust_offset_asli(offset_field, effective_target_part, C2),
                    effective_target_part,
                    str(spec.get("target_surface", "")),
                )
                blended_material = W1 * source_material_adj + W2 * target_material_adj
            else:
                blended_material = transition_material_from_parts(
                    source_field,
                    target_field,
                    offset_field,
                    t,
                    effective_source_part,
                    effective_target_part,
                    str(spec.get("source_surface", "")),
                    str(spec.get("target_surface", "")),
                )
                if blended_material is None:
                    blended_material = ((1.0 - t) * source_material + t * target_material)
                    
            bridge_material = cross_labyrinth_bridge_material(
                source_field,
                target_field,
                offset_field,
                t,
                source_part,
                target_part,
                source_labyrinth,
                target_labyrinth,
                topology_mode,
                str(spec.get("source_surface", "")),
                str(spec.get("target_surface", "")),
            )
            if bridge_material is not None:
                blended_material = np.maximum(blended_material, bridge_material)
                
            material_field[blend_mask] = blended_material[blend_mask]
        except Exception as exc:
            App.Console.PrintWarning("Failed to apply face transition material: {}\n".format(exc))

    for spec in list(edge_transition_specs or []):
        blend_radius = float(spec.get("blend_radius", 5.0))
        edge_points = spec.get("edge_points", [])
        if not edge_points or blend_radius <= 0.0:
            continue
        adj_specs = spec.get("adjacent_regions", [])
        if len(adj_specs) < 2:
            continue
        
        adj_indices = [int(r["index"]) for r in adj_specs]
        transition_mask = np.isin(region_index, adj_indices)
        if not np.any(transition_mask):
            continue
            
        try:
            # 1. Compute Euclidean distance from each voxel to the transition edge
            distance = _edge_transition_distance(edge_points)
            
            # Define the cylindrical region of influence
            blend_mask = transition_mask & (distance <= blend_radius)
            if not np.any(blend_mask):
                App.Console.PrintMessage("[EDGE-DBG] blend_mask is EMPTY, skipping\n")
                continue
            
            App.Console.PrintMessage("[EDGE-DBG] Phase2: blend_mask has {} voxels (of {} total)\n".format(int(np.sum(blend_mask)), blend_mask.size))
            App.Console.PrintMessage("[EDGE-DBG] adj_indices={}, transition_mask has {} voxels\n".format(adj_indices, int(np.sum(transition_mask))))
            App.Console.PrintMessage("[EDGE-DBG] distance range in blend: {:.4f} to {:.4f}\n".format(float(np.min(distance[blend_mask])), float(np.max(distance[blend_mask]))))
                
            # 2. Compute N-way regional blending weights and the radial blend coordinate
            blend_mode = str(spec.get("blend", TRANSITION_BLEND_THRESHOLD))
            weights, u = _edge_transition_weights(adj_specs, distance, blend_radius, blend_mode)
            
            # 3. Capture pre-existing background material (includes face transitions)
            bg_material = material_field.copy()
            
            # 4. Perform N-Way Interval Boundary Blending: We blend the lower and upper bounds of 
            # each adjacent region, then construct the blended material field from 
            # the already-blended Phase 1 field and these blended bounds.
            blended_lower = np.zeros(material_field.shape, dtype=float)
            blended_upper = np.zeros(material_field.shape, dtype=float)
            for r_spec, w_k in weights:
                r_field = evaluated_field(r_spec, "equation", "base_density")
                r_part = str(r_spec.get("part", part))
                r_surface = str(r_spec.get("surface", ""))
                
                limit = max(
                    float(np.nanmax(np.abs(r_field))) if r_field.size else 1.0,
                    float(np.nanmax(np.abs(offset_field))) if offset_field.size else 1.0,
                    1.0,
                ) + 1.0
                
                if r_surface == SURFACE_EMPTY:
                    r_lower = np.full(field.shape, limit, dtype=float)
                    r_upper = np.full(field.shape, -limit, dtype=float)
                elif r_surface == SURFACE_SOLID_FILL:
                    r_lower = np.full(field.shape, -limit, dtype=float)
                    r_upper = np.full(field.shape, limit, dtype=float)
                else:
                    r_lower, r_upper = interval_bounds_for_part(r_field, offset_field, r_part)
                    if r_lower is None or r_upper is None:
                        r_lower = np.full(field.shape, limit, dtype=float)
                        r_upper = np.full(field.shape, -limit, dtype=float)
                        
                blended_lower += w_k * r_lower
                blended_upper += w_k * r_upper
                
            blended_material = np.minimum(field - blended_lower, blended_upper - field)
            
            # 5. Hierarchical Background Blending: smoothly merge edge material with background
            # w_edge=1 at edge center (d=0), w_edge=0 at cylinder boundary (d=R)
            w_edge = 1.0 - u
            final_material = w_edge * blended_material + (1.0 - w_edge) * bg_material
            
            delta = final_material - bg_material
            App.Console.PrintMessage("[EDGE-DBG] u range in blend: {:.4f} to {:.4f}\n".format(float(np.min(u[blend_mask])), float(np.max(u[blend_mask]))))
            App.Console.PrintMessage("[EDGE-DBG] w_edge range in blend: {:.4f} to {:.4f}\n".format(float(np.min(w_edge[blend_mask])), float(np.max(w_edge[blend_mask]))))
            App.Console.PrintMessage("[EDGE-DBG] bg_material in blend: min={:.4f} max={:.4f} mean={:.4f}\n".format(
                float(np.min(bg_material[blend_mask])), float(np.max(bg_material[blend_mask])), float(np.mean(bg_material[blend_mask]))))
            App.Console.PrintMessage("[EDGE-DBG] blended_material in blend: min={:.4f} max={:.4f} mean={:.4f}\n".format(
                float(np.min(blended_material[blend_mask])), float(np.max(blended_material[blend_mask])), float(np.mean(blended_material[blend_mask]))))
            App.Console.PrintMessage("[EDGE-DBG] final_material in blend: min={:.4f} max={:.4f} mean={:.4f}\n".format(
                float(np.min(final_material[blend_mask])), float(np.max(final_material[blend_mask])), float(np.mean(final_material[blend_mask]))))
            App.Console.PrintMessage("[EDGE-DBG] delta (final-bg) in blend: min={:.6f} max={:.6f} absmax={:.6f}\n".format(
                float(np.min(delta[blend_mask])), float(np.max(delta[blend_mask])), float(np.max(np.abs(delta[blend_mask])))))  
            App.Console.PrintMessage("[EDGE-DBG] non-zero delta voxels: {} of {}\n".format(
                int(np.sum(np.abs(delta[blend_mask]) > 1e-10)), int(np.sum(blend_mask))))
            # Sign change analysis: determines actual mesh geometry changes
            bg_pos = bg_material[blend_mask] >= 0
            final_pos = final_material[blend_mask] >= 0
            pos_to_neg = int(np.sum(bg_pos & ~final_pos))  # solid becomes void
            neg_to_pos = int(np.sum(~bg_pos & final_pos))  # void becomes solid
            App.Console.PrintMessage("[EDGE-DBG] SIGN CHANGES: pos->neg (solid->void)={}, neg->pos (void->solid)={}\n".format(pos_to_neg, neg_to_pos))
            # Count voxels near the zero-crossing in the blend zone
            near_zero_bg = int(np.sum(np.abs(bg_material[blend_mask]) < 0.1))
            near_zero_final = int(np.sum(np.abs(final_material[blend_mask]) < 0.1))
            App.Console.PrintMessage("[EDGE-DBG] voxels near zero-crossing: bg={}, final={}\n".format(near_zero_bg, near_zero_final))
                
            material_field[blend_mask] = final_material[blend_mask]
        except Exception as exc:
            App.Console.PrintWarning("Failed to apply edge transition in Phase 2: {}\n".format(exc))

    grid["surface"] = field.ravel(order="F")
    grid["lower_surface"] = (field + 0.5 * offset_field).ravel(order="F")
    grid["upper_surface"] = (field - 0.5 * offset_field).ravel(order="F")
    grid["material"] = material_field.ravel(order="F")
    has_boundary = _add_boundary_field(grid, wx, wy, wz, boundary_mode, boundary_object, sampling)
    surface = _extract_part_polydata(grid, part, has_boundary, add_caps, material_scalars="material")
    if ring_map is not None:
        radius, period, map_origin, rotation_matrix = ring_map
        surface = _remove_periodic_axis_caps(surface, period)
        surface = _stitch_periodic_axis_edges(surface, period)
        surface = _map_ring_polydata_to_world(surface, radius, period, map_origin, rotation_matrix)
    return surface


def _make_hybrid_cylindrical_ring_grid(
    boundary_object,
    cell_size,
    resolution,
    phase,
    origin,
    origin_rotation,
    ring_angular_cells,
    density_mode,
    base_density,
    density_controls,
    density_count_mode,
    density_gradient,
    boundary_mode,
    sampling,
    offset,
    grading_resolution,
    harmonic_boundary_condition,
):
    shell = _cylindrical_shell_from_boundary_object(boundary_object)
    if shell is None:
        return None
    shell_center, shell_axis, outer_radius, inner_radius, hmin, hmax = shell
    shell_center = np.asarray(shell_center, dtype=float)
    shell_axis = np.asarray(shell_axis, dtype=float)
    shell_axis = shell_axis / max(float(np.linalg.norm(shell_axis)), 1e-12)

    if origin is None:
        origin = shell_center
    origin = np.asarray(origin, dtype=float)

    rotation_matrix = _rotation_matrix(origin_rotation, boundary_object)
    if rotation_matrix is None:
        z_axis = np.array((0.0, 0.0, 1.0), dtype=float)
        if abs(abs(float(np.dot(shell_axis, z_axis))) - 1.0) > 1e-6:
            return None

    cell_size = np.asarray(cell_size, dtype=float)
    phase = np.asarray(phase, dtype=float)
    inner_radius = max(0.0, float(inner_radius))
    outer_radius = max(inner_radius + 1e-9, float(outer_radius))
    height = max(float(hmax) - float(hmin), 1e-9)
    radius = inner_radius + 0.5 * (outer_radius - inner_radius)
    angular_cells = max(1, int(ring_angular_cells))
    period = float(cell_size[0]) * float(angular_cells)
    radial_spacing = max(float(cell_size[1]), 1e-9) / max(int(resolution), 1)
    height_spacing = max(float(cell_size[2]), 1e-9) / max(int(resolution), 1)
    nu = int(resolution) * angular_cells + 1

    u_coords = _make_axis(0.0, period, nu)
    radial_coords = _make_aligned_axis(inner_radius, outer_radius, radial_spacing, 0.0)
    h_coords = _make_aligned_axis(float(hmin), float(hmax), height_spacing, 0.0)
    v_coords = radial_coords - radius
    u, v, h = np.meshgrid(u_coords, v_coords, h_coords, indexing="ij")
    local_x, local_y, local_z = _cylindrical_ring_local_arrays(u, v, h, radius, period)
    if rotation_matrix is not None:
        wx, wy, wz = _origin_frame_to_world_arrays(rotation_matrix, local_x, local_y, local_z, origin)
    else:
        wx = local_x + origin[0]
        wy = local_y + origin[1]
        wz = local_z + origin[2]

    grid = pv.ImageData(
        dimensions=(len(u_coords), len(v_coords), len(h_coords)),
        spacing=(
            float(u_coords[1] - u_coords[0]) if len(u_coords) > 1 else 1.0,
            float(v_coords[1] - v_coords[0]) if len(v_coords) > 1 else 1.0,
            float(h_coords[1] - h_coords[0]) if len(h_coords) > 1 else 1.0,
        ),
        origin=(0.0, float(v_coords[0]), float(h_coords[0])),
    )

    density = _density_multiplier(wx, wy, wz, density_mode, base_density, density_controls)
    if str(density_mode) == "Non-uniform" and str(density_gradient) == GRADIENT_HARMONIC and density_controls:
        density = _harmonic_interpolated_field(
            wx,
            wy,
            wz,
            boundary_mode,
            boundary_object,
            sampling,
            density_controls,
            max(0.05, float(base_density)),
            "density",
            minimum=0.05,
            grading_resolution=grading_resolution,
            harmonic_boundary_condition=harmonic_boundary_condition,
        )
    radial_position = radius + v
    px = u + phase[0]
    py = (radial_position + phase[1]) * density
    pz = (h + phase[2]) * density
    offset_field = _offset_field(
        wx,
        wy,
        wz,
        float(offset),
        "Uniform",
        None,
        GRADIENT_FACE_DISTANCE,
        boundary_mode,
        boundary_object,
        sampling,
        grading_resolution,
        harmonic_boundary_condition,
    )
    kx, ky, kz = [2.0 * math.pi / max(float(cell_size[i]), 1e-9) for i in range(3)]
    ring_map = (radius, period, origin, rotation_matrix)
    return grid, kx * px, ky * py, kz * pz, offset_field, wx, wy, wz, ring_map


def generate_cylindrical_ring_polydata(
    equation,
    part=PART_SHEET,
    cell_size=(10.0, 10.0, 10.0),
    resolution=16,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
    add_caps=True,
    origin=None,
    origin_rotation=None,
    ring_radius=2.0,
    ring_outer_radius=5.0,
    ring_height=10.0,
    ring_angular_cells=8,
    density_mode="Uniform",
    base_density=1.0,
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    density_offset_mode="Uniform",
    density_offset_value=0.3,
    density_offset_controls=None,
    density_offset_gradient=GRADIENT_FACE_DISTANCE,
    equation_blend_controls=None,
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    configure_vtk_smp()
    cell_size = np.asarray(cell_size, dtype=float)
    phase = np.asarray(phase, dtype=float)
    if origin is None:
        origin = _default_origin(boundary_mode, boundary_object)
    origin = np.asarray(origin, dtype=float)

    inner_radius = max(float(ring_radius), 1e-9)
    outer_radius = max(float(ring_outer_radius), inner_radius + 1e-9)
    radial_thickness = outer_radius - inner_radius
    radius = inner_radius + 0.5 * radial_thickness
    height = max(float(ring_height), 1e-9)
    angular_cells = max(1, int(ring_angular_cells))
    period = float(cell_size[0]) * float(angular_cells)
    angular_cell_size = max(float(cell_size[0]), 1e-9)
    radial_cell_size = max(float(cell_size[1]), 1e-9)
    height_cell_size = max(float(cell_size[2]), 1e-9)
    radial_spacing = radial_cell_size / max(int(resolution), 1)
    height_spacing = height_cell_size / max(int(resolution), 1)

    nu = int(resolution) * angular_cells + 1

    u_coords = _make_axis(0.0, period, nu)
    radial_coords = _make_aligned_axis(inner_radius, outer_radius, radial_spacing, 0.0)
    h_coords = _make_aligned_axis(0.0, height, height_spacing, 0.0)
    v_coords = radial_coords - radius
    nv = len(v_coords)
    nw = len(h_coords)
    u, v, h = np.meshgrid(u_coords, v_coords, h_coords, indexing="ij")

    local_x, local_y, local_z = _cylindrical_ring_local_arrays(u, v, h, radius, period)
    rotation_matrix = _rotation_matrix(origin_rotation)
    if rotation_matrix is not None:
        wx, wy, wz = _origin_frame_to_world_arrays(rotation_matrix, local_x, local_y, local_z, origin)
    else:
        wx = local_x + origin[0]
        wy = local_y + origin[1]
        wz = local_z + origin[2]

    grid = pv.ImageData(
        dimensions=(nu, nv, nw),
        spacing=(
            float(u_coords[1] - u_coords[0]) if len(u_coords) > 1 else 1.0,
            float(v_coords[1] - v_coords[0]) if len(v_coords) > 1 else 1.0,
            float(h_coords[1] - h_coords[0]) if len(h_coords) > 1 else 1.0,
        ),
        origin=(0.0, float(v_coords[0]), float(h_coords[0])),
    )

    ring_cell_size = (angular_cell_size, radial_cell_size, height_cell_size)
    density = _density_multiplier(
        wx,
        wy,
        wz,
        density_mode,
        base_density,
        density_controls,
    )
    if str(density_mode) == "Non-uniform" and str(density_gradient) == GRADIENT_HARMONIC and density_controls:
        density = _harmonic_interpolated_field(
            wx,
            wy,
            wz,
            BOUNDARY_BOX,
            None,
            0.0,
            density_controls,
            max(0.05, float(base_density)),
            "density",
            minimum=0.05,
            grading_resolution=0,
            harmonic_boundary_condition=harmonic_boundary_condition,
        )
    radial_position = radius + v
    px = u + phase[0]
    py = (radial_position + phase[1]) * density
    pz = (h + phase[2]) * density
    offset_field = _offset_field(
        wx,
        wy,
        wz,
        float(density_offset_value),
        density_offset_mode,
        density_offset_controls,
        density_offset_gradient,
        BOUNDARY_BOX,
        None,
        0.0,
        grading_resolution,
        harmonic_boundary_condition,
    )
    kx, ky, kz = [2.0 * math.pi / max(ring_cell_size[i], 1e-9) for i in range(3)]
    field = np.asarray(evaluate_equation(equation, kx * px, ky * py, kz * pz), dtype=float)
    if field.shape == ():
        field = np.full(u.shape, float(field))
    field = _blend_equation_field(field, kx * px, ky * py, kz * pz, wx, wy, wz, equation_blend_controls)
    if offset_field.shape != field.shape:
        offset_field = np.full(field.shape, float(density_offset_value), dtype=float)

    radial_position = radius + v
    boundary = np.minimum.reduce(
        (
            radial_position - inner_radius,
            outer_radius - radial_position,
            h,
            height - h,
        )
    )
    clip_boundary = _boundary_field(boundary_mode, boundary_object, wx, wy, wz, sampling)
    if clip_boundary is not None:
        boundary = np.minimum(boundary, clip_boundary)
    grid["surface"] = field.ravel(order="F")
    grid["lower_surface"] = (field + 0.5 * offset_field).ravel(order="F")
    grid["upper_surface"] = (field - 0.5 * offset_field).ravel(order="F")
    grid["boundary"] = boundary.ravel(order="F")
    surface = _extract_part_polydata(grid, part, True, add_caps)

    surface = _remove_periodic_axis_caps(surface, period)
    surface = _stitch_periodic_axis_edges(surface, period)
    return _map_ring_polydata_to_world(surface, radius, period, origin, rotation_matrix)


def _cylindrical_ring_local_arrays(u, v, h, radius, circumference):
    theta = 2.0 * math.pi * u / max(float(circumference), 1e-12)
    radial = float(radius) + v
    return radial * np.cos(theta), radial * np.sin(theta), h


def _origin_frame_to_world_arrays(rotation_matrix, lx, ly, lz, origin):
    wx = rotation_matrix[0, 0] * lx + rotation_matrix[0, 1] * ly + rotation_matrix[0, 2] * lz + origin[0]
    wy = rotation_matrix[1, 0] * lx + rotation_matrix[1, 1] * ly + rotation_matrix[1, 2] * lz + origin[1]
    wz = rotation_matrix[2, 0] * lx + rotation_matrix[2, 1] * ly + rotation_matrix[2, 2] * lz + origin[2]
    return wx, wy, wz


def _remove_periodic_axis_caps(polydata, period):
    polydata = polydata.triangulate()
    faces = np.asarray(polydata.faces, dtype=np.int64)
    if len(faces) == 0:
        return polydata
    face_matrix = faces.reshape((-1, 4))
    triangles = face_matrix[face_matrix[:, 0] == 3, 1:4]
    points = np.asarray(polydata.points, dtype=float)
    tolerance = max(float(period) * 1e-8, 1e-8)
    lower = points[triangles, 0] <= tolerance
    upper = points[triangles, 0] >= float(period) - tolerance
    keep = ~(np.all(lower, axis=1) | np.all(upper, axis=1))
    if np.all(keep):
        return polydata
    kept = triangles[keep]
    if len(kept) == 0:
        return polydata
    new_faces = np.empty(len(kept) * 4, dtype=np.int64)
    new_faces[0::4] = 3
    new_faces.reshape((-1, 4))[:, 1:4] = kept
    result = pv.PolyData(points.copy(), new_faces)
    for name, values in polydata.point_data.items():
        result.point_data[name] = values
    return result.clean().triangulate()


def _stitch_periodic_axis_edges(polydata, period):
    polydata = polydata.triangulate()
    faces = np.asarray(polydata.faces, dtype=np.int64)
    if len(faces) == 0:
        return polydata
    face_matrix = faces.reshape((-1, 4))
    triangles = face_matrix[face_matrix[:, 0] == 3, 1:4].copy()
    points = np.asarray(polydata.points, dtype=float)
    tolerance = max(float(period) * 1e-8, 1e-8)
    lower_indices = np.flatnonzero(points[:, 0] <= tolerance)
    upper_indices = np.flatnonzero(points[:, 0] >= float(period) - tolerance)
    if len(lower_indices) == 0 or len(upper_indices) == 0:
        return polydata

    key_scale = 1.0 / tolerance

    def seam_key(point):
        return (int(round(float(point[1]) * key_scale)), int(round(float(point[2]) * key_scale)))

    lower_by_key = {seam_key(points[index]): int(index) for index in lower_indices}
    replacements = {}
    for index in upper_indices:
        lower_index = lower_by_key.get(seam_key(points[index]))
        if lower_index is not None:
            replacements[int(index)] = lower_index
    if not replacements:
        return polydata

    remapped = triangles.copy()
    for source, target in replacements.items():
        remapped[remapped == source] = target
    keep = (
        (remapped[:, 0] != remapped[:, 1])
        & (remapped[:, 1] != remapped[:, 2])
        & (remapped[:, 2] != remapped[:, 0])
    )
    remapped = remapped[keep]
    if len(remapped) == 0:
        return polydata

    new_faces = np.empty(len(remapped) * 4, dtype=np.int64)
    new_faces[0::4] = 3
    new_faces.reshape((-1, 4))[:, 1:4] = remapped
    result = pv.PolyData(points.copy(), new_faces)
    for name, values in polydata.point_data.items():
        result.point_data[name] = values
    return result.clean(tolerance=tolerance).triangulate()


def _map_ring_polydata_to_world(polydata, radius, circumference, origin, rotation_matrix=None):
    points = np.asarray(polydata.points, dtype=float)
    local_x, local_y, local_z = _cylindrical_ring_local_arrays(
        points[:, 0],
        points[:, 1],
        points[:, 2],
        radius,
        circumference,
    )
    if rotation_matrix is not None:
        wx, wy, wz = _origin_frame_to_world_arrays(rotation_matrix, local_x, local_y, local_z, origin)
    else:
        wx = local_x + origin[0]
        wy = local_y + origin[1]
        wz = local_z + origin[2]
    mapped = polydata.copy(deep=True)
    mapped.points = np.column_stack((wx, wy, wz))
    return mapped.clean(tolerance=max(float(radius) * 1e-8, 1e-8)).triangulate()


def polydata_to_freecad_mesh(polydata):
    polydata = polydata.triangulate().clean()
    if polydata.n_cells == 0:
        raise ValueError("Generated TPMS mesh is empty")
        
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp_name = tmp.name
    try:
        # Write binary STL using PyVista's extremely fast C++ writer
        polydata.save(tmp_name, binary=True)
        # Read using FreeCAD's extremely fast C++ reader
        mesh = Mesh.Mesh()
        mesh.read(tmp_name)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
            
    try:
        mesh.harmonizeNormals()
    except Exception:
        pass
    return mesh


def relax_polydata_lloyd(polydata, iterations=5, skip_boundary=True, relax_cap_surface=False):
    iterations = max(0, int(iterations))
    if iterations == 0 or polydata.n_points == 0:
        return polydata

    relaxed = polydata.triangulate().copy(deep=True)
    faces = np.asarray(relaxed.faces, dtype=np.int64)
    if len(faces) == 0:
        return relaxed

    face_matrix = faces.reshape((-1, 4))
    triangles = face_matrix[face_matrix[:, 0] == 3, 1:4]
    if len(triangles) == 0:
        return relaxed

    points = np.asarray(relaxed.points, dtype=float).copy()
    fixed = _relax_fixed_vertices(relaxed, relax_cap_surface) if skip_boundary else np.zeros(len(points), dtype=bool)
    cap = _cap_vertices(relaxed) if skip_boundary and relax_cap_surface else np.zeros(len(points), dtype=bool)
    cap_movable = cap & ~fixed
    cap_origin = points.copy()
    cap_normals = _cap_vertex_normals(relaxed, triangles, cap) if np.any(cap_movable) else None

    edges = np.vstack(
        (
            triangles[:, [0, 1]],
            triangles[:, [1, 2]],
            triangles[:, [2, 0]],
        )
    )
    edges = np.vstack((edges, edges[:, ::-1]))
    source = edges[:, 0]
    target = edges[:, 1]
    counts = np.bincount(source, minlength=len(points)).astype(float)
    movable = (~fixed) & (counts > 0) & (~cap_movable)

    cap_source = cap_target = cap_counts = None
    if np.any(cap_movable):
        cap_face_mask = cap[triangles].all(axis=1)
        cap_triangles = triangles[cap_face_mask]
        if len(cap_triangles):
            cap_edges = np.vstack(
                (
                    cap_triangles[:, [0, 1]],
                    cap_triangles[:, [1, 2]],
                    cap_triangles[:, [2, 0]],
                )
            )
            cap_edges = np.vstack((cap_edges, cap_edges[:, ::-1]))
            cap_source = cap_edges[:, 0]
            cap_target = cap_edges[:, 1]
            cap_counts = np.bincount(cap_source, minlength=len(points)).astype(float)
        else:
            cap_movable[:] = False

    for iteration in range(iterations):
        sums = np.zeros_like(points)
        np.add.at(sums, source, points[target])
        averages = points.copy()
        averages[movable] = sums[movable] / counts[movable, None]
        points[movable] = averages[movable]
        if iteration == 0 and cap_normals is not None and np.any(cap_movable):
            cap_sums = np.zeros_like(points)
            np.add.at(cap_sums, cap_source, points[cap_target])
            cap_valid = cap_movable & (cap_counts > 0)
            points[cap_valid] = cap_sums[cap_valid] / cap_counts[cap_valid, None]
            displacement = points[cap_movable] - cap_origin[cap_movable]
            normals = cap_normals[cap_movable]
            normal_part = np.sum(displacement * normals, axis=1)[:, None] * normals
            points[cap_movable] = cap_origin[cap_movable] + displacement - normal_part

    relaxed.points = points
    return relaxed


def _relax_fixed_vertices(polydata, relax_cap_surface=False):
    points = np.asarray(polydata.points, dtype=float)
    fixed = np.zeros(polydata.n_points, dtype=bool)

    cap = _cap_vertices(polydata)
    if np.any(cap):
        if relax_cap_surface:
            fixed |= _cap_seam_vertices(polydata, cap)
        else:
            fixed |= cap

    if not np.any(fixed):
        bounds = polydata.bounds
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 1.0)
        tolerance = span * 1e-7
        fixed |= np.isclose(points[:, 0], bounds[0], atol=tolerance)
        fixed |= np.isclose(points[:, 0], bounds[1], atol=tolerance)
        fixed |= np.isclose(points[:, 1], bounds[2], atol=tolerance)
        fixed |= np.isclose(points[:, 1], bounds[3], atol=tolerance)
        fixed |= np.isclose(points[:, 2], bounds[4], atol=tolerance)
        fixed |= np.isclose(points[:, 2], bounds[5], atol=tolerance)

    return fixed


def _cap_vertices(polydata):
    if "boundary" not in polydata.point_data:
        return np.zeros(polydata.n_points, dtype=bool)
    boundary = np.asarray(polydata.point_data["boundary"], dtype=float)
    finite_boundary = boundary[np.isfinite(boundary)]
    if not len(finite_boundary):
        return np.zeros(polydata.n_points, dtype=bool)
    scale = max(float(np.max(np.abs(finite_boundary))), 1.0)
    return np.abs(boundary) <= max(scale * 1e-6, 1e-9)


def _cap_seam_vertices(polydata, cap):
    candidates = []
    for name in ("upper_surface", "lower_surface", "surface"):
        if name not in polydata.point_data:
            continue
        values = np.asarray(polydata.point_data[name], dtype=float)
        finite_values = values[np.isfinite(values)]
        if not len(finite_values):
            continue
        scale = max(float(np.max(np.abs(finite_values))), 1.0)
        candidates.append(np.abs(values) <= max(scale * 1e-6, 1e-9))

    if not candidates:
        return cap
    seam = np.zeros(polydata.n_points, dtype=bool)
    for candidate in candidates:
        seam |= cap & candidate
    return seam


def _cap_vertex_normals(polydata, triangles, cap):
    points = np.asarray(polydata.points, dtype=float)
    normals = np.zeros_like(points)
    cap_faces = cap[triangles].all(axis=1)
    for triangle in triangles[cap_faces]:
        a, b, c = points[triangle]
        normal = np.cross(b - a, c - a)
        length = np.linalg.norm(normal)
        if length <= 1e-12:
            continue
        normal = normal / length
        normals[triangle] += normal

    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.array((0.0, 0.0, 1.0))
    return normals


def _prepare_polydata(
    polydata,
    mesh_relaxation=False,
    relax_iterations=1,
    relax_skip_boundary=True,
    relax_cap_surface=False,
):
    if mesh_relaxation:
        return relax_polydata_lloyd(polydata, relax_iterations, relax_skip_boundary, relax_cap_surface)
    return polydata


def _prepare_freecad_mesh(
    polydata,
    mesh_relaxation=False,
    relax_iterations=1,
    relax_skip_boundary=True,
    relax_cap_surface=False,
    require_closed=False,
):
    prepared = _prepare_polydata(polydata, mesh_relaxation, relax_iterations, relax_skip_boundary, relax_cap_surface)
    mesh = polydata_to_freecad_mesh(prepared)
    if (
        require_closed
        and mesh_relaxation
        and relax_skip_boundary
        and relax_cap_surface
        and not mesh.isSolid()
    ):
        App.Console.PrintWarning("Cap relaxation did not preserve a closed mesh; keeping cap vertices fixed.\n")
        prepared = relax_polydata_lloyd(polydata, relax_iterations, relax_skip_boundary, False)
        mesh = polydata_to_freecad_mesh(prepared)
    return mesh


def translated_copy_mesh(mesh, offset):
    copied = mesh.copy()
    copied.translate(float(offset[0]), float(offset[1]), float(offset[2]))
    return copied


def generate_freecad_mesh(
    equation,
    part=PART_SHEET,
    cell_size=(10.0, 10.0, 10.0),
    repeat_cell=(1, 1, 1),
    resolution=16,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
    mesh_stitching=False,
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    add_caps=True,
    mesh_relaxation=False,
    relax_iterations=1,
    relax_skip_boundary=True,
    relax_cap_surface=False,
    origin=None,
    origin_rotation=None,
    density_mode="Uniform",
    base_density=1.0,
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    density_offset_mode="Uniform",
    density_offset_value=0.3,
    density_offset_controls=None,
    density_offset_gradient=GRADIENT_FACE_DISTANCE,
    equation_blend_controls=None,
    coordinate_mode=COORDINATE_CARTESIAN,
    ring_radius=2.0,
    ring_outer_radius=5.0,
    ring_height=10.0,
    ring_angular_cells=8,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
):
    repeat_cell = tuple(max(1, int(value)) for value in repeat_cell)
    cell_size = tuple(float(value) for value in cell_size)

    if str(coordinate_mode) == COORDINATE_CYLINDRICAL_RING:
        polydata = generate_cylindrical_ring_polydata(
            equation,
            part,
            cell_size,
            resolution,
            offset,
            phase,
            add_caps,
            origin,
            origin_rotation,
            ring_radius,
            ring_outer_radius,
            ring_height,
            ring_angular_cells,
            density_mode,
            base_density,
            density_controls,
            density_count_mode,
            density_gradient,
            density_offset_mode,
            density_offset_value,
            density_offset_controls,
            density_offset_gradient,
            equation_blend_controls,
            boundary_mode=boundary_mode,
            boundary_object=boundary_object,
            sampling=sampling,
            grading_resolution=grading_resolution,
            harmonic_boundary_condition=harmonic_boundary_condition,
        )
        return _prepare_freecad_mesh(
            polydata,
            mesh_relaxation,
            relax_iterations,
            relax_skip_boundary,
            relax_cap_surface,
            add_caps,
        )

    if mesh_stitching:
        polydata = generate_polydata(
            equation,
            part,
            cell_size,
            repeat_cell,
            resolution,
            offset,
            phase,
            boundary_mode,
            boundary_object,
            sampling,
            add_caps,
            origin,
            origin_rotation,
            density_mode,
            base_density,
            density_controls,
            density_count_mode,
            density_gradient,
            density_offset_mode,
            density_offset_value,
            density_offset_controls,
            density_offset_gradient,
            equation_blend_controls,
            grading_resolution,
            harmonic_boundary_condition,
        )
        return _prepare_freecad_mesh(
            polydata,
            mesh_relaxation,
            relax_iterations,
            relax_skip_boundary,
            relax_cap_surface,
            add_caps,
        )

    if boundary_mode != BOUNDARY_BOX:
        polydata = generate_polydata(
            equation,
            part,
            cell_size,
            repeat_cell,
            resolution,
            offset,
            phase,
            boundary_mode,
            boundary_object,
            sampling,
            add_caps,
            origin,
            origin_rotation,
            density_mode,
            base_density,
            density_controls,
            density_count_mode,
            density_gradient,
            density_offset_mode,
            density_offset_value,
            density_offset_controls,
            density_offset_gradient,
            equation_blend_controls,
            grading_resolution,
            harmonic_boundary_condition,
        )
        mesh = _prepare_freecad_mesh(
            polydata,
            mesh_relaxation,
            relax_iterations,
            relax_skip_boundary,
            relax_cap_surface,
            add_caps,
        )
        return mesh

    polydata = generate_polydata(
        equation,
        part,
        cell_size,
        (1, 1, 1),
        resolution,
        offset,
        phase,
        boundary_mode,
        boundary_object,
        sampling,
        add_caps,
        origin,
        origin_rotation,
        density_mode,
        base_density,
        density_controls,
        density_count_mode,
        density_gradient,
        density_offset_mode,
        density_offset_value,
        density_offset_controls,
        density_offset_gradient,
        equation_blend_controls,
        grading_resolution,
        harmonic_boundary_condition,
    )
    unit_mesh = _prepare_freecad_mesh(
        polydata,
        mesh_relaxation,
        relax_iterations,
        relax_skip_boundary,
        relax_cap_surface,
        add_caps,
    )
    combined = Mesh.Mesh()
    origin_shift = (
        -0.5 * cell_size[0] * (repeat_cell[0] - 1),
        -0.5 * cell_size[1] * (repeat_cell[1] - 1),
        -0.5 * cell_size[2] * (repeat_cell[2] - 1),
    )

    for ix in range(repeat_cell[0]):
        for iy in range(repeat_cell[1]):
            for iz in range(repeat_cell[2]):
                offset_vector = (
                    origin_shift[0] + ix * cell_size[0],
                    origin_shift[1] + iy * cell_size[1],
                    origin_shift[2] + iz * cell_size[2],
                )
                combined.addMesh(translated_copy_mesh(unit_mesh, offset_vector))

    try:
        combined.harmonizeNormals()
    except Exception:
        pass
    return combined


def generate_hybrid_freecad_mesh(
    equation,
    part=PART_SHEET,
    cell_size=(10.0, 10.0, 10.0),
    repeat_cell=(1, 1, 1),
    resolution=16,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
    boundary_mode=BOUNDARY_SELECTED_SOLID,
    boundary_object=None,
    sampling=0.0,
    add_caps=True,
    mesh_relaxation=False,
    relax_iterations=1,
    relax_skip_boundary=True,
    relax_cap_surface=False,
    origin=None,
    origin_rotation=None,
    base_density=1.0,
    region_specs=None,
    transition_controls=None,
    transition_region_specs=None,
    density_mode="Uniform",
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    density_offset_mode="Uniform",
    density_offset_controls=None,
    density_offset_gradient=GRADIENT_FACE_DISTANCE,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_INSULATOR,
    coordinate_mode=COORDINATE_CARTESIAN,
    ring_angular_cells=8,
    face_transition_specs=None,
    edge_transition_specs=None,
):
    polydata = generate_hybrid_polydata(
        equation,
        part,
        cell_size,
        repeat_cell,
        resolution,
        offset,
        phase,
        boundary_mode,
        boundary_object,
        sampling,
        add_caps,
        origin,
        origin_rotation,
        base_density,
        region_specs,
        transition_controls,
        transition_region_specs,
        density_mode,
        density_controls,
        density_count_mode,
        density_gradient,
        density_offset_mode,
        density_offset_controls,
        density_offset_gradient,
        grading_resolution,
        harmonic_boundary_condition,
        coordinate_mode,
        ring_angular_cells,
        face_transition_specs=face_transition_specs,
        edge_transition_specs=edge_transition_specs,
    )
    return _prepare_freecad_mesh(
        polydata,
        mesh_relaxation,
        relax_iterations,
        relax_skip_boundary,
        relax_cap_surface,
        add_caps,
    )


def add_tpms_mesh_to_document(
    equation,
    part=PART_SHEET,
    cell_size=(10.0, 10.0, 10.0),
    repeat_cell=(1, 1, 1),
    resolution=16,
    offset=0.3,
    phase=(0.0, 0.0, 0.0),
    mesh_stitching=False,
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    add_caps=True,
    mesh_relaxation=False,
    relax_iterations=1,
    relax_skip_boundary=True,
    relax_cap_surface=False,
    origin=None,
    origin_rotation=None,
    density_mode="Uniform",
    base_density=1.0,
    density_controls=None,
    density_count_mode=DENSITY_COUNT_FOLLOW,
    density_gradient=GRADIENT_FACE_DISTANCE,
    density_offset_mode="Uniform",
    density_offset_value=0.3,
    density_offset_controls=None,
    density_offset_gradient=GRADIENT_FACE_DISTANCE,
    grading_resolution=16,
    label="TPMS unit cell",
):
    if App.ActiveDocument is None:
        App.newDocument("TPMS")
    doc = App.ActiveDocument

    mesh = generate_freecad_mesh(
        equation,
        part,
        cell_size,
        repeat_cell,
        resolution,
        offset,
        phase,
        mesh_stitching,
        boundary_mode,
        boundary_object,
        sampling,
        add_caps,
        mesh_relaxation,
        relax_iterations,
        relax_skip_boundary,
        relax_cap_surface,
        origin,
        origin_rotation,
        density_mode,
        base_density,
        density_controls,
        density_count_mode,
        density_gradient,
        density_offset_mode,
        density_offset_value,
        density_offset_controls,
        density_offset_gradient,
        grading_resolution=grading_resolution,
    )

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
    obj.addProperty("App::PropertyBool", "MeshStitching", "TPMS", "Stitch repeated mesh boundaries")
    obj.addProperty("App::PropertyString", "BoundaryMode", "Boundary", "Boundary used to clip the generated TPMS")
    obj.addProperty("App::PropertyFloat", "Sampling", "Boundary", "Target grid resolution along the longest sampled axis; 0 uses Resolution")
    obj.addProperty("App::PropertyBool", "AddCaps", "Boundary", "Add caps where TPMS intersects the boundary")
    obj.addProperty("App::PropertyBool", "MeshRelaxation", "Relaxation", "Apply Lloyd-style mesh relaxation")
    obj.addProperty("App::PropertyInteger", "RelaxIterations", "Relaxation", "Lloyd-style relaxation iterations")
    obj.addProperty("App::PropertyBool", "RelaxSkipBoundary", "Relaxation", "Keep boundary/cap vertices fixed during relaxation")
    obj.addProperty("App::PropertyBool", "RelaxCapSurface", "Relaxation", "Allow cap vertices to relax tangentially while keeping seam fixed")
    obj.addProperty("App::PropertyVector", "Origin", "TPMS", "TPMS phase origin")
    obj.addProperty("App::PropertyVector", "OriginRotation", "TPMS", "TPMS origin-frame rotation in XYZ degrees")
    obj.addProperty("App::PropertyString", "DensityMode", "Grading", "Unit-cell density mode")
    obj.addProperty("App::PropertyFloat", "BaseDensity", "Grading", "Base TPMS unit-cell density multiplier")
    obj.addProperty("App::PropertyString", "DensityCountMode", "Grading", "How non-uniform unit-cell density affects total TPMS cell count")
    obj.addProperty("App::PropertyString", "DensityGradient", "Grading", "Unit-cell density source")
    obj.addProperty("App::PropertyString", "DensityOffsetMode", "Grading", "Thickness grading mode")
    obj.addProperty("App::PropertyFloat", "DensityOffsetValue", "Grading", "Target thickness for thickness grading")
    obj.addProperty("App::PropertyString", "DensityOffsetGradient", "Grading", "Thickness grading source")
    obj.addProperty("App::PropertyInteger", "GradingResolution", "Grading", "Harmonic grading grid cells along the longest axis")
    obj.ImplicitEquation = equation
    obj.TPMSPart = part
    obj.Resolution = int(resolution)
    obj.RepeatX = int(repeat_cell[0])
    obj.RepeatY = int(repeat_cell[1])
    obj.RepeatZ = int(repeat_cell[2])
    obj.Offset = float(offset)
    obj.MeshStitching = bool(mesh_stitching)
    obj.BoundaryMode = str(boundary_mode)
    obj.Sampling = float(sampling)
    obj.AddCaps = bool(add_caps)
    obj.MeshRelaxation = bool(mesh_relaxation)
    obj.RelaxIterations = int(relax_iterations)
    obj.RelaxSkipBoundary = bool(relax_skip_boundary)
    obj.RelaxCapSurface = bool(relax_cap_surface)
    obj.DensityMode = str(density_mode)
    obj.BaseDensity = float(base_density)
    obj.DensityCountMode = str(density_count_mode)
    obj.DensityGradient = str(density_gradient)
    obj.DensityOffsetMode = str(density_offset_mode)
    obj.DensityOffsetValue = float(density_offset_value)
    obj.DensityOffsetGradient = str(density_offset_gradient)
    obj.GradingResolution = int(grading_resolution)
    if origin is not None:
        obj.Origin = App.Vector(float(origin[0]), float(origin[1]), float(origin[2]))
    if origin_rotation is not None and not hasattr(origin_rotation, "toMatrix"):
        try:
            obj.OriginRotation = App.Vector(float(origin_rotation[0]), float(origin_rotation[1]), float(origin_rotation[2]))
        except Exception:
            pass
    doc.recompute()
    return obj
