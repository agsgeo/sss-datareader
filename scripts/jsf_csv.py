"""Extrai campos documentados de arquivos EdgeTech JSF para CSV.

O script le diretamente a estrutura binaria JSF, sem carregar as matrizes
de amplitude acustica. Para cada arquivo sao gerados:

    <nome>.csv              pings acusticos, com PORT e STBD pareados
    <nome>_2090.csv         navegacao/situacao do AUV
    <nome>_2080.csv         registros do DVL
    <nome>_mensagens.csv    contagem dos tipos de mensagem

Este script realiza somente extracao e decodificacao de campos. Nao executa
avaliacoes especificas nem classificacoes de resultados.

Referencia de formato:
EdgeTech, JSF File and Message Descriptions, documento 0023492.
"""

import argparse
import csv
import math
import struct
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


# Referencial geodesico informado por fonte documental externa ao JSF.
# Para SIRGAS 2000 geografico, use "EPSG:4674".
# Para WGS 84 geografico, use "EPSG:4326".
# Use None quando o referencial nao estiver documentalmente definido.
# Este campo apenas documenta o CRS; nenhuma coordenada JSF e transformada.
CRS_GEOGRAFICO_DECLARADO = "EPSG:4674"


# ---------------------------------------------------------------------------
# ESTRUTURA BINARIA JSF
# ---------------------------------------------------------------------------

# Cabecalho comum de 16 bytes:
# marker, versao, sessao, tipo, comando, subsistema, canal,
# sequencia, reservado, tamanho da mensagem seguinte.
CABECALHO_MENSAGEM = struct.Struct("<HBBHBBBBHI")

MARCADOR_JSF = 0x1601
MENSAGEM_SONAR = 80
MENSAGEM_DVL = 2080
MENSAGEM_SITUACAO = 2090
TAMANHO_CABECALHO_SONAR = 240


def u16(dados, offset):
    return struct.unpack_from("<H", dados, offset)[0]


def i16(dados, offset):
    return struct.unpack_from("<h", dados, offset)[0]


def u32(dados, offset):
    return struct.unpack_from("<I", dados, offset)[0]


def i32(dados, offset):
    return struct.unpack_from("<i", dados, offset)[0]


def u64(dados, offset):
    return struct.unpack_from("<Q", dados, offset)[0]


def f32(dados, offset):
    return struct.unpack_from("<f", dados, offset)[0]


def f64(dados, offset):
    return struct.unpack_from("<d", dados, offset)[0]


def data_hora_utc(timestamp_s):
    try:
        return datetime.fromtimestamp(timestamp_s, timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
    except (OverflowError, OSError, ValueError):
        return ""


def valor_finito(valor):
    return valor if isinstance(valor, (int, float)) and math.isfinite(valor) else ""


def rotulo_subsistema(numero):
    return {
        20: "CH12 / baixa frequencia",
        21: "CH34 / alta frequencia",
        22: "frequencia muito alta",
    }.get(numero, f"subsistema {numero}")


def coordenadas_type80(x_raw, y_raw, unidades):
    """Converte somente representacoes explicitamente definidas no JSF."""
    if unidades == 1:  # milimetros
        return x_raw / 1000.0, y_raw / 1000.0, "", ""
    if unidades == 2:  # minutos de arco multiplicados por 10000
        return "", "", y_raw / 600000.0, x_raw / 600000.0
    if unidades == 3:  # decimetros
        return x_raw / 10.0, y_raw / 10.0, "", ""
    if unidades == 4:  # centimetros
        return x_raw / 100.0, y_raw / 100.0, "", ""
    return "", "", "", ""


# ---------------------------------------------------------------------------
# DECODIFICACAO DAS MENSAGENS
# ---------------------------------------------------------------------------

def extrair_mensagem_80(cabecalho, dados, offset_arquivo):
    versao, subsistema, canal = cabecalho[1], cabecalho[5], cabecalho[6]

    msb = u16(dados, 16)
    lsb1 = u16(dados, 18)
    lsb2 = u16(dados, 20)
    validade = u16(dados, 30)

    segundos_1970 = u32(dados, 0)
    milissegundos_dia = u32(dados, 200)
    timestamp_ms = segundos_1970 * 1000 + milissegundos_dia % 1000
    timestamp_s = timestamp_ms / 1000.0

    numero_amostras = u16(dados, 114) | (((msb >> 8) & 0xF) << 16)
    intervalo_amostragem_ns = u32(dados, 116) + (lsb1 & 0xFF) / 256.0

    frequencia_inicial_dahz = u16(dados, 126) | ((msb & 0xF) << 16)
    frequencia_final_dahz = u16(dados, 128) | (((msb >> 4) & 0xF) << 16)
    duracao_varredura_ms = u16(dados, 130) + ((lsb2 >> 4) & 0x3FF) / 1000.0

    velocidade_nos = i16(dados, 194) / 10.0
    fracao_velocidade = (lsb2 & 0xF) / 100.0
    if velocidade_nos < 0:
        velocidade_nos -= fracao_velocidade
    else:
        velocidade_nos += fracao_velocidade

    x_raw = i32(dados, 80)
    y_raw = i32(dados, 84)
    unidades = i16(dados, 88)
    x_m, y_m, latitude, longitude = coordenadas_type80(
        x_raw, y_raw, unidades
    )

    velocidade_som = f32(dados, 148)
    if not (validade & (1 << 14)):
        velocidade_som = ""

    return {
        "offset_arquivo": offset_arquivo,
        "versao_protocolo": versao,
        "subsistema": subsistema,
        "designacao_subsistema": rotulo_subsistema(subsistema),
        "canal": canal,
        "ping_numero": u32(dados, 8),
        "pacote_numero": u16(dados, 220),
        "timestamp_ms": timestamp_ms,
        "data_hora_utc": data_hora_utc(timestamp_s),
        "segundos_desde_1970": segundos_1970,
        "milissegundos_do_dia": milissegundos_dia,
        "flags_validade": validade,
        "flags_validade_hex": f"0x{validade:04X}",
        "formato_dados": i16(dados, 34),
        "inicio_janela_amostras": u32(dados, 4),
        "numero_amostras": numero_amostras,
        "intervalo_amostragem_ns": intervalo_amostragem_ns,
        "frequencia_inicial_hz": frequencia_inicial_dahz * 10,
        "frequencia_final_hz": frequencia_final_dahz * 10,
        "largura_banda_hz": abs(
            frequencia_final_dahz - frequencia_inicial_dahz
        ) * 10,
        "duracao_varredura_ms": duracao_varredura_ms,
        "identificador_pulso": u16(dados, 142),
        "altitude_m": i32(dados, 144) / 1000.0
        if validade & (1 << 6)
        else "",
        "velocidade_som_mps": valor_finito(velocidade_som),
        "frequencia_mistura_hz": valor_finito(f32(dados, 152)),
        "rumo_graus": u16(dados, 172) / 100.0
        if validade & (1 << 3)
        else "",
        "pitch_graus": i16(dados, 174) * 180.0 / 32768.0
        if validade & (1 << 5)
        else "",
        "roll_graus": i16(dados, 176) * 180.0 / 32768.0
        if validade & (1 << 5)
        else "",
        "velocidade_nos": velocidade_nos
        if validade & (1 << 2)
        else "",
        "coordenadas_unidade": unidades,
        "x_ou_longitude_raw": x_raw,
        "y_ou_latitude_raw": y_raw,
        "x_m": x_m,
        "y_m": y_m,
        "latitude_graus": latitude,
        "longitude_graus": longitude,
        "crs_geografico_declarado": CRS_GEOGRAFICO_DECLARADO or "",
    }


def extrair_mensagem_2080(cabecalho, dados, offset_arquivo):
    validade = u32(dados, 12)
    timestamp_ms = u32(dados, 0) * 1000 + u32(dados, 4)
    vx = i16(dados, 32) / 1000.0
    vy = i16(dados, 34) / 1000.0
    vz = i16(dados, 36) / 1000.0

    velocidades_xy_validas = bool(validade & 1) and vx != -32.768 and vy != -32.768
    velocidade_z_valida = bool(validade & (1 << 2)) and vz != -32.768
    velocidade_som = u16(dados, 56)

    distancias = [i32(dados, 16 + 4 * indice) / 100.0 for indice in range(4)]

    return {
        "offset_arquivo": offset_arquivo,
        "versao_protocolo": cabecalho[1],
        "timestamp_ms": timestamp_ms,
        "data_hora_utc": data_hora_utc(timestamp_ms / 1000.0),
        "flags_validade": validade,
        "flags_validade_hex": f"0x{validade:08X}",
        "referencial_velocidade": "veiculo"
        if validade & (1 << 1)
        else "terrestre",
        "distancia_feixe_1_m": distancias[0] if distancias[0] > 0 else "",
        "distancia_feixe_2_m": distancias[1] if distancias[1] > 0 else "",
        "distancia_feixe_3_m": distancias[2] if distancias[2] > 0 else "",
        "distancia_feixe_4_m": distancias[3] if distancias[3] > 0 else "",
        "velocidade_x_mps": vx if velocidades_xy_validas else "",
        "velocidade_y_mps": vy if velocidades_xy_validas else "",
        "velocidade_z_mps": vz if velocidade_z_valida else "",
        "profundidade_m": u16(dados, 44) / 10.0
        if validade & (1 << 10)
        else "",
        "pitch_graus": i16(dados, 46) / 100.0
        if validade & (1 << 7)
        else "",
        "roll_graus": i16(dados, 48) / 100.0
        if validade & (1 << 8)
        else "",
        "rumo_graus": u16(dados, 50) / 100.0
        if validade & (1 << 6)
        else "",
        "salinidade_ppt": u16(dados, 52)
        if validade & (1 << 11)
        else "",
        "temperatura_c": i16(dados, 54) / 100.0
        if validade & (1 << 9)
        else "",
        "velocidade_som_mps": velocidade_som
        if validade & (1 << 12)
        else "",
    }


def extrair_mensagem_2090(cabecalho, dados, offset_arquivo):
    validade = u32(dados, 12)
    timestamp_us = u64(dados, 20)
    if validade & 1 and timestamp_us:
        timestamp_s = timestamp_us / 1_000_000.0
    else:
        timestamp_s = u32(dados, 0) + u32(dados, 4) / 1000.0
        timestamp_us = round(timestamp_s * 1_000_000)

    return {
        "offset_arquivo": offset_arquivo,
        "versao_protocolo": cabecalho[1],
        "timestamp_us": timestamp_us,
        "data_hora_utc": data_hora_utc(timestamp_s),
        "flags_validade": validade,
        "flags_validade_hex": f"0x{validade:08X}",
        "latitude_graus": f64(dados, 28)
        if validade & (1 << 1)
        else "",
        "longitude_graus": f64(dados, 36)
        if validade & (1 << 2)
        else "",
        "crs_geografico_declarado": CRS_GEOGRAFICO_DECLARADO or "",
        "profundidade_m": f64(dados, 44)
        if validade & (1 << 3)
        else "",
        "rumo_graus": f64(dados, 52)
        if validade & (1 << 4)
        else "",
        "pitch_graus": f64(dados, 60)
        if validade & (1 << 5)
        else "",
        "roll_graus": f64(dados, 68)
        if validade & (1 << 6)
        else "",
        "posicao_relativa_x_m": f64(dados, 76)
        if validade & (1 << 7)
        else "",
        "posicao_relativa_y_m": f64(dados, 84)
        if validade & (1 << 8)
        else "",
        "posicao_relativa_z_m": f64(dados, 92)
        if validade & (1 << 9)
        else "",
        "velocidade_x_mps": f64(dados, 100)
        if validade & (1 << 10)
        else "",
        "velocidade_y_mps": f64(dados, 108)
        if validade & (1 << 11)
        else "",
        "velocidade_z_mps": f64(dados, 116)
        if validade & (1 << 12)
        else "",
        "velocidade_norte_mps": f64(dados, 124)
        if validade & (1 << 13)
        else "",
        "velocidade_leste_mps": f64(dados, 132)
        if validade & (1 << 14)
        else "",
        "velocidade_baixo_mps": f64(dados, 140)
        if validade & (1 << 15)
        else "",
    }


# ---------------------------------------------------------------------------
# LEITURA DO ARQUIVO E PAREAMENTO DOS CANAIS
# ---------------------------------------------------------------------------

def ler_jsf(caminho):
    canais = {}
    registros_2090 = []
    registros_2080 = []
    contagens = Counter()

    with caminho.open("rb") as arquivo:
        while True:
            offset = arquivo.tell()
            bruto = arquivo.read(CABECALHO_MENSAGEM.size)
            if not bruto:
                break
            if len(bruto) != CABECALHO_MENSAGEM.size:
                raise ValueError(f"Cabecalho truncado no byte {offset}")

            cabecalho = CABECALHO_MENSAGEM.unpack(bruto)
            marcador = cabecalho[0]
            tipo = cabecalho[3]
            subsistema = cabecalho[5]
            canal = cabecalho[6]
            tamanho = cabecalho[9]

            if marcador != MARCADOR_JSF:
                raise ValueError(
                    f"Marcador invalido no byte {offset}: 0x{marcador:04X}"
                )

            contagens[(tipo, subsistema, canal, cabecalho[1])] += 1

            if tipo == MENSAGEM_SONAR:
                dados = arquivo.read(min(tamanho, TAMANHO_CABECALHO_SONAR))
                if len(dados) < TAMANHO_CABECALHO_SONAR:
                    raise ValueError(f"Mensagem 80 truncada no byte {offset}")
                arquivo.seek(tamanho - len(dados), 1)

                registro = extrair_mensagem_80(cabecalho, dados, offset)
                chave = (
                    registro["subsistema"],
                    registro["ping_numero"],
                    registro["canal"],
                )
                # Em arquivos com mais de um pacote por ping, conserva o
                # primeiro cabecalho, que identifica o inicio daquele ping.
                if chave not in canais or registro["pacote_numero"] == 1:
                    canais[chave] = registro

            elif tipo == MENSAGEM_DVL:
                dados = arquivo.read(tamanho)
                if len(dados) != tamanho:
                    raise ValueError(f"Mensagem 2080 truncada no byte {offset}")
                registros_2080.append(
                    extrair_mensagem_2080(cabecalho, dados, offset)
                )

            elif tipo == MENSAGEM_SITUACAO:
                dados = arquivo.read(tamanho)
                if len(dados) != tamanho:
                    raise ValueError(f"Mensagem 2090 truncada no byte {offset}")
                registros_2090.append(
                    extrair_mensagem_2090(cabecalho, dados, offset)
                )

            else:
                arquivo.seek(tamanho, 1)

    agrupados = defaultdict(dict)
    for (subsistema, ping_numero, canal), registro in canais.items():
        agrupados[(subsistema, ping_numero)][canal] = registro

    pings_pareados = []
    for (subsistema, ping_numero), lados in agrupados.items():
        port = lados.get(0)
        stbd = lados.get(1)
        referencia = port or stbd
        if referencia is None:
            continue

        timestamps = [
            lado["timestamp_ms"] for lado in (port, stbd) if lado is not None
        ]
        registro = {
            "subsistema": subsistema,
            "designacao_subsistema": rotulo_subsistema(subsistema),
            "ping_numero": ping_numero,
            "timestamp_ms": min(timestamps),
            "data_hora_utc": data_hora_utc(min(timestamps) / 1000.0),
            "diferenca_tempo_port_stbd_ms": abs(
                port["timestamp_ms"] - stbd["timestamp_ms"]
            )
            if port and stbd
            else "",
            "port_presente": port is not None,
            "stbd_presente": stbd is not None,
            "velocidade_type80_nos": referencia["velocidade_nos"],
            "altitude_type80_m": referencia["altitude_m"],
            "rumo_type80_graus": referencia["rumo_graus"],
            "pitch_type80_graus": referencia["pitch_graus"],
            "roll_type80_graus": referencia["roll_graus"],
            "coordenadas_unidade": referencia["coordenadas_unidade"],
            "x_m": referencia["x_m"],
            "y_m": referencia["y_m"],
            "latitude_graus": referencia["latitude_graus"],
            "longitude_graus": referencia["longitude_graus"],
            "crs_geografico_declarado": referencia[
                "crs_geografico_declarado"
            ],
        }

        for prefixo, lado in (("port", port), ("stbd", stbd)):
            campos = (
                "offset_arquivo",
                "versao_protocolo",
                "pacote_numero",
                "flags_validade_hex",
                "formato_dados",
                "inicio_janela_amostras",
                "numero_amostras",
                "intervalo_amostragem_ns",
                "frequencia_inicial_hz",
                "frequencia_final_hz",
                "largura_banda_hz",
                "duracao_varredura_ms",
                "identificador_pulso",
                "velocidade_som_mps",
                "frequencia_mistura_hz",
            )
            for campo in campos:
                registro[f"{prefixo}_{campo}"] = lado[campo] if lado else ""

        pings_pareados.append(registro)

    pings_pareados.sort(
        key=lambda linha: (
            linha["subsistema"],
            linha["timestamp_ms"],
            linha["ping_numero"],
        )
    )
    registros_2090.sort(key=lambda linha: linha["timestamp_us"])
    registros_2080.sort(key=lambda linha: linha["timestamp_ms"])

    registros_contagem = [
        {
            "tipo_mensagem": chave[0],
            "subsistema": chave[1],
            "canal": chave[2],
            "versao_protocolo": chave[3],
            "quantidade": quantidade,
        }
        for chave, quantidade in sorted(contagens.items())
    ]

    return pings_pareados, registros_2090, registros_2080, registros_contagem


# ---------------------------------------------------------------------------
# EXPORTACAO CSV
# ---------------------------------------------------------------------------

def salvar_csv(caminho, registros):
    if not registros:
        return False
    with caminho.open("w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=list(registros[0].keys()),
            extrasaction="ignore",
        )
        escritor.writeheader()
        escritor.writerows(registros)
    return True


def gerar_csv(caminho, indice, saida):
    print(f"\n[{indice + 1}] {caminho.name}")
    try:
        pings, situacao, dvl, mensagens = ler_jsf(caminho)

        arquivos_saida = (
            (saida / f"{caminho.stem}.csv", pings),
            (saida / f"{caminho.stem}_2090.csv", situacao),
            (saida / f"{caminho.stem}_2080.csv", dvl),
            (saida / f"{caminho.stem}_mensagens.csv", mensagens),
        )

        for arquivo_saida, registros in arquivos_saida:
            if salvar_csv(arquivo_saida, registros):
                print(f"  {len(registros):>7} registros -> {arquivo_saida.name}")

    except Exception as erro:
        print(f"  [ERRO] {erro}")
        import traceback

        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="Extrai registros de arquivos JSF para CSV."
    )
    parser.add_argument("entrada", type=Path, help="Pasta com os arquivos JSF")
    parser.add_argument("saida", type=Path, help="Pasta de destino dos CSVs")
    args = parser.parse_args()

    pasta = args.entrada
    saida = args.saida
    saida.mkdir(parents=True, exist_ok=True)
    arquivos = sorted(pasta.glob("*.jsf"), key=lambda caminho: caminho.name)

    print(f"JSF -> CSV | {len(arquivos)} arquivo(s)")
    print(f"Entrada: {pasta}")
    print(f"Saida:   {saida}")
    print(
        "CRS geografico declarado externamente: "
        f"{CRS_GEOGRAFICO_DECLARADO or 'nao definido'}"
    )

    for indice, caminho in enumerate(arquivos):
        gerar_csv(caminho, indice, saida)

    print("\nConcluido.")


if __name__ == "__main__":
    main()
