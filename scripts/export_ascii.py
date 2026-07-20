import argparse
import struct
import math
import csv
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict

# Tentativa de importar dependências do XTF (caso o usuário processe XTF)
try:
    import pyxtf
    import pandas as pd
    from pyproj import CRS, Transformer
    XTF_DISPONIVEL = True
    KNO_TO_MS = 0.514444
except ImportError:
    XTF_DISPONIVEL = False

# Configurações de CRS padrão herdadas dos seus scripts
CRS_GEOGRAFICO_JSF = "EPSG:4674"  #
CRS_PROJETADO_XTF = "EPSG:31984"   #[cite: 7]

# --- FUNÇÕES AUXILIARES DE COORDENADAS E PARSE (Herdadas do jsf_csv.py) ---
CABECALHO_MENSAGEM = struct.Struct("<HBBHBBBBHI")  #[cite: 8]
MARCADOR_JSF = 0x1601  #[cite: 8]
MENSAGEM_SONAR = 80  #[cite: 8]
MENSAGEM_DVL = 2080  #[cite: 8]
MENSAGEM_SITUACAO = 2090  #[cite: 8]
TAMANHO_CABECALHO_SONAR = 240  #[cite: 8]

def u16(dados, offset): return struct.unpack_from("<H", dados, offset)[0]  #[cite: 8]
def i16(dados, offset): return struct.unpack_from("<h", dados, offset)[0]  #[cite: 8]
def u32(dados, offset): return struct.unpack_from("<I", dados, offset)[0]  #[cite: 8]
def i32(dados, offset): return struct.unpack_from("<i", dados, offset)[0]  #[cite: 8]
def u64(dados, offset): return struct.unpack_from("<Q", dados, offset)[0]  #[cite: 8]
def f32(dados, offset): return struct.unpack_from("<f", dados, offset)[0]  #[cite: 8]
def f64(dados, offset): return struct.unpack_from("<d", dados, offset)[0]  #[cite: 8]

def data_hora_utc(timestamp_s):  #[cite: 8]
    try: return datetime.fromtimestamp(timestamp_s, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  #[cite: 8]
    except: return ""  #[cite: 8]

def coordenadas_type80(x_raw, y_raw, unidades):  #[cite: 8]
    if unidades == 1: return x_raw / 1000.0, y_raw / 1000.0, "", ""  #[cite: 8]
    if unidades == 2: return "", "", y_raw / 600000.0, x_raw / 600000.0  #[cite: 8]
    if unidades == 3: return x_raw / 10.0, y_raw / 10.0, "", ""  #[cite: 8]
    if unidades == 4: return x_raw / 100.0, y_raw / 100.0, "", ""  #[cite: 8]
    return "", "", "", ""  #[cite: 8]

# --- PROCESSAMENTO JSF ---
def processar_jsf(caminho, pasta_saida):
    # Lógica de extração idêntica simplificada do jsf_csv para focar no output ASCII
    # (Coleta pings de sonar pareando canais PORT e STBD)
    canais = {}
    with caminho.open("rb") as arquivo:
        while True:
            offset = arquivo.tell()
            bruto = arquivo.read(CABECALHO_MENSAGEM.size)
            if not bruto: break
            cabecalho = CABECALHO_MENSAGEM.unpack(bruto)
            tipo, subsistema, canal, tamanho = cabecalho[3], cabecalho[5], cabecalho[6], cabecalho[9]
            
            if tipo == MENSAGEM_SONAR:
                dados = arquivo.read(min(tamanho, TAMANHO_CABECALHO_SONAR))
                arquivo.seek(tamanho - len(dados), 1)
                
                # Decodificação direta simplificada baseada no original
                msb, validade = u16(dados, 16), u16(dados, 30)  #[cite: 8]
                segundos_1970, milissegundos_dia = u32(dados, 0), u32(dados, 200)  #[cite: 8]
                timestamp_ms = segundos_1970 * 1000 + milissegundos_dia % 1000  #[cite: 8]
                ping_num = u32(dados, 8)  #[cite: 8]
                
                x_raw, y_raw, unidades = i32(dados, 80), i32(dados, 84), i16(dados, 88)  #[cite: 8]
                x_m, y_m, lat, lon = coordenadas_type80(x_raw, y_raw, unidades)  #[cite: 8]
                
                registro = {
                    "ping": ping_num, "timestamp_ms": timestamp_ms, "utc": data_hora_utc(timestamp_ms/1000.0),
                    "lat": lat if lat else y_m, "lon": lon if lon else x_m, 
                    "rumo": u16(dados, 172) / 100.0 if validade & (1 << 3) else "",  #[cite: 8]
                    "altitude": i32(dados, 144) / 1000.0 if validade & (1 << 6) else ""  #[cite: 8]
                }
                canais[(subsistema, ping_num, canal)] = registro
            else:
                arquivo.seek(tamanho, 1)

    # Agrupa e salva em ASCII Tabular (.txt)
    agrupados = defaultdict(dict)
    for (sub, ping, chan), reg in canais.items():
        agrupados[(sub, ping)][chan] = reg

    arquivo_txt = pasta_saida / f"{caminho.stem}_jsf_ascii.txt"
    with arquivo_txt.open("w", encoding="utf-8") as f:
        # Cabeçalho do arquivo ASCII separado por TAB
        f.write("PING\tTIMESTAMP_MS\tUTC_DATETIME\tLAT_Y\tLON_X\tRUMO\tALTITUDE\n")
        for (sub, ping), lados in sorted(agrupados.items()):
            ref = lados.get(0) or lados.get(1)
            if ref:
                f.write(f"{ref['ping']}\t{ref['timestamp_ms']}\t{ref['utc']}\t{ref['lat']}\t{ref['lon']}\t{ref['rumo']}\t{ref['altitude']}\n")
    print(f"      -> ASCII exportado: {arquivo_txt.name}")

# --- PROCESSAMENTO XTF ---
def processar_xtf(caminho, pasta_saida):
    if not XTF_DISPONIVEL:
        print("      [ERRO] Bibliotecas pyxtf/pandas/pyproj não encontradas. Instale os requirements.txt")  #[cite: 6]
        return

    # Lógica de extração idêntica adaptada do seu script original xtf_csv.py
    try:
        fh, packets = pyxtf.xtf_read(str(caminho))  #[cite: 7]
    except Exception as e:
        print(f"      [ERRO] Falha ao ler XTF: {e}")
        return

    chave = next(iter(packets), None)  #[cite: 7]
    if chave is None or not packets[chave]: return

    pings = packets[chave]  #[cite: 7]
    
    # Criar transformador de CRS geodésico
    crs_proj = CRS.from_user_input(CRS_PROJETADO_XTF)  #[cite: 7]
    transformer = Transformer.from_crs(crs_proj, crs_proj.geodetic_crs, always_xy=True)  #[cite: 7]

    arquivo_txt = pasta_saida / f"{caminho.stem}_xtf_ascii.txt"
    with arquivo_txt.open("w", encoding="utf-8") as f:
        f.write("PING\tEVENTO\tUTC_DATETIME\tSENSOR_X\tSENSOR_Y\tRUMO\tVELOCIDADE_MS\tALTITUDE\n")
        
        for p in pings:
            # Recupera data e hora
            try: dt = datetime(p.Year, p.Month, p.Day, p.Hour, p.Minute, p.Second, p.HSeconds * 10000)  #[cite: 7]
            except: dt = None
            dt_str = dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:22] if dt else ''  #[cite: 7]

            # Transformação de coordenadas baseada nas unidades[cite: 7]
            x, y = p.SensorXcoordinate, p.SensorYcoordinate  #[cite: 7]
            if fh.NavUnits == 0:  # Projetado[cite: 7]
                try: lon, lat = transformer.transform(x, y)  #[cite: 7]
                except: lat, lon = x, y
            else:
                lat, lon = y, x

            vel_ms = round(p.ShipSpeed * KNO_TO_MS, 4)  #[cite: 7]
            
            f.write(f"{p.PingNumber}\t{p.EventNumber}\t{dt_str}\t{round(lon,7)}\t{round(lat,7)}\t{round(p.SensorHeading, 2)}\t{vel_ms}\t{round(p.SensorPrimaryAltitude, 3)}\n")  #[cite: 7]
    print(f"      -> ASCII exportado: {arquivo_txt.name}")

# --- CONTROLE PRINCIPAL ---
def main():
    parser = argparse.ArgumentParser(description="Conversor unificado de Datagramas SSS (JSF/XTF) para ASCII tabular puro.")
    parser.add_argument("entrada", type=Path, help="Pasta de entrada contendo arquivos .jsf ou .xtf")
    parser.add_argument("saida", type=Path, help="Pasta de destino dos arquivos ASCII")
    args = parser.parse_args()

    args.saida.mkdir(parents=True, exist_ok=True)

    # Varre ambos os tipos de arquivo na pasta informada
    arquivos_jsf = sorted(args.entrada.glob("*.jsf"))
    arquivos_xtf = sorted(args.entrada.glob("*.xtf"))

    print(f"ASCII Exporter | Encontrados {len(arquivos_jsf)} arquivo(s) JSF e {len(arquivos_xtf)} arquivo(s) XTF.")

    for i, arq in enumerate(arquivos_jsf):
        print(f"\n  [{i+1}] Processando JSF: {arq.name}")
        processar_jsf(arq, args.saida)

    for i, arq in enumerate(arquivos_xtf):
        print(f"\n  [{i+1}] Processando XTF: {arq.name}")
        processar_xtf(arq, args.saida)

    print("\nConcluído com sucesso.")

if __name__ == "__main__":
    main()