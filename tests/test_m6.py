import math

import pytest

from src.m6_cpm_pert import (
    build_network, forward_backward, pert_expected, pert_variance,
    project_completion_probability,
)


def test_pert_expected_and_variance_formulas():
    assert pert_expected(2, 4, 6) == pytest.approx(4.0)  # (2+16+6)/6
    assert pert_variance(2, 4, 6) == pytest.approx((4 / 6) ** 2)


def test_forward_backward_known_cpm_network():
    # hand-solved network:
    #   A(3), B(2) have no predecessors
    #   C(4) after A, D(3) after B, E(2) after C and D
    # forward: ES/EF A=0/3 B=0/2 C=3/7 D=2/5 E=7/9 -> project duration 9
    # backward: LF/LS E=9/7 C=7/3 D=7/4 A=3/0 B=4/2
    # slack: A=0 B=2 C=0 D=2 E=0 -> critical path A-C-E
    activities = {
        "A": (3, []),
        "B": (2, []),
        "C": (4, ["A"]),
        "D": (3, ["B"]),
        "E": (2, ["C", "D"]),
    }
    G = build_network(activities)
    result = forward_backward(G)

    assert result["project_duration"] == pytest.approx(9.0)
    assert result["ES"] == pytest.approx({"A": 0, "B": 0, "C": 3, "D": 2, "E": 7})
    assert result["EF"] == pytest.approx({"A": 3, "B": 2, "C": 7, "D": 5, "E": 9})
    assert result["LS"] == pytest.approx({"A": 0, "B": 2, "C": 3, "D": 4, "E": 7})
    assert result["LF"] == pytest.approx({"A": 3, "B": 4, "C": 7, "D": 7, "E": 9})
    assert result["slack"] == pytest.approx({"A": 0, "B": 2, "C": 0, "D": 2, "E": 0})
    assert result["critical_path"] == ["A", "C", "E"]


def test_project_completion_probability_matches_hand_calc():
    # X: PERT(2,4,6) -> te=4, var=(4/6)^2; Y: PERT(1,2,3) after X -> te=2, var=(2/6)^2
    # both on the (only, hence critical) chain: mean=6, var=0.44444+0.11111=0.55556
    # std=0.745356; deadline=7 -> z=(7-6)/0.745356=1.34164
    # p = 0.5*(1+erf(z/sqrt2))
    activities = {
        "X": ((2, 4, 6), []),
        "Y": ((1, 2, 3), ["X"]),
    }
    G = build_network(activities)
    result = project_completion_probability(G, deadline=7)

    expected_mean = 6.0
    expected_std = math.sqrt((4 / 6) ** 2 + (2 / 6) ** 2)
    expected_z = (7 - expected_mean) / expected_std
    expected_p = 0.5 * (1 + math.erf(expected_z / math.sqrt(2)))

    assert result["mean"] == pytest.approx(expected_mean)
    assert result["std"] == pytest.approx(expected_std)
    assert result["z"] == pytest.approx(expected_z)
    assert result["probability"] == pytest.approx(expected_p)
    assert result["probability"] == pytest.approx(0.9101437525605001)


def test_cyclic_network_raises_value_error():
    activities = {"P": (1, ["Q"]), "Q": (1, ["P"])}
    G = build_network(activities)
    with pytest.raises(ValueError):
        forward_backward(G)


def test_build_network_unknown_predecessor_raises():
    with pytest.raises(ValueError):
        build_network({"A": (1, ["ghost"])})
