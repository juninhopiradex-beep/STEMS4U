# Avisos de terceiros — STEMS4U by Piradex

O código do STEMS4U é © Ricardo Amorim (Piradex). Os componentes abaixo pertencem aos respectivos autores.
Os modelos NÃO vêm no instalador; cada modelo instalado tem um `PROVENANCE.json` com versão, hash e licença.

## Modelos de IA

| Modelo | Autores | Licença do código | Licença dos pesos | Estado |
|---|---|---|---|---|
| HTDemucs v4, HTDemucs FT, HTDemucs 6s | Simon Rouard, Francisco Massa, Alexandre Défossez — Meta AI | MIT | MIT | Verificada — https://github.com/facebookresearch/demucs |
| HTDemucs ONNX (versão web) | Conversão dos pesos oficiais (demucs-web, timcsy) | MIT | MIT | Verificada |
| DrumSep 6 peças (MDX23C) | aufr33, jarredou (pesos); KUIELab e ZFTurbo (arquitectura); openmirlab/mdxnet-infer (código de inferência, copiado em `stems4u/models/mdx23c/`) | MIT | Não documentada formalmente | Uso pessoal / build de desenvolvimento |
| DrumSep | inagoy | MIT | MIT segundo a model card da conversão ONNX | A confirmar no repositório original |
| MelBand Roformer Karaoke | aufr33, viperx | MIT (Music-Source-Separation-Training, ZFTurbo) | Não declarada | Só build de desenvolvimento |
| MelBand Roformer De-Reverb | anvuew | MIT | Não declarada | Só build de desenvolvimento |
| MelBand Roformer De-Noise | aufr33 | MIT | Não declarada | Só build de desenvolvimento |

## Bibliotecas

| Componente | Licença |
|---|---|
| Python | PSF License |
| PyTorch, torchaudio | BSD-3-Clause |
| Demucs (código) | MIT |
| Open-Unmix (filtro de Wiener usado pelo Demucs) | MIT |
| dora-search, einops, julius | MIT |
| NumPy, SciPy | BSD-3-Clause |
| soundfile | BSD-3-Clause · libsndfile LGPL-2.1 (biblioteca dinâmica, substituível) |
| pywebview | BSD-3-Clause |
| PyYAML, tqdm | MIT / MPL-2.0+MIT |
| PyInstaller (bootloader) | GPL-2.0 com excepção que permite distribuir apps comerciais |
| onnxruntime-web | MIT |
| demucs-web | MIT |
| ffmpeg (Windows, Fase 2) | Build LGPL, ligação dinâmica |

## LGPL

libsndfile (e futuramente ffmpeg) são distribuídos como bibliotecas dinâmicas separadas. Podes substituí-las por outra versão compatível colocando o ficheiro com o mesmo nome dentro da pasta da aplicação (`_internal` no Windows, `Contents/Frameworks` no macOS). O código-fonte destas bibliotecas está em https://github.com/libsndfile/libsndfile e https://ffmpeg.org.

Na Fase 6 este ficheiro passa a ser gerado automaticamente a partir do conteúdo real da build (com SBOM CycloneDX).
