"""Issue #225 Slice 1: characterization only, no QR behavior change."""

import pytest

from scoreform.layouts import require_layout, supported_layout_ids
from scoreform.qr_print_baseline import measure_qr_print_baseline


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_current_layout_geometry_is_characterized(layout_id):
    layout = require_layout(layout_id)
    result = measure_qr_print_baseline(layout, "PDS2|r=rt_" + "a" * 32)
    assert result.layout_id == layout_id
    assert result.size_points == pytest.approx(69.6)
    assert result.size_inches == pytest.approx(69.6 / 72.0)
    assert result.border_modules == 4
    assert result.error_correction == "L"
    assert result.matrix_modules >= 21
    assert result.total_modules == result.matrix_modules + 8
    assert result.module_inches > 0


def test_longer_payload_can_increase_density_without_increasing_print_size():
    layout = require_layout(supported_layout_ids()[0])
    short = measure_qr_print_baseline(layout, "PDS2|r=rt_" + "a" * 32)
    long = measure_qr_print_baseline(
        layout,
        "PDS2|m=scoreform|c=english_12_pd4|w=locke_check|"
        "r=rt_" + "a" * 32 + "|p=pg_" + "b" * 32,
    )
    assert long.total_modules >= short.total_modules
    assert long.size_points == short.size_points
    assert long.module_inches <= short.module_inches


def test_empty_payload_rejected():
    with pytest.raises(ValueError, match="nonempty"):
        measure_qr_print_baseline(require_layout(supported_layout_ids()[0]), "")
