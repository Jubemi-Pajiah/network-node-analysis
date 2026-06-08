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
# used by the EPANET hydraulic engine; textbooks commonly quote the
# rounded forms 10.67 and 4.87. The precise values are used here so that the
# solver and EPANET solve an identical head-loss relationship.
HW_N = 1.852
HW_CONST = 10.667
HW_D_EXP = 4.871

DW_N = 2.0


def hw_resistance(length: float, diameter: float, C: float) -> float:
    """Hazen-Williams resistance coefficient K_ij."""
    return HW_CONST * length / (C ** HW_N * diameter ** HW_D_EXP)


def swamee_jain_f(reynolds: float, rel_roughness: float) -> float:
    """Darcy friction factor from the Swamee-Jain (1976) explicit formula.

    f = 0.25 / [log10( eps/(3.7 D) + 5.74 / Re^0.9 )]^2

    valid for 5000 <= Re <= 1e8 and 1e-6 <= eps/D <= 1e-2. For low Reynolds
    numbers the laminar value 64/Re is used so the solver stays well behaved
    while flows develop during the early iterations.
    """
    if reynolds < 1e-8:
        return 0.0
    if reynolds < 2000.0:
        return 64.0 / reynolds
    denom = math.log10(rel_roughness / 3.7 + 5.74 / reynolds ** 0.9)
    return 0.25 / (denom * denom)


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
