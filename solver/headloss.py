"""Head-loss models for the nodal head correction solver.

Two models are supported, both written in the generalized power-law form:

    H_i - H_j = K_ij * |Q_ij|^(n-1) * Q_ij

so that the flow recovered from a head difference is:

    Q_ij = sign(H_i - H_j) * (|H_i - H_j| / K_ij)^(1/n)

Hazen-Williams:  n = 1.852, K independent of Q.
Darcy-Weisbach:  n = 2.0, K depends on the friction factor f, which is
                 recomputed every iteration from the Reynolds number using the
                 Swamee-Jain (1976) explicit approximation of the
                 Colebrook-White equation.
"""

from __future__ import annotations

import math

# Physical constants (SI units)
G = 9.81                 # gravitational acceleration, m/s^2
NU_WATER = 1.004e-6      # kinematic viscosity of water at 20 C, m^2/s

# Model identifiers
HW = "H-W"   # Hazen-Williams
DW = "D-W"   # Darcy-Weisbach

# Hazen-Williams exponent and SI resistance constant.
# The constant 10.667 and diameter exponent 4.871 are the precise SI values
# used by the EPANET hydraulic engine; textbooks commonly quote the rounded
# forms 10.67 and 4.87. The precise values are used here so that the
# solver and EPANET solve an identical head-loss relationship. Hazen-Williams
# is retained for reference only; all reported results use Darcy-Weisbach.
HW_N = 1.852
HW_CONST = 10.667
HW_D_EXP = 4.871

DW_N = 2.0


def hw_resistance(length: float, diameter: float, C: float) -> float:
    """Hazen-Williams resistance coefficient K_ij."""
    return HW_CONST * length / (C ** HW_N * diameter ** HW_D_EXP)


RE_LAMINAR = 2000.0    # upper limit of the laminar regime
RE_TURBULENT = 4000.0  # lower limit of the fully developed turbulent regime


def _sj(reynolds: float, rel_roughness: float) -> float:
    """Swamee-Jain (1976) explicit approximation of Colebrook-White.

    f = 0.25 / [log10( eps/(3.7 D) + 5.74 / Re^0.9 )]^2
    """
    denom = math.log10(rel_roughness / 3.7 + 5.74 / reynolds ** 0.9)
    return 0.25 / (denom * denom)


def _dsj_dre(reynolds: float, rel_roughness: float) -> float:
    """Derivative of _sj with respect to Reynolds number."""
    a = rel_roughness / 3.7 + 5.74 / reynolds ** 0.9
    da = -0.9 * 5.74 / reynolds ** 1.9
    log_a = math.log10(a)
    return -0.5 * da / (a * math.log(10.0) * log_a ** 3)


def swamee_jain_f(reynolds: float, rel_roughness: float) -> float:
    """Darcy friction factor across all three flow regimes.

    Laminar (Re <= 2000):     f = 64 / Re  (Hagen-Poiseuille)
    Turbulent (Re >= 4000):   Swamee-Jain (1976), valid to Re = 1e8
    Transitional (2000-4000): smooth interpolation between the two

    The blend matters. The laminar and Swamee-Jain branches disagree sharply
    where they meet - at Re = 2000 they give 0.032 and about 0.050 - so
    switching directly between them makes f discontinuous. A pipe carrying
    little flow then sits astride the jump and its friction factor alternates
    between branches from one iteration to the next, which stalls convergence.
    Interpolating smoothly across the critical zone keeps f continuous in the
    flow, in the same spirit as the transitional treatment used by EPANET
    (Rossman, 2000).
    """
    if reynolds < 1e-8:
        return 0.0
    if reynolds <= RE_LAMINAR:
        return 64.0 / reynolds
    if reynolds >= RE_TURBULENT:
        return _sj(reynolds, rel_roughness)

    t = (reynolds - RE_LAMINAR) / (RE_TURBULENT - RE_LAMINAR)
    f_lam = 64.0 / RE_LAMINAR
    f_turb = _sj(RE_TURBULENT, rel_roughness)
    # Smoothstep rather than a slope-matched Hermite: carrying the steep
    # laminar slope into the blend drives f below both endpoint values in the
    # middle of the critical zone, which is not physical. Zero end slopes keep
    # the interpolation monotone between the two branches.
    blend = t * t * (3.0 - 2.0 * t)
    return f_lam + (f_turb - f_lam) * blend


def dw_resistance(length: float, diameter: float, friction_factor: float) -> float:
    """Darcy-Weisbach resistance coefficient K_ij.

    K_ij = 8 f L / (pi^2 g D^5)
    """
    return 8.0 * friction_factor * length / (math.pi ** 2 * G * diameter ** 5)


def dw_resistance_from_flow(length: float, diameter: float, epsilon: float,
                            flow: float) -> float:
    """Darcy-Weisbach K_ij for a given flow, recomputing f via Swamee-Jain.

    The friction factor depends on the flow through the Reynolds number, so the
    resistance is updated each iteration rather than held constant.
    """
    area = math.pi * diameter ** 2 / 4.0
    velocity = abs(flow) / area
    reynolds = velocity * diameter / NU_WATER
    f = swamee_jain_f(reynolds, epsilon / diameter)
    if f <= 0.0:
        # No flow yet: fall back to a fully rough estimate so K is finite.
        f = swamee_jain_f(1.0e6, epsilon / diameter)
    return dw_resistance(length, diameter, f)


def model_exponent(model: str) -> float:
    if model == HW:
        return HW_N
    if model == DW:
        return DW_N
    raise ValueError(f"unknown head-loss model '{model}' (use '{HW}' or '{DW}')")
