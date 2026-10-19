"""Pruebas de la regla de comisiones (no requieren base de datos).

Ejecutar:  pip install pytest  &&  pytest -q
"""
from decimal import Decimal

from app.services import base_comision, calcular_comision


def test_piezas_no_generan_comision():
    # $650 de mano de obra + $2,000 de piezas -> la base es sólo la mano de obra
    base = base_comision(Decimal("650"), Decimal("2000"), Decimal("2650"))
    assert base == Decimal("650.00")
    assert calcular_comision(base, Decimal("15")) == Decimal("97.50")


def test_orden_solo_piezas_no_genera_comision():
    assert base_comision(0, Decimal("1200"), Decimal("1200")) == Decimal("0.00")


def test_orden_antigua_sin_detalle_usa_total():
    assert base_comision(0, 0, Decimal("500")) == Decimal("500.00")


def test_redondeo_a_centavos():
    assert calcular_comision(Decimal("333.33"), Decimal("15")) == Decimal("50.00")
    assert calcular_comision(Decimal("100.10"), Decimal("12.5")) == Decimal("12.51")


def test_porcentaje_cero():
    assert calcular_comision(Decimal("1000"), Decimal("0")) == Decimal("0.00")
