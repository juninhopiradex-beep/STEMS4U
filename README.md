# STEMS4U by Piradex

Separador profissional de stems para macOS (Intel e Apple Silicon), Windows e browser.
Separa voz, bateria (bombo, tarola, toms, pratos), baixo, guitarra, piano e Other, com mixer multipista sincronizado à amostra, sem enviar a música para lado nenhum.

A arquitetura completa, o que já funciona e o que é experimental estão em **[ARQUITETURA.md](ARQUITETURA.md)**.

## Começar no Mac (Intel, incluindo Catalina 10.15)

1. Instala o **Python 3.11.9** do python.org (instalador "macOS 64-bit universal2").
2. No Terminal, dentro desta pasta:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-macos-intel.txt
   pip install demucs==4.0.1 --no-deps
   python -m stems4u app
   ```
3. Na primeira abertura, carrega em **Instalar modelos base** (≈135 MB, licença MIT). Ficam em `~/Library/Application Support/STEMS4U/models`.

Apple Silicon e Windows: igual, mas com `requirements.txt` (no Windows usa `py -3.11` e `.venv\Scripts\activate`).

## Peças de bateria (bombo, tarola, toms, pratos)

O modelo DrumSep instala-se manualmente enquanto a licença dos pesos não estiver confirmada:
```bash
python -m stems4u models import drumsep_inagoy /caminho/para/49469ca8.th
```
O ficheiro vem do repositório https://github.com/inagoy/drumsep.

## Linha de comandos

```bash
python -m stems4u info                                   # hardware e stems disponíveis
python -m stems4u models list                            # modelos, licenças, estado
python -m stems4u models install htdemucs_ft             # alta qualidade
python -m stems4u separate musica.wav --stems vocals,kick,snare,bass --quality high --out ~/Stems
python -m stems4u separate *.wav --stems vocals --out ~/Stems           # lote
python -m stems4u separate musica.wav --stems vocals --preview 30 --out ~/Stems
python -m stems4u separate musica.wav --stems kick,lead_vocal --dry-run --out .   # ver o plano de modelos
```
Ids de stems: `vocals lead_vocal backing_vocals vocal_reverb drums kick snare toms cymbals bass guitar piano noise`.

## Testes e benchmark

```bash
pip install pytest
pytest -q                                   # motor, pipeline, API (sem modelos)
STEMS4U_REAL=1 pytest -s tests/test_real_model.py   # com o HTDemucs real
python tools/benchmark.py bench/ --models htdemucs,htdemucs_ft --quality balanced,high
```

## Publicar no GitHub e obter os instaladores

1. Cria o repositório e envia **todos** os ficheiros (são menos de 100, cabem num só upload pelo browser).
   No Finder carrega **Cmd + Shift + .** para veres a pasta escondida `.github` — ela tem de ir também, é a que compila as apps.
2. Em **Actions**, o workflow *Build STEMS4U* compila automaticamente:
   `STEMS4U-macOS-Intel.zip` (verificado para Catalina 10.15), `STEMS4U-macOS-AppleSilicon.zip`, `STEMS4U-Windows.zip`.
   Descarrega-os em Actions → última execução → *Artifacts*.
3. Versão web: o `index.html` da raiz é a app (cópia de `ui/index.html` com o cabeçalho HTML). Em **Settings → Pages** basta *Deploy from a branch → main → / (root)*. Sempre que mudares `ui/index.html`, copia-o também para a raiz.
4. Depois do primeiro build, copia os SHA-256 que aparecem no resumo do job *real-model* para o manifesto (ou corre `python tools/pin_models.py --write`). A partir daí, o verificador da build pública passa a verde.

As apps não estão assinadas nem notarizadas: no Mac abre a primeira vez com botão direito → Abrir.

## Onde ficam os dados

| | macOS | Windows |
|---|---|---|
| Modelos, logs, projectos | `~/Library/Application Support/STEMS4U` | `%LOCALAPPDATA%\STEMS4U\Data` |
| Cache de separações | `~/Library/Caches/STEMS4U` | `%LOCALAPPDATA%\STEMS4U\Cache` |

© Ricardo Amorim (Piradex). Componentes de terceiros: ver [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
