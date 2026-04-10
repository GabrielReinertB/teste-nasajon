# NASAJON – Prova Técnica

## Pré-requisitos

- Python 3.10+ instalado
- Conexão com internet (API IBGE + Supabase)
- `ACCESS_TOKEN` JWT obtido via login no Supabase (Postman ou curl)

## Como rodar

### 1. Instalar dependências
```powershell
python -m pip install -r requirements.txt
```

### 2. Executar
Passe o `ACCESS_TOKEN` como argumento:
```powershell
python main.py <SEU_ACCESS_TOKEN>
```
Ou exporte como variável de ambiente e rode sem argumento:
```powershell
$env:ACCESS_TOKEN="<SEU_ACCESS_TOKEN>"
python main.py
```

### 3. Saídas esperadas
- **Console**: progresso do matching, estatísticas calculadas e resposta JSON da API de correção (incluindo o `score`).
- **`resultado.csv`**: gerado automaticamente na mesma pasta.

## O que o programa faz

1. Lê `input.csv` (municípios + populações)
2. Busca todos os municípios da API pública do IBGE (`/localidades/municipios`)
3. Faz matching por nome (exato → fuzzy com `rapidfuzz`) para obter nome oficial, UF, região e código IBGE
4. Gera `resultado.csv` com colunas: `municipio_input, populacao_input, municipio_ibge, uf, regiao, id_ibge, status`
5. Calcula estatísticas: `total_municipios`, `total_ok`, `total_nao_encontrado`, `total_erro_api`, `pop_total_ok`, `medias_por_regiao`
6. Envia as estatísticas via POST para a Edge Function da Nasajon com `Authorization: Bearer <token>`

## Decisões técnicas

- **Normalização de nomes**: `unicodedata.normalize` remove acentos antes de comparar, tornando "Florianopolis" equivalente a "Florianópolis".
- **Fuzzy matching**: `rapidfuzz.fuzz.token_sort_ratio` com threshold de 80 captura erros de digitação como "Belo Horzionte" → "Belo Horizonte" e "Santoo Andre" → "Santo André".
- **Duplicatas/entradas inválidas**: "Santo Andre" → match exato com "Santo André" (`OK`). "Santoo Andre" também encontra fuzzy match com "Santo André", mas como aquele ID IBGE já foi reivindicado pela linha anterior, recebe `NAO_ENCONTRADO`. Isso reflete a intenção do enunciado: a entrada com erro de digitação grave é considerada não encontrada.
- **Fonte única de dados IBGE**: um único GET em `/municipios` carrega todos os ~5.570 municípios em memória; evita múltiplos requests por entrada.
