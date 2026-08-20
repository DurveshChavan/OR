import numpy as np
import pandas as pd
import pytest

from api.engine.decision import (
    emv, maximax, maximin, laplace, hurwicz, minimax_regret, decision_tree,
    saddle_point, dominance, graphical_2xn, mixed_strategy_lp, escalation_decision,
    escalation_game,
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


BREACH_RATES = {1: 0.2}
SLA_PENALTIES = {1: 100}
LABOUR_COST = {"resolve-in-place": 10, "escalate-L2": 30, "escalate-vendor": 60}
BREACH_REDUCTION = {"escalate-L2": 0.5, "escalate-vendor": 0.25}


def test_escalation_decision_known_values_no_reassignment_stays_in_place():
    ticket = pd.Series({"priority": 1, "reassignment_count": 0})
    result = escalation_decision(
        ticket, BREACH_RATES, SLA_PENALTIES, LABOUR_COST, breach_reduction=BREACH_REDUCTION
    )
    # p_breach per act: resolve=0.2*1=0.2  L2=0.2*0.5=0.1  vendor=0.2*0.25=0.05
    # cost(breach,no-breach): resolve=(110,10) L2=(130,30) vendor=(160,60)
    # EMV: resolve=-(.2*110+.8*10)=-30  L2=-(.1*130+.9*30)=-40  vendor=-(.05*160+.95*60)=-65
    # low urgency -> resolving in place is still cheapest overall
    assert result["p_breach"] == pytest.approx([0.2, 0.1, 0.05])
    assert result["values"] == pytest.approx([-30.0, -40.0, -65.0])
    assert result["best_index"] == 0
    assert result["acts"][result["best_index"]] == "resolve-in-place"


def test_escalation_decision_schedule_already_breached_forces_escalation():
    # time_to_breach_hours<=0: the schedule already shows this ticket
    # missing its deadline -> p_breach forced to 1.0 before reduction
    ticket = pd.Series({"priority": 1, "reassignment_count": 0})
    result = escalation_decision(
        ticket, BREACH_RATES, SLA_PENALTIES, LABOUR_COST,
        breach_reduction=BREACH_REDUCTION, time_to_breach_hours=0.0,
    )
    # p_breach per act: resolve=1.0  L2=0.5  vendor=0.25
    # EMV: resolve=-(1*110+0*10)=-110  L2=-(.5*130+.5*30)=-80  vendor=-(.25*160+.75*60)=-85
    # now escalating to L2 is cheapest -- breach_reduction is what makes
    # escalation ever worth its extra labour cost
    assert result["p_breach"] == pytest.approx([1.0, 0.5, 0.25])
    assert result["values"] == pytest.approx([-110.0, -80.0, -85.0])
    assert result["best_index"] == 1
    assert result["acts"][result["best_index"]] == "escalate-L2"


def test_escalation_decision_reassignment_bumps_breach_prob():
    ticket = pd.Series({"priority": 1, "reassignment_count": 2})
    result = escalation_decision(
        ticket, BREACH_RATES, SLA_PENALTIES, LABOUR_COST,
        breach_reduction=BREACH_REDUCTION, reassignment_bump=0.15,
    )
    # base p_breach = 0.2 * (1 + 0.15*2) = 0.26 -> per-act: .26, .13, .065
    # EMV: resolve=-(.26*110+.74*10)=-36  L2=-(.13*130+.87*30)=-43
    # vendor=-(.065*160+.935*60)=-66.5
    assert result["p_breach"] == pytest.approx([0.26, 0.13, 0.065])
    assert result["values"] == pytest.approx([-36.0, -43.0, -66.5])
    assert result["best_index"] == 0


def test_escalation_decision_bump_capped_at_probability_one():
    ticket = pd.Series({"priority": 1, "reassignment_count": 50})
    result = escalation_decision(
        ticket, BREACH_RATES, SLA_PENALTIES, LABOUR_COST, reassignment_bump=0.15
    )
    assert result["p_breach"][0] == pytest.approx(1.0)  # resolve-in-place: no reduction


def test_original_pipeline_escalation_instance_textbook_case():
    """The fixed resolve/escalate payoff table pipeline.py used before
    make_escalation_decision switched to escalation_decision() built from
    real breach rates (see api/engine/pipeline.py's CONFIG and
    make_escalation_decision) -- kept here as a standing verification
    case now that it no longer lives in application code.
    """
    payoff = [[80, 20], [60, 50], [40, 70]]  # cols: quick-fix, complex
    probs = [0.7, 0.3]
    result = emv(payoff, probs)
    # A1: .7*80+.3*20=62  A2: .7*60+.3*50=57  A3: .7*40+.3*70=49
    assert result["values"] == pytest.approx([62.0, 57.0, 49.0])
    assert result["best_index"] == 0
    assert result["best_value"] == pytest.approx(62.0)


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


def test_escalation_game_cell_matches_escalation_decision_formula():
    # same expected-cost formula escalation_decision uses per ticket,
    # applied here per (act, priority) cell instead of per ticket.
    breach_rates = {1: 0.2, 2: 0.1}
    sla_penalties = {1: 100, 2: 40}
    labour_cost = {"resolve-in-place": 10, "escalate-L2": 30, "escalate-vendor": 60}
    breach_reduction = {"escalate-L2": 0.5, "escalate-vendor": 0.25}

    result = escalation_game(breach_rates, sla_penalties, labour_cost, breach_reduction)

    assert result["acts"] == ["resolve-in-place", "escalate-L2"]
    assert result["priorities"] == [1, 2]

    # resolve-in-place, P1: p=0.2, breach_cost=100+10=110, no_breach_cost=10
    # cost = .2*110 + .8*10 = 22+8 = 30 -> payoff -30
    assert result["matrix"][0][0] == pytest.approx(-30.0)
    # escalate-L2, P1: p=0.2*0.5=0.1, breach_cost=100+30=130, no_breach_cost=30
    # cost = .1*130 + .9*30 = 13+27 = 40 -> payoff -40
    assert result["matrix"][1][0] == pytest.approx(-40.0)


def test_escalation_game_wires_all_four_techniques_consistently():
    # minimax theorem: whether or not a saddle point exists, the
    # graphical method's value and the mixed-strategy LP's value must
    # agree with each other (and with the saddle value, if one exists).
    breach_rates = {1: 0.5, 2: 0.05, 3: 0.5}
    sla_penalties = {1: 500, 2: 20, 3: 500}
    labour_cost = {"resolve-in-place": 10, "escalate-L2": 200, "escalate-vendor": 400}
    breach_reduction = {"escalate-L2": 0.1, "escalate-vendor": 0.05}

    result = escalation_game(breach_rates, sla_penalties, labour_cost, breach_reduction)
    saddle = result["saddle_point"]
    graphical = result["graphical"]
    mixed = result["mixed_strategy_lp"]

    assert graphical["value"] == pytest.approx(mixed["value"], abs=1e-4)
    if saddle["exists"]:
        assert saddle["value"] == pytest.approx(graphical["value"], abs=1e-4)
    else:
        assert 0.0 <= graphical["p"] <= 1.0

    reduced = result["dominance"]
    assert len(reduced["rows_kept"]) <= len(result["acts"])
    assert len(reduced["cols_kept"]) <= len(result["priorities"])
