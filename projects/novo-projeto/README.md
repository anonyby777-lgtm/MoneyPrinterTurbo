# 📥 Novo projeto — entrada de vídeos

Pasta criada para receber os vídeos que você vai enviar pelo **GitHub**, sem precisar
fazer `git push` de arquivos pesados.

> **Passo a passo completo (com os links prontos): [`SETUP.md`](SETUP.md)**
>
> Resumo do link que você vai usar:
> `https://github.com/SEU-USUARIO/SEU-REPO/issues/new?template=enviar-videos.yml`

## Estrutura da pasta

```
projects/novo-projeto/
├── README.md              ← este arquivo
├── SETUP.md               ← como gerar o link no SEU repositório (2 caminhos)
├── manifest.json          ← inventário dos vídeos recebidos (nome, tamanho, sha256, origem)
├── intake/
│   ├── ENVIAR-VIDEOS.md   ← instruções para colar na descrição da issue
│   ├── enviar-videos.yml  ← modelo de issue (→ .github/ISSUE_TEMPLATE/)
│   └── video-intake.yml   ← workflow do Actions que importa sozinho (→ .github/workflows/)
└── videos/                ← os vídeos baixados ficam aqui (ignorado pelo git por padrão)
```

## Como enviar os vídeos (3 passos)

1. **Crie o repositório novo** (ou use um existente) e garanta que as *Issues* estão ligadas
   — em repositórios novos elas já vêm ligadas; em *forks* é preciso ativar em
   `Settings → General → Features → Issues`.
2. **Abra a issue de coleta** com o formulário pronto:

   ```
   https://github.com/SEU-USUARIO/SEU-REPO/issues/new?template=enviar-videos.yml&title=Enviar+v%C3%ADdeos+%E2%80%94+novo-projeto
   ```

   (o arquivo `intake/enviar-videos.yml` deste projeto é o modelo dessa issue)
3. **Arraste os vídeos** para dentro da caixa de texto da issue e clique em **Comment**.
   O GitHub faz o upload e gera um link permanente do tipo
   `https://github.com/user-attachments/assets/...` — é esse o "link" que fica valendo.

Depois há duas formas de trazer os arquivos para o projeto:

**Automática (recomendada)** — copie `intake/video-intake.yml` para
`.github/workflows/` do repositório. Toda vez que alguém anexar vídeo na issue,
o workflow baixa, commita em `projects/novo-projeto/videos/`, atualiza o
`manifest.json` e comenta o resultado na própria issue. Requer
`Settings → Actions → Workflow permissions → Read and write permissions`.

**Manual** — de dentro do clone do repositório:

```bash
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/1            # baixa
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/1 --push     # baixa + commita
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/1 --dry-run  # só lista
```

O script usa apenas a biblioteca padrão do Python e grava em
`projects/novo-projeto/videos/`, atualizando o `manifest.json`.

> ⚠️ Rode o script **na sua máquina**, não dentro de sandbox/proxy com saída de rede
> filtrada: os anexos de issue redirecionam para
> `github-production-user-asset-*.s3.amazonaws.com`, que esses ambientes bloqueiam
> (o runner do GitHub Actions, não).

## Limites do GitHub que importam aqui

| Onde | Limite |
| --- | --- |
| Vídeo anexado em issue/PR — conta **Free** | **10 MB** por vídeo |
| Vídeo anexado em issue/PR — conta **paga** | 100 MB por vídeo |
| Qualquer outro arquivo em issue (ex.: `.zip`) | 25 MB |
| Upload pela interface web do repositório (*Add file → Upload files*) | 25 MB |
| `git push` de um arquivo | aviso em 50 MB, **bloqueio em 100 MB** |
| Asset de um *Release* | 2 GB |

**Vídeo maior que 10 MB?** Duas saídas que continuam sendo "via GitHub":

- Compacte em `.zip` (vídeo já comprimido quase não reduz, mas o limite do zip é 25 MB)
  e importe com `python3 tools/gh_issue_intake.py ... --unzip`.
- Anexe em um **Release** do repositório e me mande o link do release — eu puxo de lá.
- Ou re-encode o vídeo antes: `ffmpeg -i entrada.mov -c:v libx264 -crf 28 -preset slow -c:a aac -b:a 128k saida.mp4`

## Ligar estes vídeos ao MoneyPrinterTurbo

Quando os vídeos estiverem em `projects/novo-projeto/videos/`, copie (ou linke) para
`storage/local_videos/` e use o material local na WebUI/API:

```bash
mkdir -p storage/local_videos
cp projects/novo-projeto/videos/*.mp4 storage/local_videos/
```

A API também aceita upload direto, se preferir:

```bash
curl -F "file=@meu-video.mp4" http://127.0.0.1:8080/api/v1/video_materials
curl http://127.0.0.1:8080/api/v1/video_materials   # lista o que já está lá
```

## Observações

- `videos/` é ignorado pelo git neste projeto: vídeos pesados não devem viver no
  histórico. Se quiser versionar, remova a linha correspondente do `.gitignore` e
  use Git LFS (`git lfs track "*.mp4"`).
- `tools/gh_issue_intake.py` usa só a biblioteca padrão do Python 3.11+.
- Para repositório privado, exporte um token antes: `export GH_TOKEN=ghp_...`
  (o `GITHUB_TOKEN` do próprio Actions já basta para o modo automático).
- Com `--push`, os vídeos são adicionados com `git add -f` (o `.gitignore` de
  `videos/` é sobrescrito de propósito, porque você pediu para versionar).
  Arquivos acima de 90 MB são mantidos só no disco — o GitHub recusa push > 100 MB.
