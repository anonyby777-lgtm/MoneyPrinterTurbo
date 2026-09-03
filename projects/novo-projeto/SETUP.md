# 🔗 Como gerar o seu link de envio de vídeos (GitHub)

Este guia transforma "me manda uns vídeos" em **um link** que você (ou qualquer
colaborador) abre, arrasta os vídeos e pronto — os arquivos entram no projeto.

Como o GitHub hospeda os anexos de issue, o link funciona assim:

```
https://github.com/<USUÁRIO>/<REPO>/issues/new?template=enviar-videos.yml
```

ou, para quem já tem a issue aberta, o link dos próprios vídeos:

```
https://github.com/user-attachments/assets/<uuid>
```

---

## Caminho A — repositório novo (recomendado)

### 1. Criar o repositório

- Vazio, só com README: <https://github.com/new>
- Ou já com a estrutura deste projeto:
  <https://github.com/new?owner=SEU-USUARIO> e depois copie os arquivos abaixo.

Issues já vêm **habilitadas** em repositório novo. Se não estiverem:
`Settings → General → Features → Issues ✅`.

### 2. Copiar 3 arquivos do MoneyPrinterTurbo para o repo novo

| Origem (aqui) | Destino (repo novo) |
| --- | --- |
| `tools/gh_issue_intake.py` | `tools/gh_issue_intake.py` |
| `projects/novo-projeto/intake/enviar-videos.yml` | `.github/ISSUE_TEMPLATE/enviar-videos.yml` |
| `projects/novo-projeto/intake/video-intake.yml` | `.github/workflows/video-intake.yml` |

```bash
git clone https://github.com/SEU-USUARIO/SEU-REPO.git && cd SEU-REPO
mkdir -p tools .github/ISSUE_TEMPLATE .github/workflows projects/novo-projeto/videos
cp /caminho/do/MoneyPrinterTurbo/tools/gh_issue_intake.py tools/
cp /caminho/do/MoneyPrinterTurbo/projects/novo-projeto/intake/enviar-videos.yml .github/ISSUE_TEMPLATE/
cp /caminho/do/MoneyPrinterTurbo/projects/novo-projeto/intake/video-intake.yml .github/workflows/
cp /caminho/do/MoneyPrinterTurbo/projects/novo-projeto/{README.md,manifest.json} projects/novo-projeto/
printf '*\n!.gitignore\n' > projects/novo-projeto/videos/.gitignore
git add -A && git commit -m "chore: estrutura de recebimento de vídeos via issue" && git push
```

### 3. Ligar o Actions

`Settings → Actions → General → Workflow permissions →`
**Read and write permissions** ✅ (necessário para o workflow commitar os vídeos).

### 4. O link 🎉

```
https://github.com/SEU-USUARIO/SEU-REPO/issues/new?template=enviar-videos.yml
```

Abra, arraste os vídeos, **Submit new issue**. Em ~1 minuto o workflow baixa tudo,
commita em `projects/novo-projeto/videos/`, atualiza o `manifest.json` e comenta
na issue o que entrou.

---

## Caminho B — usar o fork que já existe

Repositório: <https://github.com/anonyby777-lgtm/MoneyPrinterTurbo>
(branch desta sessão: `arena/01a068c5-moneyprinterturbo`)

Ele é um **fork com Issues desabilitadas**, e o bot desta sessão não tem permissão
de administração para religá-las. Você faz em 4 cliques:

1. <https://github.com/anonyby777-lgtm/MoneyPrinterTurbo/settings> → *Features* → **Issues ✅** → *Save changes*
2. <https://github.com/anonyby777-lgtm/MoneyPrinterTurbo/settings/actions> → *Workflow permissions* → **Read and write permissions** → *Save*
3. Merge desta branch para `main` (o workflow só executa a partir da branch padrão):
   <https://github.com/anonyby777-lgtm/MoneyPrinterTurbo/compare/main...arena/01a068c5-moneyprinterturbo>
4. Link de envio:
   <https://github.com/anonyby777-lgtm/MoneyPrinterTurbo/issues/new?template=enviar-videos.yml>

O modelo de issue já foi adicionado em `.github/ISSUE_TEMPLATE/enviar-videos.yml`.
O workflow **não** foi colocado em `.github/workflows/` aqui de propósito: ele
passaria a rodar no fork inteiro (inclusive nos eventos herdados do upstream).
Copie `projects/novo-projeto/intake/video-intake.yml` para lá se quiser ativar.

---

## Rodar manualmente (sem Actions)

Na sua máquina — não em sandbox com rede filtrada, porque os anexos ficam em
`github-production-user-asset-*.s3.amazonaws.com`:

```bash
# lista o que a issue tem anexado
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/1 --dry-run

# baixa para projects/novo-projeto/videos/ e atualiza o manifest
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/1

# idem + commit e push na branch atual
python3 tools/gh_issue_intake.py https://github.com/SEU-USUARIO/SEU-REPO/issues/1 --push

# repo privado
export GH_TOKEN=ghp_xxx        # scope: repo (clássico) ou Contents:Read/Issues:Read (fine-grained)
python3 tools/gh_issue_intake.py SEU-USUARIO/SEU-REPO#1
```

Requisitos: Python 3.11+ (só biblioteca padrão) e `git` no PATH para `--push`.

---

## Limites que definem qual link usar

| Situação | Melhor destino | Limite |
| --- | --- | --- |
| Vídeo ≤ 10 MB | anexar na issue (link acima) | 10 MB por vídeo em conta Free |
| Vídeo ≤ 100 MB | issue em conta paga, ou zip ≤ 25 MB com `--unzip` | 100 MB / 25 MB |
| Vídeo grande (até 2 GB) | **Release** do repositório | 2 GB por asset |
| Muitos vídeos de uma vez | pasta sincronizada (Drive/Dropbox) + `rsync` | — |

Para Release: <https://github.com/SEU-USUARIO/SEU-REPO/releases/new> — crie a
release, anexe os vídeos e me mande a URL; eu baixo com
`curl -L <url-do-asset> -o projects/novo-projeto/videos/<nome>`.

---

## Checklist rápido

- [ ] Repositório criado e com Issues habilitadas
- [ ] `tools/gh_issue_intake.py` copiado
- [ ] `.github/ISSUE_TEMPLATE/enviar-videos.yml` copiado
- [ ] `.github/workflows/video-intake.yml` copiado (opcional, mas recomendado)
- [ ] Actions com permissão de escrita
- [ ] Link de envio testado com um vídeo pequeno
