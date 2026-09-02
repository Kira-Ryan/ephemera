"""Radial / in-track / cross-track components of a difference vector, from the operator state.

Standard construction: R along the position vector, C along the orbital angular momentum
(r x v), I completing the right-handed set (C x R), so I points roughly along the velocity.
Pure functions on 3-tuples; no library dependency, so the tests can check them by hand."""
from __future__ import annotations

import math

Vec = tuple[float, float, float]


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    n = norm(a)
    if n == 0.0:
        raise ValueError("zero vector has no direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def ric_components(d: Vec, r: Vec, v: Vec) -> tuple[float, float, float]:
    """(radial, in-track, cross-track) components of `d` in the frame defined by state (r, v)."""
    R = unit(r)
    C = unit(cross(r, v))
    I = cross(C, R)
    return (dot(d, R), dot(d, I), dot(d, C))
