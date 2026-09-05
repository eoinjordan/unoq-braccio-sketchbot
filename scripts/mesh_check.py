#!/usr/bin/env python3
"""Validate the printable STL parts in ``hardware/``.

Slicers silently produce junk from meshes that are not closed, not manifold, or
that contain stray shells, so the printable assets get the same treatment as
the code: a check that runs in CI.

    python scripts/mesh_check.py hardware/pencil-grip/*.stl
    python scripts/mesh_check.py --json hardware/pencil-grip/braccio_pencil_grip_8mm.stl

Also usable as a library (see ``tests/test_hardware_meshes.py``)::

    from scripts.mesh_check import inspect_stl
    report = inspect_stl("hardware/pencil-grip/braccio_pencil_grip_8mm.stl")
    assert report.is_printable
"""

from __future__ import annotations

import argparse
import json
import struct
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Vertices closer than this (mm) are treated as one vertex. OpenSCAD/CGAL
# output is exact to well under a micron, so this only welds points that are
# numerically identical.
WELD_TOL = 1e-5


def load_stl(path) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Return (triangles Nx3x3, per-facet normals Nx3 or None) from an STL."""
    data = Path(path).read_bytes()
    if data[:5].lower() == b"solid" and b"facet" in data[:2048]:
        words = data.decode("ascii", "replace").split()
        pts: List[List[float]] = []
        i = 0
        while i < len(words):
            if words[i] == "vertex":
                pts.append([float(words[i + 1]), float(words[i + 2]), float(words[i + 3])])
                i += 4
            else:
                i += 1
        return np.array(pts, float).reshape(-1, 3, 3), None

    count = struct.unpack("<I", data[80:84])[0]
    raw = np.frombuffer(data[84:84 + count * 50], dtype=np.uint8).reshape(count, 50)
    floats = raw[:, :48].copy().view("<f4").reshape(count, 4, 3).astype(np.float64)
    return floats[:, 1:, :], floats[:, 0, :]


def write_stl(path, tris: np.ndarray, normals: Optional[np.ndarray] = None) -> None:
    """Write a binary STL, recomputing facet normals when none are supplied."""
    tris = np.asarray(tris, dtype=np.float64)
    if normals is None:
        n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        length = np.linalg.norm(n, axis=1, keepdims=True)
        normals = np.divide(n, length, out=np.zeros_like(n), where=length > 0)
    header = b"binary STL written by scripts/mesh_check.py".ljust(80, b" ")
    block = np.zeros((len(tris), 12), dtype="<f4")
    block[:, 0:3] = normals
    block[:, 3:12] = tris.reshape(-1, 9)
    raw = np.zeros((len(tris), 50), dtype=np.uint8)
    raw[:, :48] = block.view(np.uint8).reshape(len(tris), 48)
    Path(path).write_bytes(header + struct.pack("<I", len(tris)) + raw.tobytes())


def write_obj(path, tris: np.ndarray) -> None:
    """Write a welded Wavefront OBJ, for slicers and viewers that prefer it."""
    verts, faces = _weld(tris)
    lines = [f"# {Path(path).name} - written by scripts/mesh_check.py"]
    lines += [f"v {x:.8f} {y:.8f} {z:.8f}" for x, y, z in verts]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


def _weld(tris: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return (unique vertices, faces as indices into them)."""
    pts = tris.reshape(-1, 3)
    decimals = max(0, int(round(-np.log10(WELD_TOL))))
    uniq, inverse = np.unique(np.round(pts, decimals), axis=0, return_inverse=True)
    return uniq, inverse.reshape(-1, 3)


def _components(vertex_count: int, faces: np.ndarray) -> np.ndarray:
    """Union-find over shared vertices, returning a component label per vertex."""
    parent = np.arange(vertex_count)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for tri in faces:
        roots = [find(int(v)) for v in tri]
        for other in roots[1:]:
            if other != roots[0]:
                parent[other] = roots[0]
    return np.array([find(i) for i in range(vertex_count)])


@dataclass
class MeshReport:
    path: str
    triangles: int
    vertices: int
    edges: int
    boundary_edges: int
    nonmanifold_edges: int
    inconsistent_windings: int
    degenerate_triangles: int
    shells: int
    size_mm: Tuple[float, float, float]
    min_mm: Tuple[float, float, float]
    max_mm: Tuple[float, float, float]
    volume_cm3: float
    area_cm2: float
    flipped_normals: Optional[int]

    @property
    def is_watertight(self) -> bool:
        return self.boundary_edges == 0 and self.nonmanifold_edges == 0

    @property
    def is_printable(self) -> bool:
        """One closed, consistently wound, positive-volume solid."""
        return (self.is_watertight
                and self.shells == 1
                and self.inconsistent_windings == 0
                and self.degenerate_triangles == 0
                and self.volume_cm3 > 0)

    def problems(self) -> List[str]:
        out: List[str] = []
        if self.boundary_edges:
            out.append(f"{self.boundary_edges} open edge(s): the mesh is not closed")
        if self.nonmanifold_edges:
            out.append(f"{self.nonmanifold_edges} non-manifold edge(s)")
        if self.inconsistent_windings:
            out.append(f"{self.inconsistent_windings} inconsistently wound edge(s)")
        if self.degenerate_triangles:
            out.append(f"{self.degenerate_triangles} zero-area triangle(s)")
        if self.shells > 1:
            out.append(f"{self.shells} disconnected shells: stray geometry the "
                       f"slicer prints as loose fragments")
        if self.volume_cm3 <= 0:
            out.append("non-positive volume: the solid is inside out")
        return out


def inspect_stl(path) -> MeshReport:
    tris, normals = load_stl(path)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cross = np.cross(b - a, c - a)
    twice_area = np.linalg.norm(cross, axis=1)

    verts, faces = _weld(tris)
    undirected: Dict[Tuple[int, int], int] = defaultdict(int)
    directed: Dict[Tuple[int, int], int] = defaultdict(int)
    for tri in faces:
        for i in range(3):
            u, v = int(tri[i]), int(tri[(i + 1) % 3])
            undirected[(min(u, v), max(u, v))] += 1
            directed[(u, v)] += 1
    counts = np.fromiter(undirected.values(), dtype=int)

    labels = _components(len(verts), faces)
    pts = tris.reshape(-1, 3)
    lo, hi = pts.min(0), pts.max(0)

    flipped: Optional[int] = None
    if normals is not None:
        norm_len = np.linalg.norm(normals, axis=1, keepdims=True)
        usable = norm_len[:, 0] > 1e-6
        if usable.any():
            geo = np.divide(cross, twice_area[:, None],
                            out=np.zeros_like(cross), where=twice_area[:, None] > 0)
            dots = np.einsum("ij,ij->i", geo[usable], normals[usable] / norm_len[usable])
            flipped = int((dots < 0).sum())

    return MeshReport(
        path=str(path),
        triangles=len(tris),
        vertices=len(verts),
        edges=len(counts),
        boundary_edges=int((counts == 1).sum()),
        nonmanifold_edges=int((counts > 2).sum()),
        inconsistent_windings=int(sum(1 for v in directed.values() if v > 1)),
        degenerate_triangles=int((twice_area < 1e-12).sum()),
        shells=int(len(np.unique(labels))),
        size_mm=tuple(round(float(v), 3) for v in (hi - lo)),
        min_mm=tuple(round(float(v), 3) for v in lo),
        max_mm=tuple(round(float(v), 3) for v in hi),
        volume_cm3=round(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0) / 1000.0, 4),
        area_cm2=round(float(twice_area.sum() / 2.0) / 100.0, 3),
        flipped_normals=flipped,
    )


def largest_shell(path) -> Tuple[np.ndarray, Optional[np.ndarray], int]:
    """Return (triangles, normals, dropped_triangles) for the biggest shell."""
    tris, normals = load_stl(path)
    verts, faces = _weld(tris)
    labels = _components(len(verts), faces)
    uniq, counts = np.unique(labels, return_counts=True)
    keep = uniq[int(np.argmax(counts))]
    mask = labels[faces[:, 0]] == keep
    return tris[mask], (None if normals is None else normals[mask]), int((~mask).sum())


def describe(report: MeshReport) -> str:
    x, y, z = report.size_mm
    lines = [
        f"{report.path}",
        f"  {report.triangles} triangles, {report.vertices} vertices, "
        f"{report.shells} shell(s)",
        f"  bounding box {x:.2f} x {y:.2f} x {z:.2f} mm  "
        f"(min {report.min_mm}, max {report.max_mm})",
        f"  volume {report.volume_cm3:.2f} cm3, surface {report.area_cm2:.2f} cm2",
        f"  watertight={report.is_watertight} printable={report.is_printable}",
    ]
    lines += [f"  ! {problem}" for problem in report.problems()]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate printable STL parts.")
    parser.add_argument("paths", nargs="+", help="STL files to inspect.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    parser.add_argument("--strip-stray-shells", action="store_true",
                        help="Rewrite each file keeping only its largest shell.")
    parser.add_argument("--write-obj", action="store_true",
                        help="Also write an .obj next to each .stl inspected.")
    parser.add_argument("--binary", action="store_true",
                        help="Rewrite each STL as binary (OpenSCAD emits ASCII).")
    args = parser.parse_args(argv)

    failures = 0
    reports = []
    for path in args.paths:
        if args.strip_stray_shells:
            tris, normals, dropped = largest_shell(path)
            if dropped:
                write_stl(path, tris, normals)
                print(f"{path}: dropped {dropped} stray triangle(s)")
            else:
                print(f"{path}: already a single shell")
        if args.binary:
            tris, normals = load_stl(path)
            before = Path(path).stat().st_size
            write_stl(path, tris, normals)
            print(f"{path}: {before // 1024} kB -> "
                  f"{Path(path).stat().st_size // 1024} kB binary STL")
        if args.write_obj:
            obj_path = Path(path).with_suffix(".obj")
            write_obj(obj_path, load_stl(path)[0])
            print(f"{obj_path}: written")
        report = inspect_stl(path)
        reports.append(report)
        if args.json:
            continue
        print(describe(report))
        if not report.is_printable:
            failures += 1

    if args.json:
        print(json.dumps([asdict(r) for r in reports], indent=2, default=list))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
