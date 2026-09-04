"""Vectorizer: edge image -> polyline strokes."""

from __future__ import annotations

import cv2
import numpy as np

from sketch_artist.vectorize import bounding_box, strokes_from_edges


def test_strokes_from_rectangle(conf):
    edges = np.zeros((512, 512), np.uint8)
    cv2.rectangle(edges, (100, 100), (400, 400), 255, 2)
    strokes = strokes_from_edges(edges, conf["drawing"])
    assert len(strokes) >= 1
    assert all(len(s) >= 2 for s in strokes)


def test_blank_image_gives_no_strokes(conf):
    edges = np.zeros((512, 512), np.uint8)
    assert strokes_from_edges(edges, conf["drawing"]) == []


def test_bounding_box():
    strokes = [[(0.0, 0.0), (10.0, 20.0)], [(5.0, 5.0), (30.0, 4.0)]]
    assert bounding_box(strokes) == (0.0, 0.0, 30.0, 20.0)
