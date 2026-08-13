import numpy as np
import pytest

from src.m5_decision import (
    emv, maximax, maximin, laplace, hurwicz, minimax_regret, decision_tree,
    saddle_point, dominance, graphical_2xn, mixed_strategy_lp,
)

# Hand-computed payoff table: rows = acts A1,A2,A3; cols = states S1,S2,S3
PAYOFF = [[5, 10, 18], [8, 12, 10], [12, 8, 4]]
PROBS = [0.2, 0.5, 0.3]


def test_emv_known_values():
    result = emv(PAYOFF, PROBS)
    # A1: .2*5+.5*10+.3*18=11.4  A2: .2*8+.5*12+.3*10=10.6  A3: .2*12+.5*8+.3*4=7.6
    assert result["values"] == pytest.approx([11.4, 10.6, 7.6])
    assert result["best_index"] == 0


def test_maximax_known_values():
    result = maximax(PAYOFF)
    assert result["values"] == pytest.approx([18, 12, 12])
    assert result["best_index"] == 0


def test_maximin_known_values():
    result = maximin(PAYOFF)
    # worst case per act: 5, 8, 4 -> best of the worst cases is A2 (8)
    assert result["values"] == pytest.approx([5, 8, 4])
    assert result["best_index"] == 1


def test_laplace_known_values():
    result = laplace(PAYOFF)
    assert result["values"] == pytest.approx([11.0, 10.0, 8.0])
    assert result["best_index"] == 0


def test_hurwicz_known_values():
    result = hurwicz(PAYOFF, alpha=0.6)
    # A1: .6*18+.4*5=12.8  A2: .6*12+.4*8=10.4  A3: .6*12+.4*4=8.8
    assert result["values"] == pytest.approx([12.8, 10.4, 8.8])
    assert result["best_index"] == 0


def test_minimax_regret_known_values():
    result = minimax_regret(PAYOFF)
    # regret table: [[7,2,0],[4,0,8],[0,4,14]] -> max regret per act [7,8,14]
    assert np.allclose(result["regret_matrix"], [[7, 2, 0], [4, 0, 8], [0, 4, 14]])
    assert result["values"] == pytest.approx([7, 8, 14])
    assert result["best_index"] == 0


def test_decision_tree_folds_back_expected_value():
    tree = {
        "type": "decision",
        "children": {
            "yes": {"type": "chance", "branches": [(0.5, 100), (0.5, -20)]},
            "no": 0,
        },
    }
    result = decision_tree(tree)
    assert result["expected_value"] == pytest.approx(40.0)  # .5*100+.5*-20
    assert result["best_action"] == "yes"


def test_saddle_point_found():
    # row minima [1,4] -> maximin=4(row1); col maxima [5,4] -> minimax=4(col1)
    result = saddle_point([[1, 3], [5, 4]])
    assert result["exists"] is True
    assert result["value"] == pytest.approx(4.0)
    assert result["position"] == (1, 1)


def test_saddle_point_absent():
    result = saddle_point([[4, 1], [2, 3]])
    assert result["exists"] is False


def test_dominance_reduces_known_matrix():
    # row1=[1,1,1] dominated by row0; then col0 dominated by col2 among
    # the surviving rows {0,2} -> reduces to rows{0,2}, cols{1,2}
    matrix = [[4, 2, 3], [1, 1, 1], [3, 5, 2]]
    result = dominance(matrix)
    assert result["rows_kept"] == [0, 2]
    assert result["cols_kept"] == [1, 2]
    assert np.allclose(result["matrix"], [[2, 3], [5, 2]])


def test_graphical_2xn_matches_2x2_analytic_value():
    # analytic 2x2 formula for [[a,b],[c,d]] with no saddle point:
    # value=(ad-bc)/(a+d-b-c), p=(d-c)/(a+d-b-c)
    matrix = [[4, 1], [2, 3]]
    result = graphical_2xn(matrix)
    assert result["value"] == pytest.approx(2.5)
    assert result["p"] == pytest.approx(0.25)


def test_mixed_strategy_lp_matches_2x2_analytic_value_and_graphical():
    matrix = [[4, 1], [2, 3]]
    result = mixed_strategy_lp(matrix)
    assert result["value"] == pytest.approx(2.5)
    assert result["row_strategy"] == pytest.approx([0.25, 0.75])
    assert result["col_strategy"] == pytest.approx([0.5, 0.5])

    graphical = graphical_2xn(matrix)
    assert result["value"] == pytest.approx(graphical["value"])
