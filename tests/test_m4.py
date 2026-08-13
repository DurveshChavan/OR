import pytest

from src.m4_sequencing import johnson_two_machine, two_jobs_m_machines


def test_johnson_two_machine_known_sequence_and_makespan():
    # hand-applied Johnson's rule:
    # global min=1 (J2,M1)->front; min=2 (J1,M2)->back; min=3 (J4,M1)->front;
    # min=4 (J5,M2)->back; J3 left in the middle.
    # sequence: J2, J4, J3, J5, J1
    jobs = {"J1": (5, 2), "J2": (1, 6), "J3": (9, 7), "J4": (3, 8), "J5": (10, 4)}

    result = johnson_two_machine(jobs)

    assert result["sequence"] == ["J2", "J4", "J3", "J5", "J1"]
    assert result["makespan"] == pytest.approx(30.0)


def test_johnson_two_machine_tie_prefers_machine1_slot():
    # equal times on both machines -> convention: goes to the front (M1 rule)
    jobs = {"A": (3, 3), "B": (1, 5)}
    result = johnson_two_machine(jobs)
    # B's smallest time (1) is on M1 -> scheduled first
    assert result["sequence"][0] == "B"


def test_two_jobs_m_machines_known_elapsed_time():
    # job1: A(2) -> B(1) -> C(2), total 5
    # job2: B(1) -> A(2) -> C(2), total 5
    # hand-traced unit-grid DP: max simultaneous (diagonal) time = 3
    # elapsed = 5 + 5 - 3 = 7; a concrete feasible schedule achieving 7:
    #   t=0..2 job1:A, job2:B(0..1) then waits for A until t=2
    #   t=2..3 job1:B, job2:A(2..4)
    #   t=3..5 job1:C, job2 waits for C until t=5
    #   t=5..7 job2:C
    job1 = [("A", 2), ("B", 1), ("C", 2)]
    job2 = [("B", 1), ("A", 2), ("C", 2)]

    result = two_jobs_m_machines(job1, job2)

    assert result["elapsed_time"] == pytest.approx(7.0)
    assert result["idle_time_job1"] == pytest.approx(2.0)
    assert result["idle_time_job2"] == pytest.approx(2.0)


def test_two_jobs_m_machines_no_shared_machines_is_fully_parallel():
    # disjoint machines at every step -> nothing ever blocks, full diagonal
    # possible, elapsed time = max(T1, T2), zero idle for the longer job.
    job1 = [("A", 3), ("B", 2)]
    job2 = [("C", 1), ("D", 4)]

    result = two_jobs_m_machines(job1, job2)

    assert result["elapsed_time"] == pytest.approx(5.0)  # max(5, 5)
    assert result["idle_time_job1"] == pytest.approx(0.0)
    assert result["idle_time_job2"] == pytest.approx(0.0)
