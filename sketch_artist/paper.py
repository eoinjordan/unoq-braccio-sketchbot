"""Shared paper-local and arm-base coordinate transforms, in millimetres."""

from __future__ import annotations

import math


def rotate_xy(x_mm: float, y_mm: float, rotation_deg: float = 0.0):
    angle = math.radians(float(rotation_deg))
    cosine, sine = math.cos(angle), math.sin(angle)
    return x_mm * cosine - y_mm * sine, x_mm * sine + y_mm * cosine


def paper_to_world(paper: dict, x_mm: float, y_mm: float):
    return rotate_xy(float(paper["origin_x_mm"]) + x_mm,
                     float(paper["origin_y_mm"]) + y_mm,
                     float(paper.get("rotation_deg", 0.0)))


def world_to_paper(paper: dict, x_mm: float, y_mm: float):
    local_x, local_y = rotate_xy(x_mm, y_mm, -float(paper.get("rotation_deg", 0.0)))
    return local_x - float(paper["origin_x_mm"]), local_y - float(paper["origin_y_mm"])


def paper_corners(paper: dict):
    width, height = float(paper["width_mm"]), float(paper["height_mm"])
    return [paper_to_world(paper, local_x, local_y)
            for local_x, local_y in ((0, 0), (width, 0), (width, height), (0, height))]