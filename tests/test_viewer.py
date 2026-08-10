"""Viewer server: real HTTP requests against a live server over a
recorded fixture trace."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from conftest import bell_program
from traceact import JsonlSink, TraceConfig, configure, reset_config

import qlens
from qlens import tracing
from qlens.viewer.server import serve

pytest.importorskip("qiskit")


@pytest.fixture()
def viewer(tmp_path: Path) -> Any:
    """A live viewer over a source holding one passing and one failing run."""
    from qlens.conformance._builders import BUILDERS

    source = tmp_path / "traces.jsonl"
    state_dir = tmp_path / "qstates"
    configure(
        project="qlens-viewer-test",
        config=TraceConfig(sink_mode="blocking"),
        sinks=[JsonlSink(str(source))],
    )
    tracing.configure(state_dir=str(state_dir))

    build = BUILDERS["qiskit"]
    passing = qlens.run(build(bell_program(), 2), trace="gates")
    qlens.assert_distribution(passing, {"00": 0.5, "11": 0.5}, seed=0)
    failing = qlens.run(build(bell_program(), 2), trace=True)
    with pytest.raises(qlens.QlensAssertionError):
        qlens.assert_distribution(failing, {"01": 1.0}, seed=0)
    tracing.finish_traces()

    server = serve(str(source), state_dir=str(state_dir), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, passing.traced_run.trace_id, failing.traced_run.trace_id
    server.shutdown()
    server.server_close()
    reset_config()
    tracing.configure(state_dir="data/qstates", project=None, correlation_id=None)


def _fixture_assertion_line() -> int:
    """The line the fixture's failing check sits on.

    Attribution has to name the caller's own line, so the test needs the
    real number rather than a claim that some line was recorded. Reading
    it back from the source keeps that exact, without a literal that
    every edit above it silently invalidates.
    """
    marker = "qlens.assert_distribution(failing,"
    lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    matches = [n for n, line in enumerate(lines, 1) if line.lstrip().startswith(marker)]
    assert len(matches) == 1, f"expected one {marker!r} call, found {matches}"
    return matches[0]


def _get(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return dict(json.loads(response.read()))


def test_unknown_route_404(viewer: Any) -> None:
    base, _, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base}/api/nope")
    assert excinfo.value.code == 404


def test_circuit_requires_trace_id(viewer: Any) -> None:
    base, _, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base}/api/circuit")
    assert excinfo.value.code == 400


def test_unknown_trace_id_404(viewer: Any) -> None:
    base, _, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base}/api/circuit?trace_id=trc_nope")
    assert excinfo.value.code == 404


def test_static_traversal_stays_in_static_dir(viewer: Any) -> None:
    base, _, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{base}/static/..%2F..%2Fserver.py", timeout=10)
    assert excinfo.value.code == 404


def test_static_traversal_out_of_a_subdirectory_is_refused(viewer: Any) -> None:
    """Serving fonts from a subdirectory ruled out matching on basename,
    so climbing back out of one has to be refused on the resolved path."""
    base, _, _ = viewer
    for route in (
        "fonts/../../server.py",
        "fonts%2F..%2F..%2Fserver.py",
        "fonts/../../../../../../etc/hosts",
    ):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(f"{base}/static/{route}", timeout=10)
        assert excinfo.value.code == 404, route


def test_missing_font_is_404_not_an_empty_body(viewer: Any) -> None:
    base, _, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{base}/static/fonts/NotAFont.woff2", timeout=10)
    assert excinfo.value.code == 404


def test_health(viewer: Any) -> None:
    base, _, _ = viewer
    data = _get(f"{base}/api/health")
    assert data["status"] == "ok"
    assert data["version"] == qlens.__version__


def test_circuits_lists_both_runs(viewer: Any) -> None:
    base, passing_id, failing_id = viewer
    data = _get(f"{base}/api/circuits")
    by_id = {c["trace_id"]: c for c in data["circuits"]}
    assert by_id[passing_id]["status"] == "completed"
    assert by_id[passing_id]["assertions_failed"] == 0
    assert by_id[failing_id]["status"] == "failed"
    assert by_id[failing_id]["assertions_failed"] == 1


def test_circuit_detail_shape(viewer: Any) -> None:
    base, passing_id, _ = viewer
    data = _get(f"{base}/api/circuit?trace_id={passing_id}")
    assert len(data["layers"]) == 2
    assert data["layers"][1]["gates"][0]["gate"] == "cx"
    assert len(data["qstates"]) == 2
    assert data["assertions"][0]["status"] == "completed"


def test_state_at_positions(viewer: Any) -> None:
    base, passing_id, _ = viewer
    final = _get(f"{base}/api/state?trace_id={passing_id}&position=-1")
    assert final["num_qubits"] == 2
    amps = final["amplitudes"]
    assert len(amps) == 4
    # Bell state: |00> and |11> at 1/sqrt(2), big-endian.
    assert amps[0][0] == pytest.approx(0.7071, abs=1e-3)
    assert amps[3][0] == pytest.approx(0.7071, abs=1e-3)

    after_h = _get(f"{base}/api/state?trace_id={passing_id}&position=0")
    assert after_h["amplitudes"][2][0] == pytest.approx(0.7071, abs=1e-3)


def test_state_layer_mode_serves_all_positions(viewer: Any) -> None:
    # Layer mode only records a final qstate event, but the sidecar
    # spools every snapshot, so any position must be servable.
    base, _, failing_id = viewer
    data = _get(f"{base}/api/state?trace_id={failing_id}&position=0")
    assert data["captured_positions"] == [0, 1]


def test_state_uncaptured_position_404(viewer: Any) -> None:
    base, passing_id, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base}/api/state?trace_id={passing_id}&position=42")
    assert excinfo.value.code == 404


def test_stream_emits_run_summaries(viewer: Any) -> None:
    base, _, _ = viewer
    request = urllib.request.Request(f"{base}/api/stream")
    with urllib.request.urlopen(request, timeout=10) as response:
        line = response.readline().decode()
        assert line.startswith("data: ")
        summary = json.loads(line[len("data: ") :])
        assert "trace_id" in summary and "status" in summary


def test_index_served(viewer: Any) -> None:
    base, _, _ = viewer
    with urllib.request.urlopen(f"{base}/", timeout=10) as response:
        body = response.read().decode()
    assert "Qlens" in body


def test_assertion_events_carry_position_source_and_metrics(viewer: Any) -> None:
    base, _, failing_id = viewer
    data = _get(f"{base}/api/circuit?trace_id={failing_id}")
    assertion = data["assertions"][0]
    assert assertion["status"] == "failed"
    # Position is the run's last captured gate: where the marker goes.
    assert assertion["position"] == 1
    assert assertion["source"].endswith(f"test_viewer.py:{_fixture_assertion_line()}")
    assert assertion["details"]["tolerance"] == pytest.approx(0.05)
    assert assertion["details"]["p_value"] < 0.05
    assert assertion["expected"] == {"01": 1.0}


def test_infinite_statistic_serialises_as_null(viewer: Any) -> None:
    # An observed outcome the expectation calls impossible gives an
    # infinite chi-square, which JSON cannot represent.
    base, _, failing_id = viewer
    data = _get(f"{base}/api/circuit?trace_id={failing_id}")
    assert data["assertions"][0]["details"]["statistic"] is None


def test_waterfall_plane_shape_and_axes(viewer: Any) -> None:
    import base64

    base, passing_id, _ = viewer
    data = _get(f"{base}/api/waterfall?trace_id={passing_id}")
    assert data["num_states"] == 4
    assert data["num_positions"] == 2
    assert data["positions"] == [0, 1]
    assert data["first_row_state"] == 0
    assert data["last_row_state"] == 3
    for plane in ("magnitude", "phase"):
        raw = base64.b64decode(data[plane])
        assert len(raw) == data["rows"] * data["num_positions"]


def test_waterfall_threshold_drops_empty_rows(viewer: Any) -> None:
    base, passing_id, _ = viewer
    data = _get(f"{base}/api/waterfall?trace_id={passing_id}&threshold=0.1")
    # Big-endian: H on qubit 0 occupies |00> and |10>, then CX takes the
    # second to |11>. |01> is never occupied, so one row drops out and
    # the survivors fall into two bands with a gap between them.
    assert data["kept_rows"] == 3
    assert data["elided_rows"] == 1
    assert data["segments"] == [[0, 0], [1, 2]]


def test_waterfall_bands_rows_when_over_max(viewer: Any) -> None:
    base, passing_id, _ = viewer
    data = _get(f"{base}/api/waterfall?trace_id={passing_id}&max_rows=2")
    assert data["rows"] == 2
    assert data["kept_rows"] == 4  # nothing dropped, only reduced for display


def test_waterfall_threshold_above_everything_falls_back(viewer: Any) -> None:
    # Filtering every row away would render a blank panel; ignoring the
    # filter is the less confusing failure.
    base, passing_id, _ = viewer
    data = _get(f"{base}/api/waterfall?trace_id={passing_id}&threshold=99")
    assert data["kept_rows"] == 4
    assert data["threshold"] == 0.0


def test_waterfall_rejects_non_numeric_query(viewer: Any) -> None:
    base, passing_id, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base}/api/waterfall?trace_id={passing_id}&threshold=abc")
    assert excinfo.value.code == 400


def test_waterfall_normalizes_below_the_absolute_maximum(viewer: Any) -> None:
    # Position 0 of any circuit is near a basis state, so the absolute
    # maximum is ~1 while the rest of the run sits far lower. The
    # normalizing peak must track the body of the data, not that spike.
    base, passing_id, _ = viewer
    data = _get(f"{base}/api/waterfall?trace_id={passing_id}")
    assert data["peak"] <= data["maximum"]


def test_static_module_files_served(viewer: Any) -> None:
    base, _, _ = viewer
    for name in ("app.js", "draw.js", "ui.js", "styles.css"):
        with urllib.request.urlopen(f"{base}/static/{name}", timeout=10) as response:
            assert response.status == 200
            assert response.read()


def test_every_font_the_stylesheet_names_is_actually_served(viewer: Any) -> None:
    """The stylesheet is the only place the font filenames appear, so a
    rename that misses it degrades to a system fallback in silence. Every
    url() it declares gets fetched."""
    base, _, _ = viewer
    with urllib.request.urlopen(f"{base}/static/styles.css", timeout=10) as response:
        css = response.read().decode()

    references = re.findall(r"url\(['\"]([^'\"]+)['\"]\)", css)
    assert references, "the stylesheet declares no @font-face sources"

    for reference in references:
        with urllib.request.urlopen(f"{base}/static/{reference}", timeout=10) as response:
            assert response.status == 200, reference
            assert response.headers["Content-Type"] == "font/woff2", reference
            # woff2 opens with the signature 'wOF2'.
            assert response.read(4) == b"wOF2", reference


def test_fonts_are_cached_rather_than_refetched_each_reload(viewer: Any) -> None:
    base, _, _ = viewer
    with urllib.request.urlopen(
        f"{base}/static/fonts/SpaceGrotesk-Variable.woff2", timeout=10
    ) as response:
        assert "immutable" in response.headers["Cache-Control"]
    # Code is never stored. no-cache would still store and revalidate,
    # which leaves an open tab running a previous version's JavaScript
    # against a restarted server.
    for asset in ("app.js", "styles.css"):
        with urllib.request.urlopen(f"{base}/static/{asset}", timeout=10) as response:
            assert response.headers["Cache-Control"] == "no-store", asset
    with urllib.request.urlopen(f"{base}/", timeout=10) as response:
        assert response.headers["Cache-Control"] == "no-store"


def test_bundled_fonts_ship_their_licences() -> None:
    """Both faces are OFL 1.1, which permits bundling only while the
    licence and copyright notice travel with the font."""
    fonts = Path(qlens.viewer.server.__file__).parent / "static" / "fonts"
    faces = sorted(fonts.glob("*.woff2"))
    assert faces, "no fonts are vendored"
    for licence in ("SpaceGrotesk-OFL.txt", "CommitMono-OFL.txt"):
        text = (fonts / licence).read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE Version 1.1" in text, licence
        assert "Copyright" in text, licence


def test_assertion_events_carry_method_and_reliability(viewer: Any) -> None:
    base, passing_id, _ = viewer
    data = _get(f"{base}/api/circuit?trace_id={passing_id}")
    assertion = data["assertions"][0]
    assert assertion["method"] == "chi_square"
    assert assertion["reliability"]["reliable"] is True


def test_run_summary_reports_the_settings_it_used(viewer: Any) -> None:
    """The viewer states which defaults were in force rather than
    assuming the built-in ones."""
    base, passing_id, _ = viewer
    summary = next(
        c for c in _get(f"{base}/api/circuits")["circuits"] if c["trace_id"] == passing_id
    )
    assert summary["settings"]["distribution_test"] == "chi_square"
    assert summary["settings"]["on_unreliable_statistics"] == "warn"


def test_unreliable_checks_are_counted_separately_from_failures(viewer: Any) -> None:
    """A flagged check may have passed, and its passing is the part that
    cannot be trusted, so it cannot be folded into the failure count."""
    base, passing_id, _ = viewer
    summary = next(
        c for c in _get(f"{base}/api/circuits")["circuits"] if c["trace_id"] == passing_id
    )
    assert summary["assertions_failed"] == 0
    assert summary["assertions_unreliable"] == 0


def test_waterfall_accepts_a_viewport(viewer: Any) -> None:
    base, passing_id, _ = viewer
    data = _get(f"{base}/api/waterfall?trace_id={passing_id}&pos_from=0&pos_to=1")
    assert data["view"]["pos_from"] == 0
    assert data["view"]["pos_to"] == 1
    assert data["view_positions"] == [0]
    # The run's own axis is unchanged: the transport spans the run.
    assert data["num_positions"] >= 1


def test_waterfall_rejects_a_non_numeric_viewport(viewer: Any) -> None:
    base, passing_id, _ = viewer
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(
            f"{base}/api/waterfall?trace_id={passing_id}&pos_from=abc", timeout=10
        )
    assert excinfo.value.code == 400


def test_zooming_unpacks_the_sidecar_only_once(
    viewer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zooming is meant to cost a reduction and no I/O, which is a claim
    about the grid cache rather than about the viewport code. Counting
    the actual decompressions is the only way to hold it."""
    import numpy as np

    from qlens.viewer import _waterfall

    base, passing_id, _ = viewer
    _waterfall._cache.clear()

    unpacks = 0
    real_load = np.load

    def counting(*args: Any, **kwargs: Any) -> Any:
        nonlocal unpacks
        unpacks += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(np, "load", counting)

    _get(f"{base}/api/waterfall?trace_id={passing_id}")
    assert unpacks == 1, "the first request has to read the sidecar"

    for span in ((0, 1), (0, 2), (1, 2)):
        _get(
            f"{base}/api/waterfall?trace_id={passing_id}"
            f"&pos_from={span[0]}&pos_to={span[1]}"
        )
    assert unpacks == 1, "every later viewport reduces from the cached grid"


def test_a_viewport_does_not_add_a_second_grid_to_the_cache(viewer: Any) -> None:
    from qlens.viewer import _waterfall

    base, passing_id, _ = viewer
    _get(f"{base}/api/waterfall?trace_id={passing_id}")
    before = len(_waterfall._cache)
    for span in ((0, 1), (0, 2), (1, 2)):
        _get(
            f"{base}/api/waterfall?trace_id={passing_id}"
            f"&pos_from={span[0]}&pos_to={span[1]}"
        )
    assert len(_waterfall._cache) == before
