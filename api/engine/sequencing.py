"""M4 — sequencing (Unit III).

johnson_two_machine: classic n-job/2-machine flow shop (Johnson's rule).
two_jobs_m_machines: classic 2-job/m-machine graphical method, done as an
equivalent finite grid computation (see derivation in two_jobs_m_machines'
docstring) instead of literally drawing the graph.
"""


def johnson_two_machine(jobs):
    """Johnson's rule: repeatedly take the remaining job with the smallest
    single processing time; if that time is on machine 1, schedule it as
    early as possible, if on machine 2, as late as possible. `jobs` is
    {name: (t1, t2)}."""
    remaining = dict(jobs)
    n = len(jobs)
    sequence = [None] * n
    first, last = 0, n - 1

    while remaining:
        job, (t1, t2) = min(remaining.items(), key=lambda kv: min(kv[1]))
        if t1 <= t2:
            sequence[first] = job
            first += 1
        else:
            sequence[last] = job
            last -= 1
        del remaining[job]

    makespan, schedule = _simulate_flow_shop(sequence, jobs)
    return {"sequence": sequence, "makespan": makespan, "schedule": schedule}


def _simulate_flow_shop(sequence, jobs):
    m1_time = 0.0
    m2_time = 0.0
    schedule = []
    for job in sequence:
        t1, t2 = jobs[job]
        m1_start = m1_time
        m1_end = m1_start + t1
        m2_start = max(m1_end, m2_time)
        m2_end = m2_start + t2
        schedule.append({
            "job": job, "m1_start": m1_start, "m1_end": m1_end,
            "m2_start": m2_start, "m2_end": m2_end,
        })
        m1_time = m1_end
        m2_time = m2_end
    return m2_time, schedule


def two_jobs_m_machines(job1_times, job2_times):
    """Graphical method for 2 jobs sharing m machines, each job visiting
    every machine exactly once in its own given order. `job1_times` /
    `job2_times` are lists of (machine_id, duration) in that job's
    processing order; durations must be whole numbers (standard for these
    hand-worked problems).

    Derivation used instead of literally drawing the graph: plot job1's
    cumulative processing time on the x-axis and job2's on the y-axis. A
    monotone path from (0,0) to (T1,T2) moves right (job1 works alone), up
    (job2 works alone), or diagonally at 45 degrees (both work at once, on
    *different* machines -- one machine can't serve both jobs at the same
    instant, so a diagonal step through the unit square where job1 and
    job2 would be on the *same* machine is forbidden). 1 unit of diagonal
    travel advances both axes in 1 unit of wall-clock time, while a unit
    of horizontal/vertical travel advances only one axis in 1 unit of
    wall-clock time, so elapsed_time = T1 + T2 - D, D = total diagonal
    travelled, and the graphical problem reduces to maximising D.

    D is computed by a standard grid-path DP over unit squares (x, y) for
    x in 1..T1, y in 1..T2 -- not over the coarser m x m grid of machine
    segments directly, because a segment's diagonal run can end partway
    through it (whenever the two segments sharing that run have different
    lengths) and then continue into a neighbouring segment pair; indexing
    by segment alone loses that hand-off and can under- or over-count D.
    The unit grid sidesteps this: every cell is a 1x1 square, so a
    diagonal step always lines up with its neighbours exactly.
    """
    machine_at_1 = []
    for machine, duration in job1_times:
        machine_at_1.extend([machine] * int(duration))
    machine_at_2 = []
    for machine, duration in job2_times:
        machine_at_2.extend([machine] * int(duration))

    t1, t2 = len(machine_at_1), len(machine_at_2)

    dp = [[0] * (t2 + 1) for _ in range(t1 + 1)]
    for x in range(1, t1 + 1):
        for y in range(1, t2 + 1):
            best = max(dp[x - 1][y], dp[x][y - 1])
            if machine_at_1[x - 1] != machine_at_2[y - 1]:
                best = max(best, dp[x - 1][y - 1] + 1)
            dp[x][y] = best

    max_diagonal = dp[t1][t2]
    elapsed_time = t1 + t2 - max_diagonal

    return {
        "elapsed_time": float(elapsed_time),
        "idle_time_job1": float(elapsed_time - t1),
        "idle_time_job2": float(elapsed_time - t2),
    }
