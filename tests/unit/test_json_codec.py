import math

import pytest

from browser_automation.json_codec import StrictJsonError, dumps_strict, loads_strict


@pytest.mark.parametrize(
    "source",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        '[1,{"nested":NaN}]',
        "1e999",
        '{"nested":[-1e999]}',
    ],
)
def test_strict_decoder_rejects_named_and_overflow_non_finite_values(source: str) -> None:
    with pytest.raises(StrictJsonError):
        loads_strict(source)


@pytest.mark.parametrize(
    "value",
    [
        math.nan,
        math.inf,
        -math.inf,
        {"nested": [math.nan]},
        [1, {"nested": -math.inf}],
    ],
)
def test_strict_encoder_rejects_scalar_and_nested_non_finite_values(value) -> None:
    with pytest.raises(StrictJsonError):
        dumps_strict(value)


def test_strict_codec_preserves_normal_json_values() -> None:
    value = {"number": 1.25, "nested": [True, None, "text"]}
    assert loads_strict(dumps_strict(value)) == value


@pytest.mark.parametrize(
    "value",
    [
        "\ud800",
        "\udfff",
        {"nested": ["\ud800"]},
        {"nested": ["\udfff"]},
    ],
)
def test_strict_encoder_escapes_lone_surrogates_for_utf8_sinks(value) -> None:
    encoded = dumps_strict(value)
    encoded_bytes = encoded.encode("utf-8", errors="strict")
    assert loads_strict(encoded_bytes.decode("utf-8")) == value
