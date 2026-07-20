# SSSdatareader

Ferramentas em Python para leitura estruturada e exportação de dados de sonar
de varredura lateral nos formatos EdgeTech JSF e XTF.

O projeto torna a leitura dos datagramas reproduzivel, preservando campos
brutos relevantes e exportando tabelas CSV ou ASCII. Ele se limita a leitura,
decodificação e exportação dos registros.

## Conteúdo

```text
sss-datareader/
|-- scripts/
|   |-- jsf_csv.py       # Leitura de JSF e exportacao para CSV
|   |-- xtf_csv.py       # Leitura de XTF e exportacao para CSV
|   `-- export_ascii.py  # Exportacao resumida de JSF ou XTF para ASCII
|-- README.md
|-- CITATION.cff
|-- .zenodo.json
|-- LICENSE
|-- requirements.txt
`-- SHA256SUMS.txt
```

## Requisitos

Python 3.10 ou superior e recomendado. Instale as dependencias com:

```bash
python -m pip install -r requirements.txt
```

O leitor JSF utiliza apenas a biblioteca padrao do Python. O processamento de
XTF e a exportação XTF para ASCII utilizam `pyxtf`, `numpy`, `pandas` e
`pyproj`.

## Uso

### JSF para CSV

```bash
python scripts/jsf_csv.py /caminho/pasta_jsf /caminho/pasta_saida
```

Para cada arquivo JSF são gerados, quando houver registros correspondentes:

```text
<nome>.csv
<nome>_2080.csv
<nome>_2090.csv
<nome>_mensagens.csv
```

O arquivo principal contem os pings acústicos com os canais PORT e STBD
pareados por subsistema e numero do ping. As mensagens 2080 e 2090 sao
exportadas separadamente para preservar os registros auxiliares.

### XTF para CSV

```bash
python scripts/xtf_csv.py /caminho/pasta_xtf /caminho/pasta_saida
```

O sistema de referencia utilizado para documentar as coordenadas XTF esta
definido no inicio de `scripts/xtf_csv.py`. Revise esse parametro antes de
usar o script em um conjunto de dados cujo CRS nao esteja documentalmente
definido.

### JSF ou XTF para ASCII

```bash
python scripts/export_ascii.py /caminho/pasta_dados /caminho/pasta_saida
```

Essa exportação é resumida e destina-se a inspecao tabular simples. Para uma
extração completa, utilize os conversores especificos JSF ou XTF.

## Reprodutibilidade

Os hashes SHA-256 dos scripts publicados estão em `SHA256SUMS.txt`. Os hashes
identificam o conteudo exato de cada versão e devem ser registrados quando o
script for usado em uma analise reproduzivel.

O projeto nao inclui dados JSF, XTF, CSV, planilhas ou dados proprietarios de
qualquer campanha. Dados de terceiros devem ser utilizados somente quando
houver autorizacao para isso.

## Citação

Consulte `CITATION.cff` para a citacao recomendada. O arquivo `.zenodo.json`
fornece os metadados especificos usados pelo Zenodo para arquivar uma release.
Quando os dois arquivos estiverem presentes, o Zenodo usa o `.zenodo.json`
para o registro da release.

Apos a criacao de uma release no GitHub, o repositorio pode ser conectado ao
Zenodo para gerar um DOI permanente. O DOI da versao arquivada deve ser
acrescentado ao `CITATION.cff` e ao README depois que o Zenodo concluir o
deposito.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21460296.svg)](https://doi.org/10.5281/zenodo.21460296)

## Licença

Este projeto é distribuido sob a licenca MIT. Consulte o arquivo `LICENSE`.
