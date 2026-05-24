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


PART_SHEET = "Sheet"
PART_UPPER = "Upper skeletal"
PART_LOWER = "Lower skeletal"
PART_SURFACE = "Zero surface"

COORDINATE_CARTESIAN = "Cartesian"
COORDINATE_CYLINDRICAL_RING = "Cylindrical ring"

BOUNDARY_BOX = "Box"
BOUNDARY_SPHERE = "Sphere"
BOUNDARY_SELECTED_SOLID = "Selected solid"
DENSITY_COUNT_PRESERVE = "Preserve overall count"
DENSITY_COUNT_FOLLOW = "Follow unit cell density"
GRADIENT_FACE_DISTANCE = "Selected-face distance field"
GRADIENT_FACE_PLANE = "Face plane"
GRADIENT_HARMONIC = "Harmonic field"
HARMONIC_BOUNDARY_CONDUCTOR = "Conductor"
HARMONIC_BOUNDARY_INSULATOR = "Insulator"

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
    return list(SURFACE_EQUATIONS)


def evaluate_equation(equation, x, y, z):
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


def coordinate_modes():
    return [COORDINATE_CARTESIAN, COORDINATE_CYLINDRICAL_RING]


def _make_axis(minimum, maximum, default_count):
    count = max(2, int(default_count))
    return np.linspace(float(minimum), float(maximum), count)


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
    harmonic_boundary_condition=HARMONIC_BOUNDARY_CONDUCTOR,
):
    cell_size = np.asarray(cell_size, dtype=float)
    repeat_cell = np.asarray(repeat_cell, dtype=int)
    repeat_cell = np.maximum(repeat_cell, 1)
    phase = np.asarray(phase, dtype=float)

    if origin is None:
        origin = _default_origin(boundary_mode, boundary_object)
    phase_origin = np.asarray(origin, dtype=float)

    if boundary_mode == BOUNDARY_SELECTED_SOLID:
        bounds = _shape_bounds(boundary_object)
        fallback_spacing = min(float(value) / max(int(resolution), 1) for value in cell_size)
        spacing = max(fallback_spacing, 1e-9)
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
        default_counts = [int(math.ceil(length / spacing)) + 1 for length in lengths]

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
    harmonic_boundary_condition=HARMONIC_BOUNDARY_CONDUCTOR,
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
    harmonic_boundary_condition=HARMONIC_BOUNDARY_CONDUCTOR,
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
    harmonic_boundary_condition=HARMONIC_BOUNDARY_CONDUCTOR,
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


def _boundary_shell_mask(inside):
    mask = np.zeros(inside.shape, dtype=bool)
    for axis in range(3):
        lower = [slice(None)] * 3
        upper = [slice(None)] * 3
        lower[axis] = slice(0, -1)
        upper[axis] = slice(1, None)
        diff = inside[tuple(lower)] != inside[tuple(upper)]
        mask[tuple(lower)] |= diff
        mask[tuple(upper)] |= diff
    return mask


def _selected_boundary_field_signed_vtk(boundary_object, wx, wy, wz, sampling, fallback_resolution):
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
    shell = _boundary_shell_mask(inside)

    spacing = min(
        _axis_spacing(wx, axis=0),
        _axis_spacing(wy, axis=1),
        _axis_spacing(wz, axis=2),
    )
    field = np.where(inside, spacing, -spacing).astype(float)
    if np.any(shell):
        shell_points = np.column_stack((wx[shell], wy[shell], wz[shell]))
        signed_distance = _implicit_distances(surface, shell_points)
        field[shell] = -signed_distance
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
        field = _analytic_boundary_field(boundary_object, wx, wy, wz)
        if field is not None:
            return field
        try:
            fallback_resolution = max(wx.shape)
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


def _analytic_boundary_field(boundary_object, wx, wy, wz):
    if bool(getattr(boundary_object, "ForceTessellatedBoundary", False)):
        return None
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
            lx, ly, lz = _world_to_local_arrays(placement, wx, wy, wz)
            return _spherical_shell_field(lx, ly, lz, *sphere_shell)
        conical_shell = _conical_inner_cylindrical_shell_from_shape(boundary_object.Shape)
        if conical_shell is not None:
            lx, ly, lz = _world_to_local_arrays(placement, wx, wy, wz)
            return _conical_inner_cylindrical_shell_field(lx, ly, lz, *conical_shell)
        shell = _cylindrical_shell_from_shape(boundary_object.Shape)
        if shell is not None:
            lx, ly, lz = _world_to_local_arrays(placement, wx, wy, wz)
            return _cylindrical_shell_field(lx, ly, lz, *shell)

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


def _conical_inner_cylindrical_shell_from_shape(shape):
    if shape is None or shape.isNull():
        return None

    cylinders = []
    cones = []
    for face in shape.Faces:
        surface = face.Surface
        surface_type = type(surface).__name__
        if surface_type == "Plane":
            continue
        try:
            umin, umax, _vmin, _vmax = face.ParameterRange
        except Exception:
            return None
        if abs(abs(float(umax) - float(umin)) - 2.0 * math.pi) > 1e-5:
            return None
        if surface_type == "Cylinder" and hasattr(surface, "Radius"):
            axis = _unit_array(surface.Axis)
            if axis is None:
                return None
            cylinders.append((float(surface.Radius), _vector_array(surface.Center), axis))
        elif surface_type == "Cone" and hasattr(surface, "Radius") and hasattr(surface, "SemiAngle"):
            axis = _unit_array(surface.Axis)
            if axis is None:
                return None
            cones.append(
                (
                    float(surface.Radius),
                    float(surface.SemiAngle),
                    _vector_array(surface.Center),
                    axis,
                )
            )
        else:
            return None

    if len(cylinders) != 1 or len(cones) != 1:
        return None

    outer_radius, center, axis = cylinders[0]
    cone_radius, cone_angle, cone_center, cone_axis = cones[0]
    if outer_radius <= 1e-9:
        return None
    if abs(abs(float(np.dot(axis, cone_axis))) - 1.0) > 1e-6:
        return None
    tolerance = max(outer_radius * 1e-6, 1e-7)
    offset = cone_center - center
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

    slope = math.tan(float(cone_angle))
    test_inner = _conical_radius_at_axial(
        np.array((hmin, hmax), dtype=float),
        center,
        axis,
        cone_center,
        cone_axis,
        cone_radius,
        slope,
    )
    if np.any(test_inner < -tolerance) or np.any(test_inner >= outer_radius - tolerance):
        return None
    return (
        tuple(center),
        tuple(axis),
        float(outer_radius),
        float(hmin),
        float(hmax),
        tuple(cone_center),
        tuple(cone_axis),
        float(cone_radius),
        float(slope),
    )


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


def _conical_radius_at_axial(axial, center, axis, cone_center, cone_axis, cone_radius, slope):
    center = np.asarray(center, dtype=float)
    axis = np.asarray(axis, dtype=float)
    cone_center = np.asarray(cone_center, dtype=float)
    cone_axis = np.asarray(cone_axis, dtype=float)
    origin_projection = float(np.dot(center - cone_center, cone_axis))
    axis_projection = float(np.dot(axis, cone_axis))
    cone_axial = origin_projection + np.asarray(axial, dtype=float) * axis_projection
    return float(cone_radius) + cone_axial * float(slope)


def _conical_inner_cylindrical_shell_field(
    px,
    py,
    pz,
    center,
    axis,
    outer_radius,
    hmin,
    hmax,
    cone_center,
    cone_axis,
    cone_radius,
    cone_slope,
):
    center = np.asarray(center, dtype=float)
    axis = np.asarray(axis, dtype=float)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)

    dx = px - center[0]
    dy = py - center[1]
    dz = pz - center[2]
    axial = dx * axis[0] + dy * axis[1] + dz * axis[2]
    radial_sq = dx * dx + dy * dy + dz * dz - axial * axial
    radial = np.sqrt(np.maximum(radial_sq, 0.0))

    inner_radius = _conical_radius_at_axial(
        axial,
        center,
        axis,
        cone_center,
        np.asarray(cone_axis, dtype=float) / max(float(np.linalg.norm(cone_axis)), 1e-12),
        cone_radius,
        cone_slope,
    )
    outer_radius = max(float(outer_radius), 1e-12)
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
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_CONDUCTOR,
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

    if offset_field.shape != field.shape:
        offset_field = np.full(field.shape, float(density_offset_value), dtype=float)
    grid["surface"] = field.ravel(order="F")
    grid["lower_surface"] = (field + 0.5 * offset_field).ravel(order="F")
    grid["upper_surface"] = (field - 0.5 * offset_field).ravel(order="F")
    has_boundary = _add_boundary_field(grid, wx, wy, wz, boundary_mode, boundary_object, sampling)

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
    ring_radius=25.0,
    ring_outer_radius=35.0,
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
    boundary_mode=BOUNDARY_BOX,
    boundary_object=None,
    sampling=0.0,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_CONDUCTOR,
):
    configure_vtk_smp()
    cell_size = np.asarray(cell_size, dtype=float)
    phase = np.asarray(phase, dtype=float)
    origin = np.asarray(origin if origin is not None else (0.0, 0.0, 0.0), dtype=float)

    inner_radius = max(float(ring_radius), 1e-9)
    outer_radius = max(float(ring_outer_radius), inner_radius + 1e-9)
    radial_thickness = outer_radius - inner_radius
    radius = inner_radius + 0.5 * radial_thickness
    height = max(float(ring_height), 1e-9)
    angular_cells = max(1, int(ring_angular_cells))
    circumference = 2.0 * math.pi * radius
    angular_cell_size = circumference / float(angular_cells)
    radial_cell_size = max(float(cell_size[1]), 1e-9)
    height_cell_size = max(float(cell_size[2]), 1e-9)

    nu = int(resolution) * angular_cells + 1
    nv = max(3, int(math.ceil(radial_thickness / radial_cell_size * int(resolution))) + 1)
    nw = max(3, int(math.ceil(height / height_cell_size * int(resolution))) + 1)

    u_coords = _make_axis(0.0, circumference, nu)
    v_coords = _make_axis(-0.5 * radial_thickness, 0.5 * radial_thickness, nv)
    h_coords = _make_axis(0.0, height, nw)
    u, v, h = np.meshgrid(u_coords, v_coords, h_coords, indexing="ij")

    local_x, local_y, local_z = _cylindrical_ring_local_arrays(u, v, h, radius, circumference)
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
        origin=(0.0, -0.5 * radial_thickness, 0.0),
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
    px = u + phase[0]
    py = (v + phase[1]) * density
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
    if offset_field.shape != field.shape:
        offset_field = np.full(field.shape, float(density_offset_value), dtype=float)

    boundary = np.minimum.reduce(
        (
            v + 0.5 * radial_thickness,
            0.5 * radial_thickness - v,
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

    if not add_caps:
        surface = _generate_uncapped_polydata(grid, part, True)
    elif part == PART_SHEET:
        volume = grid.clip_scalar(scalars="upper_surface").clip_scalar(
            scalars="lower_surface",
            invert=False,
        )
        volume = _apply_boundary_clip(volume, True)
        surface = volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    elif part == PART_UPPER:
        volume = grid.clip_scalar(scalars="upper_surface", invert=False)
        volume = _apply_boundary_clip(volume, True)
        surface = volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    elif part == PART_LOWER:
        volume = grid.clip_scalar(scalars="lower_surface")
        volume = _apply_boundary_clip(volume, True)
        surface = volume.extract_surface(algorithm="dataset_surface").clean().triangulate()
    elif part == PART_SURFACE:
        surface = grid.contour(isosurfaces=[0.0], scalars="surface").extract_surface().clean().triangulate()
    else:
        raise ValueError("Unsupported TPMS part: {}".format(part))

    surface = _remove_periodic_axis_caps(surface, circumference)
    surface = _stitch_periodic_axis_edges(surface, circumference)
    return _map_ring_polydata_to_world(surface, radius, circumference, origin, rotation_matrix)


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
    faces = np.asarray(polydata.faces)
    if len(faces) == 0:
        raise ValueError("Generated TPMS mesh is empty")

    face_matrix = faces.reshape((-1, 4))
    triangles = face_matrix[face_matrix[:, 0] == 3, 1:4]
    if len(triangles) == 0:
        raise ValueError("Generated TPMS mesh has no triangular facets")

    facets = np.asarray(polydata.points, dtype=float)[triangles].tolist()
    mesh = Mesh.Mesh(facets)
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
    relax_iterations=5,
    relax_skip_boundary=True,
    relax_cap_surface=False,
):
    if mesh_relaxation:
        return relax_polydata_lloyd(polydata, relax_iterations, relax_skip_boundary, relax_cap_surface)
    return polydata


def _prepare_freecad_mesh(
    polydata,
    mesh_relaxation=False,
    relax_iterations=5,
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
    relax_iterations=5,
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
    coordinate_mode=COORDINATE_CARTESIAN,
    ring_radius=25.0,
    ring_outer_radius=35.0,
    ring_height=10.0,
    ring_angular_cells=8,
    grading_resolution=16,
    harmonic_boundary_condition=HARMONIC_BOUNDARY_CONDUCTOR,
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
    relax_iterations=5,
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
