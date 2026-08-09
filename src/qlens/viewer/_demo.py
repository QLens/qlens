"""Sample runs, so ``qlens view --demo`` opens on something to read.

An empty viewer teaches nothing: the reading guide has no waterfall to
point at, and there is no way to try the transport or the assertion
markers before wiring up a real project. These runs fill that gap.

They are recorded through the ordinary path — real snapshots, real
``qlens.run`` result objects, real ``assert_distribution`` calls, the
same trace adapter and the same sidecar spooling — so what the viewer
renders here is exactly what it renders for a user's own tests. The gate
programs execute on the bundled reference simulator rather than a
provider, which is what keeps the demo working on a bare install with
neither Qiskit nor PennyLane present.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from qlens._execution import ExecutionResult, Snapshot
from qlens._reliability import QlensStatisticsWarning
from qlens.conformance._reference import apply_gate

# Fixed seeds everywhere: the demo is a teaching surface and a support
# artefact, so two people looking at it should be looking at the same
# picture.
_CIRCUIT_SEED = 20260809
_SAMPLING_SEED = 4

Program = list[tuple[str, tuple[int, ...], tuple[float, ...]]]


def _ghz_with_phase(num_qubits: int = 4) -> Program:
    """Entangle, wind phase onto each qubit, then unwind most of it.

    Shows the two things the waterfall is for: amplitude collapsing onto
    a few basis states, and phase moving while magnitude does not.
    """
    program: Program = [("h", (0,), ())]
    for q in range(num_qubits - 1):
        program.append(("cx", (q, q + 1), ()))
    for turn in range(6):
        for q in range(num_qubits):
            program.append(("rz", (q,), (math.pi / (3 + turn + q),)))
        program.append(("cz", (0, num_qubits - 1), ()))
    for q in range(num_qubits):
        program.append(("h", (q,), ()))
    for q in range(num_qubits - 1):
        program.append(("cx", (q, q + 1), ()))
    return program


def _layered_ansatz(num_qubits: int = 6, layers: int = 14) -> Program:
    """A variational-style ansatz: the shape most people will point the
    viewer at first, and dense enough to need the transport."""
    rng = np.random.default_rng(_CIRCUIT_SEED)
    program: Program = [("h", (q,), ()) for q in range(num_qubits)]
    for layer in range(layers):
        for q in range(num_qubits):
            program.append(("ry", (q,), (float(rng.uniform(0.2, math.pi - 0.2)),)))
            program.append(("rz", (q,), (float(rng.uniform(0, 2 * math.pi)),)))
        for q in range(layer % 2, num_qubits - 1, 2):
            program.append(("cx", (q, q + 1), ()))
    return program


def _sparse_subspace(num_qubits: int = 9, active: int = 4) -> Program:
    """Work inside a small subspace of a wide register.

    Most real algorithms never touch most of their basis states, which is
    what the collapse control exists for: here 496 of 512 rows stay at
    zero throughout, and hiding them is the difference between a legible
    waterfall and a field of black.
    """
    rng = np.random.default_rng(_CIRCUIT_SEED + 1)
    program: Program = [("h", (q,), ()) for q in range(active)]
    for layer in range(8):
        for q in range(active):
            program.append(("rz", (q,), (float(rng.uniform(0, 2 * math.pi)),)))
        for q in range(layer % 2, active - 1, 2):
            program.append(("cz", (q, q + 1), ()))
        # Carry the subspace onto a couple of the idle qubits without
        # spreading across the whole register.
        program.append(("cx", (layer % active, active + (layer % 2)), ()))
    for q in range(active):
        program.append(("h", (q,), ()))
    return program


def _capture(program: Program, num_qubits: int) -> ExecutionResult:
    """Run a neutral gate program, keeping the state after every gate."""
    state = np.zeros(2**num_qubits, dtype=np.complex128)
    state[0] = 1.0
    snapshots: list[Snapshot] = []
    for position, (gate, qubits, params) in enumerate(program):
        state = apply_gate(state, gate, qubits, params, num_qubits)
        names = ("theta",) if params else ()
        snapshots.append(
            Snapshot(
                position=position,
                gate=gate,
                qubits=qubits,
                params=dict(zip(names, (float(p) for p in params), strict=True)),
                statevector=state.copy(),
            )
        )

    def counts(shots: int, seed: int | None) -> dict[str, int]:
        probabilities = np.abs(snapshots[-1].statevector) ** 2
        probabilities = probabilities / probabilities.sum()
        rng = np.random.default_rng(seed)
        drawn = rng.multinomial(shots, probabilities)
        return {
            format(index, f"0{num_qubits}b"): int(count)
            for index, count in enumerate(drawn)
            if count
        }

    return ExecutionResult(
        backend="reference",
        num_qubits=num_qubits,
        snapshots=snapshots,
        _counts_fn=counts,
    )


def _true_distribution(result: ExecutionResult) -> dict[str, float]:
    """The run's own outcome distribution: the expectation a passing test
    would have been written against.

    Every basis state is included, even the negligible ones. Trimming to
    the largest terms would leave the sampler free to draw an outcome the
    expectation calls impossible, which chi-square rejects outright — the
    demo's passing check would fail on a technicality.
    """
    probabilities = np.abs(result.final_statevector) ** 2
    return {
        format(index, f"0{result.num_qubits}b"): float(probability)
        for index, probability in enumerate(probabilities)
    }


def generate(directory: str | Path) -> tuple[str, str]:
    """Write the sample runs. Returns (trace source, state directory)."""
    import traceact

    import qlens
    from qlens import tracing

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    source = root / "traces.jsonl"
    state_dir = root / "qstates"

    traceact.configure(sinks=[traceact.JsonlSink(str(source))])
    tracing.configure(state_dir=str(state_dir), project="qlens-demo")

    # Recorded oldest first: the viewer opens on the newest run, and the
    # ansatz is the one worth landing on.
    _record_ghz(qlens, tracing)
    _record_sparse(qlens, tracing)
    _record_ansatz(qlens, tracing)
    return str(source), str(state_dir)


def _record_ansatz(qlens: Any, tracing: Any) -> None:
    """A run whose assertions disagree: one written against the circuit's
    real output passes, one written against a guess fails."""
    result = _capture(_layered_ansatz(), num_qubits=6)
    result.traced_run = tracing.start_run(result, mode="layers")
    qlens.assert_distribution(
        result, _true_distribution(result), test="chi_square_exact", seed=_SAMPLING_SEED
    )
    try:
        qlens.assert_distribution(
            result,
            {"000000": 0.5, "111111": 0.5},
            seed=_SAMPLING_SEED,
        )
    except AssertionError:
        pass  # the point of this run: a failed check to click through to
    tracing.finish_traces()


def _record_sparse(qlens: Any, tracing: Any) -> None:
    """The same output checked two ways.

    Its distribution is heavy-tailed: half the occupied states expect
    well under one count at 1024 shots. A distance check handles that; a
    plain chi-square p-value does not, and recording both gives the
    viewer a flagged assertion sitting next to a sound one on identical
    data, which is the clearest way to show what the flag means.
    """
    result = _capture(_sparse_subspace(), num_qubits=9)
    expected = _true_distribution(result)
    result.traced_run = tracing.start_run(result, mode="layers")
    qlens.assert_distribution(
        result, expected, test="tvd", tolerance=0.1, seed=_SAMPLING_SEED
    )
    with warnings.catch_warnings():
        # Recorded on purpose so the viewer has a flagged check to show.
        warnings.simplefilter("ignore", QlensStatisticsWarning)
        try:
            qlens.assert_distribution(
                result, expected, test="chi_square", seed=_SAMPLING_SEED
            )
        except AssertionError:
            pass
    tracing.finish_traces()


def _record_ghz(qlens: Any, tracing: Any) -> None:
    """Small and evenly spread, so plain chi-square suits it."""
    result = _capture(_ghz_with_phase(), num_qubits=4)
    result.traced_run = tracing.start_run(result, mode="layers")
    qlens.assert_distribution(
        result, _true_distribution(result), test="chi_square", seed=_SAMPLING_SEED
    )
    tracing.finish_traces()
