"""Pruebas unitarias de las reglas de calidad. Ejecutar: python -m pytest seccion_3 -q"""
from datetime import date

import pandas as pd
import pytest

import validar_calidad_facturacion as v

CFG = v.Configuracion(fecha_referencia=date(2026, 9, 25))


def validar_filas(filas):
    df = pd.DataFrame(filas, columns=v.COLUMNAS).astype(str)
    df.insert(0, "fila_origen", range(2, len(df) + 2))
    return v.validar(df, CFG)


@pytest.mark.parametrize("entrada,esperado", [
    ("12", 12), (" 12 ", 12), ("CLI-0012", 12), ("cli_12", 12), ("00012", 12), ("12.0", 12), ("C12", 12),
    ("ABC", None), ("-15", None), ("12-A", None), ("0", None), ("CLIENTE", None),
])
def test_normalizar_id(entrada, esperado):
    assert v.normalizar_id(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("2026-08-01", date(2026, 8, 1)), ("01/08/2026", date(2026, 8, 1)), ("2026/08", date(2026, 8, 1)),
    ("08-2026", date(2026, 8, 1)), ("202608", date(2026, 8, 1)), ("ago-2026", date(2026, 8, 1)),
    ("Agosto 2026", date(2026, 8, 1)), ("2026-08-15", date(2026, 8, 1)),
    ("2026-13-01", None), ("31/02/2026", None), ("sin periodo", None),
])
def test_normalizar_periodo(entrada, esperado):
    assert v.normalizar_periodo(entrada)[0] == esperado


def test_registro_limpio_es_valido():
    r = validar_filas([["1", "2026-08-01", "10", "500000"]])
    assert r.valido.all() and r.advertencias.iloc[0] == ""


def test_completitud_y_validez():
    r = validar_filas([["", "2026-08-01", "10", "1"], ["2", "2026-08-01", "-3", "1"],
                       ["3", "2026-08-01", "10", "-100"], ["4", "2026-08-01", "N/D", "abc"]])
    assert r.reglas[0] == ["COM_ID_NULO"]
    assert r.reglas[1] == ["VAL_TRABAJADORES_RANGO"]
    assert r.reglas[2] == ["VAL_VALOR_RANGO"]
    assert r.reglas[3] == ["COM_TRABAJADORES_NULO", "VAL_VALOR_RANGO"]


def test_consistencia():
    r = validar_filas([["1", "2026-08-01", "0", "900000"], ["2", "2026-08-01", "0", "0"]])
    assert r.reglas[0] == ["CON_TRABAJADORES_CERO"] and r.valido[1]


def test_oportunidad():
    r = validar_filas([["1", "2026-11-01", "5", "1"], ["2", "2026-07-01", "5", "1"],
                       ["3", "2026-06-01", "5", "1"], ["4", "2026-09-01", "5", "1"]])
    assert r.reglas[0] == ["OPO_PERIODO_FUTURO"]
    assert r.valido[1]                               # julio cerró el 31/07: 56 días de atraso
    assert r.reglas[2] == ["OPO_ATRASO_MAYOR_60D"]   # junio cerró el 30/06: 87 días
    assert r.valido[3]


def test_unicidad_exacto_conflicto_y_rescate():
    r = validar_filas([
        ["1", "2026-08-01", "10", "100"], ["CLI-0001", "01/08/2026", "10", "100"],   # exacto (formatos distintos)
        ["2", "2026-08-01", "10", "100"], ["2", "2026-08", "12", "100"],             # conflicto
        ["3", "2026-08-01", "-1", "100"], ["3", "2026-08-01", "10", "100"],          # el malo no tumba al bueno
    ])
    assert r.valido[0] and r.reglas[1] == ["UNI_DUPLICADO_EXACTO"]
    assert r.reglas[2] == r.reglas[3] == ["UNI_DUPLICADO_CONFLICTO"]
    assert not r.valido[4] and r.valido[5]


def test_esquema_incompleto(tmp_path):
    ruta = tmp_path / "malo.csv"
    ruta.write_text("id_cliente,periodo\n1,2026-08-01\n", encoding="utf-8")
    with pytest.raises(v.ErrorCarga):
        v.cargar_archivo(ruta)


def test_flujo_completo(tmp_path):
    entrada = tmp_path / "prueba.csv"
    v.generar_archivo_prueba(entrada, 600, CFG.fecha_referencia)
    rep = v.ejecutar(entrada, tmp_path / "out", CFG)
    assert rep["total_registros"] >= 1000
    assert rep["registros_validos"] + rep["registros_rechazados"] == rep["total_registros"]
    for dim in v.DIMENSIONES:
        assert rep["score_por_dimension"][dim]["incumplen"] > 0          # cada problema fue sembrado
    validos = pd.read_parquet(tmp_path / "out" / "facturacion_validos.parquet")
    assert len(validos) == rep["registros_validos"]
    assert not validos.duplicated(["id_cliente", "periodo"]).any()
    rech = pd.read_excel(tmp_path / "out" / "facturacion_rechazados.xlsx")
    assert len(rech) == rep["registros_rechazados"] and rech.razon_rechazo.notna().all()
