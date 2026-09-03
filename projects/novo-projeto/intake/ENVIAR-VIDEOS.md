# 📤 Como me enviar os vídeos por esta issue

Arraste (ou cole) cada vídeo aqui embaixo e clique em **Comment**.
O GitHub hospeda o arquivo e gera um link permanente — é esse link que eu uso.

```
https://github.com/user-attachments/assets/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

## Regras do jogo (limites do GitHub)

- **Conta Free:** até **10 MB** por vídeo anexado em issue/PR.
- **Conta paga:** até 100 MB por vídeo.
- **Outros arquivos** (ex.: `.zip` com vídeos dentro): até **25 MB**.
- Anexos ficam **públicos** em repositório público: não envie material confidencial aqui.

## Se o vídeo passar do limite

1. Zipe e anexe o `.zip` (o limite sobe para 25 MB) — eu importo com
   `python3 tools/gh_issue_intake.py <link-da-issue> --unzip`.
2. Ou anexe num **Release** do repositório (até 2 GB por arquivo) e me passe o link.
3. Ou reduza antes:
   `ffmpeg -i entrada.mov -c:v libx264 -crf 28 -preset slow -c:a aac -b:a 128k saida.mp4`

## Para cada vídeo, se puder, informe

| Campo | Exemplo |
| --- | --- |
| Nome/ordem desejada | `01-abertura.mp4` |
| Uso no projeto | abertura / b-roll / depoimento / encerramento |
| Trecho aproveitado | 00:12 – 00:31 |
| Observações | sem áudio original, gravado na vertical, etc. |

Nomes com prefixo numérico (`01-`, `02-`, …) mantêm a ordem na concatenação
sequencial do MoneyPrinterTurbo.

## Depois de enviar

Rode no clone do repositório:

```bash
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/NUMERO
# e, se quiser já versionar o que couber no limite do git:
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/NUMERO --push
```

Os arquivos caem em `projects/novo-projeto/videos/` e o `manifest.json` é atualizado.
