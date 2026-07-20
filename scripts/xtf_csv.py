import argparse
import pyxtf
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from pyproj import CRS, Transformer

KNO_TO_MS   = 0.514444

# Sistema de referencia das coordenadas X/Y gravadas nos arquivos XTF.
# Para SIRGAS 2000 / UTM zona 24S, use "EPSG:31984".
# Para WGS 84 / UTM zona 24S, use "EPSG:32724".
# Use None quando o sistema de referencia nao estiver documentalmente definido;
# nesse caso, X/Y serao exportados sem conversao para latitude/longitude.
CRS_COORDENADAS_XTF = "EPSG:31984"


def criar_transformador(crs_origem):
    if not crs_origem:
        return None
    crs_projetado = CRS.from_user_input(crs_origem)
    return Transformer.from_crs(
        crs_projetado, crs_projetado.geodetic_crs, always_xy=True
    )


def coordenadas_geograficas(x, y, nav_units, transformer):
    if not x or not y:
        return None, None

    if nav_units == 3:
        lon, lat = x, y
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            return round(lat, 7), round(lon, 7)
        return None, None

    if nav_units != 0 or transformer is None:
        return None, None

    try:
        lon, lat = transformer.transform(x, y)
        return round(lat, 7), round(lon, 7)
    except Exception:
        return None, None


def ping_datetime(p):
    try:
        return datetime(p.Year, p.Month, p.Day,
                        p.Hour, p.Minute, p.Second,
                        p.HSeconds * 10_000)
    except Exception:
        return None


def extrair_chan_header(ch):
    def g(attr, default=0):
        v = getattr(ch, attr, default)
        return v if v is not None else default
    return {
        'slant_range_m':   float(g('SlantRange', 0.0)),
        'time_delay_ms':   float(g('TimeDelay',  0.0)),
        'frequency_hz':    int(g('Frequency',    0)),
        'num_amostras':    int(g('NumSamples',   0)),
        'bandwidth_hz':    int(g('BandWidth',    0)) * 100 if g('BandWidth') else 0,
        'pulse_length_us': int(g('FixedVSOP',    0)),
        'gain_code':       int(g('GainCode',     0)),
        'init_gain':       int(g('InitialGainCode', 0)),
        'weight':          int(g('Weight',       0)),
    }


def extrair_pings(pings, nav_units, transformer):
    registros = []
    for p in pings:
        dt  = ping_datetime(p)
        lat, lon = coordenadas_geograficas(
            p.SensorXcoordinate,
            p.SensorYcoordinate,
            nav_units,
            transformer,
        )

        chs = getattr(p, 'ping_chan_headers', [])
        ch0 = extrair_chan_header(chs[0]) if len(chs) >= 1 else {}
        ch1 = extrair_chan_header(chs[1]) if len(chs) >= 2 else {}

        n_am0 = ch0.get('num_amostras') or (len(p.data[0]) if p.data else 0)
        n_am1 = ch1.get('num_amostras') or (len(p.data[1]) if len(p.data) > 1 else 0)
        sr0   = ch0.get('slant_range_m') or float(getattr(p, 'Range', 0) or 0)
        sr1   = ch1.get('slant_range_m') or float(getattr(p, 'Range', 0) or 0)

        registros.append({
            'ping_numero':        p.PingNumber,
            'evento':             p.EventNumber,
            'datetime_utc':       dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:22] if dt else '',
            'nav_fix_ms':         p.NavFixMilliseconds,
            'nav_units':          nav_units,
            'sensor_x_raw':       round(p.SensorXcoordinate, 7),
            'sensor_y_raw':       round(p.SensorYcoordinate, 7),
            'latitude_graus':     lat,
            'longitude_graus':    lon,
            'rumo_graus':         round(p.SensorHeading, 2),
            'velocidade_nos':     round(p.ShipSpeed, 4),
            'velocidade_ms':      round(p.ShipSpeed * KNO_TO_MS, 4),
            'pitch_graus':        round(p.SensorPitch, 3),
            'roll_graus':         round(p.SensorRoll, 3),
            'prof_agua_m':        round(p.SensorDepth, 3),
            'altitude_fundo_m':   round(p.SensorPrimaryAltitude, 3),
            'vel_som_oneway_ms':  round(p.SoundVelocity, 1),
            'vel_som_real_ms':    round(p.SoundVelocity * 2, 1),
            'port_slant_range_m': sr0,
            'port_num_amostras':  n_am0,
            'port_frequencia_hz': ch0.get('frequency_hz', 0),
            'port_time_delay_ms': ch0.get('time_delay_ms', 0),
            'port_bandwidth_hz':  ch0.get('bandwidth_hz', 0),
            'port_pulse_us':      ch0.get('pulse_length_us', 0),
            'port_gain':          ch0.get('gain_code', 0),
            'stbd_slant_range_m': sr1,
            'stbd_num_amostras':  n_am1,
            'stbd_frequencia_hz': ch1.get('frequency_hz', 0),
            'stbd_time_delay_ms': ch1.get('time_delay_ms', 0),
            'stbd_bandwidth_hz':  ch1.get('bandwidth_hz', 0),
            'stbd_pulse_us':      ch1.get('pulse_length_us', 0),
            'stbd_gain':          ch1.get('gain_code', 0),
        })
    return pd.DataFrame(registros)


def gerar_csv(caminho: Path, idx: int, saida_dir: Path, transformer):
    print(f"\n  [{idx+1}] {caminho.name}")

    try:
        fh, packets = pyxtf.xtf_read(str(caminho))
    except Exception as e:
        print(f"      [ERRO] {e}")
        return

    chave = next(iter(packets), None)
    if chave is None or not packets[chave]:
        print(f"      [AVISO] Sem pacotes sonar.")
        return

    pings = packets[chave]
    print(f"      {len(pings)} pings lidos")

    try:
        df = extrair_pings(pings, fh.NavUnits, transformer)
        saida = saida_dir / (caminho.stem + ".csv")
        df.to_csv(str(saida), index=False, encoding='utf-8')
        print(f"      -> {saida}")
    except Exception as e:
        print(f"      [ERRO] {e}")
        import traceback; traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="Extrai os registros de arquivos XTF para CSV."
    )
    parser.add_argument("entrada", type=Path, help="Pasta com os arquivos XTF")
    parser.add_argument("saida", type=Path, help="Pasta de destino dos CSVs")
    args = parser.parse_args()

    pasta = args.entrada
    saida_dir = args.saida
    saida_dir.mkdir(parents=True, exist_ok=True)

    transformer = criar_transformador(CRS_COORDENADAS_XTF)
    arquivos = sorted(pasta.glob("*.xtf"), key=lambda p: p.name)

    print(f"XTF -> CSV  |  {len(arquivos)} arquivo(s)")
    print(f"Entrada: {pasta}  |  Saida: {saida_dir}\n")
    print(f"CRS informado para X/Y: {CRS_COORDENADAS_XTF or 'nao definido'}\n")

    for i, arq in enumerate(arquivos):
        gerar_csv(arq, i, saida_dir, transformer)

    print(f"\nConcluido.")


if __name__ == "__main__":
    main()
