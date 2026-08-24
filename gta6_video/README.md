# GTA 6 — Variações de vídeo (Lucia & Jason)

8 variações do vídeo original `GTA6_Lucia_Jason_60s.mp4`, todas em **1080×1920 (9:16)**,
com narração em PT-BR, legendas e títulos próprios — e **sem música** (só narração + SFX leves),
cada uma com um conjunto **diferente de curiosidades** sobre os dois protagonistas de GTA 6.

## Vídeos gerados (`out/`)

| # | Arquivo | Duração | Tema |
|---|---------|---------|------|
| 1 | `GTA6_var_01_quem_e_lucia.mp4` | 52.8s | Quem é Lucia (primeira protagonista feminina, Liberty City, prisão…) |
| 2 | `GTA6_var_02_quem_e_jason.mp4` | 49.8s | Quem é Jason (exército, Keys, tráfico, palafita…) |
| 3 | `GTA6_var_03_bonnie_e_clyde.mp4` | 56.0s | A relação: Bonnie & Clyde modernos |
| 4 | `GTA6_var_04_dois_protagonistas.mp4` | 48.3s | Dois protagonistas jogáveis (troca de personagem) |
| 5 | `GTA6_var_05_passado_sombrio.mp4` | 50.8s | O passado sombrio dos dois |
| 6 | `GTA6_var_06_leonida_vice_city.mp4` | 49.0s | Cenário: Leonida & Vice City |
| 7 | `GTA6_var_07_recordes_bastidores.mp4` | 54.2s | Recordes e bastidores (trailer, lançamento 19/11/2026) |
| 8 | `GTA6_var_08_detalhes_escondidos.mp4` | 42.9s | Detalhes que quase ninguém notou |

## Como regenerar

```bash
# 1) narração TTS (feita via generate_speech, salva em render/var/<slug>/narr.mp3)
# 2) montagem
python generate_variations.py            # todas as 8
python generate_variations.py quem_e_lucia  # só uma
```

- `variations.py` — conteúdo (narração, legendas, títulos, imagens) das 8 variações.
- `generate_variations.py` — pipeline (Ken Burns + overlays + áudio sem música + montagem).
- `images/user/` — imagens-fonte; `render/images_analysis.json` — análise facial p/ foco dos cortes.

## Fonte dos fatos

Curiosidades baseadas na descrição oficial da Rockstar, trailers 1 e 2 e cobertura
especializada (fandom/wiki GTA, GTA Boom, Screen Rant, etc.), com data de referência
de 24/08/2026. Itens especulativos estão marcados como tal (ex.: "segundo análises do trailer").
