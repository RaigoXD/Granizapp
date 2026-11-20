"""Formatos de dinero y cantidades: lo que se muestra debe poder volver a leerse igual."""
import pytest

from granizapp.core.utils import fmt_money, fmt_number, parse_float, parse_money


@pytest.mark.parametrize("value", [0, 1, 2.5, 320, 1500, 6000, 1234.56, 12000, 1_250_000, 0.25, 0.333])
def test_number_round_trip(value):
    shown = fmt_number(value, 3)
    assert parse_float(shown) == pytest.approx(value, abs=1e-3), (value, shown)


@pytest.mark.parametrize("text,expected", [
    ("6.000", 6000), ("1.500", 1500), ("2.5", 2.5), ("2,5", 2.5), ("1.234,5", 1234.5), ("1,234.5", 1234.5),
    ("0.250", 0.25), ("0,250", 0.25), ("320", 320), (" 12 ", 12), ("-3", -3), ("abc", 0.0), ("", 0.0),
    ("12.34", 12.34), ("1.250.000", 1_250_000),
])
def test_parse_float(text, expected):
    assert parse_float(text) == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [
    ("14000", 14000), ("14.000", 14000), ("$ 14.000", 14000), ("14k", 14000), ("1,5k", 1500), ("1.5k", 1500),
    ("1.2m", 1_200_000), ("-500", -500), ("", 0), ("x", 0),
])
def test_parse_money(text, expected):
    assert parse_money(text) == expected


def test_money_round_trip():
    for v in (0, 500, 14000, 1_250_000):
        assert parse_money(fmt_money(v)) == v
