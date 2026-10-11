# STEMS4U by Piradex — Arquitetura técnica

Versão 0.1 (Fase 1) · Outubro 2026

Este documento responde aos pontos 1 a 11 das instruções de desenvolvimento antes do código, e regista o que já foi implementado na Fase 1. Onde uma funcionalidade pedida não é fiável com a tecnologia actual, está escrito porquê e qual é a alternativa realista.

---

## 0. Decisões principais

| Decisão | Escolha | Porquê |
|---|---|---|
| Motor de IA | Python + PyTorch, com camada de backends (Demucs, Roformer/MDX via audio-separator, ONNX no futuro) | Todos os modelos de topo (HTDemucs, BS/MelBand-Roformer, SCNet, MDX23C) são publicados em PyTorch. Reescrever em C++ agora custaria meses sem ganho de qualidade. |
| App desktop | Janela nativa via pywebview (WKWebView no macOS, WebView2 no Windows) + motor no mesmo processo | Corre no teu MacBook Pro 2013 com Catalina (Electron e Tauri recentes já não suportam bem 10.15), não exige Rust, e a mesma interface serve a versão web. |
| Interface | Um único `ui/index.html` em JavaScript puro, sem build | O teu estilo de trabalho; o mesmo ficheiro corre na app desktop e no GitHub Pages. |
| Reprodução | Web Audio: um só `AudioContext` (um relógio), fontes arrancadas no mesmo instante, ganhos com rampas | Sincronização à amostra, mute/solo/volume/pan sem parar a reprodução. |
| Versão web | HTDemucs em ONNX (MIT) no browser com WebGPU/WASM | Separa 4 stems sem servidor e sem upload. As funções avançadas ficam na app desktop. |
| Modelos | Descarregados pelo Gestor de Modelos, nunca no instalador | Instalador pequeno, licenças controladas por modelo, actualizações independentes. |
| Licenças | Manifesto com licença do código ≠ licença dos pesos, SHA-256, verificador fail-closed | Uma build pública não pode incluir pesos com licença ambígua. |

---

## 1. Análise dos requisitos: o que é executável hoje e o que é experimental

**Legenda:** ✅ fiável com tecnologia actual · 🧪 experimental (funciona, qualidade variável) · ⛔ não fiável hoje (alternativa proposta)

### Separação

| Requisito | Estado | Notas |
|---|---|---|
| Voz / Bateria / Baixo / Other | ✅ | HTDemucs v4 (MIT). Roformers dão mais ~1–3 dB de SDR na voz mas a licença dos pesos tem de ser confirmada. |
| Guitarra, Piano | 🧪 | `htdemucs_6s` (MIT): guitarra razoável, piano com bleeding (os próprios autores avisam). BS-RoFormer SW (6 stems) é melhor, licença por confirmar. |
| Voz principal vs coros | ✅ (licença 🧪) | MelBand Roformer Karaoke é a referência; pesos sem licença declarada → só build de desenvolvimento por agora. |
| Bombo, Tarola, Toms, Pratos | ✅/🧪 | DrumSep (4 peças) aplicado à pista de bateria. Bombo e tarola bons (SDR ≈14 e ≈8 dB), toms e pratos com bleeding (≈5–6 dB). |
| Hi-hat separado dos pratos, ride/crash | 🧪 | Modelos MDX23C/SCNet de 5–6 peças existem; pesos com licença não documentada. |
| Clap separado de snare | ⛔ | Nenhum modelo público faz isto bem. Fica em Tarola. |
| Kick layer 2, 808 vs baixo, sub-bass | ⛔ | Não são fontes acusticamente distintas para os modelos actuais. **Alternativa:** divisão por banda com fase linear dentro do stem de baixo (Sub < 60 Hz / Corpo) — soma exacta, honesta quanto ao que é. Fase 3. |
| Synth, Pads, Cordas, Metais, Sopros | ⛔ (aberto) | Há modelos comunitários (MVSep) mas sem pesos com licença clara. **Alternativas:** licenciar comercialmente (AudioShake, Music.AI/Moises e semelhantes oferecem SDK/API) ou treinar modelos próprios. |
| Percussão africana (congas, djembé, talking drum, shakers…) | ⛔ hoje, prioridade | Nenhum dataset aberto cobre estes instrumentos. Plano na secção 9: dataset próprio a partir dos teus multitracks (Kuduro, Afro House, Kizomba). |
| Guitarra L/R, Coros L/R | 🧪 | Possível com separação por azimute (máscaras de panorama sobre o stem) quando as fontes estão panoramizadas. Fase 3. |
| Ad-libs, sussurros, coro | ⛔ | Sem modelo. Ficam na voz principal ou nos coros. |
| Reverb / ambiência vocal | 🧪 | De-reverb Roformer (voz). Exporta "Voz principal (seca)" + "Reverb vocal" em par complementar. Reverb global: experimental. |
| Ruído | 🧪 | De-noise Roformer. |

### Análise e qualidade

| Requisito | Estado | Implementação |
|---|---|---|
| Deteção de instrumentos com % | 🧪 | **Hoje:** "presença" medida depois da separação (energia do stem relativa à mistura); stems abaixo de −50 dB não são exportados e o relatório diz porquê. **Fase 3:** classificador AudioSet (ex.: PANNs CNN14, código MIT — confirmar pesos) por janelas de 1 s, antes da separação. As percentagens de um classificador são probabilidades de presença, não de qualidade. |
| Confidence score por stem | 🧪 | Não existe métrica de confiança calibrada sem a fonte verdadeira. **Alternativa realista (Fase 3/4):** concordância entre dois modelos diferentes (SI-SDR entre as duas estimativas) + presença + bleeding estimado → índice 0–100 calibrado contra o benchmark. Mostrado como "fiabilidade estimada". |
| Bleeding por stem | 🧪 | Sem referência só se pode estimar (coerência espectral entre stems). Com referência (benchmark) é medido com exactidão. |
| Reconstruction accuracy | ✅ | Duas métricas: soma das saídas do modelo vs mistura (mede o modelo) e reconstrução final com Other (exacta por construção, verifica sincronização e exportação). |
| Peak, True Peak, RMS, LUFS, Crest, DR, Largura, Correlação, Centróide | ✅ | `metrics.py` (BS.1770-4, filtro K com coeficientes da norma, true peak 4x). |
| Fundamental estimada, BPM, tonalidade, compasso | ✅/🧪 | Fase 3 (pYIN para f0; BPM e tonalidade com algoritmos clássicos; compasso é experimental). |
| Cleanup: de-bleed, transient recovery, phase repair | 🧪 | Fase 4. De-bleed por máscara de Wiener entre stems com quantidade regulável; transient recovery por comparação da envolvente de ataques do stem com a da mistura na mesma banda, com ganho limitado; nunca destrutivo (sempre um stem novo, o original fica). "Phase repair" e "HF/LF reconstruction" sem referência são, na prática, geração de conteúdo: só como opção explícita. |
| Ensemble | ✅ | Fase 4: média ponderada no domínio do tempo (preserva fase), pesos por banda com crossovers de fase linear, e selecção por stem (o melhor modelo por stem segundo o benchmark). Máscaras min/max espectrais como opção. |

### Produto

| Requisito | Estado | Fase |
|---|---|---|
| Import WAV/AIFF/FLAC/MP3/AAC/M4A, metadados | ✅ | 1 (M4A/AAC: CoreAudio no macOS, ffmpeg LGPL no Windows) |
| Player multipista: play, pausa, stop, loop, seek, zoom, mute, solo, volume, pan | ✅ | 1 |
| Sincronização à amostra, mesma duração, mesma taxa | ✅ | 1 (testado) |
| Export WAV 16/24/32f, AIFF, FLAC, nomes organizados | ✅ | 1 · MP3 na Fase 5 (encoder LGPL) |
| Reamostragem de exportação 44,1–192 kHz | ✅ | 5 (hoje exporta à taxa original da mistura) |
| Pré-escuta 10/30/60 s | ✅ | 1 |
| Cache de separações | ✅ | 1 (por hash do áudio + modelo + versão + qualidade) |
| Fila / lote | ✅ motor, CLI | 1 (UI de fila na Fase 2) |
| Deteção de hardware e recomendação | ✅ | 1 |
| Modos Rápido / Equilibrado / Alta / Ultra | ✅ | 1 · Ensemble na Fase 4 |
| Gestor de modelos (instalar, remover, versão, tamanho, hardware, licença) | ✅ | 1 |
| Projecto `.s4u` | ✅ | 1 (gravado com cada separação; abrir projecto) |
| CLI | ✅ | 1 |
| API interna | ✅ | 1 (HTTP local + SSE, com token) |
| Grupos de stems | ✅ parcial | Hierarquia pai/filho já existe; grupos personalizados na Fase 5 |
| Comparação A/B de modelos | ✅ | 4 (o motor já guarda cada separação em cache por modelo) |
| Espectrograma | ✅ | 3 |
| Cloud opcional, plugin DAW, mobile | Preparado | A API e os backends são o ponto de extensão |

---

## 2. Modelos recomendados

Recomendação por tarefa, separando sempre **licença do código** e **licença dos pesos**. "Verificada" significa que pode ir numa build comercial.

| Tarefa | Modelo base (já integrado) | Licença dos pesos | Melhor qualidade disponível | Licença dos pesos |
|---|---|---|---|---|
| 4 stems | HTDemucs v4 / HTDemucs FT (Meta) | MIT ✅ | BS-RoFormer / SCNet XL (comunidade MVSep / ZFTurbo) | a confirmar |
| Voz / instrumental | HTDemucs FT | MIT ✅ | BS-Roformer Viperx 1297, MelBand Roformer Kim / becruily | a confirmar |
| Voz principal / coros | — | — | MelBand Roformer Karaoke (aufr33 & viperx) | a confirmar |
| Guitarra, piano | HTDemucs 6s | MIT ✅ | BS-RoFormer SW (6 stems) | a confirmar |
| Peças de bateria | DrumSep 4 peças (inagoy, HDemucs) | MIT segundo a model card da conversão; confirmar no original | MDX23C DrumSep 6 peças (aufr33 & jarredou), SCNet XL drums | não documentada |
| De-reverb / de-noise | — | — | MelBand Roformer (anvuew / aufr33) | a confirmar |
| Browser | HTDemucs ONNX (conversões MIT dos pesos oficiais) | MIT ✅ | — | — |
| A evitar | LarsNet / LARS (bateria 5 peças) | **CC BY-NC 4.0** ⛔ comercial | | |

**Como resolver as licenças "a confirmar":** pedir autorização escrita aos autores (muitos aceitam com atribuição), ou treinar versões próprias com o código MIT do ZFTurbo (Music-Source-Separation-Training) sobre dados licenciados. Até lá, esses modelos funcionam na build de desenvolvimento e o verificador impede-os na build pública.

Não escolher pela popularidade: `tools/benchmark.py` compara SDR, SI-SDR, bleeding, transientes, tempo e RAM em músicas tuas, por género.

---

## 3. Stack tecnológica

| Camada | Tecnologia |
|---|---|
| Linguagem do motor | Python 3.11 |
| Inferência | PyTorch (2.2.2 no Mac Intel, que é a última versão com builds para Intel; actual no Windows e Apple Silicon). CUDA no Windows com NVIDIA, Metal (MPS) no Apple Silicon, CPU em todo o lado. ONNX Runtime previsto como backend alternativo (DirectML no Windows sem NVIDIA). |
| DSP | NumPy, SciPy (reamostragem polifásica, filtros), libsndfile (soundfile) |
| Descodificação AAC/M4A | `afconvert` (CoreAudio, já existe no macOS) · ffmpeg LGPL no Windows |
| Interface | HTML/CSS/JS puro num ficheiro, Web Audio API |
| Janela desktop | pywebview (WKWebView / WebView2) |
| Empacotamento | PyInstaller, compilado em GitHub Actions (macOS Intel, macOS Apple Silicon, Windows) |
| Web | GitHub Pages + onnxruntime-web + demucs-web (MIT) |
| Testes | pytest; teste real com HTDemucs em CI |

**Mac Intel / Catalina:** o pacote para Intel é compilado com Python do python.org (binários para 10.9+), `MACOSX_DEPLOYMENT_TARGET=10.15`, e o CI falha se algum binário exigir macOS mais recente (`packaging/check_macos_min.sh`). Num i7 de 2013 sem GPU utilizável, conta com cerca de 1× o tempo da música no modo Equilibrado e 4× em Alta (estimativa; mede com o benchmark). Roformers em CPU são muito lentos (dezenas de minutos por música).

---

## 4. Arquitetura da aplicação

```
┌─────────────────────────── ui/index.html (JS puro) ───────────────────────────┐
│  Selector de stems · Qualidade · Pasta · Progresso · Mixer Web Audio · Export │
└───────────────┬────────────────────────────────────────────┬──────────────────┘
                │ HTTP local 127.0.0.1 + token + SSE         │ modo web
┌───────────────▼─────────────── server.py (API) ──────────┐  ┌────▼────────────────┐
│ /api/info /probe /upload /jobs /events /file /save ...   │  │ HTDemucs ONNX        │
└───────────────┬──────────────────────────────────────────┘  │ WebGPU / WASM        │
┌───────────────▼────── jobs.py (fila, 1 worker, cancelar) ┐  └─────────────────────┘
┌───────────────▼────── pipeline.py ───────────────────────────────────────────────┐
│ import → plano de modelos → separação por estágios → reconstrução (Other)        │
│ → presença → métricas → export → projecto .s4u + relatório                      │
└──────┬──────────────┬───────────────┬──────────────┬───────────────┬────────────┘
  audio_io.py    chunking.py     models/registry.py  models/backends.py  metrics.py
 (import/export) (blocos+overlap) (manifesto,licenças, (Demucs, Roformer,  (LUFS, TP,
                                  hashes, instalação)  futuro ONNX/cloud)   reconstrução)
                         hardware.py · config.py (pastas, logs, erros legíveis)
```

**Mapa dos módulos pedidos → código:**

| Módulo pedido | Ficheiro | Estado |
|---|---|---|
| Audio Import Engine | `audio_io.py` | ✅ |
| Audio Analysis Engine / Audio Metrics Engine | `metrics.py` | ✅ |
| Instrument Detection Engine | `detect.py` | Fase 3 |
| Separation Engine | `pipeline.py` + `models/backends.py` | ✅ |
| Model Manager | `models/registry.py` + `manifest.json` | ✅ |
| Ensemble Engine | `ensemble.py` | Fase 4 |
| Stem Reconstruction Engine | `pipeline.py` (Other, presença, reconstrução) | ✅ |
| Artifact Cleanup Engine | `cleanup.py` | Fase 4 |
| Waveform / Spectrogram Engine | `ui/index.html` (waveform) · espectrograma | ✅ / Fase 3 |
| Playback Engine | `ui/index.html` (Web Audio) | ✅ |
| Export Engine | `audio_io.write` + export de mistura offline na UI | ✅ |
| Project Manager | `.s4u` em `pipeline.py`, abrir em `server.py` | ✅ básico |
| Hardware Detection Engine | `hardware.py` | ✅ |
| Queue Manager | `jobs.py` | ✅ |

**Planeamento de modelos (o utilizador não vê dependências):** cada modelo declara a entrada (`mistura` ou um stem) e as saídas. O planeador resolve as cadeias: pedir "Bombo" corre HTDemucs → Bateria → DrumSep; pedir "Voz principal" corre HTDemucs → Voz → Karaoke. Escolhe o modelo base mais especializado que cubra tudo o que é preciso (só usa o de 6 stems se pedires guitarra ou piano) e respeita o modo de qualidade.

**Lógica de Other:** `Other = mistura − Σ(folhas)`, em que folha é um stem seleccionado sem descendentes seleccionados. Pais exportados com filhos começam em mute. A soma das pistas audíveis por defeito reconstrói a mistura; o resíduo de cada modelo filho (o que o DrumSep não atribuiu a nenhuma peça) cai em Other em vez de desaparecer.

---

## 5. Estrutura de pastas

```
stems4u/
├─ ARQUITETURA.md            este documento
├─ README.md                 instalar, correr, compilar, publicar
├─ THIRD_PARTY_NOTICES.md    atribuições e licenças
├─ pyproject.toml · requirements.txt · requirements-macos-intel.txt
├─ stems4u/                  motor (pacote Python)
│  ├─ __init__.py  __main__.py  cli.py  desktop.py  server.py  jobs.py
│  ├─ pipeline.py  stems.py  audio_io.py  chunking.py  metrics.py
│  ├─ hardware.py  config.py
│  └─ models/  manifest.json  registry.py  backends.py
├─ ui/index.html             interface (desktop e web)
├─ tests/                    testes do motor, da API e do modelo real
├─ tools/                    benchmark.py, pin_models.py
├─ packaging/                PyInstaller (spec, launcher), verificador macOS 10.15
└─ .github/workflows/        build.yml (testes + 3 builds), pages.yml (versão web)
```

Dados do utilizador (nunca dentro da app instalada): `~/Library/Application Support/STEMS4U` (modelos, logs, projectos) e `~/Library/Caches/STEMS4U` no macOS; `%LOCALAPPDATA%\STEMS4U` no Windows.

---

## 6. Comunicação UI ↔ motor

- O motor abre um servidor HTTP em `127.0.0.1` numa porta aleatória e gera um token por sessão. A janela abre `http://127.0.0.1:PORTA/?t=TOKEN`; todas as rotas `/api` exigem esse token (outras páginas do browser não conseguem usar o motor).
- Pedidos curtos são JSON. Ficheiros grandes (upload da mistura arrastada, gravação da mistura exportada) vão em binário.
- O progresso chega por **Server-Sent Events** (`/api/jobs/{id}/events`): etapa, percentagem real (por bloco processado), modelo, tempo decorrido. O evento final traz o resultado completo.
- A separação corre numa thread de trabalho: a interface nunca bloqueia. Cancelar marca uma flag que o motor verifica entre blocos (cancelamento seguro, sem ficheiros a meio).
- Erros chegam como `{code, message, hint}` em português; o detalhe técnico vai para `logs/stems4u.log`.
- A mesma API serve, no futuro, a versão cloud, um plugin JUCE (que pode chamar a CLI ou a API) e um cliente móvel.

---

## 7. Pipeline de processamento

1. **Import:** `probe` (formato, taxa, bits, canais, duração, título/artista/álbum) e descodificação para float32. Mono passa a dual-mono. O original nunca é tocado.
2. **Pré-escuta (opcional):** excerto de 10/30/60 s a partir de 30 % da música.
3. **Plano:** escolha de modelos e cadeia de dependências (secção 4).
4. **Conversão para 44,1 kHz** com filtro polifásico de fase linear (sem deslocamento temporal).
5. **Separação por estágios**, em blocos de 30 s com 3 s de sobreposição (janelas sin²/cos², soma exacta = 1). Cada estágio consulta primeiro a cache.
6. **Volta à taxa original** (48/88,2/96/192 kHz). O conteúdo acima de 22 kHz que os modelos não vêem fica automaticamente em Other, porque Other é calculado contra a mistura original.
7. **Presença:** stems sem conteúdo audível (< −50 dB relativamente à mistura) não são exportados e ficam em Other.
8. **Other** e métricas de reconstrução.
9. **Métricas por stem** e **exportação** sem normalização (dither TPDF em 16 bits; aviso se houver pico acima de 0 dBFS em formato inteiro, com sugestão de 32-bit float).
10. **Projecto `.s4u` + `relatorio.json`** (modelos, licenças, plano, métricas, avisos, tempo).

Nomes: `01_Música_Vocals.wav`, `02_Música_Drums.wav`, … — o número mantém a ordem ao importar na DAW.

---

## 8. GPU, CPU, RAM e cache

- **Deteção:** sistema, arquitectura, CPU e threads, RAM, PyTorch, CUDA (nome e VRAM) ou Metal.
- **Recomendação:** NVIDIA ≥ 8 GB → Ultra; GPU menor ou Apple Silicon → Alta; CPU com ≥ 12 GB e ≥ 8 threads → Equilibrado; resto → Rápido. Cada modelo declara RAM, VRAM e velocidade relativa no manifesto.
- **Memória:** um modelo carregado de cada vez; blocos de 30 s limitam a memória de inferência; um só trabalho de IA de cada vez (a fila serializa). "VRAM insuficiente" é apanhado e explicado.
- **Cache:** `Caches/STEMS4U/separations/<hash>.npz`, chave = SHA-256 do áudio a 44,1 kHz + estágio + modelo + versão + qualidade. Mudar só os stems seleccionados ou o formato não repete a IA.
- **Fase 6:** streaming de ficheiros muito longos (sets de DJ) directamente do disco, limpeza automática da cache por tamanho.

---

## 9. Prioridade para música africana

Os datasets públicos (MUSDB18, MoisesDB) são sobretudo pop/rock ocidental; nenhum modelo aberto separa congas, djembé, talking drum, cowbell ou shakers. Plano:

1. **Medir primeiro:** pastas de benchmark por género (Kuduro, Afro House, Afrobeats, Kizomba, Semba…) com stems reais das tuas sessões e da Music AO (com autorização dos artistas). O benchmark já lê o género do nome da pasta.
2. **Dataset próprio:** multitracks → stems de referência por família de percussão. Aumento de dados por remistura aleatória de stems (técnica padrão de treino).
3. **Treino:** fine-tune de um modelo de bateria (MDX23C ou SCNet com o código MIT do ZFTurbo) com uma classe "percussão" e depois subclasses. Pesos teus = licença tua.
4. Até lá: a percussão fica em Bateria ou Other e a interface di-lo explicitamente.

---

## 10. Testes e benchmark

**Já implementado (21 testes a passar):**
- Chunking: reconstrução exacta de um sinal com qualquer duração; ausência de degraus de volume nas junções; rampas complementares.
- LUFS contra a referência EBU (−23 LUFS a 44,1/48/96 kHz, ±0,1); true peak inter-amostra; métrica de reconstrução.
- Planeador: escolha do modelo especializado, cadeias de dependências, recusa quando falta modelo, verificador de licenças fail-closed.
- Pipeline completo: "só voz" dá Voz + Other complementar; bateria detalhada com pai em mute e sem duplicação; alinhamento à amostra (correlação máxima no atraso 0); mesma duração e taxa (48 kHz de entrada, 48 kHz de saída); stems vazios não exportados; pré-escuta; 16 bits; cancelamento; aviso de clipping; float sem normalização.
- API: token obrigatório, trabalho completo por SSE, servir stems, bloqueio de ficheiros fora das pastas autorizadas.
- Backend Demucs validado com o modelo de teste do próprio Demucs (sem pesos).
- **Em CI:** separação real com HTDemucs (`tests/test_real_model.py`) e cálculo dos SHA-256 dos modelos.

Os testes de pipeline usam um separador-oráculo **só de teste**, que conhece as fontes de uma mistura sintética. Valida tudo à volta do modelo; a qualidade dos modelos mede-se com o benchmark.

**Benchmark (`tools/benchmark.py`):** SDR, SI-SDR, bleeding por fonte (projecção nas fontes verdadeiras), preservação de transientes, tempo, factor de tempo real, RAM máxima. CSV completo + resumo por género/modelo/qualidade. Formato MUSDB18-HQ.

**Testes manuais por género** (Afro House, House, Kuduro, Afrobeats, Hip-Hop, Trap, R&B, Pop, Rock, Jazz, Acústico, Orquestral, Electrónica): ouvir cada stem em solo, verificar ataques de bombo e tarola, sub do baixo, respirações e sibilantes na voz, imagem estéreo dos coros.

---

## 11. Fases

| Fase | Conteúdo | Estado |
|---|---|---|
| 1 | Motor de áudio, import, playback multipista, 4 stems + 6 stems + peças de bateria, export WAV/AIFF/FLAC, CLI, API, cache, gestor de modelos, deteção de hardware, fila (motor), pré-escuta, projecto `.s4u`, versão web | **Feito nesta entrega** |
| 2 | UI da fila/lote, Roformers (voz/karaoke) com licenças confirmadas, DirectML/ONNX, ffmpeg LGPL no instalador Windows | Seguinte |
| 3 | Deteção de instrumentos, fiabilidade estimada, espectrograma, BPM/tonalidade/f0, divisão por banda (sub/808), L/R por azimute | |
| 4 | Ensemble, A/B de modelos, de-bleed, transient recovery, análise de fase | |
| 5 | Grupos personalizados, MP3, reamostragem de exportação, definições, CLI avançada | |
| 6 | Optimização, UI final, benchmark por género, assinatura e notarização Apple, instalador Windows assinado | |

---

## 12. Distribuição e licenças

- O instalador não inclui modelos. O Gestor de Modelos descarrega de fontes oficiais, verifica SHA-256 e grava `PROVENANCE.json` ao lado de cada modelo.
- `STEMS4U_BUILD=public` activa a política fail-closed: só modelos com licença dos pesos verificada, redistribuição autorizada e SHA-256 fixado.
- A licença MIT do código de um repositório **não** cobre automaticamente os pesos treinados: o manifesto separa as duas.
- Para venda: assinatura Developer ID + notarização no macOS, certificado de assinatura no Windows. Sem isso, o macOS pede "Abrir" com botão direito na primeira vez.

## 13. Limitações desta versão (honestas)

- Os pesos reais não foram executados no ambiente onde este código foi escrito (sem acesso aos servidores dos modelos); o caminho de código do Demucs foi validado com o modelo de teste do Demucs e a separação real corre no CI do GitHub e no teu computador.
- Os SHA-256 completos dos modelos ainda estão por fixar (o CI calcula-os; `tools/pin_models.py --write` grava-os). Até lá a verificação usa o prefixo de hash que a própria Meta publica no nome de cada ficheiro.
- DrumSep e os Roformers precisam de confirmação de licença antes de uma build comercial.
- No modo web: 44,1 kHz e 4 stems; a exportação da mistura funciona no GitHub Pages (a pré-visualização do Claude não permite descargas).
